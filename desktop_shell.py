from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

READY_URL = re.compile(r"https?://127\.0\.0\.1:(\d+)/")
APP_NAME = "StreamSnip AI"
LOCAL_ROOT = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / APP_NAME
CONFIG_FILE = LOCAL_ROOT / "desktop-shell.json"
STARTUP_TIMEOUT = 180
SHUTDOWN_TIMEOUT = 25


class DesktopShell:
    """Small pywebview shell for the one local FastAPI + React application."""

    def __init__(self) -> None:
        self.process: subprocess.Popen[str] | None = None
        self.base_url = ""
        self._output: queue.Queue[str] = queue.Queue()
        self._closed = threading.Event()

    @staticmethod
    def _message(title: str, message: str, *, error: bool = True) -> None:
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, message, title, 0x10 if error else 0x40)
        except Exception:
            sys.stderr.write(f"{title}: {message}\n")

    @staticmethod
    def _read_config() -> dict[str, str]:
        if not CONFIG_FILE.is_file():
            raise RuntimeError(
                "The StreamSnip processing runtime is not configured yet.\n\n"
                "Run the StreamSnip AI installer again and choose Repair."
            )
        try:
            raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Could not read the local engine configuration: {exc}") from exc
        if not isinstance(raw, dict):
            raise RuntimeError("The local engine configuration is invalid.")

        config = {str(key): str(value) for key, value in raw.items() if value}
        source = Path(config.get("source_root", "")).resolve()
        python = Path(config.get("python_executable", "")).resolve()
        data = Path(config.get("data_root", str(LOCAL_ROOT / "Library"))).resolve()
        if not (source / "autoclip.py").is_file():
            raise RuntimeError(f"The StreamSnip engine files are missing: {source}")
        if not python.is_file():
            raise RuntimeError(f"The configured Python runtime is missing: {python}")
        data.mkdir(parents=True, exist_ok=True)
        config["source_root"] = str(source)
        config["python_executable"] = str(python)
        config["data_root"] = str(data)
        return config

    def _start_backend(self, config: dict[str, str]) -> None:
        environment = os.environ.copy()
        environment.update({
            "STREAMSNIP_NATIVE_HOST": "1",
            "STREAMSNIP_BIND_HOST": "127.0.0.1",
            "STREAMSNIP_PORT": "0",
            "STREAMSNIP_DATA_DIR": config["data_root"],
            "PYTHONUTF8": "1",
        })
        ffmpeg = config.get("ffmpeg_executable", "")
        if ffmpeg and Path(ffmpeg).is_file():
            ffmpeg = str(Path(ffmpeg).resolve())
            environment["STREAMSNIP_FFMPEG_PATH"] = ffmpeg
            environment["PATH"] = str(Path(ffmpeg).parent) + os.pathsep + environment.get("PATH", "")

        self.process = subprocess.Popen(
            [config["python_executable"], "-u", str(Path(config["source_root"]) / "autoclip.py")],
            cwd=config["source_root"],
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

        def pump_output() -> None:
            assert self.process is not None and self.process.stdout is not None
            for line in self.process.stdout:
                self._output.put(line.rstrip())

        threading.Thread(target=pump_output, name="streamsnip-engine-output", daemon=True).start()

    def _wait_for_backend(self) -> str:
        assert self.process is not None
        deadline = time.monotonic() + STARTUP_TIMEOUT
        output_tail: list[str] = []
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                while True:
                    try:
                        output_tail.append(self._output.get_nowait())
                    except queue.Empty:
                        break
                detail = "\n".join(output_tail[-16:])
                raise RuntimeError(
                    f"The StreamSnip engine exited during startup (code {self.process.returncode}).\n\n{detail}"
                )
            try:
                line = self._output.get(timeout=0.2)
            except queue.Empty:
                continue
            output_tail.append(line)
            output_tail = output_tail[-24:]
            match = READY_URL.search(line)
            if match:
                self.base_url = f"http://127.0.0.1:{match.group(1)}/"
                self._wait_for_health(deadline)
                return self.base_url
        raise TimeoutError(
            f"The StreamSnip engine did not report a ready URL within {STARTUP_TIMEOUT} seconds.\n\n"
            + "\n".join(output_tail[-12:])
        )

    def _wait_for_health(self, deadline: float) -> None:
        last_error = ""
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(self.base_url + "api/health", timeout=2) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                if response.status == 200 and payload.get("status") == "ok":
                    return
            except (OSError, ValueError, urllib.error.URLError) as exc:
                last_error = str(exc)
            time.sleep(0.2)
        raise RuntimeError("The local FastAPI service did not become healthy. " + last_error)

    def _request_backend_quit(self) -> None:
        if not self.base_url:
            return
        try:
            with urllib.request.urlopen(self.base_url + "api/session", timeout=3) as response:
                token = json.loads(response.read().decode("utf-8")).get("token", "")
            if not token:
                return
            request = urllib.request.Request(
                self.base_url + "api/quit",
                data=b"{}",
                headers={"Content-Type": "application/json", "X-Token": str(token)},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                response.read()
        except (OSError, ValueError, urllib.error.URLError):
            # The React Quit button may already have stopped the backend.
            pass

    def _stop_backend(self) -> None:
        process = self.process
        if process is None or process.poll() is not None:
            return
        self._request_backend_quit()
        try:
            process.wait(timeout=SHUTDOWN_TIMEOUT)
        except subprocess.TimeoutExpired:
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    check=False,
                    capture_output=True,
                    timeout=8,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except (OSError, subprocess.TimeoutExpired):
                process.kill()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass

    def run(self) -> int:
        try:
            config = self._read_config()
            self._start_backend(config)
            self._wait_for_backend()

            import webview

            window = webview.create_window(
                APP_NAME,
                self.base_url + "dashboard/",
                width=1440,
                height=960,
                min_size=(980, 660),
                background_color="#0F0F0F",
                text_select=True,
            )
            window.events.closed += lambda: self._closed.set()

            def close_window_when_backend_exits() -> None:
                assert self.process is not None
                while self.process.poll() is None and not self._closed.wait(0.25):
                    pass
                if self.process.poll() is not None and not self._closed.is_set():
                    try:
                        window.destroy()
                    except Exception:
                        pass

            threading.Thread(
                target=close_window_when_backend_exits,
                name="streamsnip-shell-lifecycle",
                daemon=True,
            ).start()
            # WebView2 is the native Windows web runtime, not a separate browser process.
            webview.start(
                gui="edgechromium",
                debug=False,
                private_mode=False,
                storage_path=str(LOCAL_ROOT / "WebView2"),
            )
            self._request_backend_quit()
            return 0
        except Exception as exc:
            self._message(APP_NAME + " could not start", str(exc))
            return 1
        finally:
            self._stop_backend()


def main() -> int:
    return DesktopShell().run()


if __name__ == "__main__":
    raise SystemExit(main())
