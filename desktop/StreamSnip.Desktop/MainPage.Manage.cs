using System.IO;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Windows.Storage;
using Windows.Storage.Pickers;

namespace StreamSnip_Desktop;

public sealed partial class MainPage
{
    private TextBox? _wordsText;
    private TextBlock? _wordsStatus;
    private TextBlock? _wordsCount;
    private TextBlock? _builtinVocabularyCounts;
    private Grid? _builtinVocabularyGrid;
    private string _activityFilter = "";
    private bool _activityProblemsOnly;
    private TextBox? _activitySearchBox;
    private Button? _activityAllButton;
    private Button? _activityProblemsButton;
    private TextBlock? _activityVisibleCount;
    private StackPanel? _activityRowsHost;
    private TextBlock? _publishingStatusText;
    private readonly Dictionary<string, CheckBox> _accountChecks = new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<string, PasswordBox> _zernioKeys = new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<string, StackPanel> _zernioAccountPanels = new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<string, TextBlock> _zernioSlotStatuses = new(StringComparer.OrdinalIgnoreCase);
    private readonly List<string> _publishingSlotIds = [];
    private readonly Dictionary<string, string> _publishingSlotLabels = new(StringComparer.OrdinalIgnoreCase);
    private JsonObject _publishingStatus = new();
    private bool _publishingOptionsDirty;
    private bool _publishingAccountsDirty;
    private bool _applyingPublishingStatus;
    private CheckBox? _publishingAutoPost;
    private ComboBox? _publishingSchedule;
    private ComboBox? _publishingVisibility;
    private StackPanel? _bulkPublishingPanel;

    private void RenderProvidersPage()
    {
        AddPageHeading("AI & Providers", "Configure the global AI highlight provider and caption/transcription provider. These choices apply to every creator and local video.");
        PageHost.Children.Add(CreatePanel(
            "AI provider",
            "Select the global model that analyses transcripts, chooses highlights, and creates clip metadata.",
            BuildAiSettingsTab()));
        PageHost.Children.Add(CreatePanel(
            "Caption provider",
            "Choose the global speech-to-text provider. Each creator keeps its own visual subtitle style separately.",
            BuildCaptionProviderSettingsPanel()));
    }

    private void RenderSettingsPage()
    {
        AddPageHeading("Settings", "Choose where recordings and finished clips are stored, then tune the appearance of your workspace.");

        var storage = new StackPanel { Spacing = 10 };
        var recordings = Input(SettingString("rec_dir"));
        var clips = Input(SettingString("out_dir"));
        var recordingsBrowse = CreateButton("Browse", async () =>
        {
            var path = await PickFolderAsync();
            if (!string.IsNullOrWhiteSpace(path)) recordings.Text = path;
        });
        var clipsBrowse = CreateButton("Browse", async () =>
        {
            var path = await PickFolderAsync();
            if (!string.IsNullOrWhiteSpace(path)) clips.Text = path;
        });
        AddLabeled(storage, "Recordings folder", recordings);
        storage.Children.Add(recordingsBrowse);
        AddLabeled(storage, "Rendered clips folder", clips);
        storage.Children.Add(clipsBrowse);
        var saveStorage = CreateButton("Save storage settings", async () =>
        {
            try
            {
                SetSetting("rec_dir", recordings.Text.Trim());
                SetSetting("out_dir", clips.Text.Trim());
                await SaveCaptureSettingsAsync();
                await DialogResultAsync("Settings saved", "The storage folders have been saved.");
            }
            catch (Exception ex) { await ShowErrorAsync("Could not save storage settings", ex.Message); }
        }, primary: true);
        storage.Children.Add(saveStorage);
        PageHost.Children.Add(CreatePanel("Storage locations", "Choose where source recordings and completed clips are stored.", storage));

        var appearance = new StackPanel { Spacing = 12 };
        appearance.Children.Add(Txt("Theme", 11, true));
        var themeGrid = new Grid { ColumnSpacing = 9, RowSpacing = 9 };
        for (var i = 0; i < (int)Math.Ceiling(Themes.Length / 3.0); i++)
            themeGrid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        for (var i = 0; i < 3; i++)
            themeGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        for (var i = 0; i < Themes.Length; i++)
        {
            var palette = Themes[i];
            var preview = new Grid { Height = 38, ColumnSpacing = 3, Margin = new Thickness(0, 0, 0, 5) };
            foreach (var color in new[] { palette.App, palette.Surface, palette.Accent })
            {
                preview.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
                var swatch = new Border { Background = new SolidColorBrush(ParseColor(color)), CornerRadius = new CornerRadius(4) };
                Grid.SetColumn(swatch, preview.ColumnDefinitions.Count - 1);
                preview.Children.Add(swatch);
            }
            var contents = new StackPanel { Spacing = 4 };
            contents.Children.Add(preview);
            contents.Children.Add(Txt(palette.Name, 10, true));
            var selected = _theme == palette.Id;
            var card = new Button
            {
                Content = contents,
                HorizontalContentAlignment = HorizontalAlignment.Stretch,
                Background = Application.Current.Resources[selected ? "AccentSoftBrush" : "SurfaceBrush"] as Brush,
                BorderBrush = Application.Current.Resources[selected ? "AccentBrush" : "LineBrush"] as Brush,
                BorderThickness = new Thickness(selected ? 2 : 1),
                CornerRadius = new CornerRadius(9),
                Padding = new Thickness(9)
            };
            card.Click += (_, _) =>
            {
                ApplyTheme(palette.Id);
                RenderCurrentPage();
            };
            Grid.SetRow(card, i / 3);
            Grid.SetColumn(card, i % 3);
            themeGrid.Children.Add(card);
        }
        appearance.Children.Add(themeGrid);

        var selectedPalette = Themes.FirstOrDefault(item => item.Id == _theme) ?? Themes[0];
        var accentInput = Input(IsValidAccent(_customAccent) ? _customAccent : selectedPalette.Accent, "#RRGGBB");
        AddLabeled(appearance, "Custom accent color", accentInput,
            "Enter a six-digit hex color. Primary actions and selected controls update; success and error colors stay distinct.");
        appearance.Children.Add(ActionRow(
            CreateButton("Apply accent", () =>
            {
                var value = accentInput.Text.Trim();
                if (!value.StartsWith("#", StringComparison.Ordinal)) value = "#" + value;
                if (!IsValidAccent(value))
                {
                    _ = ShowErrorAsync("Invalid accent color", "Enter a six-digit hex value, such as #42B9CC.");
                    return;
                }
                _customAccent = value;
                ApplyTheme(_theme);
                RenderCurrentPage();
            }, primary: true),
            CreateButton("Reset to theme", () =>
            {
                _customAccent = "";
                ApplyTheme(_theme);
                RenderCurrentPage();
            })));

        var fontChoice = new ComboBox { MinWidth = 260, HorizontalAlignment = HorizontalAlignment.Stretch };
        fontChoice.ItemsSource = FontChoices;
        fontChoice.SelectedItem = _fontName;
        fontChoice.SelectionChanged += (_, _) =>
        {
            if (fontChoice.SelectedItem is string selected)
            {
                ApplyFont(selected);
                RenderCurrentPage();
            }
        };
        AddLabeled(appearance, "Application font", fontChoice,
            "JetBrains Mono is the default UI font. Also choose Manrope, DM Sans, Inter, Open Sans, IBM Plex Sans, Nunito Sans, Roboto, Source Sans 3, Poppins, Lato, Fira Code, Segoe UI, Consolas, Aptos, Arial, Tahoma, Verdana, Georgia, Trebuchet MS, or Times New Roman. All app panels and controls use the selected family; video captions have separate creator-specific font and style settings.");

        var fontSizeChoice = new ComboBox { MinWidth = 260, HorizontalAlignment = HorizontalAlignment.Stretch };
        fontSizeChoice.ItemsSource = new[] { "Small", "Medium", "Large" };
        fontSizeChoice.SelectedItem = _fontSize switch { "small" => "Small", "large" => "Large", _ => "Medium" };
        fontSizeChoice.SelectionChanged += (_, _) =>
        {
            if (fontSizeChoice.SelectedItem is string selected)
            {
                ApplyFontSize(selected.ToLowerInvariant());
                RenderCurrentPage();
            }
        };
        AddLabeled(appearance, "Application text size", fontSizeChoice,
            "Small: 13 DIP | Medium: 14 DIP (default) | Large: 16 DIP. Applies across the desktop UI; headings scale proportionally and video captions are unaffected.");
        PageHost.Children.Add(CreatePanel("Workspace appearance", "Choose a palette, font, and text size saved on this device.", appearance));

        var maintenance = new StackPanel { Spacing = 10 };
        var updateResult = Txt("Check the installed app version against GitHub Releases. Updates are downloaded and verified before installation.", 10, false, "#9CDEF2");
        maintenance.Children.Add(updateResult);

        Button? checkUpdateButton = null;
        Button? installUpdateButton = null;
        checkUpdateButton = CreateButton("Check app update", async () =>
        {
            checkUpdateButton!.IsEnabled = false;
            if (installUpdateButton is not null) installUpdateButton.IsEnabled = false;
            updateResult.Text = "Checking the latest StreamSnip AI release…";
            try
            {
                var result = await PostAsync("/api/check_app_update", new JsonObject());
                var current = result["current"]?.ToString() ?? "unknown";
                var latest = result["latest"]?.ToString() ?? current;
                var available = bool.TryParse(result["update"]?.ToString(), out var hasUpdate) && hasUpdate;
                var canInstall = bool.TryParse(result["can_install"]?.ToString(), out var verifiedInstaller) && verifiedInstaller;
                if (!available)
                    updateResult.Text = $"You're up to date (v{current}).";
                else if (canInstall)
                {
                    updateResult.Text = $"Update available: v{latest} (installed v{current}). Select Install update to download and install it.";
                    if (installUpdateButton is not null) installUpdateButton.IsEnabled = true;
                }
                else
                    updateResult.Text = $"Update v{latest} is available, but GitHub did not provide a verified Windows installer. Open the release page to update manually.";
            }
            catch (Exception ex)
            {
                updateResult.Text = $"Could not check for updates: {ex.Message}";
            }
            finally
            {
                checkUpdateButton!.IsEnabled = true;
            }
        });

        installUpdateButton = CreateButton("Install update", async () =>
        {
            installUpdateButton!.IsEnabled = false;
            checkUpdateButton!.IsEnabled = false;
            updateResult.Text = "Downloading and verifying the Windows installer…";
            try
            {
                var result = await PostAsync("/api/install_app_update", new JsonObject
                {
                    ["parent_pid"] = Environment.ProcessId
                });
                if (!(bool.TryParse(result["ok"]?.ToString(), out var ok) && ok))
                    throw new InvalidOperationException(result["message"]?.ToString() ?? "The installer could not be prepared.");
                updateResult.Text = result["message"]?.ToString() ?? "Update verified. StreamSnip AI will close to finish installing.";
                await Task.Delay(800);
                await ShutdownApplicationAsync();
            }
            catch (Exception ex)
            {
                updateResult.Text = $"Could not install the update: {ex.Message}";
                installUpdateButton!.IsEnabled = true;
                checkUpdateButton!.IsEnabled = true;
            }
        });
        installUpdateButton.IsEnabled = false;

        Button? checkComponentsButton = null;
        checkComponentsButton = CreateButton("Check components", async () =>
        {
            checkComponentsButton!.IsEnabled = false;
            updateResult.Text = "Checking installed components…";
            try
            {
                var result = await PostAsync("/api/check_updates", new JsonObject());
                updateResult.Text = result.ToJsonString(new System.Text.Json.JsonSerializerOptions { WriteIndented = true });
            }
            catch (Exception ex) { updateResult.Text = ex.Message; }
            finally { checkComponentsButton!.IsEnabled = true; }
        });
        maintenance.Children.Add(ActionRow(checkUpdateButton, installUpdateButton));
        maintenance.Children.Add(checkComponentsButton);        PageHost.Children.Add(CreatePanel("Maintenance", "Review installed component versions and release availability.", maintenance));
        ApplyFontToVisualTree(this);
    }

    private async Task<string?> PickFolderAsync()
    {
        var picker = new FolderPicker();
        picker.SuggestedStartLocation = PickerLocationId.ComputerFolder;
        picker.FileTypeFilter.Add("*");
        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowInstance!);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);
        var folder = await picker.PickSingleFolderAsync();
        return folder?.Path;
    }

    private async void RenderPublishingPage()
    {
        AddPageHeading("Publisher", "Connect up to five Zernio API keys and choose the social accounts that can receive your clips.");

        _publishingStatus = new JsonObject();
        try
        {
            _publishingStatus = await GetAsync("/api/publishing/status");
        }
        catch (Exception ex)
        {
            _publishingStatusText = Txt(ex.Message, 10, false, "#F08A83");
        }

        var zernio = GetZernioPublishingStatus();
        var savedConnections = (zernio["connections"] as JsonArray ?? new JsonArray())
            .Select(item => item as JsonObject)
            .Where(item => item is not null)
            .Cast<JsonObject>()
            .Take(5)
            .ToList();

        _accountChecks.Clear();
        _zernioKeys.Clear();
        _zernioAccountPanels.Clear();
        _zernioSlotStatuses.Clear();
        _publishingSlotIds.Clear();
        _publishingSlotLabels.Clear();
        _publishingAccountsDirty = false;
        _publishingOptionsDirty = false;

        var page = new StackPanel { Spacing = 14 };
        var defaults = new StackPanel { Spacing = 10 };
        var autoPost = new CheckBox
        {
            Content = "Automatically queue rendered clips",
            IsChecked = zernio["auto_post"]?.GetValue<bool>() ?? false,
            FontFamily = CurrentFont
        };
        _publishingAutoPost = autoPost;
        var schedule = new ComboBox { MinWidth = 180 };
        schedule.ItemsSource = new[] { "0", "5", "10", "15", "30", "60", "120", "240", "1440" };
        schedule.SelectedItem = zernio["schedule_minutes"]?.ToString() ?? "0";
        _publishingSchedule = schedule;
        var visibility = new ComboBox { MinWidth = 180 };
        visibility.ItemsSource = new[] { "public", "unlisted", "private" };
        visibility.SelectedItem = zernio["visibility"]?.ToString() ?? "public";
        _publishingVisibility = visibility;

        autoPost.Checked += (_, _) => { if (!_applyingPublishingStatus) _publishingOptionsDirty = true; };
        autoPost.Unchecked += (_, _) => { if (!_applyingPublishingStatus) _publishingOptionsDirty = true; };
        schedule.SelectionChanged += (_, _) => { if (!_applyingPublishingStatus) _publishingOptionsDirty = true; };
        visibility.SelectionChanged += (_, _) => { if (!_applyingPublishingStatus) _publishingOptionsDirty = true; };

        defaults.Children.Add(autoPost);
        AddLabeled(defaults, "Default spacing between scheduled posts (minutes)", schedule,
            "Auto schedule uses this interval for each next clip. A 0-minute setting defaults to 5 minutes when you use Auto schedule.");
        AddLabeled(defaults, "Default visibility", visibility);
        _publishingStatusText ??= Txt("Checking Zernio status…", 10, false, "#9CDEF2");
        defaults.Children.Add(_publishingStatusText);

        var connectionCards = new StackPanel { Spacing = 10 };
        for (var index = 0; index < 5; index++)
        {
            var saved = index < savedConnections.Count ? savedConnections[index] : null;
            var id = saved?["id"]?.ToString();
            if (string.IsNullOrWhiteSpace(id))
                id = $"streamsnip-zernio-slot-{index + 1}";
            var label = saved?["label"]?.ToString();
            if (string.IsNullOrWhiteSpace(label))
                label = $"Zernio connection {index + 1}";
            _publishingSlotIds.Add(id);
            _publishingSlotLabels[id] = label;

            var slot = new StackPanel { Spacing = 8 };
            var header = new Grid { ColumnSpacing = 8 };
            header.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            header.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            var heading = Txt($"{index + 1}. {label}", 12, true);
            header.Children.Add(heading);
            var slotStatus = Txt(
                saved?["api_key_set"]?.GetValue<bool>() == true ? "Connected" : "Not connected",
                9, false,
                saved?["api_key_set"]?.GetValue<bool>() == true ? "#70C9A3" : "#9CDEF2");
            slotStatus.HorizontalAlignment = HorizontalAlignment.Right;
            Grid.SetColumn(slotStatus, 1);
            header.Children.Add(slotStatus);
            slot.Children.Add(header);
            _zernioSlotStatuses[id] = slotStatus;

            var key = new PasswordBox
            {
                PlaceholderText = saved?["api_key_set"]?.GetValue<bool>() == true
                    ? "Leave empty to keep the saved API key, or enter a replacement"
                    : "Paste Zernio API key",
                MinHeight = 36,
                FontFamily = CurrentFont
            };
            _zernioKeys[id] = key;
            AddLabeled(slot, "API key", key, "The key stays on this PC and is never returned by the local API.");

            var accounts = new StackPanel { Spacing = 5 };
            _zernioAccountPanels[id] = accounts;
            if (saved?["accounts"] is JsonArray existingAccounts)
                RenderConnectionAccounts(id, accounts, existingAccounts);
            else
                accounts.Children.Add(ThemeText("Save this key to discover its connected accounts.", 9, false, "MutedTextBrush"));
            slot.Children.Add(accounts);

            slot.Children.Add(ActionRow(
                CreateButton("Save & verify", async () => await SavePublishingConnectionsAsync(), primary: true),
                CreateButton("Refresh accounts", async () => await LoadPublishingAccountsAsync(id, accounts))));
            var card = new Border
            {
                Background = Application.Current.Resources["SurfaceSoftBrush"] as Brush,
                BorderBrush = Application.Current.Resources["LineBrush"] as Brush,
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(10),
                Padding = new Thickness(12),
                Child = slot
            };
            connectionCards.Children.Add(card);
        }

        defaults.Children.Add(ActionRow(
            CreateButton("Save all connections", async () => await SavePublishingConnectionsAsync(), primary: true),
            CreateButton("Refresh all accounts", async () =>
            {
                foreach (var id in _publishingSlotIds)
                {
                    var saved = FindPublishingConnection(id);
                    if (saved?["api_key_set"]?.GetValue<bool>() == true
                        && _zernioAccountPanels.TryGetValue(id, out var target))
                    {
                        await LoadPublishingAccountsAsync(id, target);
                    }
                }
            })));
        page.Children.Add(CreatePanel(
            "Publisher defaults",
            "These options apply across all five connection slots.",
            defaults));
        page.Children.Add(CreatePanel(
            "Zernio connections",
            "Five independent API-key slots. Every slot can load and enable the same supported social destinations.",
            connectionCards));

        if (_bulkClipNames.Count > 0)
        {
            var bulkPanel = new StackPanel { Spacing = 10 };
            bulkPanel.Children.Add(Txt($"{_bulkClipNames.Count:N0} clips selected for publishing", 12, true));
            bulkPanel.Children.Add(Txt("Each clip uses its saved title, description and caption metadata. All selected Zernio account destinations receive the batch.", 10, false, "#9CDEF2"));
            var selectedList = new StackPanel { Spacing = 4 };
            foreach (var name in _bulkClipNames.Take(12))
                selectedList.Children.Add(Txt(name, 9, false, "#9CDEF2"));
            if (_bulkClipNames.Count > 12)
                selectedList.Children.Add(Txt($"and {_bulkClipNames.Count - 12:N0} more…", 9, false, "#9CDEF2"));
            bulkPanel.Children.Add(selectedList);
            bulkPanel.Children.Add(ActionRow(
                CreateButton("Publish selected clips", async () =>
                {
                    try
                    {
                        var names = new JsonArray();
                        foreach (var name in _bulkClipNames) names.Add(name);
                        var result = await PostAsync("/api/publishing/publish", new JsonObject
                        {
                            ["names"] = names,
                            ["account_ids"] = BuildSelectedAccountMap()
                        });
                        await DialogResultAsync("Publishing started", result.ToJsonString(new System.Text.Json.JsonSerializerOptions { WriteIndented = true }));
                        _bulkClipNames.Clear();
                        _selectedClipNames.Clear();
                        await RefreshStateAsync(forceRender: false);
                    }
                    catch (Exception ex) { await ShowErrorAsync("Could not publish selected clips", ex.Message); }
                }, primary: true),
                CreateButton("Back to clip library", () => NavigateTo("clips"))));
            _bulkPublishingPanel = bulkPanel;
            page.Children.Add(CreatePanel("Publish selected clips", "Send the selected batch to the enabled Zernio destinations.", bulkPanel));
        }
        else if (_selectedClip is not null)
        {
            var publishPanel = new StackPanel { Spacing = 10 };
            publishPanel.Children.Add(Txt("Selected clip", 10, true));
            publishPanel.Children.Add(Txt(_selectedClip.Title.Length > 0 ? _selectedClip.Title : _selectedClip.Name, 12, true));
            var title = Input(
                string.IsNullOrWhiteSpace(_selectedClip.Title) ? _selectedClip.Name : _selectedClip.Title,
                "Post title");
            var description = Input(_selectedClip.Description, "Post description", multiline: true);
            AddLabeled(publishPanel, "Post title", title);
            AddLabeled(publishPanel, "Post description", description);
            publishPanel.Children.Add(CreateButton("Post via Zernio", async () =>
            {
                try
                {
                    var result = await PostAsync("/api/publishing/publish-one", new JsonObject
                    {
                        ["name"] = _selectedClip.Name,
                        ["title"] = title.Text.Trim(),
                        ["description"] = description.Text.Trim(),
                        ["account_ids"] = BuildSelectedAccountMap()
                    });
                    await DialogResultAsync("Publishing started", result.ToJsonString(new System.Text.Json.JsonSerializerOptions { WriteIndented = true }));
                    _selectedClip = null;
                    await RefreshStateAsync(forceRender: false);
                }
                catch (Exception ex) { await ShowErrorAsync("Could not publish clip", ex.Message); }
            }, primary: true));
            page.Children.Add(CreatePanel("Publish clip", "The engine reports the per-account provider result in Activity.", publishPanel));
        }

        PageHost.Children.Add(page);
        await LoadPublishingStatusAsync();
    }

    private JsonObject GetZernioPublishingStatus()
    {
        var providers = _publishingStatus["providers"] as JsonObject;
        return providers?["zernio"] as JsonObject ?? _publishingStatus;
    }

    private JsonObject? FindPublishingConnection(string connectionId)
    {
        var connections = GetZernioPublishingStatus()["connections"] as JsonArray;
        return connections?
            .Select(item => item as JsonObject)
            .FirstOrDefault(item => string.Equals(item?["id"]?.ToString(), connectionId, StringComparison.OrdinalIgnoreCase));
    }

    private async Task LoadPublishingStatusAsync()
    {
        if (_engine is null) return;
        try
        {
            _publishingStatus = await GetAsync("/api/publishing/status");
            var zernio = GetZernioPublishingStatus();
            var configured = zernio["api_key_set"]?.GetValue<bool>()
                ?? zernio["configured"]?.GetValue<bool>() ?? false;
            _applyingPublishingStatus = true;
            try
            {
                if (!_publishingOptionsDirty)
                {
                    if (_publishingAutoPost is not null)
                        _publishingAutoPost.IsChecked = zernio["auto_post"]?.GetValue<bool>() ?? false;
                    if (_publishingSchedule is not null)
                        _publishingSchedule.SelectedItem = zernio["schedule_minutes"]?.ToString() ?? "0";
                    if (_publishingVisibility is not null)
                        _publishingVisibility.SelectedItem = zernio["visibility"]?.ToString() ?? "public";
                }

                foreach (var id in _publishingSlotIds)
                {
                    var connection = FindPublishingConnection(id);
                    if (_zernioSlotStatuses.TryGetValue(id, out var status))
                    {
                        var isConnected = connection?["api_key_set"]?.GetValue<bool>() == true;
                        status.Text = isConnected ? "Connected" : "Not connected";
                        status.Foreground = Application.Current.Resources[
                            isConnected ? "SuccessBrush" : "MutedTextBrush"] as Brush;
                    }
                    if (!_publishingAccountsDirty
                        && _zernioAccountPanels.TryGetValue(id, out var target))
                    {
                        RenderConnectionAccounts(id, target, connection?["accounts"] as JsonArray ?? new JsonArray());
                    }
                }
            }
            finally { _applyingPublishingStatus = false; }

            if (_publishingStatusText is not null)
            {
                var savedCount = (zernio["connections"] as JsonArray)?.Count ?? 0;
                _publishingStatusText.Text = savedCount > 0
                    ? $"{savedCount}/5 Zernio connection(s) saved · credentials stay on this PC."
                    : configured
                        ? "A Zernio key is configured."
                        : "No Zernio API keys connected yet.";
            }
        }
        catch (Exception ex)
        {
            if (_publishingStatusText is not null) _publishingStatusText.Text = ex.Message;
        }
    }

    private void RenderConnectionAccounts(string connectionId, StackPanel target, JsonArray accounts)
    {
        target.Children.Clear();
        if (accounts.Count == 0)
        {
            target.Children.Add(ThemeText("No connected accounts found for this key yet.", 9, false, "MutedTextBrush"));
            return;
        }

        target.Children.Add(Txt("Enabled destinations", 10, true));
        foreach (var node in accounts)
        {
            if (node is not JsonObject account) continue;
            var id = account["id"]?.ToString() ?? "";
            var platform = account["platform"]?.ToString() ?? "";
            if (string.IsNullOrWhiteSpace(id) || string.IsNullOrWhiteSpace(platform)) continue;
            var name = account["name"]?.ToString() ?? platform;
            var username = account["username"]?.ToString() ?? "";
            var active = account["is_active"]?.GetValue<bool>() ?? true;
            var providerEnabled = account["provider_enabled"]?.GetValue<bool>() ?? true;
            var rateLimited = account["rate_limited"]?.GetValue<bool>() ?? false;
            var check = new CheckBox
            {
                Content = string.IsNullOrWhiteSpace(username)
                    ? $"{name} · {platform}"
                    : $"{name}  @{username}  ·  {platform}",
                Tag = new AccountSelection(connectionId, id, platform),
                IsChecked = account["posting_enabled"]?.GetValue<bool>()
                    ?? account["enabled"]?.GetValue<bool>() ?? (active && providerEnabled),
                IsEnabled = active && providerEnabled && !rateLimited,
                FontFamily = CurrentFont
            };
            check.Checked += (_, _) => { if (!_applyingPublishingStatus) _publishingAccountsDirty = true; };
            check.Unchecked += (_, _) => { if (!_applyingPublishingStatus) _publishingAccountsDirty = true; };
            _accountChecks[connectionId + "::" + id] = check;
            target.Children.Add(check);

            var error = account["last_error"]?.ToString();
            if (!string.IsNullOrWhiteSpace(error))
                target.Children.Add(ThemeText(error, 9, false, "MutedTextBrush"));
        }
    }

    private async Task LoadPublishingAccountsAsync(string connectionId, StackPanel target)
    {
        try
        {
            if (FindPublishingConnection(connectionId)?["api_key_set"]?.GetValue<bool>() != true)
                throw new InvalidOperationException("Save and verify this connection before loading its accounts.");
            var result = await PostAsync("/api/publishing/accounts", new JsonObject
            {
                ["provider"] = "zernio",
                ["connection_id"] = connectionId
            });
            var accounts = result["accounts"] as JsonArray ?? new JsonArray();
            var selected = new JsonArray();
            foreach (var item in accounts)
                if (item is JsonObject account)
                    selected.Add(account.DeepClone());
            RenderConnectionAccounts(connectionId, target, selected);
            _publishingAccountsDirty = false;
            await LoadPublishingStatusAsync();
        }
        catch (Exception ex)
        {
            await ShowErrorAsync("Could not load Zernio accounts", ex.Message);
        }
    }

    private async Task SavePublishingConnectionsAsync()
    {
        try
        {
            var connections = new JsonArray();
            foreach (var id in _publishingSlotIds)
            {
                var saved = FindPublishingConnection(id);
                var key = _zernioKeys.TryGetValue(id, out var password)
                    ? password.Password.Trim()
                    : "";
                var hasSavedKey = saved?["api_key_set"]?.GetValue<bool>() == true;
                if (string.IsNullOrWhiteSpace(key) && !hasSavedKey) continue;

                var connection = new JsonObject
                {
                    ["id"] = id,
                    ["label"] = _publishingSlotLabels.GetValueOrDefault(id, id)
                };
                if (!string.IsNullOrWhiteSpace(key))
                    connection["api_key"] = key;

                var accountRows = new JsonArray();
                foreach (var check in _accountChecks.Values)
                {
                    if (check.Tag is not AccountSelection selected
                        || !string.Equals(selected.ConnectionId, id, StringComparison.OrdinalIgnoreCase))
                        continue;
                    accountRows.Add(new JsonObject
                    {
                        ["id"] = selected.Id,
                        ["posting_enabled"] = check.IsChecked == true
                    });
                }
                if (accountRows.Count > 0)
                    connection["accounts"] = accountRows;
                connections.Add(connection);
            }

            if (connections.Count == 0)
                throw new InvalidOperationException("Enter at least one Zernio API key before saving.");

            var result = await PostAsync("/api/publishing", new JsonObject
            {
                ["provider"] = "zernio",
                ["connections"] = connections,
                ["auto_post"] = _publishingAutoPost?.IsChecked == true,
                ["schedule_minutes"] = int.TryParse(_publishingSchedule?.SelectedItem?.ToString(), out var delay) ? delay : 0,
                ["visibility"] = _publishingVisibility?.SelectedItem?.ToString() ?? "public"
            });

            foreach (var key in _zernioKeys.Values) key.Password = "";
            _publishingAccountsDirty = false;
            _publishingOptionsDirty = false;
            _publishingStatus = result;
            await LoadPublishingStatusAsync();
            if (_publishingStatusText is not null)
                _publishingStatusText.Text = "Publisher connections and defaults saved.";
        }
        catch (Exception ex)
        {
            await ShowErrorAsync("Could not save Publisher settings", ex.Message);
        }
    }

    private JsonArray BuildSelectedAccountMap()
    {
        var result = new JsonArray();
        foreach (var check in _accountChecks.Values)
        {
            if (check.IsChecked != true || check.Tag is not AccountSelection selection) continue;
            result.Add(new JsonObject
            {
                ["connection_id"] = selection.ConnectionId,
                ["account_id"] = selection.Id
            });
        }
        return result;
    }

    private sealed record AccountSelection(string ConnectionId, string Id, string Platform);

    private void RenderHypeWordsPage()
    {
        AddPageHeading("Hype words", "Custom phrases can help the highlight scorer notice creator-specific reactions.");

        var editor = new StackPanel { Spacing = 10 };
        _wordsText = Input("", "One word or phrase per line", multiline: true);
        _wordsText.MinHeight = 360;
        _wordsCount = Txt("0 custom entries", 9, false, "#9CDEF2");
        _wordsText.TextChanged += (_, _) => UpdateCustomWordsCount();
        editor.Children.Add(_wordsText);
        editor.Children.Add(_wordsCount);
        editor.Children.Add(Txt("Lines beginning with # are comments. Add an optional score after a vertical bar, for example: no way bro | 3.", 9, false, "#9CDEF2"));
        editor.Children.Add(ActionRow(
            CreateButton("Save phrase list", async () =>
            {
                try
                {
                    var result = await PostAsync("/api/words", new JsonObject { ["text"] = _wordsText.Text });
                    if (_wordsStatus is not null)
                        _wordsStatus.Text = $"Saved Â· {result["entries"]?.ToString() ?? "0"} custom entries";
                }
                catch (Exception ex) { await ShowErrorAsync("Could not save phrase list", ex.Message); }
            }, primary: true),
            CreateButton("Reload", async () => await LoadWordsAsync())));
        _wordsStatus = Txt("Loading custom phrasesâ€¦", 9, false, "#9CDEF2");
        editor.Children.Add(_wordsStatus);

        var vocabulary = new StackPanel { Spacing = 10 };
        _builtinVocabularyCounts = Txt("Loading built-in vocabularyâ€¦", 10, false, "#9CDEF2");
        vocabulary.Children.Add(_builtinVocabularyCounts);
        _builtinVocabularyGrid = new Grid { ColumnSpacing = 6, RowSpacing = 6 };
        for (var i = 0; i < 4; i++)
            _builtinVocabularyGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        vocabulary.Children.Add(_builtinVocabularyGrid);

        var info = new StackPanel { Spacing = 4 };
        info.Children.Add(Txt("How scoring works", 11, true));
        info.Children.Add(Txt("Transcript phrases contribute to moment detection. AI providers can also evaluate wider context when configured.", 9, false, "#9CDEF2"));

        var left = CreatePanel(
            "Custom words and phrases",
            "One phrase per line. Add an optional score after a vertical bar, for example: no way bro | 3",
            editor);
        var right = Vertical(
            CreatePanel("Built-in vocabulary", "The engine includes streamer reactions and common phrases.", vocabulary),
            CreatePanel("Local highlight scoring", "", info));
        PageHost.Children.Add(TwoColumns(left, right, 1.45, 1));
        _ = LoadWordsAsync();
    }

    private void UpdateCustomWordsCount()
    {
        if (_wordsText is null || _wordsCount is null) return;
        var lines = _wordsText.Text.Split(new[] { "\r\n", "\n" }, StringSplitOptions.None);
        var count = lines.Count(line =>
            !string.IsNullOrWhiteSpace(line) && !line.TrimStart().StartsWith("#", StringComparison.Ordinal));
        _wordsCount.Text = $"{count:N0} custom entries";
    }
    private async Task LoadWordsAsync()
    {
        try
        {
            var response = await GetAsync("/api/words");
            if (_wordsText is not null)
            {
                _wordsText.Text = response["text"]?.ToString()
                    ?? response["custom_text"]?.ToString()
                    ?? response["custom"]?.ToString()
                    ?? "";
                UpdateCustomWordsCount();
            }

            var words = response["words"] is JsonArray wordArray
                ? wordArray.Select(x => x?.ToString() ?? "").Where(x => x.Length > 0).ToList()
                : new List<string>();
            var phrases = response["phrases"] is JsonArray phraseArray
                ? phraseArray.Select(x => x?.ToString() ?? "").Where(x => x.Length > 0).ToList()
                : new List<string>();
            if (_builtinVocabularyCounts is not null)
                _builtinVocabularyCounts.Text = $"{words.Count:N0} words Â· {phrases.Count:N0} phrases";
            if (_builtinVocabularyGrid is not null)
            {
                _builtinVocabularyGrid.Children.Clear();
                _builtinVocabularyGrid.RowDefinitions.Clear();
                var visibleWords = words.Take(24).ToList();
                var rowCount = (int)Math.Ceiling(visibleWords.Count / 4.0);
                for (var row = 0; row < rowCount; row++)
                    _builtinVocabularyGrid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
                for (var i = 0; i < visibleWords.Count; i++)
                {
                    var chip = new Border
                    {
                        Background = Application.Current.Resources["SurfaceSoftBrush"] as Brush,
                        BorderBrush = Application.Current.Resources["LineBrush"] as Brush,
                        BorderThickness = new Thickness(1),
                        CornerRadius = new CornerRadius(7),
                        Padding = new Thickness(7, 5, 7, 5),
                        Margin = new Thickness(1)
                    };
                    chip.Child = Txt(visibleWords[i], 9, false, "#9CDEF2");
                    Grid.SetRow(chip, i / 4);
                    Grid.SetColumn(chip, i % 4);
                    _builtinVocabularyGrid.Children.Add(chip);
                }
            }
            if (_wordsStatus is not null)
                _wordsStatus.Text = "Changes apply to the next processed chunk.";
        }
        catch (Exception ex)
        {
            if (_wordsStatus is not null) _wordsStatus.Text = ex.Message;
            if (_builtinVocabularyCounts is not null) _builtinVocabularyCounts.Text = "Built-in vocabulary could not be loaded.";
        }
    }
    private void RenderActivityPage()
    {
        AddPageHeading("Activity", "Messages from capture, transcription, rendering, creator monitors, and publishing.");

        var controls = new StackPanel { Spacing = 8 };
        _activityAllButton = CreateButton("All events", () =>
        {
            _activityProblemsOnly = false;
            UpdateActivityFilterButtons();
            UpdateActivityRows();
        });
        _activityProblemsButton = CreateButton("Problems only", () =>
        {
            _activityProblemsOnly = true;
            UpdateActivityFilterButtons();
            UpdateActivityRows();
        });
        controls.Children.Add(ActionRow(_activityAllButton, _activityProblemsButton));
        _activitySearchBox = Input(_activityFilter, "Filter events");
        _activitySearchBox.TextChanged += (_, _) =>
        {
            _activityFilter = _activitySearchBox.Text;
            UpdateActivityRows();
        };
        controls.Children.Add(_activitySearchBox);
        controls.Children.Add(CreateButton("Download log", async () => await DownloadRuntimeLogAsync()));

        _activityVisibleCount = Txt("", 9, false, "#9CDEF2");
        _activityRowsHost = new StackPanel { Spacing = 3 };
        var body = Vertical(controls, _activityVisibleCount, _activityRowsHost);
        PageHost.Children.Add(CreatePanel("Engine events", "Recent messages from the local capture and rendering engine.", body));
        UpdateActivityFilterButtons();
        UpdateActivityRows();
    }

    private void UpdateActivityPageState()
    {
        UpdateActivityRows();
    }

    private void UpdateActivityFilterButtons()
    {
        var problems = _activity.Count(IsProblemLog);
        if (_activityProblemsButton is not null)
            _activityProblemsButton.Content = problems > 0 ? $"Problems only ({problems:N0})" : "Problems only";
        SetActivityButtonStyle(_activityAllButton, !_activityProblemsOnly);
        SetActivityButtonStyle(_activityProblemsButton, _activityProblemsOnly);
    }

    private static void SetActivityButtonStyle(Button? button, bool selected)
    {
        if (button is null) return;
        button.Background = Application.Current.Resources[selected ? "SurfaceHoverBrush" : "SurfaceBrush"] as Brush;
        button.BorderBrush = Application.Current.Resources[selected ? "AccentBrush" : "LineBrush"] as Brush;
        button.Foreground = Application.Current.Resources[selected ? "PrimaryTextBrush" : "BodyTextBrush"] as Brush;
    }

    private static bool IsProblemLog(LogItem log)
    {
        return log.FileLock is not null ||
            Regex.IsMatch(log.Message, @"\b(error|failed|failure|exception|warning|rejected|exhausted|unavailable)\b",
                RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
    }

    private void UpdateActivityRows()
    {
        if (_activityRowsHost is null) return;
        _activityRowsHost.Children.Clear();
        UpdateActivityFilterButtons();

        var filter = _activityFilter.Trim();
        var filtered = _activity.Where(log =>
        {
            if (_activityProblemsOnly && !IsProblemLog(log)) return false;
            return filter.Length == 0 ||
                (log.Message + " " + log.Time).Contains(filter, StringComparison.CurrentCultureIgnoreCase);
        }).ToList();

        if (_activityVisibleCount is not null)
            _activityVisibleCount.Text = $"{filtered.Count:N0} messages shown";
        if (filtered.Count == 0)
        {
            _activityRowsHost.Children.Add(Txt(
                _activityProblemsOnly ? "No problems recorded." : "No activity found.",
                11, true));
            _activityRowsHost.Children.Add(Txt(
                _activityProblemsOnly
                    ? "Errors, warnings and file-lock events from capture or publishing will appear here."
                    : "Engine messages appear here when capture, processing or publishing work begins.",
                9, false, "#9CDEF2"));
            _activityPageRenderedLastLogId = _lastLogId;
            return;
        }

        foreach (var log in filtered.TakeLast(300).Reverse())
        {
            var row = new Grid { ColumnSpacing = 12, Padding = new Thickness(8, 6, 8, 6) };
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(76) });
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            row.Children.Add(Txt(log.Time, 9, false, "#9CDEF2"));

            var details = new StackPanel { Spacing = 6 };
            var message = Txt(log.Message, 10);
            if (IsProblemLog(log))
                message.Foreground = Application.Current.Resources["DangerBrush"] as Brush;
            details.Children.Add(message);

            if (log.FileLock is JsonObject fileLock && fileLock["holders"] is JsonArray holders)
            {
                var fileName = fileLock["name"]?.ToString() ?? "";
                foreach (var holder in holders.OfType<JsonObject>())
                {
                    if (!int.TryParse(holder["pid"]?.ToString(), out var pid)) continue;
                    var processName = holder["name"]?.ToString() ?? "Unknown process";
                    var processPath = holder["path"]?.ToString() ?? "";
                    var stop = CreateButton($"Close {processName} (PID {pid})", async () =>
                        await StopFileHolderAsync(fileName, processName, processPath, pid), danger: true);
                    stop.MinHeight = 29;
                    details.Children.Add(stop);
                }
            }

            Grid.SetColumn(details, 1);
            row.Children.Add(details);
            _activityRowsHost.Children.Add(new Border
            {
                Background = Application.Current.Resources["SurfaceSoftBrush"] as Brush,
                BorderBrush = Application.Current.Resources["LineBrush"] as Brush,
                BorderThickness = new Thickness(0, 0, 0, 1),
                Child = row
            });
        }
        _activityPageRenderedLastLogId = _lastLogId;
    }

    private async Task StopFileHolderAsync(string fileName, string processName, string processPath, int pid)
    {
        var location = string.IsNullOrWhiteSpace(processPath) ? "" : Environment.NewLine + processPath;
        var dialog = new ContentDialog
        {
            XamlRoot = XamlRoot,
            Title = $"Close {processName}?",
            Content = $"This will ask Windows to close the process holding {fileName}.{location}{Environment.NewLine}Save any work in that application first.",
            PrimaryButtonText = "Close process",
            CloseButtonText = "Cancel",
            DefaultButton = ContentDialogButton.Close
        };
        if (await dialog.ShowAsync() != ContentDialogResult.Primary) return;
        try
        {
            var result = await PostAsync("/api/stop_file_holder", new JsonObject
            {
                ["name"] = fileName,
                ["pid"] = pid
            });
            await DialogResultAsync("Close request sent", result["message"]?.ToString() ?? "Windows received the close request.");
            await RefreshStateAsync();
        }
        catch (Exception ex)
        {
            await ShowErrorAsync("Could not close the locking process", ex.Message);
        }
    }

    private async Task DownloadRuntimeLogAsync()
    {
        var logPath = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "StreamSnip AI", "streamsnip.log");
        if (!File.Exists(logPath))
        {
            await ShowErrorAsync("Runtime log not found", logPath);
            return;
        }

        var picker = new FileSavePicker
        {
            SuggestedStartLocation = PickerLocationId.Downloads,
            SuggestedFileName = "streamsnip.log"
        };
        picker.FileTypeChoices.Add("Log file", new List<string> { ".log" });
        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowInstance!);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);
        var file = await picker.PickSaveFileAsync();
        if (file is null) return;
        await FileIO.WriteTextAsync(file, File.ReadAllText(logPath));
        await DialogResultAsync("Log saved", file.Path);
    }
    private void RenderHelpPage()
    {
        AddPageHeading("Help & how-to", "Setup walkthroughs, workflow guides, troubleshooting, and how the creator workspace behaves.");
        PageHost.Children.Add(CreatePanel("Quick start: first clip",
            "Move from a stream or local VOD to a rendered clip.",
            Vertical(
                Txt("1. Choose a Twitch/YouTube URL or local video in Live Studio.", 11),
                Txt("2. In Settings, choose Gemini, local Ollama, OpenAI/ChatGPT, or Anthropic/Claude. The selected model chooses moments and writes titles, descriptions, and tags.", 11),
                Txt("3. Choose a Faster-Whisper model and language for local transcription.", 11),
                Txt("4. Set video layout, output format, captions, creator credit, and profanity filtering.", 11),
                Txt("5. Press Start capture explicitly. Monitor progress in Dashboard and Activity.", 11),
                Txt("6. Review the rendered clip, edit title and description, then queue it through Zernio.", 11),
                CreateButton("Open Live Studio", () => NavigateTo("live"), primary: true))));
        PageHost.Children.Add(TwoColumns(
            CreatePanel("Capture", "Live streams and local recordings.",
                Txt("Live capture reconnects when the stream drops. Recorded VODs are transcribed, analyzed, and rendered locally. A graceful stop finishes clips already captured.", 10)),
            CreatePanel("AI and transcription", "Keep provider choice explicit.",
                Txt("Ollama runs locally. Gemini, OpenAI/ChatGPT, and Claude receive transcript text through the API you configure. Faster-Whisper and media processing run on this PC. Legacy hook phrases do not affect normal AI selection.", 10))));
        PageHost.Children.Add(TwoColumns(
            CreatePanel("Creators", "Independent source monitoring.",
                Txt("Each saved creator has independent live and VOD folders. A creator profile can be monitored without starting the current Live Studio capture.", 10)),
            CreatePanel("Clip library and publishing", "Local review, metadata and delivery.",
                Txt("Each clip has an MP4 plus a matching TXT metadata file. Publishing uses the configured Zernio connection and reports final platform results in Activity.", 10))));
    }

    private void RenderAboutPage()
    {
        AddPageHeading("About StreamSnip AI", "A local-first creator clipping workspace.");
        var brand = new StackPanel { Spacing = 10 };
        brand.Children.Add(Txt("StreamSnip AI", 20, true));
        brand.Children.Add(Txt("Creator Studio  ·  Native Windows desktop interface", 10, false, "#9CDEF2"));
        brand.Children.Add(Txt("The WinUI desktop app owns the windows and native controls. The Python engine handles Streamlink capture, FFmpeg media processing, Faster-Whisper transcription, AI highlight analysis, and clip rendering.", 11));
        brand.Children.Add(Txt("Application version 4.0.16", 10, false, "MutedTextBrush"));
        brand.Children.Add(ActionRow(
            CreateButton("GitHub source", () => OpenExternal("https://github.com/sifat-jaman-13/stream-clip-ai")),
            CreateButton("Latest releases", () => OpenExternal("https://github.com/sifat-jaman-13/stream-clip-ai/releases/latest"))));
        PageHost.Children.Add(CreatePanel("Application", "Built by ScarZero.", brand));
        PageHost.Children.Add(CreatePanel("Local-first architecture", "Your media processing stays on this PC.",
            Txt("The desktop UI communicates with the local Python engine over a loopback-only authenticated API. Local AI options and FFmpeg processing remain on-device; transcript text is shared only with the hosted provider you choose.", 10)));
    }

    private static void OpenExternal(string url)
    {
        try
        {
            System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(url) { UseShellExecute = true });
        }
        catch { }
    }
}
