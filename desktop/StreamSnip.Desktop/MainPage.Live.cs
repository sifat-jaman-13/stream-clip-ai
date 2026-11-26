using System.Globalization;
using System.Text.Json.Nodes;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Imaging;
using Windows.Storage;
using Windows.Storage.Pickers;
using Windows.Storage.Streams;

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

    private void RenderLiveStudioPage()
    {
        _liveStatusText = null;
        _liveProgressText = null;
        _liveProgress = null;
        _liveTargetInput = null;
        _liveModeInput = null;

        AddPageHeading("Live Studio", "Choose a source, configure capture and clipping, then start processing when you are ready.");

        var sourcePanel = new StackPanel { Spacing = 12 };
        _liveModeInput = new ComboBox { MinWidth = 180, HorizontalAlignment = HorizontalAlignment.Stretch };
        _liveModeInput.ItemsSource = new[] { "Live stream", "Video file / VOD" };
        _liveModeInput.SelectedIndex = SettingString("mode", "live") == "file" ? 1 : 0;
        _liveModeInput.SelectionChanged += (_, _) =>
        {
            SetSetting("mode", _liveModeInput.SelectedIndex == 1 ? "file" : "live");
            if (_liveTargetInput is not null)
                _liveTargetInput.PlaceholderText = _liveModeInput.SelectedIndex == 1
                    ? "Choose a local video file…" : "Paste a Twitch or YouTube URL";
        };
        AddLabeled(sourcePanel, "Source type", _liveModeInput);

        _liveTargetInput = Input(
            SettingString("target"),
            SettingString("mode", "live") == "file"
                ? "Choose a local video file…" : "Paste a Twitch or YouTube URL");
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
        _sourcePreviewPlaceholder.Children.Add(new FontIcon
        {
            Glyph = new string((char)0xE714, 1),
                FontFamily = new FontFamily("Segoe MDL2 Assets"),
                FontSize = 22,
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
        AddSettingNumber(captureGrid, 0, 0, "Capture chunk length (minutes)", "chunk_min", 3, 60);
        AddSettingNumber(captureGrid, 1, 0, "Seconds before highlight", "pre", 3, 90);
        AddSettingNumber(captureGrid, 0, 1, "Seconds after highlight", "post", 3, 90);
        AddSettingNumber(captureGrid, 1, 1, "Minimum highlight score", "min_score", 0, 100);
        AddSettingNumber(captureGrid, 0, 2, "Capture bitrate (Kbps)", "capture_bitrate_kbps", 8000, 50000);
        AddSettingNumber(captureGrid, 1, 2, "Maximum clips per chunk", "max_clips", 1, 50);
        capture.Children.Add(captureGrid);
        capture.Children.Add(ThemeText("Settings are applied to the next capture. Existing work is not changed.", 10, false, "MutedTextBrush"));
        tabs.TabItems.Add(new TabViewItem { Header = Txt("Capture", 16, true), Content = capture, IsClosable = false });

        var ai = BuildAiSettingsTab();
        tabs.TabItems.Add(new TabViewItem { Header = Txt("AI provider", 16, true), Content = ai, IsClosable = false });

        var speech = new StackPanel { Spacing = 12, Padding = new Thickness(4, 12, 4, 4) };
        var model = new ComboBox { MinWidth = 230, HorizontalAlignment = HorizontalAlignment.Stretch };
        var modelNames = _settings?.TranscriberModels?.Length > 0
            ? _settings.TranscriberModels : ["distil-large-v3", "large-v3-turbo", "medium", "large-v3", "small", "base"];
        model.ItemsSource = modelNames;
        model.SelectedItem = SettingString("model", "distil-large-v3");
        model.SelectionChanged += (_, _) => SetSetting("model", model.SelectedItem?.ToString() ?? "distil-large-v3");
        AddLabeled(speech, "Faster-Whisper model", model,
            "Speech recognition runs locally and can use compatible NVIDIA GPU acceleration.");
        var language = Input(SettingString("language", "auto"), "auto");
        AddLabeled(speech, "Transcription language", language, "Use auto to detect the spoken language.");
        language.TextChanged += (_, _) => SetSetting("language", language.Text.Trim());
        var threads = new ComboBox { MinWidth = 180 };
        threads.ItemsSource = new[] { "1", "2", "4", "6", "8", "12", "16" };
        threads.SelectedItem = SettingString("cpu_threads", "4");
        threads.SelectionChanged += (_, _) => SetSetting("cpu_threads", threads.SelectedItem?.ToString() ?? "4");
        AddLabeled(speech, "CPU threads", threads, "Used when transcription runs on the CPU.");
        tabs.TabItems.Add(new TabViewItem { Header = Txt("Transcription", 16, true), Content = speech, IsClosable = false });

        var captions = new StackPanel { Spacing = 12, Padding = new Thickness(4, 12, 4, 4) };
        var layout = new ComboBox { MinWidth = 260, HorizontalAlignment = HorizontalAlignment.Stretch };
        var layouts = _settings?.Layouts?.Length > 0
            ? _settings.Layouts
            : ["Facecam + game (Twitch)", "Full video", "Selected crop"];
        layout.ItemsSource = layouts;
        layout.SelectedItem = SettingString("layout", layouts[0]);
        layout.SelectionChanged += (_, _) => SetSetting("layout", layout.SelectedItem?.ToString() ?? layouts[0]);
        AddLabeled(captions, "Video layout", layout);
        var format = new ComboBox { MinWidth = 170 };
        format.ItemsSource = new[] { "9:16", "16:9", "1:1", "4:5" };
        format.SelectedItem = SettingString("output_format", "9:16");
        format.SelectionChanged += (_, _) => SetSetting("output_format", format.SelectedItem?.ToString() ?? "9:16");
        AddLabeled(captions, "Output format", format);
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
        tabs.TabItems.Add(new TabViewItem { Header = Txt("Captions", 16, true), Content = captions, IsClosable = false });

        var setupPanel = CreatePanel("Capture setup",
            "Capture, AI provider, transcription, and captions stay together before you start.",
            tabs);

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
                if (string.IsNullOrWhiteSpace(SettingString("target")))
                    throw new InvalidOperationException("Choose a Twitch/YouTube URL or a local video file first.");

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
                    if (_liveTabs is not null) _liveTabs.SelectedIndex = 1;
                    var message = aiProvider switch
                    {
                        "gemini" => "Save a Google AI Studio API key in the AI provider tab before starting capture.",
                        "openai" => "Save an OpenAI API key and model in the AI provider tab before starting capture.",
                        "anthropic" => "Save an Anthropic API key and Claude model in the AI provider tab before starting capture.",
                        "custom" => "Enter and save the model name for your custom OpenAI-compatible endpoint.",
                        _ => "Choose a supported AI provider in the AI provider tab."
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

        var captureActions = _engine is null
            ? ActionRow(CreateButton("Repair runtime", () =>
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
                    FileName = System.IO.Path.Combine(
                        Environment.GetFolderPath(Environment.SpecialFolder.System),
                        "WindowsPowerShell", "v1.0", "powershell.exe"),
                    UseShellExecute = true,
                    Arguments = "-NoExit -NoProfile -ExecutionPolicy Bypass -File " +
                        "\"" + setupScript + "\"" + " -AppDir " +
                        "\"" + appRoot + "\"" +
                        " -NativeDesktop -NonInteractive -SkipLaunch -NoPause"
                };
                System.Diagnostics.Process.Start(start);
            }))
            : ActionRow(_startCaptureButton, _stopCaptureButton);
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
        "max_clips" => 5,
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
