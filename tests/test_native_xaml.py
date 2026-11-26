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


if __name__ == "__main__":
    unittest.main()
