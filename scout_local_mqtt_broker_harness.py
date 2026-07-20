from __future__ import annotations

import socket
import struct
import threading
from dataclasses import asdict, dataclass
from typing import Callable, Literal


_LOOPBACK_HOST = "127.0.0.1"
_MAX_PACKET_BYTES = 1_048_576
_SOCKET_TIMEOUT_SECONDS = 2.0

MqttCallback = Callable[[str, bytes], None]
Lifecycle = Literal["created", "running", "stopped"]


class MqttLoopbackError(RuntimeError):
    """Raised when the local MQTT protocol exchange cannot be completed."""


class MqttProtocolError(MqttLoopbackError):
    """Raised for a malformed or unsupported MQTT 3.1.1 packet."""


class MqttLoopbackTimeout(MqttLoopbackError):
    """Raised when a synchronous loopback protocol response times out."""


@dataclass(frozen=True)
class MqttLoopbackStatus:
    artifact_kind: str
    schema_version: str
    lifecycle: Lifecycle
    bind_host: str
    bound_port: int | None
    protocol: str
    broker_connection_verified: bool
    accepted_connection_count: int
    loopback_publish_count: int
    qos0_publish_count: int
    qos1_publish_count: int
    puback_count: int
    external_network_calls_made: bool = False
    real_outbound_send_performed: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class MqttPublishReceipt:
    topic: str
    payload_byte_count: int
    qos: int
    packet_id: int | None
    puback_received: bool
    broker_acknowledged: bool
    broker_host: str
    broker_port: int
    external_network_calls_made: bool = False
    real_outbound_send_performed: bool = False


@dataclass(frozen=True)
class _BrokerSubscription:
    peer: "_BrokerPeer"
    topic: str
    qos: int


class _BrokerPeer:
    def __init__(self, connection: socket.socket) -> None:
        self.connection = connection
        self.subscriptions: list[_BrokerSubscription] = []


class MqttLoopbackSubscription:
    """A subscribed loopback client whose callback receives raw MQTT payloads."""

    def __init__(
        self,
        *,
        client: "_MqttLoopbackClient",
        callback: MqttCallback,
    ) -> None:
        self._client = client
        self._callback = callback
        self._closed = threading.Event()
        self._delivery_count = 0
        self._delivery_lock = threading.Lock()
        self._delivery_condition = threading.Condition(self._delivery_lock)
        self._last_error: str | None = None
        self._thread = threading.Thread(
            target=self._receive_loop,
            name="scout-mqtt-loopback-subscriber",
            daemon=True,
        )
        self._thread.start()

    @property
    def delivery_count(self) -> int:
        with self._delivery_lock:
            return self._delivery_count

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def wait_for_delivery_count(self, expected: int, *, timeout: float) -> bool:
        if expected < 0:
            raise ValueError("expected delivery count cannot be negative")
        if timeout <= 0:
            raise ValueError("delivery wait timeout must be positive")
        with self._delivery_condition:
            return self._delivery_condition.wait_for(
                lambda: self._delivery_count >= expected or self._closed.is_set(),
                timeout=timeout,
            ) and self._delivery_count >= expected

    def close(self) -> None:
        self._closed.set()
        with self._delivery_condition:
            self._delivery_condition.notify_all()
        self._client.disconnect()
        if threading.current_thread() is not self._thread:
            self._thread.join(timeout=_SOCKET_TIMEOUT_SECONDS)

    def _receive_loop(self) -> None:
        try:
            while not self._closed.is_set():
                try:
                    packet = self._client.receive_packet()
                except MqttLoopbackTimeout:
                    continue
                if packet is None:
                    return
                header, body = packet
                packet_type = header >> 4
                if packet_type == 3:
                    topic, payload, qos, packet_id = _parse_publish(header, body)
                    try:
                        self._callback(topic, payload)
                    except Exception as exc:  # callback is a harness boundary
                        self._last_error = f"callback_error:{type(exc).__name__}:{exc}"
                        continue
                    with self._delivery_condition:
                        self._delivery_count += 1
                        self._delivery_condition.notify_all()
                    if qos == 1 and packet_id is not None:
                        self._client.send_packet(0x40, struct.pack("!H", packet_id))
                    continue
                if packet_type == 13:
                    continue
                raise MqttProtocolError(
                    f"subscriber received unsupported MQTT packet type {packet_type}"
                )
        except (MqttLoopbackError, OSError) as exc:
            if not self._closed.is_set():
                self._last_error = f"{type(exc).__name__}:{exc}"
        finally:
            self._closed.set()
            with self._delivery_condition:
                self._delivery_condition.notify_all()

    def __enter__(self) -> "MqttLoopbackSubscription":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


class LocalMqttBrokerHarness:
    """Minimal MQTT 3.1.1 broker and clients restricted to IPv4 loopback.

    The harness opens real TCP sockets, but both broker and clients use the
    numeric 127.0.0.1 address. It never resolves a hostname or invokes a
    production transport.
    """

    def __init__(self, *, host: str = _LOOPBACK_HOST, port: int = 0) -> None:
        if host != _LOOPBACK_HOST:
            raise ValueError("local MQTT harness host must be exactly 127.0.0.1")
        if port != 0:
            raise ValueError("local MQTT harness must request ephemeral port 0")
        self._host = host
        self._requested_port = port
        self._bound_port: int | None = None
        self._lifecycle: Lifecycle = "created"
        self._server: socket.socket | None = None
        self._accept_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.RLock()
        self._send_lock = threading.Lock()
        self._clients: set[socket.socket] = set()
        self._client_threads: set[threading.Thread] = set()
        self._subscriptions: dict[str, list[_BrokerSubscription]] = {}
        self._next_client_id = 1
        self._next_delivery_packet_id = 1
        self._broker_connection_verified = False
        self._accepted_connection_count = 0
        self._loopback_publish_count = 0
        self._qos0_publish_count = 0
        self._qos1_publish_count = 0
        self._puback_count = 0

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        if self._bound_port is None:
            raise MqttLoopbackError("local MQTT broker has not started")
        return self._bound_port

    def start(self) -> MqttLoopbackStatus:
        with self._lock:
            if self._lifecycle == "running":
                return self.status()
            if self._lifecycle == "stopped":
                raise MqttLoopbackError("stopped local MQTT broker cannot be restarted")

            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                server.bind((self._host, self._requested_port))
                server.listen()
                server.settimeout(0.1)
            except BaseException:
                server.close()
                raise

            bound_host, bound_port = server.getsockname()
            if bound_host != _LOOPBACK_HOST:
                server.close()
                raise MqttLoopbackError("broker escaped the explicit IPv4 loopback bind")
            self._server = server
            self._bound_port = int(bound_port)
            self._lifecycle = "running"
            self._accept_thread = threading.Thread(
                target=self._accept_loop,
                name="scout-mqtt-loopback-broker",
                daemon=True,
            )
            self._accept_thread.start()
            return self.status()

    def stop(self) -> MqttLoopbackStatus:
        with self._lock:
            if self._lifecycle == "stopped":
                return self.status()
            self._stop_event.set()
            server = self._server
            self._server = None
            clients = list(self._clients)

        if server is not None:
            server.close()
        for client in clients:
            _close_socket(client)

        accept_thread = self._accept_thread
        if accept_thread is not None and threading.current_thread() is not accept_thread:
            accept_thread.join(timeout=_SOCKET_TIMEOUT_SECONDS)
        with self._lock:
            client_threads = list(self._client_threads)
        for thread in client_threads:
            if threading.current_thread() is not thread:
                thread.join(timeout=_SOCKET_TIMEOUT_SECONDS)

        with self._lock:
            self._clients.clear()
            self._subscriptions.clear()
            self._lifecycle = "stopped"
            return self.status()

    def subscribe(
        self,
        topic: str,
        callback: MqttCallback,
        *,
        qos: int = 1,
    ) -> MqttLoopbackSubscription:
        _validate_qos(qos)
        _validate_topic(topic)
        if not callable(callback):
            raise TypeError("subscriber callback must be callable")
        self._require_running()

        client = self._new_client("subscriber")
        packet_id = 1
        body = struct.pack("!H", packet_id) + _encode_utf8(topic) + bytes((qos,))
        client.send_packet(0x82, body)
        packet = client.receive_packet()
        if packet is None:
            client.close()
            raise MqttLoopbackError("broker closed before SUBACK")
        header, response = packet
        if header != 0x90 or response != struct.pack("!HB", packet_id, qos):
            client.close()
            raise MqttProtocolError("invalid SUBACK from local broker")
        return MqttLoopbackSubscription(client=client, callback=callback)

    def publish(
        self,
        topic: str,
        payload: bytes | bytearray | memoryview,
        *,
        qos: int = 1,
    ) -> MqttPublishReceipt:
        _validate_qos(qos)
        _validate_topic(topic)
        if not isinstance(payload, (bytes, bytearray, memoryview)):
            raise TypeError("MQTT payload must be bytes-like")
        payload_bytes = bytes(payload)
        self._require_running()

        client = self._new_client("publisher")
        packet_id = 1 if qos == 1 else None
        body = _encode_utf8(topic)
        if packet_id is not None:
            body += struct.pack("!H", packet_id)
        body += payload_bytes
        puback_received = False
        try:
            client.send_packet(0x30 | (qos << 1), body)
            if packet_id is not None:
                packet = client.receive_packet()
                if packet is None:
                    raise MqttLoopbackError("broker closed before PUBACK")
                header, response = packet
                if header != 0x40 or response != struct.pack("!H", packet_id):
                    raise MqttProtocolError("invalid PUBACK from local broker")
                puback_received = True
        finally:
            client.disconnect()

        return MqttPublishReceipt(
            topic=topic,
            payload_byte_count=len(payload_bytes),
            qos=qos,
            packet_id=packet_id,
            puback_received=puback_received,
            broker_acknowledged=puback_received,
            broker_host=self.host,
            broker_port=self.port,
        )

    def ping(self) -> bool:
        self._require_running()
        client = self._new_client("ping")
        try:
            client.send_packet(0xC0, b"")
            packet = client.receive_packet()
            return packet == (0xD0, b"")
        finally:
            client.disconnect()

    def status(self) -> MqttLoopbackStatus:
        with self._lock:
            return MqttLoopbackStatus(
                artifact_kind="scout_local_mqtt_broker_harness_status",
                schema_version="scout.local_mqtt_broker_harness.status.v0",
                lifecycle=self._lifecycle,
                bind_host=self._host,
                bound_port=self._bound_port,
                protocol="MQTT-3.1.1",
                broker_connection_verified=self._broker_connection_verified,
                accepted_connection_count=self._accepted_connection_count,
                loopback_publish_count=self._loopback_publish_count,
                qos0_publish_count=self._qos0_publish_count,
                qos1_publish_count=self._qos1_publish_count,
                puback_count=self._puback_count,
            )

    def __enter__(self) -> "LocalMqttBrokerHarness":
        self.start()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.stop()

    def _require_running(self) -> None:
        with self._lock:
            if self._lifecycle != "running" or self._server is None:
                raise MqttLoopbackError("local MQTT broker is not running")

    def _new_client(self, role: str) -> "_MqttLoopbackClient":
        with self._lock:
            client_number = self._next_client_id
            self._next_client_id += 1
        return _MqttLoopbackClient.connect(
            host=self.host,
            port=self.port,
            client_id=f"scout-loopback-{role}-{client_number}",
        )

    def _accept_loop(self) -> None:
        while not self._stop_event.is_set():
            server = self._server
            if server is None:
                return
            try:
                connection, address = server.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            if address[0] != _LOOPBACK_HOST:
                _close_socket(connection)
                continue
            connection.settimeout(_SOCKET_TIMEOUT_SECONDS)
            thread = threading.Thread(
                target=self._serve_client,
                args=(connection,),
                name="scout-mqtt-loopback-peer",
                daemon=True,
            )
            with self._lock:
                self._clients.add(connection)
                self._client_threads.add(thread)
                self._accepted_connection_count += 1
            thread.start()

    def _serve_client(self, connection: socket.socket) -> None:
        peer = _BrokerPeer(connection)
        try:
            packet = _read_packet(connection)
            if packet is None:
                return
            header, body = packet
            if header != 0x10:
                raise MqttProtocolError(
                    "first client packet must be CONNECT with fixed-header flags zero"
                )
            _validate_connect(body)
            self._send(connection, 0x20, b"\x00\x00")
            with self._lock:
                self._broker_connection_verified = True

            while not self._stop_event.is_set():
                try:
                    packet = _read_packet(connection)
                except socket.timeout:
                    continue
                if packet is None:
                    return
                header, body = packet
                packet_type = header >> 4
                if packet_type == 3:
                    self._handle_publish(peer, header, body)
                    continue
                if packet_type == 4:
                    if header != 0x40:
                        raise MqttProtocolError("PUBACK fixed-header flags must be zero")
                    _validate_packet_id_body(body, "PUBACK")
                    continue
                if packet_type == 8:
                    self._handle_subscribe(peer, header, body)
                    continue
                if packet_type == 12:
                    if header != 0xC0 or body:
                        raise MqttProtocolError(
                            "PINGREQ must have zero flags and an empty body"
                        )
                    self._send(connection, 0xD0, b"")
                    continue
                if packet_type == 14:
                    if header != 0xE0 or body:
                        raise MqttProtocolError(
                            "DISCONNECT must have zero flags and an empty body"
                        )
                    return
                raise MqttProtocolError(f"unsupported MQTT packet type {packet_type}")
        except (MqttProtocolError, OSError, socket.timeout):
            return
        finally:
            self._remove_peer(peer)

    def _handle_subscribe(self, peer: _BrokerPeer, header: int, body: bytes) -> None:
        if header & 0x0F != 0x02:
            raise MqttProtocolError("SUBSCRIBE fixed-header flags must be 0x2")
        if len(body) < 5:
            raise MqttProtocolError("SUBSCRIBE body is too short")
        packet_id = struct.unpack("!H", body[:2])[0]
        if packet_id == 0:
            raise MqttProtocolError("SUBSCRIBE packet id cannot be zero")
        topic, cursor = _decode_utf8(body, 2)
        if cursor >= len(body):
            raise MqttProtocolError("SUBSCRIBE is missing requested QoS")
        qos = body[cursor]
        _validate_protocol_qos(qos)
        if cursor + 1 != len(body):
            raise MqttProtocolError("multiple topic filters are not supported")
        _validate_topic(topic)
        subscription = _BrokerSubscription(peer=peer, topic=topic, qos=qos)
        with self._lock:
            peer.subscriptions.append(subscription)
            self._subscriptions.setdefault(topic, []).append(subscription)
        self._send(peer.connection, 0x90, struct.pack("!HB", packet_id, qos))

    def _handle_publish(self, peer: _BrokerPeer, header: int, body: bytes) -> None:
        topic, payload, qos, packet_id = _parse_publish(header, body)
        _validate_topic(topic)
        with self._lock:
            self._loopback_publish_count += 1
            if qos == 0:
                self._qos0_publish_count += 1
            else:
                self._qos1_publish_count += 1
            subscribers = tuple(self._subscriptions.get(topic, ()))

        for subscription in subscribers:
            delivery_qos = min(qos, subscription.qos)
            delivery_body = _encode_utf8(topic)
            if delivery_qos == 1:
                delivery_packet_id = self._take_delivery_packet_id()
                delivery_body += struct.pack("!H", delivery_packet_id)
            delivery_body += payload
            try:
                self._send(
                    subscription.peer.connection,
                    0x30 | (delivery_qos << 1),
                    delivery_body,
                )
            except OSError:
                self._remove_peer(subscription.peer)

        if qos == 1 and packet_id is not None:
            with self._lock:
                self._send(peer.connection, 0x40, struct.pack("!H", packet_id))
                self._puback_count += 1

    def _take_delivery_packet_id(self) -> int:
        with self._lock:
            packet_id = self._next_delivery_packet_id
            self._next_delivery_packet_id = 1 + (packet_id % 65535)
            return packet_id

    def _send(self, connection: socket.socket, header: int, body: bytes) -> None:
        packet = bytes((header,)) + _encode_remaining_length(len(body)) + body
        with self._send_lock:
            connection.sendall(packet)

    def _remove_peer(self, peer: _BrokerPeer) -> None:
        with self._lock:
            for subscription in peer.subscriptions:
                subscriptions = self._subscriptions.get(subscription.topic, [])
                self._subscriptions[subscription.topic] = [
                    item for item in subscriptions if item.peer is not peer
                ]
                if not self._subscriptions[subscription.topic]:
                    self._subscriptions.pop(subscription.topic, None)
            peer.subscriptions.clear()
            self._clients.discard(peer.connection)
            self._client_threads.discard(threading.current_thread())
        _close_socket(peer.connection)


class _MqttLoopbackClient:
    def __init__(self, connection: socket.socket) -> None:
        self._connection = connection
        self._send_lock = threading.Lock()
        self._closed = False

    @classmethod
    def connect(
        cls,
        *,
        host: str,
        port: int,
        client_id: str,
    ) -> "_MqttLoopbackClient":
        if host != _LOOPBACK_HOST:
            raise ValueError("loopback MQTT client host must be exactly 127.0.0.1")
        connection = socket.create_connection(
            (host, port),
            timeout=_SOCKET_TIMEOUT_SECONDS,
        )
        connection.settimeout(_SOCKET_TIMEOUT_SECONDS)
        client = cls(connection)
        connect_body = (
            _encode_utf8("MQTT")
            + bytes((4, 2))
            + struct.pack("!H", 60)
            + _encode_utf8(client_id)
        )
        try:
            client.send_packet(0x10, connect_body)
            response = client.receive_packet()
            if response != (0x20, b"\x00\x00"):
                raise MqttProtocolError("local broker did not accept MQTT CONNECT")
        except BaseException:
            client.close()
            raise
        return client

    def send_packet(self, header: int, body: bytes) -> None:
        packet = bytes((header,)) + _encode_remaining_length(len(body)) + body
        with self._send_lock:
            if self._closed:
                raise MqttLoopbackError("MQTT loopback client is closed")
            self._connection.sendall(packet)

    def receive_packet(self) -> tuple[int, bytes] | None:
        try:
            return _read_packet(self._connection)
        except socket.timeout as exc:
            raise MqttLoopbackTimeout(
                "timed out waiting for local MQTT broker"
            ) from exc

    def disconnect(self) -> None:
        if self._closed:
            return
        try:
            self.send_packet(0xE0, b"")
        except (MqttLoopbackError, OSError):
            pass
        finally:
            self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        _close_socket(self._connection)


def _read_packet(connection: socket.socket) -> tuple[int, bytes] | None:
    first = connection.recv(1)
    if not first:
        return None
    remaining_length = 0
    multiplier = 1
    for _ in range(4):
        encoded = connection.recv(1)
        if not encoded:
            raise MqttProtocolError("connection closed inside MQTT remaining length")
        value = encoded[0]
        remaining_length += (value & 0x7F) * multiplier
        if remaining_length > _MAX_PACKET_BYTES:
            raise MqttProtocolError("MQTT packet exceeds local harness size limit")
        if value & 0x80 == 0:
            return first[0], _read_exact(connection, remaining_length)
        multiplier *= 128
    raise MqttProtocolError("invalid MQTT remaining length")


def _read_exact(connection: socket.socket, length: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < length:
        chunk = connection.recv(length - len(chunks))
        if not chunk:
            raise MqttProtocolError("connection closed inside MQTT packet")
        chunks.extend(chunk)
    return bytes(chunks)


def _encode_remaining_length(length: int) -> bytes:
    if length < 0 or length > _MAX_PACKET_BYTES:
        raise ValueError("MQTT packet size is outside the local harness limit")
    encoded = bytearray()
    while True:
        digit = length % 128
        length //= 128
        if length:
            digit |= 0x80
        encoded.append(digit)
        if not length:
            return bytes(encoded)


def _encode_utf8(value: str) -> bytes:
    encoded = value.encode("utf-8")
    if not encoded or len(encoded) > 65535:
        raise ValueError("MQTT UTF-8 value must contain 1 to 65535 bytes")
    return struct.pack("!H", len(encoded)) + encoded


def _decode_utf8(body: bytes, cursor: int = 0) -> tuple[str, int]:
    if cursor + 2 > len(body):
        raise MqttProtocolError("MQTT UTF-8 length is missing")
    length = struct.unpack("!H", body[cursor : cursor + 2])[0]
    cursor += 2
    if length == 0 or cursor + length > len(body):
        raise MqttProtocolError("MQTT UTF-8 value is empty or truncated")
    try:
        value = body[cursor : cursor + length].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MqttProtocolError("MQTT UTF-8 value is invalid") from exc
    return value, cursor + length


def _validate_connect(body: bytes) -> None:
    protocol_name, cursor = _decode_utf8(body)
    if protocol_name != "MQTT" or cursor + 4 > len(body):
        raise MqttProtocolError("CONNECT must use MQTT protocol name")
    protocol_level = body[cursor]
    connect_flags = body[cursor + 1]
    if protocol_level != 4:
        raise MqttProtocolError("only MQTT 3.1.1 protocol level 4 is supported")
    if connect_flags & 0x01:
        raise MqttProtocolError("CONNECT reserved flag must be zero")
    cursor += 4
    client_id, cursor = _decode_utf8(body, cursor)
    if not client_id or cursor != len(body):
        raise MqttProtocolError("CONNECT payload must contain only a client id")


def _parse_publish(
    header: int,
    body: bytes,
) -> tuple[str, bytes, int, int | None]:
    qos = (header >> 1) & 0x03
    _validate_protocol_qos(qos)
    topic, cursor = _decode_utf8(body)
    packet_id = None
    if qos == 1:
        if cursor + 2 > len(body):
            raise MqttProtocolError("QoS 1 PUBLISH is missing packet id")
        packet_id = struct.unpack("!H", body[cursor : cursor + 2])[0]
        if packet_id == 0:
            raise MqttProtocolError("PUBLISH packet id cannot be zero")
        cursor += 2
    return topic, body[cursor:], qos, packet_id


def _validate_packet_id_body(body: bytes, packet_name: str) -> None:
    if len(body) != 2 or struct.unpack("!H", body)[0] == 0:
        raise MqttProtocolError(f"{packet_name} must contain a non-zero packet id")


def _validate_qos(qos: int) -> None:
    if qos not in (0, 1):
        raise ValueError("local MQTT harness supports QoS 0 or QoS 1")


def _validate_protocol_qos(qos: int) -> None:
    if qos not in (0, 1):
        raise MqttProtocolError("local MQTT broker supports QoS 0 or QoS 1")


def _validate_topic(topic: str) -> None:
    if not isinstance(topic, str) or not topic:
        raise ValueError("MQTT topic must be a non-empty string")
    if "\x00" in topic or "+" in topic or "#" in topic:
        raise ValueError("local MQTT harness requires an exact topic without wildcards")
    if len(topic.encode("utf-8")) > 65535:
        raise ValueError("MQTT topic exceeds the MQTT UTF-8 length limit")


def _close_socket(connection: socket.socket) -> None:
    try:
        connection.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    connection.close()
