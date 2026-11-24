"""Local, review-first browser upload preparation for StreamSnip AI."""
from __future__ import annotations

import asyncio
import os
import queue
import threading
from pathlib import Path
from typing import Any

UPLOAD_URLS = {
    "youtube": "https://www.youtube.com/upload",
    "instagram": "https://www.instagram.com/create/select/",
    "facebook": "https://www.facebook.com/reels/create/",
    "tiktok": "https://www.tiktok.com/upload",
}

class BrowserAutomationError(RuntimeError):
    pass

def detect_default_browser() -> str:
    """Best-effort default browser detection on Windows; Chrome elsewhere."""
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice",
            ) as key:
                prog_id = winreg.QueryValueEx(key, "ProgId")[0].lower()
            if "firefox" in prog_id:
                return "firefox"
            if "edge" in prog_id or "microsoft" in prog_id:
                return "edge"
            if "chrome" in prog_id:
                return "chrome"
        except (OSError, ImportError):
            pass
        return "edge"
    return "chrome"

def upload_url(platform: str) -> str:
    key = str(platform).strip().lower()
    if key not in UPLOAD_URLS:
        raise BrowserAutomationError("Unsupported manual posting platform: " + key)
    return UPLOAD_URLS[key]

class BrowserAutomationManager:
    """Owns Playwright on one async event-loop thread; HTTP requests may arrive on any thread."""
    def __init__(self, profile_root: Path):
        self.profile_root = Path(profile_root)
        self._commands: queue.Queue = queue.Queue()
        self._state_lock = threading.RLock()
        self._playwright = None
        self._context = None
        self._page = None
        self._browser = ""
        self._prepared: dict[str, Any] | None = None
        self._worker = threading.Thread(target=self._worker_main, daemon=True,
                                        name="streamsnip-browser-automation")
        self._worker.start()

    def _worker_main(self):
        asyncio.run(self._worker_loop())

    async def _worker_loop(self):
        while True:
            operation, arguments, completed, result = await asyncio.to_thread(self._commands.get)
            try:
                if operation == "prepare":
                    result["value"] = await self._prepare_unlocked(**arguments)
                elif operation == "close":
                    await self._close_unlocked()
                    result["value"] = {"ok": True}
                elif operation == "stop":
                    await self._close_unlocked()
                    result["value"] = {"ok": True}
                    completed.set()
                    return
                else:
                    raise BrowserAutomationError("Unknown browser automation operation.")
            except Exception as exc:
                result["error"] = exc
            finally:
                completed.set()

    def _dispatch(self, operation: str, arguments: dict[str, Any] | None = None,
                  timeout: float = 120.0):
        completed = threading.Event()
        result: dict[str, Any] = {}
        self._commands.put((operation, arguments or {}, completed, result))
        if not completed.wait(timeout):
            raise BrowserAutomationError("Browser automation timed out. Check the browser window before retrying.")
        if "error" in result:
            raise result["error"]
        return result.get("value")

    def status(self) -> dict[str, Any]:
        try:
            from playwright.async_api import async_playwright  # noqa: F401
            package_available = True
        except ImportError:
            package_available = False
        with self._state_lock:
            return {
                "available": package_available,
                "session_active": self._context is not None,
                "browser": self._browser or detect_default_browser(),
                "prepared": dict(self._prepared) if self._prepared else None,
                "profile_dir": str(self.profile_root),
                "requires_final_publish_click": True,
            }

    async def _open(self, browser: str):
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise BrowserAutomationError(
                "Browser automation is not installed. Install the Playwright dependency, then restart StreamSnip AI."
            ) from exc

        selected = browser if browser in {"chrome", "edge", "firefox"} else detect_default_browser()
        self.profile_root.mkdir(parents=True, exist_ok=True)
        self._playwright = await async_playwright().start()
        try:
            if selected == "firefox":
                self._context = await self._playwright.firefox.launch_persistent_context(
                    str(self.profile_root / "firefox"), headless=False)
            else:
                channel = "chrome" if selected == "chrome" else "msedge"
                self._context = await self._playwright.chromium.launch_persistent_context(
                    str(self.profile_root / selected), channel=channel, headless=False)
        except Exception as exc:
            await self._close_unlocked()
            raise BrowserAutomationError(
                f"Could not launch {selected}. Check that it is installed; Firefox also needs the Playwright Firefox runtime."
            ) from exc
        self._browser = selected
        self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()

    @staticmethod
    async def _fill_first(page, selectors: tuple[str, ...], value: str) -> bool:
        if not value:
            return True
        for selector in selectors:
            try:
                locator = page.locator(selector).first
                if await locator.count() and await locator.is_visible():
                    await locator.fill(value, timeout=1800)
                    return True
            except Exception:
                continue
        return False

    def prepare(self, *, video_path: Path, platform: str, title: str,
                description: str, browser: str = "default") -> dict[str, Any]:
        target = upload_url(platform)
        path = Path(video_path).resolve()
        if not path.is_file() or path.suffix.lower() not in {".mp4", ".mov", ".m4v", ".webm"}:
            raise BrowserAutomationError("The selected clip is missing or is not a supported video file.")
        selected_browser = detect_default_browser() if browser == "default" else browser
        if selected_browser not in {"chrome", "edge", "firefox"}:
            raise BrowserAutomationError("Choose Chrome, Edge, Firefox, or the Windows default browser.")
        return self._dispatch("prepare", {
            "video_path": path, "platform": platform, "target": target,
            "title": str(title or "")[:100],
            "description": str(description or "")[:5000],
            "browser": selected_browser,
        })

    async def _prepare_unlocked(self, *, video_path: Path, platform: str, target: str,
                                title: str, description: str, browser: str):
        if self._context is not None and self._browser != browser:
            await self._close_unlocked()
        if self._context is None:
            await self._open(browser)
        page = self._page
        try:
            await page.goto(target, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(1500)
            file_inputs = page.locator('input[type="file"]')
            file_selected = bool(await file_inputs.count())
            if file_selected:
                await file_inputs.first.set_input_files(str(video_path), timeout=15000)
            if platform.lower() == "youtube":
                title_filled = await self._fill_first(page, (
                    '#textbox[aria-label*="title" i]', '[contenteditable="true"][aria-label*="title" i]',
                    'input[aria-label*="title" i]', 'textarea[aria-label*="title" i]',
                ), title)
                description_filled = await self._fill_first(page, (
                    '#textbox[aria-label*="description" i]', '[contenteditable="true"][aria-label*="description" i]',
                    'textarea[aria-label*="description" i]',
                ), description)
            else:
                # Instagram, Facebook Reels, and TikTok primarily expose one caption field.
                caption = "\n\n".join(part for part in (title, description) if part)
                caption_filled = await self._fill_first(page, (
                    'textarea[aria-label*="caption" i]', 'textarea[placeholder*="caption" i]',
                    '[contenteditable="true"][aria-label*="caption" i]',
                    '[contenteditable="true"][data-placeholder*="caption" i]',
                    'textarea[aria-label*="description" i]',
                ), caption)
                title_filled = caption_filled
                description_filled = caption_filled
            self._prepared = {
                "platform": platform.lower(), "file": video_path.name,
                "file_selected": file_selected, "title_filled": title_filled,
                "description_filled": description_filled,
                "ready_for_review": file_selected,
            }
            return dict(self._prepared)
        except Exception as exc:
            raise BrowserAutomationError(f"Could not prepare the {platform} upload: {exc}") from exc

    def close(self):
        self._dispatch("close")

    def stop(self):
        if self._worker.is_alive():
            self._dispatch("stop")
            self._worker.join(timeout=5)

    async def _close_unlocked(self):
        try:
            if self._context is not None:
                await self._context.close()
        except Exception:
            pass
        self._context = self._page = None
        self._prepared = None
        self._browser = ""
        try:
            if self._playwright is not None:
                await self._playwright.stop()
        except Exception:
            pass
        self._playwright = None
