from __future__ import annotations

import asyncio
import re
import threading

from api_server import create_app


BODY_LIMIT = 400_000


class _LegacyHandler:
    calls = 0
    received_bytes = 0

    def do_POST(self):
        _LegacyHandler.calls += 1
        length = int(self.headers.get("Content-Length", "0") or 0)
        payload = self.rfile.read(length)
        _LegacyHandler.received_bytes = len(payload)
        self.send_response(201)
        self.send_header("Content-Length", "0")
        self.end_headers()


async def _post(app, chunks, content_length=None):
    messages = []
    remaining = [
        {"type": "http.request", "body": chunk, "more_body": index < len(chunks) - 1}
        for index, chunk in enumerate(chunks)
    ]
    body_reads = 0

    async def receive():
        nonlocal body_reads
        if remaining:
            body_reads += 1
            return remaining.pop(0)
        await asyncio.Event().wait()

    async def send(message):
        messages.append(message)

    headers = [(b"host", b"127.0.0.1:8765"), (b"x-token", b"test-token")]
    if content_length is not None:
        headers.append((b"content-length", str(content_length).encode("ascii")))
    await app({
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/test",
        "raw_path": b"/api/test",
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 8765),
    }, receive, send)
    start = next(item for item in messages if item["type"] == "http.response.start")
    body = b"".join(item.get("body", b"") for item in messages if item["type"] == "http.response.body")
    return start["status"], body, body_reads


def _app():
    return create_app(
        _LegacyHandler,
        token="test-token",
        quit_event=threading.Event(),
        begin_window_lease=lambda: object(),
        end_window_lease=lambda _lease: None,
        find_clip_path=lambda _name: None,
        clip_regex=re.compile(r"[A-Za-z0-9_-]+\\.mp4"),
        product_name="StreamSnip Test",
        version="test",
    )


def test_declared_oversized_body_is_rejected_without_reading_payload():
    _LegacyHandler.calls = 0
    status, body, body_reads = asyncio.run(
        _post(_app(), [b"x" * (BODY_LIMIT + 1)], content_length=BODY_LIMIT + 1)
    )
    assert status == 413
    assert b"too large" in body.lower()
    assert body_reads == 0
    assert _LegacyHandler.calls == 0


def test_oversized_stream_without_content_length_is_stopped_at_limit():
    _LegacyHandler.calls = 0
    status, body, body_reads = asyncio.run(
        _post(_app(), [b"x" * (BODY_LIMIT + 1)])
    )
    assert status == 413
    assert b"too large" in body.lower()
    assert body_reads == 1
    assert _LegacyHandler.calls == 0


def test_body_at_exact_limit_is_forwarded_to_legacy_handler():
    _LegacyHandler.calls = 0
    _LegacyHandler.received_bytes = 0
    payload = b"x" * BODY_LIMIT
    status, _body, _body_reads = asyncio.run(
        _post(_app(), [payload], content_length=len(payload))
    )
    assert status == 201
    assert _LegacyHandler.calls == 1
    assert _LegacyHandler.received_bytes == BODY_LIMIT
