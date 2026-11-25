"""Visible persistent-browser automation for preparing social video uploads.

The user signs into the StreamSnip publishing browser once. This module attaches
local files through Playwright and verifies the form before reporting Ready.
It never clicks a platform's final Publish button.
"""
from __future__ import annotations

import os
import time
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

def upload_url(platform: str) -> str:
    key = str(platform).strip().lower()
    if key not in UPLOAD_URLS:
        raise BrowserAutomationError("Unsupported posting platform: " + key)
    return UPLOAD_URLS[key]

def _browser_executable() -> tuple[str, str]:
    """Use installed Chrome/Edge, keeping a separate persistent publishing profile."""
    candidates: list[tuple[str, str]] = []
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice") as key:
                prog_id = str(winreg.QueryValueEx(key, "ProgId")[0]).lower()
            if "chrome" in prog_id:
                candidates.append(("Google Chrome", os.path.join(os.environ.get("PROGRAMFILES", r"C:\Program Files"), "Google", "Chrome", "Application", "chrome.exe")))
            elif "edge" in prog_id or "microsoft" in prog_id:
                candidates.append(("Microsoft Edge", os.path.join(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"), "Microsoft", "Edge", "Application", "msedge.exe")))
        except (OSError, ImportError):
            pass
        candidates.extend([
            ("Google Chrome", r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
            ("Google Chrome", os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "Application", "chrome.exe")),
            ("Microsoft Edge", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
            ("Microsoft Edge", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        ])
    else:
        import shutil
        for name in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge"):
            found = shutil.which(name)
            if found:
                candidates.append((name, found))
    seen: set[str] = set()
    for name, path in candidates:
        key = os.path.normcase(path)
        if key not in seen and os.path.isfile(path):
            return name, path
        seen.add(key)
    raise BrowserAutomationError("Chrome or Edge is required for verified browser upload automation. Install one, then try again.")

class BrowserAutomationManager:
    """Controls a visible Chrome/Edge profile dedicated to StreamSnip publishing."""
    def __init__(self, profile_dir: Path | None = None, *_: Any, **__: Any):
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "StreamSnip AI"
        self.profile_dir = Path(profile_dir) if profile_dir else root / "publishing-browser-profile"
        self._playwright = None
        self._context = None
        self._page = None
        self._browser_name = ""
        self._prepared: dict[str, Any] | None = None
        self._commands: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        self._worker_ready = threading.Event()

    def _worker_loop(self):
        self._worker_ready.set()
        while True:
            task = self._commands.get()
            if task is None:
                return
            function, args, kwargs, completed, result = task
            try:
                result["value"] = function(*args, **kwargs)
            except BaseException as exc:
                result["error"] = exc
            finally:
                completed.set()

    def _run_worker(self, function, *args, **kwargs):
        if threading.current_thread() is self._worker:
            return function(*args, **kwargs)
        if not self._worker or not self._worker.is_alive():
            self._worker_ready.clear()
            self._worker = threading.Thread(target=self._worker_loop, name="StreamSnipPublisher", daemon=True)
            self._worker.start()
            self._worker_ready.wait(10)
        completed = threading.Event()
        result: dict[str, Any] = {}
        self._commands.put((function, args, kwargs, completed, result))
        if not completed.wait(240):
            raise BrowserAutomationError("Browser automation timed out. Check the opened browser and retry.")
        if "error" in result:
            raise result["error"]
        return result.get("value")

    def _ensure_browser(self):
        if self._context and self._page:
            try:
                if not self._page.is_closed():
                    return self._page
            except Exception:
                pass
        try:
            from playwright.sync_api import sync_playwright
            self._browser_name, executable = _browser_executable()
            self._playwright = sync_playwright().start()
            self.profile_dir.mkdir(parents=True, exist_ok=True)
            self._context = self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir), executable_path=executable,
                headless=False, viewport=None,
                args=["--no-first-run", "--no-default-browser-check"],
            )
            self._page = self._context.pages[0] if self._context.pages else self._context.new_page()
            return self._page
        except BrowserAutomationError:
            raise
        except Exception as exc:
            self._close_browser()
            raise BrowserAutomationError(f"Could not start the StreamSnip publishing browser: {exc}") from exc

    @staticmethod
    def _find_file_input(page):
        inputs = page.locator('input[type="file"]')
        try:
            total = inputs.count()
        except Exception:
            total = 0
        if not total:
            return None
        for index in range(total):
            item = inputs.nth(index)
            accept = (item.get_attribute("accept") or "").lower()
            if "video" in accept or not accept:
                return item
        return inputs.first

    @staticmethod
    def _visible_locator(page, selectors):
        for selector in selectors:
            locator = page.locator(selector)
            try:
                count = min(locator.count(), 8)
                for index in range(count):
                    candidate = locator.nth(index)
                    if candidate.is_visible() and candidate.is_enabled():
                        return candidate
            except Exception:
                continue
        return None

    @classmethod
    def _fill_text(cls, locator, value: str) -> bool:
        if locator is None:
            return False
        try:
            locator.fill(value, timeout=5000)
            actual = locator.input_value(timeout=2000)
        except Exception:
            try:
                locator.fill(value, timeout=5000)
                actual = locator.inner_text(timeout=2000)
            except Exception:
                return False
        return str(actual).strip() == str(value).strip()

    @classmethod
    def _attach_and_fill(cls, page, *, video_path: Path, platform: str, title: str, description: str) -> dict[str, Any]:
        file_input = cls._find_file_input(page)
        if file_input is None:
            raise BrowserAutomationError("The platform upload form is not available yet. Sign in in the StreamSnip browser, then retry.")
        try:
            file_input.set_input_files(str(video_path), timeout=15000)
            attached = file_input.evaluate("el => !!(el.files && el.files.length && el.files[0].name)")
            attached_name = file_input.evaluate("el => el.files && el.files[0] ? el.files[0].name : ''")
            attached_size = file_input.evaluate("el => el.files && el.files[0] ? el.files[0].size : 0")
        except Exception as exc:
            raise BrowserAutomationError(f"Could not attach the clip to the platform upload form: {exc}") from exc
        if not attached or attached_name != video_path.name or not attached_size:
            raise BrowserAutomationError("The platform did not retain the selected video file; upload was not prepared.")

        platform = platform.lower()
        title = str(title or video_path.stem).strip()[:100]
        description = str(description or "").strip()[:5000]
        title_filled = False
        description_filled = False
        if platform == "youtube":
            title_field = cls._visible_locator(page, [
                '#title-textarea [contenteditable="true"]', '#title-textarea #textbox',
                '#title-textarea textarea', '#title-textarea',
                'input[aria-label*="title" i]', 'textarea[aria-label*="title" i]',
                'input[placeholder*="title" i]', 'textarea[placeholder*="title" i]',
            ])
            description_field = cls._visible_locator(page, [
                '#description-textarea [contenteditable="true"]', '#description-textarea #textbox',
                '#description-textarea textarea', '#description-textarea',
                'textarea[aria-label*="description" i]', 'textarea[placeholder*="description" i]',
                '[contenteditable="true"][aria-label*="description" i]',
            ])
            title_filled = cls._fill_text(title_field, title)
            description_filled = cls._fill_text(description_field, description)
        else:
            caption = (title + ("\n\n" + description if description else "")).strip()
            caption_field = cls._visible_locator(page, [
                'textarea[aria-label*="caption" i]', 'textarea[placeholder*="caption" i]',
                '[contenteditable="true"][aria-label*="caption" i]',
                '[contenteditable="true"][role="textbox"]',
                'textarea[aria-label*="description" i]', 'textarea[placeholder*="description" i]',
                'div[contenteditable="true"]', 'textarea',
            ])
            caption_filled = cls._fill_text(caption_field, caption)
            # These platforms have a single caption/description field. Both generated
            # pieces are included and verified in that one field.
            title_filled = caption_filled and title in caption
            description_filled = caption_filled and (not description or description in caption)
        if not title_filled or not description_filled:
            missing = []
            if not title_filled: missing.append("title")
            if not description_filled: missing.append("description/caption")
            raise BrowserAutomationError("Video attached, but could not verify the " + " and ".join(missing) + " field(s). Review the open browser form; this is not marked Ready.")
        return {
            "platform": platform, "file": video_path.name, "opened_in_streamsnip_browser": True,
            "file_selected": True, "attached_file_name": attached_name, "attached_file_size": attached_size,
            "title_filled": True, "description_filled": True, "ready_for_review": True,
            "ready": True, "manual_video_selection_required": False,
            "title": title, "description": description,
            "publish_button_clicked": False,
        }

    def _status_impl(self) -> dict[str, Any]:
        active = bool(self._context and self._page and not self._page.is_closed())
        return {
            "available": True, "session_active": active,
            "browser": self._browser_name or "Installed Chrome/Edge",
            "mode": "persistent_automation_profile", "profile_dir": str(self.profile_dir),
            "prepared": dict(self._prepared) if self._prepared else None,
            "dedicated_profile": True, "requires_manual_video_selection": False,
            "requires_final_publish_click": True,
        }

    def status(self) -> dict[str, Any]:
        if self._worker and self._worker.is_alive():
            return self._run_worker(self._status_impl)
        return {
            "available": True, "session_active": False, "browser": "Installed Chrome/Edge",
            "mode": "persistent_automation_profile", "profile_dir": str(self.profile_dir),
            "prepared": None, "dedicated_profile": True,
            "requires_manual_video_selection": False, "requires_final_publish_click": True,
        }

    def prepare(self, *, video_path: Path, platform: str, title: str, description: str, browser: str = "default") -> dict[str, Any]:
        target = upload_url(platform)
        path = Path(video_path).resolve()
        if not path.is_file() or path.suffix.lower() not in {".mp4", ".mov", ".m4v", ".webm"}:
            raise BrowserAutomationError("The selected clip is missing or is not a supported video file.")
        return self._run_worker(self._prepare_in_browser, path, platform, title, description)

    def _prepare_in_browser(self, path: Path, platform: str, title: str, description: str) -> dict[str, Any]:
        target = upload_url(platform)
        page = self._ensure_browser()
        try:
            page.bring_to_front()
            page.goto(target, wait_until="domcontentloaded", timeout=45000)
            # Allow the user to sign in in this visible profile. The login session
            # persists, and this same page continues into the upload workflow.
            deadline = time.monotonic() + 180
            file_input = None
            while time.monotonic() < deadline:
                file_input = self._find_file_input(page)
                if file_input is not None:
                    break
                page.wait_for_timeout(1000)
            if file_input is None:
                raise BrowserAutomationError("Upload form did not become available after waiting for sign-in. Sign in in the opened StreamSnip browser and click Prepare again.")
            page.wait_for_timeout(1000)
            # Give upload-processing pages time to render their metadata controls.
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if platform.lower() == "youtube":
                    title_ready = self._visible_locator(page, ["#title-textarea", 'input[aria-label*="title" i]', 'textarea[aria-label*="title" i]'])
                    desc_ready = self._visible_locator(page, ["#description-textarea", 'textarea[aria-label*="description" i]'])
                    if title_ready and desc_ready:
                        break
                else:
                    caption_ready = self._visible_locator(page, ['textarea[aria-label*="caption" i]', 'textarea[placeholder*="caption" i]', '[contenteditable="true"][aria-label*="caption" i]', '[contenteditable="true"][role="textbox"]', 'textarea[aria-label*="description" i]', 'textarea[placeholder*="description" i]', 'div[contenteditable="true"]', 'textarea'])
                    if caption_ready:
                        break
                page.wait_for_timeout(750)
            result = self._attach_and_fill(page, video_path=path, platform=platform, title=title, description=description)
            self._prepared = dict(result)
            return dict(result)
        except BrowserAutomationError:
            raise
        except Exception as exc:
            raise BrowserAutomationError(f"Upload preparation failed; the app did not mark it Ready: {exc}") from exc

    def _close_browser(self):
        context, playwright = self._context, self._playwright
        self._context = self._page = self._playwright = None
        try:
            if context:
                context.close()
        except Exception:
            pass
        try:
            if playwright:
                playwright.stop()
        except Exception:
            pass
        self._prepared = None
        return {"ok": True}

    def close(self):
        if self._worker and self._worker.is_alive():
            try:
                self._run_worker(self._close_browser)
            finally:
                self._commands.put(None)
                self._worker.join(timeout=5)
                self._worker = None
        else:
            self._close_browser()
        return {"ok": True}

    def stop(self):
        return self.close()
