import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from browser_automation import BrowserAutomationError, BrowserAutomationManager, upload_url


class FakeLocator:
    def __init__(self, kind="other", page=None):
        self.kind = kind
        self.page = page
        self.value = ""
        self.file = None
    def count(self): return 0 if self.kind == "empty" else 1
    def nth(self, index): return self
    @property
    def first(self): return self
    def get_attribute(self, name): return "video/mp4" if name == "accept" and self.kind == "file" else None
    def is_visible(self): return True
    def is_enabled(self): return True
    def set_input_files(self, path, timeout=None): self.file = Path(path)
    def evaluate(self, expression):
        if "files[0].name" in expression: return self.file.name if self.file else ""
        if "files[0].size" in expression: return self.file.stat().st_size if self.file else 0
        if "files.length" in expression: return bool(self.file and self.file.stat().st_size)
        return None
    def fill(self, value, timeout=None): self.value = value
    def input_value(self, timeout=None): return self.value
    def inner_text(self, timeout=None): return self.value

class FakePage:
    def __init__(self, *, caption=True, title=True, description=True):
        self.file = FakeLocator("file", self)
        self.fields = {
            "title": FakeLocator("title", self) if title else None,
            "description": FakeLocator("description", self) if description else None,
            "caption": FakeLocator("caption", self) if caption else None,
        }
        self.closed = False
    def locator(self, selector):
        if selector == 'input[type="file"]': return self.file
        if selector in ("#title-textarea",) or "title" in selector.lower():
            return self.fields["title"] or FakeLocator("empty", self)
        if "description" in selector.lower():
            return self.fields["description"] or FakeLocator("empty", self)
        if "caption" in selector.lower() or "contenteditable" in selector.lower() or selector == "textarea":
            return self.fields["caption"] or FakeLocator("empty", self)
        return FakeLocator("empty", self)
    def bring_to_front(self): pass
    def goto(self, *args, **kwargs): pass
    def wait_for_timeout(self, ms): pass
    def is_closed(self): return self.closed

class BrowserAutomationTests(unittest.TestCase):
    def test_platform_upload_routes(self):
        self.assertEqual(upload_url("youtube"), "https://www.youtube.com/upload")
        self.assertEqual(upload_url("instagram"), "https://www.instagram.com/create/select/")
        self.assertEqual(upload_url("facebook"), "https://www.facebook.com/reels/create/")
        self.assertEqual(upload_url("tiktok"), "https://www.tiktok.com/upload")

    def test_unknown_platform_is_rejected(self):
        with self.assertRaises(BrowserAutomationError): upload_url("unknown")

    def test_all_platforms_attach_real_file_and_verify_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "sample.mp4"
            video.write_bytes(b"valid test video bytes")
            for platform in ("youtube", "facebook", "instagram", "tiktok"):
                with self.subTest(platform=platform):
                    page = FakePage()
                    result = BrowserAutomationManager._attach_and_fill(
                        page, video_path=video, platform=platform,
                        title="Generated title", description="Generated description")
                    self.assertTrue(result["ready_for_review"])
                    self.assertTrue(result["file_selected"])
                    self.assertEqual(result["attached_file_name"], video.name)
                    self.assertGreater(result["attached_file_size"], 0)
                    self.assertTrue(result["title_filled"])
                    self.assertTrue(result["description_filled"])
                    self.assertFalse(result["manual_video_selection_required"])
                    self.assertFalse(result["publish_button_clicked"])
                    if platform == "youtube":
                        self.assertEqual(page.fields["title"].value, "Generated title")
                        self.assertEqual(page.fields["description"].value, "Generated description")
                    else:
                        self.assertIn("Generated title", page.fields["caption"].value)
                        self.assertIn("Generated description", page.fields["caption"].value)

    def test_missing_caption_field_never_reports_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "sample.mp4"
            video.write_bytes(b"valid test video bytes")
            page = FakePage(caption=False, description=False)
            with self.assertRaises(BrowserAutomationError):
                BrowserAutomationManager._attach_and_fill(
                    page, video_path=video, platform="instagram", title="Title", description="Description")

    def test_prepare_opens_upload_and_returns_verified_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "sample.mp4"
            video.write_bytes(b"valid test video bytes")
            page = FakePage()
            manager = BrowserAutomationManager(Path(directory) / "profile")
            with patch.object(manager, "_ensure_browser", return_value=page):
                result = manager.prepare(video_path=video, platform="youtube", title="Title", description="Description")
            self.assertTrue(result["ready_for_review"])
            self.assertTrue(result["file_selected"])
            self.assertEqual(page.file.file, video)

    def test_status_never_claims_ready_without_verified_prepare(self):
        manager = BrowserAutomationManager(Path("profile"))
        status = manager.status()
        self.assertFalse(status["session_active"])
        self.assertFalse(status["requires_manual_video_selection"])
        self.assertTrue(status["requires_final_publish_click"])
        self.assertIsNone(status["prepared"])

    def test_missing_or_invalid_video_rejected_before_browser_launch(self):
        manager = BrowserAutomationManager()
        with patch.object(manager, "_ensure_browser") as launch:
            with self.assertRaises(BrowserAutomationError):
                manager.prepare(video_path=Path("does-not-exist.mp4"), platform="youtube", title="", description="")
            launch.assert_not_called()

if __name__ == "__main__":
    unittest.main()
