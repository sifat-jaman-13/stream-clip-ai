using System.Text.Json.Nodes;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;

namespace StreamSnip_Desktop;

public sealed partial class MainPage
{
    private void RenderCreatorsPage()
    {
        AddPageHeading("Creators", "Manage independent Twitch and YouTube monitors, live capture, and recorded-VOD folders.");

        var toolbar = ActionRow(
            CreateButton("Add creator", async () => await AddCreatorDialogAsync(), primary: true),
            CreateButton("Refresh", async () =>
            {
                await RefreshCreatorsAsync();
                await RefreshStateAsync();
                RenderCurrentPage();
            }));
        PageHost.Children.Add(toolbar);

        if (_creators.Count == 0)
        {
            var empty = new StackPanel { Spacing = 10 };
            empty.Children.Add(Txt("No creator sources yet.", 14, true));
            empty.Children.Add(ThemeText("Add a Twitch or YouTube channel to run an independent monitor or watch a folder for recorded VODs.", 10, false, "MutedTextBrush"));
            empty.Children.Add(CreateButton("Add your first creator", async () => await AddCreatorDialogAsync(), primary: true));
            PageHost.Children.Add(CreatePanel("Creator sources", "Each creator keeps separate folders for recordings and rendered clips.", empty));
            return;
        }

        var list = new StackPanel { Spacing = 12 };
        foreach (var creator in _creators.OrderBy(x => x.Name, StringComparer.CurrentCultureIgnoreCase))
        {
            var details = new StackPanel { Spacing = 5 };
            details.Children.Add(Txt(creator.Name, 14, true));
            details.Children.Add(ThemeText(creator.Target, 10, false, "MutedTextBrush"));
            details.Children.Add(ThemeText(
                $"Live clips  {creator.LiveClips:N0}     VOD clips  {creator.VodClips:N0}     Pending VODs  {creator.VodPending:N0}",
                10, false, "MutedTextBrush"));

            var statuses = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 6 };
            if (creator.CaptureActive)
                statuses.Children.Add(MakeStatusPill(creator.CaptureStopping ? "Capture stopping" : "Recording", creator.CaptureStopping ? "WarningBrush" : "AccentBrush"));
            else
                statuses.Children.Add(MakeStatusPill(creator.Running ? "Monitoring" : "Idle", creator.Running ? "SuccessBrush" : "MutedTextBrush"));
            if (creator.WatchingVods)
                statuses.Children.Add(MakeStatusPill("Watching VOD folder", "MutedTextBrush"));
            details.Children.Add(statuses);

            var actions = new StackPanel { Spacing = 6, MinWidth = 148 };
            if (creator.Running)
                actions.Children.Add(CreateButton("Stop monitor", async () => await CreatorActionAsync(
                    "Could not stop monitor", "/api/creators/stop", creator.Id, new JsonObject { ["force"] = false })));
            else
                actions.Children.Add(CreateButton("Start monitor", async () => await CreatorActionAsync(
                    "Could not start monitor", "/api/creators/start", creator.Id), primary: true));

            if (creator.WatchingVods)
                actions.Children.Add(CreateButton("Stop VOD watch", async () => await CreatorActionAsync(
                    "Could not stop VOD watch", "/api/creators/stop-vod-watch", creator.Id)));
            else
                actions.Children.Add(CreateButton("Watch VOD folder", async () => await CreatorActionAsync(
                    "Could not start VOD watch", "/api/creators/watch-vods", creator.Id)));

            if (creator.CaptureActive)
                actions.Children.Add(CreateButton("Stop capture", async () => await CreatorActionAsync(
                    "Could not stop capture", "/api/creators/stop-capture", creator.Id, new JsonObject { ["force"] = false }), danger: true));

            actions.Children.Add(CreateButton("Open folders", async () =>
            {
                try
                {
                    await PostAsync("/api/creators/open", new JsonObject
                    {
                        ["id"] = creator.Id,
                        ["folder"] = "live_clips"
                    });
                }
                catch (Exception ex) { await ShowErrorAsync("Could not open creator folder", ex.Message); }
            }));
            actions.Children.Add(CreateButton("Remove creator", async () =>
            {
                var dialog = new ContentDialog
                {
                    XamlRoot = XamlRoot,
                    Title = $"Remove {creator.Name}?",
                    Content = "Existing recordings and clips will be kept. Only the creator monitor profile will be removed.",
                    PrimaryButtonText = "Remove",
                    CloseButtonText = "Cancel",
                    DefaultButton = ContentDialogButton.Close
                };
                if (await dialog.ShowAsync() != ContentDialogResult.Primary) return;
                await CreatorActionAsync("Could not remove creator", "/api/creators/remove", creator.Id);
            }, danger: true));

            var row = new Grid { ColumnSpacing = 14, Padding = new Thickness(15) };
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(44) });
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            var avatar = CreateCreatorAvatar(
                creator.Name, size: 38, active: creator.Running || creator.CaptureActive);
            Grid.SetRow(avatar, 0);
            Grid.SetColumn(avatar, 0);
            row.Children.Add(avatar);
            Grid.SetColumn(details, 1);
            row.Children.Add(details);
            Grid.SetColumn(actions, 2);
            row.Children.Add(actions);
            list.Children.Add(new Border
            {
                Background = Application.Current.Resources["SurfaceBrush"] as Brush,
                BorderBrush = Application.Current.Resources["LineBrush"] as Brush,
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(11),
                Child = row
            });
        }
        PageHost.Children.Add(CreatePanel("Saved creator sources", $"{_creators.Count} creator profile(s). Monitors run independently from Live Studio capture.", list));
    }

    private async Task CreatorActionAsync(string title, string route, string creatorId, JsonObject? extra = null)
    {
        try
        {
            var body = extra?.DeepClone() as JsonObject ?? new JsonObject();
            body["id"] = creatorId;
            await PostAsync(route, body);
            await RefreshCreatorsAsync();
            RenderCurrentPage();
        }
        catch (Exception ex) { await ShowErrorAsync(title, ex.Message); }
    }

    private static string? InferCreatorHandle(string value)
    {
        var raw = value.Trim();
        if (raw.Length == 0) return null;
        if (!raw.Contains("://", StringComparison.Ordinal)) raw = "https://" + raw;
        if (!Uri.TryCreate(raw, UriKind.Absolute, out var uri)) return null;
        var host = uri.Host.ToLowerInvariant().Replace("www.", "");
        var parts = uri.AbsolutePath.Split('/', StringSplitOptions.RemoveEmptyEntries)
            .Select(part => Uri.UnescapeDataString(part)).ToArray();

        if (host == "twitch.tv" || host.EndsWith(".twitch.tv", StringComparison.Ordinal))
        {
            if (parts.Length == 0) return null;
            var first = parts[0];
            if (new[] { "videos", "directory", "search", "clip", "downloads", "settings" }
                .Contains(first, StringComparer.OrdinalIgnoreCase)) return null;
            var clean = new string(first.TrimStart('@').Where(ch => char.IsLetterOrDigit(ch) || ch == '_').ToArray());
            return clean.Length == 0 ? null : "@" + clean;
        }
        if (host == "youtube.com" || host.EndsWith(".youtube.com", StringComparison.Ordinal))
        {
            if (parts.Length == 0) return null;
            var first = parts[0];
            var candidate = first.StartsWith("@", StringComparison.Ordinal)
                ? first[1..]
                : parts.Length > 1 && (first.Equals("c", StringComparison.OrdinalIgnoreCase)
                    || first.Equals("user", StringComparison.OrdinalIgnoreCase))
                    ? parts[1]
                    : null;
            if (string.IsNullOrWhiteSpace(candidate)) return null;
            var clean = new string(candidate.Where(ch => char.IsLetterOrDigit(ch) || ch is '_' or '.' or '-').ToArray());
            return clean.Length == 0 ? null : "@" + clean;
        }
        return null;
    }

    private async Task AddCreatorDialogAsync()
    {
        var form = new StackPanel { Spacing = 11, MinWidth = 430 };
        var name = Input("", "Creator name");
        var target = Input("", "https://twitch.tv/channel or https://youtube.com/@handle");
        var nameEditedManually = false;
        var updatingNameFromUrl = false;
        name.TextChanged += (_, _) =>
        {
            if (!updatingNameFromUrl) nameEditedManually = true;
        };
        target.TextChanged += (_, _) =>
        {
            if (nameEditedManually) return;
            var detectedName = InferCreatorHandle(target.Text);
            if (detectedName is null) return;
            updatingNameFromUrl = true;
            name.Text = detectedName.TrimStart('@');
            updatingNameFromUrl = false;
        };
        AddLabeled(form, "Creator name", name);
        AddLabeled(form, "Channel URL", target, "The channel URL is used for handle detection and monitoring.");
        var dialog = new ContentDialog
        {
            XamlRoot = XamlRoot,
            Title = "Add creator source",
            Content = form,
            PrimaryButtonText = "Add creator",
            CloseButtonText = "Cancel",
            DefaultButton = ContentDialogButton.Primary
        };
        if (await dialog.ShowAsync() != ContentDialogResult.Primary) return;
        if (string.IsNullOrWhiteSpace(name.Text) || string.IsNullOrWhiteSpace(target.Text))
        {
            await ShowErrorAsync("Creator details required", "Enter both a creator name and a Twitch or YouTube channel URL.");
            return;
        }

        try
        {
            await PostAsync("/api/creators/add", new JsonObject
            {
                ["name"] = name.Text.Trim(),
                ["target"] = target.Text.Trim()
            });
            await RefreshCreatorsAsync();
            NavigateTo("creators");
        }
        catch (Exception ex) { await ShowErrorAsync("Could not add creator", ex.Message); }
    }
}
