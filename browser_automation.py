"""Open social upload pages in the user's existing system-default browser.

This deliberately does not launch Playwright, create browser profiles, automate a
browser session, or attempt to reuse/copy browser cookies. The user chooses the
video and reviews/publishes it in their own normal browser session.
"""
from __future__ import annotations

import os
import webbrowser
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
    """Return a friendly name for the OS URL handler; never launch a private profile."""
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice",
            ) as key:
                prog_id = winreg.QueryValueEx(key, "ProgId")[0].lower()
            if "firefox" in prog_id:
                return "Firefox (default)"
            if "edge" in prog_id or "microsoft" in prog_id:
                return "Microsoft Edge (default)"
            if "chrome" in prog_id:
                return "Google Chrome (default)"
        except (OSError, ImportError):
            pass
    return "System default browser"


def upload_url(platform: str) -> str:
    key = str(platform).strip().lower()
    if key not in UPLOAD_URLS:
        raise BrowserAutomationError("Unsupported manual posting platform: " + key)
    return UPLOAD_URLS[key]


class BrowserAutomationManager:
    """Opens platform pages through the OS default browser without managing a profile."""

    def __init__(self, *_: Any, **__: Any):
        self._prepared: dict[str, Any] | None = None

    def status(self) -> dict[str, Any]:
        return {
            "available": True,
            "session_active": False,
            "browser": detect_default_browser(),
            "mode": "system_default",
            "prepared": dict(self._prepared) if self._prepared else None,
            "dedicated_profile": False,
            "requires_manual_video_selection": True,
            "requires_final_publish_click": True,
        }

    def prepare(
        self,
        *,
        video_path: Path,
        platform: str,
        title: str,
        description: str,
        browser: str = "default",
    ) -> dict[str, Any]:
        target = upload_url(platform)
        path = Path(video_path).resolve()
        if not path.is_file() or path.suffix.lower() not in {".mp4", ".mov", ".m4v", ".webm"}:
            raise BrowserAutomationError("The selected clip is missing or is not a supported video file.")

        # Ignore any legacy browser selector: all manual posting uses the OS default.
        try:
            opened = webbrowser.open(target, new=2, autoraise=True)
        except Exception as exc:
            raise BrowserAutomationError(f"Could not open {platform} in your default browser: {exc}") from exc
        if not opened:
            raise BrowserAutomationError(
                "Windows could not open the upload page. Check your default browser settings and try again."
            )

        self._prepared = {
            "platform": str(platform).lower(),
            "file": path.name,
            "opened_in_default_browser": True,
            "file_selected": False,
            "title_filled": False,
            "description_filled": False,
            "ready_for_review": False,
            "manual_video_selection_required": True,
            "title": str(title or "")[:100],
            "description": str(description or "")[:5000],
        }
        return dict(self._prepared)

    def close(self):
        self._prepared = None
        return {"ok": True}

    def stop(self):
        self.close()
