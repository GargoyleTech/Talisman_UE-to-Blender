using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using CUE4Parse.FileProvider;
using CUE4Parse.UE4.AssetRegistry;
using CUE4Parse.UE4.Assets;
using CUE4Parse.UE4.Assets.Exports.Texture;
using CUE4Parse.UE4.Assets.Objects;
using CUE4Parse.UE4.Objects.UObject;
using CUE4Parse.UE4.Readers;
using CUE4Parse_Conversion.Textures;
using CUE4Parse_Conversion.Textures.BC;
using AssetRipper.TextureDecoder.Bc;
using AssetRipper.TextureDecoder.Rgb.Formats;
using SkiaSharp;

/// <summary>Texture discovery and a file mailbox, polled without Blender threads or pipe reads.</summary>
internal static class TextureBrowser
{
    internal sealed record Entry(string Path, string ObjectPath, string Name, string TextureType);
    private sealed record ScanProgress(int Count, int Scanned, int Total, bool Complete, int Failures = 0, int Registries = 0);
    private static readonly JsonSerializerOptions Json = new() { PropertyNamingPolicy = JsonNamingPolicy.CamelCase };
    private const int Schema = 1;

    private static bool IsTexture(string type) => type.Split('.').Last().StartsWith("Texture", StringComparison.OrdinalIgnoreCase);

    public static string ResolveObjectPath(DefaultFileProvider provider, IPackage package, string assetPath, string objectPath)
    {
        // Registries use /Game and /Engine aliases; package headers can retain
        // mounted Project/Content paths. Resolve aliases before exact export lookup.
        if (!GenericUnreal.ResolveAsset(provider, objectPath).Equals(assetPath, StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("The texture object does not belong to the selected package.");
        static string ObjectSuffix(string path)
        {
            var dot = path.IndexOf('.', path.LastIndexOf('/') + 1);
            return dot >= 0 ? path[dot..] : "";
        }
        var objectName = ObjectSuffix(objectPath);
        for (var index = 0; index < package.ExportMapLength; index++)
        {
            var resolved = package.ResolvePackageIndex(new FPackageIndex(package, index + 1));
            if (resolved is null) continue;
            var candidate = resolved.GetPathName();
            if (candidate.Equals(objectPath, StringComparison.OrdinalIgnoreCase) ||
                ObjectSuffix(candidate).Equals(objectName, StringComparison.OrdinalIgnoreCase))
                return candidate;
        }
        throw new InvalidOperationException("The selected texture object is missing from its package.");
    }

    private static void Write(string path, object payload)
    {
        var temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        File.WriteAllText(temporary, JsonSerializer.Serialize(payload, Json), Encoding.UTF8);
        for (var attempt = 0; ; attempt++)
        {
            try { File.Move(temporary, path, true); break; }
            catch (IOException) when (attempt < 5) { Thread.Sleep(20); }
        }
    }

    private static string Fingerprint(string packageDirectory, string configuration)
    {
        var values = new StringBuilder(configuration).Append('|').Append(Schema);
        foreach (var file in Directory.EnumerateFiles(packageDirectory, "*", SearchOption.AllDirectories)
                     .Where(path => new[] { ".pak", ".utoc", ".ucas" }.Contains(System.IO.Path.GetExtension(path).ToLowerInvariant()))
                     .OrderBy(path => path, StringComparer.OrdinalIgnoreCase))
        {
            var info = new FileInfo(file);
            values.Append('|').Append(info.FullName).Append(':').Append(info.Length).Append(':').Append(info.LastWriteTimeUtc.Ticks);
        }
        return Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(values.ToString())));
    }

    private static IEnumerable<ScanProgress> Index(CachedFileProvider provider, string directory, string signature,
        string? cachePath, bool force, Dictionary<string, Entry> entries)
    {
        var fingerprint = Fingerprint(directory, signature);
        Entry[]? cached = null;
        if (!force && !string.IsNullOrEmpty(cachePath) && File.Exists(cachePath))
        {
            try
            {
                using var cache = JsonDocument.Parse(File.ReadAllText(cachePath));
                if (cache.RootElement.GetProperty("fingerprint").GetString() == fingerprint)
                    cached = JsonSerializer.Deserialize<Entry[]>(cache.RootElement.GetProperty("entries"), Json);
            }
            catch { /* A stale or incomplete cache is rebuilt. */ }
        }
        if (cached is not null)
        {
            foreach (var entry in cached) entries[entry.ObjectPath] = entry;
            yield return new ScanProgress(entries.Count, 0, 0, true);
            yield break;
        }
        var indexedPackages = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var failures = 0;
        var registries = 0;
        foreach (var file in provider.Files.Where(item => item.Key.EndsWith("AssetRegistry.bin", StringComparison.OrdinalIgnoreCase)))
        {
            try
            {
                using var archive = new FByteArchive(file.Key, file.Value.Read(null), provider.Versions);
                var registry = new FAssetRegistryState(archive);
                foreach (var asset in registry.PreallocatedAssetDataBuffers)
                {
                    var path = GenericUnreal.ResolveAsset(provider, asset.PackageName.ToString());
                    if (!provider.Files.ContainsKey(path)) continue;
                    indexedPackages.Add(path);
                    var type = asset.AssetClass.Text;
                    if (!IsTexture(type)) continue;
                    var name = asset.AssetName.Text;
                    var objectPath = asset.PackageName + "." + name;
                    entries[objectPath] = new Entry(path, objectPath, name, type);
                }
                registries++;
            }
            catch { failures++; }
        }
        // Registries can be partial (DLC/mods, embedded exports). Scan packages
        // absent from them using class/name metadata, never texture pixels.
        var paths = provider.Files.Keys.Where(path => path.EndsWith(".umap", StringComparison.OrdinalIgnoreCase) ||
            path.EndsWith(".uasset", StringComparison.OrdinalIgnoreCase) && !indexedPackages.Contains(path)).ToArray();
        yield return new ScanProgress(entries.Count, 0, paths.Length, false, failures, registries);
        for (var position = 0; position < paths.Length; position++)
        {
            var path = paths[position];
            try
            {
                var package = provider.LoadPackage(path);
                for (var index = 0; index < package.ExportMapLength; index++)
                {
                    var type = package switch
                    {
                        IoPackage io => io.ResolveObjectIndex(io.ExportMap[index].ClassIndex)?.Name.Text ?? "",
                        Package legacy => legacy.ExportMap[index].ClassName ?? "",
                        _ => "",
                    };
                    if (!IsTexture(type)) continue;
                    var resolved = package.ResolvePackageIndex(new FPackageIndex(package, index + 1));
                    if (resolved is null) continue;
                    var objectPath = resolved.GetPathName();
                    entries[objectPath] = new Entry(path, objectPath, resolved.Name.Text, type);
                }
            }
            catch { failures++; }
            if (position % 256 == 255 || position + 1 == paths.Length)
            {
                provider.ClearPackageCache();
                yield return new ScanProgress(entries.Count, position + 1, paths.Length, false, failures, registries);
            }
        }
        var result = entries.Values.OrderBy(entry => entry.Path, StringComparer.OrdinalIgnoreCase)
            .ThenBy(entry => entry.Name, StringComparer.OrdinalIgnoreCase).ToArray();
        if (result.Length == 0 && failures > 0)
            throw new InvalidOperationException("No textures could be indexed. Check the game profile, mappings, AES key, and compression library.");
        if (!string.IsNullOrEmpty(cachePath))
        {
            try
            {
                Directory.CreateDirectory(System.IO.Path.GetDirectoryName(cachePath)!);
                Write(cachePath, new { fingerprint, entries = result });
            }
            catch (IOException) { /* Disk caching is optional. */ }
            catch (UnauthorizedAccessException) { }
        }
        yield return new ScanProgress(result.Length, paths.Length, paths.Length, true, failures, registries);
    }

    internal static object Browse(IEnumerable<Entry> entries, string directory, string search, int page, int pageSize = 128)
    {
        var prefix = directory.Trim('/') is { Length: > 0 } folder ? folder + "/" : "";
        var terms = search.Split(' ', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        var rows = new List<object>();
        if (terms.Length > 0)
        {
            rows.AddRange(entries.Where(entry => terms.All(term => (entry.Path + " " + entry.ObjectPath)
                .Contains(term, StringComparison.OrdinalIgnoreCase)))
                .OrderBy(entry => entry.Path, StringComparer.OrdinalIgnoreCase).ThenBy(entry => entry.Name, StringComparer.OrdinalIgnoreCase)
                .Select(entry => (object)new
                { entry.Path, entry.ObjectPath, entry.Name, entry.TextureType, isDirectory = false }));
        }
        else
        {
            var folders = new SortedSet<string>(StringComparer.OrdinalIgnoreCase);
            var files = new List<Entry>();
            foreach (var entry in entries.Where(entry => entry.Path.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)))
            {
                var rest = entry.Path[prefix.Length..];
                var slash = rest.IndexOf('/');
                if (slash >= 0) folders.Add(prefix + rest[..slash]);
                else files.Add(entry);
            }
            rows.AddRange(folders.Select(path => (object)new { path, objectPath = "", name = path.Split('/').Last(),
                textureType = "", isDirectory = true }));
            rows.AddRange(files.OrderBy(entry => entry.Path, StringComparer.OrdinalIgnoreCase).ThenBy(entry => entry.Name, StringComparer.OrdinalIgnoreCase)
                .Select(entry => (object)new { entry.Path, entry.ObjectPath, entry.Name, entry.TextureType, isDirectory = false }));
        }
        page = Math.Clamp(page, 0, Math.Max(0, (rows.Count - 1) / pageSize));
        return new { rows = rows.Skip(page * pageSize).Take(pageSize), total = rows.Count, page, pageSize };
    }

    private sealed class MemoryBulkData(byte[] data) : TBulkData<byte>(data);

    public static byte[] DecodePreview(UTexture texture, byte[] pixels, int width, int height, EPixelFormat format)
    {
        if (texture.Format != format)
        {
            // Remake's resident-mip adapter recovers a format discarded by the
            // parser. Decode those recovered bytes with the same library's BC codecs.
            byte[] rgba;
            if (format == EPixelFormat.PF_BC7)
                Bc7.Decompress<ColorRGBA<byte>, byte>(pixels, width, height, out rgba);
            else rgba = format switch
            {
                EPixelFormat.PF_DXT1 => BCDecoder.BC1(pixels, width, height, 1),
                EPixelFormat.PF_DXT3 => BCDecoder.BC2(pixels, width, height, 1),
                EPixelFormat.PF_DXT5 => BCDecoder.BC3(pixels, width, height, 1),
                EPixelFormat.PF_BC4 => BCDecoder.BC4(pixels, width, height, 1),
                EPixelFormat.PF_BC5 => BCDecoder.BC5(pixels, width, height, 1),
                EPixelFormat.PF_BC6H => BCDecoder.BC6H(pixels, width, height, 1),
                _ => throw new NotSupportedException("The recovered texture format cannot be previewed: " + format),
            };
            return EncodePreview(new CTexture(width, height,
                format is EPixelFormat.PF_BC4 or EPixelFormat.PF_BC5 ? EPixelFormat.PF_B8G8R8A8 : EPixelFormat.PF_R8G8B8A8, rgba));
        }
        var mip = new FTexture2DMipMap(new MemoryBulkData(pixels), width, height, 1);
        var decoded = texture.Decode(mip) ?? throw new InvalidOperationException("No readable texture pixels for this preview.");
        return EncodePreview(decoded);
    }

    public static byte[] EncodePreview(CTexture texture)
    {
        using var bitmap = texture.ToSkBitmap();
        // Unreal alphas commonly store masks; preview RGB even when alpha is zero.
        using var opaque = new SKBitmap();
        var info = bitmap.Info;
        info.AlphaType = SKAlphaType.Opaque;
        if (!opaque.InstallPixels(info, bitmap.GetPixels(), bitmap.RowBytes))
            throw new InvalidOperationException("The texture preview pixels could not be read.");
        var ratio = Math.Min(1.0, 384 / (double)Math.Max(bitmap.Width, bitmap.Height));
        using var resized = opaque.Resize(new SKImageInfo(Math.Max(1, (int)(bitmap.Width * ratio)),
            Math.Max(1, (int)(bitmap.Height * ratio))), SKFilterQuality.Medium)
            ?? throw new InvalidDataException("The texture preview could not be resized.");
        var colors = resized.Pixels;
        for (var index = 0; index < colors.Length; index++) colors[index] = colors[index].WithAlpha(255);
        resized.Pixels = colors;
        using var image = SKImage.FromBitmap(resized);
        using var data = image.Encode(SKEncodedImageFormat.Png, 100);
        return data.ToArray();
    }

    public static void Run(CachedFileProvider provider, string mailbox, string packageDirectory,
        Func<JsonElement, string, Dictionary<string, object?>> export)
    {
        Directory.CreateDirectory(mailbox);
        if (provider.Files.Count == 0)
            throw new InvalidOperationException("No packages were mounted. Check the game folder, profile, AES key, and compression library.");
        Write(System.IO.Path.Combine(mailbox, "ready.json"), new { ok = true });
        var entries = new Dictionary<string, Entry>(StringComparer.OrdinalIgnoreCase);
        IEnumerator<ScanProgress>? scan = null;
        var idle = DateTime.UtcNow;
        // A dead Blender process cannot leave the mounted provider alive forever.
        while (Directory.Exists(mailbox) && DateTime.UtcNow - idle < TimeSpan.FromMinutes(5))
        {
            var file = Directory.EnumerateFiles(mailbox, "request-*.json").Order().FirstOrDefault();
            if (file is null) { Thread.Sleep(40); continue; }
            idle = DateTime.UtcNow;
            var id = System.IO.Path.GetFileNameWithoutExtension(file)["request-".Length..];
            var result = System.IO.Path.Combine(mailbox, "response-" + id + ".json");
            try
            {
                using var request = JsonDocument.Parse(File.ReadAllText(file));
                var root = request.RootElement;
                var action = root.GetProperty("action").GetString();
                object payload;
                if (action is "index" or "index_step")
                {
                    if (action == "index")
                    {
                        scan?.Dispose();
                        entries.Clear();
                        scan = Index(provider, packageDirectory, root.GetProperty("signature").GetString()!,
                            root.GetProperty("cachePath").GetString(), root.TryGetProperty("force", out var force) && force.GetBoolean(), entries).GetEnumerator();
                    }
                    if (scan is null || !scan.MoveNext()) throw new InvalidOperationException("The texture index is not running.");
                    payload = scan.Current;
                    Write(System.IO.Path.Combine(mailbox, "progress.json"), payload);
                    if (scan.Current.Complete) { scan.Dispose(); scan = null; }
                }
                else if (action == "browse")
                    payload = Browse(entries.Values, root.GetProperty("directory").GetString() ?? "",
                        root.GetProperty("search").GetString() ?? "", root.GetProperty("page").GetInt32());
                else if (action is "preview" or "texture")
                {
                    var output = System.IO.Path.Combine(mailbox, "image-" + id + (action == "preview" ? ".png" : ".dds"));
                    var info = export(root, output);
                    payload = info;
                }
                else throw new ArgumentException("Unknown texture browser request.");
                Write(result, new { ok = true, payload });
            }
            catch (Exception error)
            {
                // Never echo command lines, keys, or third-party exception data.
                var message = error is NotSupportedException or NotImplementedException or InvalidOperationException
                    ? error.Message : "The texture request failed. Check the game profile and package configuration.";
                Write(result, new { ok = false, error = message, errorType = error.GetType().Name });
            }
            finally { File.Delete(file); provider.ClearPackageCache(); }
        }
    }
}
