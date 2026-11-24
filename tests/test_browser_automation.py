import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from browser_automation import BrowserAutomationError, BrowserAutomationManager, upload_url


class BrowserAutomationTests(unittest.TestCase):
    def test_platform_upload_routes(self):
        self.assertEqual(upload_url("youtube"), "https://www.youtube.com/upload")
        self.assertEqual(upload_url("instagram"), "https://www.instagram.com/create/select/")
        self.assertEqual(upload_url("facebook"), "https://www.facebook.com/reels/create/")
        self.assertEqual(upload_url("tiktok"), "https://www.tiktok.com/upload")

    def test_unknown_platform_is_rejected(self):
        with self.assertRaises(BrowserAutomationError):
            upload_url("unknown-social-site")

    def test_manual_post_opens_os_default_browser_without_profile_or_playwright(self):
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "clip.mp4"
            video.write_bytes(b"test video")
            manager = BrowserAutomationManager(Path(directory) / "must-not-be-created")
            with patch("browser_automation.webbrowser.open", return_value=True) as open_url:
                result = manager.prepare(
                    video_path=video,
                    platform="youtube",
                    title="Test title",
                    description="Test description",
                    browser="firefox",  # Legacy UI value must be ignored.
                )
            open_url.assert_called_once_with("https://www.youtube.com/upload", new=2, autoraise=True)
            self.assertTrue(result["opened_in_default_browser"])
            self.assertFalse(result["file_selected"])
            self.assertTrue(result["manual_video_selection_required"])
            self.assertFalse((Path(directory) / "must-not-be-created").exists())

    def test_status_explicitly_reports_no_dedicated_profile(self):
        manager = BrowserAutomationManager(Path("unused"))
        status = manager.status()
        self.assertTrue(status["available"])
        self.assertFalse(status["session_active"])
        self.assertFalse(status["dedicated_profile"])
        self.assertEqual(status["mode"], "system_default")

    def test_browser_open_failure_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "clip.mp4"
            video.write_bytes(b"test video")
            manager = BrowserAutomationManager()
            with patch("browser_automation.webbrowser.open", return_value=False):
                with self.assertRaises(BrowserAutomationError):
                    manager.prepare(video_path=video, platform="youtube", title="", description="")


if __name__ == "__main__":
    unittest.main()
