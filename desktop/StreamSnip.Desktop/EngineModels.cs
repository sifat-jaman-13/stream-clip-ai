using System.Text.Json.Nodes;
using System.Text.Json.Serialization;

namespace StreamSnip_Desktop;

public sealed record EngineState
{
    [JsonPropertyName("running")] public bool Running { get; init; }
    [JsonPropertyName("stopping")] public bool Stopping { get; init; }
    [JsonPropertyName("mode")] public string? Mode { get; init; }
    [JsonPropertyName("phase")] public string Phase { get; init; } = "idle";
    [JsonPropertyName("status")] public string Status { get; init; } = "Connecting to StreamSnip AI…";
    [JsonPropertyName("progress")] public int Progress { get; init; }
    [JsonPropertyName("last_id")] public long LastId { get; init; }
    [JsonPropertyName("revision")] public long Revision { get; init; }
    [JsonPropertyName("clip_total")] public int ClipTotal { get; init; }
    [JsonPropertyName("posted_total")] public int PostedTotal { get; init; }
    [JsonPropertyName("scheduled_total")] public int ScheduledTotal { get; init; }
    [JsonPropertyName("session")] public SessionState Session { get; init; } = new();
    [JsonPropertyName("posting")] public PostingState Posting { get; init; } = new();
    [JsonPropertyName("clips")] public List<ClipItem> Clips { get; init; } = [];
    [JsonPropertyName("logs")] public List<LogItem> Logs { get; init; } = [];
}

public sealed record SessionState
{
    [JsonPropertyName("clips")] public int Clips { get; init; }
    [JsonPropertyName("chunks")] public int Chunks { get; init; }
    [JsonPropertyName("elapsed")] public int Elapsed { get; init; }
}

public sealed record PostingState
{
    [JsonPropertyName("active")] public bool Active { get; init; }
    [JsonPropertyName("total")] public int Total { get; init; }
    [JsonPropertyName("completed")] public int Completed { get; init; }
    [JsonPropertyName("current")] public string Current { get; init; } = "";
    [JsonPropertyName("errors")] public int Errors { get; init; }
}

public sealed record LogItem
{
    [JsonPropertyName("id")] public long Id { get; init; }
    [JsonPropertyName("t")] public string Time { get; init; } = "";
    [JsonPropertyName("m")] public string Message { get; init; } = "";
    [JsonPropertyName("file_lock")] public JsonNode? FileLock { get; init; }
}

public sealed record ClipItem
{
    [JsonPropertyName("name")] public string Name { get; init; } = "";
    [JsonPropertyName("title")] public string Title { get; init; } = "";
    [JsonPropertyName("description")] public string Description { get; init; } = "";
    [JsonPropertyName("caption")] public string Caption { get; init; } = "";
    [JsonPropertyName("creator_name")] public string CreatorName { get; init; } = "";
    [JsonPropertyName("source")] public string Source { get; init; } = "";
    [JsonPropertyName("mtime")] public double ModifiedAt { get; init; }
    [JsonPropertyName("size_mb")] public double SizeMb { get; init; }
    [JsonPropertyName("posted")] public bool Posted { get; init; }
    [JsonPropertyName("posted_at")] public JsonNode? PostedAt { get; init; }
    [JsonPropertyName("scheduled")] public bool Scheduled { get; init; }
    [JsonPropertyName("scheduled_at")] public JsonNode? ScheduledAt { get; init; }
    [JsonPropertyName("delivery_state")] public string DeliveryState { get; init; } = "ready";
}

public sealed record CreatorItem
{
    [JsonPropertyName("id")] public string Id { get; init; } = "";
    [JsonPropertyName("name")] public string Name { get; init; } = "";
    [JsonPropertyName("target")] public string Target { get; init; } = "";
    [JsonPropertyName("running")] public bool Running { get; init; }
    [JsonPropertyName("capture_active")] public bool CaptureActive { get; init; }
    [JsonPropertyName("capture_stopping")] public bool CaptureStopping { get; init; }
    [JsonPropertyName("watching_vods")] public bool WatchingVods { get; init; }
    [JsonPropertyName("phase")] public string Phase { get; init; } = "idle";
    [JsonPropertyName("status")] public string Status { get; init; } = "";
    [JsonPropertyName("vod_status")] public string VodStatus { get; init; } = "";
    [JsonPropertyName("live_clips")] public int LiveClips { get; init; }
    [JsonPropertyName("vod_clips")] public int VodClips { get; init; }
    [JsonPropertyName("vod_pending")] public int VodPending { get; init; }
}

public sealed class EngineSettings
{
    public JsonObject Values { get; private set; } = new();
    public JsonObject Ai { get; private set; } = new();
    public string[] TranscriberModels { get; private set; } = [];
    public string[] Layouts { get; private set; } = [];
    public string[] OutputFormats { get; private set; } = [];

    public static EngineSettings FromResponse(JsonObject response) => new()
    {
        Values = response["settings"]?.DeepClone() as JsonObject ?? new JsonObject(),
        Ai = response["ai"]?.DeepClone() as JsonObject ?? new JsonObject(),
        TranscriberModels = response["transcriber_models"]?.AsArray().Select(x => x?.GetValue<string>() ?? "").ToArray() ?? [],
        Layouts = response["layouts"]?.AsArray().Select(x => x?.GetValue<string>() ?? "").ToArray() ?? [],
        OutputFormats = response["output_formats"]?.AsArray().Select(x => x?.GetValue<string>() ?? "").ToArray() ?? []
    };
}
