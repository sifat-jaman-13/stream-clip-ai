using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Text;
using Microsoft.UI.Xaml.Media;

namespace StreamSnip_Desktop;

public sealed partial class MainPage
{
    private TextBlock? _dashboardClipCount;
    private TextBlock? _dashboardScheduledCount;
    private TextBlock? _dashboardCreatorCount;
    private TextBlock? _dashboardElapsed;
    private TextBlock? _dashboardClipDetail;
    private TextBlock? _dashboardChunkDetail;
    private TextBlock? _dashboardProgressStatus;
    private TextBlock? _dashboardProgressPercent;
    private StackPanel? _dashboardSessionDetails;
    private Grid? _dashboardProgressRow;
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
        _dashboardScheduledCount = null;
        _dashboardCreatorCount = null;
        _dashboardElapsed = null;
        _dashboardClipDetail = null;
        _dashboardChunkDetail = null;
        _dashboardProgressStatus = null;
        _dashboardProgressPercent = null;
        _dashboardSessionDetails = null;
        _dashboardProgressRow = null;
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

        var heading = new Grid { ColumnSpacing = 24, Margin = new Thickness(0, 0, 0, 2) };
        heading.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        heading.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        var headingCopy = new StackPanel { Spacing = 8 };
        headingCopy.Children.Add(Txt("Dashboard", 28, true));
        headingCopy.Children.Add(ThemeText(
            "Your capture sessions, clip output and monitored creators.",
            13, false, "MutedTextBrush"));
        heading.Children.Add(headingCopy);

        var openStudio = CreateButton("Open Live Studio", () => NavigateTo("live"), primary: true);
        openStudio.MinWidth = 190;
        openStudio.VerticalAlignment = VerticalAlignment.Center;
        Grid.SetColumn(openStudio, 1);
        heading.Children.Add(openStudio);
        PageHost.Children.Add(heading);

        // One source-to-publish rundown replaces the vanity metric strip.
        PageHost.Children.Add(CreateSessionRundown(state));

        _dashboardRecentHost = new StackPanel { Spacing = 0 };
        PopulateRecentClips();
        var clipsPanel = CreatePanel(
            "Latest clips",
            "Rendered highlights ready for review.",
            _dashboardRecentHost);

        _dashboardCreatorsHost = new StackPanel { Spacing = 0 };
        PopulateCreatorActivity();
        var creatorsPanel = CreatePanel(
            "Creator monitors",
            "Live channels and background VOD watches.",
            _dashboardCreatorsHost);

        PageHost.Children.Add(AdaptiveColumns(clipsPanel, creatorsPanel, 1.7, 1.0));

        _dashboardActivityHost = new StackPanel { Spacing = 0 };
        PopulateRecentActivity();
        PageHost.Children.Add(CreatePanel(
            "Recent activity",
            "The latest messages from capture, processing and publishing.",
            _dashboardActivityHost));
    }

    private Border CreateSessionRundown(EngineState state)
    {
        var content = new StackPanel { Spacing = 0 };
        var engineReady = _engine is not null &&
            state.Phase is not ("offline" or "error");
        var statusBrushKey = !engineReady
            ? "DangerBrush"
            : state.Running
                ? state.Stopping ? "WarningBrush" : "AccentBrush"
                : "SuccessBrush";
        var statusLabel = !engineReady
            ? "Engine offline"
            : state.Running
                ? PhaseLabel(state.Phase)
                : "Ready";

        _dashboardCaptureTitle = Txt(
            state.Running
                ? state.Status
                : !engineReady ? "Local processing is unavailable" : "No active capture",
            16, true);
        _dashboardCaptureSubtitle = ThemeText(
            state.Running
                ? (state.Mode == "file" ? "Processing a video file" : "Recording a live stream")
                    + " · " + FormatDuration(state.Session.Elapsed)
                : !engineReady
                    ? "Repair the local engine before starting capture and rendering."
                    : "Choose a live stream or local video in Live Studio. Nothing records until you press Start capture.",
            13, false, "MutedTextBrush");

        var header = new Grid { ColumnSpacing = 22 };
        header.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        header.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });

        var copy = new StackPanel { Spacing = 7, VerticalAlignment = VerticalAlignment.Center };
        copy.Children.Add(_dashboardCaptureTitle);
        copy.Children.Add(_dashboardCaptureSubtitle);
        header.Children.Add(copy);

        var pill = MakeStatusPill(statusLabel, statusBrushKey);
        _dashboardCapturePill = pill;
        _dashboardCapturePillText = pill.Child as TextBlock;
        Grid.SetColumn(pill, 1);
        header.Children.Add(pill);
        content.Children.Add(header);

        _dashboardWorkflowHost = new StackPanel
        {
            Spacing = 0,
            Margin = new Thickness(0, 30, 0, 0)
        };
        PopulateWorkflowStrip(state);
        content.Children.Add(_dashboardWorkflowHost);

        _dashboardSessionDetails = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            Spacing = 22,
            Margin = new Thickness(0, 24, 0, 8),
            Visibility = state.Running ? Visibility.Visible : Visibility.Collapsed
        };
        _dashboardElapsed = ThemeText($"Elapsed  {FormatDuration(state.Session.Elapsed)}", 12.5, false, "BodyTextBrush");
        _dashboardClipDetail = ThemeText($"Clips  {state.Session.Clips:N0}", 12.5, false, "BodyTextBrush");
        _dashboardChunkDetail = ThemeText($"Chunks  {state.Session.Chunks:N0}", 12.5, false, "BodyTextBrush");
        _dashboardSessionDetails.Children.Add(_dashboardElapsed);
        _dashboardSessionDetails.Children.Add(_dashboardClipDetail);
        _dashboardSessionDetails.Children.Add(_dashboardChunkDetail);
        content.Children.Add(_dashboardSessionDetails);

        _dashboardProgressRow = new Grid
        {
            Margin = new Thickness(0, 4, 0, 0),
            Visibility = state.Running ? Visibility.Visible : Visibility.Collapsed
        };
        _dashboardProgressRow.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        _dashboardProgressRow.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        _dashboardProgressStatus = ThemeText(state.Status, 12, false, "MutedTextBrush");
        _dashboardProgressPercent = Txt($"{Math.Clamp(state.Progress, 0, 100)}%", 12, true);
        _dashboardProgressRow.Children.Add(_dashboardProgressStatus);
        Grid.SetColumn(_dashboardProgressPercent, 1);
        _dashboardProgressRow.Children.Add(_dashboardProgressPercent);
        content.Children.Add(_dashboardProgressRow);

        _dashboardProgress = new ProgressBar
        {
            Minimum = 0,
            Maximum = 100,
            Value = Math.Clamp(state.Progress, 0, 100),
            Height = 7,
            Margin = new Thickness(0, 8, 0, 0),
            Background = Application.Current.Resources["SurfaceSoftBrush"] as Brush,
            Foreground = Application.Current.Resources["AccentBrush"] as Brush,
            Visibility = state.Running ? Visibility.Visible : Visibility.Collapsed
        };
        content.Children.Add(_dashboardProgress);

        return CreatePanel(
            "Session rundown",
            "Follow the real source-to-clip path. Each stage changes only when the local engine reports progress.",
            content);
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
            Child = new FontIcon
            {
                Glyph = new string((char)0xE714, 1),
                FontFamily = new FontFamily("Segoe MDL2 Assets"),
                FontSize = 22,
                Width = 22,
                Height = 22,
                Foreground = Application.Current.Resources[state.Running ? "AccentBrush" : "MutedTextBrush"] as Brush
            },
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

        var engineReady = _engine is not null;
        var phase = (state.Phase ?? "idle").Trim().ToLowerInvariant();
        var hasSource = !string.IsNullOrWhiteSpace(SettingString("target"));
        var hasReviewableClips = state.ClipTotal > 0 || state.Session.Clips > 0;
        var postingComplete = state.Posting.Total > 0 &&
            state.Posting.Completed >= state.Posting.Total && !state.Posting.Active;

        var current = !engineReady ? -1 : state.Posting.Active ? 6 : phase switch
        {
            "waiting" or "recording" or "stopping" => 1,
            "transcribing" when state.Progress >= 100 ||
                state.Status.Contains("finding", StringComparison.OrdinalIgnoreCase) => 3,
            "transcribing" => 2,
            "rendering" => 4,
            "done" => hasReviewableClips ? 5 : 0,
            "error" => -2,
            _ when postingComplete => -3,
            _ when hasReviewableClips => 5,
            _ when hasSource => 1,
            _ => 0
        };

        var stages = new[]
        {
            (Name: "Source", Detail: hasSource ? "Source selected" : "Choose stream or VOD"),
            (Name: "Capture", Detail: "Live or local video"),
            (Name: "Transcribe", Detail: "Speech to text"),
            (Name: "Analyze", Detail: "Find highlights"),
            (Name: "Render", Detail: "Captioned clips"),
            (Name: "Review", Detail: "Edit title and details"),
            (Name: "Publish", Detail: "Manual approval")
        };

        var strip = new Grid
        {
            Padding = new Thickness(4, 14, 4, 4),
            RowSpacing = 10
        };
        for (var i = 0; i < stages.Length; i++)
            strip.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        strip.RowDefinitions.Add(new RowDefinition { Height = new GridLength(38) });
        strip.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        strip.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });

        var completedCount = current switch
        {
            >= 0 => current,
            -3 => stages.Length,
            _ => 0
        };

        var track = new Border
        {
            Height = 3,
            Background = Application.Current.Resources["LineBrush"] as Brush,
            VerticalAlignment = VerticalAlignment.Center,
            Margin = new Thickness(25, 0, 25, 0)
        };
        Grid.SetColumnSpan(track, stages.Length);
        Grid.SetRow(track, 0);
        strip.Children.Add(track);

        if (completedCount > 0)
        {
            var progressTrack = new Border
            {
                Height = 3,
                Background = Application.Current.Resources["SuccessBrush"] as Brush,
                VerticalAlignment = VerticalAlignment.Center,
                HorizontalAlignment = HorizontalAlignment.Left,
                Width = 0
            };
            void SizeProgress(double width) =>
                progressTrack.Width = Math.Max(0, width * completedCount / stages.Length);
            strip.SizeChanged += (_, args) => SizeProgress(args.NewSize.Width - 50);
            strip.Loaded += (_, _) => SizeProgress(strip.ActualWidth - 50);
            Grid.SetColumnSpan(progressTrack, stages.Length);
            Grid.SetRow(progressTrack, 0);
            strip.Children.Add(progressTrack);
        }

        for (var i = 0; i < stages.Length; i++)
        {
                var isUnavailable = !engineReady && i > 0;
            var isFailed = current == -2 && i == (phase == "rendering" ? 4 : phase == "transcribing" ? 2 : 1);
            var isComplete = i < completedCount || (!engineReady && i == 0 && hasSource);
            var isCurrent = i == current || (current == -2 && isFailed) ||
                (current == -1 && i == 0 && !hasSource);
            var tone = isUnavailable
                ? "MutedTextBrush"
                : isFailed ? "DangerBrush"
                : isComplete ? "SuccessBrush"
                : isCurrent ? "AccentBrush"
                : "MutedTextBrush";

            var marker = new Border
            {
                Width = 34,
                Height = 34,
                CornerRadius = new CornerRadius(17),
                Background = Application.Current.Resources[isCurrent ? "AccentSoftBrush" : "SurfaceSoftBrush"] as Brush,
                BorderBrush = Application.Current.Resources[tone] as Brush,
                BorderThickness = new Thickness(isCurrent ? 2 : 1),
                HorizontalAlignment = HorizontalAlignment.Center,
                VerticalAlignment = VerticalAlignment.Center,
                Child = new TextBlock
                {
                    Text = (i + 1).ToString(System.Globalization.CultureInfo.InvariantCulture),
                    FontFamily = CurrentFont,
                    FontSize = 15,
                    FontWeight = FontWeights.SemiBold,
                    Foreground = Application.Current.Resources[tone] as Brush,
                    HorizontalAlignment = HorizontalAlignment.Center,
                    VerticalAlignment = VerticalAlignment.Center
                }
            };
            Grid.SetColumn(marker, i);
            Grid.SetRow(marker, 0);
            strip.Children.Add(marker);

            var label = ThemeText(stages[i].Name, 15.5, isCurrent || isComplete,
                isCurrent ? "PrimaryTextBrush" : tone);
            label.HorizontalAlignment = HorizontalAlignment.Center;
            label.TextAlignment = TextAlignment.Center;
            label.TextTrimming = TextTrimming.CharacterEllipsis;
            Grid.SetColumn(label, i);
            Grid.SetRow(label, 1);
            strip.Children.Add(label);

            var detail = ThemeText(
                isUnavailable ? "Unavailable"
                : isFailed ? "Failed"
                : isComplete ? "Complete"
                : isCurrent ? StageCurrentDetail(i, state, hasSource, hasReviewableClips)
                : i == 6 ? "Manual approval"
                : "Waiting",
                13.5, isCurrent || isFailed, tone);
            detail.HorizontalAlignment = HorizontalAlignment.Center;
            detail.TextAlignment = TextAlignment.Center;
            detail.TextTrimming = TextTrimming.CharacterEllipsis;
            Grid.SetColumn(detail, i);
            Grid.SetRow(detail, 2);
            strip.Children.Add(detail);
        }

        _dashboardWorkflowHost.Children.Add(strip);
    }

    private static string StageCurrentDetail(int index, EngineState state, bool hasSource, bool hasReviewableClips) =>
        index switch
        {
            0 => hasSource ? "Selected" : "Choose a source",
            1 => state.Running ? PhaseLabel(state.Phase) : "Ready to start",
            2 => "Transcribing",
            3 => "Finding moments",
            4 => state.Status,
            5 => hasReviewableClips ? "Ready to review" : "Waiting for clips",
            6 => state.Posting.Current.Length > 0 ? state.Posting.Current : "Uploading",
            _ => "Waiting"
        };

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
            empty.Children.Add(new FontIcon
            {
                Glyph = new string((char)0xE714, 1),
                FontFamily = new FontFamily("Segoe MDL2 Assets"),
                FontSize = 22,
                Width = 28,
                Height = 28,
                Foreground = Application.Current.Resources["MutedTextBrush"] as Brush
            });
            empty.Children.Add(Txt("No clips yet", 12, true));
            empty.Children.Add(ThemeText(
                "Generated clips appear here after the engine finds and renders a highlight.",
                14, false, "BodyTextBrush"));
            empty.Children.Add(CreateButton("Choose a source", () => NavigateTo("live")));
            _dashboardRecentHost.Children.Add(empty);
            return;
        }

        foreach (var clip in recent)
        {
            var row = new Grid { ColumnSpacing = 11, Padding = new Thickness(4, 11, 4, 11) };
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(40) });
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });

            var clipIcon = new Border
            {
                Width = 40,
                Height = 40,
                CornerRadius = new CornerRadius(8),
                Background = Application.Current.Resources["SurfaceSoftBrush"] as Brush,
                Child = new FontIcon
                {
                    Glyph = new string((char)0xE714, 1),
                FontFamily = new FontFamily("Segoe MDL2 Assets"),
                FontSize = 22,
                    Width = 20,
                    Height = 20,
                    Foreground = Application.Current.Resources["MutedTextBrush"] as Brush
                },
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

        var open = CreateButton("Open clip library", () => NavigateTo("clips"));
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

        var manage = CreateButton("Manage creators", () => NavigateTo("creators"));
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
        _dashboardScheduledCount?.SetValue(TextBlock.TextProperty, _state.ScheduledTotal.ToString("N0"));
        _dashboardCreatorCount?.SetValue(TextBlock.TextProperty,
            _creators.Count(x => x.Running || x.CaptureActive).ToString("N0"));
        if (_dashboardElapsed is not null)
            _dashboardElapsed.Text = $"Elapsed  {FormatDuration(_state.Session.Elapsed)}";
        if (_dashboardClipDetail is not null)
            _dashboardClipDetail.Text = $"Clips  {_state.Session.Clips:N0}";
        if (_dashboardChunkDetail is not null)
            _dashboardChunkDetail.Text = $"Chunks  {_state.Session.Chunks:N0}";
        if (_dashboardSessionDetails is not null)
            _dashboardSessionDetails.Visibility = _state.Running ? Visibility.Visible : Visibility.Collapsed;
        if (_dashboardProgressRow is not null)
            _dashboardProgressRow.Visibility = _state.Running ? Visibility.Visible : Visibility.Collapsed;
        if (_dashboardProgressStatus is not null)
            _dashboardProgressStatus.Text = _state.Status;
        if (_dashboardProgressPercent is not null)
            _dashboardProgressPercent.Text = $"{Math.Clamp(_state.Progress, 0, 100)}%";

        if (_dashboardCaptureTitle is not null)
            _dashboardCaptureTitle.Text = _state.Running ? _state.Status :
                _engine is null ? "Local processing is unavailable" : "No active capture";
        if (_dashboardCaptureSubtitle is not null)
        {
            _dashboardCaptureSubtitle.Text = _state.Running
                ? (_state.Mode == "file" ? "Processing a video file" : "Recording a live stream") + " · " + FormatDuration(_state.Session.Elapsed)
                : _engine is null
                    ? "Repair the local engine before starting capture and rendering."
                    : "Choose a live stream or local video in Live Studio. Nothing records until you press Start capture.";
        }
        var currentPhaseBrush = _engine is null ? "DangerBrush" : PhaseBrushKey(_state);
        if (_dashboardCapturePillText is not null)
        {
            _dashboardCapturePillText.Text = _engine is null ? "Offline" : PhaseLabel(_state.Phase);
            _dashboardCapturePillText.Foreground = Application.Current.Resources[currentPhaseBrush] as Brush;
        }
        if (_dashboardCapturePill is not null)
            _dashboardCapturePill.BorderBrush = Application.Current.Resources[currentPhaseBrush] as Brush;
        if (_dashboardProgress is not null)
        {
            _dashboardProgress.Value = Math.Clamp(_state.Progress, 0, 100);
            _dashboardProgress.Visibility = _state.Running ? Visibility.Visible : Visibility.Collapsed;
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
