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


    def test_application_font_size_options_and_medium_default_are_persisted(self):
        source = (DESKTOP / "MainPage.xaml.cs").read_text(encoding="utf-8")
        settings = (DESKTOP / "MainPage.Manage.cs").read_text(encoding="utf-8")
        self.assertIn('private string _fontSize = "medium";', source)
        self.assertIn('["fontSize"] = _fontSize', source)
        self.assertIn('"small" => 13.0 / 14.0', source)
        self.assertIn('"medium" => 1.0', source)
        self.assertIn('"large" => 16.0 / 14.0', source)
        self.assertIn('"Application text size"', settings)
        self.assertIn('new[] { "Small", "Medium", "Large" }', settings)
        self.assertIn('ConditionalWeakTable<FrameworkElement, FontSizeBaseline>', source)
        self.assertIn('baseline.Value * _applicationFontScale', source)
        self.assertIn('ApplyFontSizeToElement(textBlock, textBlock.FontSize', source)
        self.assertIn('ApplyFontSizeToElement(button, button.FontSize', source)
        self.assertIn('ApplyFontSizeToElement(textBox, textBox.FontSize', source)
        self.assertIn('Small: 13 DIP', settings)
        self.assertIn('Large: 16 DIP', settings)
        self.assertNotIn('RenderSettingsPage();', settings)

    def test_global_font_and_standard_size_scale_apply_to_late_loaded_controls(self):
        source = (DESKTOP / "MainPage.xaml.cs").read_text(encoding="utf-8")
        app_xaml = (DESKTOP / "App.xaml").read_text(encoding="utf-8")
        page_xaml = (DESKTOP / "MainPage.xaml").read_text(encoding="utf-8")
        self.assertIn('Inter-Variable.ttf#Inter', app_xaml)
        self.assertIn('element.Loaded += (_, _) => ApplyFontToVisualTree(element);', source)
        self.assertIn('textBlock.FontFamily = ActiveFontFamily;', source)
        self.assertIn('control.FontFamily = ActiveFontFamily;', source)
        self.assertIn('baseline.Value * _applicationFontScale', source)
        self.assertIn('private string _fontName = "Inter";', source)
        self.assertIn('"small" => 13.0 / 14.0', source)
        self.assertIn('"medium" => 1.0', source)
        self.assertIn('"large" => 16.0 / 14.0', source)
        self.assertIn('FontFamily="{ThemeResource AppFont}"', page_xaml)

    def test_studio_dark_colors_the_windows_title_bar_with_supported_api_guard(self):
        source = (DESKTOP / "MainPage.xaml.cs").read_text(encoding="utf-8")
        self.assertIn('AppWindowTitleBar.IsCustomizationSupported()', source)
        self.assertIn('titleBar.BackgroundColor = app;', source)
        self.assertIn('titleBar.ButtonHoverBackgroundColor = hover;', source)
        self.assertIn('titleBar.ButtonPressedBackgroundColor = accentColor;', source)
        self.assertIn('UpdateWindowTitleBar(themePalette, accent);', source)
        self.assertIn('UpdateWindowTitleBar(currentPalette', source)

    def test_native_font_picker_only_offers_available_bundled_or_system_fonts(self):
        source = (DESKTOP / "MainPage.xaml.cs").read_text(encoding="utf-8")
        project = (DESKTOP / "StreamSnip.Desktop.csproj").read_text(encoding="utf-8")
        settings = (DESKTOP / "MainPage.Manage.cs").read_text(encoding="utf-8")
        fonts = {
            "Inter": ("Inter-Variable.ttf", "Inter-OFL.txt"),
            "Open Sans": ("OpenSans-Variable.ttf", "Open-Sans-OFL.txt"),
            "IBM Plex Sans": ("IBMPlexSans-Variable.ttf", "IBM-Plex-Sans-OFL.txt"),
            "Roboto": ("Roboto-Variable.ttf", "Roboto-OFL.txt"),
            "Source Sans 3": ("SourceSans3-Variable.ttf", "Source-Sans-3-OFL.txt"),
        }
        for family, (asset, license_file) in fonts.items():
            self.assertIn(f'"{family}"', source)
            self.assertIn(asset, source)
            self.assertIn(asset, project)
            self.assertTrue((DESKTOP / "Assets" / "Fonts" / asset).is_file())
            self.assertTrue((ROOT / "licenses" / "third-party" / license_file).is_file())
        self.assertIn('"Segoe UI"', source)
        self.assertIn('"Consolas"', source)
        self.assertIn('All app panels and controls use the selected family', settings)

    def test_font_size_changes_replace_settings_view_and_expose_all_three_options(self):
        source = (DESKTOP / "MainPage.xaml.cs").read_text(encoding="utf-8")
        settings = (DESKTOP / "MainPage.Manage.cs").read_text(encoding="utf-8")
        self.assertIn('"small" => 13.0 / 14.0', source)
        self.assertIn('"medium" => 1.0', source)
        self.assertIn('"large" => 16.0 / 14.0', source)
        self.assertIn('new[] { "Small", "Medium", "Large" }', settings)
        self.assertIn('ApplyFontSize(selected.ToLowerInvariant());', settings)
        self.assertIn('RenderCurrentPage();', settings)
        self.assertNotIn('RenderSettingsPage();', settings)

    def test_old_jetbrains_default_migrates_once_but_custom_font_choices_are_preserved(self):
        source = (DESKTOP / "MainPage.xaml.cs").read_text(encoding="utf-8")
        dashboard = (ROOT / "dashboard" / "src" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn('fontPreferenceVersion < 1', source)
        self.assertIn('savedFont = "Inter";', source)
        self.assertIn('["fontPreferenceVersion"] = 1', source)
        self.assertIn('preferenceVersion !== "1"', dashboard)
        self.assertIn('saved === "jetbrains-mono" ? "inter" : saved', dashboard)
        self.assertIn('localStorage.setItem("streamsnip.font-version", "1")', dashboard)

    def test_popup_and_dropdown_controls_use_the_global_font_resource(self):
        app_xaml = (DESKTOP / "App.xaml").read_text(encoding="utf-8")
        for control in ("ComboBoxItem", "MenuFlyoutItem", "MenuFlyoutSubItem", "ListViewItem", "GridViewItem"):
            self.assertIn(f'<Style TargetType="{control}">', app_xaml)
            self.assertIn('Value="{ThemeResource AppFont}"', app_xaml)

    def test_inter_is_the_single_app_wide_default_font(self):
        source = (DESKTOP / "MainPage.xaml.cs").read_text(encoding="utf-8")
        app_xaml = (DESKTOP / "App.xaml").read_text(encoding="utf-8")
        dashboard = (ROOT / "dashboard" / "src" / "App.tsx").read_text(encoding="utf-8")
        design = (ROOT / "DESIGN.md").read_text(encoding="utf-8")
        self.assertIn('private string _fontName = "Inter";', source)
        self.assertIn('"Inter"', source)
        self.assertIn('"JetBrains Mono"', source)
        self.assertIn('Inter-Variable.ttf#Inter</FontFamily>', app_xaml)
        self.assertIn('return "inter";', dashboard)
        self.assertIn('{ id: "inter", name: "Inter"', dashboard)
        self.assertIn('family: "Inter, sans-serif"', design)

    def test_standard_global_font_sizes_apply_to_every_text_role(self):
        source = (DESKTOP / "MainPage.xaml.cs").read_text(encoding="utf-8")
        app_xaml = (DESKTOP / "App.xaml").read_text(encoding="utf-8")
        settings = (DESKTOP / "MainPage.Manage.cs").read_text(encoding="utf-8")
        self.assertIn('"small" => 13.0 / 14.0', source)
        self.assertIn('"medium" => 1.0', source)
        self.assertIn('"large" => 16.0 / 14.0', source)
        self.assertIn('private static double UiFontSize(double size)', source)
        self.assertIn('if (size <= 15.0) return 14.0;', source)
        self.assertIn('if (size <= 18.0) return 16.0;', source)
        self.assertIn('if (size <= 22.0) return 20.0;', source)
        self.assertIn('return 24.0; // Page headings use a restrained 24-DIP base at Medium.', source)
        self.assertIn('ApplyFontSizeToElement(textBlock, textBlock.FontSize', source)
        self.assertIn('ApplyFontSizeToElement(control, control.FontSize', source)
        self.assertIn('Small: 13 DIP', settings)
        self.assertIn('Large: 16 DIP', settings)
        self.assertIn('<Setter Property="FontSize" Value="14" />', app_xaml)
        self.assertNotIn('FontSizeReductionFor', source)

    def test_sidebar_workspace_card_uses_content_sized_row(self):
        page = ET.parse(DESKTOP / "MainPage.xaml").getroot()
        sidebar = next(
            element for element in page.iter()
            if element.attrib.get(f"{XAML}Name") == "SidebarRoot"
        )
        rows = sidebar.find(f"{PRESENTATION}Grid.RowDefinitions")
        self.assertIsNotNone(rows)
        row_definitions = rows.findall(f"{PRESENTATION}RowDefinition")
        self.assertGreaterEqual(len(row_definitions), 3)
        self.assertEqual(
            row_definitions[1].attrib.get("Height"),
            "Auto",
            "The workspace card row must measure its two text lines and padding instead of clipping the subtitle.",
        )
if __name__ == "__main__":
    unittest.main()
