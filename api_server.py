"""FastAPI transport for StreamSnip's local application services.

Media and transcription work remains in the Core/Engine worker layer. Synchronous
service routes run in Starlette's worker pool, never on the ASGI event loop.
"""
from __future__ import annotations

import asyncio
import ipaddress
import os
import socket
import re
import secrets
from pathlib import Path
from typing import Callable, Pattern
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.concurrency import run_in_threadpool


def patch_windows_proactor_connection_reset() -> bool:
    """Backport CPython's guarded Proactor socket shutdown on Windows.

    A peer reset (WSAECONNRESET / WinError 10054) can occur while a browser
    connection is being torn down. Some Python builds let that expected
    ConnectionError escape from _call_connection_lost before socket.close()
    and server detachment run. Match CPython's newer guarded cleanup behavior
    while leaving every unrelated transport error visible.
    """
    if os.name != "nt":
        return False

    try:
        import inspect
        from asyncio import proactor_events
        transport_base = proactor_events._ProactorBasePipeTransport
        original = transport_base._call_connection_lost
    except (AttributeError, ImportError):
        return False

    if getattr(original, "_streamsnip_connection_reset_compat", False):
        return True

    try:
        if "except ConnectionError" in inspect.getsource(original):
            return True
    except (OSError, TypeError):
        pass

    def streamsnip_call_connection_lost(self, exc):
        if self._called_connection_lost:
            return
        try:
            self._protocol.connection_lost(exc)
        finally:
            if hasattr(self._sock, "shutdown") and self._sock.fileno() != -1:
                try:
                    self._sock.shutdown(socket.SHUT_RDWR)
                except ConnectionError:
                    # The browser/client already reset this connection.
                    # Continue closing and detaching the dead transport.
                    pass
            self._sock.close()
            self._sock = None
            server = self._server
            if server is not None:
                server._detach(self)
                self._server = None
            self._called_connection_lost = True

    streamsnip_call_connection_lost.__name__ = original.__name__
    streamsnip_call_connection_lost.__qualname__ = original.__qualname__
    streamsnip_call_connection_lost.__module__ = original.__module__
    streamsnip_call_connection_lost.__doc__ = original.__doc__
    streamsnip_call_connection_lost._streamsnip_connection_reset_compat = True
    transport_base._call_connection_lost = streamsnip_call_connection_lost
    return True


class _HeaderMap:
    """Case-insensitive request headers compatible with BaseHTTPRequestHandler."""

    def __init__(self, headers, body_length: int = 0) -> None:
        self._values = {str(key).lower(): str(value) for key, value in headers.items()}
        self._values.setdefault("content-length", str(body_length))

    def get(self, name: str, default=None):
        return self._values.get(str(name).lower(), default)


class ServiceRequestAdapter:
    """Bridge a Starlette request to the existing handler's small HTTP interface."""

    def __init__(self, request: Request, routes_class: type, body: bytes = b"") -> None:
        import io

        self._routes_class = routes_class
        self.headers = _HeaderMap(request.headers, len(body))
        self.path = request.url.path + (("?" + request.url.query) if request.url.query else "")
        self.rfile = io.BytesIO(body)
        self.wfile = io.BytesIO()
        self.close_connection = False
        self.status_code = 200
        self.response_headers: dict[str, str] = {}

    def __getattr__(self, name: str):
        attribute = getattr(self._routes_class, name, None)
        if attribute is None:
            raise AttributeError(name)
        if callable(attribute):
            return attribute.__get__(self, type(self))
        return attribute

    def send_response(self, code: int, message: str | None = None) -> None:
        self.status_code = int(code)

    def send_header(self, name: str, value: str) -> None:
        self.response_headers[str(name)] = str(value)

    def end_headers(self) -> None:
        pass


MAX_REQUEST_BODY_BYTES = 400_000


async def read_request_body_limited(request: Request, limit: int = MAX_REQUEST_BODY_BYTES):
    """Read a request body without buffering more than the configured limit.

    A trustworthy Content-Length lets us reject an oversized request before
    consuming its body. Chunked or missing-length requests are counted as they
    arrive and stop as soon as the limit is crossed.
    """
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except (TypeError, ValueError):
            return JSONResponse(status_code=400, content={"error": "invalid content length"})
        if declared_length < 0:
            return JSONResponse(status_code=400, content={"error": "invalid content length"})
        if declared_length > limit:
            return JSONResponse(status_code=413, content={"error": "request body too large"})

    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            return JSONResponse(status_code=413, content={"error": "request body too large"})
    return bytes(body)


def create_app(
    routes_class: type,
    *,
    token: str,
    quit_event,
    begin_window_lease: Callable[[], object],
    end_window_lease: Callable[[object], None],
    find_clip_path: Callable[[str], Path | None],
    clip_regex: Pattern[str],
    product_name: str,
    version: str,
) -> FastAPI:
    """Build the local-only ASGI application around StreamSnip's app services."""
    app = FastAPI(
        title=f"{product_name} local API",
        version=version,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )

    @app.middleware("http")
    async def require_loopback(request: Request, call_next):
        host = request.headers.get("host", "")
        try:
            hostname = (urlsplit("//" + host).hostname or "").lower().rstrip(".")
        except ValueError:
            hostname = ""
        if hostname not in {"127.0.0.1", "localhost", "::1"}:
            return JSONResponse(status_code=403, content={"error": "Local requests only."})

        client_host = request.client.host if request.client else ""
        try:
            client_ip = ipaddress.ip_address(client_host)
            mapped = getattr(client_ip, "ipv4_mapped", None)
            is_loopback = client_ip.is_loopback or bool(mapped and mapped.is_loopback)
        except ValueError:
            is_loopback = False
        if not is_loopback:
            return JSONResponse(status_code=403, content={"error": "Local requests only."})
        return await call_next(request)

    @app.get("/api/health", tags=["system"])
    async def health():
        return {"status": "ok", "app": product_name, "version": version}

    @app.get("/api/window/lease", include_in_schema=False)
    async def window_lease(request: Request):
        if not secrets.compare_digest(request.headers.get("x-token", ""), token):
            raise HTTPException(status_code=403, detail="forbidden")

        async def stream():
            lease_id = request.query_params.get("id", "")
            lease = begin_window_lease(lease_id or None)
            if lease is None:
                return
            try:
                yield b": connected\n\n"
                while not quit_event.is_set():
                    await asyncio.sleep(1.0)
                    if not quit_event.is_set():
                        yield b": keepalive\n\n"
            finally:
                end_window_lease(lease)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "Connection": "keep-alive"},
        )

    @app.get("/clips/{name}", include_in_schema=False)
    def serve_clip(name: str, request: Request):
        if clip_regex.fullmatch(name):
            clip_path = find_clip_path(name)
        elif (
            len(name) <= 255
            and name.endswith(".txt")
            and len(name) > 4
            and all(char.isascii() and (char.isalnum() or char in "_-") for char in name[:-4])
        ):
            source = find_clip_path(Path(name).stem + ".mp4")
            clip_path = source.with_suffix(".txt") if source else None
        else:
            clip_path = None

        if not clip_path or not clip_path.is_file():
            return JSONResponse(status_code=404, content={"error": "not found"})

        size = clip_path.stat().st_size
        content_type = "video/mp4" if name.endswith(".mp4") else "text/plain; charset=utf-8"
        headers = {"Accept-Ranges": "bytes", "Cache-Control": "no-cache"}
        if size == 0:
            headers["Content-Length"] = "0"
            return Response(content=b"", media_type=content_type, headers=headers)

        start, end, status_code = 0, size - 1, 200
        range_value = request.headers.get("range", "")
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_value.strip())
        if match:
            first, last = match.groups()
            if first == "" and last:
                start = max(0, size - int(last))
            elif first:
                start = int(first)
                if last:
                    end = int(last)
            end = min(end, size - 1)
            if start > end or start >= size:
                return Response(
                    status_code=416,
                    headers={"Content-Range": f"bytes */{size}", "Content-Length": "0"},
                )
            status_code = 206

        length = end - start + 1
        headers["Content-Length"] = str(length)
        if status_code == 206:
            headers["Content-Range"] = f"bytes {start}-{end}/{size}"

        def file_chunks():
            with clip_path.open("rb") as handle:
                handle.seek(start)
                remaining = length
                while remaining:
                    chunk = handle.read(min(262144, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

        return StreamingResponse(
            file_chunks(),
            status_code=status_code,
            media_type=content_type,
            headers=headers,
        )

    @app.api_route("/{path:path}", methods=["GET", "POST"], include_in_schema=False)
    async def dispatch_app_route(path: str, request: Request):
        body = b""
        if request.method == "POST":
            body = await read_request_body_limited(request)
            if isinstance(body, JSONResponse):
                return body

        adapter = ServiceRequestAdapter(request, routes_class, body)
        route_method = routes_class.do_GET if request.method == "GET" else routes_class.do_POST
        await run_in_threadpool(route_method.__get__(adapter, type(adapter)))
        return Response(
            content=adapter.wfile.getvalue(),
            status_code=adapter.status_code,
            headers=adapter.response_headers,
        )

    return app
