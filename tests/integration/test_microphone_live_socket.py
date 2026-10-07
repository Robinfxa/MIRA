"""Real loopback Uvicorn WebSocket checks for the browser microphone route.

Only synthetic PCM, a synthetic ASR iterator, and local generation/review fakes are used.
No browser, microphone device, Google, Codex, or JEV service is contacted.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import socket
import struct
import threading
import time
from contextlib import contextmanager
from uuid import uuid4

import httpx
import uvicorn

from mira.application.contracts import CandidateRange, EffectProposal, ReviewObservation, ReviewVerdict
from mira.application.ports.media import TranscriptRevision
from mira.bootstrap.providers import Providers
from mira.config.settings import Settings
from mira.entrypoints.http.app import create_app
from mira.domain.models import EffectKind


class _Generate:
    async def generate(self, _context):
        yield CandidateRange((EffectProposal(EffectKind.SPEECH, "Synthetic fixture only."),), "test")


class _Review:
    async def review(self, _context, _candidate):
        return ReviewObservation(ReviewVerdict.ALLOW, "Synthetic fixture only.")


class _SyntheticAsr:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.closed = threading.Event()
        self.closed_count = 0
        self.packets: list[object] = []

    async def transcribe(self, packets):
        self.started.set()
        try:
            async for packet in packets:
                self.packets.append(packet)
                yield TranscriptRevision(packet.stream_id, len(self.packets), "synthetic transcript", True)
        finally:
            self.closed_count += 1
            self.closed.set()


class _RawWebSocket:
    """Tiny stdlib-only RFC 6455 client, keeping the server test independent of extras."""

    def __init__(self, address: tuple[str, int], target: str, *, origin: str | None) -> None:
        self.sock = socket.create_connection(address, timeout=3)
        self.sock.settimeout(3)
        self.buffer = bytearray()
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        headers = [
            f"GET {target} HTTP/1.1",
            f"Host: {address[0]}:{address[1]}",
            "Upgrade: websocket",
            "Connection: Upgrade",
            "Sec-WebSocket-Version: 13",
            f"Sec-WebSocket-Key: {key}",
        ]
        if origin is not None:
            headers.append(f"Origin: {origin}")
        self.sock.sendall(("\r\n".join(headers) + "\r\n\r\n").encode("ascii"))
        response = self._read_headers()
        try:
            self.status = int(response.split(b"\r\n", 1)[0].split()[1])
        except (IndexError, ValueError):
            self.status = 0

    def _fill(self, size: int) -> None:
        while len(self.buffer) < size:
            chunk = self.sock.recv(max(4096, size - len(self.buffer)))
            if not chunk:
                raise EOFError("socket closed before the expected WebSocket frame")
            self.buffer.extend(chunk)

    def _take(self, size: int) -> bytes:
        self._fill(size)
        value = bytes(self.buffer[:size])
        del self.buffer[:size]
        return value

    def _read_headers(self) -> bytes:
        while b"\r\n\r\n" not in self.buffer:
            chunk = self.sock.recv(4096)
            if not chunk:
                break
            self.buffer.extend(chunk)
        boundary = self.buffer.find(b"\r\n\r\n")
        if boundary < 0:
            result = bytes(self.buffer)
            self.buffer.clear()
            return result
        result = bytes(self.buffer[:boundary + 4])
        del self.buffer[:boundary + 4]
        return result

    def send_text(self, text: str) -> None:
        payload = text.encode("utf-8")
        mask = os.urandom(4)
        first = bytes([0x81])
        if len(payload) < 126:
            header = first + bytes([0x80 | len(payload)])
        elif len(payload) <= 0xFFFF:
            header = first + bytes([0x80 | 126]) + struct.pack(">H", len(payload))
        else:
            header = first + bytes([0x80 | 127]) + struct.pack(">Q", len(payload))
        masked = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        self.sock.sendall(header + mask + masked)

    def send_json(self, value: dict) -> None:
        self.send_text(json.dumps(value, separators=(",", ":")))

    def _read_frame(self) -> tuple[int, bytes]:
        first, second = self._take(2)
        opcode = first & 0x0F
        length = second & 0x7F
        if length == 126:
            length = struct.unpack(">H", self._take(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", self._take(8))[0]
        mask = self._take(4) if second & 0x80 else None
        payload = self._take(length)
        if mask is not None:
            payload = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        return opcode, payload

    def receive_text(self) -> dict:
        while True:
            opcode, payload = self._read_frame()
            if opcode == 0x1:
                return json.loads(payload.decode("utf-8"))
            if opcode == 0x8:
                raise EOFError("server closed before a text message")
            if opcode == 0x9:
                self._send_control(0xA, payload)

    def receive_close_code(self) -> int:
        while True:
            opcode, payload = self._read_frame()
            if opcode == 0x8:
                return struct.unpack(">H", payload[:2])[0] if len(payload) >= 2 else 1005
            if opcode == 0x9:
                self._send_control(0xA, payload)

    def _send_control(self, opcode: int, payload: bytes = b"") -> None:
        mask = os.urandom(4)
        masked = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        self.sock.sendall(bytes([0x80 | opcode, 0x80 | len(payload)]) + mask + masked)

    def close(self, *, graceful: bool = True) -> None:
        try:
            if graceful and self.status == 101:
                self._send_control(0x8, struct.pack(">H", 1000))
        except (OSError, EOFError):
            pass
        try:
            self.sock.close()
        except OSError:
            pass


@contextmanager
def _running_server(asr: _SyntheticAsr):
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    host, port = listener.getsockname()
    origin = f"http://{host}:{port}"
    settings = Settings().model_copy(update={
        "environment": "test",
        "http": Settings().http.model_copy(update={
            "host": "127.0.0.1", "port": port, "allowed_origins": (origin,),
        }),
    })
    app = create_app(settings, providers=Providers(_Generate(), _Review()), speech_recognition=asr)
    server = uvicorn.Server(uvicorn.Config(
        app, host=host, port=port, ws="auto", ws_max_size=32768, ws_max_queue=8,
        log_config=None, log_level="critical", access_log=False,
    ))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and not server.started and thread.is_alive():
        time.sleep(0.01)
    try:
        assert server.started, "Uvicorn failed to start the local integration server"
        yield app, (host, port), origin
    finally:
        server.should_exit = True
        thread.join(timeout=3)
        if thread.is_alive():
            server.force_exit = True
            thread.join(timeout=1)
        listener.close()
        assert not thread.is_alive(), "Uvicorn local test server did not shut down"


def _new_session(address: tuple[str, int]) -> tuple[str, str, dict]:
    with httpx.Client(trust_env=False, timeout=3) as client:
        response = client.post(
            f"http://{address[0]}:{address[1]}/api/v1/sessions",
            json={"client_instance_id": str(uuid4())},
        )
    assert response.status_code == 201
    data = response.json()
    state = data["session"]
    return state["session_id"], data["session_token"], state


def _start_payload(token: str, state: dict) -> dict:
    return {
        "type": "start", "session_token": token, "stream_id": str(uuid4()),
        "activity_seq": state["activity_seq"], "input_epoch": state["input_epoch"],
        "sample_rate_hz": 16000,
    }


def _connect(address: tuple[str, int], session_id: str, *, origin: str | None,
             query: str = "") -> _RawWebSocket:
    path = f"/api/v1/sessions/{session_id}/microphone{query}"
    return _RawWebSocket(address, path, origin=origin)


def _retry_ready_after_cleanup(address: tuple[str, int], session_id: str, token: str,
                              state: dict, origin: str) -> _RawWebSocket:
    """Retry only a still-owned voice slot; return once disconnect cleanup is observable."""
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        ws = _connect(address, session_id, origin=origin)
        assert ws.status == 101
        ws.send_json(_start_payload(token, state))
        message = ws.receive_text()
        if message["type"] == "ready":
            return ws
        assert message["type"] == "error" and message["code"] == "busy"
        assert ws.receive_close_code() == 1000
        ws.close(graceful=False)
        time.sleep(0.01)
    raise AssertionError("microphone media slot was not released after socket cleanup")


def test_real_uvicorn_socket_accepts_authenticated_microphone_and_closes_cleanly():
    asr = _SyntheticAsr()
    with _running_server(asr) as (_app, address, origin):
        session_id, token, state = _new_session(address)
        ws = _connect(address, session_id, origin=origin)
        try:
            assert ws.status == 101
            start = _start_payload(token, state)
            ws.send_json(start)
            assert ws.receive_text()["type"] == "ready"
            pcm = base64.b64encode(b"\x00\x00" * 320).decode("ascii")
            ws.send_json({"type": "audio", "sequence": 1, "first_sample": 0,
                          "pcm_base64": pcm})
            transcript = ws.receive_text()
            assert transcript["type"] == "transcript" and transcript["is_final"] is True
            ws.send_json({"type": "finish"})
            complete = ws.receive_text()
            assert complete["type"] == "complete" and complete["had_final"] is True
            assert ws.receive_close_code() == 1000
            assert asr.closed.wait(1)
            assert len(asr.packets) == 1
        finally:
            ws.close(graceful=False)


def test_real_uvicorn_socket_rejects_wrong_and_missing_session_auth_without_asr():
    asr = _SyntheticAsr()
    with _running_server(asr) as (_app, address, origin):
        session_id, token, state = _new_session(address)
        for start in (_start_payload("wrong-test-token", state),
                      {key: value for key, value in _start_payload(token, state).items()
                       if key != "session_token"}):
            ws = _connect(address, session_id, origin=origin)
            try:
                assert ws.status == 101
                ws.send_json(start)
                error = ws.receive_text()
                assert error["type"] == "error"
                assert error["code"] in {"session_not_found", "invalid_input"}
                assert ws.receive_close_code() == 1000
            finally:
                ws.close(graceful=False)
        assert not asr.started.is_set()


def test_real_uvicorn_socket_rejects_missing_and_untrusted_origin_before_upgrade():
    asr = _SyntheticAsr()
    with _running_server(asr) as (_app, address, _origin):
        session_id, _token, _state = _new_session(address)
        for origin in (None, "https://untrusted.invalid"):
            ws = _connect(address, session_id, origin=origin)
            try:
                assert ws.status == 403
            finally:
                ws.close(graceful=False)
        assert not asr.started.is_set()


def test_real_uvicorn_wsproto_enforces_32k_message_limit_and_reaps_disconnected_asr():
    asr = _SyntheticAsr()
    with _running_server(asr) as (_app, address, origin):
        session_id, token, state = _new_session(address)
        ws = _connect(address, session_id, origin=origin)
        try:
            assert ws.status == 101
            ws.send_json(_start_payload(token, state))
            assert ws.receive_text()["type"] == "ready"
            ws.send_text("x" * (32768 + 1))
            assert ws.receive_close_code() == 1009
            assert asr.closed.wait(1)
            assert asr.closed_count == 1
        finally:
            ws.close(graceful=False)

        # A new stream on the same session is the observable proof that the oversized-message
        # socket and its ASR operation were reaped.
        asr.closed.clear()
        retry = _retry_ready_after_cleanup(address, session_id, token, state, origin)
        try:
            retry.close(graceful=False)
            assert asr.closed.wait(1)
        finally:
            retry.close(graceful=False)


def test_real_uvicorn_tcp_disconnect_cancels_asr_and_releases_the_voice_slot():
    asr = _SyntheticAsr()
    with _running_server(asr) as (_app, address, origin):
        session_id, token, state = _new_session(address)
        ws = _connect(address, session_id, origin=origin)
        assert ws.status == 101
        ws.send_json(_start_payload(token, state))
        assert ws.receive_text()["type"] == "ready"
        ws.send_json({"type": "audio", "sequence": 1, "first_sample": 0,
                      "pcm_base64": base64.b64encode(b"\x00\x00" * 320).decode("ascii")})
        assert ws.receive_text()["type"] == "transcript"
        ws.close(graceful=False)
        assert asr.closed.wait(1)
        assert asr.closed_count == 1 and len(asr.packets) == 1

        asr.closed.clear()
        retry = _retry_ready_after_cleanup(address, session_id, token, state, origin)
        try:
            retry.close(graceful=False)
            assert asr.closed.wait(1)
            assert asr.closed_count == 2
        finally:
            retry.close(graceful=False)
