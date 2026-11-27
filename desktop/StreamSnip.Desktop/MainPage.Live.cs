using System.Globalization;
using System.Text.Json.Nodes;
using Microsoft.UI;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Imaging;
using Windows.Storage;
using Windows.Storage.Pickers;
using Windows.Storage.Streams;
using Windows.UI;

namespace StreamSnip_Desktop;

public sealed partial class MainPage
{
    private TextBlock? _liveStatusText;
    private TextBlock? _liveProgressText;
    private ProgressBar? _liveProgress;
    private TextBox? _liveTargetInput;
    private ComboBox? _liveModeInput;
    private Button? _startCaptureButton;
    private Button? _stopCaptureButton;
    private TabView? _liveTabs;
    private Image? _sourcePreviewImage;
    private StackPanel? _sourcePreviewPlaceholder;
    private TextBlock? _sourcePreviewInfo;
    private string? _liveSelectedCreatorId;
    private bool _switchingLiveMode;
    private readonly Dictionary<string, TextBlock> _liveCreatorDetailsById = new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<string, Button> _liveCreatorActionsById = new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<string, Button> _liveCreatorSelectButtonsById = new(StringComparer.OrdinalIgnoreCase);

    private void RenderLiveStudioPage()
    {
        _liveStatusText = null;
        _liveProgressText = null;
        _liveProgress = null;
        _liveTargetInput = null;
        _liveModeInput = null;

        AddPageHeading("Live Studio", "Start and stop each saved creator independently. Customize that creator's framing and visual captions here; configure global AI and caption providers in AI & Providers.");

        var sourcePanel = new StackPanel { Spacing = 12 };
        _liveModeInput = new ComboBox { MinWidth = 180, HorizontalAlignment = HorizontalAlignment.Stretch };
        _liveModeInput.ItemsSource = new[] { "Live stream", "Video file / VOD" };
        _liveModeInput.SelectedIndex = SettingString("mode", "live") == "file" ? 1 : 0;
        _switchingLiveMode = true;
        _liveModeInput.SelectionChanged += async (_, _) =>
        {
            if (_switchingLiveMode || _settings is null)
                return;

            try
            {
                var nextMode = _liveModeInput.SelectedIndex == 1 ? "file" : "live";
                var currentTarget = _liveTargetInput?.Text.Trim() ?? SettingString("target");
                if (nextMode == "file")
                {
                    if (_liveSelectedCreatorId is not null)
                        await SaveSelectedCreatorSettingsAsync(currentTarget);

                    RestoreGlobalCaptureSettings();
                    SetSetting("mode", "file");
                    if (!string.Equals(_globalSettings?["mode"]?.ToString(), "file", StringComparison.OrdinalIgnoreCase))
                        SetSetting("target", "");
                    _liveSelectedCreatorId = null;
                    _framingValuesInitialized = false;
                    _framingBitmap = null;
                }
                else
                {
                    RestoreGlobalCaptureSettings();
                    SetSetting("mode", "live");
                    SetSetting("target", "");
                    _liveSelectedCreatorId = null;
                    _framingValuesInitialized = false;
                    _framingBitmap = null;
                }
                RenderCurrentPage();
            }
            catch (Exception ex)
            {
                await ShowErrorAsync("Could not change source type", ex.Message);
            }
        };
        AddLabeled(sourcePanel, "Source type", _liveModeInput);
        _switchingLiveMode = false;

        if (_liveModeInput.SelectedIndex == 0)
            AddLiveCreatorPicker(sourcePanel);

        _liveTargetInput = Input(
            SettingString("target"),
            SettingString("mode", "live") == "file"
                ? "Choose a local video file…" : "Select a saved creator above");
        _liveTargetInput.IsReadOnly = _liveModeInput.SelectedIndex == 0;
        AddLabeled(sourcePanel, "Stream URL or video file", _liveTargetInput,
            "The same source is used for creator detection, frame preview, and capture.");
        _sourcePreviewInfo = ThemeText("Preview updates from the selected source.", 14, false, "MutedTextBrush");
        var sourcePreview = new StackPanel { Spacing = 8 };
        var previewSurface = new Grid { MinHeight = 120 };
        _sourcePreviewImage = new Image
        {
            Stretch = Stretch.Uniform,
            MaxHeight = 260,
            HorizontalAlignment = HorizontalAlignment.Center,
            VerticalAlignment = VerticalAlignment.Center
        };
        previewSurface.Children.Add(_sourcePreviewImage);

        _sourcePreviewPlaceholder = new StackPanel
        {
            Spacing = 8,
            HorizontalAlignment = HorizontalAlignment.Center,
            VerticalAlignment = VerticalAlignment.Center
        };
        _sourcePreviewPlaceholder.Children.Add(new PathIcon
        {
            Data = CreateVideoIconGeometry(),
            Width = 30,
            Height = 30,
            Foreground = Application.Current.Resources["MutedTextBrush"] as Brush
        });
        var previewTitle = ThemeText("Source preview", 14, true, "PrimaryTextBrush");
        previewTitle.HorizontalAlignment = HorizontalAlignment.Center;
        _sourcePreviewPlaceholder.Children.Add(previewTitle);
        var previewHint = ThemeText("Paste a stream URL or choose a video file.", 12, false, "MutedTextBrush");
        previewHint.HorizontalAlignment = HorizontalAlignment.Center;
        _sourcePreviewPlaceholder.Children.Add(previewHint);
        previewSurface.Children.Add(_sourcePreviewPlaceholder);
        previewSurface.SizeChanged += (_, args) =>
            previewSurface.Height = Math.Max(120, args.NewSize.Width * 9.0 / 16.0);
        previewSurface.Loaded += (_, _) =>
            previewSurface.Height = Math.Max(120, previewSurface.ActualWidth * 9.0 / 16.0);

        sourcePreview.Children.Add(new Border
        {
            Background = Application.Current.Resources["SurfaceSoftBrush"] as Brush,
            BorderBrush = Application.Current.Resources["LineBrush"] as Brush,
            BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(9),
            Padding = new Thickness(10),
            Child = previewSurface
        });
        sourcePreview.Children.Add(_sourcePreviewInfo);
        _liveTargetInput.TextChanged += (_, _) =>
        {
            if (_sourcePreviewImage is not null) _sourcePreviewImage.Source = null;
            if (_sourcePreviewPlaceholder is not null) _sourcePreviewPlaceholder.Visibility = Visibility.Visible;
            if (_sourcePreviewInfo is not null)
            {
                var detected = InferCreatorHandle(_liveTargetInput.Text);
                _sourcePreviewInfo.Text = detected is null
                    ? "Creator handle is not exposed by this URL."
                    : $"Detected creator handle: {detected}";
            }
        };
        var browseButton = CreateButton("Browse video", async () =>
        {
            try
            {
                var file = await PickVideoFileAsync();
                if (file is not null)
                {
                    _liveModeInput.SelectedIndex = 1;
                    _liveTargetInput.Text = file.Path;
                    SetSetting("mode", "file");
                    SetSetting("target", file.Path);
                }
            }
            catch (Exception ex) { await ShowErrorAsync("File selection failed", ex.Message); }
        });
        var detect = CreateButton("Preview source frame", async () =>
        {
            var target = _liveTargetInput.Text.Trim();
            if (target.Length == 0) return;
            try
            {
                var result = await PostAsync("/api/frame", new JsonObject
                {
                    ["mode"] = SettingString("mode", "live"),
                    ["target"] = target
                });
                var frameData = result["image"]?.GetValue<string>();
                if (string.IsNullOrWhiteSpace(frameData))
                    throw new InvalidOperationException("The source preview response did not contain an image.");
                var separator = frameData.IndexOf(',');
                var base64 = separator >= 0 ? frameData[(separator + 1)..] : frameData;
                var bytes = Convert.FromBase64String(base64);
                using var stream = new InMemoryRandomAccessStream();
                using (var writer = new DataWriter(stream.GetOutputStreamAt(0)))
                {
                    writer.WriteBytes(bytes);
                    await writer.StoreAsync();
                    await writer.FlushAsync();
                }
                stream.Seek(0);
                var bitmap = new BitmapImage();
                await bitmap.SetSourceAsync(stream);
                if (_sourcePreviewImage is not null) _sourcePreviewImage.Source = bitmap;
                if (_sourcePreviewPlaceholder is not null) _sourcePreviewPlaceholder.Visibility = Visibility.Collapsed;
                var detected = InferCreatorHandle(target);
                if (_sourcePreviewInfo is not null)
                    _sourcePreviewInfo.Text = detected is null
                        ? "Frame captured · this URL does not expose a creator handle. Creator credit can be entered in Captions."
                        : $"Frame captured · detected creator handle: {detected}";
            }
            catch (Exception ex) { await ShowErrorAsync("Source preview failed", ex.Message); }
        });
        sourcePanel.Children.Add(ActionRow(browseButton, detect));
        sourcePanel.Children.Add(sourcePreview);

        if (_liveModeInput.SelectedIndex == 1)
        {
            sourcePanel.Children.Add(ThemeText(
                "Local video settings are separate from live creators. Use this mode for cat videos, downloaded VODs, and any MP4 you want to clip.",
                11, false, "MutedTextBrush"));
        }
        else if (_liveSelectedCreatorId is not null)
        {
            var selectedCreator = _creators.FirstOrDefault(item => item.Id == _liveSelectedCreatorId);
            if (selectedCreator is not null)
                sourcePanel.Children.Add(ThemeText(
                    $"Using {selectedCreator.Name}'s own facecam/game framing, crop coordinates, subtitle styling, and profanity treatment. AI provider, caption provider, video layout, output format, and clipping settings are shared across creators.",
                    11, false, "MutedTextBrush"));
        }

        var tabs = new TabView
        {
            IsAddTabButtonVisible = false,
            CanReorderTabs = false,
            CanDragTabs = false,
            TabWidthMode = TabViewWidthMode.Equal,
            FontFamily = CurrentFont,
            FontSize = 16
        };
        _liveTabs = tabs;

        var capture = new StackPanel { Spacing = 12, Padding = new Thickness(4, 12, 4, 4) };
        var captureGrid = new Grid { ColumnSpacing = 14, RowSpacing = 12 };
        captureGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        captureGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        for (var row = 0; row < 3; row++)
            captureGrid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        AddSettingNumber(captureGrid, 0, 0, "Capture chunk length (minutes)", "chunk_min", 3, 15);
        AddSettingNumber(captureGrid, 1, 0, "Seconds before highlight", "pre", 3, 90);
        AddSettingNumber(captureGrid, 0, 1, "Seconds after highlight", "post", 3, 90);
        AddSettingNumber(captureGrid, 1, 1, "Minimum highlight score", "min_score", 0, 100);
        AddSettingNumber(captureGrid, 0, 2, "Capture bitrate (Kbps)", "capture_bitrate_kbps", 8000, 50000);
        AddSettingNumber(captureGrid, 1, 2, "Clips per batch", "clips_per_chunk", 0, 10);
        capture.Children.Add(captureGrid);

        var renderDefaults = new Grid { ColumnSpacing = 14, RowSpacing = 8 };
        renderDefaults.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        renderDefaults.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        var layoutField = new StackPanel { Spacing = 5 };
        var layouts = _settings?.Layouts?.Length > 0
            ? _settings.Layouts : ["Facecam + game (Twitch)", "Full video", "Selected crop"];
        var layout = new ComboBox { ItemsSource = layouts, MinWidth = 220, HorizontalAlignment = HorizontalAlignment.Stretch };
        layout.SelectedItem = SettingString("layout", layouts[0]);
        layout.SelectionChanged += (_, _) => SetSetting("layout", layout.SelectedItem?.ToString() ?? layouts[0]);
        AddLabeled(layoutField, "Video layout", layout, "Shared rendering preset for every creator.");
        Grid.SetColumn(layoutField, 0);
        renderDefaults.Children.Add(layoutField);

        var formatField = new StackPanel { Spacing = 5 };
        var format = new ComboBox { ItemsSource = new[] { "9:16", "16:9", "1:1", "4:5" }, MinWidth = 150, HorizontalAlignment = HorizontalAlignment.Stretch };
        format.SelectedItem = SettingString("output_format", "9:16");
        format.SelectionChanged += (_, _) => SetSetting("output_format", format.SelectedItem?.ToString() ?? "9:16");
        AddLabeled(formatField, "Output format", format, "Shared aspect ratio for every creator.");
        Grid.SetColumn(formatField, 1);
        renderDefaults.Children.Add(formatField);
        capture.Children.Add(ThemeText("Shared clipping defaults for every creator", 11, true, "PrimaryTextBrush"));
        capture.Children.Add(renderDefaults);

        capture.Children.Add(ThemeText("Settings are applied to the next capture. Existing work is not changed.", 10, false, "MutedTextBrush"));
        tabs.TabItems.Add(new TabViewItem { Header = "Capture", Content = capture, IsClosable = false });

        var framing = BuildFramingTab();
        tabs.TabItems.Add(new TabViewItem { Header = "Framing", Content = framing, IsClosable = false });



        var captions = new StackPanel { Spacing = 12, Padding = new Thickness(4, 12, 4, 4) };
        var captionMode = new ComboBox { MinWidth = 170 };
        captionMode.ItemsSource = new[] { "Karaoke", "Classic" };
        captionMode.SelectedItem = SettingString("subtitle_mode", "Karaoke");
        captionMode.SelectionChanged += (_, _) => SetSetting("subtitle_mode", captionMode.SelectedItem?.ToString() ?? "Karaoke");
        AddLabeled(captions, "Subtitle mode", captionMode);
        var style = new ComboBox { MinWidth = 220 };
        style.ItemsSource = new[] { "GTA Neon", "Classic", "Hormozi", "Neon", "MrBeast", "Minimal", "Fire" };
        style.SelectedItem = SettingString("subtitle_style", "GTA Neon");
        style.SelectionChanged += (_, _) => SetSetting("subtitle_style", style.SelectedItem?.ToString() ?? "GTA Neon");
        AddLabeled(captions, "Subtitle style", style);

        var highlight = new ComboBox { MinWidth = 170 };
        highlight.ItemsSource = new[] { "Yellow", "Green", "Cyan", "Orange", "Pink" };
        highlight.SelectedItem = SettingString("color", "Yellow");
        highlight.SelectionChanged += (_, _) => SetSetting("color", highlight.SelectedItem?.ToString() ?? "Yellow");
        AddLabeled(captions, "Caption highlight color", highlight);

        var presetPosition = new ComboBox { MinWidth = 180 };
        presetPosition.ItemsSource = new[] { "Top", "Upper third", "Middle", "Lower third", "Bottom" };
        presetPosition.SelectedItem = SettingString("position", "Lower third");
        presetPosition.SelectionChanged += (_, _) => SetSetting("position", presetPosition.SelectedItem?.ToString() ?? "Lower third");
        AddLabeled(captions, "Caption location preset", presetPosition);

        var baseSize = Input(SettingNumber("caption_size", 82).ToString(System.Globalization.CultureInfo.InvariantCulture));
        baseSize.TextChanged += (_, _) =>
        {
            if (int.TryParse(baseSize.Text, out var value))
                SetSetting("caption_size", Math.Clamp(value, 60, 150));
        };
        AddLabeled(captions, "Preset caption size (60–150)", baseSize);

        var wordsPerLine = new ComboBox { MinWidth = 140 };
        wordsPerLine.ItemsSource = new[] { "1", "2", "3", "4" };
        wordsPerLine.SelectedItem = SettingNumber("words_per_line", 3).ToString(System.Globalization.CultureInfo.InvariantCulture);
        wordsPerLine.SelectionChanged += (_, _) =>
        {
            if (int.TryParse(wordsPerLine.SelectedItem?.ToString(), out var value))
                SetSetting("words_per_line", value);
        };
        AddLabeled(captions, "Words per line", wordsPerLine);

        var customCaption = new CheckBox
        {
            Content = "Custom caption styling",
            IsChecked = SettingBool("subtitle_custom"),
            FontFamily = CurrentFont,
            Foreground = Application.Current.Resources["BodyTextBrush"] as Brush
        };
        var customCaptionFields = new StackPanel { Spacing = 10 };
        var captionFonts = new ComboBox { MinWidth = 230 };
        captionFonts.ItemsSource = new[]
        {
            "Impact", "Arial Black", "Arial", "Aptos", "Roboto", "Segoe UI",
            "Verdana", "Tahoma", "Trebuchet MS", "Georgia", "Times New Roman"
        };
        captionFonts.SelectedItem = SettingString("font", "Impact");
        captionFonts.SelectionChanged += (_, _) => SetSetting("font", captionFonts.SelectedItem?.ToString() ?? "Impact");
        AddLabeled(customCaptionFields, "Caption font", captionFonts);

        var customSize = Input(SettingNumber("subtitle_font_size", 82).ToString(System.Globalization.CultureInfo.InvariantCulture));
        customSize.TextChanged += (_, _) =>
        {
            if (int.TryParse(customSize.Text, out var value))
                SetSetting("subtitle_font_size", Math.Clamp(value, 60, 180));
        };
        AddLabeled(customCaptionFields, "Custom font size (60–180)", customSize);

        var textColor = Input(SettingString("subtitle_text_color", "#FFFFFF"), "#RRGGBB");
        textColor.TextChanged += (_, _) => SetSetting("subtitle_text_color", textColor.Text.Trim());
        AddLabeled(customCaptionFields, "Caption text color", textColor, "Use a six-digit hex value, for example #FFFFFF.");

        var strokeColor = Input(SettingString("subtitle_stroke_color", "#000000"), "#RRGGBB");
        strokeColor.TextChanged += (_, _) => SetSetting("subtitle_stroke_color", strokeColor.Text.Trim());
        AddLabeled(customCaptionFields, "Caption outline color", strokeColor, "Use a six-digit hex value, for example #000000.");

        var captionPosition = new ComboBox { MinWidth = 160 };
        captionPosition.ItemsSource = new[] { "Top", "Center", "Bottom" };
        captionPosition.SelectedItem = SettingString("subtitle_position", "Bottom");
        captionPosition.SelectionChanged += (_, _) => SetSetting("subtitle_position", captionPosition.SelectedItem?.ToString() ?? "Bottom");
        AddLabeled(customCaptionFields, "Caption position", captionPosition);

        var captionAlignment = new ComboBox { MinWidth = 160 };
        captionAlignment.ItemsSource = new[] { "Left", "Center" };
        captionAlignment.SelectedItem = SettingString("subtitle_alignment", "Center");
        captionAlignment.SelectionChanged += (_, _) => SetSetting("subtitle_alignment", captionAlignment.SelectedItem?.ToString() ?? "Center");
        AddLabeled(customCaptionFields, "Caption alignment", captionAlignment);

        var animation = new ComboBox { MinWidth = 230 };
        animation.ItemsSource = new[]
        {
            "highlight", "pop_in", "pop_in_line", "one_by_one", "build_up", "full_line"
        };
        animation.SelectedItem = SettingString("subtitle_animation", "highlight");
        animation.SelectionChanged += (_, _) => SetSetting("subtitle_animation", animation.SelectedItem?.ToString() ?? "highlight");
        AddLabeled(customCaptionFields, "Caption animation", animation);

        var verticalNudge = Input(SettingNumber("subtitle_nudge", 0).ToString(System.Globalization.CultureInfo.InvariantCulture));
        verticalNudge.TextChanged += (_, _) =>
        {
            if (int.TryParse(verticalNudge.Text, out var value))
                SetSetting("subtitle_nudge", Math.Clamp(value, -400, 400));
        };
        AddLabeled(customCaptionFields, "Vertical nudge (-400 to 400)", verticalNudge);

        void UpdateCustomCaptionVisibility()
        {
            var enabled = customCaption.IsChecked == true;
            customCaptionFields.Visibility = enabled ? Visibility.Visible : Visibility.Collapsed;
            SetSetting("subtitle_custom", enabled);
        }
        customCaption.Checked += (_, _) => UpdateCustomCaptionVisibility();
        customCaption.Unchecked += (_, _) => UpdateCustomCaptionVisibility();
        captions.Children.Add(customCaption);
        captions.Children.Add(customCaptionFields);
        UpdateCustomCaptionVisibility();

        captions.Children.Add(ThemeText(
            "These caption settings are stored with the selected creator. Local videos keep a separate local-video profile.",
            11, false, "MutedTextBrush"));

        var credit = Input(SettingString("streamer_tag"), "Auto-detected from source URL");
        AddLabeled(captions, "Creator credit", credit,
            "Leave blank to infer a handle from supported Twitch and YouTube channel URLs.");
        credit.TextChanged += (_, _) => SetSetting("streamer_tag", credit.Text);
        var showTag = new CheckBox
        {
            Content = "Show creator tag in the video",
            IsChecked = SettingBool("show_tag_video", true),
            FontFamily = CurrentFont,
            Foreground = Application.Current.Resources["BodyTextBrush"] as Brush
        };
        showTag.Checked += (_, _) => SetSetting("show_tag_video", true);
        showTag.Unchecked += (_, _) => SetSetting("show_tag_video", false);
        captions.Children.Add(showTag);
        var profanity = new CheckBox
        {
            Content = "Filter detected profanity",
            IsChecked = SettingBool("profanity_filter_enabled"),
            FontFamily = CurrentFont,
            Foreground = Application.Current.Resources["BodyTextBrush"] as Brush
        };
        profanity.Checked += (_, _) => SetSetting("profanity_filter_enabled", true);
        profanity.Unchecked += (_, _) => SetSetting("profanity_filter_enabled", false);
        captions.Children.Add(profanity);
        tabs.TabItems.Add(new TabViewItem { Header = "Captions", Content = captions, IsClosable = false });

        var saveCreatorSetup = CreateButton(
            _liveModeInput.SelectedIndex == 1 ? "Save local video setup" : "Save creator setup",
            async () =>
            {
                try
                {
                    SetSetting("target", _liveTargetInput?.Text.Trim() ?? "");
                    SetSetting("mode", _liveModeInput?.SelectedIndex == 1 ? "file" : "live");
                    await SaveCaptureSettingsAsync();
                    await DialogResultAsync(
                        "Settings saved",
                        _liveModeInput?.SelectedIndex == 1
                            ? "Shared AI, caption-provider, and clipping defaults were saved for local videos and every creator."
                            : "This creator's framing, crop coordinates, subtitle styling, and profanity treatment were saved. Shared AI/caption providers and clipping defaults were updated for every creator.");
                }
                catch (Exception ex) { await ShowErrorAsync("Could not save setup", ex.Message); }
            }, primary: true);
        saveCreatorSetup.IsEnabled = _engine is not null;
        var setupContent = new StackPanel { Spacing = 12 };
        setupContent.Children.Add(tabs);
        setupContent.Children.Add(ActionRow(saveCreatorSetup));

        var setupPanel = CreatePanel("Capture setup",
            "Each creator keeps separate facecam/game framing, crop coordinates, subtitle styling, and profanity treatment. AI provider, caption provider, video layout, output format, and clipping settings are shared defaults.",
            setupContent);

        var current = _state ?? new EngineState();
        _liveStatusText = Txt(_engine is null ? "Local processing unavailable" : current.Status, 16, true);
        _liveProgressText = ThemeText(
            _engine is null ? "Repair the local runtime to restore capture and rendering."
                : $"{PhaseLabel(current.Phase)} · {current.Progress}% · {current.Session.Clips:N0} clips",
            14, false, "MutedTextBrush");
        _liveProgress = new ProgressBar
        {
            Minimum = 0,
            Maximum = 100,
            Value = Math.Clamp(current.Progress, 0, 100),
            Height = 7,
            Visibility = _engine is null ? Visibility.Collapsed : Visibility.Visible,
            Margin = new Thickness(0, 4, 0, 0),
            Background = Application.Current.Resources["SurfaceSoftBrush"] as Brush,
            Foreground = Application.Current.Resources["AccentBrush"] as Brush
        };
        _startCaptureButton = CreateButton("Start capture", async () =>
        {
            try
            {
                SetSetting("target", _liveTargetInput?.Text.Trim() ?? "");
                SetSetting("mode", _liveModeInput?.SelectedIndex == 1 ? "file" : "live");
                if (SettingString("mode", "live") != "file")
                    throw new InvalidOperationException("Use the Start live / Stop live control on the individual creator row.");
                if (string.IsNullOrWhiteSpace(SettingString("target")))
                    throw new InvalidOperationException("Choose a saved creator or local video file first.");
                if (SettingString("mode", "live") == "live" && _liveSelectedCreatorId is null)
                    throw new InvalidOperationException("Select one of your saved creators first. Add a new channel from Manage creators to create its own framing and caption profile.");

                var ai = _settings?.Ai ?? new JsonObject();
                var aiProvider = ai["provider"]?.ToString() ?? "gemini";
                var providerReady = aiProvider switch
                {
                    "gemini" => ai["gemini_key_set"]?.GetValue<bool>() == true,
                    "openai" => ai["openai_key_set"]?.GetValue<bool>() == true &&
                                !string.IsNullOrWhiteSpace(ai["openai_model"]?.ToString()),
                    "anthropic" => ai["anthropic_key_set"]?.GetValue<bool>() == true &&
                                   !string.IsNullOrWhiteSpace(ai["anthropic_model"]?.ToString()),
                    "custom" => !string.IsNullOrWhiteSpace(ai["custom_api_model"]?.ToString()),
                    "ollama" => true,
                    _ => false
                };
                if (!providerReady)
                {
                    NavigateTo("providers");
                    var message = aiProvider switch
                    {
                        "gemini" => "Save a Google AI Studio API key in AI & Providers before starting a local-video capture.",
                        "openai" => "Save an OpenAI API key and model in AI & Providers before starting a local-video capture.",
                        "anthropic" => "Save an Anthropic API key and Claude model in AI & Providers before starting a local-video capture.",
                        "custom" => "Enter and save the model name for your custom OpenAI-compatible endpoint.",
                        _ => "Choose a supported AI provider in AI & Providers."
                    };
                    throw new InvalidOperationException(message);
                }
                await SaveCaptureSettingsAsync();
                await PostAsync("/api/start", _settings?.Values.DeepClone() as JsonObject ?? new JsonObject());
                await RefreshStateAsync(forceRender: false);
            }
            catch (Exception ex) { await ShowErrorAsync("Could not start capture", ex.Message); }
        }, primary: true);
        _stopCaptureButton = CreateButton("Stop capture", async () =>
        {
            try
            {
                await PostAsync("/api/stop", new JsonObject { ["force"] = false });
                await RefreshStateAsync(forceRender: false);
            }
            catch (Exception ex) { await ShowErrorAsync("Could not stop capture", ex.Message); }
        }, danger: true);
        _startCaptureButton.IsEnabled = _engine is not null && !current.Running;
        _stopCaptureButton.IsEnabled = current.Running;

        var actionBar = new Grid { ColumnSpacing = 24, VerticalAlignment = VerticalAlignment.Center };
        actionBar.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        actionBar.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        var sessionInfo = new StackPanel { Spacing = 3, VerticalAlignment = VerticalAlignment.Center };
        sessionInfo.Children.Add(_liveStatusText);
        sessionInfo.Children.Add(_liveProgressText);
        sessionInfo.Children.Add(_liveProgress);
        actionBar.Children.Add(sessionInfo);

        FrameworkElement captureActions;
        if (_engine is null)
        {
            captureActions = ActionRow(CreateButton("Repair runtime", () =>
            {
                var appRoot = System.IO.Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "Programs", "StreamSnip AI Native");
                var setupScript = System.IO.Path.Combine(appRoot, "setup_windows.ps1");
                if (!System.IO.File.Exists(setupScript))
                {
                    _ = ShowErrorAsync("Installer files are missing",
                        "Run the latest StreamSnip AI installer to restore its setup files, then choose Repair runtime again.");
                    return;
                }
                var start = new System.Diagnostics.ProcessStartInfo
                {
                    FileName = System.IO.Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System),
                        "WindowsPowerShell", "v1.0", "powershell.exe"),
                    UseShellExecute = true,
                    Arguments = "-NoExit -NoProfile -ExecutionPolicy Bypass -File " +
                        "\"" + setupScript + "\"" + " -AppDir " +
                        "\"" + appRoot + "\"" +
                        " -NativeDesktop -NonInteractive -SkipLaunch -NoPause"
                };
                System.Diagnostics.Process.Start(start);
            }));
        }
        else if (_liveModeInput?.SelectedIndex == 1)
        {
            captureActions = ActionRow(_startCaptureButton, _stopCaptureButton);
        }
        else
        {
            captureActions = ActionRow(ThemeText(
                "Use each creator row above to start or stop that creator independently.",
                12, true, "MutedTextBrush"));
        }
        captureActions.VerticalAlignment = VerticalAlignment.Center;
        Grid.SetColumn(captureActions, 1);
        actionBar.Children.Add(captureActions);
        PageActionHost.Child = actionBar;
        PageActionHost.Visibility = Visibility.Visible;

        PageHost.Children.Add(AdaptiveColumns(
            CreatePanel("Source", "Select the stream or recording you want to process.", sourcePanel),
            setupPanel,
            0.95, 1.05));
    }

    private static string LiveCreatorDetails(CreatorItem creator)
    {
        var details = new List<string>
        {
            creator.CaptureStopping ? "Stopping capture" :
            creator.CaptureActive ? "Recording" :
            creator.Running ? (string.Equals(creator.Phase, "stopping", StringComparison.OrdinalIgnoreCase) ? "Stopping live monitor" : "Monitoring") : "Idle"
        };
        if (creator.WatchingVods) details.Add("Watching VOD folder");
        details.Add($"{creator.LiveClips:N0} live clips");
        details.Add($"{creator.VodClips:N0} VOD clips");
        return string.Join("  \u00b7  ", details);
    }

    private void UpdateLiveCreatorRows()
    {
        if (_currentPage != "live") return;
        if (_liveCreatorDetailsById.Count != _creators.Count ||
            _creators.Any(creator => !_liveCreatorDetailsById.ContainsKey(creator.Id)))
        {
            RenderCurrentPage();
            return;
        }
        foreach (var creator in _creators)
        {
            if (_liveCreatorDetailsById.TryGetValue(creator.Id, out var details))
            {
                details.Text = LiveCreatorDetails(creator);
                details.Foreground = Application.Current.Resources[creator.CaptureActive ? "SuccessBrush" : "MutedTextBrush"] as Brush;
            }
            if (_liveCreatorActionsById.TryGetValue(creator.Id, out var action))
            {
                action.Content = creator.CaptureStopping ? "Stopping\u2026" :
                    creator.CaptureActive ? "Stop capture" : creator.Running ? "Stop live" : "Start live";
                action.IsEnabled = _engine is not null && !creator.CaptureStopping &&
                    !string.Equals(creator.Phase, "stopping", StringComparison.OrdinalIgnoreCase);
            }
            if (_liveCreatorSelectButtonsById.TryGetValue(creator.Id, out var select))
            {
                var selected = creator.Id == _liveSelectedCreatorId;
                select.Content = selected ? "Selected" : "Use creator";
                select.IsEnabled = _engine is not null && _state?.Running != true && !selected;
            }
        }
    }

    private void AddLiveCreatorPicker(StackPanel parent)
    {
        _liveCreatorDetailsById.Clear();
        _liveCreatorActionsById.Clear();
        _liveCreatorSelectButtonsById.Clear();
        var header = new Grid { ColumnSpacing = 12 };
        header.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        header.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        var title = new StackPanel { Spacing = 3 };
        title.Children.Add(Txt("Saved creators", 14, true));
        title.Children.Add(ThemeText(
            "Each creator keeps separate facecam/game framing, crop coordinates, subtitle styling, and profanity treatment. AI provider, caption provider, video layout, output format, and clipping settings are shared defaults.",
            11, false, "MutedTextBrush"));
        header.Children.Add(title);
        var manage = CreateButton("Manage creators", () => NavigateTo("creators"));
        Grid.SetColumn(manage, 1);
        header.Children.Add(manage);
        parent.Children.Add(header);

        if (_creators.Count == 0)
        {
            var empty = new StackPanel { Spacing = 8 };
            empty.Children.Add(ThemeText(
                "No saved creators yet. Add your Twitch or YouTube channels and they will appear here.",
                12, false, "MutedTextBrush"));
            empty.Children.Add(CreateButton("Add a creator", () => NavigateTo("creators"), primary: true));
            parent.Children.Add(CreatePanel("Creator sources", "", empty));
            return;
        }

        var list = new StackPanel { Spacing = 0 };
        foreach (var creator in _creators.OrderBy(item => item.Name, StringComparer.CurrentCultureIgnoreCase))
        {
            var isSelected = creator.Id == _liveSelectedCreatorId;
            var copy = new StackPanel { Spacing = 3, VerticalAlignment = VerticalAlignment.Center };
            copy.Children.Add(Txt(creator.Name, 13, true));
            copy.Children.Add(ThemeText(creator.Target, 10, false, "MutedTextBrush"));
            var detailsText = ThemeText(LiveCreatorDetails(creator), 10, false,
                creator.CaptureActive ? "SuccessBrush" : "MutedTextBrush");
            copy.Children.Add(detailsText);
            _liveCreatorDetailsById[creator.Id] = detailsText;

            var select = CreateButton(isSelected ? "Selected" : "Use creator", async () =>
            {
                try { await SelectLiveCreatorAsync(creator); }
                catch (Exception ex) { await ShowErrorAsync("Could not load creator settings", ex.Message); }
            }, primary: isSelected);
            select.IsEnabled = _engine is not null && _state?.Running != true && !isSelected;
            _liveCreatorSelectButtonsById[creator.Id] = select;

            var liveActionLabel = creator.CaptureStopping
                ? "Stopping..."
                : creator.CaptureActive ? "Stop capture"
                : creator.Running ? "Stop live" : "Start live";
            var liveAction = CreateButton(liveActionLabel, async () =>
            {
                try { await ToggleCreatorLiveAsync(creator); }
                catch (Exception ex) { await ShowErrorAsync("Could not change creator state", ex.Message); }
            }, primary: !creator.Running && !creator.CaptureActive, danger: creator.Running || creator.CaptureActive);
            liveAction.IsEnabled = _engine is not null && !creator.CaptureStopping &&
                !string.Equals(creator.Phase, "stopping", StringComparison.OrdinalIgnoreCase);
            _liveCreatorActionsById[creator.Id] = liveAction;

            // Keep identity and channel details on the first row. Action buttons share a
            // full-width second row so narrow Live Studio panels never crush the URL/status text.
            var row = new Grid
            {
                ColumnSpacing = 10,
                RowSpacing = 8,
                Padding = new Thickness(9, 10, 9, 10)
            };
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(40) });
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            row.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            row.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });

            var avatar = CreateCreatorAvatar(
                creator.Name, size: 32, active: creator.Running || creator.CaptureActive);
            Grid.SetRow(avatar, 0);
            Grid.SetColumn(avatar, 0);
            row.Children.Add(avatar);

            Grid.SetColumn(copy, 1);
            row.Children.Add(copy);

            var actions = new Grid { ColumnSpacing = 10 };
            actions.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            actions.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            select.HorizontalAlignment = HorizontalAlignment.Stretch;
            select.HorizontalContentAlignment = HorizontalAlignment.Center;
            liveAction.HorizontalAlignment = HorizontalAlignment.Stretch;
            liveAction.HorizontalContentAlignment = HorizontalAlignment.Center;
            Grid.SetColumn(select, 0);
            actions.Children.Add(select);
            Grid.SetColumn(liveAction, 1);
            actions.Children.Add(liveAction);
            Grid.SetRow(actions, 1);
            Grid.SetColumn(actions, 1);
            row.Children.Add(actions);
            list.Children.Add(new Border
            {
                BorderBrush = Application.Current.Resources["LineBrush"] as Brush,
                BorderThickness = new Thickness(0, 0, 0, 1),
                Background = isSelected
                    ? Application.Current.Resources["AccentSoftBrush"] as Brush
                    : new SolidColorBrush(Colors.Transparent),
                Child = row
            });
        }
        parent.Children.Add(list);

        if (_liveSelectedCreatorId is not null)
        {
            var selectedCreator = _creators.FirstOrDefault(item => item.Id == _liveSelectedCreatorId);
            if (selectedCreator is not null)
                parent.Children.Add(ThemeText(
                    $"Selected creator: {selectedCreator.Name}. This profile stores facecam/game framing, crop coordinates, subtitle styling, and profanity treatment. AI provider, caption provider, video layout, output format, and clipping settings are shared across creators.",
                    11, false, "BodyTextBrush"));
        }
    }

    private async Task ToggleCreatorLiveAsync(CreatorItem creator)
    {
        if (_engine is null)
            throw new InvalidOperationException("The local media engine is not connected.");

        if (creator.CaptureActive)
        {
            await PostAsync("/api/creators/stop-capture", new JsonObject
            {
                ["id"] = creator.Id,
                ["force"] = false
            });
        }
        else if (creator.Running)
        {
            await PostAsync("/api/creators/stop", new JsonObject
            {
                ["id"] = creator.Id,
                ["force"] = false
            });
        }
        else
        {
            if (_liveSelectedCreatorId == creator.Id)
                await SaveSelectedCreatorSettingsAsync(creator.Target);
            await PostAsync("/api/creators/start", new JsonObject { ["id"] = creator.Id });
        }

        await RefreshCreatorsAsync();
        if (_currentPage == "live")
            UpdateLiveCreatorRows();
        else if (_currentPage == "creators")
            RenderCurrentPage();
    }

    private async Task SelectLiveCreatorAsync(CreatorItem creator)
    {
        if (_engine is null)
            throw new InvalidOperationException("The local media engine is not connected.");
        if (_state?.Running == true)
            throw new InvalidOperationException("Stop the current capture before changing creators.");

        if (_liveSelectedCreatorId is not null && _liveSelectedCreatorId != creator.Id)
            await SaveSelectedCreatorSettingsAsync(_liveTargetInput?.Text.Trim() ?? "");

        var response = await _engine.GetJsonAsync(
            "/api/creators/settings?id=" + Uri.EscapeDataString(creator.Id), _shutdown.Token);
        var settings = response["settings"] as JsonObject;
        if (settings is null)
            throw new InvalidOperationException("The creator settings response was empty.");

        var values = settings.DeepClone() as JsonObject ?? new JsonObject();
        values["creator_id"] = creator.Id;
        values["mode"] = "live";
        values["target"] = creator.Target;
        ReplaceLiveSettings(values);
        _liveSelectedCreatorId = creator.Id;
        if (_liveModeInput is not null) _liveModeInput.SelectedIndex = 0;
        if (_liveTargetInput is not null)
        {
            _liveTargetInput.Text = creator.Target;
            _liveTargetInput.IsReadOnly = true;
        }
        _framingValuesInitialized = false;
        _framingBitmap = null;
        _framingResultSummary = null;
        RenderCurrentPage();
    }

    private async Task SaveSelectedCreatorSettingsAsync(string target)
    {
        if (_liveSelectedCreatorId is null || _settings is null)
            return;
        var creator = _creators.FirstOrDefault(item => item.Id == _liveSelectedCreatorId);
        if (creator is null)
            throw new InvalidOperationException("The selected creator no longer exists. Refresh the creator list.");
        if (!string.Equals(target, creator.Target, StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("The source URL does not match the selected creator.");

        var values = _settings.Values.DeepClone() as JsonObject ?? new JsonObject();
        values["creator_id"] = creator.Id;
        values["mode"] = "live";
        values["target"] = creator.Target;
        await SaveCreatorSettingsAsync(creator.Id, values);
    }

    private async Task SaveGlobalCaptureSettingsAsync(string mode, string target)
    {
        if (_settings is null)
            throw new InvalidOperationException("Settings have not loaded yet.");
        var values = _settings.Values.DeepClone() as JsonObject ?? new JsonObject();
        values.Remove("creator_id");
        values["mode"] = mode;
        values["target"] = target;
        await PostAsync("/api/settings", values);
        _globalSettings = values.DeepClone() as JsonObject ?? new JsonObject();
    }

    private void RestoreGlobalCaptureSettings()
    {
        if (_settings is null || _globalSettings is null)
            return;
        var values = _globalSettings.DeepClone() as JsonObject ?? new JsonObject();
        values.Remove("creator_id");
        ReplaceLiveSettings(values);
    }

    private void ReplaceLiveSettings(JsonObject values)
    {
        if (_settings is null)
            throw new InvalidOperationException("Settings have not loaded yet.");
        _settings.Values.Clear();
        foreach (var item in values)
            _settings.Values[item.Key] = item.Value?.DeepClone();
    }

    private void AddSettingNumber(Grid grid, int column, int row, string label, string key, double minimum, double maximum)
    {
        var box = Input(SettingNumber(key, DefaultSettingNumber(key)).ToString(CultureInfo.InvariantCulture));
        box.TextChanged += (_, _) =>
        {
            if (double.TryParse(box.Text, NumberStyles.Any, CultureInfo.InvariantCulture, out var value))
                SetSetting(key, Math.Clamp(value, minimum, maximum));
        };
        var field = new StackPanel { Spacing = 5 };
        field.Children.Add(Txt(label, 10, true));
        field.Children.Add(box);
        Grid.SetColumn(field, column);
        Grid.SetRow(field, row);
        grid.Children.Add(field);
    }

    private static double DefaultSettingNumber(string key) => key switch
    {
        "chunk_min" => 10,
        "pre" => 20,
        "post" => 15,
        "min_score" => 70,
        "capture_bitrate_kbps" => 8000,
        "clips_per_chunk" => 2,
        _ => 0
    };

    private UIElement BuildAiSettingsTab()
    {
        var panel = new StackPanel { Spacing = 12, Padding = new Thickness(4, 12, 4, 4) };
        var ai = _settings?.Ai ?? new JsonObject();

        var provider = new ComboBox
        {
            MinWidth = 280,
            HorizontalAlignment = HorizontalAlignment.Stretch
        };
        var providers = new (string Id, string Label)[]
        {
            ("gemini", "Google Gemini"),
            ("ollama", "Ollama · local / free"),
            ("openai", "OpenAI / ChatGPT API"),
            ("anthropic", "Anthropic / Claude API"),
            ("custom", "Custom OpenAI-compatible API")
        };
        foreach (var option in providers)
        {
            provider.Items.Add(new ComboBoxItem { Content = option.Label, Tag = option.Id });
        }
        var savedProvider = ai["provider"]?.ToString() ?? "gemini";
        provider.SelectedItem = provider.Items
            .OfType<ComboBoxItem>()
            .FirstOrDefault(item => string.Equals(item.Tag?.ToString(), savedProvider, StringComparison.OrdinalIgnoreCase))
            ?? provider.Items.OfType<ComboBoxItem>().First();

        AddLabeled(panel, "AI provider", provider);

        var providerLabel = ThemeText(
            "The selected model analyzes transcript windows for viral moments, then generates the title, description, and topical tags.",
            10, false, "MutedTextBrush");
        panel.Children.Add(providerLabel);

        var ollamaUrl = Input(ai["ollama_url"]?.ToString() ?? "http://127.0.0.1:11434");
        var ollamaModel = Input(ai["ollama_model"]?.ToString() ?? "", "Installed Ollama model name");

        var geminiModel = Input(ai["gemini_model"]?.ToString() ?? "gemini-3.1-flash-lite",
            "Gemini model ID");
        var geminiKey = new PasswordBox
        {
            PlaceholderText = ai["gemini_key_set"]?.GetValue<bool>() == true
                ? "A key is saved · enter a new key to replace"
                : "Google AI Studio API key"
        };

        var openAiBase = Input(ai["openai_api_base"]?.ToString() ?? "https://api.openai.com/v1");
        var openAiModel = Input(ai["openai_model"]?.ToString() ?? "", "OpenAI model ID");
        var openAiKey = new PasswordBox
        {
            PlaceholderText = ai["openai_key_set"]?.GetValue<bool>() == true
                ? "A key is saved · enter a new key to replace"
                : "OpenAI API key"
        };

        var anthropicBase = Input(ai["anthropic_api_base"]?.ToString() ?? "https://api.anthropic.com");
        var anthropicModel = Input(ai["anthropic_model"]?.ToString() ?? "", "Claude model ID");
        var anthropicKey = new PasswordBox
        {
            PlaceholderText = ai["anthropic_key_set"]?.GetValue<bool>() == true
                ? "A key is saved · enter a new key to replace"
                : "Anthropic API key"
        };

        var customBase = Input(ai["custom_api_base"]?.ToString() ?? "https://api.openai.com/v1");
        var customModel = Input(ai["custom_api_model"]?.ToString() ?? "", "OpenAI-compatible model ID");
        var customKey = new PasswordBox
        {
            PlaceholderText = ai["custom_api_key_set"]?.GetValue<bool>() == true
                ? "A key is saved · enter a new key to replace"
                : "API key (leave blank for local endpoints)"
        };

        var ollamaFields = new StackPanel { Spacing = 10 };
        AddLabeled(ollamaFields, "Ollama server URL", ollamaUrl,
            "Local default: http://127.0.0.1:11434");
        AddLabeled(ollamaFields, "Ollama model", ollamaModel,
            "Use a model already installed in Ollama. Transcript processing stays on this PC.");

        var geminiFields = new StackPanel { Spacing = 10 };
        AddLabeled(geminiFields, "Gemini model", geminiModel);
        AddLabeled(geminiFields, "Google AI Studio key", geminiKey);

        var openAiFields = new StackPanel { Spacing = 10 };
        AddLabeled(openAiFields, "OpenAI API base", openAiBase);
        AddLabeled(openAiFields, "ChatGPT model", openAiModel);
        AddLabeled(openAiFields, "OpenAI API key", openAiKey);

        var anthropicFields = new StackPanel { Spacing = 10 };
        AddLabeled(anthropicFields, "Anthropic API base", anthropicBase);
        AddLabeled(anthropicFields, "Claude model", anthropicModel);
        AddLabeled(anthropicFields, "Anthropic API key", anthropicKey);

        var customFields = new StackPanel { Spacing = 10 };
        AddLabeled(customFields, "Compatible API base URL", customBase);
        AddLabeled(customFields, "Model", customModel);
        AddLabeled(customFields, "API key", customKey,
            "For local OpenAI-compatible servers, the key can be left blank.");

        panel.Children.Add(ollamaFields);
        panel.Children.Add(geminiFields);
        panel.Children.Add(openAiFields);
        panel.Children.Add(anthropicFields);
        panel.Children.Add(customFields);

        string SelectedProvider() =>
            (provider.SelectedItem as ComboBoxItem)?.Tag?.ToString() ?? "gemini";

        void UpdateProviderFields()
        {
            var selected = SelectedProvider();
            providerLabel.Text = selected switch
            {
                "gemini" => "Google Gemini analyzes transcript windows and writes the title, description, and tags. API usage consumes your Google quota.",
                "ollama" => "Ollama runs locally on this PC. The selected local model chooses viral moments and writes all clip metadata without a hosted API key.",
                "openai" => "OpenAI / ChatGPT API analyzes the transcript, selects viral moments, and generates post metadata.",
                "anthropic" => "Claude through the Anthropic Messages API analyzes the transcript, selects viral moments, and generates post metadata.",
                "custom" => "Advanced option for any OpenAI-compatible chat-completions endpoint, including local servers.",
                _ => "Choose the model that will select moments and create post metadata."
            };

            ollamaFields.Visibility = selected == "ollama" ? Visibility.Visible : Visibility.Collapsed;
            geminiFields.Visibility = selected == "gemini" ? Visibility.Visible : Visibility.Collapsed;
            openAiFields.Visibility = selected == "openai" ? Visibility.Visible : Visibility.Collapsed;
            anthropicFields.Visibility = selected == "anthropic" ? Visibility.Visible : Visibility.Collapsed;
            customFields.Visibility = selected == "custom" ? Visibility.Visible : Visibility.Collapsed;
        }

        provider.SelectionChanged += (_, _) => UpdateProviderFields();
        UpdateProviderFields();

        panel.Children.Add(ThemeText(
            "One provider handles the complete AI decision: transcript analysis, viral-moment selection, clip title, description, and topical hashtags. Hosted providers receive transcript text; Ollama keeps it local.",
            10, false, "MutedTextBrush"));

        var messages = ThemeText("", 10, false, "MutedTextBrush");
        panel.Children.Add(messages);

        JsonObject BuildPayload()
        {
            var body = new JsonObject
            {
                ["provider"] = SelectedProvider(),
                ["ollama_url"] = ollamaUrl.Text.Trim(),
                ["ollama_model"] = ollamaModel.Text.Trim(),
                ["gemini_model"] = geminiModel.Text.Trim(),
                ["openai_api_base"] = openAiBase.Text.Trim(),
                ["openai_model"] = openAiModel.Text.Trim(),
                ["anthropic_api_base"] = anthropicBase.Text.Trim(),
                ["anthropic_model"] = anthropicModel.Text.Trim(),
                ["custom_api_base"] = customBase.Text.Trim(),
                ["custom_api_model"] = customModel.Text.Trim()
            };
            if (!string.IsNullOrWhiteSpace(geminiKey.Password))
                body["gemini_api_key"] = geminiKey.Password.Trim();
            if (!string.IsNullOrWhiteSpace(openAiKey.Password))
                body["openai_api_key"] = openAiKey.Password.Trim();
            if (!string.IsNullOrWhiteSpace(anthropicKey.Password))
                body["anthropic_api_key"] = anthropicKey.Password.Trim();
            if (!string.IsNullOrWhiteSpace(customKey.Password))
                body["custom_api_key"] = customKey.Password.Trim();
            return body;
        }

        var test = CreateButton("Test provider", async () =>
        {
            try
            {
                messages.Text = "Testing provider connection…";
                var response = await PostAsync("/api/ai/test", BuildPayload());
                messages.Text = response["message"]?.ToString() ?? "Provider test completed.";
            }
            catch (Exception ex)
            {
                messages.Text = ex.Message;
            }
        });

        var save = CreateButton("Save AI settings", async () =>
        {
            try
            {
                await PostAsync("/api/ai/settings", BuildPayload());
                geminiKey.Password = "";
                openAiKey.Password = "";
                anthropicKey.Password = "";
                customKey.Password = "";
                _settings = EngineSettings.FromResponse(await GetAsync("/api/config"));
                messages.Text = "AI provider saved. This model will select moments and create clip metadata.";
            }
            catch (Exception ex)
            {
                await ShowErrorAsync("Could not save AI settings", ex.Message);
            }
        }, primary: true);

        panel.Children.Add(ActionRow(test, save));
        return panel;
    }
    private UIElement BuildCaptionProviderSettingsPanel()
    {
        var speech = new StackPanel { Spacing = 12, Padding = new Thickness(4, 12, 4, 4) };
        speech.Children.Add(ThemeText(
            "Facecam/game framing, crop coordinates, visual subtitle treatment, and profanity filtering are saved per creator. AI and caption providers plus clipping defaults are global in AI & Providers and Capture.",
            11, false, "MutedTextBrush"));
        var speechProvider = new ComboBox { MinWidth = 230, HorizontalAlignment = HorizontalAlignment.Stretch };
        speechProvider.ItemsSource = new[] { "Faster-Whisper", "Custom command" };
        speechProvider.SelectedIndex = SettingString("transcriber_provider", "faster-whisper") == "custom-command" ? 1 : 0;
        AddLabeled(speech, "Caption / transcription provider", speechProvider,
            "This processing provider is global, not saved independently per creator.");

        var speechModelFields = new StackPanel { Spacing = 10 };
        var commandFields = new StackPanel { Spacing = 10 };
        var model = new ComboBox { MinWidth = 230, HorizontalAlignment = HorizontalAlignment.Stretch };
        var modelNames = _settings?.TranscriberModels?.Length > 0
            ? _settings.TranscriberModels : ["distil-large-v3", "large-v3-turbo", "medium", "large-v3", "small", "base"];
        model.ItemsSource = modelNames;
        model.SelectedItem = SettingString("model", "distil-large-v3");
        model.SelectionChanged += (_, _) => SetSetting("model", model.SelectedItem?.ToString() ?? "distil-large-v3");
        AddLabeled(speechModelFields, "Faster-Whisper model", model,
            "Uses a supported GPU first. CPU processing is used only when a supported GPU is unavailable.");
        var language = Input(SettingString("transcriber_language", "auto"), "auto");
        AddLabeled(speechModelFields, "Transcription language", language,
            "Global default across creators. Use auto to detect the spoken language.");
        language.TextChanged += (_, _) => SetSetting("transcriber_language", language.Text.Trim());

        var command = Input(SettingString("transcriber_command"), "Command with {input}, {output}, and {language} placeholders", multiline: true);
        AddLabeled(commandFields, "Custom caption/transcription command", command,
            "Runs locally. The command must write the transcript to the requested output path.");
        command.TextChanged += (_, _) => SetSetting("transcriber_command", command.Text);

        speech.Children.Add(speechModelFields);
        speech.Children.Add(commandFields);
        void UpdateSpeechProviderFields()
        {
            var custom = speechProvider.SelectedIndex == 1;
            speechModelFields.Visibility = custom ? Visibility.Collapsed : Visibility.Visible;
            commandFields.Visibility = custom ? Visibility.Visible : Visibility.Collapsed;
            SetSetting("transcriber_provider", custom ? "custom-command" : "faster-whisper");
        }
        speechProvider.SelectionChanged += (_, _) => UpdateSpeechProviderFields();
        UpdateSpeechProviderFields();

        var saveStatus = ThemeText("Provider changes are not applied until saved. These settings are global across all creators.",
            10, false, "MutedTextBrush");
        speech.Children.Add(saveStatus);
        speech.Children.Add(CreateButton("Save caption provider", async () =>
        {
            try
            {
                if (_settings is null)
                    throw new InvalidOperationException("Settings have not loaded yet.");
                var values = _globalSettings?.DeepClone() as JsonObject
                    ?? _settings.Values.DeepClone() as JsonObject ?? new JsonObject();
                foreach (var key in new[] { "transcriber_provider", "transcriber_command", "transcriber_language", "model" })
                {
                    if (_settings.Values.TryGetPropertyValue(key, out var value))
                        values[key] = value?.DeepClone();
                }
                values.Remove("creator_id");
                await PostAsync("/api/settings", values);
                _settings = EngineSettings.FromResponse(await GetAsync("/api/config"));
                _globalSettings = _settings.Values.DeepClone() as JsonObject ?? new JsonObject();
                saveStatus.Text = "Caption provider saved as a shared default for every creator.";
            }
            catch (Exception ex)
            {
                saveStatus.Text = "Could not save caption provider: " + ex.Message;
            }
        }, primary: true));
        return speech;
    }

    private async Task<StorageFile?> PickVideoFileAsync()
    {
        var picker = new FileOpenPicker();
        picker.SuggestedStartLocation = PickerLocationId.VideosLibrary;
        foreach (var extension in new[] { ".mp4", ".mkv", ".mov", ".webm", ".avi", ".ts" })
            picker.FileTypeFilter.Add(extension);
        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowInstance!);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);
        return await picker.PickSingleFileAsync();
    }

    private void UpdateLiveState()
    {
        if (_state is null) return;
        if (_liveStatusText is not null) _liveStatusText.Text = _state.Status;
        if (_liveProgress is not null) _liveProgress.Value = Math.Clamp(_state.Progress, 0, 100);
        if (_liveProgressText is not null)
            _liveProgressText.Text = $"{PhaseLabel(_state.Phase)} · {_state.Progress}% · {_state.Session.Clips:N0} clips";
        if (_startCaptureButton is not null) _startCaptureButton.IsEnabled = _engine is not null && !_state.Running;
        if (_stopCaptureButton is not null) _stopCaptureButton.IsEnabled = _state.Running;
    }
}
