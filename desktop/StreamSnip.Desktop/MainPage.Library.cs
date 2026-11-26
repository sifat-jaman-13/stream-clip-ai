using System.Text.Json.Nodes;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Windows.Media.Core;

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
    private TextBlock? _clipLibraryCount;
    private TextBlock? _clipPageInfo;
    private Button? _clipPreviousButton;
    private Button? _clipNextButton;
    private TextBox? _clipSearchInput;
    private bool _clipPublished;

    private void RenderClipLibraryPage(bool published)
    {
        _clipPublished = published;
        _clipTab = published ? "posted" : "clips";
        AddPageHeading(
            published ? "Published" : "Clip library",
            published
                ? "Clips recorded in your local posted registry."
                : "Review generated clips, edit their post metadata, and prepare publishing.");

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
        var actions = ActionRow(
            CreateButton("Ready to review", () => NavigateTo("clips"), primary: !published),
            CreateButton("Published", () => NavigateTo("published"), primary: published),
            CreateButton("Open clips folder", async () =>
            {
                try { await PostAsync("/api/open_folder", new JsonObject()); }
                catch (Exception ex) { await ShowErrorAsync("Could not open clips folder", ex.Message); }
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

        var layout = new Grid { ColumnSpacing = 15 };
        layout.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1.25, GridUnitType.Star) });
        layout.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        layout.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        layout.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });

        var listPanel = new StackPanel { Spacing = 10 };
        var currentTotal = published ? (_state?.PostedTotal ?? 0) : (_state?.ClipTotal ?? 0);
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
        var total = published ? (_state?.PostedTotal ?? 0) : (_state?.ClipTotal ?? 0);
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

        var preview = new StackPanel { Spacing = 10 };
        if (_selectedClip is null)
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
            emptyPreviewContent.Children.Add(new FontIcon
            {
                Glyph = new string((char)0xE714, 1),
                FontFamily = new FontFamily("Segoe MDL2 Assets"),
                FontSize = 22,
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
            preview.Children.Add(Txt("Clip preview", 13, true));
            _clipPlayer = new MediaPlayerElement
            {
                AreTransportControlsEnabled = true,
                AutoPlay = false,
                MinHeight = 235,
                MaxHeight = 360,
                Stretch = Stretch.Uniform
            };
            if (_engine?.BaseAddress is Uri baseAddress)
            {
                var clipUri = new Uri(baseAddress, "clips/" + Uri.EscapeDataString(_selectedClip.Name));
                _clipPlayer.Source = MediaSource.CreateFromUri(clipUri);
            }
            preview.Children.Add(_clipPlayer);
            preview.Children.Add(ThemeText(_selectedClip.Name, 10, false, "MutedTextBrush"));

            _clipTitleInput = Input(
                string.IsNullOrWhiteSpace(_selectedClip.Title) ? _selectedClip.Name : _selectedClip.Title,
                "Post title");
            AddLabeled(preview, "Post title", _clipTitleInput);
            _clipDescriptionInput = Input(_selectedClip.Description, "Post description", multiline: true);
            AddLabeled(preview, "Post description", _clipDescriptionInput);

            var previewActions = new StackPanel { Spacing = 8 };
            previewActions.Children.Add(ActionRow(
                CreateButton("Save details", async () => await SaveSelectedClipMetadataAsync(), primary: true),
                CreateButton("Publish", () => NavigateToPublishingForClip(_selectedClip), primary: false)));
            previewActions.Children.Add(ActionRow(
                CreateButton("Show in folder", async () =>
                {
                    try { await PostAsync("/api/reveal", new JsonObject { ["name"] = _selectedClip.Name }); }
                    catch (Exception ex) { await ShowErrorAsync("Could not reveal clip", ex.Message); }
                }),
                CreateButton("Delete clip", async () => await DeleteSelectedClipAsync(), danger: true)));
            preview.Children.Add(previewActions);
        }

        var listSection = CreatePanel(
            published ? "Published clips" : "Ready to review",
            "Your newest MP4 files and their TXT-backed post metadata.",
            listPanel);
        var inspector = CreatePanel("Inspector", "Native Windows video preview and editable post metadata.", preview);
        layout.Children.Add(listSection);
        layout.Children.Add(inspector);

        void ApplyLibraryBreakpoint(double width)
        {
            var stacked = width < 860;
            layout.ColumnSpacing = stacked ? 0 : 15;
            layout.RowSpacing = stacked ? 16 : 0;
            Grid.SetColumn(listSection, 0);
            Grid.SetRow(listSection, 0);
            Grid.SetColumnSpan(listSection, stacked ? 2 : 1);
            Grid.SetColumn(inspector, stacked ? 0 : 1);
            Grid.SetRow(inspector, stacked ? 1 : 0);
            Grid.SetColumnSpan(inspector, stacked ? 2 : 1);
        }

        layout.SizeChanged += (_, args) => ApplyLibraryBreakpoint(args.NewSize.Width);
        layout.Loaded += (_, _) => ApplyLibraryBreakpoint(layout.ActualWidth);
        PageHost.Children.Add(layout);
    }

    private StackPanel? _clipRowsHost;

    private void UpdateClipLibraryState()
    {
        if (_clipRowsHost is null) return;
        var published = _clipPublished;
        var total = published ? (_state?.PostedTotal ?? 0) : (_state?.ClipTotal ?? 0);
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
        RefreshClipRows(published);
    }

    private void RefreshClipRows(bool published)
    {
        if (_clipRowsHost is null) return;
        _clipRowsHost.Children.Clear();
        var clips = _state?.Clips ?? [];
        var filtered = clips.Where(clip =>
            string.IsNullOrWhiteSpace(_clipSearch) ||
            $"{clip.Title} {clip.Name} {clip.CreatorName} {clip.Source}"
                .Contains(_clipSearch, StringComparison.CurrentCultureIgnoreCase)).ToList();

        if (filtered.Count == 0)
        {
            _clipRowsHost.Children.Add(Txt(
                string.IsNullOrWhiteSpace(_clipSearch)
                    ? published ? "Nothing has been published yet." : "Your clip library is empty."
                    : "No clips match this search.",
                11, true));
            _clipRowsHost.Children.Add(ThemeText(
                "Clips appear here after the engine finishes rendering a highlight.",
                10, false, "MutedTextBrush"));
            return;
        }

        foreach (var clip in filtered)
        {
            var selected = _selectedClip?.Name == clip.Name;
            var copy = new StackPanel { Spacing = 3 };
            copy.Children.Add(Txt(
                string.IsNullOrWhiteSpace(clip.Title) ? clip.Name : clip.Title,
                10, true));
            copy.Children.Add(ThemeText(
                $"{(string.IsNullOrWhiteSpace(clip.CreatorName) ? clip.Source : clip.CreatorName)}  ·  {FormatSize(clip.SizeMb)}",
                10, false, "MutedTextBrush"));
            copy.Children.Add(ThemeText(FormatClipDate(clip.ModifiedAt), 10, false, "MutedTextBrush"));

            var choose = new Button
            {
                Content = copy,
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
                _selectedClip = clip;
                RenderClipLibraryPage(published);
            };
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
            row.Children.Add(selectedCheck);
            Grid.SetColumn(choose, 1);
            row.Children.Add(choose);
            _clipRowsHost.Children.Add(row);
        }
        UpdateClipSelectionBar();
        UpdateClipSelectPageCheck(filtered);
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
        if (await dialog.ShowAsync() != ContentDialogResult.Primary) return;
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
        var count = published ? (_state?.PostedTotal ?? 0) : (_state?.ClipTotal ?? 0);
        if (count <= 0) return;
        var tab = published ? "posted" : "clips";
        var dialog = new ContentDialog
        {
            XamlRoot = XamlRoot,
            Title = $"Delete all {count:N0} {(published ? "published" : "ready")} clip(s)?",
            Content = "This permanently removes every MP4 and matching metadata file in this tab. This cannot be undone.",
            PrimaryButtonText = "Delete all",
            CloseButtonText = "Cancel",
            DefaultButton = ContentDialogButton.Close
        };
        if (await dialog.ShowAsync() != ContentDialogResult.Primary) return;
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
        if (await dialog.ShowAsync() != ContentDialogResult.Primary) return;
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
