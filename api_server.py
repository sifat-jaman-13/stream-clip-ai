"""FastAPI transport for StreamSnip's established local application services.

Heavy media and transcription work remains in the existing Core/Engine worker
layer. Synchronous legacy routes run in Starlette's worker pool, not the ASGI
event loop. This keeps the migration backward-compatible with the current UI.
"""
from __future__ import annotations

import asyncio
import ipaddress
import re
import secrets
from pathlib import Path
from typing import Callable, Pattern
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.concurrency import run_in_threadpool


class _HeaderMap:
    """Case-insensitive request headers compatible with BaseHTTPRequestHandler."""

    def __init__(self, headers, body_length: int = 0) -> None:
        self._values = {str(key).lower(): str(value) for key, value in headers.items()}
        self._values.setdefault("content-length", str(body_length))

    def get(self, name: str, default=None):
        return self._values.get(str(name).lower(), default)


class LegacyRequestAdapter:
    """Bridge a Starlette request to the existing handler's small HTTP interface."""

    def __init__(self, request: Request, handler_class: type, body: bytes = b"") -> None:
        import io

        self._handler_class = handler_class
        self.headers = _HeaderMap(request.headers, len(body))
        self.path = request.url.path + (("?" + request.url.query) if request.url.query else "")
        self.rfile = io.BytesIO(body)
        self.wfile = io.BytesIO()
        self.close_connection = False
        self.status_code = 200
        self.response_headers: dict[str, str] = {}

    def __getattr__(self, name: str):
        attribute = getattr(self._handler_class, name, None)
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


def create_app(
    legacy_handler: type,
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
            lease = begin_window_lease()
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
        elif re.fullmatch(r"[A-Za-z0-9_-]+\.txt", name):
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
    async def dispatch_legacy(path: str, request: Request):
        body = b""
        if request.method == "POST":
            body = await request.body()
            if len(body) > 400_000:
                return JSONResponse(status_code=413, content={"error": "too large"})

        adapter = LegacyRequestAdapter(request, legacy_handler, body)
        handler_method = legacy_handler.do_GET if request.method == "GET" else legacy_handler.do_POST
        await run_in_threadpool(handler_method, adapter)
        return Response(
            content=adapter.wfile.getvalue(),
            status_code=adapter.status_code,
            headers=adapter.response_headers,
        )

    return app
