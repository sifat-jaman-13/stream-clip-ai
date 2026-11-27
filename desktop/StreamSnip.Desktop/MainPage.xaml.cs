using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Runtime.CompilerServices;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.UI;
using Microsoft.UI.Text;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Controls.Primitives;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml.Shapes;
using Windows.Foundation;
using WinRT.Interop;
using Windows.Media.Core;
using Windows.Storage;
using Windows.Storage.Pickers;
using Windows.UI;

namespace StreamSnip_Desktop;

public sealed partial class MainPage : Page
{











































	private sealed record ThemePalette(string Id, string Name, string App, string Surface, string Soft, string Hover, string Sidebar, string Ink, string Body, string Muted, string Line, string Accent, string Success, string Warning, string Danger)
	{
        public string PrimaryText => EnsureTextContrastAcross(Ink, 7.0, App, Surface, Soft, Hover);
        public string BodyText => EnsureTextContrastAcross(Body, 4.5, App, Surface, Soft, Hover);
        public string MutedText => EnsureTextContrastAcross(Muted, 4.5, App, Surface, Soft, Hover);
        public bool IsLight => Id is "studio-light" or "odysseas" or "solarized";
        public string SidebarSurface => Id == "odysseas" ? "#3A5868" : Soft;
        public string SidebarInk => EnsureTextContrastAcross(Id == "odysseas" ? "#F7F9F8" : Ink, 7.0, Sidebar, SidebarSurface);
        public string SidebarBody => EnsureTextContrastAcross(Id == "odysseas" ? "#E0E8E5" : Body, 4.5, Sidebar, SidebarSurface);
        public string SidebarMuted => EnsureTextContrastAcross(Id == "odysseas" ? "#C9D6D1" : Muted, 4.5, Sidebar, SidebarSurface);
        public string SidebarLine => EnsureTextContrastAcross(Id == "odysseas" ? "#7F9BA6" : Line, 3.0, Sidebar, SidebarSurface);
        public string SidebarAccentBorder => EnsureTextContrastAcross(Accent, 3.0, Sidebar, SidebarSurface);
        public string SidebarAccentText => EnsureTextContrastAcross(Accent, 4.5, Sidebar, SidebarSurface);
        public string AccentText => EnsureTextContrastAcross(Accent, 4.5, App, Surface, Soft, Hover);
        public string SuccessText => EnsureTextContrastAcross(Success, 4.5, App, Surface, Soft, Hover);
        public string WarningText => EnsureTextContrastAcross(Warning, 4.5, App, Surface, Soft, Hover);
        public string DangerText => EnsureTextContrastAcross(Danger, 4.5, App, Surface, Soft, Hover);
    }

	private enum EngineIndicator
	{
		Success,
		Warning,
		Danger
	}

	private static readonly JsonSerializerOptions JsonOptions = new JsonSerializerOptions
	{
		PropertyNameCaseInsensitive = true
	};

	private EngineSupervisor? _engine;
	private UIElement? _engineNotice;

	private EngineSettings? _settings;

	private JsonObject? _globalSettings;

	private EngineState? _state;

	private List<CreatorItem> _creators = new List<CreatorItem>();

	private readonly List<LogItem> _activity = new List<LogItem>();

	private readonly CancellationTokenSource _shutdown = new CancellationTokenSource();

	private CancellationTokenSource? _eventsCancellation;

	private string _currentPage = "overview";

	private string _clipTab = "clips";

	private string _clipSearch = "";

	private int _clipOffset;

	private long _lastLogId;
	private long _activityPageRenderedLastLogId = -1;

	private bool _loaded;

	private bool _quitting;

	private const string DefaultFontUri = "ms-appx:///Assets/Fonts/JetBrainsMono-Variable.ttf#JetBrains Mono";

	private static readonly FontFamily DefaultFontFamily = new FontFamily(DefaultFontUri);

	private static FontFamily ActiveFontFamily = DefaultFontFamily;

	private bool _refreshRunning;

	private string _theme = "studio-dark";
	private string _customAccent = "";

	private string _fontName = "JetBrains Mono";
	private string _fontSize = "medium";
	private static double _applicationFontScale = 1.0;

	private sealed class FontSizeBaseline(double value)
	{
		public double Value { get; } = value;
	}

	private static readonly ConditionalWeakTable<FrameworkElement, FontSizeBaseline> FontSizeBaselines = new();
	private static readonly ConditionalWeakTable<FrameworkElement, object> FontLoadHandlers = new();

	private string _lastEngineMessage = "";
	private Border? _clipBadgeBorder;
	private TextBlock? _clipBadgeText;
	private Border? _creatorBadgeBorder;
	private TextBlock? _creatorBadgeText;

	private readonly string _preferencesPath = System.IO.Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "StreamSnip AI", "desktop-preferences.json");

	private static readonly ThemePalette[] Themes = new ThemePalette[12]
	{
		new ThemePalette("studio-dark", "Studio Dark", "#0F0F0F", "#181818", "#212121", "#2B2B2B", "#0F0F0F", "#F1F1F1", "#D6D6D6", "#AAAAAA", "#303030", "#FF0033", "#81C995", "#F6C26B", "#F28B82"),
		new ThemePalette("odysseus", "Odysseus", "#282C34", "#1B2028", "#232B35", "#2D3743", "#171C23", "#E8F0F4", "#C8D5DC", "#9CDEF2", "#355A66", "#E06C75", "#80C99A", "#E6B96F", "#F28B82"),
		new ThemePalette("studio-light", "Studio Light", "#F3F5F8", "#FFFFFF", "#E8EDF3", "#DDE5EE", "#E9EEF4", "#172A3B", "#40576C", "#4E657A", "#CAD5E0", "#B42318", "#176747", "#794D00", "#A52B24"),
		new ThemePalette("github", "GitHub Dark", "#0D1117", "#161B22", "#21262D", "#292F38", "#010409", "#E6EDF3", "#C9D1D9", "#8B949E", "#30363D", "#F85149", "#3FB950", "#D29922", "#FF7B72"),
		new ThemePalette("nord", "Nord", "#2E3440", "#3B4252", "#434C5E", "#4C566A", "#2E3440", "#ECEFF4", "#D8DEE9", "#88C0D0", "#4C566A", "#88C0D0", "#A3BE8C", "#EBCB8B", "#BF616A"),
		new ThemePalette("odysseas", "Odysseus Paper", "#EEF2EF", "#FAFCFA", "#E3EBE6", "#D7E2DB", "#243B49", "#1C3038", "#40555C", "#485F61", "#CBD8D0", "#A3452D", "#28664E", "#79500C", "#9D4038"),
		new ThemePalette("ocean", "Ocean Depths", "#101C27", "#162635", "#1E3242", "#294153", "#0C1721", "#EDF5FA", "#C5D4DE", "#9AB3C1", "#2D4656", "#42B9CC", "#83C99A", "#E4BF72", "#E9877F"),
		new ThemePalette("forest", "Forest Night", "#111B17", "#182720", "#22352B", "#30483A", "#0C1511", "#EAF4ED", "#C5D8CA", "#9CBAA4", "#2E4737", "#83C99A", "#6DAF83", "#E4BD69", "#E9857B"),
		new ThemePalette("solarized", "Solarized Paper", "#F2EEDF", "#FFFCF3", "#EAE4D2", "#DCD3BC", "#E6DEC9", "#273B3A", "#445852", "#4A5F58", "#CFC4A7", "#17635E", "#286346", "#7B510C", "#9D392F"),
		new ThemePalette("rose-graphite", "Rose Graphite", "#211C20", "#2C242A", "#362B33", "#463640", "#1A1519", "#F4EDF0", "#DBCBD3", "#C39DAB", "#49353F", "#DD8EA4", "#8ABF9A", "#E2B36E", "#EF8790"),
		new ThemePalette("ember", "Ember Studio", "#1D1A16", "#28231D", "#332C23", "#41362A", "#17130F", "#F2EDE5", "#D7C9B7", "#BCA588", "#4A3B2A", "#E8A34B", "#99C68C", "#F0C674", "#E57D68"),
		new ThemePalette("slate", "Slate Studio", "#20262D", "#272F38", "#313B45", "#3D4853", "#181E24", "#EEF2F5", "#CAD2D9", "#AAB7C2", "#3C4853", "#8BB9D8", "#8EC7A1", "#E0BC77", "#E28B85")
	};

	private static readonly string[] FontChoices =
	[
		"JetBrains Mono", "Manrope", "DM Sans", "Inter", "Open Sans", "IBM Plex Sans", "Nunito Sans",
		"Roboto", "Source Sans 3", "Poppins", "Lato", "Fira Code", "Segoe UI", "Consolas",
		"Aptos", "Arial", "Tahoma", "Verdana", "Georgia", "Trebuchet MS", "Times New Roman"
	];

	private FontFamily CurrentFont => ActiveFontFamily;







































	public MainPage()
	{
		InitializeComponent();
        SearchQueryIcon.Data = CreateSearchIconGeometry();
		Loaded += Page_Loaded;
		Unloaded += Page_Unloaded;
		LoadPreferences();
        // RequestedTheme is a construction-time WinUI setting. Select it once
        // before the page enters the visual tree; runtime palette changes only
        // replace the live theme brushes in both theme dictionaries.
        var initialPalette = Themes.FirstOrDefault(item => item.Id == _theme) ?? Themes[0];
        RequestedTheme = initialPalette.IsLight ? ElementTheme.Light : ElementTheme.Dark;
		ApplyTheme(_theme);
		ApplyFont(_fontName);
		InitializeNavigationBadges();
		RegisterSearchShortcuts();
	}

	private static PathGeometry CreateSearchIconGeometry()
    {
        var geometry = new PathGeometry { FillRule = FillRule.EvenOdd };
        var outer = new PathFigure { StartPoint = new Point(9.5, 2.5), IsClosed = true };
        foreach (var point in new[]
        {
            new Point(12.2, 3.04), new Point(14.45, 4.55), new Point(15.96, 6.8),
            new Point(16.5, 9.5), new Point(15.96, 12.2), new Point(14.45, 14.45),
            new Point(12.2, 15.96), new Point(9.5, 16.5), new Point(6.8, 15.96),
            new Point(4.55, 14.45), new Point(3.04, 12.2), new Point(2.5, 9.5),
            new Point(3.04, 6.8), new Point(4.55, 4.55), new Point(6.8, 3.04)
        })
            outer.Segments.Add(new LineSegment { Point = point });
        geometry.Figures.Add(outer);

        var inner = new PathFigure { StartPoint = new Point(9.5, 4.7), IsClosed = true };
        foreach (var point in new[]
        {
            new Point(11.9, 5.35), new Point(13.65, 7.1), new Point(14.3, 9.5),
            new Point(13.65, 11.9), new Point(11.9, 13.65), new Point(9.5, 14.3),
            new Point(7.1, 13.65), new Point(5.35, 11.9), new Point(4.7, 9.5),
            new Point(5.35, 7.1), new Point(7.1, 5.35)
        })
            inner.Segments.Add(new LineSegment { Point = point });
        geometry.Figures.Add(inner);

        var handle = new PathFigure { StartPoint = new Point(14, 13), IsClosed = true };
        foreach (var point in new[]
        {
            new Point(15.6, 14.4), new Point(21.3, 20.1), new Point(20.1, 21.3),
            new Point(14.4, 15.6), new Point(13, 14)
        })
            handle.Segments.Add(new LineSegment { Point = point });
        geometry.Figures.Add(handle);
        return geometry;
    }

    private static PathGeometry CreateVideoIconGeometry()
    {
        var geometry = new PathGeometry();
        var body = new PathFigure { StartPoint = new Point(4, 5), IsClosed = true };
        foreach (var point in new[]
        {
            new Point(14, 5), new Point(16, 7), new Point(16, 17),
            new Point(14, 19), new Point(4, 19), new Point(2, 17), new Point(2, 7)
        })
            body.Segments.Add(new LineSegment { Point = point });
        geometry.Figures.Add(body);

        var lens = new PathFigure { StartPoint = new Point(16, 9), IsClosed = true };
        foreach (var point in new[] { new Point(22, 6), new Point(22, 18), new Point(16, 15) })
            lens.Segments.Add(new LineSegment { Point = point });
        geometry.Figures.Add(lens);
        return geometry;
    }

	private async void Page_Loaded(object sender, RoutedEventArgs e)
	{
		ApplyFontToVisualTree(this);
		var currentPalette = Themes.FirstOrDefault(item => item.Id == _theme) ?? Themes[0];
		UpdateWindowTitleBar(currentPalette, IsValidAccent(_customAccent) ? _customAccent : currentPalette.Accent);
		UpdateSidebarSelection();
		if (!_loaded)
		{
			_loaded = true;
			await StartEngineAsync();
		}
	}

	private async Task StartEngineAsync()
	{
		SetEngineIndicator("Starting local engine…", EngineIndicator.Warning);
		try
		{
			_engine = await EngineSupervisor.StartAsync(_shutdown.Token);
			_engine.OutputReceived += Engine_OutputReceived;
			_engine.ProcessExited += Engine_ProcessExited;
			SetEngineIndicator("Connected", EngineIndicator.Success);
			FooterEngineText.Text = "Local Python engine";
			await LoadWorkspaceAsync();
			StartEventListener();

			if (_engineNotice is not null)
			{
				PageHost.Children.Remove(_engineNotice);
				_engineNotice = null;
			}
			RenderCurrentPage();
		}
		catch (Exception ex)
		{
			SetEngineIndicator("Engine unavailable", EngineIndicator.Danger);
			FooterEngineText.Text = "Engine not available";

			// Keep the workspace usable; engine recovery must not replace the page.
			PageHost.Children.Clear();
			RenderCurrentPage();
			_engineNotice = CreateEngineUnavailableNotice(ex.Message);
			PageHost.Children.Insert(0, _engineNotice);
		}
	}

	private Border CreateEngineUnavailableNotice(string detail)
	{
		var message = detail.Contains("pyvenv.cfg", StringComparison.OrdinalIgnoreCase)
			? "The installed Python environment is missing pyvenv.cfg. Repair the local runtime to restore capture and rendering."
			: detail;

		var copy = new StackPanel { Spacing = 5 };
		copy.Children.Add(Txt("LOCAL ENGINE UNAVAILABLE", 11, true, "DangerBrush"));
		copy.Children.Add(Txt(message, 12.5, false, "BodyTextBrush"));

		var actions = ActionRow(
			CreateButton("Retry engine", async () => await RetryEngineAsync(), primary: true),
			CreateButton("Open runtime folder", async () =>
			{
				var runtimePath = System.IO.Path.Combine(
					Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
					"Programs", "StreamSnip AI Native", "runtime");
				await OpenPath(runtimePath);
			}));

		var layout = new Grid { ColumnSpacing = 22, VerticalAlignment = VerticalAlignment.Center };
		layout.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
		layout.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
		layout.Children.Add(copy);
		Grid.SetColumn(actions, 1);
		layout.Children.Add(actions);

		return new Border
		{
			Background = Application.Current.Resources["SurfaceSoftBrush"] as Brush,
			BorderBrush = Application.Current.Resources["DangerBrush"] as Brush,
			BorderThickness = new Thickness(1),
			CornerRadius = new CornerRadius(8),
			Padding = new Thickness(18, 14, 18, 14),
			Child = layout
		};
	}

	private async Task RetryEngineAsync()
	{
		if (_engine != null)
		{
			await _engine.DisposeAsync();
			_engine = null;
		}
		await StartEngineAsync();
	}

	private async void Page_Unloaded(object sender, RoutedEventArgs e)
	{
		_eventsCancellation?.Cancel();
		_shutdown.Cancel();
		if (_engine != null)
		{
			try
			{
				await _engine.QuitAsync();
			}
			catch
			{
			}
			await _engine.DisposeAsync();
			_engine = null;
		}
	}

	private async void Engine_OutputReceived(object? sender, string line)
	{
		if (string.IsNullOrWhiteSpace(line))
		{
			return;
		}
		await RunOnUIAsync(() =>
		{
			_lastEngineMessage = line;
			if (line.Contains("running at http://127.0.0.1", StringComparison.OrdinalIgnoreCase))
			{
				SetEngineIndicator("Connected", EngineIndicator.Success);
			}
		});
	}

	private async void Engine_ProcessExited(object? sender, int? exitCode)
	{
		await RunOnUIAsync(() =>
		{
			SetEngineIndicator("Engine stopped", EngineIndicator.Danger);
			FooterEngineText.Text = "Engine stopped · exit " + (exitCode?.ToString(CultureInfo.InvariantCulture) ?? "unknown");
		});
	}

	private async Task LoadWorkspaceAsync()
	{
		if (_engine == null)
		{
			throw new InvalidOperationException("The engine client is unavailable.");
		}
		_settings = EngineSettings.FromResponse(await _engine.GetJsonAsync("/api/config", _shutdown.Token));
		_globalSettings = _settings.Values.DeepClone() as JsonObject ?? new JsonObject();
		await RefreshStateAsync();
		await RefreshCreatorsAsync();
		SetEngineIndicator("Connected", EngineIndicator.Success);
	}

	private async Task RefreshStateAsync(bool forceRender = false)
	{
		if (_engine == null || _refreshRunning)
		{
			return;
		}
		_refreshRunning = true;
		try
		{
			long since = _state?.LastId ?? _lastLogId;
			string currentPage = _currentPage;
			bool flag = ((currentPage == "clips" || currentPage == "published") ? true : false);
			int offset = (flag ? _clipOffset : 0);
			string tab = ((_currentPage == "published") ? "scheduled" : _clipTab);
			foreach (LogItem item in (_state = JsonSerializer.Deserialize<EngineState>((await _engine.GetJsonAsync($"/api/state?since={since}&clip_offset={offset}&clip_tab={tab}", _shutdown.Token)).ToJsonString(), JsonOptions) ?? new EngineState()).Logs.OrderBy((LogItem x) => x.Id))
			{
				if (item.Id > _lastLogId)
				{
					_activity.Add(item);
					_lastLogId = Math.Max(_lastLogId, item.Id);
				}
			}
			if (_activity.Count > 500)
			{
				_activity.RemoveRange(0, _activity.Count - 500);
			}
			UpdateEngineIndicator();
			UpdateSidebarBadges();
			if (forceRender && _currentPage != "activity")
			{
				RenderCurrentPage();
			}
			else
			{
				UpdateVisiblePageState();
			}
		}
		catch (OperationCanceledException) when (_shutdown.IsCancellationRequested)
		{
		}
		catch (Exception ex2)
		{
			Exception ex3 = ex2;
			SetEngineIndicator("Reconnecting", EngineIndicator.Warning);
			_lastEngineMessage = ex3.Message;
		}
		finally
		{
			_refreshRunning = false;
		}
	}

	private async Task RefreshCreatorsAsync()
	{
		if (_engine != null)
		{
			JsonObject response = await _engine.GetJsonAsync("/api/creators", _shutdown.Token);
			MainPage mainPage = this;
			JsonNode? jsonNode = response["creators"];
			mainPage._creators = ((jsonNode != null) ? jsonNode.Deserialize<List<CreatorItem>>(JsonOptions) : null) ?? new List<CreatorItem>();
			UpdateSidebarBadges();
		}
	}

	private void StartEventListener()
	{
		if (_engine == null)
			return;

		_eventsCancellation?.Cancel();
		_eventsCancellation = CancellationTokenSource.CreateLinkedTokenSource(_shutdown.Token);
		var token = _eventsCancellation.Token;

		_ = Task.Run(async () =>
		{
			try
			{
				using var timer = new PeriodicTimer(TimeSpan.FromMilliseconds(1800));
				var tick = 0;
				while (await timer.WaitForNextTickAsync(token).ConfigureAwait(false))
				{
					tick++;
					var refreshCreators = true;
					if (!DispatcherQueue.TryEnqueue(() =>
					{
						_ = RefreshStateAsync();
						if (refreshCreators)
							_ = RefreshCreatorsForPollingAsync();
					}))
						break;
				}
			}
			catch (OperationCanceledException) when (token.IsCancellationRequested)
			{
			}
		}, token);
	}

	private async Task RefreshCreatorsForPollingAsync()
	{
		try
		{
			var previous = _creators.ToArray();
			await RefreshCreatorsAsync();
			var changed = !previous.SequenceEqual(_creators);
			UpdateSidebarBadges();
			if (changed && _currentPage == "creators")
				RenderCurrentPage();
			else if (changed && _currentPage == "live")
				UpdateLiveCreatorRows();
		}
		catch (OperationCanceledException) when (_shutdown.IsCancellationRequested)
		{
		}
		catch (Exception ex)
		{
			_lastEngineMessage = ex.Message;
		}
	}


	private async Task RunOnUIAsync(Action action)
	{
		if (DispatcherQueue.HasThreadAccess)
		{
			action();
			return;
		}
		TaskCompletionSource completion = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
		if (DispatcherQueue.TryEnqueue(() =>
		{
			try
			{
				action();
				completion.SetResult();
			}
			catch (Exception exception)
			{
				completion.SetException(exception);
			}
		}))
		{
			await completion.Task;
		}
	}

	private void UpdateVisiblePageState()
	{
		PageTitleText.Text = GetPageTitle(_currentPage);
		if (_currentPage == "overview")
		{
			UpdateDashboardState();
			return;
		}
		if (_currentPage == "live")
		{
			UpdateLiveState();
			return;
		}
		if (_currentPage == "activity")
		{
			UpdateActivityPageState();
			return;
		}
		string currentPage = _currentPage;
		if ((currentPage == "clips" || currentPage == "published") ? true : false)
		{
			UpdateClipLibraryState();
		}
		// Activity and Creators are rebuilt only when their own source data changes.
		// Their refresh workers compare snapshots before touching the visual tree.
	}


    private void NavItem_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button button && button.Tag is string page)
            NavigateTo(page);
    }

	private void InitializeNavigationBadges()
	{
		_clipBadgeText = AttachNavigationBadge(NavClipsButton, out _clipBadgeBorder);
		_creatorBadgeText = AttachNavigationBadge(NavCreatorsButton, out _creatorBadgeBorder);
		UpdateSidebarBadges();
	}

	private static TextBlock AttachNavigationBadge(Button button, out Border badgeBorder)
	{
		if (button.Content is not StackPanel content)
			throw new InvalidOperationException($"Navigation item '{button.Name}' has no expected content panel.");

		var layout = new Grid { ColumnSpacing = 8 };
		layout.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
		layout.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
		content.HorizontalAlignment = HorizontalAlignment.Stretch;
		Grid.SetColumn(content, 0);
		layout.Children.Add(content);

		var badgeText = new TextBlock
		{
			FontFamily = ActiveFontFamily,
			FontSize = UiFontSize(9),
			FontWeight = FontWeights.SemiBold,
			VerticalAlignment = VerticalAlignment.Center,
			HorizontalAlignment = HorizontalAlignment.Center
		};
		badgeBorder = new Border
		{
			Padding = new Thickness(6, 2, 6, 2),
			CornerRadius = new CornerRadius(99),
			BorderThickness = new Thickness(1),
			VerticalAlignment = VerticalAlignment.Center,
			Visibility = Visibility.Collapsed,
			Child = badgeText
		};
		Grid.SetColumn(badgeBorder, 1);
		layout.Children.Add(badgeBorder);
		button.Content = layout;
		return badgeText;
	}

	private void UpdateSidebarBadges()
	{
		var theme = Themes.FirstOrDefault(x => x.Id == _theme) ?? Themes[0];
		var clipCount = Math.Max(0, _state?.ClipTotal ?? 0);
		var creatorCount = _creators.Count(x => x.Running || x.CaptureActive);

		SetSidebarBadge(_clipBadgeBorder, _clipBadgeText, clipCount, theme, live: false);
		SetSidebarBadge(_creatorBadgeBorder, _creatorBadgeText, creatorCount, theme, live: true);
	}

	private static void SetSidebarBadge(
		Border? border, TextBlock? text, int count, ThemePalette theme, bool live)
	{
		if (border is null || text is null)
			return;
		border.Visibility = count > 0 ? Visibility.Visible : Visibility.Collapsed;
		text.Text = count > 99 ? "99+" : count.ToString(CultureInfo.InvariantCulture);
		border.Background = new SolidColorBrush(ParseColor(theme.SidebarSurface));
		border.BorderBrush = new SolidColorBrush(ParseColor(live ? theme.SidebarAccentBorder : theme.SidebarLine));
		text.Foreground = new SolidColorBrush(ParseColor(live ? theme.SidebarAccentText : theme.SidebarMuted));
	}

	private void RegisterSearchShortcuts()
	{
		var controlK = new Microsoft.UI.Xaml.Input.KeyboardAccelerator
		{
			Key = Windows.System.VirtualKey.K,
			Modifiers = Windows.System.VirtualKeyModifiers.Control
		};
		controlK.Invoked += (_, args) =>
		{
			GlobalSearchBox.Focus(FocusState.Programmatic);
			args.Handled = true;
		};
		KeyboardAccelerators.Add(controlK);

		var slash = new Microsoft.UI.Xaml.Input.KeyboardAccelerator
		{
			Key = (Windows.System.VirtualKey)0xBF
		};
		slash.Invoked += (_, args) =>
		{
			var focused = Microsoft.UI.Xaml.Input.FocusManager.GetFocusedElement(XamlRoot);
			if (focused is TextBox or PasswordBox or RichEditBox or AutoSuggestBox)
				return;
			GlobalSearchBox.Focus(FocusState.Programmatic);
			args.Handled = true;
		};
		KeyboardAccelerators.Add(slash);
	}

private void UpdateSidebarSelection()
    {
        var items = new[]
        {
            NavOverviewButton, NavLiveButton, NavCreatorsButton, NavClipsButton,
            NavPublishedButton, NavWordsButton, NavPublishingButton, NavProvidersButton, NavSettingsButton,
            NavActivityButton, NavHelpButton, NavAboutButton
        };
        var theme = Themes.FirstOrDefault(x => x.Id == _theme) ?? Themes[0];
        var transparent = new SolidColorBrush(ColorHelper.FromArgb(0, 0, 0, 0));

        foreach (var button in items)
        {
            var selected = string.Equals(button.Tag as string, _currentPage, StringComparison.Ordinal);
            button.Background = selected
                ? new SolidColorBrush(ParseColor(theme.SidebarSurface))
                : transparent;
            button.Foreground = new SolidColorBrush(ParseColor(
                selected ? theme.SidebarInk : theme.SidebarBody));
            button.BorderBrush = selected
                ? new SolidColorBrush(ParseColor(theme.SidebarAccentBorder))
                : transparent;
            button.BorderThickness = new Thickness(1);
        }
        UpdateSidebarBadges();
    }

    private void NavigateTo(string page)
    {
        _currentPage = page;
        ContentScrollViewer.ChangeView(null, 0, null);
        PageTitleText.Text = GetPageTitle(page);
        UpdateSidebarSelection();
        if (page == "clips") _clipTab = "clips";
        if (page == "published") _clipTab = "scheduled";
        RenderCurrentPage();
    }

	private static string GetPageTitle(string page)
	{
		if (1 == 0)
		{
		}
		string result = page switch
		{
			"overview" => "Dashboard",
			"live" => "Live Studio",
			"creators" => "Creators",
			"clips" => "Clip library",
			"published" => "Scheduled",
			"publishing" => "Publisher",
			"words" => "Hype words",
			"activity" => "Activity",
			"settings" => "Settings",
			"providers" => "AI & Providers",
			"help" => "Help",
			"about" => "About StreamSnip AI",
			_ => "StreamSnip AI",
		};
		if (1 == 0)
		{
		}
		return result;
	}

	private void RenderCurrentPage()
	{
		PageHost.Children.Clear();
		PageActionHost.Child = null;
		PageActionHost.Visibility = Visibility.Collapsed;
		try
		{
			RenderCurrentPageCore();
		}
		catch (Exception ex)
		{
			_lastEngineMessage = ex.ToString();
			PageActionHost.Child = null;
			PageActionHost.Visibility = Visibility.Collapsed;
			PageHost.Children.Clear();
			PageHost.Children.Add(new TextBlock
			{
				Text = GetPageTitle(_currentPage),
				FontFamily = ActiveFontFamily,
				 FontSize = UiFontSize(26),
				FontWeight = FontWeights.SemiBold,
				Foreground = Application.Current.Resources["PrimaryTextBrush"] as Brush,
				Margin = new Thickness(0, 0, 0, 10)
			});
			var details = new StackPanel { Spacing = 8 };
			details.Children.Add(new TextBlock
			{
				Text = "This page could not finish rendering.",
				FontFamily = ActiveFontFamily,
				FontSize = UiFontSize(14),
				FontWeight = FontWeights.SemiBold,
				Foreground = Application.Current.Resources["PrimaryTextBrush"] as Brush
			});
			details.Children.Add(new TextBlock
			{
				Text = ex.ToString(),
				FontFamily = ActiveFontFamily,
				FontSize = UiFontSize(12.5),
				TextWrapping = TextWrapping.Wrap,
				Foreground = Application.Current.Resources["BodyTextBrush"] as Brush
			});
			details.Children.Add(CreateButton("Copy error details", () =>
				_ = CopyDiagnosticTextAsync(ex.ToString())));
			PageHost.Children.Add(CreatePanel("Page render error", "The native app is still running. This diagnostic captures the failing control so it can be fixed.", details));
		}
		RestoreEngineNotice();
		ApplyFontToVisualTree(this);
	}

	private void RestoreEngineNotice()
	{
		if (_engineNotice is null)
			return;
		foreach (UIElement child in PageHost.Children)
		{
			if (ReferenceEquals(child, _engineNotice))
				return;
		}
		PageHost.Children.Insert(0, _engineNotice);
	}

	private async Task CopyDiagnosticTextAsync(string text)
	{
		try
		{
			var package = new Windows.ApplicationModel.DataTransfer.DataPackage();
			package.SetText(text);
			Windows.ApplicationModel.DataTransfer.Clipboard.SetContent(package);
			await Task.CompletedTask;
		}
		catch { }
	}

	private void RenderCurrentPageCore()
	{
		switch (_currentPage)
		{
		case "overview":
			RenderDashboardPage();
			break;
		case "live":
			RenderLiveStudioPage();
			break;
		case "creators":
			RenderCreatorsPage();
			break;
		case "clips":
			RenderClipLibraryPage(published: false);
			break;
		case "published":
			RenderClipLibraryPage(published: true);
			break;
		case "publishing":
			RenderPublishingPage();
			break;
		case "words":
			RenderHypeWordsPage();
			break;
		case "activity":
			RenderActivityPage();
			break;
		case "providers":
			RenderProvidersPage();
			break;
		case "settings":
			RenderSettingsPage();
			break;
		case "help":
			RenderHelpPage();
			break;
		case "about":
			RenderAboutPage();
			break;
		default:
			RenderDashboardPage();
			break;
		}
	}

	private async void GlobalSearchBox_QuerySubmitted(AutoSuggestBox sender, AutoSuggestBoxQuerySubmittedEventArgs args)
	{
		_clipSearch = args.QueryText?.Trim() ?? "";
		_clipTab = "clips";
		_clipOffset = 0;
		NavigateTo("clips");
	}

	private void GlobalSearchBox_TextChanged(AutoSuggestBox sender, AutoSuggestBoxTextChangedEventArgs args)
	{
		if (args.Reason == AutoSuggestionBoxTextChangeReason.UserInput)
		{
			_clipSearch = sender.Text?.Trim() ?? "";
		}
	}

	private void HelpButton_Click(object sender, RoutedEventArgs e)
	{
		NavigateTo("help");
	}

	private async void QuitButton_Click(object sender, RoutedEventArgs e)
	{
		await QuitApplicationAsync();
	}

	private async Task QuitApplicationAsync()
	{
		if (_quitting)
			return;

		ContentDialog dialog = new ContentDialog
		{
			XamlRoot = XamlRoot,
			Title = "Quit StreamSnip AI?",
			Content = "Active capture and creator monitors will be stopped before the application closes.",
			PrimaryButtonText = "Quit",
			CloseButtonText = "Cancel",
			DefaultButton = ContentDialogButton.Primary
		};
		if (await dialog.ShowAsync() != ContentDialogResult.Primary)
			return;

		await ShutdownApplicationAsync();
	}

	private async Task ShutdownApplicationAsync()
	{
		if (_quitting)
			return;

		_quitting = true;
		QuitButton.IsEnabled = false;
		QuitButton.Content = "Shutting down…";
		_eventsCancellation?.Cancel();
		try
		{
			if (_engine != null)
			{
				await _engine.QuitAsync();
				await _engine.DisposeAsync();
				_engine = null;
			}
		}
		catch (Exception ex)
		{
			await ShowErrorAsync("Shutdown warning", ex.Message);
		}
		Application.Current.Exit();
	}
	private async Task<JsonObject> GetAsync(string route)
	{
		if (_engine == null)
		{
			throw new InvalidOperationException("The local engine is not connected.");
		}
		return await _engine.GetJsonAsync(route, _shutdown.Token);
	}

	private async Task<JsonObject> PostAsync(string route, JsonObject? body = null)
	{
		if (_engine == null)
		{
			throw new InvalidOperationException("The local engine is not connected.");
		}
		JsonObject result = await _engine.PostJsonAsync(route, body, _shutdown.Token);
		await RefreshStateAsync();
		return result;
	}

	private async Task RunActionAsync(string title, Func<Task> action)
	{
		try
		{
			await action();
		}
		catch (Exception ex)
		{
			await ShowErrorAsync(title, ex.Message);
		}
	}

	private async Task ShowErrorAsync(string title, string message)
	{
		if ((object)XamlRoot != null)
		{
			ContentDialog dialog = new ContentDialog
			{
				XamlRoot = XamlRoot,
				Title = title,
				Content = new TextBlock
				{
					Text = message,
					TextWrapping = TextWrapping.Wrap,
					FontFamily = CurrentFont,
					FontSize = ScaledFontSize(12),
					MaxWidth = 560.0
				},
				CloseButtonText = "Close",
				DefaultButton = ContentDialogButton.Close
			};
			await dialog.ShowAsync();
		}
	}

	private void SetEngineIndicator(string message, EngineIndicator kind)
	{
		EngineStatusText.Text = message;
		if (SidebarEngineText is not null)
		{
			SidebarEngineText.Text = message switch
			{
				"Capture active" => "Capture active",
				"Stopping" => "Capture stopping",
				"Engine unavailable" or "Engine stopped" => "Engine unavailable",
				"Reconnecting" or "Event stream reconnecting" => "Reconnecting",
				"Starting local engine…" or "Connecting" => "Connecting to engine",
				_ => "Engine connected"
			};
		}
		if (1 == 0)
		{
		}
		var statusBrushKey = kind switch
		{
			EngineIndicator.Success => "SuccessBrush",
			EngineIndicator.Danger => "DangerBrush",
			EngineIndicator.Warning => "WarningBrush",
			_ => "MutedTextBrush"
		};
		var statusBrush = Application.Current.Resources[statusBrushKey] as Brush;
		if (statusBrush is not null)
		{
			EngineStatusDot.Fill = statusBrush;
			if (SidebarEngineDot is not null)
				SidebarEngineDot.Fill = statusBrush;
			if (FooterEngineDot is not null)
				FooterEngineDot.Fill = statusBrush;
		}
	}

	private void UpdateEngineIndicator()
	{
		if (_state is null)
		{
			SetEngineIndicator("Connecting", EngineIndicator.Warning);
		}
		else if (_state.Running)
		{
			SetEngineIndicator(_state.Stopping ? "Stopping" : "Capture active", _state.Stopping ? EngineIndicator.Warning : EngineIndicator.Success);
		}
		else
		{
			SetEngineIndicator("Engine ready", EngineIndicator.Success);
		}
	}

	private void LoadPreferences()
	{
		try
		{
			if (File.Exists(_preferencesPath))
			{
				JsonObject? jsonObject = JsonNode.Parse(File.ReadAllText(_preferencesPath)) as JsonObject;
				_theme = jsonObject?["theme"]?.GetValue<string>() ?? _theme;
				_customAccent = jsonObject?["accent"]?.GetValue<string>() ?? "";
				if (!IsValidAccent(_customAccent)) _customAccent = "";
				var fontPreferenceVersion = jsonObject?["fontPreferenceVersion"]?.GetValue<int>() ?? 0;
				var savedFont = jsonObject?["font"]?.GetValue<string>();
				// Restore JetBrains Mono after the temporary Manrope default migration.
				// Preserve explicitly selected fonts other than that migrated default.
				if (fontPreferenceVersion < 8 &&
					(string.IsNullOrWhiteSpace(savedFont) ||
					 string.Equals(savedFont, "Manrope", StringComparison.Ordinal) ||
					 (fontPreferenceVersion < 2 && string.Equals(savedFont, "Inter", StringComparison.Ordinal))))
					savedFont = "JetBrains Mono";
				_fontName = NormalizeFontName(savedFont ?? _fontName);
				_fontSize = NormalizeFontSize(jsonObject?["fontSize"]?.GetValue<string>() ?? _fontSize);
				_applicationFontScale = FontSizeScaleFor(_fontSize);
			}
		}
		catch
		{
		}
	}

	private void SavePreferences()
	{
		try
		{
			string? preferencesDirectory = System.IO.Path.GetDirectoryName(_preferencesPath);
			if (!string.IsNullOrWhiteSpace(preferencesDirectory))
				Directory.CreateDirectory(preferencesDirectory);
			JsonObject jsonObject = new JsonObject
			{
				["theme"] = _theme,
				["accent"] = _customAccent,
				["font"] = _fontName,
				["fontSize"] = _fontSize,
				["fontPreferenceVersion"] = 8
			};
			File.WriteAllText(_preferencesPath, jsonObject.ToJsonString(new JsonSerializerOptions
			{
				WriteIndented = true
			}));
		}
		catch
		{
		}
	}

	private void ApplyTheme(string themeId)
	{
		ThemePalette themePalette = Themes.FirstOrDefault((ThemePalette t) => t.Id == themeId) ?? Themes[0];
		_theme = themePalette.Id;
		SetResourceBrush("AppBackgroundBrush", themePalette.App);
		SetResourceBrush("SurfaceBrush", themePalette.Surface);
		SetResourceBrush("SurfaceSoftBrush", themePalette.Soft);
		SetResourceBrush("SurfaceHoverBrush", themePalette.Hover);
		SetResourceBrush("SidebarBrush", themePalette.Sidebar);
		SetResourceBrush("SidebarSurfaceBrush", themePalette.SidebarSurface);
		SetResourceBrush("SidebarLineBrush", themePalette.SidebarLine);
		SetResourceBrush("SidebarTextBrush", themePalette.SidebarInk);
		SetResourceBrush("SidebarBodyTextBrush", themePalette.SidebarBody);
		SetResourceBrush("SidebarMutedTextBrush", themePalette.SidebarMuted);
		SetResourceBrush("PrimaryTextBrush", themePalette.PrimaryText);
		SetResourceBrush("BodyTextBrush", themePalette.BodyText);
		SetResourceBrush("MutedTextBrush", themePalette.MutedText);
		SetResourceBrush("LineBrush", themePalette.Line);
		string accent = IsValidAccent(_customAccent) ? _customAccent : themePalette.Accent;
		SetResourceBrush("AccentBrush", accent);
		SetResourceBrush("AccentSoftBrush", BlendHex(accent, themePalette.Surface, 0.16));
		SetResourceBrush("AccentInkBrush", AccentTextHex(accent));
		SetResourceBrush("AccentTextBrush", themePalette.AccentText);
		SetResourceBrush("SuccessBrush", themePalette.Success);
		SetResourceBrush("WarningBrush", themePalette.Warning);
		SetResourceBrush("DangerBrush", themePalette.Danger);
		SetResourceBrush("SuccessTextBrush", themePalette.SuccessText);
		SetResourceBrush("WarningTextBrush", themePalette.WarningText);
		SetResourceBrush("DangerTextBrush", themePalette.DangerText);

		// TextBox, PasswordBox and AutoSuggestBox content presenters use TextControl*
		// theme resources internally. Foreground on the outer control is not sufficient
		// for every visual state, so keep the template resources in sync with this palette.
		SetResourceBrush("TextControlForeground", themePalette.PrimaryText);
		SetResourceBrush("TextControlForegroundPointerOver", themePalette.PrimaryText);
		SetResourceBrush("TextControlForegroundFocused", themePalette.PrimaryText);
		SetResourceBrush("TextControlForegroundDisabled", themePalette.BodyText);
		SetResourceBrush("TextControlPlaceholderForeground", themePalette.MutedText);
		SetResourceBrush("TextControlPlaceholderForegroundPointerOver", themePalette.MutedText);
		SetResourceBrush("TextControlPlaceholderForegroundFocused", themePalette.MutedText);
		SetResourceBrush("TextControlPlaceholderForegroundDisabled", themePalette.BodyText);
		SetResourceBrush("TextControlBackground", themePalette.Soft);
		SetResourceBrush("TextControlBackgroundPointerOver", themePalette.Hover);
		SetResourceBrush("TextControlBackgroundFocused", themePalette.Surface);
		SetResourceBrush("TextControlBackgroundDisabled", themePalette.Soft);
		SetResourceBrush("TextControlBorderBrush", themePalette.Line);
		SetResourceBrush("TextControlBorderBrushPointerOver", themePalette.Line);
		SetResourceBrush("TextControlBorderBrushFocused", themePalette.AccentText);
		SetResourceBrush("TextControlBorderBrushDisabled", themePalette.Line);

		// Buttons must remain legible when WinUI moves between normal/hover/pressed/disabled.
		SetResourceBrush("ButtonForeground", themePalette.BodyText);
		SetResourceBrush("ButtonForegroundPointerOver", themePalette.PrimaryText);
		SetResourceBrush("ButtonForegroundPressed", themePalette.PrimaryText);
		SetResourceBrush("ButtonForegroundDisabled", themePalette.BodyText);
		SetResourceBrush("ButtonBackground", themePalette.Surface);
		SetResourceBrush("ButtonBackgroundPointerOver", themePalette.Hover);
		SetResourceBrush("ButtonBackgroundPressed", themePalette.Soft);
		SetResourceBrush("ButtonBackgroundDisabled", themePalette.Soft);
		SetResourceBrush("ButtonBorderBrush", themePalette.Line);
		SetResourceBrush("ButtonBorderBrushPointerOver", themePalette.Line);
		SetResourceBrush("ButtonBorderBrushPressed", themePalette.Line);
		SetResourceBrush("ButtonBorderBrushDisabled", themePalette.Line);

		// ComboBox selection, dropdown and disabled states are independent WinUI resources.
		SetResourceBrush("ComboBoxForeground", themePalette.PrimaryText);
		SetResourceBrush("ComboBoxForegroundPointerOver", themePalette.PrimaryText);
		SetResourceBrush("ComboBoxForegroundPressed", themePalette.BodyText);
		SetResourceBrush("ComboBoxForegroundDisabled", themePalette.BodyText);
		SetResourceBrush("ComboBoxForegroundFocused", themePalette.PrimaryText);
		SetResourceBrush("ComboBoxForegroundFocusedPressed", themePalette.PrimaryText);
		SetResourceBrush("ComboBoxHeaderForeground", themePalette.PrimaryText);
		SetResourceBrush("ComboBoxHeaderForegroundDisabled", themePalette.BodyText);
		SetResourceBrush("ComboBoxPlaceHolderForeground", themePalette.MutedText);
        SetResourceBrush("ComboBoxPlaceHolderForegroundPointerOver", themePalette.MutedText);
        SetResourceBrush("ComboBoxPlaceHolderForegroundPressed", themePalette.MutedText);
        SetResourceBrush("ComboBoxPlaceHolderForegroundDisabled", themePalette.BodyText);
        SetResourceBrush("ComboBoxPlaceHolderForegroundFocused", themePalette.MutedText);
		SetResourceBrush("ComboBoxDropDownForeground", themePalette.PrimaryText);
		SetResourceBrush("ComboBoxItemForeground", themePalette.PrimaryText);
		SetResourceBrush("ComboBoxItemForegroundPressed", themePalette.BodyText);
		SetResourceBrush("ComboBoxItemForegroundPointerOver", themePalette.PrimaryText);
		SetResourceBrush("ComboBoxItemForegroundDisabled", themePalette.BodyText);
		SetResourceBrush("ComboBoxItemForegroundSelected", themePalette.PrimaryText);
		SetResourceBrush("ComboBoxItemForegroundSelectedUnfocused", themePalette.PrimaryText);
		SetResourceBrush("ComboBoxItemForegroundSelectedPressed", themePalette.PrimaryText);
		SetResourceBrush("ComboBoxItemForegroundSelectedPointerOver", themePalette.PrimaryText);
		SetResourceBrush("ComboBoxItemForegroundSelectedDisabled", themePalette.BodyText);
        SetResourceBrush("ComboBoxBackground", themePalette.Soft);
        SetResourceBrush("ComboBoxBackgroundPointerOver", themePalette.Hover);
        SetResourceBrush("ComboBoxBackgroundPressed", themePalette.Hover);
        SetResourceBrush("ComboBoxBackgroundDisabled", themePalette.Soft);
        SetResourceBrush("ComboBoxBackgroundFocused", themePalette.Surface);
        SetResourceBrush("ComboBoxBackgroundUnfocused", themePalette.Soft);
        SetResourceBrush("ComboBoxBackgroundBorderBrushFocused", themePalette.AccentText);
        SetResourceBrush("ComboBoxBackgroundBorderBrushUnfocused", themePalette.Line);
        SetResourceBrush("ComboBoxBorderBrush", themePalette.Line);
        SetResourceBrush("ComboBoxBorderBrushPointerOver", themePalette.Line);
        SetResourceBrush("ComboBoxBorderBrushPressed", themePalette.Line);
        SetResourceBrush("ComboBoxBorderBrushDisabled", themePalette.Line);
        SetResourceBrush("ComboBoxDropDownBackground", themePalette.Surface);
        SetResourceBrush("ComboBoxDropDownBackgroundPointerOver", themePalette.Hover);
        SetResourceBrush("ComboBoxDropDownBackgroundPointerPressed", themePalette.Soft);
        SetResourceBrush("ComboBoxDropDownBorderBrush", themePalette.Line);
        SetResourceBrush("ComboBoxDropDownGlyphForeground", themePalette.MutedText);
        SetResourceBrush("ComboBoxDropDownGlyphForegroundDisabled", themePalette.BodyText);
        SetResourceBrush("ComboBoxDropDownGlyphForegroundFocused", themePalette.PrimaryText);
        SetResourceBrush("ComboBoxDropDownGlyphForegroundFocusedPressed", themePalette.PrimaryText);
        SetResourceBrush("ComboBoxItemBackground", themePalette.Surface);
        SetResourceBrush("ComboBoxItemBackgroundPointerOver", themePalette.Hover);
        SetResourceBrush("ComboBoxItemBackgroundPressed", themePalette.Soft);
        SetResourceBrush("ComboBoxItemBackgroundDisabled", themePalette.Soft);
        SetResourceBrush("ComboBoxItemBackgroundSelected", BlendHex(themePalette.Accent, themePalette.Surface, 0.14));
        SetResourceBrush("ComboBoxItemBackgroundSelectedUnfocused", BlendHex(themePalette.Accent, themePalette.Surface, 0.14));
        SetResourceBrush("ComboBoxItemBackgroundSelectedPointerOver", BlendHex(themePalette.Accent, themePalette.Surface, 0.18));
        SetResourceBrush("ComboBoxItemBackgroundSelectedPressed", BlendHex(themePalette.Accent, themePalette.Surface, 0.2));
        SetResourceBrush("ComboBoxItemBackgroundSelectedDisabled", themePalette.Soft);
        SetResourceBrush("ComboBoxItemBorderBrush", themePalette.Line);
        SetResourceBrush("ComboBoxItemBorderBrushPointerOver", themePalette.Line);
        SetResourceBrush("ComboBoxItemBorderBrushPressed", themePalette.Line);
        SetResourceBrush("ComboBoxItemBorderBrushDisabled", themePalette.Line);
        SetResourceBrush("ComboBoxItemBorderBrushSelected", themePalette.AccentText);
        SetResourceBrush("ComboBoxItemBorderBrushSelectedUnfocused", themePalette.Line);
        SetResourceBrush("ComboBoxItemBorderBrushSelectedPointerOver", themePalette.AccentText);
        SetResourceBrush("ComboBoxItemBorderBrushSelectedPressed", themePalette.AccentText);
        SetResourceBrush("ComboBoxItemBorderBrushSelectedDisabled", themePalette.Line);

        // CheckBox and radio states are also template-owned and must not fall back to OS colors.
        foreach (var key in new[] { "Unchecked", "Checked", "Indeterminate" })
        {
            var foreground = key == "Unchecked" ? themePalette.BodyText : themePalette.PrimaryText;
            foreach (var state in new[] { "", "PointerOver", "Pressed" })
                SetResourceBrush($"CheckBoxForeground{key}{state}", state.Length == 0 ? foreground : themePalette.PrimaryText);
            SetResourceBrush($"CheckBoxForeground{key}Disabled", themePalette.BodyText);
        }
        foreach (var state in new[] { "", "PointerOver", "Pressed" })
        {
            SetResourceBrush("CheckBoxBackgroundUnchecked" + state, state.Length == 0 ? themePalette.Surface : themePalette.Hover);
            SetResourceBrush("CheckBoxBackgroundChecked" + state, themePalette.Accent);
            SetResourceBrush("CheckBoxBackgroundIndeterminate" + state, themePalette.Accent);
            SetResourceBrush("CheckBoxBorderBrushUnchecked" + state, state.Length == 0 ? themePalette.Line : themePalette.BodyText);
            SetResourceBrush("CheckBoxBorderBrushChecked" + state, themePalette.Accent);
            SetResourceBrush("CheckBoxCheckGlyphForegroundChecked" + state, AccentTextHex(accent));
            SetResourceBrush("CheckBoxCheckGlyphForegroundIndeterminate" + state, AccentTextHex(accent));
        }
        SetResourceBrush("CheckBoxBackgroundUncheckedDisabled", themePalette.Soft);
        SetResourceBrush("CheckBoxBackgroundCheckedDisabled", themePalette.Soft);
        SetResourceBrush("CheckBoxBackgroundIndeterminateDisabled", themePalette.Soft);
        SetResourceBrush("CheckBoxBorderBrushUncheckedDisabled", themePalette.Line);
        SetResourceBrush("CheckBoxBorderBrushCheckedDisabled", themePalette.Line);
        SetResourceBrush("CheckBoxCheckGlyphForegroundCheckedDisabled", themePalette.BodyText);
        SetResourceBrush("CheckBoxCheckGlyphForegroundIndeterminateDisabled", themePalette.BodyText);
        SetResourceBrush("RadioButtonForeground", themePalette.BodyText);
        SetResourceBrush("RadioButtonForegroundPointerOver", themePalette.PrimaryText);
        SetResourceBrush("RadioButtonForegroundPressed", themePalette.PrimaryText);
        SetResourceBrush("RadioButtonForegroundDisabled", themePalette.BodyText);
        SetResourceBrush("RadioButtonBackground", themePalette.Surface);
        SetResourceBrush("RadioButtonBackgroundPointerOver", themePalette.Hover);
        SetResourceBrush("RadioButtonBackgroundPressed", themePalette.Soft);
        SetResourceBrush("RadioButtonBackgroundDisabled", themePalette.Soft);
        SetResourceBrush("RadioButtonBorderBrush", themePalette.Line);
        SetResourceBrush("RadioButtonBorderBrushPointerOver", themePalette.BodyText);
        SetResourceBrush("RadioButtonBorderBrushPressed", themePalette.BodyText);
        SetResourceBrush("RadioButtonBorderBrushDisabled", themePalette.Line);
        SetResourceBrush("RadioButtonOuterEllipseCheckedFill", themePalette.Accent);
        SetResourceBrush("RadioButtonOuterEllipseCheckedStroke", themePalette.Accent);
        SetResourceBrush("RadioButtonOuterEllipseFill", themePalette.Surface);
        SetResourceBrush("RadioButtonOuterEllipseStroke", themePalette.Line);
        SetResourceBrush("RadioButtonCheckGlyphFill", AccentTextHex(accent));
        SetResourceBrush("ProgressBarBackground", themePalette.Soft);
        SetResourceBrush("ProgressBarForeground", themePalette.Accent);
        SetResourceBrush("ToggleSwitchContentForeground", themePalette.BodyText);
        SetResourceBrush("ToggleSwitchContentForegroundDisabled", themePalette.BodyText);
        SetResourceBrush("ToggleSwitchFillOn", themePalette.Accent);
        SetResourceBrush("ToggleSwitchFillOff", themePalette.Line);
        SetResourceBrush("ToggleSwitchFillOnDisabled", themePalette.Soft);
        SetResourceBrush("ToggleSwitchFillOffDisabled", themePalette.Soft);
        SetResourceBrush("ToggleSwitchKnobFillOn", AccentTextHex(accent));
        SetResourceBrush("ToggleSwitchKnobFillOff", themePalette.Surface);
        SetResourceBrush("ToggleSwitchKnobFillOnDisabled", themePalette.BodyText);
        SetResourceBrush("ToggleSwitchKnobFillOffDisabled", themePalette.BodyText);

        // TabView's selected header has its own foreground/background resources.
		SetResourceBrush("TabViewItemHeaderForeground", themePalette.BodyText);
        SetResourceBrush("TabViewItemHeaderForegroundPressed", themePalette.PrimaryText);
		SetResourceBrush("TabViewItemHeaderForegroundPointerOver", themePalette.PrimaryText);
		SetResourceBrush("TabViewItemHeaderForegroundSelected", themePalette.PrimaryText);
		SetResourceBrush("TabViewItemHeaderForegroundDisabled", themePalette.BodyText);
		SetResourceBrush("TabViewItemHeaderBackground", themePalette.Surface);
        SetResourceBrush("TabViewItemHeaderBackgroundPressed", themePalette.Soft);
		SetResourceBrush("TabViewItemHeaderBackgroundPointerOver", themePalette.Hover);
		SetResourceBrush("TabViewItemHeaderBackgroundSelected", themePalette.Hover);
		SetResourceBrush("TabViewItemHeaderBackgroundDisabled", themePalette.Soft);
		SetResourceBrush("TabViewItemIconForeground", themePalette.BodyText);
        SetResourceBrush("TabViewItemIconForegroundPressed", themePalette.PrimaryText);
		SetResourceBrush("TabViewItemIconForegroundPointerOver", themePalette.PrimaryText);
		SetResourceBrush("TabViewItemIconForegroundSelected", themePalette.AccentText);
		SetResourceBrush("TabViewItemIconForegroundDisabled", themePalette.BodyText);

        // Palette changes are applied through the live app/page/theme dictionaries.
        // Do not mutate RequestedTheme here: WinUI locks it after the page is loaded.
		RootBackgroundUpdate();
        ApplyShellPalette(themePalette);
        UpdateSidebarSelection();
        if (_loaded)
            UpdateEngineIndicator();
		UpdateWindowTitleBar(themePalette, accent);
		SavePreferences();
	}

	private static void UpdateWindowTitleBar(ThemePalette palette, string accent)
	{
		try
		{
			if (!AppWindowTitleBar.IsCustomizationSupported()) return;
			var titleBar = App.MainWindowInstance?.AppWindow.TitleBar;
			if (titleBar is null) return;

			var app = ParseColor(palette.App);
			var sidebar = ParseColor(palette.Sidebar);
			var hover = ParseColor(palette.Hover);
			var primaryText = ParseColor(palette.PrimaryText);
			var bodyText = ParseColor(palette.BodyText);
			var mutedText = ParseColor(palette.MutedText);
			var accentColor = ParseColor(accent);
			var accentText = ParseColor(AccentTextHex(accent));

			titleBar.BackgroundColor = app;
			titleBar.ForegroundColor = primaryText;
			titleBar.ButtonBackgroundColor = app;
			titleBar.ButtonForegroundColor = bodyText;
			titleBar.ButtonHoverBackgroundColor = hover;
			titleBar.ButtonHoverForegroundColor = primaryText;
			titleBar.ButtonPressedBackgroundColor = accentColor;
			titleBar.ButtonPressedForegroundColor = accentText;
			titleBar.InactiveBackgroundColor = sidebar;
			titleBar.InactiveForegroundColor = mutedText;
			titleBar.ButtonInactiveBackgroundColor = sidebar;
			titleBar.ButtonInactiveForegroundColor = mutedText;
		}
		catch
		{
			// Keep the native window available if the OS declines a title-bar color.
		}
	}

    private void ApplyShellPalette(ThemePalette palette)
    {
        SolidColorBrush BrushFor(string color) => new SolidColorBrush(ParseColor(color));
        var transparent = new SolidColorBrush(Color.FromArgb(0, 0, 0, 0));

        RootLayoutGrid.Background = BrushFor(palette.App);
        SidebarRoot.Background = BrushFor(palette.Sidebar);
        SidebarBrandBorder.Background = BrushFor(palette.Sidebar);
        SidebarWorkspaceBorder.Background = BrushFor(palette.SidebarSurface);
        SidebarWorkspaceBorder.BorderBrush = BrushFor(palette.SidebarLine);
        SidebarEngineBorder.Background = BrushFor(palette.SidebarSurface);
        SidebarEngineBorder.BorderBrush = BrushFor(palette.SidebarLine);

        SidebarBrandTitleText.Foreground = BrushFor(palette.SidebarInk);
        SidebarBrandSubtitleText.Foreground = BrushFor(palette.SidebarMuted);
        SidebarWorkspaceTitleText.Foreground = BrushFor(palette.SidebarInk);
        SidebarWorkspaceDeviceText.Foreground = BrushFor(palette.SidebarMuted);
        SidebarStudioLabel.Foreground = BrushFor(palette.SidebarMuted);
        SidebarLibraryLabel.Foreground = BrushFor(palette.SidebarMuted);
        SidebarManageLabel.Foreground = BrushFor(palette.SidebarMuted);
        SidebarEngineText.Foreground = BrushFor(palette.SidebarInk);
        SidebarLocalProcessingText.Foreground = BrushFor(palette.SidebarMuted);

        TopBarRoot.Background = BrushFor(palette.Surface);
        TopBarRoot.BorderBrush = BrushFor(palette.Line);
        TopBarBrandText.Foreground = BrushFor(palette.MutedText);
        TopBarDivider.Background = BrushFor(palette.Line);
        PageTitleText.Foreground = BrushFor(palette.PrimaryText);

        GlobalSearchBox.Background = BrushFor(palette.Soft);
        GlobalSearchBox.Foreground = BrushFor(palette.PrimaryText);
        GlobalSearchBox.BorderBrush = BrushFor(palette.Line);
        SearchQueryIcon.Foreground = BrushFor(palette.MutedText);

        EngineStatusBorder.Background = BrushFor(palette.Soft);
        EngineStatusBorder.BorderBrush = BrushFor(palette.Line);
        EngineStatusText.Foreground = BrushFor(palette.BodyText);

        HelpButton.Background = transparent;
        HelpButton.Foreground = BrushFor(palette.BodyText);
        HelpButton.BorderBrush = BrushFor(palette.Line);
        HelpButtonText.Foreground = BrushFor(palette.MutedText);
        QuitButton.Background = BrushFor(palette.Surface);
        QuitButton.Foreground = BrushFor(palette.BodyText);
        QuitButton.BorderBrush = BrushFor(palette.Line);

        PageActionHost.Background = BrushFor(palette.Surface);
        PageActionHost.BorderBrush = BrushFor(palette.Line);
        FooterRoot.Background = BrushFor(palette.Surface);
        FooterRoot.BorderBrush = BrushFor(palette.Line);
        FooterEngineText.Foreground = BrushFor(palette.MutedText);
        FooterSeparatorText.Foreground = BrushFor(palette.Line);
        FooterLocalMessageText.Foreground = BrushFor(palette.MutedText);
        FooterVersionText.Foreground = BrushFor(palette.MutedText);
    }

	private void SetResourceBrush(string key, string hex)
	{
		Color color = ParseColor(hex);
        // Static references are avoided for palette colors, but also replace app/page entries
        // so any existing direct code references pick up the current theme brush.
        Application.Current.Resources[key] = new SolidColorBrush(color);
        Resources[key] = new SolidColorBrush(color);

        // WinUI theme dictionary brushes are shared/frozen. Replace each matching entry.
        foreach (var themeKey in new object[] { "Default", "Light" })
        {
            if (Application.Current.Resources.ThemeDictionaries.TryGetValue(themeKey, out var dictionaryValue) &&
                dictionaryValue is ResourceDictionary themeDictionary &&
                themeDictionary.ContainsKey(key))
            {
                themeDictionary[key] = new SolidColorBrush(color);
            }
        }
	}

	private void RootBackgroundUpdate()
	{
        var palette = Themes.First((ThemePalette t) => t.Id == _theme);
		Background = new SolidColorBrush(ParseColor(palette.App));
		SidebarRoot.Background = new SolidColorBrush(ParseColor(palette.Sidebar));
        if (App.MainWindowInstance?.Content is Grid windowRoot)
            windowRoot.Background = new SolidColorBrush(ParseColor(palette.App));
	}

	private void ApplyFont(string fontName)
	{
		_fontName = NormalizeFontName(fontName);
		ActiveFontFamily = ResolveFontFamily(_fontName);
		Application.Current.Resources["AppFont"] = ActiveFontFamily;
		SavePreferences();
		if (XamlRoot is not null)
			ApplyFontToVisualTree(this);
	}

	private static string NormalizeFontName(string? fontName) => FontChoices.Contains(fontName ?? "", StringComparer.Ordinal) ? fontName! : "JetBrains Mono";

	private static FontFamily ResolveFontFamily(string fontName) => fontName switch
	{
		"JetBrains Mono" => new FontFamily("ms-appx:///Assets/Fonts/JetBrainsMono-Variable.ttf#JetBrains Mono"),
		"DM Sans" => new FontFamily("ms-appx:///Assets/Fonts/DMSans-Variable.ttf#DM Sans"),
		"Poppins" => new FontFamily("ms-appx:///Assets/Fonts/Poppins-Regular.ttf#Poppins"),
		"Lato" => new FontFamily("ms-appx:///Assets/Fonts/Lato-Regular.ttf#Lato"),
		"Manrope" => new FontFamily("ms-appx:///Assets/Fonts/Manrope-Variable.ttf#Manrope"),
		"Nunito Sans" => new FontFamily("ms-appx:///Assets/Fonts/NunitoSans-Variable.ttf#Nunito Sans"),
		"Fira Code" => new FontFamily("ms-appx:///Assets/Fonts/FiraCode-Variable.ttf#Fira Code"),
		"Inter" => new FontFamily("ms-appx:///Assets/Fonts/Inter-Variable.ttf#Inter"),
		"Open Sans" => new FontFamily("ms-appx:///Assets/Fonts/OpenSans-Variable.ttf#Open Sans"),
		"IBM Plex Sans" => new FontFamily("ms-appx:///Assets/Fonts/IBMPlexSans-Variable.ttf#IBM Plex Sans"),
		"Roboto" => new FontFamily("ms-appx:///Assets/Fonts/Roboto-Variable.ttf#Roboto"),
		"Source Sans 3" => new FontFamily("ms-appx:///Assets/Fonts/SourceSans3-Variable.ttf#Source Sans 3"),
		"Segoe UI" => new FontFamily("Segoe UI"),
		"Consolas" => new FontFamily("Consolas"),
		"Aptos" => new FontFamily("Aptos"),
		"Arial" => new FontFamily("Arial"),
		"Tahoma" => new FontFamily("Tahoma"),
		"Verdana" => new FontFamily("Verdana"),
		"Georgia" => new FontFamily("Georgia"),
		"Trebuchet MS" => new FontFamily("Trebuchet MS"),
		"Times New Roman" => new FontFamily("Times New Roman"),
		_ => DefaultFontFamily
	};

	private void ApplyFontSize(string fontSize)
	{
		_fontSize = NormalizeFontSize(fontSize);
		_applicationFontScale = FontSizeScaleFor(_fontSize);
		SavePreferences();
		if (XamlRoot is not null)
			ApplyFontToVisualTree(this);
	}

	private static string NormalizeFontSize(string? fontSize) => fontSize?.Trim().ToLowerInvariant() switch
	{
		"small" => "small",
		"medium" => "medium",
		"large" => "large",
		_ => "medium"
	};

	private static double FontSizeScaleFor(string fontSize) => fontSize switch
	{
		"small" => 13.0 / 14.0,
		"medium" => 1.0,
		"large" => 16.0 / 14.0,
		_ => 1.0
	};

	private static double ScaledFontSize(double size) => Math.Max(10.0, UiFontSize(size) * _applicationFontScale);

	private void ApplyFontToVisualTree(DependencyObject root)
	{
		if (root is FrameworkElement element && !FontLoadHandlers.TryGetValue(element, out _))
		{
			FontLoadHandlers.Add(element, new object());
			element.Loaded += (_, _) => ApplyFontToVisualTree(element);
		}

		if (root is TextBlock textBlock)
		{
			ApplyFontSizeToElement(textBlock, textBlock.FontSize, size => textBlock.FontSize = size);
			textBlock.FontFamily = ActiveFontFamily;
		}
		else if (root is Control control)
		{
			ApplyFontSizeToElement(control, control.FontSize, size => control.FontSize = size);
			control.FontFamily = ActiveFontFamily;
		}

		var childCount = Microsoft.UI.Xaml.Media.VisualTreeHelper.GetChildrenCount(root);
		for (var index = 0; index < childCount; index++)
			ApplyFontToVisualTree(Microsoft.UI.Xaml.Media.VisualTreeHelper.GetChild(root, index));
	}

	private static void ApplyFontSizeToElement(FrameworkElement element, double currentSize, Action<double> setFontSize)
	{
		if (!FontSizeBaselines.TryGetValue(element, out var baseline))
		{
			baseline = new FontSizeBaseline(currentSize);
			FontSizeBaselines.Add(element, baseline);
		}
		setFontSize(Math.Max(10.0, baseline.Value * _applicationFontScale));
	}

	private static double UiFontSize(double size)
	{
		// Consistent 14-DIP body scale with proportional hierarchy for labels and headings.
		if (size <= 9.0) return 11.0;
		if (size <= 10.0) return 12.0;
		if (size <= 11.5) return 13.0;
		if (size <= 15.0) return 14.0;
		if (size <= 18.0) return 16.0;
		if (size <= 22.0) return 20.0;
		return 24.0; // Page headings use a restrained 24-DIP base at Medium.
	}

	private static bool IsValidAccent(string? value)
	{
		return !string.IsNullOrWhiteSpace(value) && System.Text.RegularExpressions.Regex.IsMatch(value, "^#[0-9A-Fa-f]{6}$");
	}

	private static string EnsureTextContrastAcross(string foreground, double minimumRatio, params string[] backgrounds)
	{
		var validBackgrounds = backgrounds
			.Where(background => IsValidAccent(background))
			.Distinct(StringComparer.OrdinalIgnoreCase)
			.ToArray();
		if (validBackgrounds.Length == 0)
			return foreground;
		double WorstRatio(string candidate) => validBackgrounds.Min(background => ColorContrastRatio(candidate, background));
		if (WorstRatio(foreground) >= minimumRatio)
			return foreground;

		var target = WorstRatio("#FFFFFF") >= WorstRatio("#000000") ? "#FFFFFF" : "#000000";
		for (var step = 1; step <= 100; step++)
		{
			var candidate = BlendHex(target, foreground, step / 100.0);
			if (WorstRatio(candidate) >= minimumRatio)
				return candidate;
		}
		return target;
	}
private static string EnsureTextContrast(string foreground, string background, double minimumRatio)
	{
		if (ColorContrastRatio(foreground, background) >= minimumRatio)
			return foreground;

		var target = ColorContrastRatio("#FFFFFF", background) >= ColorContrastRatio("#000000", background)
			? "#FFFFFF" : "#000000";
		for (var step = 1; step <= 100; step++)
		{
			var candidate = BlendHex(target, foreground, step / 100.0);
			if (ColorContrastRatio(candidate, background) >= minimumRatio)
				return candidate;
		}
		return target;
	}

	private static double ColorContrastRatio(string foreground, string background)
	{
		static double Channel(byte channel)
		{
			var value = channel / 255.0;
			return value <= 0.04045 ? value / 12.92 : Math.Pow((value + 0.055) / 1.055, 2.4);
		}
		static double Luminance(Color color) =>
			0.2126 * Channel(color.R) + 0.7152 * Channel(color.G) + 0.0722 * Channel(color.B);

		var first = Luminance(ParseColor(foreground));
		var second = Luminance(ParseColor(background));
		return (Math.Max(first, second) + 0.05) / (Math.Min(first, second) + 0.05);
	}

	private static string BlendHex(string foreground, string background, double amount)
	{
		Color front = ParseColor(foreground);
		Color back = ParseColor(background);
		byte r = (byte)Math.Clamp(Math.Round(front.R * amount + back.R * (1 - amount)), 0, 255);
		byte g = (byte)Math.Clamp(Math.Round(front.G * amount + back.G * (1 - amount)), 0, 255);
		byte b = (byte)Math.Clamp(Math.Round(front.B * amount + back.B * (1 - amount)), 0, 255);
		return $"#{r:X2}{g:X2}{b:X2}";
	}

	private static string AccentTextHex(string hex)
	{
		Color color = ParseColor(hex);
		static double LinearChannel(byte channel)
		{
			double value = channel / 255.0;
			return value <= 0.04045 ? value / 12.92 : Math.Pow((value + 0.055) / 1.055, 2.4);
		}
		double luminance = 0.2126 * LinearChannel(color.R) + 0.7152 * LinearChannel(color.G) + 0.0722 * LinearChannel(color.B);
		double darkLuminance = 0.005605;
		double darkContrast = (Math.Max(luminance, darkLuminance) + 0.05) / (Math.Min(luminance, darkLuminance) + 0.05);
		double lightContrast = 1.05 / (luminance + 0.05);
		return darkContrast >= lightContrast ? "#111111" : "#FFFFFF";
	}

	private static Color ParseColor(string hex)
	{
		string text = hex.TrimStart('#');
		return ColorHelper.FromArgb(byte.MaxValue, byte.Parse(text.Substring(0, 2), NumberStyles.HexNumber, CultureInfo.InvariantCulture), byte.Parse(text.Substring(2, 2), NumberStyles.HexNumber, CultureInfo.InvariantCulture), byte.Parse(text.Substring(4, 2), NumberStyles.HexNumber, CultureInfo.InvariantCulture));
	}

	private string SettingString(string key, string fallback = "")
	{
		return _settings?.Values[key]?.ToString() ?? fallback;
	}

	private bool SettingBool(string key, bool fallback = false)
	{
		JsonNode? jsonNode = _settings?.Values[key];
		if (jsonNode == null)
		{
			return fallback;
		}
		if (bool.TryParse(jsonNode.ToString(), out var result))
		{
			return result;
		}
		return jsonNode.ToString() == "1";
	}

	private double SettingNumber(string key, double fallback = 0.0)
	{
		JsonNode? jsonNode = _settings?.Values[key];
		double result;
		return (jsonNode != null && double.TryParse(jsonNode.ToString(), NumberStyles.Any, CultureInfo.InvariantCulture, out result)) ? result : fallback;
	}

	private void SetSetting(string key, object? value)
	{
		if (_settings != null)
		{
			_settings.Values[key] = ((value == null) ? null : JsonSerializer.SerializeToNode(value));
		}
	}

	private async Task SaveCaptureSettingsAsync()
	{
		if (_settings == null)
			throw new InvalidOperationException("Settings have not loaded yet.");

		var values = _settings.Values.DeepClone() as JsonObject ?? new JsonObject();
		var mode = _liveModeInput?.SelectedIndex == 1 ? "file" : SettingString("mode", "live");
		var creatorId = mode == "live" ? _liveSelectedCreatorId : null;
		var target = _liveTargetInput?.Text.Trim() ?? values["target"]?.ToString() ?? "";

		if (mode == "live" && string.IsNullOrWhiteSpace(creatorId))
			throw new InvalidOperationException("Select a saved creator before saving live settings. Each live creator has an independent settings profile.");

		if (!string.IsNullOrWhiteSpace(creatorId))
		{
			var creator = _creators.FirstOrDefault(item => item.Id == creatorId);
			if (creator is null)
				throw new InvalidOperationException("The selected creator no longer exists. Refresh the creator list and select it again.");
			if (!string.Equals(target, creator.Target, StringComparison.OrdinalIgnoreCase))
				throw new InvalidOperationException("The stream URL changed. Select its matching saved creator before saving creator-specific settings.");

			values["mode"] = "live";
			values["target"] = creator.Target;
			values["creator_id"] = creator.Id;
			await SaveCreatorSettingsAsync(creator.Id, values);
			return;
		}

		values["mode"] = mode;
		values["target"] = target;
		values.Remove("creator_id");
		await PostAsync("/api/settings", values);
		_globalSettings = values.DeepClone() as JsonObject ?? new JsonObject();
	}

	private async Task SaveCreatorSettingsAsync(string creatorId, JsonObject values)
	{
		if (_engine is null)
			throw new InvalidOperationException("The local media engine is not connected.");
		await PostAsync("/api/creators/settings/save", new JsonObject
		{
			["id"] = creatorId,
			["settings"] = values.DeepClone()
		});

		// The backend persists provider, layout/aspect and clipping keys globally.
		// Mirror only that same shared subset locally: never copy creator framing,
		// subtitle styling, or profanity treatment into the local-video snapshot.
		_globalSettings ??= new JsonObject();
		foreach (var key in new[]
		{
			"transcriber_provider", "transcriber_command", "transcriber_language", "model",
			"compute_device", "cpu_threads", "language", "clips_per_chunk", "chunk_min",
			"pre", "post", "min_score", "capture_bitrate_kbps", "delete_rec",
			"layout", "output_format"
		})
		{
			if (values.TryGetPropertyValue(key, out var sharedValue))
				_globalSettings[key] = sharedValue?.DeepClone();
		}
	}


    private Border CreateCreatorAvatar(string creatorName, double size = 34, bool active = false)
    {
        var trimmed = (creatorName ?? string.Empty).Trim();
        var initial = trimmed.Length > 0
            ? System.Globalization.StringInfo.GetNextTextElement(trimmed).ToUpperInvariant()
            : "C";

        var label = Txt(initial, Math.Max(12, size * 0.38), true);
        label.TextAlignment = TextAlignment.Center;
        label.HorizontalAlignment = HorizontalAlignment.Stretch;
        label.VerticalAlignment = VerticalAlignment.Center;
        label.TextWrapping = TextWrapping.NoWrap;
        label.Margin = new Thickness(0);
        label.Padding = new Thickness(0);
        label.Foreground = Application.Current.Resources["PrimaryTextBrush"] as Brush;

        var content = new Grid
        {
            Width = size - 2,
            Height = size - 2,
            MinWidth = size - 2,
            MinHeight = size - 2,
            HorizontalAlignment = HorizontalAlignment.Center,
            VerticalAlignment = VerticalAlignment.Center
        };
        content.Children.Add(label);
        Grid.SetRow(label, 0);
        Grid.SetColumn(label, 0);

        return new Border
        {
            Width = size,
            Height = size,
            MinWidth = size,
            MinHeight = size,
            Padding = new Thickness(0),
            CornerRadius = new CornerRadius(size <= 32 ? 8 : 10),
            Background = Application.Current.Resources[active ? "AccentSoftBrush" : "SurfaceSoftBrush"] as Brush,
            BorderBrush = Application.Current.Resources[active ? "AccentTextBrush" : "LineBrush"] as Brush,
            BorderThickness = new Thickness(1),
            HorizontalAlignment = HorizontalAlignment.Center,
            VerticalAlignment = VerticalAlignment.Center,
            Child = content
        };
    }

	private static TextBlock Txt(string text, double size = 12.0, bool strong = false, string? color = null)
	{
		TextBlock textBlock = new TextBlock
		{
			Text = text,
			FontFamily = ActiveFontFamily,
			FontSize = UiFontSize(size),
			FontWeight = (strong ? FontWeights.SemiBold : FontWeights.Normal),
			TextWrapping = TextWrapping.Wrap
		};
		ApplyFontSizeToElement(textBlock, textBlock.FontSize, size => textBlock.FontSize = size);
		if (!string.IsNullOrWhiteSpace(color))
		{
			var textRoleKey = color switch
			{
				"AccentBrush" => "AccentTextBrush",
				"SuccessBrush" => "SuccessTextBrush",
				"WarningBrush" => "WarningTextBrush",
				"DangerBrush" => "DangerTextBrush",
				_ => color
			};
			if (Application.Current.Resources.TryGetValue(textRoleKey, out var resource) && resource is Brush resourceBrush)
			{
				textBlock.Foreground = resourceBrush;
			}
			else
			{
				var legacyKey = color.ToUpperInvariant() switch
				{
					"#9CDEF2" => "MutedTextBrush",
					"#C8D5DC" => "BodyTextBrush",
					"#E8F0F4" => "PrimaryTextBrush",
					"#80C99A" => "SuccessTextBrush",
					"#E6B96F" => "WarningTextBrush",
					"#E06C75" => "DangerTextBrush",
					_ => null
				};
				if (legacyKey is not null && Application.Current.Resources[legacyKey] is Brush legacyBrush)
					textBlock.Foreground = legacyBrush;
				else if (IsValidAccent(color))
				{
					var accentBrush = Application.Current.Resources["AccentBrush"] as SolidColorBrush;
					var successBrush = Application.Current.Resources["SuccessBrush"] as SolidColorBrush;
					var warningBrush = Application.Current.Resources["WarningBrush"] as SolidColorBrush;
					var dangerBrush = Application.Current.Resources["DangerBrush"] as SolidColorBrush;
					var role = accentBrush?.Color == ParseColor(color) ? "AccentTextBrush"
						: successBrush?.Color == ParseColor(color) ? "SuccessTextBrush"
						: warningBrush?.Color == ParseColor(color) ? "WarningTextBrush"
						: dangerBrush?.Color == ParseColor(color) ? "DangerTextBrush" : null;
					if (role is not null && Application.Current.Resources[role] is Brush roleBrush)
						textBlock.Foreground = roleBrush;
					else
					{
						var accessible = EnsureTextContrastAcross(color, 4.5,
							ResourceBrushHex("AppBackgroundBrush", "#0F0F0F"),
							ResourceBrushHex("SurfaceBrush", "#181818"),
							ResourceBrushHex("SurfaceSoftBrush", "#212121"),
							ResourceBrushHex("SurfaceHoverBrush", "#2B2B2B"));
						textBlock.Foreground = new SolidColorBrush(ParseColor(accessible));
					}
				}
				else
					textBlock.Foreground = Application.Current.Resources["BodyTextBrush"] as Brush;
			}
		}
		else
		{
			textBlock.Foreground = Application.Current.Resources["BodyTextBrush"] as Brush;
		}
		return textBlock;
	}

	private static string ResourceBrushHex(string key, string fallback)
	{
		if (Application.Current.Resources.TryGetValue(key, out var resource) && resource is SolidColorBrush brush)
		{
			var color = brush.Color;
			return $"#{color.R:X2}{color.G:X2}{color.B:X2}";
		}
		return fallback;
	}

	private Button CreateButton(string label, Action action, bool primary = false, bool danger = false)
	{
		Button button = new Button();
		button.Content = label;
		button.FontFamily = CurrentFont;
		button.FontSize = 14.0;
		ApplyFontSizeToElement(button, button.FontSize, size => button.FontSize = size);
		button.Padding = new Thickness(18.0, 10.0, 18.0, 10.0);
		button.MinHeight = 48.0;
		button.CornerRadius = new CornerRadius(8.0);
		Button button2 = button;
		ResourceDictionary resources = Application.Current.Resources;
		string key;
		if (primary)
		{
			key = "AccentBrush";
		}
		else
		{
			key = (danger ? "SurfaceSoftBrush" : "SurfaceBrush");
		}
		button2.Background = resources[key] as Brush;
		button.Foreground = (primary ? (Application.Current.Resources["AccentInkBrush"] as Brush) : (Application.Current.Resources[danger ? "DangerTextBrush" : "BodyTextBrush"] as Brush));
		button.BorderBrush = Application.Current.Resources[danger ? "DangerBrush" : "LineBrush"] as Brush;
		button.BorderThickness = new Thickness(1.0);
		button.HorizontalAlignment = HorizontalAlignment.Left;
		Button button3 = button;
		button3.Click += (object _, RoutedEventArgs _) =>
		{
			action();
		};
		return button3;
	}

	private TextBox Input(string text = "", string placeholder = "", bool multiline = false)
	{
		TextBox textBox = new TextBox();
		textBox.Text = text;
		textBox.PlaceholderText = placeholder;
		textBox.FontFamily = CurrentFont;
		textBox.FontSize = 14.0;
		ApplyFontSizeToElement(textBox, textBox.FontSize, size => textBox.FontSize = size);
		textBox.MinHeight = (multiline ? 148 : 48);
		textBox.AcceptsReturn = multiline;
		textBox.TextWrapping = ((!multiline) ? TextWrapping.NoWrap : TextWrapping.Wrap);
		textBox.VerticalContentAlignment = ((!multiline) ? VerticalAlignment.Center : VerticalAlignment.Top);
		textBox.Background = Application.Current.Resources["SurfaceSoftBrush"] as Brush;
		textBox.Foreground = Application.Current.Resources["PrimaryTextBrush"] as Brush;
		textBox.BorderBrush = Application.Current.Resources["LineBrush"] as Brush;
		return textBox;
	}

	private static StackPanel ActionRow(params UIElement[] children)
	{
		StackPanel stackPanel = new StackPanel
		{
			Orientation = Orientation.Horizontal,
			Spacing = 10.0
		};
		foreach (UIElement item in children)
		{
			stackPanel.Children.Add(item);
		}
		return stackPanel;
	}

	private static StackPanel Vertical(params UIElement[] children)
	{
		StackPanel stackPanel = new StackPanel
		{
			Spacing = 12.0
		};
		foreach (UIElement item in children)
		{
			stackPanel.Children.Add(item);
		}
		return stackPanel;
	}

	private static Border CreatePanel(string title, string description, UIElement content)
	{
		StackPanel stackPanel = new StackPanel
		{
			Spacing = 18.0
		};
		stackPanel.Children.Add(Txt(title, 20.0, strong: true));
		if (!string.IsNullOrWhiteSpace(description))
		{
			stackPanel.Children.Add(Txt(description, 14.0, strong: false, "BodyTextBrush"));
		}
		stackPanel.Children.Add(content);
		Border border = new Border();
		border.Background = Application.Current.Resources["SurfaceBrush"] as Brush;
		border.BorderBrush = Application.Current.Resources["LineBrush"] as Brush;
		border.BorderThickness = new Thickness(1.0);
		border.CornerRadius = new CornerRadius(12.0);
		border.Padding = new Thickness(26.0);
		border.Child = stackPanel;
		return border;
	}

	private static void AddLabeled(StackPanel parent, string label, UIElement control, string? hint = null)
	{
		StackPanel stackPanel = new StackPanel
		{
			Spacing = 7.0
		};
		stackPanel.Children.Add(Txt(label, 14.0, strong: true));
		stackPanel.Children.Add(control);
		if (!string.IsNullOrWhiteSpace(hint))
		{
			stackPanel.Children.Add(Txt(hint, 14.0, strong: false, "BodyTextBrush"));
		}
		parent.Children.Add(stackPanel);
	}

	private static Grid TwoColumns(FrameworkElement left, FrameworkElement right, double leftWeight = 1.0, double rightWeight = 1.0)
	{
		Grid grid = new Grid
		{
			ColumnSpacing = 20.0
		};
		grid.ColumnDefinitions.Add(new ColumnDefinition
		{
			Width = new GridLength(leftWeight, GridUnitType.Star)
		});
		grid.ColumnDefinitions.Add(new ColumnDefinition
		{
			Width = new GridLength(rightWeight, GridUnitType.Star)
		});
		Grid.SetColumn(right, 1);
		grid.Children.Add(left);
		grid.Children.Add(right);
		return grid;
	}

	private void AddPageHeading(string title, string description)
	{
		var heading = new StackPanel { Spacing = 10.0 };
		heading.Children.Add(Txt(title, 30.0, strong: true));
		heading.Children.Add(Txt(description, 14.0, strong: false, "BodyTextBrush"));
		PageHost.Children.Add(heading);
	}

	private void SetBusy(Button button, bool busy, string normalText, string busyText)
	{
		button.IsEnabled = !busy;
		button.Content = (busy ? busyText : normalText);
	}

	private async Task OpenPath(string path)
	{
		try
		{
			if (!Directory.Exists(path))
			{
				await ShowErrorAsync("Folder not found", path);
				return;
			}
			Process.Start(new ProcessStartInfo("explorer.exe", path)
			{
				UseShellExecute = true
			});
		}
		catch (Exception ex)
		{
			await ShowErrorAsync("Could not open folder", ex.Message);
		}
	}

	private async Task DialogResultAsync(string title, string message)
	{
		if ((object)XamlRoot != null)
		{
			ContentDialog dialog = new ContentDialog
			{
				XamlRoot = XamlRoot,
				Title = title,
				Content = new TextBlock
				{
					Text = message,
					TextWrapping = TextWrapping.Wrap,
					FontFamily = CurrentFont,
					FontSize = ScaledFontSize(12),
					MaxWidth = 520.0
				},
				CloseButtonText = "Close"
			};
			await dialog.ShowAsync();
		}
	}
}
