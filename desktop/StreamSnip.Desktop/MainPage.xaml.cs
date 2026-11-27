using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
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
using Microsoft.UI.Xaml.Shapes;
using WinRT.Interop;
using Windows.Media.Core;
using Windows.Storage;
using Windows.Storage.Pickers;
using Windows.UI;

namespace StreamSnip_Desktop;

public sealed partial class MainPage : Page
{











































	private sealed record ThemePalette(string Id, string Name, string App, string Surface, string Soft, string Hover, string Sidebar, string Ink, string Body, string Muted, string Line, string Accent, string Success, string Warning, string Danger);

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

	private const string JetBrainsFontUri = "ms-appx:///Assets/Fonts/JetBrainsMono-Variable.ttf#JetBrains Mono";

	private static readonly FontFamily JetBrainsFontFamily = new FontFamily("ms-appx:///Assets/Fonts/JetBrainsMono-Variable.ttf#JetBrains Mono");

	private static FontFamily ActiveFontFamily = JetBrainsFontFamily;

	private bool _refreshRunning;

	private string _theme = "odysseus";
	private string _customAccent = "";

	private string _fontName = "JetBrains Mono";

	private string _lastEngineMessage = "";
	private Border? _clipBadgeBorder;
	private TextBlock? _clipBadgeText;
	private Border? _creatorBadgeBorder;
	private TextBlock? _creatorBadgeText;

	private readonly string _preferencesPath = System.IO.Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "StreamSnip AI", "desktop-preferences.json");

	private static readonly ThemePalette[] Themes = new ThemePalette[12]
	{
		new ThemePalette("odysseus", "Odysseus", "#282C34", "#1B2028", "#232B35", "#2D3743", "#171C23", "#E8F0F4", "#C8D5DC", "#9CDEF2", "#355A66", "#E06C75", "#80C99A", "#E6B96F", "#E06C75"),
		new ThemePalette("studio-light", "Studio Light", "#F9F9F9", "#FFFFFF", "#F5F5F5", "#EFEFEF", "#FFFFFF", "#0F0F0F", "#303030", "#606060", "#E5E5E5", "#CC0000", "#137333", "#A15C00", "#B3261E"),
		new ThemePalette("studio-dark", "Studio Dark", "#0F0F0F", "#181818", "#212121", "#2B2B2B", "#0F0F0F", "#F1F1F1", "#D6D6D6", "#AAAAAA", "#303030", "#FF0033", "#81C995", "#F6C26B", "#F28B82"),
		new ThemePalette("github", "GitHub Dark", "#0D1117", "#161B22", "#21262D", "#292F38", "#010409", "#E6EDF3", "#C9D1D9", "#8B949E", "#30363D", "#F85149", "#3FB950", "#D29922", "#F85149"),
		new ThemePalette("nord", "Nord", "#2E3440", "#3B4252", "#434C5E", "#4C566A", "#2E3440", "#ECEFF4", "#D8DEE9", "#88C0D0", "#4C566A", "#88C0D0", "#A3BE8C", "#EBCB8B", "#BF616A"),
		new ThemePalette("odysseas", "Odysseus Paper", "#EDF0EC", "#FFFEFA", "#F5F6F2", "#E9EDE8", "#142838", "#172631", "#42515A", "#637277", "#D9DFD9", "#EF6A42", "#327B62", "#A9752D", "#C74E47"),
		new ThemePalette("ocean", "Ocean Depths", "#101C27", "#162635", "#1E3242", "#294153", "#0C1721", "#EDF5FA", "#C5D4DE", "#9AB3C1", "#2D4656", "#42B9CC", "#83C99A", "#E4BF72", "#E9877F"),
		new ThemePalette("forest", "Forest Night", "#111B17", "#182720", "#22352B", "#30483A", "#0C1511", "#EAF4ED", "#C5D8CA", "#9CBAA4", "#2E4737", "#83C99A", "#83C99A", "#E4BD69", "#E9857B"),
		new ThemePalette("solarized", "Solarized Paper", "#F6F2E8", "#FFFDF6", "#F0EADC", "#E8E0CD", "#EEE8D8", "#28383A", "#44585B", "#687F7C", "#D9D2C0", "#277A78", "#42856D", "#A9682A", "#BD5947"),
		new ThemePalette("rose-graphite", "Rose Graphite", "#211C20", "#2C242A", "#362B33", "#463640", "#1A1519", "#F4EDF0", "#DBCBD3", "#C39DAB", "#49353F", "#DD8EA4", "#8ABF9A", "#E2B36E", "#EF8790"),
		new ThemePalette("ember", "Ember Studio", "#1D1A16", "#28231D", "#332C23", "#41362A", "#17130F", "#F2EDE5", "#D7C9B7", "#BCA588", "#4A3B2A", "#E8A34B", "#99C68C", "#E8A34B", "#E57D68"),
		new ThemePalette("slate", "Slate Studio", "#20262D", "#272F38", "#313B45", "#3D4853", "#181E24", "#EEF2F5", "#CAD2D9", "#AAB7C2", "#3C4853", "#8BB9D8", "#8EC7A1", "#E0BC77", "#E28B85")
	};

	private static readonly string[] FontChoices = new string[15]
	{
		"JetBrains Mono", "Segoe UI", "Google Sans", "Inter", "Roboto", "Open Sans", "Montserrat", "Poppins", "Lato", "Nunito Sans", "DM Sans",
		"IBM Plex Sans", "Space Grotesk", "Fira Code", "Consolas"
	};

	private FontFamily CurrentFont => ActiveFontFamily;







































	public MainPage()
	{
		InitializeComponent();
		Loaded += Page_Loaded;
		Unloaded += Page_Unloaded;
		LoadPreferences();
		ApplyTheme(_theme);
		ApplyFont(_fontName);
		InitializeNavigationBadges();
		RegisterSearchShortcuts();
	}

	private async void Page_Loaded(object sender, RoutedEventArgs e)
	{
		ApplyFontToVisualTree(this);
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
		border.Background = new SolidColorBrush(ParseColor(theme.Soft));
		border.BorderBrush = new SolidColorBrush(ParseColor(live ? theme.Accent : theme.Line));
		text.Foreground = new SolidColorBrush(ParseColor(live ? theme.Accent : theme.Muted));
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
            NavPublishedButton, NavWordsButton, NavPublishingButton, NavSettingsButton,
            NavActivityButton, NavHelpButton, NavAboutButton
        };
        var theme = Themes.FirstOrDefault(x => x.Id == _theme) ?? Themes[0];
        var transparent = new SolidColorBrush(ColorHelper.FromArgb(0, 0, 0, 0));

        foreach (var button in items)
        {
            var selected = string.Equals(button.Tag as string, _currentPage, StringComparison.Ordinal);
            button.Background = selected
                ? new SolidColorBrush(ParseColor(theme.Soft))
                : transparent;
            button.Foreground = Application.Current.Resources[
                selected ? "PrimaryTextBrush" : "BodyTextBrush"] as Brush;
            button.BorderBrush = selected
                ? new SolidColorBrush(ParseColor(theme.Accent))
                : transparent;
            button.BorderThickness = new Thickness(1);
        }
        UpdateSidebarBadges();
    }

    private void NavigateTo(string page)
    {
        _currentPage = page;
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

	private void AppearanceButton_Click(object sender, RoutedEventArgs e)
	{
		var panel = new StackPanel { Width = 292, Spacing = 5, Padding = new Thickness(12) };
		panel.Children.Add(Txt("Appearance", 13, true));
		panel.Children.Add(Txt("Choose your workspace palette.", 10, false, "#9CDEF2"));

		var flyout = new Flyout
		{
			Content = new Border
			{
				Background = Application.Current.Resources["SurfaceBrush"] as Brush,
				BorderBrush = Application.Current.Resources["LineBrush"] as Brush,
				BorderThickness = new Thickness(1),
				CornerRadius = new CornerRadius(12),
				Child = panel
			}
		};

		foreach (var theme in Themes)
		{
			var row = new Grid { ColumnSpacing = 10, Padding = new Thickness(7, 7, 7, 7) };
			row.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
			row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
			row.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });

			var swatches = new StackPanel
			{
				Orientation = Orientation.Horizontal,
				Spacing = 3,
				VerticalAlignment = VerticalAlignment.Center
			};
			foreach (var color in new[] { theme.App, theme.Surface, theme.Sidebar, theme.Accent })
			{
				swatches.Children.Add(new Border
				{
					Width = 12,
					Height = 22,
					CornerRadius = new CornerRadius(4),
					Background = new SolidColorBrush(ParseColor(color)),
					BorderBrush = new SolidColorBrush(ParseColor(theme.Line)),
					BorderThickness = new Thickness(1)
				});
			}
			row.Children.Add(swatches);

			var copy = new StackPanel { Spacing = 1, VerticalAlignment = VerticalAlignment.Center };
			copy.Children.Add(Txt(theme.Name, 11, true));
			copy.Children.Add(Txt(theme.Id switch
			{
				"odysseus" => "Graphite · arctic cyan · coral",
				"github" => "Midnight slate · signal red",
				"studio-light" => "Clean neutral · signal red",
				"studio-dark" => "Low-light charcoal · vivid red",
				"nord" => "Blue-gray · frost · soft cyan",
				"odysseas" => "Navy · chalk · warm orange",
				"ocean" => "Deep blue · sea glass · cyan",
				"forest" => "Evergreen · moss · mint",
				"solarized" => "Warm parchment · ink · teal",
				"rose-graphite" => "Warm charcoal · muted rose",
				"ember" => "Dark umber · copper · amber",
				"slate" => "Cool graphite · steel blue",
				_ => "Graphite workspace"
			}, 9, false, "#9CDEF2"));
			Grid.SetColumn(copy, 1);
			row.Children.Add(copy);

			if (theme.Id == _theme)
			{
				var check = Txt("✓", 14, true, theme.Accent);
				check.VerticalAlignment = VerticalAlignment.Center;
				Grid.SetColumn(check, 2);
				row.Children.Add(check);
			}

			var option = new Button
			{
				Content = row,
				HorizontalAlignment = HorizontalAlignment.Stretch,
				HorizontalContentAlignment = HorizontalAlignment.Stretch,
				Background = new SolidColorBrush(ParseColor(theme.Id == _theme ? theme.Soft : "#00000000")),
				BorderBrush = new SolidColorBrush(ParseColor("#00000000")),
				BorderThickness = new Thickness(0),
				Padding = new Thickness(0),
				MinHeight = 46
			};
			option.Click += (_, _) =>
			{
				ApplyTheme(theme.Id);
				UpdateSidebarSelection();
				RenderCurrentPage();
				flyout.Hide();
			};
			panel.Children.Add(option);
		}

		panel.Children.Add(Txt("Custom accent color", 11, true));
		var accentInput = Input(IsValidAccent(_customAccent) ? _customAccent : Themes.First(t => t.Id == _theme).Accent, "#RRGGBB");
		panel.Children.Add(accentInput);
		panel.Children.Add(ActionRow(
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
				UpdateSidebarSelection();
				RenderCurrentPage();
				flyout.Hide();
			}, primary: true),
			CreateButton("Reset", () =>
			{
				_customAccent = "";
				ApplyTheme(_theme);
				UpdateSidebarSelection();
				RenderCurrentPage();
				flyout.Hide();
			})));
		flyout.ShowAt(AppearanceButton);
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
		{
			return;
		}
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
		{
			return;
		}
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
				_fontName = jsonObject?["font"]?.GetValue<string>() ?? _fontName;
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
				["font"] = _fontName
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
		SetResourceBrush("PrimaryTextBrush", themePalette.Ink);
		SetResourceBrush("BodyTextBrush", themePalette.Body);
		SetResourceBrush("MutedTextBrush", themePalette.Muted);
		SetResourceBrush("LineBrush", themePalette.Line);
		string accent = IsValidAccent(_customAccent) ? _customAccent : themePalette.Accent;
		SetResourceBrush("AccentBrush", accent);
		SetResourceBrush("AccentSoftBrush", BlendHex(accent, themePalette.Surface, 0.16));
		SetResourceBrush("AccentInkBrush", AccentTextHex(accent));
		SetResourceBrush("SuccessBrush", themePalette.Success);
		SetResourceBrush("WarningBrush", themePalette.Warning);
		SetResourceBrush("DangerBrush", themePalette.Danger);
		RootBackgroundUpdate();
		SavePreferences();
	}

	private static void SetResourceBrush(string key, string hex)
	{
		Color color = ParseColor(hex);
		if (Application.Current.Resources.TryGetValue(key, out var value) && value is SolidColorBrush solidColorBrush)
		{
			solidColorBrush.Color = color;
		}
		else
		{
			Application.Current.Resources[key] = new SolidColorBrush(color);
		}
	}

	private void RootBackgroundUpdate()
	{
		Background = new SolidColorBrush(ParseColor(Themes.First((ThemePalette t) => t.Id == _theme).App));
		SidebarRoot.Background = new SolidColorBrush(ParseColor(Themes.First((ThemePalette t) => t.Id == _theme).Sidebar));
	}

	private void ApplyFont(string fontName)
	{
		_fontName = FontChoices.Contains(fontName) ? fontName : "JetBrains Mono";
		ActiveFontFamily = _fontName == "JetBrains Mono" ? JetBrainsFontFamily : new FontFamily(_fontName);
		Application.Current.Resources["AppFont"] = ActiveFontFamily;
		SavePreferences();
		if (XamlRoot is not null)
			ApplyFontToVisualTree(this);
	}

	private static void ApplyFontToVisualTree(DependencyObject root)
	{
		if (root is TextBlock textBlock)
			textBlock.FontFamily = ActiveFontFamily;
		if (root is Control control)
			control.FontFamily = ActiveFontFamily;

		var childCount = Microsoft.UI.Xaml.Media.VisualTreeHelper.GetChildrenCount(root);
		for (var index = 0; index < childCount; index++)
			ApplyFontToVisualTree(Microsoft.UI.Xaml.Media.VisualTreeHelper.GetChild(root, index));
	}

	private static double UiFontSize(double size)
	{
		// Slightly tightened native desktop type scale while preserving hierarchy.
		if (size <= 9.0) return 13.0;
		if (size <= 10.0) return 13.5;
		if (size <= 11.5) return 14.0;
		if (size <= 13.0) return 15.0;
		if (size <= 15.0) return 16.5;
		if (size <= 18.0) return 19.0;
		if (size <= 22.0) return 24.0;
		if (size <= 26.0) return 29.0;
		return Math.Max(13.0, Math.Round(size * 1.18, 1) - 1.0);
	}

	private static bool IsValidAccent(string? value)
	{
		return !string.IsNullOrWhiteSpace(value) && System.Text.RegularExpressions.Regex.IsMatch(value, "^#[0-9A-Fa-f]{6}$");
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
		{
			throw new InvalidOperationException("Settings have not loaded yet.");
		}
		await PostAsync("/api/settings", (_settings.Values.DeepClone() as JsonObject) ?? new JsonObject());
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
		if (!string.IsNullOrWhiteSpace(color))
		{
			if (Application.Current.Resources.TryGetValue(color, out var resource) && resource is Brush resourceBrush)
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
					"#80C99A" => "SuccessBrush",
					"#E6B96F" => "WarningBrush",
					"#E06C75" => "DangerBrush",
					_ => null
				};
				textBlock.Foreground = legacyKey is not null &&
					Application.Current.Resources[legacyKey] is Brush legacyBrush
					? legacyBrush
					: new SolidColorBrush(ParseColor(color));
			}
		}
		else
		{
			textBlock.Foreground = Application.Current.Resources["BodyTextBrush"] as Brush;
		}
		return textBlock;
	}

	private Button CreateButton(string label, Action action, bool primary = false, bool danger = false)
	{
		Button button = new Button();
		button.Content = label;
		button.FontFamily = CurrentFont;
		button.FontSize = 15.0;
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
		button.Foreground = (primary ? (Application.Current.Resources["AccentInkBrush"] as Brush) : (Application.Current.Resources[danger ? "DangerBrush" : "BodyTextBrush"] as Brush));
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
		textBox.FontSize = 15.0;
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
					MaxWidth = 520.0
				},
				CloseButtonText = "Close"
			};
			await dialog.ShowAsync();
		}
	}
}
