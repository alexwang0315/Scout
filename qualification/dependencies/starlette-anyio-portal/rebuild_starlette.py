#!/usr/bin/env python3
"""Rebuild the scoped Starlette wheel with only the upstream portal alias backport."""
from __future__ import annotations
import argparse
import base64
import csv
import hashlib
import io
import json
from pathlib import Path
import urllib.request
import zipfile

BASE_VERSION = "1.6.0"
VERSION = "1.6.0+scout.anyioportal1"
SOURCE_SHA256 = "a86dd39d14bb45f85a3d18525215a9ef0cfd1f192ac793220e72598c90335f0c"
SOURCE_URL = "https://files.pythonhosted.org/packages/c8/cb/6a6a47d5b464bd08695d254f3da6e7986cc70c9fa5d778eda57538edfe56/starlette-1.6.0-py3-none-any.whl"
MAIN_COMMIT = "03f12b7fcf0a3e21a8da648ca0900c79472e9efe"
MAIN_SOURCE_SHA256 = "30b2bf322de2f7a5170dd3e4d352b7c61f3a1c5d092ee96b90c69af44ba4f0e2"
ROOT = Path(__file__).resolve().parent

def digest(data):
    return hashlib.sha256(data).hexdigest()

def build(output_dir, download=False):
    source = ROOT / "upstream/starlette-1.6.0-py3-none-any.whl"
    if not source.exists() and download:
        source.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(SOURCE_URL, timeout=30) as response:
            data = response.read()
        if digest(data) != SOURCE_SHA256:
            raise ValueError("Official source wheel hash mismatch")
        source.write_bytes(data)
    data = source.read_bytes()
    if digest(data) != SOURCE_SHA256:
        raise ValueError("Official source wheel hash mismatch")
    old_info = f"starlette-{BASE_VERSION}.dist-info"
    new_info = f"starlette-{VERSION}.dist-info"
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        contents = {name.replace(old_info + "/", new_info + "/", 1): z.read(name)
                    for name in z.namelist() if not name.endswith("/")}
    source_code = contents["starlette/testclient.py"]
    old = b"anyio.abc.BlockingPortal"
    new = b"anyio.from_thread.BlockingPortal"
    if source_code.count(old) != 3:
        raise ValueError("Expected exactly three deprecated portal references")
    contents["starlette/testclient.py"] = source_code.replace(old, new)
    init = contents["starlette/__init__.py"]
    if init != b'__version__ = "1.6.0"\n':
        raise ValueError("Unexpected package version declaration")
    contents["starlette/__init__.py"] = f'__version__ = "{VERSION}"\n'.encode()
    metadata = contents[f"{new_info}/METADATA"]
    if metadata.count(b"\nVersion: 1.6.0\n") != 1:
        raise ValueError("Unexpected metadata version")
    contents[f"{new_info}/METADATA"] = metadata.replace(
        b"\nVersion: 1.6.0\n", f"\nVersion: {VERSION}\n".encode())
    wheel_lines = contents[f"{new_info}/WHEEL"].decode().splitlines()
    contents[f"{new_info}/WHEEL"] = ("\n".join(
        "Generator: scout-anyio-portal-backport-1" if line.startswith("Generator:") else line
        for line in wheel_lines) + "\n").encode()
    provenance = {
        "base_version": BASE_VERSION, "version": VERSION,
        "source_wheel_url": SOURCE_URL, "source_wheel_sha256": SOURCE_SHA256,
        "upstream_reference_commit": MAIN_COMMIT,
        "upstream_reference_testclient_sha256": MAIN_SOURCE_SHA256,
        "code_change": {"file": "starlette/testclient.py", "replace": old.decode(),
                       "with": new.decode(), "count": 3},
        "original_testclient_sha256": digest(source_code),
        "candidate_testclient_sha256": digest(contents["starlette/testclient.py"]),
        "local_backport_not_official_release": True,
    }
    contents[f"{new_info}/scout-build.json"] = (json.dumps(provenance, sort_keys=True, indent=2) + "\n").encode()
    record_name = f"{new_info}/RECORD"
    contents.pop(record_name)
    record = io.StringIO(newline="")
    writer = csv.writer(record, lineterminator="\n")
    for name, payload in sorted(contents.items()):
        encoded = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).rstrip(b"=").decode()
        writer.writerow((name, "sha256=" + encoded, len(payload)))
    writer.writerow((record_name, "", ""))
    contents[record_name] = record.getvalue().encode()
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"starlette-{VERSION}-py3-none-any.whl"
    buffer = io.BytesIO()
    # Fixed timestamp, sorted entries and stored bytes avoid build-clock/zlib drift.
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as z:
        for name, payload in sorted(contents.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            z.writestr(info, payload)
    result = buffer.getvalue()
    if output.exists() and output.read_bytes() != result:
        raise ValueError(f"Refuse to overwrite different wheel: {output}")
    output.write_bytes(result)
    return output, {"wheel": str(output), "sha256": digest(result), **provenance}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    output, receipt = build(args.output_dir, args.download)
    print(json.dumps(receipt, indent=2))
