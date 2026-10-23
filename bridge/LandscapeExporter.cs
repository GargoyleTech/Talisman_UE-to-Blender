using System.Runtime.InteropServices;
using CUE4Parse.UE4.Assets.Exports.Component.Landscape;
using CUE4Parse.UE4.Assets.Exports.Texture;
using CUE4Parse.UE4.Objects.UObject;
using CUE4Parse_Conversion.Textures;

/// <summary>Cooked terrain data, separate from StaticMesh and Rebirth MEC geometry.</summary>
internal sealed class LandscapeExporter
{
    private const long CacheLimit = 128L * 1024 * 1024;
    private readonly Dictionary<string, (CTexture Image, LinkedListNode<string> Node)> _images = new();
    private readonly LinkedList<string> _lru = new();
    private long _bytes;

    public void Clear() { _images.Clear(); _lru.Clear(); _bytes = 0; }

    public static object Metadata(ULandscapeComponent c, string map) => new
    {
        sourceMap = map, objectPath = c.GetPathName(), owner = c.Outer?.GetPathName(),
        quads = c.ComponentSizeQuads, subsectionQuads = c.SubsectionSizeQuads,
        subsections = c.NumSubsections, sectionBase = new[] { c.SectionBaseX, c.SectionBaseY },
    };

    public object Export(ULandscapeComponent c, string output, int requestedLod)
    {
        int full = c.ComponentSizeQuads, sub = c.SubsectionSizeQuads, sections = c.NumSubsections;
        if (sections is not (1 or 2) || sub < 1 || sub > 255 || ((sub + 1) & sub) != 0 || full != sub * sections)
            throw new InvalidDataException("Unsupported Landscape subsection topology.");
        if (requestedLod is < 0 or > 7) throw new ArgumentOutOfRangeException(nameof(requestedLod));
        var maxLod = System.Numerics.BitOperations.Log2((uint)(sub + 1)) - 1;
        int lod = Math.Min(requestedLod, maxLod), quads = sections * (((sub + 1) >> lod) - 1);
        int width = quads + 1, vertices = checked(width * width);
        var heightTexture = c.GetHeightmap() ?? throw new InvalidDataException("Landscape has no readable height texture.");
        var height = Image(heightTexture);
        int ox = (int)MathF.Round(c.HeightmapScaleBias.Z * height.Width), oy = (int)MathF.Round(c.HeightmapScaleBias.W * height.Height);
        if (ox < 0 || oy < 0 || ox + sections * (sub + 1) > height.Width || oy + sections * (sub + 1) > height.Height)
            throw new InvalidDataException("Landscape height atlas region is outside the stored mip.");
        var xyTexture = c.GetOrDefault<UTexture2D?>("XYOffsetmapTexture", null);
        var xy = xyTexture is null ? null : Image(xyTexture);
        var allocations = c.WeightmapLayerAllocations;
        if (allocations.Length > 256) throw new InvalidDataException("More than 256 Landscape layer allocations.");
        var weights = allocations.Length == 0 ? Array.Empty<UTexture2D>() : c.GetWeightmapTextures();
        var layers = new List<object>(); var weightImages = new List<(CTexture Image, int Channel)>();
        (CTexture Image, int Channel)? visibility = null;
        foreach (var a in allocations)
        {
            if (a.WeightmapTextureIndex >= weights.Length || a.WeightmapTextureChannel >= 4)
                throw new InvalidDataException("Landscape layer references an invalid weight texture/channel.");
            var image = Image(weights[a.WeightmapTextureIndex]);
            if (image.Width < sections * (sub + 1) || image.Height < sections * (sub + 1))
                throw new InvalidDataException("Landscape weight texture is smaller than its component.");
            string path = Ref(a.LayerInfo) ?? "", name = a.LayerInfo.Name;
            bool noWeightBlend = false;
            // Layer identity is useful even when an optional LayerInfo asset is unavailable.
            try
            {
                var info = a.LayerInfo.Load();
                if (info is not null && info.TryGetValue<FName>(out var layerName, "LayerName")) name = layerName.Text;
                noWeightBlend = info?.GetOrDefault("bNoWeightBlend", false) ?? false;
            }
            catch { }
            if (path.Contains("LandscapeVisibilityLayerInfo", StringComparison.OrdinalIgnoreCase) || name.Equals("Visibility", StringComparison.OrdinalIgnoreCase))
                visibility = (image, a.WeightmapTextureChannel);
            else
            {
                layers.Add(new { name, path, noWeightBlend, texture = weights[a.WeightmapTextureIndex].GetPathName(), channel = (int)a.WeightmapTextureChannel });
                weightImages.Add((image, a.WeightmapTextureChannel));
            }
        }
        var root = Path.TrimEndingDirectorySeparator(Path.GetFullPath(output)); Directory.CreateDirectory(root);
        var token = "landscape-" + Guid.NewGuid().ToString("N");
        var pending = Path.Combine(root, token + ".partial"); var final = Path.Combine(root, token);
        Directory.CreateDirectory(pending);
        var streams = new Dictionary<string, object>();
        try
        {
            var positions = new float[vertices * 3]; var normals = new float[vertices * 3];
            var paint = weightImages.Select(_ => new byte[vertices]).ToArray();
            for (int y = 0; y < width; y++) for (int x = 0; x < width; x++)
            {
                float sx = (float)x * full / quads, sy = (float)y * full / quads;
                int index = y * width + x, p = index * 3;
                var z = Sample(height, sub, sx, sy, full, 0, 1, ox, oy);
                positions[p] = sx; positions[p + 1] = sy; positions[p + 2] = (z - 32768) / 128;
                if (xy is not null)
                {
                    positions[p] += (Sample(xy, sub, sx, sy, full, 0, 1) - 32768) / 256;
                    positions[p + 1] += (Sample(xy, sub, sx, sy, full, 2, 3) - 32768) / 256;
                }
                float nx = Sample(height, sub, sx, sy, full, 2, -1, ox, oy) * (2f / 255) - 1;
                float ny = Sample(height, sub, sx, sy, full, 3, -1, ox, oy) * (2f / 255) - 1;
                normals[p] = nx; normals[p + 1] = ny; normals[p + 2] = MathF.Sqrt(Math.Max(0, 1 - nx * nx - ny * ny));
                for (int layer = 0; layer < paint.Length; layer++)
                {
                    var (wi, channel) = weightImages[layer];
                    paint[layer][index] = (byte)Math.Clamp((int)MathF.Round(Sample(wi, sub, sx, sy, full, channel)), 0, 255);
                }
            }
            Write("positions", MemoryMarshal.AsBytes(positions.AsSpan()), "<f4", vertices, 3);
            Write("normals", MemoryMarshal.AsBytes(normals.AsSpan()), "<f4", vertices, 3);
            for (int i = 0; i < paint.Length; i++) Write("paint" + i, paint[i], "|u1", vertices);
            var holes = new byte[quads * quads]; var holeCount = 0;
            if (visibility is { } vis)
                for (int y = 0; y < quads; y++) for (int x = 0; x < quads; x++)
                {
                    // A lower-resolution mesh conservatively preserves any hole in its covered area.
                    int x0 = x * full / quads, y0 = y * full / quads;
                    int x1 = Math.Min(full, (int)Math.Ceiling((double)(x + 1) * full / quads));
                    int y1 = Math.Min(full, (int)Math.Ceiling((double)(y + 1) * full / quads));
                    bool hole = false;
                    for (int yy = y0; yy < y1 && !hole; yy++) for (int xx = x0; xx < x1; xx++)
                        if (Channel(vis.Image, Texel(xx, sub), Texel(yy, sub), vis.Channel) >= 170) { hole = true; break; }
                    if (hole) { holes[y * quads + x] = 1; holeCount++; }
                }
            Write("holes", holes, "|u1", quads, quads);
            Directory.Move(pending, final);
            return new
            {
                objectPath = c.GetPathName(), owner = c.Outer?.GetPathName(), quads, sourceQuads = full, lod, requestedLod,
                vertexCount = vertices, triangleCount = (quads * quads - holeCount) * 2, holeQuads = holeCount,
                xyOffsets = xy is not null, sectionBase = new[] { c.SectionBaseX, c.SectionBaseY },
                heightmap = heightTexture.GetPathName(), layers,
                materials = c.GetOrDefault<FPackageIndex[]>("MaterialInstances", []).Select(Ref).ToArray(),
                overrideMaterial = Ref(c.OverrideMaterial), overrideHoleMaterial = Ref(c.OverrideHoleMaterial),
                landscapeMaterial = OwnerMaterial(c, "LandscapeMaterial"),
                landscapeHoleMaterial = OwnerMaterial(c, "LandscapeHoleMaterial"),
                holePolicy = lod == 0 ? "UE4_STATIC_EXPORT" : "ANY_COVERED_QUAD",
                binaryLandscape = new { version = 1, directory = final, streams },
            };
        }
        catch
        {
            if (Directory.Exists(pending) && Path.GetDirectoryName(pending) == root) Directory.Delete(pending, true);
            throw;
        }
        void Write(string name, ReadOnlySpan<byte> data, string dtype, params int[] shape)
        {
            using var file = new FileStream(Path.Combine(pending, name + ".bin"), FileMode.CreateNew, FileAccess.Write, FileShare.None);
            file.Write(data); streams[name] = new { file = name + ".bin", dtype, shape };
        }
    }

    private CTexture Image(UTexture2D texture)
    {
        var key = texture.GetPathName();
        if (_images.TryGetValue(key, out var cached)) { _lru.Remove(cached.Node); _lru.AddLast(cached.Node); return cached.Image; }
        var image = texture.DecodeMip(0) ?? throw new InvalidDataException("Terrain texture has no stored mip: " + key);
        if (image.Width != texture.PlatformData.SizeX || image.Height != texture.PlatformData.SizeY)
            throw new InvalidDataException("Terrain texture's full cooked resolution is unavailable: " + key);
        if (image.PixelFormat is not (EPixelFormat.PF_B8G8R8A8 or EPixelFormat.PF_R8G8B8A8) || image.Data.LongLength != checked((long)image.Width * image.Height * 4))
            throw new InvalidDataException("Terrain texture is not a supported RGBA8 image: " + key);
        while (_bytes + image.Data.LongLength > CacheLimit && _lru.First is { } oldest)
        {
            _bytes -= _images[oldest.Value].Image.Data.LongLength; _images.Remove(oldest.Value); _lru.RemoveFirst();
        }
        if (image.Data.LongLength <= CacheLimit) { _images[key] = (image, _lru.AddLast(key)); _bytes += image.Data.LongLength; }
        return image;
    }
    private static int Texel(int x, int sub) => x + (x > 0 ? (x - 1) / sub : 0);
    private static string? OwnerMaterial(ULandscapeComponent c, string property)
    {
        try { return Ref(c.Outer?.Load()?.GetOrDefault<FPackageIndex>(property)); }
        catch { return null; } // Optional actor material metadata must not discard usable geometry.
    }
    private static string? Ref(FPackageIndex? reference) => reference is null || reference.IsNull ? null : reference.ResolvedObject?.GetPathName() ?? reference.Name;
    private static int Channel(CTexture image, int x, int y, int channel)
    {
        if (x < 0 || y < 0 || x >= image.Width || y >= image.Height) throw new InvalidDataException("Terrain texture region is out of range.");
        int offset = image.PixelFormat == EPixelFormat.PF_B8G8R8A8 ? channel switch { 0 => 2, 1 => 1, 2 => 0, _ => 3 } : channel;
        return image.Data[(y * image.Width + x) * 4 + offset];
    }
    private static float Sample(CTexture image, int sub, float x, float y, int full, int channel, int low = -1, int ox = 0, int oy = 0)
    {
        int x0 = (int)MathF.Floor(x), y0 = (int)MathF.Floor(y), x1 = Math.Min(full, x0 + 1), y1 = Math.Min(full, y0 + 1);
        float tx = x - x0, ty = y - y0;
        int Read(int px, int py)
        {
            px = ox + Texel(px, sub); py = oy + Texel(py, sub);
            int value = Channel(image, px, py, channel);
            return low < 0 ? value : (value << 8) | Channel(image, px, py, low);
        }
        float a = Read(x0, y0);
        if (tx == 0 && ty == 0) return a;
        float b = Read(x1, y0), c = Read(x0, y1), d = Read(x1, y1);
        return (a + (b - a) * tx) * (1 - ty) + (c + (d - c) * tx) * ty;
    }
}
