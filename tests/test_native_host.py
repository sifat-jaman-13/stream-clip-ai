import unittest
from unittest.mock import patch

import autoclip


class NativeHostLaunchTests(unittest.TestCase):
    def test_native_host_does_not_open_a_browser_window(self):
        with patch.dict(autoclip.os.environ, {"STREAMSNIP_NATIVE_HOST": "1"}):
            self.assertFalse(autoclip.should_open_browser_window("127.0.0.1"))
            self.assertFalse(autoclip.should_open_browser_window("localhost"))

    def test_regular_loopback_desktop_mode_keeps_browser_window(self):
        with patch.dict(autoclip.os.environ, {}, clear=False):
            autoclip.os.environ.pop("STREAMSNIP_NATIVE_HOST", None)
            self.assertTrue(autoclip.should_open_browser_window("127.0.0.1"))

    def test_non_loopback_bind_never_opens_a_browser_window(self):
        with patch.dict(autoclip.os.environ, {}, clear=False):
            autoclip.os.environ.pop("STREAMSNIP_NATIVE_HOST", None)
            self.assertFalse(autoclip.should_open_browser_window("0.0.0.0"))


if __name__ == "__main__":
    unittest.main()
