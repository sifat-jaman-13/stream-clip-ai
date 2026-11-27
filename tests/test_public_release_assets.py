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
        self.assertIn('<html lang="en" data-type="software" data-theme="studio-dark" data-theme-choice="studio-dark">', html)
        self.assertIn('<meta name="page-type" content="software">', html)
        self.assertIn('<meta name="site-kind" content="software">', html)
        css = (ROOT / "docs" / "assets" / "site.css").read_text(encoding="utf-8")
        self.assertRegex(css, r"@media\s*\(max-width:\s*900px\)")
        self.assertIn('class="mobile-menu"', html)
        self.assertIn('class="mobile-download"', html)
        self.assertIn('id="menu-toggle"', html)
        self.assertIn('class="source-link"', html)
        self.assertIn('aria-label="Choose website theme"', html)
        self.assertEqual(html.count('class="theme-option"'), 13)
        social_card = ROOT / "docs" / "assets" / "streamsnipai-social-card.png"
        self.assertTrue(social_card.is_file(), "A raster social card is required for link previews.")
        self.assertIn('property="og:image" content="https://sifat-jaman-13.github.io/stream-clip-ai/assets/streamsnipai-social-card.png"', html)
        self.assertIn('name="twitter:image" content="https://sifat-jaman-13.github.io/stream-clip-ai/assets/streamsnipai-social-card.png"', html)
        parser = PageInspector()
        parser.feed(html)
        self.assertEqual(len(parser.ids), len(set(parser.ids)), "Landing page contains duplicate IDs.")
        self.assertTrue(parser.images, "Landing page should show real product images.")
        for image in parser.images:
            self.assertIn("alt", image, f"Image has no alt text: {image}")
            src = image.get("src", "")
            if not re.match(r"^(?:[a-z][a-z0-9+.-]*:|/|#)", src, re.IGNORECASE):
                local_path = src[2:] if src.startswith("./") else src
                self.assertTrue((html_path.parent / local_path).is_file(), f"Missing local image: {src}")
        for anchor in parser.links:
            self.assertIn(f'id="{anchor}"', html, f"Broken in-page link: #{anchor}")

    def test_readme_screenshots_exist_and_feature_truth_is_clear(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        screenshots = re.findall(r'src="(docs/assets/product/[^"]+)"', readme)
        for image in screenshots:
            self.assertTrue((ROOT / image).is_file(), f"Missing README screenshot: {image}")
        for image in ("dashboard.png", "live-studio.png", "creator-monitoring.png", "clip-library.png", "publishing.png"):
            self.assertIn(f"docs/assets/product/{image}", screenshots)
        self.assertIn("4.0.10 native Windows Release build", readme)
        self.assertNotIn("Page render error", readme)
        self.assertIn("Facebook", readme)
        self.assertIn("Instagram", readme)
        self.assertIn("YouTube", readme)
        self.assertIn("TikTok is not a supported destination", readme)
        self.assertIn("local multi-frame facecam detection", readme)

    def test_readme_links_to_complete_guide_and_local_markdown_links_resolve(self):
        readme_path = ROOT / "README.md"
        guide_path = ROOT / "docs" / "USER_GUIDE.md"
        readme = readme_path.read_text(encoding="utf-8")
        guide = guide_path.read_text(encoding="utf-8")
        self.assertIn("docs/USER_GUIDE.md", readme)
        for heading in (
            "## Install StreamSnip AI", "## First launch: make your first clip",
            "## Creator monitoring", "## Publisher and Zernio",
            "## Files, storage, and privacy", "## Troubleshooting",
            "## Update, repair, backup, and uninstall",
        ):
            self.assertIn(heading, guide)
        guide_images = re.findall(r'src="(assets/product/[^"]+)"', guide)
        self.assertTrue(guide_images, "The user guide should include real product screenshots.")
        for image in guide_images:
            self.assertTrue((ROOT / "docs" / image).is_file(), f"Missing user-guide image: {image}")
        for document_path, content in ((readme_path, readme), (guide_path, guide)):
            for target in re.findall(r"\]\(([^)]+)\)", content):
                target = target.split("#", 1)[0]
                if not target or target.startswith(("http://", "https://", "mailto:")):
                    continue
                local_path = (document_path.parent / target).resolve()
                self.assertTrue(local_path.exists(), f"Broken local link in {document_path.name}: {target}")

    def test_hero_product_screenshot_has_motion_and_respects_reduced_motion(self):
        css = (ROOT / "docs" / "assets" / "site.css").read_text(encoding="utf-8")
        js = (ROOT / "docs" / "assets" / "site.js").read_text(encoding="utf-8")
        html = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
        self.assertIn("@keyframes product-image-drift", css)
        self.assertIn("@keyframes product-image-light-sweep", css)
        self.assertRegex(css, r"prefers-reduced-motion\s*:\s*reduce")
        self.assertIn("IntersectionObserver", js)
        self.assertIn("visibilitychange", js)
        self.assertIn("prefers-reduced-motion", js)
        self.assertIn('class="app-window product-motion"', html)

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

    def test_studio_dark_is_the_default_without_overriding_saved_theme(self):
        html = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
        site_js = (ROOT / "docs" / "assets" / "site.js").read_text(encoding="utf-8")
        react = (ROOT / "dashboard" / "src" / "App.tsx").read_text(encoding="utf-8")
        native = (ROOT / "desktop" / "StreamSnip.Desktop" / "MainPage.xaml.cs").read_text(encoding="utf-8")
        css = (ROOT / "dashboard" / "src" / "App.css").read_text(encoding="utf-8")

        self.assertIn('data-theme="studio-dark" data-theme-choice="studio-dark"', html)
        self.assertIn('let choice = "studio-dark";', html)
        self.assertIn('let choice = root.dataset.themeChoice || "studio-dark";', site_js)
        self.assertIn('saveChoice("studio-dark");', site_js)
        self.assertIn('localStorage.getItem("streamsnip.theme")', react)
        self.assertIn('return "studio-dark";', react)
        self.assertIn('private string _theme = "studio-dark";', native)
        self.assertIn('html[data-theme="studio-dark"]', css)
        self.assertIn('data-theme-choice="studio-dark" aria-pressed="true"', html)
        self.assertIn('data-theme-choice="system" aria-pressed="false"', html)

    def test_browser_font_picker_uses_the_same_offline_font_catalog(self):
        app = (ROOT / "dashboard" / "src" / "App.tsx").read_text(encoding="utf-8")
        css = (ROOT / "dashboard" / "src" / "App.css").read_text(encoding="utf-8")
        expected = {
            "JetBrains Mono": "JetBrainsMono-Variable.ttf",
            "Inter": "Inter-Variable.ttf",
            "Open Sans": "OpenSans-Variable.ttf",
            "IBM Plex Sans": "IBMPlexSans-Variable.ttf",
            "Roboto": "Roboto-Variable.ttf",
            "Source Sans 3": "SourceSans3-Variable.ttf",
            "DM Sans": "DMSans-Variable.ttf",
            "Poppins": "Poppins-Regular.ttf",
            "Lato": "Lato-Regular.ttf",
        }
        for family, asset in expected.items():
            self.assertIn(f'name: "{family}"', app)
            self.assertIn(f'font-family: "{family}"', css)
            self.assertTrue((ROOT / "dashboard" / "public" / "fonts" / asset).is_file())
        self.assertIn('id: "segoe-ui", name: "Segoe UI"', app)
        self.assertIn('id: "consolas", name: "Consolas"', app)
        for family in ("Manrope", "Nunito Sans", "Fira Code"):
            self.assertIn(f'name: "{family}"', app)
        for family in ("Aptos", "Arial", "Tahoma", "Verdana", "Georgia", "Trebuchet MS", "Times New Roman"):
            self.assertIn(f'name: "{family}"', app)
        self.assertIn('return "jetbrains-mono";', app)
        self.assertIn('preferenceVersion !== "8"', app)
        self.assertIn('saved === "manrope" || saved === "jetbrains-mono"', app)
        self.assertIn('preferenceVersion === "1" && saved === "inter"', app)

    def test_directml_facecam_helper_is_built_and_included_in_native_installer(self):
        build = (ROOT / "build_native_installer.ps1").read_text(encoding="utf-8")
        installer = (ROOT / "installer" / "StreamSnipNative.iss").read_text(encoding="utf-8")
        helper_project = ROOT / "tools" / "FacecamInference" / "FacecamInference.csproj"
        self.assertTrue(helper_project.is_file())
        self.assertIn('tools\\FacecamInference\\FacecamInference.csproj', build)
        self.assertIn('dotnet publish $facecamProject', build)
        self.assertIn('FacecamInference.exe', build)
        self.assertIn('..\\dist\\FacecamInference\\*', installer)
        self.assertIn('DestDir: "{app}\\source\\facecam-inference"', installer)

    def test_release_version_is_consistent(self):
        self.assertIn('APP_VERSION = "4.0.16"', (ROOT / "autoclip.py").read_text(encoding="utf-8"))
        self.assertIn('version = "4.0.16"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertIn('#define MyAppVersion "4.0.16"', (ROOT / "installer" / "StreamSnipNative.iss").read_text(encoding="utf-8"))
        self.assertIn('Version="4.0.16.0"', (ROOT / "desktop" / "StreamSnip.Desktop" / "Package.appxmanifest").read_text(encoding="utf-8-sig"))


if __name__ == "__main__":
    unittest.main()
