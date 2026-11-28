using System.Text.Json.Nodes;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Imaging;
using Windows.Media.Core;
using Windows.Media.Playback;
using Windows.Storage.Pickers;
using Windows.Storage;

namespace StreamSnip_Desktop;

public sealed partial class MainPage
{
    private ClipItem? _selectedClip;
    private readonly HashSet<string> _selectedClipNames = new(StringComparer.OrdinalIgnoreCase);
    private List<string> _bulkClipNames = [];
    private StackPanel? _clipSelectionBar;
    private TextBlock? _clipSelectionCount;
    private CheckBox? _clipSelectPage;
    private Button? _clipDeleteAllButton;
    private TextBox? _clipTitleInput;
    private TextBox? _clipDescriptionInput;
    private MediaPlayerElement? _clipPlayer;
    private Border? _clipInspectorCard;
    private Border? _clipListSection;
    private Grid? _clipLibraryLayout;
    private readonly Dictionary<string, Button> _clipRowButtons = new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<string, Image> _clipThumbnailImages = new(StringComparer.OrdinalIgnoreCase);
    private readonly List<MediaPlayer> _clipHoverPlayers = [];
    private TextBlock? _clipLibraryCount;
    private TextBlock? _clipPageInfo;
    private Button? _clipPreviousButton;
    private Button? _clipNextButton;
    private TextBox? _clipSearchInput;
    private bool _clipPublished;
    private bool _zernioSyncInProgress;
    private DateTime _lastZernioSyncUtc = DateTime.MinValue;
    private DateTime _lastClipDataRefreshUtc = DateTime.MinValue;
    private string _lastClipDataTab = "";

    private void RenderClipLibraryPage(bool published)
    {
        _clipPublished = published;
        _clipTab = published ? "scheduled" : "clips";
        AddPageHeading(
            published ? "Scheduled & Posted" : "Clip library",
            published
                ? "Zernio posts accepted for future publishing and clips already sent successfully."
                : "Review generated clips, edit their post metadata, and publish or schedule them with Zernio.");

        var toolbar = new Grid { ColumnSpacing = 12 };
        toolbar.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        toolbar.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        var search = Input(_clipSearch, "Filter by title, file name, or creator");
        _clipSearchInput = search;
        search.MinWidth = 280;
        search.TextChanged += (_, _) =>
        {
            _clipSearch = search.Text;
            RefreshClipRows(published);
        };
        toolbar.Children.Add(search);
        var autoScheduleButton = CreateButton("Auto schedule", async () => await AutoScheduleClipsAsync(), primary: !published);
        autoScheduleButton.Visibility = published ? Visibility.Collapsed : Visibility.Visible;
        var syncButton = CreateButton(
            "Sync with Zernio",
            async () => await SyncZernioPostsAsync(showResult: true));
        syncButton.Visibility = published ? Visibility.Visible : Visibility.Collapsed;
        var actions = ActionRow(
            CreateButton("Ready to review", () => NavigateTo("clips"), primary: !published),
            CreateButton("Scheduled", () => NavigateTo("published"), primary: published),
            autoScheduleButton,
            syncButton,
            CreateButton("Open creator folders", async () =>
            {
                try { await PostAsync("/api/creators/open-root", new JsonObject()); }
                catch (Exception ex) { await ShowErrorAsync("Could not open creator folders", ex.Message); }
            }));
        Grid.SetColumn(actions, 1);
        toolbar.Children.Add(actions);
        PageHost.Children.Add(toolbar);

        _clipSelectionBar = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            Spacing = 8,
            Padding = new Thickness(12, 8, 12, 8),
            Background = Application.Current.Resources["SurfaceSoftBrush"] as Brush,
            Visibility = Visibility.Collapsed
        };
        _clipSelectionCount = Txt("0 selected", 10, true);
        _clipSelectionBar.Children.Add(_clipSelectionCount);
        _clipSelectionBar.Children.Add(CreateButton("Publish selected", () => NavigateToPublishingForClips(_selectedClipNames.ToList()), primary: true));
        _clipSelectionBar.Children.Add(CreateButton("Delete selected", async () => await DeleteSelectedClipsAsync(), danger: true));
        _clipSelectionBar.Children.Add(CreateButton("Clear", () =>
        {
            _selectedClipNames.Clear();
            RefreshClipRows(published);
            UpdateClipSelectionBar();
        }));
        PageHost.Children.Add(_clipSelectionBar);
        UpdateClipSelectionBar();

        var layout = new Grid { ColumnSpacing = 16 };
        layout.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        layout.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(360) });
        _clipLibraryLayout = layout;
        layout.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        layout.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });

        var listPanel = new StackPanel { Spacing = 10 };
        var currentTotal = published ? (_state?.ScheduledTotal ?? 0) : (_state?.ClipTotal ?? 0);
        _clipLibraryCount = ThemeText($"{currentTotal:N0} total", 10, false, "MutedTextBrush");
        _clipSelectPage = new CheckBox
        {
            Content = "Select this page",
            FontFamily = CurrentFont,
            FontSize = UiFontSize(10)
        };
        _clipSelectPage.Checked += (_, _) => SetCurrentPageSelection(published, true);
        _clipSelectPage.Unchecked += (_, _) => SetCurrentPageSelection(published, false);
        _clipDeleteAllButton = CreateButton("Delete all", async () => await DeleteAllClipsAsync(published), danger: true);
        _clipDeleteAllButton.IsEnabled = currentTotal > 0;
        listPanel.Children.Add(ActionRow(_clipSelectPage, _clipLibraryCount, _clipDeleteAllButton));
        var list = new StackPanel { Spacing = 7 };
        _clipRowsHost = list;
        RefreshClipRows(published);
        var scroll = new ScrollViewer
        {
            Content = list,
            VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
            MaxHeight = 600
        };
        listPanel.Children.Add(scroll);

        var pageSize = 60;
        var total = published ? (_state?.ScheduledTotal ?? 0) : (_state?.ClipTotal ?? 0);
        var pageNumber = _clipOffset / pageSize + 1;
        var pages = Math.Max(1, (int)Math.Ceiling(total / (double)pageSize));
        _clipPreviousButton = CreateButton("Previous", async () =>
        {
            _clipOffset = Math.Max(0, _clipOffset - pageSize);
            await RefreshStateAsync(forceRender: true);
        });
        _clipPreviousButton.IsEnabled = _clipOffset > 0;
        _clipNextButton = CreateButton("Next", async () =>
        {
            if (_clipOffset + pageSize >= total) return;
            _clipOffset += pageSize;
            await RefreshStateAsync(forceRender: true);
        });
        _clipNextButton.IsEnabled = _clipOffset + pageSize < total;
        _clipPageInfo = ThemeText($"Page {pageNumber} of {pages}", 10, false, "MutedTextBrush");
        var pagination = ActionRow(_clipPreviousButton, _clipNextButton, _clipPageInfo);
        listPanel.Children.Add(pagination);

        var preview = BuildClipInspector(_selectedClip, published);

        _clipListSection = CreateCompactLibraryPanel(
            published ? "Scheduled & Posted clips" : "Ready to review",
            "Your newest MP4 files and their post details.",
            listPanel);
        _clipInspectorCard = CreateCompactLibraryPanel(
            "Clip details",
            "Preview, edit, and publish this video.",
            preview);
        layout.Children.Add(_clipListSection);
        layout.Children.Add(_clipInspectorCard);

        layout.SizeChanged += (_, args) => UpdateClipLibraryLayout(args.NewSize.Width);
        layout.Loaded += (_, _) => UpdateClipLibraryLayout(layout.ActualWidth);
        PageHost.Children.Add(layout);
    }

    private static Border CreateCompactLibraryPanel(
        string title,
        string description,
        UIElement content)
    {
        var stack = new StackPanel { Spacing = 10 };
        stack.Children.Add(Txt(title, 14, true));
        if (!string.IsNullOrWhiteSpace(description))
            stack.Children.Add(ThemeText(description, 10, false, "MutedTextBrush"));
        stack.Children.Add(content);
        return new Border
        {
            Background = Application.Current.Resources["SurfaceBrush"] as Brush,
            BorderBrush = Application.Current.Resources["LineBrush"] as Brush,
            BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(10),
            Padding = new Thickness(14),
            Child = stack
        };
    }

    private void UpdateClipLibraryLayout(double width)
    {
        if (_clipLibraryLayout is null || _clipListSection is null || _clipInspectorCard is null)
            return;

        var hasSelection = _selectedClip is not null;
        var stacked = hasSelection && width < 860;
        _clipInspectorCard.Visibility = hasSelection ? Visibility.Visible : Visibility.Collapsed;
        _clipLibraryLayout.ColumnSpacing = hasSelection && !stacked ? 16 : 0;
        _clipLibraryLayout.RowSpacing = stacked ? 14 : 0;

        Grid.SetColumn(_clipListSection, 0);
        Grid.SetRow(_clipListSection, 0);
        Grid.SetColumnSpan(_clipListSection, !hasSelection || stacked ? 2 : 1);
        Grid.SetColumn(_clipInspectorCard, stacked ? 0 : 1);
        Grid.SetRow(_clipInspectorCard, stacked ? 1 : 0);
        Grid.SetColumnSpan(_clipInspectorCard, stacked ? 2 : 1);
    }

    private StackPanel BuildClipInspector(ClipItem? clip, bool published)
    {
        var preview = new StackPanel { Spacing = 10 };
        if (clip is null)
        {
            preview.Children.Add(Txt("Select a clip to review", 14, true));
            preview.Children.Add(ThemeText("Preview video, edit title and description, or open the original file location.", 10, false, "MutedTextBrush"));
            var emptyPreview = new Grid { MinHeight = 150 };
            var emptyPreviewContent = new StackPanel
            {
                Spacing = 8,
                HorizontalAlignment = HorizontalAlignment.Center,
                VerticalAlignment = VerticalAlignment.Center
            };
            emptyPreviewContent.Children.Add(new PathIcon
            {
                Data = CreateVideoIconGeometry(),
                Width = 32,
                Height = 32,
                Foreground = Application.Current.Resources["MutedTextBrush"] as Brush
            });
            var selectHint = ThemeText("Choose a clip to preview", 15, true, "PrimaryTextBrush");
            selectHint.HorizontalAlignment = HorizontalAlignment.Center;
            emptyPreviewContent.Children.Add(selectHint);
            emptyPreview.Children.Add(emptyPreviewContent);
            emptyPreview.SizeChanged += (_, args) =>
                emptyPreview.Height = Math.Max(150, args.NewSize.Width * 9.0 / 16.0);
            emptyPreview.Loaded += (_, _) =>
                emptyPreview.Height = Math.Max(150, emptyPreview.ActualWidth * 9.0 / 16.0);
            preview.Children.Add(new Border
            {
                Background = Application.Current.Resources["SurfaceSoftBrush"] as Brush,
                BorderBrush = Application.Current.Resources["LineBrush"] as Brush,
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(10),
                Child = emptyPreview
            });
        }
        else
        {
            preview.Children.Add(Txt("Clip preview", 12, true));
            _clipPlayer = new MediaPlayerElement
            {
                AreTransportControlsEnabled = true,
                AutoPlay = false,
                MinHeight = 180,
                MaxHeight = 250,
                Stretch = Stretch.Uniform
            };
            if (_engine?.BaseAddress is Uri baseAddress)
            {
                var clipUri = new Uri(baseAddress, "clips/" + Uri.EscapeDataString(clip.Name));
                _clipPlayer.Source = MediaSource.CreateFromUri(clipUri);
            }
            preview.Children.Add(_clipPlayer);
            preview.Children.Add(ThemeText(clip.Name, 10, false, "MutedTextBrush"));

            _clipTitleInput = Input(
                string.IsNullOrWhiteSpace(clip.Title) ? clip.Name : clip.Title,
                "Post title");
            AddLabeled(preview, "Post title", _clipTitleInput);
            _clipDescriptionInput = Input(clip.Description, "Post description", multiline: true);
            AddLabeled(preview, "Post description", _clipDescriptionInput);

            var previewActions = new StackPanel { Spacing = 8 };
            var postSelected = CreateButton("Post via Zernio", async () => await PostClipViaZernioAsync(clip), primary: false);
            postSelected.IsEnabled = !published && !clip.Posted && !clip.Scheduled;
            previewActions.Children.Add(ActionRow(
                CreateButton("Save details", async () => await SaveSelectedClipMetadataAsync(), primary: true),
                postSelected));
            previewActions.Children.Add(ActionRow(
                CreateButton("Copy caption", async () => await CopySelectedClipCaptionAsync()),
                CreateButton("Download video", async () => await DownloadSelectedClipAsync())));
            previewActions.Children.Add(ActionRow(
                CreateButton("Show in folder", async () =>
                {
                    try { await PostAsync("/api/reveal", new JsonObject { ["name"] = clip.Name }); }
                    catch (Exception ex) { await ShowErrorAsync("Could not reveal clip", ex.Message); }
                }),
                CreateButton("Delete clip", async () => await DeleteSelectedClipAsync(), danger: true)));
            preview.Children.Add(previewActions);
        }

        return preview;
    }

    private void UpdateClipInspector(ClipItem? clip, bool published)
    {
        if (_clipInspectorCard?.Child is not StackPanel panel)
            return;

        _clipPlayer?.Source = null;
        _clipPlayer = null;
        var replacement = BuildClipInspector(clip, published);
        if (panel.Children.Count == 0)
            panel.Children.Add(replacement);
        else
        {
            panel.Children.RemoveAt(panel.Children.Count - 1);
            panel.Children.Add(replacement);
        }
    }

    private void RefreshClipThumbnail(string clipName)
    {
        if (!_clipThumbnailImages.TryGetValue(clipName, out var image) ||
            _engine?.BaseAddress is not Uri baseAddress)
            return;
        try
        {
            image.Source = null;
            image.Source = new BitmapImage(new Uri(
                baseAddress,
                "clip-thumbnails/" + Uri.EscapeDataString(clipName) + "?v=" + DateTime.UtcNow.Ticks));
        }
        catch { }
    }

    private void UpdateClipRowSelectionStyles()
    {
        foreach (var pair in _clipRowButtons)
        {
            var selected = string.Equals(
                pair.Key, _selectedClip?.Name, StringComparison.OrdinalIgnoreCase);
            pair.Value.Background = Application.Current.Resources[
                selected ? "AccentSoftBrush" : "SurfaceSoftBrush"] as Brush;
            pair.Value.BorderBrush = Application.Current.Resources[
                selected ? "AccentBrush" : "LineBrush"] as Brush;
        }
    }

    private async Task SyncZernioPostsAsync(bool showResult)
    {
        if (_zernioSyncInProgress || _engine is null)
            return;
        _zernioSyncInProgress = true;
        _lastZernioSyncUtc = DateTime.UtcNow;
        try
        {
            var result = await PostAsync("/api/publishing/sync-posts", new JsonObject());
            var message = result["message"]?.ToString() ?? "Zernio post statuses synchronized.";
            if (showResult)
                await DialogResultAsync("Zernio sync complete", message);
            await RefreshStateAsync(forceRender: true);
        }
        catch (Exception ex)
        {
            if (showResult)
                await ShowErrorAsync("Could not sync Zernio posts", ex.Message);
        }
        finally
        {
            _zernioSyncInProgress = false;
        }
    }

    private async Task CopySelectedClipCaptionAsync()
    {
        if (_selectedClip is null) return;
        var caption = !string.IsNullOrWhiteSpace(_selectedClip.Caption)
            ? _selectedClip.Caption
            : string.Join("\n\n", new[]
            {
                _selectedClip.Title,
                _selectedClip.Description
            }.Where(value => !string.IsNullOrWhiteSpace(value)));
        if (string.IsNullOrWhiteSpace(caption))
        {
            await ShowErrorAsync("Nothing to copy", "This clip does not have caption text yet.");
            return;
        }

        var package = new Windows.ApplicationModel.DataTransfer.DataPackage();
        package.SetText(caption);
        Windows.ApplicationModel.DataTransfer.Clipboard.SetContent(package);
        Windows.ApplicationModel.DataTransfer.Clipboard.Flush();
        await DialogResultAsync("Caption copied", "The clip title, description, and caption text are on your clipboard.");
    }

    private async Task DownloadSelectedClipAsync()
    {
        if (_selectedClip is null || _engine?.BaseAddress is not Uri baseAddress)
            return;
        try
        {
            var picker = new FileSavePicker
            {
                SuggestedStartLocation = PickerLocationId.Downloads,
                SuggestedFileName = Path.GetFileName(_selectedClip.Name)
            };
            picker.FileTypeChoices.Add("MP4 video", new List<string> { ".mp4" });
            var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowInstance!);
            WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);
            var destination = await picker.PickSaveFileAsync();
            if (destination is null) return;

            var clipUri = new Uri(baseAddress, "clips/" + Uri.EscapeDataString(_selectedClip.Name));
            using var client = new HttpClient { Timeout = TimeSpan.FromMinutes(5) };
            using var response = await client.GetAsync(
                clipUri, HttpCompletionOption.ResponseHeadersRead, _shutdown.Token);
            response.EnsureSuccessStatusCode();
            await using var input = await response.Content.ReadAsStreamAsync(_shutdown.Token);
            await using var output = await destination.OpenStreamForWriteAsync();
            output.SetLength(0);
            await input.CopyToAsync(output, 1024 * 1024, _shutdown.Token);
            await output.FlushAsync(_shutdown.Token);
            await DialogResultAsync("Video downloaded", destination.Path);
        }
        catch (Exception ex)
        {
            await ShowErrorAsync("Could not download clip", ex.Message);
        }
    }

    private StackPanel? _clipRowsHost;

    private void UpdateClipLibraryState(bool refreshRows = true)
    {
        if (_clipRowsHost is null) return;
        var published = _clipPublished;
        var total = published ? (_state?.ScheduledTotal ?? 0) : (_state?.ClipTotal ?? 0);
        const int pageSize = 60;
        var pageNumber = _clipOffset / pageSize + 1;
        var pages = Math.Max(1, (int)Math.Ceiling(total / (double)pageSize));
        if (_clipLibraryCount is not null)
            _clipLibraryCount.Text = $"{total:N0} clip(s)";
        if (_clipPageInfo is not null)
            _clipPageInfo.Text = $"Page {pageNumber} of {pages}";
        if (_clipPreviousButton is not null)
            _clipPreviousButton.IsEnabled = _clipOffset > 0;
        if (_clipNextButton is not null)
            _clipNextButton.IsEnabled = _clipOffset + pageSize < total;
        if (refreshRows)
            RefreshClipRows(published);
    }

    private void RefreshClipRows(bool published)
    {
        if (_clipRowsHost is null) return;
        _clipRowsHost.Children.Clear();
        _clipRowButtons.Clear();
        _clipThumbnailImages.Clear();
        foreach (var player in _clipHoverPlayers)
        {
            try { player.Pause(); player.Source = null; player.Dispose(); } catch { }
        }
        _clipHoverPlayers.Clear();
        var clips = _state?.Clips ?? [];
        var filtered = clips.Where(clip =>
            string.IsNullOrWhiteSpace(_clipSearch) ||
            $"{clip.Title} {clip.Name} {clip.CreatorName} {clip.Source}"
                .Contains(_clipSearch, StringComparison.CurrentCultureIgnoreCase)).ToList();

        if (filtered.Count == 0)
        {
            _clipRowsHost.Children.Add(Txt(
                string.IsNullOrWhiteSpace(_clipSearch)
                    ? published ? "Nothing has been scheduled yet." : "Your clip library is empty."
                    : "No clips match this search.",
                11, true));
            _clipRowsHost.Children.Add(ThemeText(
                published
                    ? "Scheduled posts and successful Zernio posts appear here."
                    : "Clips appear here after the engine finishes rendering a highlight.",
                10, false, "MutedTextBrush"));
            return;
        }

        foreach (var clip in filtered)
        {
            var selected = _selectedClip?.Name == clip.Name;
            var copy = new StackPanel { Spacing = 4, VerticalAlignment = VerticalAlignment.Center };
            copy.Children.Add(Txt(
                string.IsNullOrWhiteSpace(clip.Title) ? clip.Name : clip.Title,
                11, true));
            copy.Children.Add(ThemeText(
                $"{(clip.Scheduled ? "Scheduled" : clip.Posted ? "Posted" : "Ready to post")}  ?  {(string.IsNullOrWhiteSpace(clip.CreatorName) ? clip.Source : clip.CreatorName)}  ?  {FormatSize(clip.SizeMb)}",
                10, false, "MutedTextBrush"));
            copy.Children.Add(ThemeText(FormatClipDate(clip.ModifiedAt), 10, false, "MutedTextBrush"));

            var thumbnailGrid = new Grid { Width = 124, Height = 70 };
            thumbnailGrid.Children.Add(new PathIcon
            {
                Data = CreateVideoIconGeometry(),
                Width = 24,
                Height = 24,
                HorizontalAlignment = HorizontalAlignment.Center,
                VerticalAlignment = VerticalAlignment.Center,
                Foreground = Application.Current.Resources["MutedTextBrush"] as Brush
            });
            Image? thumbnailImage = null;
            Uri? clipUri = null;
            if (_engine?.BaseAddress is Uri thumbnailBase)
            {
                clipUri = new Uri(thumbnailBase, "clips/" + Uri.EscapeDataString(clip.Name));
                thumbnailImage = new Image
                {
                    Width = 124,
                    Height = 70,
                    Stretch = Stretch.UniformToFill,
                    HorizontalAlignment = HorizontalAlignment.Center,
                    VerticalAlignment = VerticalAlignment.Center,
                    Source = new BitmapImage(new Uri(
                        thumbnailBase,
                        "clip-thumbnails/" + Uri.EscapeDataString(clip.Name)))
                };
                thumbnailGrid.Children.Add(thumbnailImage);
                _clipThumbnailImages[clip.Name] = thumbnailImage;
            }

            // Match the v4.0.9 web card: video starts only while the card is
            // hovered, never for all 60 clips at initial gallery render.
            var hoverPlayerElement = new MediaPlayerElement
            {
                Width = 124,
                Height = 70,
                AreTransportControlsEnabled = false,
                AutoPlay = false,
                Stretch = Stretch.UniformToFill,
                Visibility = Visibility.Collapsed,
                IsHitTestVisible = false
            };
            thumbnailGrid.Children.Add(hoverPlayerElement);
            MediaPlayer? hoverMediaPlayer = null;
            var thumbnailFrame = new Border
            {
                Width = 124,
                Height = 70,
                CornerRadius = new CornerRadius(8),
                Background = Application.Current.Resources["SurfaceSoftBrush"] as Brush,
                BorderBrush = Application.Current.Resources["LineBrush"] as Brush,
                BorderThickness = new Thickness(1),
                Child = thumbnailGrid
            };
            var cardContent = new StackPanel
            {
                Orientation = Orientation.Horizontal,
                Spacing = 12,
                HorizontalAlignment = HorizontalAlignment.Stretch
            };
            cardContent.Children.Add(thumbnailFrame);
            cardContent.Children.Add(copy);

            var choose = new Button
            {
                Content = cardContent,
                HorizontalContentAlignment = HorizontalAlignment.Stretch,
                Background = Application.Current.Resources[selected ? "AccentSoftBrush" : "SurfaceSoftBrush"] as Brush,
                BorderBrush = Application.Current.Resources[selected ? "AccentBrush" : "LineBrush"] as Brush,
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(8),
                Padding = new Thickness(11, 9, 11, 9),
                HorizontalAlignment = HorizontalAlignment.Stretch
            };
            choose.Click += (_, _) =>
            {
                if (string.Equals(_selectedClip?.Name, clip.Name, StringComparison.OrdinalIgnoreCase))
                    return;
                _selectedClip = clip;
                UpdateClipRowSelectionStyles();
                UpdateClipInspector(clip, published);
                UpdateClipLibraryLayout(_clipLibraryLayout?.ActualWidth ?? 0);
            };
            choose.PointerEntered += (_, _) =>
            {
                if (clipUri is null)
                    return;
                try
                {
                    thumbnailImage?.SetValue(UIElement.VisibilityProperty, Visibility.Collapsed);
                    if (hoverMediaPlayer is null)
                    {
                        hoverMediaPlayer = new MediaPlayer
                        {
                            IsMuted = true,
                            IsLoopingEnabled = true
                        };
                        hoverPlayerElement.SetMediaPlayer(hoverMediaPlayer);
                        _clipHoverPlayers.Add(hoverMediaPlayer);
                    }
                    hoverPlayerElement.Visibility = Visibility.Visible;
                    hoverMediaPlayer.Source = MediaSource.CreateFromUri(clipUri);
                    hoverMediaPlayer.Play();
                }
                catch
                {
                    hoverPlayerElement.Visibility = Visibility.Collapsed;
                    if (thumbnailImage is not null)
                        thumbnailImage.Visibility = Visibility.Visible;
                }
            };
            choose.PointerExited += (_, _) =>
            {
                try
                {
                    hoverMediaPlayer?.Pause();
                    if (hoverMediaPlayer is not null)
                        hoverMediaPlayer.Source = null;
                }
                catch { }
                hoverPlayerElement.Visibility = Visibility.Collapsed;
                if (thumbnailImage is not null)
                    thumbnailImage.Visibility = Visibility.Visible;
            };
            _clipRowButtons[clip.Name] = choose;
            var selectedCheck = new CheckBox
            {
                IsChecked = _selectedClipNames.Contains(clip.Name),
                VerticalAlignment = VerticalAlignment.Center,
                MinWidth = 26,
                Tag = clip.Name
            };
            selectedCheck.Checked += (_, _) => ToggleClipSelection(clip.Name, true, published);
            selectedCheck.Unchecked += (_, _) => ToggleClipSelection(clip.Name, false, published);
            var row = new Grid { ColumnSpacing = 8 };
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            row.Children.Add(selectedCheck);
            Grid.SetColumn(choose, 1);
            row.Children.Add(choose);
            var postNow = CreateButton("Post", async () => await PostClipViaZernioAsync(clip), primary: true);
            postNow.Visibility = published ? Visibility.Collapsed : Visibility.Visible;
            postNow.IsEnabled = !clip.Posted && !clip.Scheduled;
            Microsoft.UI.Xaml.Automation.AutomationProperties.SetName(postNow, $"Post {clip.Name} via Zernio");
            Grid.SetColumn(postNow, 2);
            row.Children.Add(postNow);
            _clipRowsHost.Children.Add(row);
        }
        UpdateClipSelectionBar();
        UpdateClipSelectPageCheck(filtered);
        UpdateClipRowSelectionStyles();
    }
    private void ToggleClipSelection(string name, bool selected, bool published)
    {
        if (selected) _selectedClipNames.Add(name);
        else _selectedClipNames.Remove(name);
        UpdateClipSelectionBar();
        var filtered = _state?.Clips.Where(clip =>
            string.IsNullOrWhiteSpace(_clipSearch) ||
            $"{clip.Title} {clip.Name} {clip.CreatorName} {clip.Source}".Contains(_clipSearch, StringComparison.CurrentCultureIgnoreCase)).ToList() ?? [];
        UpdateClipSelectPageCheck(filtered);
    }

    private void SetCurrentPageSelection(bool published, bool selected)
    {
        var filtered = (_state?.Clips ?? []).Where(clip =>
            string.IsNullOrWhiteSpace(_clipSearch) ||
            $"{clip.Title} {clip.Name} {clip.CreatorName} {clip.Source}".Contains(_clipSearch, StringComparison.CurrentCultureIgnoreCase)).ToList();
        foreach (var clip in filtered)
        {
            if (selected) _selectedClipNames.Add(clip.Name);
            else _selectedClipNames.Remove(clip.Name);
        }
        RefreshClipRows(published);
        UpdateClipSelectionBar();
    }

    private void UpdateClipSelectPageCheck(List<ClipItem> filtered)
    {
        if (_clipSelectPage is null) return;
        _clipSelectPage.IsChecked = filtered.Count > 0 && filtered.All(clip => _selectedClipNames.Contains(clip.Name));
    }

    private void UpdateClipSelectionBar()
    {
        if (_clipSelectionBar is null) return;
        var count = _selectedClipNames.Count;
        _clipSelectionBar.Visibility = count > 0 ? Visibility.Visible : Visibility.Collapsed;
        if (_clipSelectionCount is not null)
            _clipSelectionCount.Text = $"{count:N0} selected";
        var publish = _clipSelectionBar.Children.OfType<Button>().FirstOrDefault(button => button.Content?.ToString() == "Publish selected");
        if (publish is not null) publish.IsEnabled = count > 0 && !_clipPublished;
    }

    private async Task AutoScheduleClipsAsync()
    {
        var count = _state?.ClipTotal ?? 0;
        if (count <= 0)
        {
            await DialogResultAsync("No clips to schedule", "Your ready-to-review clip list is empty.");
            return;
        }

        var dialog = new ContentDialog
        {
            XamlRoot = XamlRoot,
            Title = $"Auto-schedule {count:N0} clip(s)?",
            Content = "StreamSnip will send every ready clip to your enabled Zernio accounts and space the posts using the Publisher schedule interval. If no interval is set, posts are spaced 5 minutes apart. Clips move to Scheduled only after Zernio confirms the scheduled destinations.",
            PrimaryButtonText = "Schedule all",
            CloseButtonText = "Cancel",
            DefaultButton = ContentDialogButton.Close
        };
        if (await ShowThemedDialogAsync(dialog) != ContentDialogResult.Primary) return;

        try
        {
            var result = await PostAsync("/api/publishing/publish", new JsonObject
            {
                ["all"] = true,
                ["auto_schedule"] = true
            });
            var queued = result["queued"]?.ToString() ?? count.ToString();
            await DialogResultAsync("Auto-schedule started", $"{queued} clip(s) were submitted to the scheduler. Their status will move to Scheduled when Zernio confirms each post.");
            await RefreshStateAsync(forceRender: true);
        }
        catch (Exception ex)
        {
            await ShowErrorAsync("Could not auto-schedule clips", ex.Message);
        }
    }

    private async Task PostClipViaZernioAsync(ClipItem? clip)
    {
        if (clip is null || clip.Posted || clip.Scheduled) return;
        var title = string.IsNullOrWhiteSpace(clip.Title) ? clip.Name : clip.Title;
        try
        {
            var result = await PostAsync("/api/publishing/publish-one", new JsonObject
            {
                ["name"] = clip.Name,
                ["title"] = title,
                ["description"] = clip.Description
            });
            await DialogResultAsync(
                "Publishing started",
                $"Zernio accepted the publishing job for {clip.Name}. It will appear in Scheduled with a Posted status once Zernio confirms publication.");
            await RefreshStateAsync(forceRender: true);
        }
        catch (Exception ex)
        {
            await ShowErrorAsync("Could not post clip via Zernio", ex.Message);
        }
    }

    private async Task DeleteSelectedClipsAsync()
    {
        var names = _selectedClipNames.ToList();
        if (names.Count == 0) return;
        var dialog = new ContentDialog
        {
            XamlRoot = XamlRoot,
            Title = $"Delete {names.Count:N0} selected clip(s)?",
            Content = "This permanently removes the selected MP4 files and their matching caption/metadata files.",
            PrimaryButtonText = "Delete selected",
            CloseButtonText = "Cancel",
            DefaultButton = ContentDialogButton.Close
        };
        if (await ShowThemedDialogAsync(dialog) != ContentDialogResult.Primary) return;
        try
        {
            var array = new JsonArray();
            foreach (var name in names) array.Add(name);
            await PostAsync("/api/delete_many", new JsonObject { ["names"] = array });
            _selectedClipNames.Clear();
            if (_selectedClip is not null && names.Contains(_selectedClip.Name, StringComparer.OrdinalIgnoreCase))
                _selectedClip = null;
            await RefreshStateAsync(forceRender: true);
        }
        catch (Exception ex) { await ShowErrorAsync("Could not delete selected clips", ex.Message); }
    }

    private async Task DeleteAllClipsAsync(bool published)
    {
        var count = published ? (_state?.ScheduledTotal ?? 0) : (_state?.ClipTotal ?? 0);
        if (count <= 0) return;
        var tab = published ? "scheduled" : "clips";
        var dialog = new ContentDialog
        {
            XamlRoot = XamlRoot,
            Title = $"Delete all {count:N0} {(published ? "scheduled" : "ready")} clip(s)?",
            Content = "This permanently removes every MP4 and matching metadata file in this tab. This cannot be undone.",
            PrimaryButtonText = "Delete all",
            CloseButtonText = "Cancel",
            DefaultButton = ContentDialogButton.Close
        };
        if (await ShowThemedDialogAsync(dialog) != ContentDialogResult.Primary) return;
        try
        {
            await PostAsync("/api/delete_all", new JsonObject { ["clip_tab"] = tab });
            _selectedClipNames.Clear();
            _selectedClip = null;
            await RefreshStateAsync(forceRender: true);
        }
        catch (Exception ex) { await ShowErrorAsync("Could not delete all clips", ex.Message); }
    }

    private void NavigateToPublishingForClips(List<string> names)
    {
        if (names.Count == 0) return;
        _bulkClipNames = names.Distinct(StringComparer.OrdinalIgnoreCase).ToList();
        _selectedClip = null;
        NavigateTo("publishing");
    }
    private async Task SaveSelectedClipMetadataAsync()
    {
        if (_selectedClip is null || _clipTitleInput is null || _clipDescriptionInput is null) return;
        var title = _clipTitleInput.Text.Trim();
        if (title.Length == 0)
        {
            await ShowErrorAsync("Post title required", "Add a title before saving clip metadata.");
            return;
        }
        try
        {
            await PostAsync("/api/clip-metadata", new JsonObject
            {
                ["name"] = _selectedClip.Name,
                ["title"] = title,
                ["description"] = _clipDescriptionInput.Text.Trim()
            });
            var name = _selectedClip.Name;
            await RefreshStateAsync(forceRender: true);
            _selectedClip = _state?.Clips.FirstOrDefault(x => x.Name == name) ?? _selectedClip with
            {
                Title = title,
                Description = _clipDescriptionInput.Text.Trim()
            };
            RenderClipLibraryPage(_currentPage == "published");
        }
        catch (Exception ex) { await ShowErrorAsync("Could not save clip details", ex.Message); }
    }

    private async Task DeleteSelectedClipAsync()
    {
        if (_selectedClip is null) return;
        var name = _selectedClip.Name;
        var dialog = new ContentDialog
        {
            XamlRoot = XamlRoot,
            Title = "Delete this clip?",
            Content = "This permanently removes the MP4 and its matching caption/metadata file.",
            PrimaryButtonText = "Delete",
            CloseButtonText = "Cancel",
            DefaultButton = ContentDialogButton.Close
        };
        if (await ShowThemedDialogAsync(dialog) != ContentDialogResult.Primary) return;
        try
        {
            await PostAsync("/api/delete", new JsonObject { ["name"] = name });
            _selectedClip = null;
            await RefreshStateAsync(forceRender: true);
        }
        catch (Exception ex) { await ShowErrorAsync("Could not delete clip", ex.Message); }
    }

    private void NavigateToPublishingForClip(ClipItem? clip)
    {
        _bulkClipNames.Clear();
        _selectedClip = clip;
        NavigateTo("publishing");
    }
}
