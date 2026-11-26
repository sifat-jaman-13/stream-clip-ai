import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "desktop" / "StreamSnip.Desktop"
PRESENTATION = "{http://schemas.microsoft.com/winfx/2006/xaml/presentation}"
XAML = "{http://schemas.microsoft.com/winfx/2006/xaml}"


class NativeXamlContractTests(unittest.TestCase):
    def test_application_font_resource_is_defined_for_main_page(self):
        app = ET.parse(DESKTOP / "App.xaml").getroot()
        resources = app.find(f"{PRESENTATION}Application.Resources/{PRESENTATION}ResourceDictionary")
        self.assertIsNotNone(resources)
        keys = {node.attrib.get(f"{XAML}Key") for node in resources}
        self.assertIn("AppFont", keys)

    def test_main_window_xaml_is_minimal_and_uses_programmatic_shell(self):
        window = ET.parse(DESKTOP / "MainWindow.xaml").getroot()
        self.assertEqual(window.tag, f"{PRESENTATION}Window")
        self.assertEqual(window.attrib.get(f"{XAML}Class"), "StreamSnip_Desktop.MainWindow")
        self.assertEqual(len(list(window)), 0)

    def test_release_publish_preserves_application_xaml_resources(self):
        project = ET.parse(DESKTOP / "StreamSnip.Desktop.csproj").getroot()
        tooling_settings = project.findall(".//EnableMsixTooling")
        self.assertTrue(
            any((setting.text or "").strip().lower() == "true" for setting in tooling_settings),
            "EnableMsixTooling must remain enabled so WinUI generates the app-specific PRI index.",
        )
        disabled_release_overrides = [
            setting for setting in tooling_settings
            if setting.attrib.get("Condition") == "'$(Configuration)' == 'Release'"
            and (setting.text or "").strip().lower() == "false"
        ]
        self.assertFalse(
            disabled_release_overrides,
            "Release must not disable MSIX tooling: WinUI needs its app-specific PRI resource index.",
        )

        build_script = (ROOT / "build_native_installer.ps1").read_text(encoding="utf-8")
        self.assertIn(
            'Join-Path $publishDir "StreamSnip.Desktop.pri"',
            build_script,
            "The installer build must fail when the app-specific XAML resource index is missing.",
        )


if __name__ == "__main__":
    unittest.main()
