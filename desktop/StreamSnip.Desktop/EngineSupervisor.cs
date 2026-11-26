using System.Collections.Concurrent;
using System.Diagnostics;
using System.Net;
using System.Net.Http.Headers;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace StreamSnip_Desktop;

public sealed class EngineSupervisor : IAsyncDisposable
{
    private static readonly Regex ReadyLine = new(
        @"https?://127\.0\.0\.1:(?<port>\d+)/",
        RegexOptions.Compiled | RegexOptions.CultureInvariant);

    private readonly Process _process;
    private readonly ConcurrentQueue<string> _outputTail = new();
    private readonly TaskCompletionSource<Uri> _endpoint =
        new(TaskCreationOptions.RunContinuationsAsynchronously);
    private readonly CancellationTokenSource _lifetime = new();
    private HttpClient? _http;
    private string? _token;
    private bool _disposed;

    public event EventHandler<string>? OutputReceived;
    public event EventHandler<int?>? ProcessExited;

    public bool IsRunning => !_process.HasExited;
    public int? ProcessId => _process.HasExited ? null : _process.Id;
    public Uri? BaseAddress { get; private set; }

    private EngineSupervisor(Process process)
    {
        _process = process;
        _process.OutputDataReceived += (_, e) => HandleOutput(e.Data);
        _process.ErrorDataReceived += (_, e) =>
        {
            if (!string.IsNullOrWhiteSpace(e.Data))
            {
                RememberOutput("[stderr] " + e.Data);
                OutputReceived?.Invoke(this, e.Data);
            }
        };
        _process.Exited += (_, _) =>
        {
            var details = string.Join(Environment.NewLine, _outputTail.ToArray());
            var message = $"The StreamSnip engine exited before its local API became ready (exit code {_process.ExitCode}).";
            if (!string.IsNullOrWhiteSpace(details))
                message += Environment.NewLine + details;
            _endpoint.TrySetException(new InvalidOperationException(message));
            ProcessExited?.Invoke(this, _process.ExitCode);
        };
    }

    public static async Task<EngineSupervisor> StartAsync(CancellationToken cancellationToken = default)
    {
        var developmentConfig = ReadNativeDevelopmentConfig();
        var sourceRoot = ResolveSourceRoot(developmentConfig?.SourceRoot);
        var python = ResolvePython(sourceRoot, developmentConfig?.PythonExecutable);

        var start = new ProcessStartInfo
        {
            FileName = python,
            WorkingDirectory = sourceRoot,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true
        };
        start.ArgumentList.Add("-u");
        start.ArgumentList.Add(Path.Combine(sourceRoot, "autoclip.py"));
        start.Environment["STREAMSNIP_NATIVE_HOST"] = "1";
        start.Environment["STREAMSNIP_BIND_HOST"] = "127.0.0.1";
        start.Environment["STREAMSNIP_PORT"] = "0";

        if (!string.IsNullOrWhiteSpace(developmentConfig?.DataRoot))
        {
            start.Environment["STREAMSNIP_DATA_DIR"] = Path.GetFullPath(developmentConfig.DataRoot);
        }
        if (!string.IsNullOrWhiteSpace(developmentConfig?.FfmpegExecutable) &&
            File.Exists(developmentConfig.FfmpegExecutable))
        {
            var ffmpegPath = Path.GetFullPath(developmentConfig.FfmpegExecutable);
            start.Environment["STREAMSNIP_FFMPEG_PATH"] = ffmpegPath;
            var ffmpegDirectory = Path.GetDirectoryName(ffmpegPath);
            if (!string.IsNullOrWhiteSpace(ffmpegDirectory))
                start.Environment["PATH"] = ffmpegDirectory + Path.PathSeparator + start.Environment["PATH"];
        }
#if DEBUG
        else
        {
            // Keep developer smoke-test data out of the Git working tree and separate
            // from the user's installed production settings and clip library.
            start.Environment["STREAMSNIP_DATA_DIR"] = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "StreamSnip AI", "native-development");
        }
#endif

        var process = new Process { StartInfo = start, EnableRaisingEvents = true };
        var supervisor = new EngineSupervisor(process);
        try
        {
            if (!process.Start())
                throw new InvalidOperationException("Windows could not start the StreamSnip Python engine.");

            process.BeginOutputReadLine();
            process.BeginErrorReadLine();

            var endpoint = await supervisor._endpoint.Task.WaitAsync(
                TimeSpan.FromSeconds(45), cancellationToken).ConfigureAwait(false);
            supervisor.BaseAddress = endpoint;
            supervisor._http = new HttpClient(new SocketsHttpHandler
            {
                ConnectTimeout = TimeSpan.FromSeconds(4),
                PooledConnectionLifetime = TimeSpan.FromMinutes(5)
            })
            {
                BaseAddress = endpoint,
                Timeout = Timeout.InfiniteTimeSpan
            };

            var session = await supervisor.GetJsonAsync("/api/session", cancellationToken)
                .ConfigureAwait(false);
            supervisor._token = session["token"]?.GetValue<string>();
            if (string.IsNullOrWhiteSpace(supervisor._token))
                throw new InvalidOperationException("The local StreamSnip engine did not issue a session token.");

            var health = await supervisor.GetJsonAsync("/api/health", cancellationToken)
                .ConfigureAwait(false);
            return supervisor;
        }
        catch
        {
            await supervisor.DisposeAsync().ConfigureAwait(false);
            throw;
        }
    }

    public async Task<JsonObject> GetJsonAsync(string route, CancellationToken cancellationToken = default)
    {
        EnsureStarted();
        using var request = new HttpRequestMessage(HttpMethod.Get, route);
        if (!string.IsNullOrEmpty(_token))
            request.Headers.TryAddWithoutValidation("X-Token", _token);
        using var response = await _http!.SendAsync(
            request, HttpCompletionOption.ResponseHeadersRead, cancellationToken).ConfigureAwait(false);
        return await ReadObjectAsync(response, cancellationToken).ConfigureAwait(false);
    }

    public async Task<JsonObject> PostJsonAsync(
        string route, JsonObject? payload = null, CancellationToken cancellationToken = default)
    {
        EnsureStarted();
        using var request = new HttpRequestMessage(HttpMethod.Post, route)
        {
            Content = new StringContent(payload?.ToJsonString() ?? "{}", System.Text.Encoding.UTF8, "application/json")
        };
        if (!string.IsNullOrEmpty(_token))
            request.Headers.TryAddWithoutValidation("X-Token", _token);
        using var response = await _http!.SendAsync(request, cancellationToken).ConfigureAwait(false);
        return await ReadObjectAsync(response, cancellationToken).ConfigureAwait(false);
    }


    public async Task<bool> QuitAsync(CancellationToken cancellationToken = default)
    {
        if (_process.HasExited) return true;
        try
        {
            await PostJsonAsync("/api/quit", new JsonObject(), cancellationToken).ConfigureAwait(false);
            await _process.WaitForExitAsync(cancellationToken).WaitAsync(
                TimeSpan.FromSeconds(15), cancellationToken).ConfigureAwait(false);
            return true;
        }
        catch (TimeoutException)
        {
            return false;
        }
        catch (HttpRequestException)
        {
            return _process.HasExited;
        }
    }

    private void RememberOutput(string line)
    {
        _outputTail.Enqueue(line);
        while (_outputTail.Count > 30)
            _outputTail.TryDequeue(out _);
    }

    private void HandleOutput(string? line)
    {
        if (string.IsNullOrWhiteSpace(line)) return;
        RememberOutput(line);
        OutputReceived?.Invoke(this, line);
        var match = ReadyLine.Match(line);
        if (!match.Success) return;
        if (!int.TryParse(match.Groups["port"].Value, out var port) || port is < 1 or > 65535)
            return;
        _endpoint.TrySetResult(new Uri($"http://127.0.0.1:{port}/"));
    }

    private static async Task<JsonObject> ReadObjectAsync(
        HttpResponseMessage response, CancellationToken cancellationToken)
    {
        var text = await response.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);
        JsonObject? payload = null;
        try { payload = JsonNode.Parse(text) as JsonObject; }
        catch (JsonException) { }

        if (!response.IsSuccessStatusCode)
        {
            var message = payload?["error"]?.GetValue<string>()
                ?? payload?["detail"]?.GetValue<string>()
                ?? $"Local engine request failed ({(int)response.StatusCode} {response.StatusCode}).";
            throw new HttpRequestException(message, null, response.StatusCode);
        }
        return payload ?? new JsonObject();
    }

    private sealed record NativeDevelopmentConfig(
        string SourceRoot,
        string PythonExecutable,
        string? DataRoot,
        string? FfmpegExecutable);

    private static NativeDevelopmentConfig? ReadNativeDevelopmentConfig()
    {
        var localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        var configPaths = new List<string>
        {
            Path.Combine(localAppData, "StreamSnip AI", "native-engine.json")
        };

        // The native installer writes the authoritative engine config to the
        // shared LocalAppData location above. Keep packaged LocalState as a
        // fallback for development/package runs, never ahead of the installed config.
        try
        {
            var packageLocalState = Windows.Storage.ApplicationData.Current.LocalFolder.Path;
            configPaths.Add(Path.Combine(packageLocalState, "native-engine.json"));
        }
        catch (Exception)
        {
            // ApplicationData.Current is unavailable to ordinary unpackaged processes.
        }

#if DEBUG
        configPaths.Insert(0, Path.Combine(
            localAppData, "StreamSnip AI", "native-development", "desktop-engine.json"));
#endif

        foreach (var configPath in configPaths.Distinct(StringComparer.OrdinalIgnoreCase))
        {
            try
            {
                if (!File.Exists(configPath)) continue;
                var config = JsonNode.Parse(File.ReadAllText(configPath)) as JsonObject;
                var sourceRoot = config?["source_root"]?.GetValue<string>() ?? "";
                var python = config?["python_executable"]?.GetValue<string>() ?? "";
                var dataRoot = config?["data_root"]?.GetValue<string>();
                var ffmpegExecutable = config?["ffmpeg_executable"]?.GetValue<string>();
                if (string.IsNullOrWhiteSpace(sourceRoot) || string.IsNullOrWhiteSpace(python))
                    continue;
                return new NativeDevelopmentConfig(sourceRoot, python, dataRoot, ffmpegExecutable);
            }
            catch (Exception)
            {
                // A stale or partially written config should not block source discovery.
            }
        }
        return null;
    }

    private static string ResolveSourceRoot(string? developmentRoot = null)
    {
        var configured = Environment.GetEnvironmentVariable("STREAMSNIP_SOURCE_DIR");
        if (!string.IsNullOrWhiteSpace(configured) && File.Exists(Path.Combine(configured, "autoclip.py")))
            return Path.GetFullPath(configured);
        if (!string.IsNullOrWhiteSpace(developmentRoot) &&
            File.Exists(Path.Combine(developmentRoot, "autoclip.py")))
            return Path.GetFullPath(developmentRoot);

        foreach (var start in new[]
        {
            AppContext.BaseDirectory,
            Environment.CurrentDirectory
        })
        {
            var current = new DirectoryInfo(start);
            while (current is not null)
            {
                if (File.Exists(Path.Combine(current.FullName, "autoclip.py")))
                    return current.FullName;
                var source = Path.Combine(current.FullName, "source");
                if (File.Exists(Path.Combine(source, "autoclip.py")))
                    return source;
                current = current.Parent;
            }
        }

        throw new DirectoryNotFoundException(
            "Could not locate StreamSnip AI's Python engine (autoclip.py). The installer must place it in the source folder.");
    }

    private static string ResolvePython(string sourceRoot, string? developmentPython = null)
    {
        var configured = Environment.GetEnvironmentVariable("STREAMSNIP_PYTHON");
        var appRoot = Directory.GetParent(sourceRoot)?.FullName;
        var localPrograms = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        var candidates = new[]
        {
            configured,
            developmentPython,
            appRoot is null ? null : Path.Combine(appRoot, "runtime", "Scripts", "python.exe"),
            Path.Combine(AppContext.BaseDirectory, "runtime", "Scripts", "python.exe"),
            Path.Combine(localPrograms, "Programs", "StreamSnip AI Native", "runtime", "Scripts", "python.exe"),
            Path.Combine(localPrograms, "Programs", "StreamSnip AI", "runtime", "Scripts", "python.exe")
        };
        var python = candidates.FirstOrDefault(path => !string.IsNullOrWhiteSpace(path) && File.Exists(path));
        if (python is null)
            throw new FileNotFoundException(
                "The isolated StreamSnip Python runtime was not found. Run the StreamSnip AI setup/repair step first.");

        var resolvedPython = Path.GetFullPath(python);
        var scriptsDirectory = Path.GetDirectoryName(resolvedPython);
        if (string.Equals(Path.GetFileName(scriptsDirectory), "Scripts", StringComparison.OrdinalIgnoreCase))
        {
            var runtimeRoot = Directory.GetParent(scriptsDirectory!)?.FullName;
            var environmentConfig = runtimeRoot is null ? null : Path.Combine(runtimeRoot, "pyvenv.cfg");
            if (environmentConfig is null || !File.Exists(environmentConfig))
            {
                throw new InvalidOperationException(
                    $"The installed local Python environment is incomplete. The required file is missing: {environmentConfig ?? "runtime\\pyvenv.cfg"}. Run the StreamSnip AI installer again to repair the processing engine.");
            }
        }

        return resolvedPython;
    }

    private void EnsureStarted()
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        if (_http is null || BaseAddress is null)
            throw new InvalidOperationException("The StreamSnip engine has not finished starting.");
        if (_process.HasExited)
            throw new InvalidOperationException("The StreamSnip engine is no longer running.");
    }

    public async ValueTask DisposeAsync()
    {
        if (_disposed) return;
        _disposed = true;
        _lifetime.Cancel();
        if (!_process.HasExited)
        {
            try
            {
                await _process.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(2)).ConfigureAwait(false);
            }
            catch (TimeoutException)
            {
                try { _process.Kill(entireProcessTree: true); }
                catch (InvalidOperationException) { }
            }
        }
        _http?.Dispose();
        _process.Dispose();
        _lifetime.Dispose();
    }
}
