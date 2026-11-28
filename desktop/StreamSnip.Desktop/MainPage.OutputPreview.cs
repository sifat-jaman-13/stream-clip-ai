using System.Text.Json.Nodes;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Windows.Media.Core;
using Windows.Storage;

namespace StreamSnip_Desktop;

public sealed partial class MainPage
{
    private static MediaPlayerElement CreateOutputPreviewPlayer()
    {
        return new MediaPlayerElement
        {
            AreTransportControlsEnabled = true,
            AutoPlay = false,
            MinHeight = 360,
            MaxHeight = 620,
            Width = 320,
            Stretch = Stretch.Uniform,
            HorizontalAlignment = HorizontalAlignment.Center
        };
    }

    private string OutputFormatDescription()
    {
        return SettingString("output_format", "9:16") switch
        {
            "16:9" => "YouTube landscape ? 1920 ? 1080",
            "1:1" => "Square ? 1080 ? 1080",
            "4:5" => "Portrait feed ? 1080 ? 1350",
            _ => "YouTube Shorts / Reels / TikTok ? 1080 ? 1920"
        };
    }

    private async Task RenderActualClipPreviewAsync(
        MediaPlayerElement player,
        TextBlock status)
    {
        if (_engine is null)
            throw new InvalidOperationException("The local media engine is not connected.");

        var mode = _liveModeInput?.SelectedIndex == 1 ? "file" : "live";
        var target = _liveTargetInput?.Text.Trim() ?? SettingString("target");
        if (string.IsNullOrWhiteSpace(target))
            throw new InvalidOperationException(
                mode == "live"
                    ? "Select a saved creator before previewing the final clip."
                    : "Choose a local video before previewing the final clip.");

        if (mode == "live" && string.IsNullOrWhiteSpace(_liveSelectedCreatorId))
            throw new InvalidOperationException("Select a saved creator first.");

        // Include unsaved framing edits so the preview is immediately responsive
        // to the current editor state; this does not persist or mutate the profile.
        var values = _settings?.Values.DeepClone() as JsonObject ?? new JsonObject();
        values["mode"] = mode;
        values["target"] = target;
        if (_liveSelectedCreatorId is not null)
            values["creator_id"] = _liveSelectedCreatorId;

        if (_framingValuesInitialized)
        {
            values["cam_x"] = _framingCamX;
            values["cam_y"] = _framingCamY;
            values["cam_w"] = _framingCamW;
            values["cam_h"] = _framingCamH;
            values["game_area_x"] = _framingGameX;
            values["game_area_y"] = _framingGameY;
            values["game_area_w"] = _framingGameW;
            values["game_area_h"] = _framingGameH;
        }

        status.Text = "Rendering the selected source with the actual export layout and captions?";
        player.Source = null;

        var result = await _engine.PostJsonAsync("/api/output-preview", new JsonObject
        {
            ["mode"] = mode,
            ["target"] = target,
            ["settings"] = values
        }, _shutdown.Token);

        var dataUrl = result["video"]?.ToString() ?? "";
        var comma = dataUrl.IndexOf(',');
        var encoded = comma >= 0 ? dataUrl[(comma + 1)..] : dataUrl;
        if (string.IsNullOrWhiteSpace(encoded))
            throw new InvalidOperationException("The rendered output preview did not contain a video.");

        byte[] bytes;
        try
        {
            bytes = Convert.FromBase64String(encoded);
        }
        catch (FormatException ex)
        {
            throw new InvalidOperationException("The output preview returned invalid video data.", ex);
        }

        var previewDirectory = Path.Combine(Path.GetTempPath(), "StreamSnipAI", "OutputPreviews");
        Directory.CreateDirectory(previewDirectory);
        foreach (var stale in Directory.EnumerateFiles(previewDirectory, "*.mp4"))
        {
            try
            {
                if (File.GetLastWriteTimeUtc(stale) < DateTime.UtcNow.AddHours(-12))
                    File.Delete(stale);
            }
            catch { }
        }

        var previewPath = Path.Combine(previewDirectory, $"preview-{Guid.NewGuid():N}.mp4");
        await File.WriteAllBytesAsync(previewPath, bytes);
        var file = await StorageFile.GetFileFromPathAsync(previewPath);
        player.Source = MediaSource.CreateFromStorageFile(file);
        status.Text = $"Actual export preview ? {OutputFormatDescription()} ? 2.5-second sample. Press Play to inspect the framing and caption treatment.";
    }
}
