from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
THEME_FIELDS = {
    "--app-bg": 0,
    "--surface": 1,
    "--surface-soft": 2,
    "--surface-hover": 3,
    "--sidebar-bg": 4,
    "--ink": 5,
    "--body": 6,
    "--muted": 7,
    "--line": 8,
    "--accent": 9,
    "--success": 10,
    "--warning": 11,
    "--danger": 12,
}


class ThemeConsistencyTests(unittest.TestCase):
    def test_all_dashboard_theme_tokens_match_native_palette(self):
        native = (ROOT / "desktop" / "StreamSnip.Desktop" / "MainPage.xaml.cs").read_text(encoding="utf-8")
        css = (ROOT / "dashboard" / "src" / "App.css").read_text(encoding="utf-8")

        native_entries = re.findall(
            r'new ThemePalette\(\s*"([^"]+)"\s*,\s*"[^"]+"\s*,\s*((?:"#[0-9A-Fa-f]{6}"\s*,?\s*){13})\)',
            native,
        )
        self.assertEqual(len(native_entries), 12, "Expected the 12 native appearance themes.")

        for theme_id, raw_colors in native_entries:
            native_colors = re.findall(r'"(#[0-9A-Fa-f]{6})"', raw_colors)
            self.assertEqual(len(native_colors), 13, theme_id)
            blocks = list(re.finditer(
                rf'html\[data-theme="{re.escape(theme_id)}"\]\s*\{{(.*?)\n\}}',
                css,
                flags=re.DOTALL,
            ))
            self.assertTrue(blocks, f"Dashboard palette missing for {theme_id}.")
            # The last block is the canonical token registry; older local overrides must not win.
            block = blocks[-1].group(1)
            for token, index in THEME_FIELDS.items():
                match = re.search(rf'{re.escape(token)}\s*:\s*(#[0-9A-Fa-f]{{6}})', block)
                self.assertIsNotNone(match, f"{theme_id} is missing {token}.")
                self.assertEqual(match.group(1).upper(), native_colors[index].upper(),
                                 f"{theme_id} {token} differs between WinUI and React.")

    def test_native_startup_brushes_match_studio_dark(self):
        app_xaml = (ROOT / "desktop" / "StreamSnip.Desktop" / "App.xaml").read_text(encoding="utf-8")
        native = (ROOT / "desktop" / "StreamSnip.Desktop" / "MainPage.xaml.cs").read_text(encoding="utf-8")
        self.assertIn('private string _theme = "studio-dark";', native)
        expected = {
            "AppBackgroundBrush": "#0F0F0F",
            "SurfaceBrush": "#181818",
            "SurfaceSoftBrush": "#212121",
            "SurfaceHoverBrush": "#2B2B2B",
            "SidebarBrush": "#0F0F0F",
            "SidebarSurfaceBrush": "#212121",
            "PrimaryTextBrush": "#F1F1F1",
            "BodyTextBrush": "#D6D6D6",
            "MutedTextBrush": "#AAAAAA",
            "LineBrush": "#303030",
            "AccentBrush": "#FF0033",
            "AccentInkBrush": "#111111",
            "SuccessBrush": "#81C995",
            "WarningBrush": "#F6C26B",
            "DangerBrush": "#F28B82",
        }
        for key, color in expected.items():
            self.assertIn(f'x:Key="{key}" Color="{color}"', app_xaml, key)

    def test_jetbrains_default_and_selectable_sans_fonts_are_visible_in_settings(self):
        index_css = (ROOT / "dashboard" / "src" / "index.css").read_text(encoding="utf-8")
        app_tsx = (ROOT / "dashboard" / "src" / "App.tsx").read_text(encoding="utf-8")
        native = (ROOT / "desktop" / "StreamSnip.Desktop" / "MainPage.xaml.cs").read_text(encoding="utf-8")

        self.assertIn('font-family: var(--font-family, "JetBrains Mono"), Consolas, monospace;', index_css)
        self.assertIn('private string _fontName = "JetBrains Mono";', native)
        self.assertIn('id: "jetbrains-mono", name: "JetBrains Mono"', app_tsx)
        self.assertIn('id="settings-workspace-font"', app_tsx)
        self.assertIn('label: "Sans serif"', app_tsx)
        for font in ("Manrope", "DM Sans", "Inter", "Open Sans", "IBM Plex Sans",
                     "Nunito Sans", "Roboto", "Source Sans 3", "Poppins", "Lato"):
            self.assertIn(f'name: "{font}"', app_tsx)
            self.assertIn(f'"{font}"', native)

    def test_native_winui_control_state_resources_follow_the_active_palette(self):
        app = (ROOT / "desktop" / "StreamSnip.Desktop" / "App.xaml").read_text(encoding="utf-8")
        source = (ROOT / "desktop" / "StreamSnip.Desktop" / "MainPage.xaml.cs").read_text(encoding="utf-8")
        required = (
            "TextControlForeground", "TextControlForegroundPointerOver",
            "TextControlForegroundFocused", "TextControlForegroundDisabled",
            "TextControlPlaceholderForeground", "TextControlPlaceholderForegroundPointerOver",
            "TextControlPlaceholderForegroundFocused", "TextControlPlaceholderForegroundDisabled",
            "TextControlBackground", "TextControlBackgroundPointerOver",
            "TextControlBackgroundFocused", "TextControlBackgroundDisabled",
            "TextControlBorderBrush", "TextControlBorderBrushPointerOver",
            "TextControlBorderBrushFocused", "TextControlBorderBrushDisabled",
            "ButtonForeground", "ButtonForegroundPointerOver", "ButtonForegroundPressed",
            "ButtonForegroundDisabled", "ButtonBackground", "ButtonBackgroundPointerOver",
            "ButtonBackgroundPressed", "ButtonBackgroundDisabled",
            "ComboBoxForeground", "ComboBoxForegroundPointerOver", "ComboBoxForegroundPressed",
            "ComboBoxForegroundDisabled", "ComboBoxItemForeground", "ComboBoxItemForegroundDisabled",
            "TabViewItemHeaderForeground", "TabViewItemHeaderForegroundSelected",
            "TabViewItemHeaderForegroundDisabled", "TabViewItemHeaderBackgroundSelected",
        )
        for key in required:
            self.assertIn(f'x:Key="{key}"', app, f"Missing startup resource {key}.")
            self.assertIn(f'SetResourceBrush("{key}",', source, f"Theme does not update {key}.")
        self.assertIn('BasedOn="{StaticResource DefaultButtonStyle}"', app)
        self.assertIn('BasedOn="{StaticResource DefaultTextBoxStyle}"', app)
        self.assertIn('BasedOn="{StaticResource DefaultComboBoxStyle}"', app)
        self.assertIn('BasedOn="{StaticResource DefaultCheckBoxStyle}"', app)
        self.assertIn('BasedOn="{StaticResource DefaultRadioButtonStyle}"', app)

    def test_status_colors_are_not_reused_for_primary_actions(self):
        native = (ROOT / "desktop" / "StreamSnip.Desktop" / "MainPage.xaml.cs").read_text(encoding="utf-8")
        forest = re.search(r'new ThemePalette\("forest"[^;]+', native)
        ember = re.search(r'new ThemePalette\("ember"[^;]+', native)
        github = re.search(r'new ThemePalette\("github"[^;]+', native)
        odysseas = re.search(r'new ThemePalette\("odysseas"[^;]+', native)
        for item in (forest, ember, github, odysseas):
            self.assertIsNotNone(item)
        def colors(match):
            return re.findall(r'"(#[0-9A-Fa-f]{6})"', match.group(0))
        self.assertNotEqual(colors(forest)[9], colors(forest)[10], "Forest accent and success should be distinct.")
        self.assertNotEqual(colors(ember)[9], colors(ember)[11], "Ember accent and warning should be distinct.")
        self.assertNotEqual(colors(github)[9], colors(github)[12], "GitHub accent and danger should be distinct.")
        self.assertNotEqual(colors(odysseas)[9], colors(odysseas)[12], "Odysseus accent and danger should be distinct.")


    def test_all_light_palettes_have_wcag_readable_text_roles(self):
        native = (ROOT / "desktop" / "StreamSnip.Desktop" / "MainPage.xaml.cs").read_text(encoding="utf-8")
        entries = re.findall(
            r'new ThemePalette\(\s*"([^"]+)"\s*,\s*"[^"]+"\s*,\s*((?:"#[0-9A-Fa-f]{6}"\s*,?\s*){13})\)',
            native,
        )
        palettes = {
            theme_id: re.findall(r'"(#[0-9A-Fa-f]{6})"', colors)
            for theme_id, colors in entries
        }
        for theme_id in ("studio-light", "odysseas", "solarized"):
            colors = palettes[theme_id]
            backgrounds = tuple(colors[:4])
            self.assertGreaterEqual(
                min(self._contrast(colors[5], bg) for bg in backgrounds), 7.0,
                f"{theme_id} primary text must remain 7:1 across app surfaces.",
            )
            for token_index, label in ((6, "body"), (7, "muted")):
                self.assertGreaterEqual(
                    min(self._contrast(colors[token_index], bg) for bg in backgrounds), 4.5,
                    f"{theme_id} {label} text must remain 4.5:1 across app surfaces.",
                )
            for token_index, label in ((9, "accent"), (10, "success"), (11, "warning"), (12, "danger")):
                self.assertGreaterEqual(
                    min(self._contrast(colors[token_index], bg) for bg in backgrounds), 4.5,
                    f"{theme_id} {label} text must remain 4.5:1 across app surfaces.",
                )

        paper_sidebar = ("#243B49", "#3A5868")
        for foreground in ("#F7F9F8", "#E0E8E5", "#C9D6D1"):
            self.assertGreaterEqual(
                min(self._contrast(foreground, background) for background in paper_sidebar), 4.5,
                "Odysseus Paper's navy rail text must remain readable on both sidebar layers.",
            )

    def test_light_themes_have_distinct_surface_hierarchy_and_readable_text(self):
        native = (ROOT / "desktop" / "StreamSnip.Desktop" / "MainPage.xaml.cs").read_text(encoding="utf-8")
        css = (ROOT / "dashboard" / "src" / "App.css").read_text(encoding="utf-8")
        palettes = {
            "studio-light": ("#F3F5F8", "#FFFFFF", "#E8EDF3", "#DDE5EE"),
            "odysseas": ("#EEF2EF", "#FAFCFA", "#E3EBE6", "#D7E2DB"),
            "solarized": ("#F2EEDF", "#FFFCF3", "#EAE4D2", "#DCD3BC"),
        }
        for theme_id, expected in palettes.items():
            native_match = re.search(re.escape(f'new ThemePalette("{theme_id}"') + r'[^;]+', native)
            self.assertIsNotNone(native_match, theme_id)
            native_colors = re.findall(r'"(#[0-9A-Fa-f]{6})"', native_match.group(0))
            self.assertEqual(tuple(native_colors[:4]), expected, theme_id)
            selector = re.escape(f'html[data-theme="{theme_id}"]')
            blocks = re.findall(selector + r'\s*\{(.*?)\n\}', css, re.DOTALL)
            self.assertTrue(blocks, f"{theme_id} CSS theme block is missing")
            block = blocks[-1]
            for token, value in zip(("--app-bg", "--surface", "--surface-soft", "--surface-hover"), expected):
                self.assertIn(f"{token}:{value}", block, f"{theme_id} {token}")
            self.assertEqual(len(set(expected)), 4, f"{theme_id} needs four distinct surface levels")

    @staticmethod
    def _contrast(foreground, background):
        def luminance(value):
            channels = [int(value[index:index + 2], 16) / 255 for index in (1, 3, 5)]
            channels = [channel / 12.92 if channel <= 0.04045
                        else ((channel + 0.055) / 1.055) ** 2.4
                        for channel in channels]
            return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]
        first, second = luminance(foreground), luminance(background)
        return (max(first, second) + 0.05) / (min(first, second) + 0.05)

    def test_native_requested_theme_and_parent_foreground_inheritance(self):
        native = (ROOT / "desktop" / "StreamSnip.Desktop" / "MainPage.xaml.cs").read_text(encoding="utf-8")
        app = (ROOT / "desktop" / "StreamSnip.Desktop" / "App.xaml").read_text(encoding="utf-8")
        live = (ROOT / "desktop" / "StreamSnip.Desktop" / "MainPage.Live.cs").read_text(encoding="utf-8")
        self.assertIn('public bool IsLight => Id is "studio-light" or "odysseas" or "solarized";', native)
        constructor = native[native.index("public MainPage()"):native.index("private async void Page_Loaded")]
        self.assertIn("RequestedTheme = initialPalette.IsLight ? ElementTheme.Light : ElementTheme.Dark;", constructor)
        apply_method = native[native.index("private void ApplyTheme(string themeId)"):native.index("private static void UpdateWindowTitleBar")]
        self.assertNotIn("RequestedTheme =", apply_method)
        self.assertNotIn("RefreshRequestedTheme", native)
        text_block_style = re.search(r'<Style TargetType="TextBlock">(.*?)</Style>', app, re.DOTALL)
        self.assertIsNotNone(text_block_style)
        self.assertNotIn('Setter Property="Foreground"', text_block_style.group(1))
        for header in ("Capture", "Framing", "Captions"):
            self.assertIn(f'Header = "{header}"', live)
        self.assertIn('SetResourceBrush("TabViewItemHeaderForegroundSelected",', native)
        self.assertIn('SetResourceBrush("TabViewItemHeaderBackgroundSelected",', native)

    def test_live_creator_actions_use_a_second_row_without_squeezing_details(self):
        live = (ROOT / "desktop" / "StreamSnip.Desktop" / "MainPage.Live.cs").read_text(encoding="utf-8")
        self.assertIn("RowSpacing = 8", live)
        self.assertIn("row.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });", live)
        self.assertIn("Grid.SetRow(avatar, 0);", live)
        self.assertNotIn("Grid.SetRowSpan(avatar, 2);", live)
        self.assertIn("var actions = new Grid { ColumnSpacing = 10 };", live)
        self.assertIn("select.HorizontalAlignment = HorizontalAlignment.Stretch;", live)
        self.assertIn("liveAction.HorizontalAlignment = HorizontalAlignment.Stretch;", live)
        self.assertIn("Grid.SetRow(actions, 1);", live)
        self.assertIn("Grid.SetColumn(actions, 1);", live)

    def test_native_creator_avatar_centers_initial_and_is_reused_across_screens(self):
        main = (ROOT / "desktop" / "StreamSnip.Desktop" / "MainPage.xaml.cs").read_text(encoding="utf-8")
        dashboard = (ROOT / "desktop" / "StreamSnip.Desktop" / "MainPage.Dashboard.cs").read_text(encoding="utf-8")
        live = (ROOT / "desktop" / "StreamSnip.Desktop" / "MainPage.Live.cs").read_text(encoding="utf-8")
        creators = (ROOT / "desktop" / "StreamSnip.Desktop" / "MainPage.Creators.cs").read_text(encoding="utf-8")
        self.assertIn('private Border CreateCreatorAvatar(string creatorName, double size = 34, bool active = false)', main)
        self.assertIn('label.TextAlignment = TextAlignment.Center;', main)
        self.assertIn('label.HorizontalAlignment = HorizontalAlignment.Stretch;', main)
        self.assertIn('label.VerticalAlignment = VerticalAlignment.Center;', main)
        self.assertIn('CreateCreatorAvatar(', dashboard)
        self.assertIn('CreateCreatorAvatar(', live)
        self.assertIn('CreateCreatorAvatar(', creators)


if __name__ == "__main__":
    unittest.main()
