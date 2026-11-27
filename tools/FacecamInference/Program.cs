using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.Management;
using System.Text.Json;
using Microsoft.ML.OnnxRuntime;
using Microsoft.ML.OnnxRuntime.Tensors;

internal static class Program
{
    private const int InputSize = 640;
    private const float ScoreThreshold = 0.6f;
    private const float NmsThreshold = 0.3f;
    private const int TopK = 500;
    private static readonly int[] Strides = [8, 16, 32];

    private sealed record Detection(float X, float Y, float Width, float Height, float Score);
    private sealed record Result(string Device, IReadOnlyList<IReadOnlyList<float[]>> Faces);

    private static int Main(string[] args)
    {
        try
        {
            var model = Argument(args, "--model");
            var manifestPath = Argument(args, "--manifest");
            if (!File.Exists(model))
                throw new FileNotFoundException("The YuNet ONNX model was not found.", model);
            if (!File.Exists(manifestPath))
                throw new FileNotFoundException("The facecam frame manifest was not found.", manifestPath);

            var files = JsonSerializer.Deserialize<string[]>(File.ReadAllText(manifestPath))
                        ?? throw new InvalidDataException("The frame manifest is empty.");
            if (files.Length == 0 || files.Length > 400)
                throw new InvalidDataException("The facecam inference batch must contain between 1 and 400 frames.");
            foreach (var file in files)
                if (!File.Exists(file))
                    throw new FileNotFoundException("A sampled facecam frame is missing.", file);

            var gpuNames = PhysicalGpuNames();
            SessionOptions options = new()
            {
                GraphOptimizationLevel = GraphOptimizationLevel.ORT_ENABLE_ALL,
                ExecutionMode = ExecutionMode.ORT_SEQUENTIAL
            };
            string deviceLabel;
            if (gpuNames.Count > 0)
            {
                try
                {
                    options.AppendExecutionProvider_DML(0);
                }
                catch (Exception ex)
                {
                    throw new InvalidOperationException(
                        "A physical GPU is installed (" + string.Join(", ", gpuNames) +
                        "), but the DirectML GPU provider could not be initialized. CPU fallback is disabled. " +
                        ex.Message, ex);
                }
                deviceLabel = "GPU (DirectML) · " + gpuNames[0];
            }
            else
            {
                deviceLabel = "CPU · no supported physical GPU detected";
            }

            using var session = new InferenceSession(model, options);

            var inputName = session.InputMetadata.Keys.Single();
            string[] outputNames =
            [
                "cls_8", "cls_16", "cls_32",
                "obj_8", "obj_16", "obj_32",
                "bbox_8", "bbox_16", "bbox_32",
                "kps_8", "kps_16", "kps_32"
            ];

            var detections = new List<IReadOnlyList<float[]>>(files.Length);
            foreach (var path in files)
            {
                var tensor = BuildInputTensor(path);
                using var outputs = session.Run(
                    [NamedOnnxValue.CreateFromTensor(inputName, tensor)],
                    outputNames);
                var map = outputs.ToDictionary(
                    output => output.Name,
                    output => output.AsTensor<float>().ToArray(),
                    StringComparer.Ordinal);
                detections.Add(Decode(map).Select(face => new[] { face.X, face.Y, face.Width, face.Height, face.Score }).ToArray());
            }

            Console.Out.Write(JsonSerializer.Serialize(new Result(deviceLabel, detections), new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.CamelCase }));
            return 0;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine(ex.ToString());
            return 2;
        }
    }

    private static string Argument(string[] args, string name)
    {
        var index = Array.FindIndex(args, value =>
            string.Equals(value, name, StringComparison.OrdinalIgnoreCase));
        if (index < 0 || index + 1 >= args.Length || string.IsNullOrWhiteSpace(args[index + 1]))
            throw new ArgumentException("Required argument is missing: " + name);
        return args[index + 1];
    }

    private static List<string> PhysicalGpuNames()
    {
        var names = new List<string>();
        using var searcher = new ManagementObjectSearcher(
            "SELECT Name, PNPDeviceID FROM Win32_VideoController");
        using var devices = searcher.Get();
        foreach (ManagementObject device in devices)
        {
            var name = Convert.ToString(device["Name"]) ?? "";
            var pnpId = Convert.ToString(device["PNPDeviceID"]) ?? "";
            if (!pnpId.StartsWith("PCI\\VEN_", StringComparison.OrdinalIgnoreCase))
                continue;
            if (name.Contains("Microsoft Basic Display", StringComparison.OrdinalIgnoreCase) ||
                name.Contains("Microsoft Remote Display", StringComparison.OrdinalIgnoreCase) ||
                name.Contains("Parsec Virtual", StringComparison.OrdinalIgnoreCase))
                continue;
            names.Add(name.Trim());
        }
        return names.Distinct(StringComparer.OrdinalIgnoreCase).ToList();
    }

    private static DenseTensor<float> BuildInputTensor(string path)
    {
        using var source = new Bitmap(path);
        if (source.Width > InputSize || source.Height > InputSize)
            throw new InvalidDataException(
                $"Sample frame {Path.GetFileName(path)} is larger than the {InputSize}×{InputSize} YuNet input.");

        using var bitmap = new Bitmap(source.Width, source.Height, PixelFormat.Format24bppRgb);
        using (var graphics = Graphics.FromImage(bitmap))
        {
            graphics.Clear(Color.Black);
            graphics.InterpolationMode = InterpolationMode.HighQualityBicubic;
            graphics.DrawImageUnscaled(source, 0, 0);
        }

        var tensor = new DenseTensor<float>([1, 3, InputSize, InputSize]);
        var bounds = new Rectangle(0, 0, bitmap.Width, bitmap.Height);
        var data = bitmap.LockBits(bounds, ImageLockMode.ReadOnly, PixelFormat.Format24bppRgb);
        try
        {
            unsafe
            {
                var basePointer = (byte*)data.Scan0;
                for (var y = 0; y < bitmap.Height; y++)
                {
                    var row = basePointer + y * data.Stride;
                    for (var x = 0; x < bitmap.Width; x++)
                    {
                        var pixel = x * 3;
                        tensor[0, 0, y, x] = row[pixel];
                        tensor[0, 1, y, x] = row[pixel + 1];
                        tensor[0, 2, y, x] = row[pixel + 2];
                    }
                }
            }
        }
        finally
        {
            bitmap.UnlockBits(data);
        }
        return tensor;
    }

    private static IReadOnlyList<Detection> Decode(IReadOnlyDictionary<string, float[]> output)
    {
        var candidates = new List<Detection>();
        foreach (var stride in Strides)
        {
            var columns = InputSize / stride;
            var rows = InputSize / stride;
            var cls = output["cls_" + stride];
            var obj = output["obj_" + stride];
            var bbox = output["bbox_" + stride];

            for (var row = 0; row < rows; row++)
            {
                for (var column = 0; column < columns; column++)
                {
                    var index = row * columns + column;
                    var score = MathF.Sqrt(
                        Math.Clamp(cls[index], 0f, 1f) *
                        Math.Clamp(obj[index], 0f, 1f));
                    if (score < ScoreThreshold)
                        continue;

                    var cx = (column + bbox[index * 4]) * stride;
                    var cy = (row + bbox[index * 4 + 1]) * stride;
                    var width = MathF.Exp(bbox[index * 4 + 2]) * stride;
                    var height = MathF.Exp(bbox[index * 4 + 3]) * stride;
                    var x = cx - width / 2f;
                    var y = cy - height / 2f;
                    if (!float.IsFinite(x) || !float.IsFinite(y) ||
                        !float.IsFinite(width) || !float.IsFinite(height) ||
                        width <= 0 || height <= 0)
                        continue;

                    candidates.Add(new Detection(x, y, width, height, score));
                }
            }
        }

        var selected = new List<Detection>();
        foreach (var candidate in candidates.OrderByDescending(item => item.Score).Take(TopK))
        {
            if (selected.Any(existing => IntersectionOverUnion(candidate, existing) > NmsThreshold))
                continue;
            selected.Add(candidate);
        }
        return selected;
    }

    private static float IntersectionOverUnion(Detection left, Detection right)
    {
        var x1 = Math.Max(left.X, right.X);
        var y1 = Math.Max(left.Y, right.Y);
        var x2 = Math.Min(left.X + left.Width, right.X + right.Width);
        var y2 = Math.Min(left.Y + left.Height, right.Y + right.Height);
        var intersection = Math.Max(0f, x2 - x1) * Math.Max(0f, y2 - y1);
        var union = left.Width * left.Height + right.Width * right.Height - intersection;
        return union > 0 ? intersection / union : 0f;
    }
}
