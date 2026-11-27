import re
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

    def test_theme_setup_is_available_only_in_settings_not_the_top_utility_bar(self):
        page = (DESKTOP / "MainPage.xaml").read_text(encoding="utf-8")
        source = (DESKTOP / "MainPage.xaml.cs").read_text(encoding="utf-8")
        settings = (DESKTOP / "MainPage.Manage.cs").read_text(encoding="utf-8")

        self.assertNotIn('x:Name="AppearanceButton"', page)
        self.assertNotIn('Click="AppearanceButton_Click"', page)
        self.assertNotIn('Text="Aa"', page)
        self.assertNotIn("AppearanceButton_Click", source)
        self.assertIn('appearance.Children.Add(Txt("Theme", 11, true));', settings)
        self.assertIn("ApplyTheme(palette.Id);", settings)

    def test_requested_theme_is_set_once_before_load_and_never_toggled_during_runtime(self):
        source = (DESKTOP / "MainPage.xaml.cs").read_text(encoding="utf-8")
        constructor_start = source.index("public MainPage()")
        constructor_end = source.index("private async void Page_Loaded", constructor_start)
        constructor = source[constructor_start:constructor_end]
        apply_start = source.index("private void ApplyTheme(string themeId)")
        apply_end = source.index("private static void UpdateWindowTitleBar", apply_start)
        apply_method = source[apply_start:apply_end]

        self.assertIn("LoadPreferences();", constructor)
        self.assertIn("RequestedTheme = initialPalette.IsLight ? ElementTheme.Light : ElementTheme.Dark;", constructor)
        self.assertLess(constructor.index("RequestedTheme = initialPalette"), constructor.index("ApplyTheme(_theme);"))
        self.assertNotIn("RequestedTheme =", apply_method)
        self.assertNotIn("RefreshRequestedTheme", source)
        self.assertIn('themeDictionary[key] = new SolidColorBrush(color);', source)
        self.assertIn("ApplyShellPalette(themePalette);", source)
        self.assertIn("UpdateSidebarSelection();", source)
        self.assertIn('x:Name="ContentScrollViewer"', (DESKTOP / "MainPage.xaml").read_text(encoding="utf-8"))
        navigation_start = source.index("private void NavigateTo(string page)")
        navigation_end = source.index("private static string GetPageTitle", navigation_start)
        self.assertIn("ContentScrollViewer.ChangeView(null, 0, null);", source[navigation_start:navigation_end])
        shell_start = source.index("private void ApplyShellPalette(ThemePalette palette)")
        shell_end = source.index("private void SetResourceBrush(string key, string hex)", shell_start)
        shell = source[shell_start:shell_end]
        for element in (
            "RootLayoutGrid.Background", "SidebarRoot.Background", "SidebarBrandBorder.Background",
            "SidebarWorkspaceBorder.Background", "SidebarEngineBorder.Background",
            "SidebarStudioLabel.Foreground", "SidebarLibraryLabel.Foreground", "SidebarManageLabel.Foreground",
            "TopBarRoot.Background", "TopBarRoot.BorderBrush", "PageTitleText.Foreground",
            "GlobalSearchBox.Background", "GlobalSearchBox.Foreground", "SearchQueryIcon.Foreground",
            "EngineStatusBorder.Background", "EngineStatusText.Foreground", "QuitButton.Foreground",
            "PageActionHost.Background", "FooterRoot.Background", "FooterVersionText.Foreground",
        ):
            self.assertIn(element, shell, element)

    def test_native_icons_use_vector_geometry_instead_of_optional_glyph_fonts(self):
        page = (DESKTOP / "MainPage.xaml").read_text(encoding="utf-8")
        source = (DESKTOP / "MainPage.xaml.cs").read_text(encoding="utf-8")
        self.assertIn("<AutoSuggestBox.QueryIcon>", page)
        self.assertIn('x:Name="SearchQueryIcon"', page)
        self.assertIn('Foreground="{ThemeResource MutedTextBrush}"', page)
        self.assertIn("SearchQueryIcon.Data = CreateSearchIconGeometry();", source)
        self.assertIn("private static PathGeometry CreateSearchIconGeometry()", source)
        self.assertIn("private static PathGeometry CreateVideoIconGeometry()", source)
        self.assertNotIn("SearchIconGeometry", (DESKTOP / "App.xaml").read_text(encoding="utf-8"))
        self.assertNotIn("VideoIconGeometry", (DESKTOP / "App.xaml").read_text(encoding="utf-8"))
        for source_file in DESKTOP.glob("MainPage*.cs"):
            self.assertNotIn("new FontIcon", source_file.read_text(encoding="utf-8"), source_file.name)
            self.assertNotIn("Segoe MDL2 Assets", source_file.read_text(encoding="utf-8"), source_file.name)
        self.assertNotIn('QueryIcon="Find"', page)

    def test_sidebar_static_resources_are_page_local_and_theme_updates_refresh_page_resources(self):
        page = ET.parse(DESKTOP / "MainPage.xaml").getroot()
        source = (DESKTOP / "MainPage.xaml.cs").read_text(encoding="utf-8")
        resources = page.find(f"{PRESENTATION}Page.Resources/{PRESENTATION}ResourceDictionary")
        self.assertIsNotNone(resources, "Static sidebar resources must resolve during MainPage.InitializeComponent.")
        keys = {item.attrib.get(f"{XAML}Key") for item in resources}
        for key in ("SidebarSurfaceBrush", "SidebarTextBrush", "SidebarBodyTextBrush",
                    "SidebarMutedTextBrush", "SidebarLineBrush"):
            self.assertIn(key, keys)
        self.assertIn('Resources[key] = new SolidColorBrush(color);', source)
        page_text = (DESKTOP / "MainPage.xaml").read_text(encoding="utf-8")
        self.assertIn('Foreground="{ThemeResource SidebarBodyTextBrush}"', page_text)
        self.assertIn('Foreground="{ThemeResource SidebarMutedTextBrush}"', page_text)

    def test_capture_chunk_count_uses_the_validated_shared_clipping_setting(self):
        live = (DESKTOP / "MainPage.Live.cs").read_text(encoding="utf-8")
        self.assertIn('"clips_per_chunk"', live)
        self.assertNotIn('"max_clips"', live)

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
        self.assertIn('JetBrainsMono-Variable.ttf#JetBrains Mono', app_xaml)
        self.assertIn('private string _fontName = "JetBrains Mono";', source)
        self.assertIn('element.Loaded += (_, _) => ApplyFontToVisualTree(element);', source)
        self.assertIn('textBlock.FontFamily = ActiveFontFamily;', source)
        self.assertIn('control.FontFamily = ActiveFontFamily;', source)
        self.assertIn('baseline.Value * _applicationFontScale', source)
        self.assertIn('private string _fontName = "JetBrains Mono";', source)
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
            "DM Sans": ("DMSans-Variable.ttf", "DM-Sans-OFL.txt"),
            "Poppins": ("Poppins-Regular.ttf", "Poppins-OFL.txt"),
            "Lato": ("Lato-Regular.ttf", "Lato-OFL.txt"),
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

    def test_temporary_manrope_default_migrates_back_to_jetbrains_once(self):
        source = (DESKTOP / "MainPage.xaml.cs").read_text(encoding="utf-8")
        dashboard = (ROOT / "dashboard" / "src" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn('fontPreferenceVersion < 8', source)
        self.assertIn('string.Equals(savedFont, "Manrope", StringComparison.Ordinal)', source)
        self.assertIn('fontPreferenceVersion < 2', source)
        self.assertIn('savedFont = "JetBrains Mono";', source)
        self.assertIn('["fontPreferenceVersion"] = 8', source)
        self.assertIn('preferenceVersion !== "8"', dashboard)
        self.assertIn('saved === "manrope" || saved === "jetbrains-mono"', dashboard)
        self.assertIn('preferenceVersion === "1" && saved === "inter"', dashboard)
        self.assertIn('localStorage.setItem("streamsnip.font-version", "8")', dashboard)

    def test_popup_and_dropdown_controls_use_the_global_font_resource(self):
        app_xaml = (DESKTOP / "App.xaml").read_text(encoding="utf-8")
        for control in ("ComboBoxItem", "MenuFlyoutItem", "MenuFlyoutSubItem", "ListViewItem", "GridViewItem"):
            self.assertIn(f'<Style TargetType="{control}"', app_xaml)
            self.assertIn('Value="{ThemeResource AppFont}"', app_xaml)

    def test_jetbrains_mono_is_the_single_app_wide_default_font(self):
        source = (DESKTOP / "MainPage.xaml.cs").read_text(encoding="utf-8")
        app_xaml = (DESKTOP / "App.xaml").read_text(encoding="utf-8")
        dashboard = (ROOT / "dashboard" / "src" / "App.tsx").read_text(encoding="utf-8")
        design = (ROOT / "DESIGN.md").read_text(encoding="utf-8")
        self.assertIn('private string _fontName = "JetBrains Mono";', source)
        self.assertIn('"Manrope"', source)
        self.assertIn('"Inter"', source)
        self.assertIn('JetBrainsMono-Variable.ttf#JetBrains Mono</FontFamily>', app_xaml)
        self.assertIn('return "jetbrains-mono";', dashboard)
        self.assertIn('{ id: "jetbrains-mono", name: "JetBrains Mono"', dashboard)
        self.assertIn('family: "JetBrains Mono, monospace"', design)

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

    def test_native_update_flow_checks_installed_version_and_offers_verified_install(self):
        settings = (DESKTOP / "MainPage.Manage.cs").read_text(encoding="utf-8")
        source = (DESKTOP / "MainPage.xaml.cs").read_text(encoding="utf-8")
        self.assertIn('CreateButton("Check app update"', settings)
        self.assertIn('CreateButton("Install update"', settings)
        self.assertIn('PostAsync("/api/check_app_update"', settings)
        self.assertIn('PostAsync("/api/install_app_update"', settings)
        self.assertIn('["parent_pid"] = Environment.ProcessId', settings)
        self.assertIn('await ShutdownApplicationAsync();', settings)
        self.assertIn('private async Task ShutdownApplicationAsync()', source)
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

    def test_live_studio_exposes_automatic_facecam_detection_and_manual_framing(self):
        live = (DESKTOP / "MainPage.Live.cs").read_text(encoding="utf-8")
        framing_path = DESKTOP / "MainPage.Framing.cs"
        self.assertTrue(framing_path.is_file(), "Native Live Studio must include a dedicated framing editor.")
        framing = framing_path.read_text(encoding="utf-8")
        self.assertIn('Header = "Framing"', live)
        self.assertIn("BuildFramingTab()", live)
        self.assertIn("Find facecam automatically", framing)
        self.assertIn('PostJsonAsync("/api/facecam/detect"', framing)
        self.assertIn('PostJsonAsync("/api/frame"', framing)
        self.assertIn("Manual framing", framing)
        self.assertIn("PointerPressed", framing)
        self.assertIn("PointerMoved", framing)
        self.assertIn("Save framing", framing)
        self.assertIn("cam_x", framing)
        self.assertIn("game_area_x", framing)
        self.assertIn("SaveCaptureSettingsAsync()", framing)

    def test_live_studio_lists_all_creators_and_loads_the_selected_creator_profile(self):
        live = (DESKTOP / "MainPage.Live.cs").read_text(encoding="utf-8")
        source = (DESKTOP / "MainPage.xaml.cs").read_text(encoding="utf-8")
        framing = (DESKTOP / "MainPage.Framing.cs").read_text(encoding="utf-8")
        self.assertIn("_creators", live)
        self.assertIn("AddLiveCreatorPicker(sourcePanel);", live)
        self.assertIn("foreach (var creator in _creators.OrderBy", live)
        self.assertIn("SelectLiveCreatorAsync(creator)", live)
        self.assertIn("CreatorItem", live)
        self.assertIn("/api/creators/settings?id=", live)
        self.assertIn("_liveSelectedCreatorId", live)
        self.assertIn("SelectLiveCreatorAsync", live)
        self.assertIn("creator.Target", live)
        self.assertIn("SaveCreatorSettingsAsync", source)
        self.assertIn('"/api/creators/settings/save"', source)
        self.assertIn('["creator_id"]', live)
        self.assertIn('SettingString("output_format"', live)
        self.assertIn('new[] { "9:16", "16:9", "1:1", "4:5" }', live)
        self.assertNotIn('SettingString("output_format"', framing)
        self.assertIn("Selected creator", live + framing)

    def test_local_video_settings_are_restored_instead_of_inheriting_creator_settings(self):
        source = (DESKTOP / "MainPage.xaml.cs").read_text(encoding="utf-8")
        live = (DESKTOP / "MainPage.Live.cs").read_text(encoding="utf-8")
        self.assertIn("_globalSettings", source)
        self.assertIn("RestoreGlobalCaptureSettings", live)
        self.assertIn("mode", live)
        self.assertIn("Video file / VOD", live)

    def test_native_font_picker_has_extended_bundled_catalog(self):
        source = (DESKTOP / "MainPage.xaml.cs").read_text(encoding="utf-8")
        settings = (DESKTOP / "MainPage.Manage.cs").read_text(encoding="utf-8")
        project = (DESKTOP / "StreamSnip.Desktop.csproj").read_text(encoding="utf-8")
        for family, asset in (
            ("Manrope", "Manrope-Variable.ttf"),
            ("Nunito Sans", "NunitoSans-Variable.ttf"),
            ("Fira Code", "FiraCode-Variable.ttf"),
            ("DM Sans", "DMSans-Variable.ttf"),
            ("Poppins", "Poppins-Regular.ttf"),
            ("Lato", "Lato-Regular.ttf"),
        ):
            self.assertIn(f'"{family}"', source)
            self.assertIn(asset, source)
            self.assertIn(asset, project)
            self.assertTrue((DESKTOP / "Assets" / "Fonts" / asset).is_file())
        self.assertIn("Manrope", settings)
        self.assertIn("Fira Code", settings)
        self.assertIn("Nunito Sans", settings)
        self.assertIn("JetBrains Mono is the default", settings)

    def test_native_themes_define_distinct_sidebar_foreground_roles(self):
        source = (DESKTOP / "MainPage.xaml.cs").read_text(encoding="utf-8")
        xaml = (DESKTOP / "MainPage.xaml").read_text(encoding="utf-8")
        self.assertIn("SidebarInk", source)
        self.assertIn("SidebarBody", source)
        self.assertIn("SidebarMuted", source)
        self.assertIn('SetResourceBrush("SidebarTextBrush"', source)
        self.assertIn('SetResourceBrush("SidebarBodyTextBrush"', source)
        self.assertIn('SetResourceBrush("SidebarMutedTextBrush"', source)
        self.assertIn('Foreground="{ThemeResource SidebarBodyTextBrush}"', xaml)
        self.assertIn('Foreground="{ThemeResource SidebarMutedTextBrush}"', xaml)
        self.assertIn('x:Key="SidebarBodyTextBrush"', (DESKTOP / "App.xaml").read_text(encoding="utf-8"))
        self.assertIn('x:Key="SidebarMutedTextBrush"', (DESKTOP / "App.xaml").read_text(encoding="utf-8"))

    def test_creator_ui_keeps_only_framing_and_visual_caption_style_per_creator(self):
        live = (DESKTOP / "MainPage.Live.cs").read_text(encoding="utf-8")
        framing = (DESKTOP / "MainPage.Framing.cs").read_text(encoding="utf-8")
        manage = (DESKTOP / "MainPage.Manage.cs").read_text(encoding="utf-8")
        backend = (ROOT / "autoclip.py").read_text(encoding="utf-8")
        dashboard = (ROOT / "dashboard" / "src" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn('AI and caption providers plus clipping defaults are global in AI & Providers and Capture.', live)
        self.assertIn('BuildCaptionProviderSettingsPanel()', manage)
        self.assertIn('Save caption provider', live)
        self.assertIn('SetSetting("transcriber_provider", custom ? "custom-command" : "faster-whisper")', live)
        self.assertIn('SetSetting("transcriber_command", command.Text)', live)
        self.assertIn('"clips_per_chunk"', live)
        self.assertNotIn('"max_clips"', live)
        self.assertIn('AddLabeled(layoutField, "Video layout", layout, "Shared rendering preset for every creator.")', live)
        self.assertIn('AddLabeled(formatField, "Output format", format, "Shared aspect ratio for every creator.")', live)
        self.assertIn("AI provider, caption provider, video layout, output format, and clipping settings are shared defaults.", live)
        self.assertIn("Using {selectedCreator.Name}'s own facecam/game framing, crop coordinates, subtitle styling, and profanity treatment.", live)
        self.assertIn('"Framing is saved separately for this creator. Video layout and output format are shared clipping defaults in the Capture tab.', framing)
        self.assertNotIn('SettingString("layout"', framing)
        self.assertNotIn('SettingString("output_format"', framing)

        shared_block = backend[backend.index('CREATOR_SHARED_SETTING_KEYS = ('):backend.index('def creator_profile_values')]
        for shared in ('transcriber_provider', 'transcriber_command', 'transcriber_language', 'model',
                       'compute_device', 'cpu_threads', 'language', 'clips_per_chunk', 'chunk_min',
                       'pre', 'post', 'min_score', 'capture_bitrate_kbps', 'delete_rec', 'layout', 'output_format'):
            self.assertIn(f'"{shared}"', shared_block)
        for personal in ('profanity_filter_enabled', 'profanity_filter_words', 'profanity_audio_mode'):
            self.assertNotIn(f'"{personal}"', shared_block)
        profile = backend[backend.index('CREATOR_PROFILE_SETTING_KEYS = ('):backend.index('CREATOR_SHARED_SETTING_KEYS = (')]
        for personal in ('cam_x', 'game_area_x', 'crop_x', 'subtitle_style', 'subtitle_animation',
                         'subtitle_text_color', 'streamer_tag', 'show_tag_video',
                         'profanity_filter_enabled', 'profanity_filter_words', 'profanity_audio_mode'):
            self.assertIn(f'"{personal}"', profile)
        for shared in ('transcriber_provider', 'clips_per_chunk', 'min_score', 'layout', 'output_format'):
            self.assertNotIn(f'"{shared}"', profile)
        native = (DESKTOP / "MainPage.xaml.cs").read_text(encoding="utf-8")
        creator_save = native[native.index('private async Task SaveCreatorSettingsAsync'):]
        mirror_match = re.search(r'foreach \(var key in new\[\]\s*\{(.*?)\}\)', creator_save, re.S)
        self.assertIsNotNone(mirror_match, "Global snapshot mirroring must have an explicit allow-list.")
        mirrored_keys = set(re.findall(r'"([^"\n]+)"', mirror_match.group(1)))
        shared_keys = set(re.findall(r'"([^"\n]+)"', shared_block))
        self.assertEqual(mirrored_keys, shared_keys)
        self.assertNotIn("profanity_filter_enabled", mirrored_keys)
        self.assertNotIn("subtitle_style", mirrored_keys)
        self.assertIn('title="Caption provider"', dashboard)
        self.assertIn('Shared default across all creators.', dashboard)

    def test_ai_and_caption_providers_are_in_a_separate_sidebar_providers_section(self):
        xaml = (DESKTOP / "MainPage.xaml").read_text(encoding="utf-8")
        source = (DESKTOP / "MainPage.xaml.cs").read_text(encoding="utf-8")
        live = (DESKTOP / "MainPage.Live.cs").read_text(encoding="utf-8")
        manage = (DESKTOP / "MainPage.Manage.cs").read_text(encoding="utf-8")
        self.assertIn('x:Name="NavProvidersButton" AutomationProperties.Name="Providers" Tag="providers"', xaml)
        self.assertIn('"providers" => "AI & Providers"', source)
        self.assertIn('case "providers":', source)
        self.assertIn('RenderProvidersPage();', source)
        self.assertIn('private void RenderProvidersPage()', manage)
        self.assertIn('\"AI provider\",', manage)
        self.assertIn('\"Caption provider\",', manage)
        self.assertIn('BuildAiSettingsTab()', manage)
        self.assertIn('BuildCaptionProviderSettingsPanel()', manage)
        self.assertNotIn('Header = Txt("AI provider"', live)
        self.assertNotIn('Header = Txt("Caption provider"', live)
        self.assertIn('AddLabeled(speech, "Caption / transcription provider"', live)
        self.assertNotIn('Header = Txt("Caption provider"', live)

    def test_each_creator_has_its_own_start_and_stop_controls(self):
        live = (DESKTOP / "MainPage.Live.cs").read_text(encoding="utf-8")
        self.assertIn('creator.CaptureActive ? "Stop capture"', live)
        self.assertIn('creator.Running ? "Stop live" : "Start live"', live)
        self.assertIn('"/api/creators/start"', live)
        self.assertIn('"/api/creators/stop"', live)
        self.assertIn('"/api/creators/stop-capture"', live)
        self.assertIn('creator.Id', live)
        self.assertIn('await RefreshCreatorsAsync()', live)
        self.assertIn('SaveSelectedCreatorSettingsAsync(creator.Target)', live)

    def test_creator_state_polling_updates_row_controls_without_rebuilding_live_studio(self):
        live = (DESKTOP / "MainPage.Live.cs").read_text(encoding="utf-8")
        source = (DESKTOP / "MainPage.xaml.cs").read_text(encoding="utf-8")
        self.assertIn('private void UpdateLiveCreatorRows()', live)
        self.assertIn('_liveCreatorDetailsById', live)
        self.assertIn('_liveCreatorActionsById', live)
        self.assertIn('action.Content = creator.CaptureStopping', live)
        poll = source[source.index('private async Task RefreshCreatorsForPollingAsync'):source.index('private async Task RunOnUIAsync')]
        self.assertIn('UpdateLiveCreatorRows();', poll)
        toggle = live[live.index('private async Task ToggleCreatorLiveAsync'):live.index('private async Task SelectLiveCreatorAsync')]
        self.assertIn('UpdateLiveCreatorRows();', toggle)
        self.assertNotIn('if (_currentPage == "live" || _currentPage == "creators")\n            RenderCurrentPage();', toggle)

    def test_live_studio_global_start_stop_is_reserved_for_local_video(self):
        live = (DESKTOP / "MainPage.Live.cs").read_text(encoding="utf-8")
        self.assertIn('else if (_liveModeInput?.SelectedIndex == 1)', live)
        self.assertIn('ActionRow(_startCaptureButton, _stopCaptureButton)', live)
        self.assertIn('Use each creator row above to start or stop that creator independently.', live)
        self.assertIn('await PostAsync("/api/start"', live)
        self.assertIn('await PostAsync("/api/stop"', live)

    def test_native_creator_captions_expose_full_custom_style_controls(self):
        live = (DESKTOP / "MainPage.Live.cs").read_text(encoding="utf-8")
        for key in (
            "subtitle_custom", "subtitle_animation", "subtitle_font_size",
            "subtitle_text_color", "subtitle_stroke_color", "subtitle_position",
            "subtitle_alignment", "subtitle_nudge", "words_per_line", "caption_size",
        ):
            self.assertIn(f'"{key}"', live)
        for control in ("Custom caption styling", "Caption font", "Caption text color",
                        "Caption outline color", "Caption position", "Caption alignment",
                        "Caption animation", "Words per line"):
            self.assertIn(control, live)
        self.assertIn("SaveCaptureSettingsAsync()", live)

    def test_dashboard_font_picker_matches_the_bundled_catalog_and_system_families(self):
        app = (ROOT / "dashboard" / "src" / "App.tsx").read_text(encoding="utf-8")
        css = (ROOT / "dashboard" / "src" / "App.css").read_text(encoding="utf-8")
        for family, asset in (
            ("Manrope", "Manrope-Variable.ttf"),
            ("Nunito Sans", "NunitoSans-Variable.ttf"),
            ("Fira Code", "FiraCode-Variable.ttf"),
            ("DM Sans", "DMSans-Variable.ttf"),
            ("Poppins", "Poppins-Regular.ttf"),
            ("Lato", "Lato-Regular.ttf"),
        ):
            self.assertIn(f'name: "{family}"', app)
            self.assertIn(asset, css)
        for family in ("Aptos", "Arial", "Tahoma", "Verdana", "Georgia", "Trebuchet MS", "Times New Roman"):
            self.assertIn(f'name: "{family}"', app)

    def test_native_theme_text_roles_meet_wcag_contrast_on_every_content_surface(self):
        source = (DESKTOP / "MainPage.xaml.cs").read_text(encoding="utf-8")
        self.assertIn("EnsureTextContrastAcross(Ink, 7.0, App, Surface, Soft, Hover)", source)
        self.assertIn("EnsureTextContrastAcross(Body, 4.5, App, Surface, Soft, Hover)", source)
        self.assertIn("EnsureTextContrastAcross(Muted, 4.5, App, Surface, Soft, Hover)", source)
        self.assertIn('EnsureTextContrastAcross(Id == "odysseas" ? "#F7F9F8" : Ink, 7.0, Sidebar, SidebarSurface)', source)
        self.assertIn('EnsureTextContrastAcross(Id == "odysseas" ? "#E0E8E5" : Body, 4.5, Sidebar, SidebarSurface)', source)
        self.assertIn('EnsureTextContrastAcross(Id == "odysseas" ? "#C9D6D1" : Muted, 4.5, Sidebar, SidebarSurface)', source)
        self.assertIn('SidebarSurface => Id == "odysseas" ? "#3A5868" : Soft', source)
        self.assertIn("button.Foreground = new SolidColorBrush(ParseColor(", source)
        self.assertIn("selected ? theme.SidebarInk : theme.SidebarBody", source)
        self.assertIn("live ? theme.SidebarAccentText : theme.SidebarMuted", source)
        self.assertIn('SetResourceBrush("AccentTextBrush", themePalette.AccentText);', source)
        self.assertIn('SetResourceBrush("SuccessTextBrush", themePalette.SuccessText);', source)
        self.assertIn('SetResourceBrush("WarningTextBrush", themePalette.WarningText);', source)
        self.assertIn('SetResourceBrush("DangerTextBrush", themePalette.DangerText);', source)
        self.assertIn('SetResourceBrush("PrimaryTextBrush", themePalette.PrimaryText);', source)
        self.assertIn('SetResourceBrush("BodyTextBrush", themePalette.BodyText);', source)
        self.assertIn('SetResourceBrush("MutedTextBrush", themePalette.MutedText);', source)

        def luminance(value):
            channels = [int(value[index:index + 2], 16) / 255 for index in (1, 3, 5)]
            linear = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4 for channel in channels]
            return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

        def ratio(foreground, background):
            first, second = luminance(foreground), luminance(background)
            return (max(first, second) + 0.05) / (min(first, second) + 0.05)

        def blend(foreground, background, amount):
            front = [int(foreground[index:index + 2], 16) for index in (1, 3, 5)]
            back = [int(background[index:index + 2], 16) for index in (1, 3, 5)]
            return "#" + "".join(f"{round(a * amount + b * (1 - amount)):02X}" for a, b in zip(front, back))

        palettes = list(re.finditer(r'new ThemePalette\("([^\"]+)", "([^\"]+)", (.*?)\),', source, re.S))
        self.assertEqual(len(palettes), 12)
        for palette in palettes:
            values = re.findall(r'"(#[0-9A-Fa-f]{6})"', palette.group(3))
            self.assertEqual(len(values), 13, palette.group(1))
            backgrounds = values[:4]
            for foreground_index, minimum in ((6, 7.0), (7, 4.5), (8, 4.5)):
                foreground = values[foreground_index]
                worst = lambda candidate: min(ratio(candidate, background) for background in backgrounds)
                if worst(foreground) < minimum:
                    target = "#FFFFFF" if worst("#FFFFFF") >= worst("#000000") else "#000000"
                    foreground = next((blend(target, foreground, step / 100) for step in range(1, 101)
                                       if worst(blend(target, foreground, step / 100)) >= minimum), target)
                self.assertGreaterEqual(worst(foreground), minimum, palette.group(1))
    def test_sidebar_and_semantic_text_roles_are_contrast_checked_for_all_twelve_palettes(self):
        source = (DESKTOP / "MainPage.xaml.cs").read_text(encoding="utf-8")
        self.assertIn("SidebarAccentBorder => EnsureTextContrastAcross(Accent, 3.0, Sidebar, SidebarSurface)", source)
        self.assertIn("SidebarAccentText => EnsureTextContrastAcross(Accent, 4.5, Sidebar, SidebarSurface)", source)
        for role, foreground, threshold in (
            ("AccentText", "Accent", "4.5"),
            ("SuccessText", "Success", "4.5"),
            ("WarningText", "Warning", "4.5"),
            ("DangerText", "Danger", "4.5"),
        ):
            self.assertIn(f"{role} => EnsureTextContrastAcross({foreground}, {threshold}, App, Surface, Soft, Hover)", source)
        self.assertIn("EnsureTextContrastAcross(Accent, 4.5, Sidebar, SidebarSurface)", source)
        self.assertIn('SetResourceBrush("SidebarSurfaceBrush", themePalette.SidebarSurface);', source)

        def luminance(value):
            channels = [int(value[index:index + 2], 16) / 255 for index in (1, 3, 5)]
            linear = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4 for channel in channels]
            return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

        def ratio(first, second):
            a, b = luminance(first), luminance(second)
            return (max(a, b) + 0.05) / (min(a, b) + 0.05)

        def blend(target, foreground, amount):
            front = [int(foreground[index:index + 2], 16) for index in (1, 3, 5)]
            back = [int(target[index:index + 2], 16) for index in (1, 3, 5)]
            return "#" + "".join(f"{round(a * amount + b * (1 - amount)):02X}" for a, b in zip(front, back))

        def corrected(foreground, backgrounds, minimum):
            worst = lambda candidate: min(ratio(candidate, bg) for bg in backgrounds)
            if worst(foreground) >= minimum:
                return foreground
            target = "#FFFFFF" if worst("#FFFFFF") >= worst("#000000") else "#000000"
            return next((blend(target, foreground, step / 100) for step in range(1, 101)
                         if worst(blend(target, foreground, step / 100)) >= minimum), target)

        themes = list(re.finditer(r'new ThemePalette\("([^\"]+)", "([^\"]+)", (.*?)\),', source, re.S))
        self.assertEqual(len(themes), 12)
        for theme in themes:
            theme_id = theme.group(1)
            values = re.findall(r'"(#[0-9A-Fa-f]{6})"', theme.group(3))
            self.assertEqual(len(values), 13, theme_id)
            sidebar_surface = "#3A5868" if theme_id == "odysseas" else values[2]
            sidebar = [values[4], sidebar_surface]
            base = [values[0], values[1], values[2], values[3]]
            for idx, threshold in ((5, 7.0), (6, 4.5), (7, 4.5)):
                self.assertGreaterEqual(min(ratio(corrected(values[idx], base, threshold), bg) for bg in base),
                                        threshold, f"{theme_id} content text")
            special = {
                "odysseas": ("#F7F9F8", "#E0E8E5", "#C9D6D1", "#7F9BA6"),
            }.get(theme_id, (values[5], values[6], values[7], values[8]))
            for foreground, threshold in zip(special, (7.0, 4.5, 4.5, 3.0)):
                self.assertGreaterEqual(min(ratio(corrected(foreground, sidebar, threshold), bg) for bg in sidebar),
                                        threshold, f"{theme_id} sidebar role")
            for idx in (9, 10, 11, 12):
                foreground = corrected(values[idx], base, 4.5)
                self.assertGreaterEqual(min(ratio(foreground, bg) for bg in base), 4.5,
                                        f"{theme_id} semantic text role {idx}")

    def test_winui_light_and_default_theme_dictionaries_override_control_template_states(self):
        app = (DESKTOP / "App.xaml").read_text(encoding="utf-8")
        source = (DESKTOP / "MainPage.xaml.cs").read_text(encoding="utf-8")
        self.assertIn('<ResourceDictionary x:Key="Default">', app)
        self.assertIn('<ResourceDictionary x:Key="Light">', app)
        self.assertIn('Application.Current.Resources.ThemeDictionaries.TryGetValue(themeKey, out var dictionaryValue)', source)
        for key in (
            "TextControlForeground", "TextControlForegroundDisabled", "TextControlBackgroundDisabled",
            "ButtonForeground", "ButtonForegroundDisabled", "ButtonBackgroundDisabled",
            "ComboBoxForeground", "ComboBoxForegroundDisabled", "ComboBoxBackground",
            "ComboBoxDropDownBackground", "ComboBoxItemForegroundSelected",
            "TabViewItemHeaderForegroundSelected", "TabViewItemHeaderBackgroundSelected",
            "CheckBoxForegroundChecked", "RadioButtonForeground", "ProgressBarForeground",
        ):
            self.assertGreaterEqual(app.count(f'x:Key="{key}"'), 2, f"{key} must have Default and Light values.")

    def test_theme_brush_updates_preserve_app_references_and_replace_frozen_theme_entries(self):
        source = (DESKTOP / "MainPage.xaml.cs").read_text(encoding="utf-8")
        start = source.index("private void SetResourceBrush(string key, string hex)")
        end = source.index("private void RootBackgroundUpdate()", start)
        method = source[start:end]
        self.assertIn("Application.Current.Resources[key] = new SolidColorBrush(color);", method)
        self.assertIn("Resources[key] = new SolidColorBrush(color);", method)
        self.assertIn("themeDictionary[key] = new SolidColorBrush(color);", method)
        self.assertNotIn(".Color = color;", method)

    def test_theme_palette_xaml_uses_dynamic_theme_resources_and_updates_window_root(self):
        app = (DESKTOP / "App.xaml").read_text(encoding="utf-8")
        page = (DESKTOP / "MainPage.xaml").read_text(encoding="utf-8")
        source = (DESKTOP / "MainPage.xaml.cs").read_text(encoding="utf-8")
        roles = (
            "AppBackgroundBrush", "SurfaceBrush", "SurfaceSoftBrush", "SurfaceHoverBrush",
            "SidebarBrush", "SidebarSurfaceBrush", "SidebarTextBrush", "SidebarBodyTextBrush",
            "SidebarMutedTextBrush", "SidebarLineBrush", "PrimaryTextBrush", "BodyTextBrush",
            "MutedTextBrush", "LineBrush", "AccentBrush", "AccentSoftBrush", "AccentInkBrush",
            "AccentTextBrush", "SuccessBrush", "WarningBrush", "DangerBrush",
            "SuccessTextBrush", "WarningTextBrush", "DangerTextBrush",
        )
        for role in roles:
            self.assertGreaterEqual(app.count(f'x:Key="{role}"'), 3, role)
            self.assertNotIn(f'{{StaticResource {role}}}', app, role)
            self.assertNotIn(f'{{StaticResource {role}}}', page, role)
        self.assertIn('windowRoot.Background = new SolidColorBrush(ParseColor(palette.App));', source)
        self.assertIn('Application.Current.Resources[key] = new SolidColorBrush(color);', source)
        self.assertIn('themeDictionary[key] = new SolidColorBrush(color);', source)

    def test_main_page_static_resource_keys_exist_before_window_initialization(self):
        app_xaml = (DESKTOP / "App.xaml").read_text(encoding="utf-8")
        page_xaml = (DESKTOP / "MainPage.xaml").read_text(encoding="utf-8")
        defined = set(re.findall(r'x:Key="([^"]+)"', app_xaml))
        referenced = set(re.findall(r'\{StaticResource\s+([^}]+)\}', page_xaml))
        self.assertFalse(
            referenced - defined,
            "Every StaticResource used by MainPage.xaml must exist before InitializeComponent; theme code runs too late to define it.",
        )

    def test_capture_tab_owns_shared_video_layout_and_output_ratio_controls(self):
        framing = (DESKTOP / "MainPage.Framing.cs").read_text(encoding="utf-8")
        live = (DESKTOP / "MainPage.Live.cs").read_text(encoding="utf-8")
        self.assertIn('AddLabeled(layoutField, "Video layout", layout, "Shared rendering preset for every creator.")', live)
        self.assertIn('AddLabeled(formatField, "Output format", format, "Shared aspect ratio for every creator.")', live)
        self.assertIn('SetSetting("layout"', live)
        self.assertIn('SetSetting("output_format"', live)
        self.assertNotIn('SettingString("layout"', framing)
        self.assertNotIn('SettingString("output_format"', framing)
        self.assertIn('Framing is saved separately for this creator. Video layout and output format are shared clipping defaults in the Capture tab.', framing)
