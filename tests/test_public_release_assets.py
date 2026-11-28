import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

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
    def test_landing_page_has_valid_local_assets_and_theme_controls(self):
        html_path = ROOT / "docs" / "index.html"
        html = html_path.read_text(encoding="utf-8")
        self.assertIn('<html lang="en" data-type="software" data-theme="studio-dark" data-theme-choice="studio-dark">', html)
        self.assertIn('<meta name="page-type" content="software">', html)
        self.assertIn('class="mobile-menu"', html)
        self.assertIn('id="menu-toggle"', html)
        self.assertIn('aria-label="Choose website theme"', html)
        social_card = ROOT / "docs" / "assets" / "streamsnipai-social-card.png"
        self.assertTrue(social_card.is_file())
        parser = PageInspector()
        parser.feed(html)
        self.assertEqual(len(parser.ids), len(set(parser.ids)))
        self.assertTrue(parser.images)
        for image in parser.images:
            self.assertIn("alt", image)
            src = image.get("src", "")
            if not re.match(r"^(?:[a-z][a-z0-9+.-]*:|/|#)", src, re.IGNORECASE):
                local_path = src[2:] if src.startswith("./") else src
                self.assertTrue((html_path.parent / local_path).is_file(), f"Missing image: {src}")
        for anchor in parser.links:
            self.assertIn(f'id="{anchor}"', html, f"Broken in-page link: #{anchor}")

    def test_readme_and_user_guide_screenshots_and_links_resolve(self):
        readme_path = ROOT / "README.md"
        guide_path = ROOT / "docs" / "USER_GUIDE.md"
        readme = readme_path.read_text(encoding="utf-8-sig")
        guide = guide_path.read_text(encoding="utf-8-sig")
        for image in re.findall(r'src="(docs/assets/product/[^"]+)"', readme):
            self.assertTrue((ROOT / image).is_file(), f"Missing README screenshot: {image}")
        for image in re.findall(r'src="(assets/product/[^"]+)"', guide):
            self.assertTrue((ROOT / "docs" / image).is_file(), f"Missing guide screenshot: {image}")
        self.assertIn("FastAPI", readme)
        self.assertIn("React", readme)
        self.assertIn("pywebview", readme)
        self.assertIn("FastAPI", guide)
        self.assertIn("pywebview", guide)
        for document_path, content in ((readme_path, readme), (guide_path, guide)):
            for target in re.findall(r"\]\(([^)]+)\)", content):
                target = target.split("#", 1)[0]
                if not target or target.startswith(("http://", "https://", "mailto:")):
                    continue
                self.assertTrue((document_path.parent / target).resolve().exists(), f"Broken link: {target}")

    def test_public_site_respects_reduced_motion_and_has_no_automatic_drift(self):
        css = (ROOT / "docs" / "assets" / "site.css").read_text(encoding="utf-8")
        js = (ROOT / "docs" / "assets" / "site.js").read_text(encoding="utf-8")
        html = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("animation: product-image-drift", css)
        self.assertRegex(css, r"prefers-reduced-motion\s*:\s*reduce")
        self.assertIn("IntersectionObserver", js)
        self.assertIn("visibilitychange", js)
        self.assertIn("prefers-reduced-motion", js)
        self.assertIn('class="app-window product-motion"', html)

    def test_third_party_notices_are_packaged_for_the_pywebview_shell(self):
        notices = ROOT / "licenses" / "third-party"
        self.assertTrue((notices / "YuNet-MIT.txt").is_file())
        self.assertTrue((notices / "JetBrains-Mono-OFL.txt").is_file())
        self.assertTrue((notices / "README.md").is_file())
        self.assertFalse((ROOT / "LICENSE-NeonClipping.txt").exists())
        self.assertFalse((ROOT / "LICENSE-YuNet.txt").exists())
        installer = (ROOT / "installer" / "StreamSnipAI.iss").read_text(encoding="utf-8")
        spec = (ROOT / "StreamSnipShell.spec").read_text(encoding="utf-8")
        self.assertIn('LICENSE"; DestDir: "{app}"', installer)
        self.assertIn('..\\licenses\\third-party\\*', installer)
        self.assertIn('DestDir: "{app}\\licenses\\third-party"', installer)
        self.assertIn("webview", spec)
        self.assertNotIn("NeonClipping", spec + installer)
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("!models/face_detection_yunet_2023mar.onnx", gitignore)
        self.assertIn("custom_words.txt", gitignore)

    def test_studio_dark_is_default_and_saved_theme_is_not_overwritten(self):
        html = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
        site_js = (ROOT / "docs" / "assets" / "site.js").read_text(encoding="utf-8")
        react = (ROOT / "dashboard" / "src" / "App.tsx").read_text(encoding="utf-8")
        css = (ROOT / "dashboard" / "src" / "App.css").read_text(encoding="utf-8")
        self.assertIn('data-theme="studio-dark" data-theme-choice="studio-dark"', html)
        self.assertIn('let choice = "studio-dark";', html)
        self.assertIn('let choice = root.dataset.themeChoice || "studio-dark";', site_js)
        self.assertIn('saveChoice("studio-dark");', site_js)
        self.assertIn('localStorage.getItem("streamsnip.theme")', react)
        self.assertIn('return "studio-dark";', react)
        self.assertIn('html[data-theme="studio-dark"]', css)
        self.assertIn("Advanced themes", react)

    def test_react_font_picker_has_three_bundled_fonts_and_system_fonts(self):
        app = (ROOT / "dashboard" / "src" / "App.tsx").read_text(encoding="utf-8")
        css = (ROOT / "dashboard" / "src" / "App.css").read_text(encoding="utf-8")
        for family, asset in (
            ("JetBrains Mono", "JetBrainsMono-Variable.ttf"),
            ("Manrope", "Manrope-Variable.ttf"),
            ("Inter", "Inter-Variable.ttf"),
        ):
            self.assertIn(f'name: "{family}"', app)
            self.assertIn(f'font-family: "{family}"', css)
            self.assertTrue((ROOT / "dashboard" / "public" / "fonts" / asset).is_file())
        self.assertIn('label: "Bundled fonts"', app)
        self.assertIn('label: "System fonts"', app)
        for family in ("Segoe UI", "Aptos", "Arial", "Tahoma", "Verdana", "Georgia", "Trebuchet MS", "Times New Roman", "Consolas"):
            self.assertIn(f'name: "{family}"', app)
        self.assertIn('return "jetbrains-mono";', app)

    def test_facecam_detection_uses_opencv_yunet_without_a_compiled_helper(self):
        source = (ROOT / "facecam_detect.py").read_text(encoding="utf-8")
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("cv2.FaceDetectorYN.create", source)
        self.assertIn("CPU (OpenCV YuNet)", source)
        self.assertIn("opencv-contrib-python-headless", requirements)
        self.assertNotIn("FacecamInference.exe", source)
        self.assertFalse((ROOT / "tools" / "FacecamInference").exists())

    def test_secret_store_is_packaged_and_version_is_consistent(self):
        try:
            import tomllib
        except ModuleNotFoundError:  # Python 3.10 uses the backport.
            import tomli as tomllib
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        installer = (ROOT / "installer" / "StreamSnipAI.iss").read_text(encoding="utf-8")
        self.assertIn("secret_store", project["tool"]["setuptools"]["py-modules"])
        self.assertIn('Source: "..\\secret_store.py"', installer)
        self.assertIn('APP_VERSION = "4.1.0"', (ROOT / "autoclip.py").read_text(encoding="utf-8"))
        self.assertIn('version = "4.1.0"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertIn("#error MyAppVersion must be supplied", installer)

    def test_installer_and_workflow_use_one_pywebview_build(self):
        installer = (ROOT / "installer" / "StreamSnipAI.iss").read_text(encoding="utf-8")
        build = (ROOT / "build_installer.ps1").read_text(encoding="utf-8")
        workflow = (ROOT / ".github" / "workflows" / "build-installer.yml").read_text(encoding="utf-8")
        self.assertIn('Source: "..\\dist\\StreamSnipAI\\*"', installer)
        self.assertIn('Source: "..\\dashboard\\dist\\*"', installer)
        self.assertIn("PyInstaller", build)
        self.assertNotIn("dotnet publish", build)
        self.assertNotIn("setup-dotnet", workflow)
        self.assertIn("StreamSnipAI-Setup.exe", build)
        self.assertIn("pull_request:", workflow)
        self.assertIn('branches: ["master"]', workflow)
        self.assertIn("publish-release:", workflow)
        self.assertRegex(workflow, r"actions/download-artifact@[0-9a-f]{40}")
        self.assertIn("permissions:\n  contents: read", workflow)
        self.assertEqual(workflow.count("contents: write"), 1)

    def test_repository_tracks_only_current_desktop_delivery_and_dependency_manifests(self):
        for retired_path in ("Dockerfile", "docker-compose.yml", ".dockerignore", "uv.lock"):
            self.assertFalse((ROOT / retired_path).exists(), f"Retired or unused file remains: {retired_path}")

        dependabot = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
        for ecosystem in ("pip", "npm", "github-actions"):
            self.assertIn(f"package-ecosystem: {ecosystem}", dependabot)

        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        design = (ROOT / "DESIGN.md").read_text(encoding="utf-8")
        self.assertIn("pywebview", agents)
        self.assertNotIn("MainPage.xaml.cs", agents)
        self.assertIn("There is no WinUI/C# application", agents)
        self.assertNotIn("WinUI", design)

    def test_source_build_docs_do_not_require_retired_dotnet_toolchain(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        guide = (ROOT / "docs" / "USER_GUIDE.md").read_text(encoding="utf-8")
        self.assertNotIn(".NET 10 SDK", readme)
        self.assertNotIn(".NET 10 SDK", guide)

    def test_dashboard_uses_only_current_bundled_and_system_font_options(self):
        html = (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")
        app = (ROOT / "dashboard" / "src" / "App.tsx").read_text(encoding="utf-8")
        self.assertNotIn("fonts.googleapis.com", html)
        self.assertNotIn("fonts.gstatic.com", html)
        self.assertIn('type FontId = "jetbrains-mono" | "manrope" | "inter"', app)
        self.assertNotIn('"dm-sans"', app)
        self.assertNotIn('"fira-code"', app)

    def test_current_issue_and_security_guidance_does_not_advertise_docker_deployment(self):
        security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
        bug = (ROOT / ".github" / "ISSUE_TEMPLATE" / "bug_report.yml").read_text(encoding="utf-8")
        feature = (ROOT / ".github" / "ISSUE_TEMPLATE" / "feature_request.yml").read_text(encoding="utf-8")
        self.assertNotIn("Docker", security)
        self.assertNotIn("Docker", bug)
        self.assertNotIn("Docker", feature)

    def test_codeql_scans_current_languages_with_minimal_write_permissions(self):
        workflow = (ROOT / ".github" / "workflows" / "codeql.yml").read_text(encoding="utf-8")
        self.assertIn("language: javascript-typescript", workflow)
        self.assertIn("language: python", workflow)
        self.assertIn("build-mode: none", workflow)
        self.assertIn("security-events: write", workflow)
        self.assertIn("security-extended", workflow)
        self.assertIn("github/codeql-action/init@915412ff23e8b7659517e607487dbeae018f2934", workflow)
        self.assertIn("github/codeql-action/analyze@915412ff23e8b7659517e607487dbeae018f2934", workflow)


if __name__ == "__main__":
    unittest.main()
