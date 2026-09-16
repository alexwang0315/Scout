"""One bounded, read-only HTTP exchange over a fresh SSH stdio channel.

There is no local listening port, persistent tunnel or remote shell command.
The caller owns endpoint validation and JSON decoding; this module owns the
fixed SSH destination, HTTP framing and child-process lifetime.
"""

from __future__ import annotations

import http.client
import io
import os
import selectors
import subprocess
import time

MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_HEADER_BYTES = 64 * 1024
MAX_STDERR_BYTES = 8192
SSH_COMMAND = (
    "/usr/bin/ssh", "-T",
    "-o", "BatchMode=yes",
    "-o", "StrictHostKeyChecking=yes",
    "-o", "StdinNull=no",
    "-o", "RemoteCommand=none",
    "-o", "PermitLocalCommand=no",
    "-o", "ClearAllForwardings=yes",
    "-o", "ControlMaster=no",
    "-o", "ControlPath=none",
    "-o", "ForkAfterAuthentication=no",
    "-o", "ConnectionAttempts=1",
    "-o", "ConnectTimeout=4",
    "-o", "ServerAliveInterval=5",
    "-o", "ServerAliveCountMax=1",
    "-W", "127.0.0.1:9151", "scout",
)


class HardwareMonitorSSHError(RuntimeError):
    """Fixed error codes only; never expose SSH stderr or credential paths."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class _ResponseSocket:
    def __init__(self, raw: bytes):
        self.raw = raw

    def makefile(self, mode: str) -> io.BytesIO:
        return io.BytesIO(self.raw)


def _parse_response(raw: bytes) -> tuple[int, bytes]:
    header_end = raw.find(b"\r\n\r\n")
    if header_end < 0 or header_end > MAX_HEADER_BYTES:
        raise HardwareMonitorSSHError("invalid_response")
    try:
        with http.client.HTTPResponse(_ResponseSocket(raw)) as response:
            response.begin()
            if 300 <= response.status < 400:
                raise HardwareMonitorSSHError("redirect_refused")
            if response.getheader("Content-Type", "").split(";", 1)[0].strip() != "application/json":
                raise HardwareMonitorSSHError("invalid_response")
            length = response.length
            if length is not None and length > MAX_BODY_BYTES:
                raise HardwareMonitorSSHError("response_too_large")
            body = response.read(MAX_BODY_BYTES + 1)
            if len(body) > MAX_BODY_BYTES:
                raise HardwareMonitorSSHError("response_too_large")
            if length is not None and len(body) != length:
                raise HardwareMonitorSSHError("invalid_response")
            return response.status, body
    except (http.client.HTTPException, OSError, ValueError) as exc:
        raise HardwareMonitorSSHError("invalid_response") from exc


def read_scout_http(request_target: str, *, timeout: float) -> tuple[int, bytes]:
    """Read a fixed hardware API target; every call creates and reaps its SSH.

    stdin must stay open after flushing the request. Closing it immediately
    (as subprocess.run(input=...) does) can close ssh -W before the reply arrives.
    Both output pipes are drained concurrently within one absolute deadline.
    """
    # Defense in depth: even an internal caller cannot send another HTTP target
    # or inject headers. The proxy additionally validates the query bounds.
    path, _, query = request_target.partition("?")
    allowed = path in {
        "/api/v1/hardware-monitor/status",
        "/api/v1/hardware-monitor/history",
        "/api/v1/hardware-monitor/events",
    }
    if query:
        limit = query[6:]
        maximum = 1440 if path.endswith("/history") else 200
        allowed = (allowed and not path.endswith("/status") and query.startswith("limit=")
                   and len(limit) <= 4 and limit.isascii() and limit.isdigit()
                   and 1 <= int(limit) <= maximum)
    if not allowed:
        raise HardwareMonitorSSHError("request_refused")
    request = (
        f"GET {request_target} HTTP/1.1\r\n"
        "Host: 127.0.0.1:9151\r\nAccept: application/json\r\n"
        "Connection: close\r\n\r\n"
    ).encode("ascii")
    process = None
    deadline = time.monotonic() + timeout
    output = bytearray()
    errors = bytearray()
    try:
        process = subprocess.Popen(
            SSH_COMMAND, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, shell=False, bufsize=0,
        )
        process.stdin.write(request)
        process.stdin.flush()
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ, "stdout")
            selector.register(process.stderr, selectors.EVENT_READ, "stderr")
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise HardwareMonitorSSHError("ssh_timeout")
                for key, _ in selector.select(remaining):
                    chunk = os.read(key.fd, 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                    elif key.data == "stdout":
                        output.extend(chunk)
                        if len(output) > MAX_BODY_BYTES + MAX_HEADER_BYTES:
                            raise HardwareMonitorSSHError("response_too_large")
                    else:
                        errors.extend(chunk[:max(0, MAX_STDERR_BYTES - len(errors))])
        process.stdin.close()
        returncode = process.wait(timeout=max(0.001, deadline - time.monotonic()))
        if returncode != 0:
            code = "scout_api_unavailable" if b"open failed: connect failed" in errors else "ssh_unavailable"
            raise HardwareMonitorSSHError(code)
        return _parse_response(bytes(output))
    except subprocess.TimeoutExpired as exc:
        raise HardwareMonitorSSHError("ssh_timeout") from exc
    except OSError as exc:
        raise HardwareMonitorSSHError("ssh_unavailable") from exc
    finally:
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.wait()
            for pipe in (process.stdin, process.stdout, process.stderr):
                if pipe is not None:
                    pipe.close()
