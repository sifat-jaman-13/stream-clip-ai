import unittest
import threading
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


    def test_playwright_work_is_dispatched_to_one_worker_thread(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = BrowserAutomationManager(Path(directory) / "profiles")
            caller_thread = threading.get_ident()
            observed = {}
            async def fake_prepare(**kwargs):
                observed["thread"] = threading.get_ident()
                return {"ready_for_review": True}
            with patch.object(manager, "_prepare_unlocked", side_effect=fake_prepare):
                result = manager._dispatch("prepare", {"video_path": Path("unused")})
            self.assertTrue(result["ready_for_review"])
            self.assertNotEqual(observed["thread"], caller_thread)
            manager.stop()

    def test_unknown_platform_is_rejected(self):
        with self.assertRaises(BrowserAutomationError):
            upload_url("unknown-social-site")

if __name__ == "__main__":
    unittest.main()
