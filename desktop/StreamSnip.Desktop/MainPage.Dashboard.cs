using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;

namespace StreamSnip_Desktop;

public sealed partial class MainPage
{
    private TextBlock? _dashboardClipCount;
    private TextBlock? _dashboardPublishedCount;
    private TextBlock? _dashboardCreatorCount;
    private TextBlock? _dashboardElapsed;
    private TextBlock? _dashboardCaptureTitle;
    private TextBlock? _dashboardCaptureSubtitle;
    private TextBlock? _dashboardCapturePillText;
    private Border? _dashboardCapturePill;
    private ProgressBar? _dashboardProgress;
    private StackPanel? _dashboardWorkflowHost;
    private StackPanel? _dashboardRecentHost;
    private StackPanel? _dashboardCreatorsHost;
    private StackPanel? _dashboardActivityHost;


    private static TextBlock ThemeText(string text, double size, bool strong, string brushKey)
    {
        var block = Txt(text, size, strong);
        block.Foreground = Application.Current.Resources[brushKey] as Brush ?? block.Foreground;
        return block;
    }

    private void RenderDashboardPage()
    {
        _dashboardClipCount = null;
        _dashboardPublishedCount = null;
        _dashboardCreatorCount = null;
        _dashboardElapsed = null;
        _dashboardCaptureTitle = null;
        _dashboardCaptureSubtitle = null;
        _dashboardCapturePillText = null;
        _dashboardCapturePill = null;
        _dashboardProgress = null;
        _dashboardWorkflowHost = null;
        _dashboardRecentHost = null;
        _dashboardCreatorsHost = null;
        _dashboardActivityHost = null;

        var state = _state ?? new EngineState();
        var activeCreators = _creators.Count(x => x.Running || x.CaptureActive);

        // Original StreamSnip page heading: title/description with one primary action.
        var heading = new Grid { ColumnSpacing = 18 };
        heading.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        heading.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        var headingCopy = new StackPanel { Spacing = 7 };
        headingCopy.Children.Add(Txt("Studio overview", 28, true));
        headingCopy.Children.Add(ThemeText(
            "Monitor sources, review the latest clips, and keep your workflow moving.",
            11, false, "MutedTextBrush"));
        heading.Children.Add(headingCopy);
        var headingAction = CreateButton("Open Live Studio", () => NavigateTo("live"), primary: true);
        headingAction.MinHeight = 38;
        Grid.SetColumn(headingAction, 1);
        heading.Children.Add(headingAction);
        PageHost.Children.Add(heading);

        // Four metrics share one bordered strip; they are not four separate cards.
        var summaryGrid = new Grid { Padding = new Thickness(3, 15, 3, 15) };
        for (var i = 0; i < 4; i++)
            summaryGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });

        var metrics = new[]
        {
            ("Ready to review", state.ClipTotal.ToString("N0"), "Unpublished clips"),
            ("Published", state.PostedTotal.ToString("N0"), "In your local registry"),
            ("Active creators", activeCreators.ToString("N0"), $"{_creators.Count:N0} configured"),
            ("Current session", FormatDuration(state.Session.Elapsed),
                $"{state.Session.Clips:N0} clips · {state.Session.Chunks:N0} chunks")
        };

        _dashboardClipCount = Txt(metrics[0].Item2, 22, true);
        _dashboardPublishedCount = Txt(metrics[1].Item2, 22, true);
        _dashboardCreatorCount = Txt(metrics[2].Item2, 22, true);
        _dashboardElapsed = Txt(metrics[3].Item2, 22, true);
        var values = new[] { _dashboardClipCount, _dashboardPublishedCount, _dashboardCreatorCount, _dashboardElapsed };

        for (var i = 0; i < metrics.Length; i++)
        {
            var stat = new StackPanel { Spacing = 3, Padding = new Thickness(18, 0, 18, 0) };
            stat.Children.Add(ThemeText(metrics[i].Item1, 11, false, "MutedTextBrush"));
            stat.Children.Add(values[i]!);
            stat.Children.Add(ThemeText(metrics[i].Item3, 10, false, "MutedTextBrush"));
            if (i > 0)
            {
                var divider = new Border
                {
                    Width = 1,
                    Background = Application.Current.Resources["LineBrush"] as Brush,
                    HorizontalAlignment = HorizontalAlignment.Left,
                    VerticalAlignment = VerticalAlignment.Stretch
                };
                Grid.SetColumn(divider, i);
                summaryGrid.Children.Add(divider);
            }
            Grid.SetColumn(stat, i);
            summaryGrid.Children.Add(stat);
        }

        var summary = new Border
        {
            Background = Application.Current.Resources["SurfaceBrush"] as Brush,
            BorderBrush = Application.Current.Resources["LineBrush"] as Brush,
            BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(12),
            Child = summaryGrid
        };
        PageHost.Children.Add(summary);

        // Main column: capture state and recent clips.
        var mainColumn = new StackPanel { Spacing = 17 };
        mainColumn.Children.Add(CreateCaptureStatusPanel(state));

        _dashboardRecentHost = new StackPanel { Spacing = 0 };
        PopulateRecentClips();
        mainColumn.Children.Add(CreatePanel(
            "Recent clips",
            "Latest output from your capture and VOD workflows.",
            _dashboardRecentHost));

        // Side column: creator activity, latest logs and the local-first information note.
        var sideColumn = new StackPanel { Spacing = 17 };
        _dashboardCreatorsHost = new StackPanel { Spacing = 0 };
        PopulateCreatorActivity();
        sideColumn.Children.Add(CreatePanel(
            "Creator activity",
            "Live Studio captures and background monitors.",
            _dashboardCreatorsHost));

        _dashboardActivityHost = new StackPanel { Spacing = 0 };
        PopulateRecentActivity();
        sideColumn.Children.Add(CreatePanel(
            "Latest activity",
            "Recent local engine events.",
            _dashboardActivityHost));

        var localNote = new Grid { ColumnSpacing = 10, Padding = new Thickness(13, 12, 14, 12) };
        localNote.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        localNote.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        var localIcon = new TextBlock
        {
            Text = "◆",
            FontSize = 15,
            Foreground = Application.Current.Resources["SuccessBrush"] as Brush,
            VerticalAlignment = VerticalAlignment.Top
        };
        localNote.Children.Add(localIcon);
        var localCopy = new StackPanel { Spacing = 3 };
        localCopy.Children.Add(Txt("Local-first processing", 11, true));
        localCopy.Children.Add(ThemeText(
            "Capture and rendering stay on this PC. Hosted AI providers receive transcript text when selected.",
            10, false, "MutedTextBrush"));
        Grid.SetColumn(localCopy, 1);
        localNote.Children.Add(localCopy);
        sideColumn.Children.Add(new Border
        {
            Background = Application.Current.Resources["SurfaceSoftBrush"] as Brush,
            BorderBrush = Application.Current.Resources["LineBrush"] as Brush,
            BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(9),
            Child = localNote
        });

        PageHost.Children.Add(AdaptiveColumns(mainColumn, sideColumn, 1.55, 0.9));
    }

    private Border CreateCaptureStatusPanel(EngineState state)
    {
        var content = new StackPanel { Spacing = 0 };
        var status = new Grid { ColumnSpacing = 13 };
        status.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(46) });
        status.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        status.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });

        var symbol = new Border
        {
            Width = 46,
            Height = 46,
            CornerRadius = new CornerRadius(11),
            Background = Application.Current.Resources[state.Running ? "SurfaceSoftBrush" : "SurfaceSoftBrush"] as Brush,
            Child = ThemeText("◉", 23, true, state.Running ? "AccentBrush" : "MutedTextBrush"),
            VerticalAlignment = VerticalAlignment.Center
        };
        status.Children.Add(symbol);

        var copy = new StackPanel { Spacing = 3, VerticalAlignment = VerticalAlignment.Center };
        _dashboardCaptureTitle = Txt(
            state.Running ? state.Status : "No active capture",
            13, true);
        _dashboardCaptureSubtitle = ThemeText(
            state.Running
                ? (state.Mode == "file" ? "Processing a video file" : "Recording a live stream") + " · " + FormatDuration(state.Session.Elapsed)
                : "Choose a live source or a recorded video to begin.",
            10, false, "MutedTextBrush");
        copy.Children.Add(_dashboardCaptureTitle);
        copy.Children.Add(_dashboardCaptureSubtitle);
        Grid.SetColumn(copy, 1);
        status.Children.Add(copy);

        var pill = MakeStatusPill(PhaseLabel(state.Phase), PhaseBrushKey(state));
        _dashboardCapturePill = pill;
        _dashboardCapturePillText = pill.Child as TextBlock;
        Grid.SetColumn(pill, 2);
        status.Children.Add(pill);
        content.Children.Add(status);

        _dashboardWorkflowHost = new StackPanel { Spacing = 0, Margin = new Thickness(0, 17, 0, 0) };
        PopulateWorkflowStrip(state);
        content.Children.Add(_dashboardWorkflowHost);

        if (state.Running)
        {
            var progressLabel = new Grid { Margin = new Thickness(0, 14, 0, 6) };
            progressLabel.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            progressLabel.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            progressLabel.Children.Add(ThemeText(state.Status, 10, false, "MutedTextBrush"));
            var percent = Txt($"{Math.Clamp(state.Progress, 0, 100)}%", 10, true);
            Grid.SetColumn(percent, 1);
            progressLabel.Children.Add(percent);
            content.Children.Add(progressLabel);

            _dashboardProgress = new ProgressBar
            {
                Minimum = 0,
                Maximum = 100,
                Value = Math.Clamp(state.Progress, 0, 100),
                Height = 5,
                Background = Application.Current.Resources["SurfaceSoftBrush"] as Brush,
                Foreground = Application.Current.Resources["AccentBrush"] as Brush
            };
            content.Children.Add(_dashboardProgress);
        }

        var action = CreateButton(
            state.Running ? "View session" : "Configure capture",
            () => NavigateTo("live"),
            primary: !state.Running);
        action.Margin = new Thickness(0, 14, 0, 0);
        content.Children.Add(action);

        return CreatePanel("Capture status", "Your local engine and current source.", content);
    }

    private void PopulateWorkflowStrip(EngineState state)
    {
        if (_dashboardWorkflowHost is null) return;
        _dashboardWorkflowHost.Children.Clear();

        var stages = new[]
        {
            ("Capture", new[] { "waiting", "recording", "stopping" }),
            ("Transcribe", new[] { "transcribing" }),
            ("Analyze", new[] { "analyzing" }),
            ("Render", new[] { "rendering" }),
            ("Publish", new[] { "queued" })
        };
        var activeIndex = Array.FindIndex(stages, stage => stage.Item2.Contains(state.Phase));
        var strip = new Grid { Padding = new Thickness(8, 12, 8, 9) };
        for (var i = 0; i < stages.Length; i++)
            strip.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        strip.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        strip.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });

        var track = new Border
        {
            Height = 1,
            Background = Application.Current.Resources["LineBrush"] as Brush,
            VerticalAlignment = VerticalAlignment.Center,
            Margin = new Thickness(10, 0, 10, 0)
        };
        Grid.SetColumnSpan(track, stages.Length);
        strip.Children.Add(track);

        for (var i = 0; i < stages.Length; i++)
        {
            var active = activeIndex == i;
            var passed = activeIndex > i;
            var stage = new StackPanel { Spacing = 7, HorizontalAlignment = HorizontalAlignment.Center };
            var circle = new Border
            {
                Width = 23,
                Height = 23,
                CornerRadius = new CornerRadius(99),
                Background = Application.Current.Resources[active ? "AccentBrush" : "SurfaceSoftBrush"] as Brush,
                BorderBrush = Application.Current.Resources[active ? "AccentBrush" : passed ? "SuccessBrush" : "LineBrush"] as Brush,
                BorderThickness = new Thickness(1),
                Child = ThemeText(passed ? "✓" : (i + 1).ToString(), 10, true,
                    active ? "AccentInkBrush" : passed ? "SuccessBrush" : "MutedTextBrush"),
                HorizontalAlignment = HorizontalAlignment.Center
            };
            stage.Children.Add(circle);
            stage.Children.Add(ThemeText(stages[i].Item1, 10, active || passed,
                passed ? "SuccessBrush" : active ? "PrimaryTextBrush" : "MutedTextBrush"));
            Grid.SetColumn(stage, i);
            Grid.SetRow(stage, 0);
            strip.Children.Add(stage);
        }

        if (!state.Running && activeIndex < 0)
        {
            var ready = ThemeText("Ready", 10, false, "MutedTextBrush");
            ready.HorizontalAlignment = HorizontalAlignment.Center;
            ready.Margin = new Thickness(0, 7, 0, 0);
            Grid.SetRow(ready, 1);
            Grid.SetColumnSpan(ready, stages.Length);
            strip.Children.Add(ready);
        }

        _dashboardWorkflowHost.Children.Add(new Border
        {
            Background = Application.Current.Resources["SurfaceSoftBrush"] as Brush,
            BorderBrush = Application.Current.Resources["LineBrush"] as Brush,
            BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(9),
            Child = strip
        });
    }

    private void PopulateRecentClips()
    {
        if (_dashboardRecentHost is null) return;
        _dashboardRecentHost.Children.Clear();
        var recent = _state?.Clips.Take(5).ToList() ?? [];

        if (recent.Count == 0)
        {
            var empty = new StackPanel
            {
                Spacing = 8,
                HorizontalAlignment = HorizontalAlignment.Center,
                VerticalAlignment = VerticalAlignment.Center,
                Padding = new Thickness(12, 22, 12, 22)
            };
            empty.Children.Add(ThemeText("▣", 22, true, "MutedTextBrush"));
            empty.Children.Add(Txt("No clips yet", 12, true));
            empty.Children.Add(ThemeText(
                "Generated clips appear here after the engine finds and renders a highlight.",
                10, false, "MutedTextBrush"));
            empty.Children.Add(CreateButton("Choose a source", () => NavigateTo("live")));
            _dashboardRecentHost.Children.Add(empty);
            return;
        }

        foreach (var clip in recent)
        {
            var row = new Grid { ColumnSpacing = 11, Padding = new Thickness(4, 11, 4, 11) };
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(34) });
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });

            var clipIcon = new Border
            {
                Width = 34,
                Height = 34,
                CornerRadius = new CornerRadius(8),
                Background = Application.Current.Resources["SurfaceSoftBrush"] as Brush,
                Child = ThemeText("▣", 17, true, "MutedTextBrush"),
                VerticalAlignment = VerticalAlignment.Center
            };
            row.Children.Add(clipIcon);

            var copy = new StackPanel { Spacing = 2, VerticalAlignment = VerticalAlignment.Center };
            copy.Children.Add(Txt(
                string.IsNullOrWhiteSpace(clip.Title) ? clip.Name : clip.Title,
                11, true));
            copy.Children.Add(ThemeText(
                $"{(string.IsNullOrWhiteSpace(clip.CreatorName) ? clip.Source : clip.CreatorName)} · {FormatClipDate(clip.ModifiedAt)}",
                10, false, "MutedTextBrush"));
            Grid.SetColumn(copy, 1);
            row.Children.Add(copy);

            var size = ThemeText(FormatSize(clip.SizeMb), 10, false, "MutedTextBrush");
            size.VerticalAlignment = VerticalAlignment.Center;
            Grid.SetColumn(size, 2);
            row.Children.Add(size);
            var arrow = ThemeText("↗", 14, false, "MutedTextBrush");
            arrow.VerticalAlignment = VerticalAlignment.Center;
            arrow.Margin = new Thickness(8, 0, 0, 0);
            Grid.SetColumn(arrow, 3);
            row.Children.Add(arrow);

            var button = new Button
            {
                Content = row,
                Background = new SolidColorBrush(ParseColor("#00000000")),
                BorderBrush = new SolidColorBrush(ParseColor("#00000000")),
                BorderThickness = new Thickness(0),
                Padding = new Thickness(0),
                HorizontalAlignment = HorizontalAlignment.Stretch,
                HorizontalContentAlignment = HorizontalAlignment.Stretch,
                MinHeight = 54
            };
            button.Click += (_, _) => OpenClipInLibrary(clip);
            _dashboardRecentHost.Children.Add(button);

            _dashboardRecentHost.Children.Add(new Border
            {
                Height = 1,
                Background = Application.Current.Resources["LineBrush"] as Brush,
                Margin = new Thickness(4, 0, 4, 0),
                Opacity = 0.7
            });
        }

        var open = CreateButton("Open library  ↗", () => NavigateTo("clips"));
        open.Margin = new Thickness(4, 7, 0, 0);
        _dashboardRecentHost.Children.Add(open);
    }

    private void PopulateCreatorActivity()
    {
        if (_dashboardCreatorsHost is null) return;
        _dashboardCreatorsHost.Children.Clear();
        var creators = _creators.Take(5).ToList();

        if (creators.Count == 0)
        {
            var empty = new StackPanel { Spacing = 8, Padding = new Thickness(8, 18, 8, 18) };
            empty.Children.Add(Txt("No creator sources", 12, true));
            empty.Children.Add(ThemeText("Add a channel to monitor live streams and recorded VODs.", 10, false, "MutedTextBrush"));
            empty.Children.Add(CreateButton("Add creator", () => NavigateTo("creators")));
            _dashboardCreatorsHost.Children.Add(empty);
            return;
        }

        foreach (var creator in creators)
        {
            var row = new Grid { ColumnSpacing = 9, Padding = new Thickness(0, 10, 0, 10) };
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(31) });
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });

            var initial = creator.Name.Trim().Length > 0
                ? creator.Name.Trim()[0].ToString().ToUpperInvariant()
                : "C";
            var avatar = new Border
            {
                Width = 31,
                Height = 31,
                CornerRadius = new CornerRadius(8),
                Background = Application.Current.Resources["SurfaceSoftBrush"] as Brush,
                Child = Txt(initial, 12, true),
                VerticalAlignment = VerticalAlignment.Center
            };
            row.Children.Add(avatar);

            var captureActive = creator.CaptureActive;
            var copy = new StackPanel { Spacing = 2, VerticalAlignment = VerticalAlignment.Center };
            copy.Children.Add(Txt(creator.Name, 11, true));
            copy.Children.Add(ThemeText(
                captureActive ? "Recording in Live Studio" : creator.Status.Length > 0 ? creator.Status : creator.Phase.Length > 0 ? creator.Phase : "Saved source",
                10, false, "MutedTextBrush"));
            Grid.SetColumn(copy, 1);
            row.Children.Add(copy);

            var active = creator.Running || captureActive;
            var pill = MakeStatusPill(
                captureActive ? "Recording" : creator.Running ? "Monitoring" : "Idle",
                active ? "AccentBrush" : "MutedTextBrush");
            Grid.SetColumn(pill, 2);
            row.Children.Add(pill);
            _dashboardCreatorsHost.Children.Add(row);
            _dashboardCreatorsHost.Children.Add(new Border
            {
                Height = 1,
                Background = Application.Current.Resources["LineBrush"] as Brush,
                Opacity = 0.7
            });
        }

        var manage = CreateButton("Manage  ↗", () => NavigateTo("creators"));
        manage.Margin = new Thickness(0, 7, 0, 0);
        _dashboardCreatorsHost.Children.Add(manage);
    }

    private void PopulateRecentActivity()
    {
        if (_dashboardActivityHost is null) return;
        _dashboardActivityHost.Children.Clear();
        var recent = _activity.TakeLast(6).Reverse().ToList();
        if (recent.Count == 0)
        {
            _dashboardActivityHost.Children.Add(ThemeText(
                "Engine events appear here when work begins.",
                10, false, "MutedTextBrush"));
            return;
        }

        foreach (var log in recent)
        {
            var row = new Grid { ColumnSpacing = 8, Padding = new Thickness(0, 8, 0, 8) };
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(55) });
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            row.Children.Add(ThemeText(log.Time, 10, false, "MutedTextBrush"));
            var message = ThemeText(log.Message, 10, false, "BodyTextBrush");
            Grid.SetColumn(message, 1);
            row.Children.Add(message);
            _dashboardActivityHost.Children.Add(row);
            _dashboardActivityHost.Children.Add(new Border
            {
                Height = 1,
                Background = Application.Current.Resources["LineBrush"] as Brush,
                Opacity = 0.7
            });
        }
        var full = CreateButton("Full activity  ↗", () => NavigateTo("activity"));
        full.Margin = new Thickness(0, 7, 0, 0);
        _dashboardActivityHost.Children.Add(full);
    }

    private void UpdateDashboardState()
    {
        if (_state is null) return;
        _dashboardClipCount?.SetValue(TextBlock.TextProperty, _state.ClipTotal.ToString("N0"));
        _dashboardPublishedCount?.SetValue(TextBlock.TextProperty, _state.PostedTotal.ToString("N0"));
        _dashboardCreatorCount?.SetValue(TextBlock.TextProperty,
            _creators.Count(x => x.Running || x.CaptureActive).ToString("N0"));
        _dashboardElapsed?.SetValue(TextBlock.TextProperty, FormatDuration(_state.Session.Elapsed));

        if (_dashboardCaptureTitle is not null)
            _dashboardCaptureTitle.Text = _state.Running ? _state.Status : "No active capture";
        if (_dashboardCaptureSubtitle is not null)
        {
            _dashboardCaptureSubtitle.Text = _state.Running
                ? (_state.Mode == "file" ? "Processing a video file" : "Recording a live stream") + " · " + FormatDuration(_state.Session.Elapsed)
                : "Choose a live source or a recorded video to begin.";
        }
        if (_dashboardCapturePillText is not null)
        {
            _dashboardCapturePillText.Text = PhaseLabel(_state.Phase);
            _dashboardCapturePillText.Foreground = Application.Current.Resources[PhaseBrushKey(_state)] as Brush;
        }
        if (_dashboardCapturePill is not null)
            _dashboardCapturePill.BorderBrush = Application.Current.Resources[PhaseBrushKey(_state)] as Brush;
        if (_dashboardProgress is not null)
        {
            _dashboardProgress.Value = Math.Clamp(_state.Progress, 0, 100);
        }

        PopulateWorkflowStrip(_state);
        PopulateRecentClips();
        PopulateCreatorActivity();
        PopulateRecentActivity();
    }

    private static string PhaseBrushKey(EngineState state)
    {
        if (state.Running)
            return state.Stopping ? "WarningBrush" : "AccentBrush";
        return state.Phase is "error" or "offline" ? "DangerBrush" : "SuccessBrush";
    }

    private static Border MakeStatusPill(string text, string brushKey)
    {
        var statusBrush = Application.Current.Resources[brushKey] as Brush
            ?? Application.Current.Resources["MutedTextBrush"] as Brush;
        return new Border
        {
            CornerRadius = new CornerRadius(99),
            Background = Application.Current.Resources["SurfaceSoftBrush"] as Brush,
            BorderBrush = statusBrush,
            BorderThickness = new Thickness(1),
            Padding = new Thickness(9, 4, 9, 4),
            Child = ThemeText(text, 10, true, brushKey),
            VerticalAlignment = VerticalAlignment.Center
        };
    }

    private static string PhaseLabel(string phase) => phase switch
    {
        "idle" => "Idle",
        "offline" => "Offline",
        "waiting" => "Connecting",
        "recording" => "Recording",
        "stopping" => "Stopping",
        "transcribing" => "Transcribing",
        "analyzing" => "Finding highlights",
        "rendering" => "Rendering clips",
        "queued" => "Queued",
        "done" => "Complete",
        "error" => "Error",
        _ => string.IsNullOrWhiteSpace(phase) ? "Idle" : phase.Replace('_', ' ').Replace('-', ' ')
    };

    private static string FormatDuration(int seconds)
    {
        var value = Math.Max(0, seconds);
        var hours = value / 3600;
        var minutes = (value % 3600) / 60;
        var remaining = value % 60;
        return hours > 0 ? $"{hours}h {minutes:00}m" : $"{minutes}m {remaining:00}s";
    }

    private static string FormatSize(double mb) =>
        mb >= 1024 ? $"{mb / 1024:0.0} GB" : $"{mb:0.0} MB";

    private static string FormatClipDate(double timestamp)
    {
        try
        {
            if (timestamp <= 0) return "Recently";
            return DateTimeOffset.FromUnixTimeSeconds((long)timestamp).ToLocalTime().ToString("MMM d, h:mm tt");
        }
        catch
        {
            return "Recently";
        }
    }

    private void OpenClipInLibrary(ClipItem clip)
    {
        _selectedClip = clip;
        _clipTab = "clips";
        NavigateTo("clips");
    }
}
