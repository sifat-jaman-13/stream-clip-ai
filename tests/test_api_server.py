from __future__ import annotations

import asyncio
import json
import re
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

from api_server import create_app
import autoclip


class FakeLegacyHandler:
    def _host_ok(self):
        return self.headers.get("Host", "").startswith("127.0.0.1")

    def _send(self, code, body):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, {"error": "bad host"})
        return self._send(200, {"legacy": "get", "path": self.path})

    def do_POST(self):
        if not self._host_ok() or self.headers.get("X-Token") != "test-token":
            return self._send(403, {"error": "forbidden"})
        size = int(self.headers.get("Content-Length", "0") or 0)
        return self._send(201, self.rfile.read(size))


async def asgi_request(app, method="GET", path="/api/legacy", headers=None, body=b""):
    parts = urlsplit(path)
    received = False
    messages = []
    provided_headers = headers or {}
    host_value = next((value for key, value in provided_headers.items()
                       if key.lower() == "host"), "127.0.0.1:8765")
    raw_headers = [(b"host", host_value.encode("latin-1"))]
    raw_headers.extend((key.lower().encode("latin-1"), value.encode("latin-1"))
                       for key, value in provided_headers.items() if key.lower() != "host")

    async def receive():
        nonlocal received
        if not received:
            received = True
            return {"type": "http.request", "body": body, "more_body": False}
        await asyncio.Event().wait()

    async def send(message):
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": parts.path,
        "raw_path": parts.path.encode("ascii"),
        "query_string": parts.query.encode("ascii"),
        "root_path": "",
        "headers": raw_headers,
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 8765),
    }
    await app(scope, receive, send)
    start = next(item for item in messages if item["type"] == "http.response.start")
    response_body = b"".join(item.get("body", b"") for item in messages
                              if item["type"] == "http.response.body")
    response_headers = {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in start.get("headers", [])
    }
    return start["status"], response_headers, response_body


class APIServerTests(unittest.TestCase):
    def create_app(self, find_clip_path=lambda _name: None):
        return create_app(
            FakeLegacyHandler,
            token="test-token",
            quit_event=threading.Event(),
            begin_window_lease=lambda: object(),
            end_window_lease=lambda _lease: None,
            find_clip_path=find_clip_path,
            clip_regex=re.compile(r"[A-Za-z0-9_-]+\.mp4"),
            product_name="StreamSnip Test",
            version="test",
        )

    def test_real_streamsnip_handler_is_compatible_with_fastapi_adapter(self):
        app = create_app(
            autoclip.AppRoutes,
            token=autoclip.TOKEN,
            quit_event=autoclip.QUIT,
            begin_window_lease=autoclip.begin_window_lease,
            end_window_lease=autoclip.end_window_lease,
            find_clip_path=autoclip.find_clip_path,
            clip_regex=autoclip.CLIP_RE,
            product_name=autoclip.PRODUCT_NAME,
            version=autoclip.APP_VERSION,
        )
        status, _headers, body = asyncio.run(asgi_request(app, path="/api/session"))
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["token"], autoclip.TOKEN)

    def test_window_lease_registers_and_releases_the_browser_window_id(self):
        started = []
        ended = []
        quit_event = threading.Event()
        app = create_app(
            FakeLegacyHandler,
            token="test-token",
            quit_event=quit_event,
            begin_window_lease=lambda lease_id=None: started.append(lease_id) or lease_id,
            end_window_lease=lambda lease_id: ended.append(lease_id),
            find_clip_path=lambda _name: None,
            clip_regex=re.compile(r"[A-Za-z0-9_-]+\.mp4"),
            product_name="StreamSnip Test",
            version="test",
        )
        route = next(item for item in app.routes if getattr(item, "path", None) == "/api/window/lease")
        request = SimpleNamespace(
            headers={"x-token": "test-token"},
            query_params={"id": "window-abc"},
        )
        response = asyncio.run(route.endpoint(request))

        async def consume_until_shutdown():
            first = await response.body_iterator.__anext__()
            self.assertEqual(first, b": connected\n\n")
            quit_event.set()
            with self.assertRaises(StopAsyncIteration):
                await response.body_iterator.__anext__()

        asyncio.run(consume_until_shutdown())
        self.assertEqual(started, ["window-abc"])
        self.assertEqual(ended, ["window-abc"])

    def test_quit_response_is_returned_before_shutdown_is_scheduled(self):
        app = create_app(
            autoclip.AppRoutes,
            token=autoclip.TOKEN,
            quit_event=autoclip.QUIT,
            begin_window_lease=autoclip.begin_window_lease,
            end_window_lease=autoclip.end_window_lease,
            find_clip_path=autoclip.find_clip_path,
            clip_regex=autoclip.CLIP_RE,
            product_name=autoclip.PRODUCT_NAME,
            version=autoclip.APP_VERSION,
        )
        autoclip.QUIT.clear()
        core = SimpleNamespace(stop=MagicMock(return_value={"ok": True}),
                               stop_all_creators=MagicMock())
        timer = MagicMock()
        with patch.object(autoclip, "CORE", core), \
             patch.object(autoclip, "cancel_window_close_shutdown"), \
             patch.object(autoclip.threading, "Timer", return_value=timer) as timer_factory:
            status, _headers, body = asyncio.run(asgi_request(
                app,
                method="POST",
                path="/api/quit",
                headers={"X-Token": autoclip.TOKEN, "Content-Type": "application/json"},
                body=b"{}",
            ))

        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"ok": True, "shutting_down": True})
        core.stop.assert_called_once_with(True)
        core.stop_all_creators.assert_called_once_with()
        timer_factory.assert_called_once_with(0.8, autoclip.QUIT.set)
        timer.start.assert_called_once_with()
        self.assertFalse(autoclip.QUIT.is_set())
        autoclip.QUIT.clear()

    def test_window_closing_route_releases_the_specific_browser_window(self):
        app = create_app(
            autoclip.AppRoutes,
            token=autoclip.TOKEN,
            quit_event=autoclip.QUIT,
            begin_window_lease=autoclip.begin_window_lease,
            end_window_lease=autoclip.end_window_lease,
            find_clip_path=autoclip.find_clip_path,
            clip_regex=autoclip.CLIP_RE,
            product_name=autoclip.PRODUCT_NAME,
            version=autoclip.APP_VERSION,
        )
        payload = json.dumps({"id": "window-close-route"}).encode("utf-8")
        with patch.object(autoclip, "close_window_lease") as close_lease:
            status, _headers, body = asyncio.run(asgi_request(
                app,
                method="POST",
                path="/api/window/closing?id=window-close-route",
                headers={"X-Token": autoclip.TOKEN, "Content-Type": "application/json"},
                body=payload,
            ))
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"ok": True})
        close_lease.assert_called_once_with("window-close-route")

    def test_shared_config_route_is_served_by_fastapi(self):
        app = create_app(
            autoclip.AppRoutes,
            token=autoclip.TOKEN,
            quit_event=autoclip.QUIT,
            begin_window_lease=autoclip.begin_window_lease,
            end_window_lease=autoclip.end_window_lease,
            find_clip_path=autoclip.find_clip_path,
            clip_regex=autoclip.CLIP_RE,
            product_name=autoclip.PRODUCT_NAME,
            version=autoclip.APP_VERSION,
        )
        status, _headers, body = asyncio.run(asgi_request(app, path="/api/config"))
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertEqual(payload["settings"], autoclip.CORE.default_settings)
        self.assertNotIn("gemini_api_key", payload["ai"])

    def test_health_endpoint_reports_running_api(self):
        app = self.create_app()
        status, headers, body = asyncio.run(asgi_request(app, path="/api/health"))
        self.assertEqual(status, 200)
        self.assertEqual(headers["content-type"].split(";")[0], "application/json")
        self.assertEqual(json.loads(body)["status"], "ok")

    def test_existing_get_routes_are_forwarded_to_legacy_handler(self):
        app = self.create_app()
        status, _headers, body = asyncio.run(asgi_request(app, path="/api/legacy?since=12"))
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"legacy": "get", "path": "/api/legacy?since=12"})

    def test_existing_post_routes_keep_body_and_token_header(self):
        app = self.create_app()
        payload = b'{"target":"https://example.invalid/live"}'
        status, _headers, body = asyncio.run(asgi_request(
            app, method="POST", path="/api/legacy",
            headers={"X-Token": "test-token", "Content-Type": "application/json"},
            body=payload,
        ))
        self.assertEqual(status, 201)
        self.assertEqual(body, payload)

    def test_non_loopback_host_is_rejected(self):
        app = self.create_app()
        status, _headers, body = asyncio.run(asgi_request(
            app, headers={"Host": "evil.example"}
        ))
        self.assertEqual(status, 403)
        self.assertIn(b"local", body.lower())

    def test_clip_text_route_rejects_oversized_untrusted_names_without_path_lookup(self):
        lookup = MagicMock(return_value=None)
        app = self.create_app(find_clip_path=lookup)
        oversized_name = ("a" * 512) + ".txt"

        status, _headers, body = asyncio.run(asgi_request(app, path=f"/clips/{oversized_name}"))

        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body), {"error": "not found"})
        lookup.assert_not_called()

    def test_clip_range_requests_stream_only_the_requested_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            clip = Path(directory) / "sample.mp4"
            clip.write_bytes(b"0123456789")
            app = self.create_app(find_clip_path=lambda _name: clip)
            status, headers, body = asyncio.run(asgi_request(
                app, path="/clips/sample.mp4", headers={"Range": "bytes=2-5"}
            ))
        self.assertEqual(status, 206)
        self.assertEqual(headers["content-range"], "bytes 2-5/10")
        self.assertEqual(headers["content-length"], "4")
        self.assertEqual(body, b"2345")


    def test_proactor_connection_reset_patch_is_windows_only(self):
        import asyncio.proactor_events
        import api_server

        transport_base = asyncio.proactor_events._ProactorBasePipeTransport
        original = transport_base._call_connection_lost
        with patch.object(api_server.os, "name", "posix"):
            self.assertFalse(api_server.patch_windows_proactor_connection_reset())
        self.assertIs(transport_base._call_connection_lost, original)

    def test_windows_proactor_peer_reset_finishes_transport_cleanup(self):
        import asyncio.proactor_events
        import api_server

        transport_base = asyncio.proactor_events._ProactorBasePipeTransport
        original = transport_base._call_connection_lost
        self.addCleanup(setattr, transport_base, "_call_connection_lost", original)

        class FakeSocket:
            closed = False

            def fileno(self):
                return 123

            def shutdown(self, _how):
                raise ConnectionResetError(10054, "peer reset during shutdown")

            def close(self):
                self.closed = True

        class FakeProtocol:
            error = None

            def connection_lost(self, error):
                self.error = error

        class FakeServer:
            detached = False

            def _detach(self, _transport):
                self.detached = True

        class FakeTransport(transport_base):
            def __del__(self):
                pass

        transport = object.__new__(FakeTransport)
        fake_protocol = FakeProtocol()
        fake_socket = FakeSocket()
        fake_server = FakeServer()
        transport._called_connection_lost = False
        transport._protocol = fake_protocol
        transport._sock = fake_socket
        transport._server = fake_server

        with patch.object(api_server.os, "name", "nt"):
            self.assertTrue(api_server.patch_windows_proactor_connection_reset())

        transport_base._call_connection_lost(transport, None)

        self.assertTrue(fake_socket.closed)
        self.assertTrue(fake_protocol.error is None)
        self.assertTrue(fake_server.detached)
        self.assertTrue(transport._sock is None)
        self.assertTrue(transport._server is None)
        self.assertTrue(transport._called_connection_lost)
        self.assertTrue(transport_base._call_connection_lost is not original)

if __name__ == "__main__":
    unittest.main()
