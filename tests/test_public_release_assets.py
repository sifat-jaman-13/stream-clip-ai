from pathlib import Path
import re
import unittest
from html.parser import HTMLParser

ROOT = Path(__file__).resolve().parents[1]


class PageInspector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.images = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if "id" in values:
            self.ids.append(values["id"])
        if tag == "img":
            self.images.append(values)
        if tag == "a" and values.get("href", "").startswith("#"):
            self.links.append(values["href"][1:])


class PublicReleaseAssetTests(unittest.TestCase):
    def test_landing_page_is_declared_as_software_and_uses_real_local_images(self):
        html_path = ROOT / "docs" / "index.html"
        html = html_path.read_text(encoding="utf-8")
        self.assertIn('<html lang="en" data-type="software">', html)
        self.assertIn('<meta name="page-type" content="software">', html)
        self.assertIn('<meta name="site-kind" content="software">', html)
        self.assertIn('@media (max-width: 900px)', html)
        self.assertIn('class="nav-download-mobile"', html)
        self.assertIn('id="menu-toggle"', html)
        parser = PageInspector()
        parser.feed(html)
        self.assertEqual(len(parser.ids), len(set(parser.ids)), "Landing page contains duplicate IDs.")
        self.assertTrue(parser.images, "Landing page should show real product images.")
        for image in parser.images:
            self.assertIn("alt", image, f"Image has no alt text: {image}")
            src = image.get("src", "")
            if src.startswith("./"):
                self.assertTrue((html_path.parent / src[2:]).is_file(), f"Missing local image: {src}")
        for anchor in parser.links:
            self.assertIn(f'id="{anchor}"', html, f"Broken in-page link: #{anchor}")

    def test_readme_screenshots_exist_and_feature_truth_is_clear(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for image in re.findall(r'src="(docs/assets/product/[^"]+)"', readme):
            self.assertTrue((ROOT / image).is_file(), f"Missing README screenshot: {image}")
        self.assertIn("Facebook", readme)
        self.assertIn("Instagram", readme)
        self.assertIn("YouTube", readme)
        self.assertIn("TikTok is not a supported destination", readme)
        self.assertIn("local multi-frame facecam detection", readme)

    def test_third_party_notices_are_scoped_and_packaged(self):
        notices = ROOT / "licenses" / "third-party"
        self.assertTrue((notices / "YuNet-MIT.txt").is_file())
        self.assertTrue((notices / "JetBrains-Mono-OFL.txt").is_file())
        self.assertTrue((notices / "README.md").is_file())
        self.assertFalse((ROOT / "LICENSE-NeonClipping.txt").exists())
        self.assertFalse((ROOT / "LICENSE-YuNet.txt").exists())
        installer = (ROOT / "installer" / "StreamSnipNative.iss").read_text(encoding="utf-8")
        self.assertIn('LICENSE"; DestDir: "{app}"', installer)
        self.assertIn('..\\licenses\\third-party\\*', installer)
        self.assertIn('DestDir: "{app}\\licenses\\third-party"', installer)
        spec = (ROOT / "AutoClip.spec").read_text(encoding="utf-8")
        self.assertIn("licenses/third-party/YuNet-MIT.txt", spec)
        self.assertIn("licenses/third-party/JetBrains-Mono-OFL.txt", spec)
        self.assertNotIn("NeonClipping", spec + installer)
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("!models/face_detection_yunet_2023mar.onnx", gitignore)
        self.assertIn("custom_words.txt", gitignore)

    def test_release_version_is_consistent(self):
        self.assertIn('APP_VERSION = "4.0.6"', (ROOT / "autoclip.py").read_text(encoding="utf-8"))
        self.assertIn('version = "4.0.6"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertIn('#define MyAppVersion "4.0.6"', (ROOT / "installer" / "StreamSnipNative.iss").read_text(encoding="utf-8"))
        self.assertIn('Version="4.0.6.0"', (ROOT / "desktop" / "StreamSnip.Desktop" / "Package.appxmanifest").read_text(encoding="utf-8-sig"))


if __name__ == "__main__":
    unittest.main()
