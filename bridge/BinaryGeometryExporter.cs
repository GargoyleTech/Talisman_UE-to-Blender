using System.Collections;
using System.Runtime.InteropServices;

/// <summary>Keep mesh-sized numeric streams out of the JSON control channel.</summary>
internal static class BinaryGeometryExporter
{
    public static Dictionary<string, object?> Export(Dictionary<string, object?> mesh, string outputDirectory)
    {
        if (mesh.ContainsKey("binaryGeometry")) return mesh; // Already streamed by Nanite.
        var root = Path.TrimEndingDirectorySeparator(Path.GetFullPath(outputDirectory));
        Directory.CreateDirectory(root);
        var token = "geometry-" + Guid.NewGuid().ToString("N");
        var pending = Path.Combine(root, token + ".partial");
        var final = Path.Combine(root, token);
        Directory.CreateDirectory(pending);
        var result = new Dictionary<string, object?>(mesh);
        var streams = new Dictionary<string, object>();
        var vertices = Convert.ToInt32(mesh["vertexCount"]);
        var triangles = Convert.ToInt32(mesh["triangleCount"]);
        try
        {
            void Rows(string name, object? rows, int width, bool colors = false)
            {
                if (rows is not IEnumerable items) throw new InvalidDataException($"Missing {name} stream.");
                using var writer = Writer(pending, name);
                var count = 0;
                foreach (var row in items)
                {
                    if (row is not ICollection values || values.Count != width)
                        throw new InvalidDataException($"Invalid {name} row.");
                    if (!colors && row is float[] floats)
                        writer.Write(MemoryMarshal.AsBytes(floats.AsSpan()));
                    else foreach (var value in values)
                    {
                        if (colors) writer.Write(checked(Convert.ToByte(value)));
                        else writer.Write(Convert.ToSingle(value));
                    }
                    count++;
                }
                if (count != vertices) throw new InvalidDataException($"Mismatched {name} vertex count.");
                streams[name] = Descriptor(name, colors ? "|u1" : "<f4", vertices, width);
            }
            Rows("positions", mesh.GetValueOrDefault("positions"), 3);
            Rows("normals", mesh.GetValueOrDefault("normals"), 3);
            if (mesh.GetValueOrDefault("tangents") is { } tangents) Rows("tangents", tangents, 4);
            if (mesh.GetValueOrDefault("colors") is { } colors) Rows("colors", colors, 4, true);
            var channel = 0;
            if (mesh.GetValueOrDefault("uvChannels") is IEnumerable uvs)
                foreach (var uv in uvs)
                {
                    if (channel >= 8) throw new InvalidDataException("More than eight UV channels.");
                    Rows($"uv{channel++}", uv, 2);
                }
            using (var writer = Writer(pending, "indices"))
            {
                var count = 0;
                foreach (var index in (IEnumerable)mesh["indices"]!)
                {
                    var value = checked(Convert.ToInt32(index));
                    if (value < 0 || value >= vertices) throw new InvalidDataException("Invalid mesh index.");
                    writer.Write(value);
                    count++;
                }
                if (count != checked(triangles * 3)) throw new InvalidDataException("Mismatched triangle count.");
                streams["indices"] = Descriptor("indices", "<i4", count);
            }
            if (mesh.GetValueOrDefault("weights") is IEnumerable weights)
            {
                using var offsets = Writer(pending, "weightOffsets");
                using var pairs = Writer(pending, "weightPairs");
                int count = 0, rows = 0;
                offsets.Write(0);
                foreach (IEnumerable influences in weights)
                {
                    foreach (IList pair in influences)
                    {
                        if (pair.Count != 2) throw new InvalidDataException("Invalid skin influence.");
                        pairs.Write(Convert.ToSingle(pair[0]));
                        pairs.Write(Convert.ToSingle(pair[1]));
                        count = checked(count + 1);
                    }
                    offsets.Write(count);
                    rows++;
                }
                if (rows != vertices) throw new InvalidDataException("Mismatched skin-weight vertex count.");
                streams["weightOffsets"] = Descriptor("weightOffsets", "<i4", vertices + 1);
                streams["weightPairs"] = Descriptor("weightPairs", "<f4", count, 2);
                result["skinInfluenceCount"] = count;
            }
            foreach (var field in new[] { "positions", "normals", "tangents", "uvChannels", "colors", "indices", "weights" })
                result.Remove(field);
            if (mesh.GetValueOrDefault("lods") is IEnumerable lods)
                result["lods"] = lods.Cast<Dictionary<string, object?>>()
                    .Select(lod => Export(lod, root)).ToList();
            Directory.Move(pending, final);
            result["binaryGeometry"] = new { version = 1, directory = final, streams };
            return result;
        }
        catch
        {
            if (Directory.Exists(pending) && Path.GetDirectoryName(pending) == root)
                Directory.Delete(pending, true);
            throw;
        }
    }

    private static BinaryWriter Writer(string directory, string name) => new(new FileStream(
        Path.Combine(directory, name + ".bin"), FileMode.CreateNew, FileAccess.Write,
        FileShare.None, 262144, FileOptions.SequentialScan));

    private static object Descriptor(string name, string dtype, params int[] shape) =>
        new { file = name + ".bin", dtype, shape };
}
