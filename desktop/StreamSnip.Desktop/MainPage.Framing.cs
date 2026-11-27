using System;
using System.Text.Json.Nodes;
using Microsoft.UI;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Imaging;
using Windows.Foundation;
using Windows.Storage.Streams;
using Windows.UI;

namespace StreamSnip_Desktop;

public sealed partial class MainPage
{
    private Image? _framingImage;
    private Canvas? _framingCanvas;
    private Grid? _framingStage;
    private Border? _facecamRegion;
    private Border? _gameRegion;
    private Border? _facecamResizeHandle;
    private Border? _gameResizeHandle;
    private TextBlock? _framingStatus;
    private TextBlock? _framingValues;
    private TextBlock? _framingResultSummary;
    private BitmapImage? _framingBitmap;
    private double _framingAspectRatio = 16.0 / 9.0;

    private double _framingCamX = 70.0;
    private double _framingCamY = 4.0;
    private double _framingCamW = 29.0;
    private double _framingCamH = 37.0;
    private double _framingGameX = 23.6;
    private double _framingGameY = 0.0;
    private double _framingGameW = 52.8;
    private double _framingGameH = 100.0;
    private bool _framingValuesInitialized;

    private string? _framingDragRegion;
    private bool _framingDragResize;
    private Point _framingDragStartPoint;
    private double _framingStartX;
    private double _framingStartY;
    private double _framingStartW;
    private double _framingStartH;

    private UIElement BuildFramingTab()
    {
        EnsureFramingValues();

        var root = new StackPanel
        {
            Spacing = 12,
            Padding = new Thickness(4, 12, 4, 4)
        };
        _framingResultSummary = ThemeText(
            _liveSelectedCreatorId is null
                ? "Local video framing"
                : $"Selected creator: {_creators.FirstOrDefault(item => item.Id == _liveSelectedCreatorId)?.Name ?? "Creator"}",
            13, true, "PrimaryTextBrush");
        root.Children.Add(_framingResultSummary);
        root.Children.Add(ThemeText(
            "Framing is saved separately for this creator. Video layout and output format are shared clipping defaults in the Capture tab. Pink = facecam; cyan = gameplay.",
            12, false, "MutedTextBrush"));

        var editor = new Grid
        {
            ColumnSpacing = 18,
            VerticalAlignment = VerticalAlignment.Top
        };
        editor.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        editor.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(300) });

        _framingStage = new Grid
        {
            Height = 360,
            MinHeight = 180,
            MaxHeight = 520,
            Background = Application.Current.Resources["SurfaceSoftBrush"] as Brush
        };
        _framingImage = new Image
        {
            Stretch = Stretch.Fill,
            HorizontalAlignment = HorizontalAlignment.Stretch,
            VerticalAlignment = VerticalAlignment.Stretch
        };
        if (_framingBitmap is not null)
            _framingImage.Source = _framingBitmap;
        _framingStage.Children.Add(_framingImage);

        var placeholder = new StackPanel
        {
            Spacing = 8,
            HorizontalAlignment = HorizontalAlignment.Center,
            VerticalAlignment = VerticalAlignment.Center,
            IsHitTestVisible = false
        };
        placeholder.Children.Add(new PathIcon
        {
            Data = CreateVideoIconGeometry(),
            Width = 22,
            Height = 22,
            Foreground = Application.Current.Resources["MutedTextBrush"] as Brush
        });
        placeholder.Children.Add(ThemeText("Load a source frame", 14, true, "PrimaryTextBrush"));
        placeholder.Children.Add(ThemeText("Use the selected stream or local VOD.", 11, false, "MutedTextBrush"));
        placeholder.Name = "FramingPlaceholder";
        _framingStage.Children.Add(placeholder);
        placeholder.Visibility = _framingBitmap is null ? Visibility.Visible : Visibility.Collapsed;

        _framingCanvas = new Canvas
        {
            Background = new SolidColorBrush(Colors.Transparent),
            HorizontalAlignment = HorizontalAlignment.Stretch,
            VerticalAlignment = VerticalAlignment.Stretch,
            Visibility = _framingBitmap is null ? Visibility.Collapsed : Visibility.Visible
        };
        _framingCanvas.PointerMoved += FramingCanvas_PointerMoved;
        _framingCanvas.PointerReleased += FramingCanvas_PointerReleased;
        _framingCanvas.PointerCanceled += FramingCanvas_PointerCanceled;
        _framingCanvas.PointerCaptureLost += FramingCanvas_PointerCaptureLost;
        _framingStage.Children.Add(_framingCanvas);

        var gameBrush = new SolidColorBrush(ColorHelper.FromArgb(255, 60, 205, 232));
        var facecamBrush = new SolidColorBrush(ColorHelper.FromArgb(255, 255, 69, 168));
        _gameRegion = CreateFramingRegion("GAME CAPTURE", gameBrush);
        _facecamRegion = CreateFramingRegion("FACECAM", facecamBrush);
        _gameResizeHandle = CreateFramingResizeHandle(gameBrush);
        _facecamResizeHandle = CreateFramingResizeHandle(facecamBrush);

        _gameRegion.PointerPressed += (_, args) => BeginFramingDrag("game", false, args);
        _facecamRegion.PointerPressed += (_, args) => BeginFramingDrag("facecam", false, args);
        _gameResizeHandle.PointerPressed += (_, args) => BeginFramingDrag("game", true, args);
        _facecamResizeHandle.PointerPressed += (_, args) => BeginFramingDrag("facecam", true, args);

        _framingCanvas.Children.Add(_gameRegion);
        _framingCanvas.Children.Add(_facecamRegion);
        _framingCanvas.Children.Add(_gameResizeHandle);
        _framingCanvas.Children.Add(_facecamResizeHandle);

        _framingStage.SizeChanged += FramingStage_SizeChanged;
        _framingStage.Loaded += (_, _) => UpdateFramingOverlay();
        var previewBorder = new Border
        {
            Background = Application.Current.Resources["SurfaceSoftBrush"] as Brush,
            BorderBrush = Application.Current.Resources["LineBrush"] as Brush,
            BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(9),
            Padding = new Thickness(8),
            Child = _framingStage
        };
        editor.Children.Add(previewBorder);

        var actions = new StackPanel { Spacing = 10, VerticalAlignment = VerticalAlignment.Top };
        actions.Children.Add(Txt("Automatic facecam detection", 14, true));
        actions.Children.Add(ThemeText(
            "Samples multiple moments and checks stable webcam borders plus live faces. Uses GPU inference when a supported GPU is present.",
            11, false, "MutedTextBrush"));

        var loadFrameButton = CreateButton("Load source frame", async () =>
        {
            await LoadFramingFrameAsync();
        });
        loadFrameButton.IsEnabled = _engine is not null;
        actions.Children.Add(loadFrameButton);

        var detectButton = CreateButton("Find facecam automatically", async () =>
        {
            await DetectFacecamAutomaticallyAsync();
        }, primary: true);
        detectButton.IsEnabled = _engine is not null;
        actions.Children.Add(detectButton);

        actions.Children.Add(new Border
        {
            Height = 1,
            Background = Application.Current.Resources["LineBrush"] as Brush,
            Margin = new Thickness(0, 4, 0, 2)
        });
        actions.Children.Add(Txt("Manual framing", 14, true));
        actions.Children.Add(ThemeText(
            "Drag either outlined region to move it. Drag its small corner handle to resize it independently.",
            11, false, "MutedTextBrush"));

        _framingValues = ThemeText("", 11, false, "BodyTextBrush");
        _framingValues.TextWrapping = TextWrapping.Wrap;
        actions.Children.Add(_framingValues);

        var resetButton = CreateButton("Reset both regions", () =>
        {
            _framingCamX = 70.0;
            _framingCamY = 4.0;
            _framingCamW = 29.0;
            _framingCamH = 37.0;
            _framingGameX = 23.6;
            _framingGameY = 0.0;
            _framingGameW = 52.8;
            _framingGameH = 100.0;
            UpdateFramingOverlay();
            UpdateFramingValues();
        });
        actions.Children.Add(resetButton);

        var saveButton = CreateButton("Save framing", async () =>
        {
            await SaveFramingAsync();
        }, primary: true);
        saveButton.IsEnabled = _engine is not null;
        actions.Children.Add(saveButton);

        _framingStatus = ThemeText(
            _framingBitmap is null ? "Load a source frame to edit the regions." : "Ready · adjust either region and save.",
            11, false, "MutedTextBrush");
        _framingStatus.TextWrapping = TextWrapping.Wrap;
        actions.Children.Add(_framingStatus);

        Grid.SetColumn(actions, 1);
        editor.Children.Add(actions);
        root.Children.Add(editor);

        UpdateFramingValues();
        UpdateFramingOverlay();
        return root;
    }

    private Border CreateFramingRegion(string label, Brush accent)
    {
        return new Border
        {
            BorderBrush = accent,
            BorderThickness = new Thickness(2),
            Background = new SolidColorBrush(ColorHelper.FromArgb(24,
                ((SolidColorBrush)accent).Color.R,
                ((SolidColorBrush)accent).Color.G,
                ((SolidColorBrush)accent).Color.B)),
            Child = new TextBlock
            {
                Text = label,
                FontFamily = CurrentFont,
                FontSize = 10,
                FontWeight = Microsoft.UI.Text.FontWeights.SemiBold,
                Foreground = accent,
                Margin = new Thickness(7, 5, 4, 4),
                VerticalAlignment = VerticalAlignment.Top,
                HorizontalAlignment = HorizontalAlignment.Left
            }
        };
    }

    private static Border CreateFramingResizeHandle(Brush accent)
    {
        return new Border
        {
            Width = 14,
            Height = 14,
            Background = accent,
            BorderBrush = new SolidColorBrush(Colors.White),
            BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(2)
        };
    }

    private void EnsureFramingValues()
    {
        if (_framingValuesInitialized)
            return;
        _framingCamX = SettingNumber("cam_x", 70.0);
        _framingCamY = SettingNumber("cam_y", 4.0);
        _framingCamW = SettingNumber("cam_w", 29.0);
        _framingCamH = SettingNumber("cam_h", 37.0);
        _framingGameX = SettingNumber("game_area_x", 23.6);
        _framingGameY = SettingNumber("game_area_y", 0.0);
        _framingGameW = SettingNumber("game_area_w", 52.8);
        _framingGameH = SettingNumber("game_area_h", 100.0);
        _framingValuesInitialized = true;
    }

    private async Task LoadFramingFrameAsync()
    {
        if (_engine is null)
            throw new InvalidOperationException("The local media engine is not connected.");
        var target = _liveTargetInput?.Text.Trim() ?? SettingString("target");
        var mode = _liveModeInput?.SelectedIndex == 1 ? "file" : "live";
        if (string.IsNullOrWhiteSpace(target))
            throw new InvalidOperationException("Paste a stream URL or select a video file first.");

        if (_framingStatus is not null)
            _framingStatus.Text = "Loading a source frame…";
        try
        {
            var result = await _engine.PostJsonAsync("/api/frame", new JsonObject
            {
                ["mode"] = mode,
                ["target"] = target
            }, _shutdown.Token);
            var dataUrl = result["image"]?.ToString() ?? "";
            var comma = dataUrl.IndexOf(',');
            var encoded = comma >= 0 ? dataUrl[(comma + 1)..] : dataUrl;
            if (string.IsNullOrWhiteSpace(encoded))
                throw new InvalidOperationException("The source frame response was empty.");

            var bytes = Convert.FromBase64String(encoded);
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
            _framingBitmap = bitmap;
            _framingAspectRatio = bitmap.PixelHeight > 0
                ? (double)bitmap.PixelWidth / bitmap.PixelHeight
                : 16.0 / 9.0;
            if (_framingImage is not null)
                _framingImage.Source = bitmap;
            if (_framingCanvas is not null)
                _framingCanvas.Visibility = Visibility.Visible;
            if (_framingStage is not null)
            {
                foreach (var child in _framingStage.Children)
                {
                    if (child is StackPanel placeholder && placeholder.Name == "FramingPlaceholder")
                        placeholder.Visibility = Visibility.Collapsed;
                }
            }
            if (_framingStatus is not null)
                _framingStatus.Text = $"Frame loaded · {bitmap.PixelWidth} × {bitmap.PixelHeight}. Drag the pink and cyan regions.";
            UpdateFramingOverlay();
        }
        catch (Exception ex)
        {
            if (_framingStatus is not null)
                _framingStatus.Text = "Could not load source frame: " + ex.Message;
            throw;
        }
    }

    private async Task DetectFacecamAutomaticallyAsync()
    {
        if (_engine is null)
            throw new InvalidOperationException("The local media engine is not connected.");
        var target = _liveTargetInput?.Text.Trim() ?? SettingString("target");
        var mode = _liveModeInput?.SelectedIndex == 1 ? "file" : "live";
        if (string.IsNullOrWhiteSpace(target))
            throw new InvalidOperationException("Paste a stream URL or select a video file first.");

        // Refresh the preview from the current source so automatic results are
        // immediately visible and never applied against a stale frame.
        await LoadFramingFrameAsync();
        if (_framingStatus is not null)
            _framingStatus.Text = "Analyzing multiple frames and looking for a live facecam…";
        try
        {
            var result = await _engine.PostJsonAsync("/api/facecam/detect", new JsonObject
            {
                ["mode"] = mode,
                ["target"] = target
            }, _shutdown.Token);
            var found = bool.TryParse(result["found"]?.ToString(), out var detected) && detected;
            var device = result["inference_device"]?.ToString() ?? "unknown inference device";
            if (found && result["cam"] is JsonObject cam)
            {
                _framingCamX = ReadFramingNumber(cam, "x", _framingCamX / 100.0) * 100.0;
                _framingCamY = ReadFramingNumber(cam, "y", _framingCamY / 100.0) * 100.0;
                _framingCamW = ReadFramingNumber(cam, "w", _framingCamW / 100.0) * 100.0;
                _framingCamH = ReadFramingNumber(cam, "h", _framingCamH / 100.0) * 100.0;
                var confidence = ReadFramingNumber(result, "confidence", 0.0) * 100.0;
                var method = result["method"]?.ToString() ?? "multi-frame analysis";
                if (_framingStatus is not null)
                    _framingStatus.Text = $"Facecam found · {confidence:0}% confidence · {method} · {device}. Review the pink region, adjust if needed, then Save framing.";
                UpdateFramingOverlay();
            }
            else
            {
                var reason = result["reason"]?.ToString() ?? "No confident facecam match was found.";
                if (_framingStatus is not null)
                    _framingStatus.Text = $"No confident facecam match · {device}. {reason} The manual editor is still available.";
            }
        }
        catch (Exception ex)
        {
            if (_framingStatus is not null)
                _framingStatus.Text = "Automatic facecam detection failed: " + ex.Message;
            throw;
        }
    }

    private async Task SaveFramingAsync()
    {
        SetSetting("cam_x", _framingCamX);
        SetSetting("cam_y", _framingCamY);
        SetSetting("cam_w", _framingCamW);
        SetSetting("cam_h", _framingCamH);
        SetSetting("game_area_x", _framingGameX);
        SetSetting("game_area_y", _framingGameY);
        SetSetting("game_area_w", _framingGameW);
        SetSetting("game_area_h", _framingGameH);
        await SaveCaptureSettingsAsync();
        if (_framingStatus is not null)
            _framingStatus.Text = string.IsNullOrWhiteSpace(_liveSelectedCreatorId)
                ? "Framing saved to the local-video profile."
                : "Framing saved to this creator's profile.";
    }

    private static double ReadFramingNumber(JsonObject value, string key, double fallback)
    {
        return double.TryParse(value[key]?.ToString(), System.Globalization.NumberStyles.Float,
            System.Globalization.CultureInfo.InvariantCulture, out var parsed) && double.IsFinite(parsed)
            ? parsed
            : fallback;
    }

    private void BeginFramingDrag(string region, bool resize, PointerRoutedEventArgs args)
    {
        if (_framingCanvas is null || _framingCanvas.ActualWidth < 1 || _framingCanvas.ActualHeight < 1)
            return;
        _framingDragRegion = region;
        _framingDragResize = resize;
        _framingDragStartPoint = args.GetCurrentPoint(_framingCanvas).Position;
        var box = GetFramingBox(region);
        _framingStartX = box.X;
        _framingStartY = box.Y;
        _framingStartW = box.Width;
        _framingStartH = box.Height;
        _framingCanvas.CapturePointer(args.Pointer);
        args.Handled = true;
    }

    private void FramingCanvas_PointerMoved(object sender, PointerRoutedEventArgs args)
    {
        if (_framingDragRegion is null || _framingCanvas is null)
            return;
        var point = args.GetCurrentPoint(_framingCanvas).Position;
        var deltaX = (point.X - _framingDragStartPoint.X) / _framingCanvas.ActualWidth * 100.0;
        var deltaY = (point.Y - _framingDragStartPoint.Y) / _framingCanvas.ActualHeight * 100.0;
        var minSize = 10.0;
        var box = _framingDragResize
            ? new FramingBox(
                _framingStartX,
                _framingStartY,
                Math.Clamp(_framingStartW + deltaX, minSize, 100.0 - _framingStartX),
                Math.Clamp(_framingStartH + deltaY, minSize, 100.0 - _framingStartY))
            : new FramingBox(
                Math.Clamp(_framingStartX + deltaX, 0.0, 100.0 - _framingStartW),
                Math.Clamp(_framingStartY + deltaY, 0.0, 100.0 - _framingStartH),
                _framingStartW,
                _framingStartH);
        SetFramingBox(_framingDragRegion, box);
        UpdateFramingOverlay();
        UpdateFramingValues();
        args.Handled = true;
    }

    private void FramingCanvas_PointerReleased(object sender, PointerRoutedEventArgs args)
    {
        FinishFramingDrag();
    }

    private void FramingCanvas_PointerCanceled(object sender, PointerRoutedEventArgs args)
    {
        FinishFramingDrag();
    }

    private void FramingCanvas_PointerCaptureLost(object sender, PointerRoutedEventArgs args)
    {
        FinishFramingDrag();
    }

    private void FinishFramingDrag()
    {
        _framingDragRegion = null;
        _framingDragResize = false;
        _framingCanvas?.ReleasePointerCaptures();
    }

    private readonly record struct FramingBox(double X, double Y, double Width, double Height);

    private FramingBox GetFramingBox(string region)
    {
        return region == "facecam"
            ? new FramingBox(_framingCamX, _framingCamY, _framingCamW, _framingCamH)
            : new FramingBox(_framingGameX, _framingGameY, _framingGameW, _framingGameH);
    }

    private void SetFramingBox(string region, FramingBox box)
    {
        if (region == "facecam")
        {
            _framingCamX = box.X;
            _framingCamY = box.Y;
            _framingCamW = box.Width;
            _framingCamH = box.Height;
        }
        else
        {
            _framingGameX = box.X;
            _framingGameY = box.Y;
            _framingGameW = box.Width;
            _framingGameH = box.Height;
        }
    }

    private void FramingStage_SizeChanged(object sender, SizeChangedEventArgs args)
    {
        if (_framingStage is null || _framingCanvas is null)
            return;
        var width = args.NewSize.Width;
        if (width <= 0)
            return;
        var height = Math.Clamp(width / _framingAspectRatio, 180.0, 520.0);
        if (Math.Abs(_framingStage.Height - height) > 1.0)
            _framingStage.Height = height;
        _framingCanvas.Width = width;
        _framingCanvas.Height = height;
        UpdateFramingOverlay();
    }

    private void UpdateFramingOverlay()
    {
        if (_framingCanvas is null || _facecamRegion is null || _gameRegion is null ||
            _facecamResizeHandle is null || _gameResizeHandle is null)
            return;
        var width = _framingCanvas.ActualWidth;
        var height = _framingCanvas.ActualHeight;
        if (width < 1 || height < 1)
            return;
        PositionFramingRegion(_gameRegion, _gameResizeHandle,
            new FramingBox(_framingGameX, _framingGameY, _framingGameW, _framingGameH), width, height);
        PositionFramingRegion(_facecamRegion, _facecamResizeHandle,
            new FramingBox(_framingCamX, _framingCamY, _framingCamW, _framingCamH), width, height);
    }

    private static void PositionFramingRegion(Border region, Border handle, FramingBox box, double width, double height)
    {
        var left = width * box.X / 100.0;
        var top = height * box.Y / 100.0;
        var boxWidth = width * box.Width / 100.0;
        var boxHeight = height * box.Height / 100.0;
        region.Width = boxWidth;
        region.Height = boxHeight;
        Canvas.SetLeft(region, left);
        Canvas.SetTop(region, top);
        Canvas.SetLeft(handle, left + Math.Max(0, boxWidth - handle.Width / 2));
        Canvas.SetTop(handle, top + Math.Max(0, boxHeight - handle.Height / 2));
    }

    private void UpdateFramingValues()
    {
        if (_framingValues is null)
            return;
        _framingValues.Text =
            $"FACECAM  X {_framingCamX:0.0}%  Y {_framingCamY:0.0}%  W {_framingCamW:0.0}%  H {_framingCamH:0.0}%\n" +
            $"GAME  X {_framingGameX:0.0}%  Y {_framingGameY:0.0}%  W {_framingGameW:0.0}%  H {_framingGameH:0.0}%";
    }
}
