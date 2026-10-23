using System.Diagnostics;
using System.Runtime.CompilerServices;
using CUE4Parse.UE4.Assets.Exports.Nanite;
using CUE4Parse.UE4.Assets.Exports.StaticMesh;
using CUE4Parse.UE4.Objects.Core.Math;

/// <summary>Stream the finest stored Nanite surface without retaining a mesh-sized DTO.</summary>
internal static class NaniteMeshExporter
{
    internal const int BinaryVersion = 1;
    private const int MaxUvChannels = 8;

    public static bool HasGeometry(UStaticMesh mesh) =>
        mesh.RenderData?.NaniteResources is { PageStreamingStates.Length: > 0 };

    public static Dictionary<string, object?> Export(
        UStaticMesh mesh, string outputDirectory, long triangleLimit, int cacheMiB)
    {
        if (triangleLimit < 0 || cacheMiB < 0 || cacheMiB > 16384)
            throw new ArgumentException("Invalid Nanite triangle/cache limits.");
        var resources = mesh.RenderData?.NaniteResources
            ?? throw new InvalidOperationException("The mesh has no Nanite resources.");
        if (resources.PageStreamingStates.Length == 0)
            throw new InvalidOperationException("The mesh has no stored Nanite pages.");
        if (resources.AssemblyTransforms is { Length: > 0 })
            throw new NotSupportedException("Nanite assemblies need assembly-instance reconstruction; this static surface decoder cannot flatten them safely.");

        var timer = Stopwatch.StartNew();
        Console.Error.WriteLine($"[Nanite] {mesh.Name}: {resources.PageStreamingStates.Length:N0} pages, {resources.NumInputTriangles:N0} build-input triangles; decoding finest clusters.");
        var root = Path.TrimEndingDirectorySeparator(Path.GetFullPath(outputDirectory));
        Directory.CreateDirectory(root);
        var token = "nanite-" + Guid.NewGuid().ToString("N");
        var pending = Path.Combine(root, token + ".partial");
        var final = Path.Combine(root, token);
        Directory.CreateDirectory(pending);
        try
        {
            using var cache = new PageCache(resources, cacheMiB, pending);
            using var output = new GeometryStreams(pending);
            long vertexCount = 0, triangleCount = 0;
            var leafCount = 0;
            var allClusterCount = 0;
            var explicitTangents = false;
            var staticMaterials = mesh.StaticMaterials ?? [];
            if (staticMaterials.Length == 0)
                staticMaterials = mesh.GetOrDefault<FStaticMaterial[]>("StaticMaterials", []);
            var fallbackMaterials = mesh.Materials ?? [];
            var materialCount = Math.Max(1, Math.Max(staticMaterials.Length, fallbackMaterials.Length));

            for (var pageIndex = 0; pageIndex < resources.PageStreamingStates.Length; pageIndex++)
            {
                cache.Prepare(pageIndex);
                var page = resources.GetPage((uint)pageIndex)
                    ?? throw new InvalidDataException($"Nanite page {pageIndex} could not be decoded; incomplete native geometry was rejected.");
                cache.Observe(pageIndex);
                allClusterCount += page.Clusters.Length;
                foreach (var cluster in page.Clusters)
                {
                    // A negative edge length is the finest-cluster marker used by
                    // CUE4Parse's native converter. Other clusters overlap these.
                    if (!(cluster.EdgeLength < 0)) continue;
                    if (cluster.bSkinning || cluster.bVoxel || cluster.bCurve)
                        throw new NotSupportedException("This Nanite resource contains skinned, voxel, or curve clusters, not a rigid triangle surface.");
                    if (cluster.Vertices.Length != cluster.NumVerts || cluster.TriIndices.Length != cluster.NumTris)
                        throw new InvalidDataException("Nanite cluster geometry counts do not match its header.");
                    if (cluster.NumUVs > MaxUvChannels)
                        throw new InvalidDataException("Nanite mesh exceeds the supported eight UV sets.");
                    var nextTriangles = checked(triangleCount + cluster.TriIndices.Length);
                    if (triangleLimit > 0 && nextTriangles > triangleLimit)
                        throw new NaniteBudgetException($"Native Nanite geometry exceeds the {triangleLimit:N0}-triangle limit; no truncated mesh was imported.");
                    if (vertexCount + cluster.Vertices.Length > int.MaxValue)
                        throw new NaniteBudgetException("Native Nanite geometry exceeds Blender's 32-bit vertex index range.");
                    if (nextTriangles * 3 > int.MaxValue)
                        throw new NaniteBudgetException("Native Nanite geometry exceeds Blender's 32-bit loop index range.");
                    output.EnsureUvs((int)cluster.NumUVs, vertexCount);
                    var vertexBase = (int)vertexCount;
                    foreach (var vertex in cluster.Vertices)
                    {
                        if (vertex?.Attributes is not { } attributes)
                            throw new InvalidDataException("Nanite vertex reference or attributes were not fully resolved.");
                        Validate(vertex.Pos, "position");
                        Validate(attributes.Normal, "normal");
                        if (attributes.Normal.SizeSquared() < 1e-12f)
                            throw new InvalidDataException("Nanite vertex has a zero normal.");
                        if (attributes.UVs.Length < cluster.NumUVs)
                            throw new InvalidDataException("Nanite vertex has missing UV channels.");
                        output.Vector(output.Positions, vertex.Pos);
                        output.Vector(output.Normals, attributes.Normal);
                        var tangent = attributes.TangentXAndSign;
                        if (cluster.bHasTangents &&
                            (!float.IsFinite(tangent.X) || !float.IsFinite(tangent.Y) || !float.IsFinite(tangent.Z) || !float.IsFinite(tangent.W)))
                            throw new InvalidDataException("Nanite vertex has a non-finite tangent.");
                        output.Tangents.Write(cluster.bHasTangents ? tangent.X : 0f);
                        output.Tangents.Write(cluster.bHasTangents ? tangent.Y : 0f);
                        output.Tangents.Write(cluster.bHasTangents ? tangent.Z : 0f);
                        output.Tangents.Write(cluster.bHasTangents ? tangent.W : 1f);
                        for (var channel = 0; channel < output.Uvs.Count; channel++)
                        {
                            var uv = channel < attributes.UVs.Length ? attributes.UVs[channel] : default;
                            if (!float.IsFinite(uv.X) || !float.IsFinite(uv.Y))
                                throw new InvalidDataException("Nanite vertex has non-finite UV coordinates.");
                            output.Uvs[channel].Write(uv.X);
                            output.Uvs[channel].Write(uv.Y);
                        }
                        output.Colors.Write(attributes.Color.R);
                        output.Colors.Write(attributes.Color.G);
                        output.Colors.Write(attributes.Color.B);
                        output.Colors.Write(attributes.Color.A);
                    }
                    for (var triIndex = 0; triIndex < cluster.TriIndices.Length; triIndex++)
                    {
                        var triangle = cluster.TriIndices[triIndex];
                        if (triangle.X >= cluster.NumVerts || triangle.Y >= cluster.NumVerts || triangle.Z >= cluster.NumVerts)
                            throw new InvalidDataException("Nanite triangle references an invalid vertex.");
                        var material = cluster.GetMaterialIndex((uint)triIndex);
                        if (material >= materialCount)
                            throw new InvalidDataException($"Nanite material index {material} exceeds the mesh's {materialCount} material slots.");
                        var indices = output.MaterialIndices((int)material);
                        indices.Write(checked(vertexBase + (int)triangle.X));
                        indices.Write(checked(vertexBase + (int)triangle.Y));
                        indices.Write(checked(vertexBase + (int)triangle.Z));
                    }
                    vertexCount += cluster.Vertices.Length;
                    triangleCount = nextTriangles;
                    explicitTangents |= cluster.bHasTangents;
                    leafCount++;
                }
                cache.Trim(pageIndex);
                if (pageIndex == 0 || (pageIndex + 1) % 128 == 0)
                    Console.Error.WriteLine($"[Nanite] {mesh.Name}: page {pageIndex + 1}/{resources.PageStreamingStates.Length}, {triangleCount:N0} triangles ({timer.Elapsed.TotalSeconds:F1}s).");
            }
            if (triangleCount == 0 || vertexCount == 0)
                throw new InvalidDataException("No finest Nanite triangle clusters were recovered.");
            if (resources.NumClusters > 0 && allClusterCount != resources.NumClusters)
                throw new InvalidDataException($"Nanite cluster count mismatch: decoded {allClusterCount}, expected {resources.NumClusters}.");

            var sectionCounts = output.Complete(explicitTangents);
            var sections = new List<object>();
            long firstIndex = 0;
            foreach (var (materialIndex, count) in sectionCounts)
            {
                var slot = materialIndex < staticMaterials.Length ? staticMaterials[materialIndex] : null;
                var fallback = materialIndex < fallbackMaterials.Length ? fallbackMaterials[materialIndex] : null;
                var materialPath = slot?.MaterialInterface?.ResolvedObject?.GetPathName() ?? fallback?.ResolvedObject?.GetPathName();
                var slotName = slot?.MaterialSlotName.Text;
                if (string.IsNullOrWhiteSpace(slotName) || slotName.Equals("None", StringComparison.OrdinalIgnoreCase))
                    slotName = fallback?.Name ?? materialPath?.Split('.').LastOrDefault();
                sections.Add(new Dictionary<string, object?>
                {
                    ["materialIndex"] = materialIndex, ["materialName"] = slotName,
                    ["materialPath"] = materialPath, ["firstIndex"] = firstIndex,
                    ["triangleCount"] = count / 3, ["castShadow"] = true,
                });
                firstIndex += count;
            }
            if (firstIndex != triangleCount * 3)
                throw new InvalidDataException("Nanite material sections do not cover the decoded triangle stream.");
            var streams = new Dictionary<string, object>
            {
                ["positions"] = Stream("positions.bin", "<f4", vertexCount, 3),
                ["normals"] = Stream("normals.bin", "<f4", vertexCount, 3),
                ["colors"] = Stream("colors.bin", "|u1", vertexCount, 4),
                ["indices"] = Stream("indices.bin", "<i4", triangleCount * 3),
            };
            if (explicitTangents) streams["tangents"] = Stream("tangents.bin", "<f4", vertexCount, 4);
            for (var i = 0; i < output.Uvs.Count; i++)
                streams[$"uv{i}"] = Stream($"uv{i}.bin", "<f4", vertexCount, 2);
            cache.Dispose();
            Directory.Move(pending, final);
            return new Dictionary<string, object?>
            {
                ["name"] = mesh.Name.ToString(), ["objectPath"] = mesh.GetPathName(),
                ["sourceType"] = "Native Nanite finest clusters", ["geometrySource"] = "NANITE",
                ["renderData"] = "Nanite", ["lodIndex"] = 0,
                ["vertexCount"] = vertexCount, ["triangleCount"] = triangleCount,
                ["sections"] = sections,
                ["binaryGeometry"] = new { version = BinaryVersion, directory = final, streams },
                ["nanite"] = new
                {
                    sourceTriangles = resources.NumInputTriangles, sourceVertices = resources.NumInputVertices,
                    totalPages = resources.PageStreamingStates.Length, totalClusters = allClusterCount,
                    finestClusters = leafCount, complete = true, uvChannels = output.Uvs.Count,
                    explicitTangents, triangleLimit, cacheMiB, peakDecodedPageBytes = cache.PeakBytes,
                    referenceSpillBytes = cache.SpillBytes, referencePageReads = cache.SpillReads,
                    elapsedSeconds = timer.Elapsed.TotalSeconds,
                },
            };
        }
        catch
        {
            // Both paths are generated immediate children of the requested output.
            if (Directory.Exists(pending) && Path.GetDirectoryName(pending) == root)
                Directory.Delete(pending, true);
            throw;
        }
        finally
        {
            Array.Clear(resources.LoadedPages);
        }
    }

    private static object Stream(string file, string dtype, params long[] shape) => new { file, dtype, shape };

    private static void Validate(FVector value, string name)
    {
        if (!float.IsFinite(value.X) || !float.IsFinite(value.Y) || !float.IsFinite(value.Z))
            throw new InvalidDataException($"Nanite vertex has a non-finite {name}.");
    }

    private sealed class GeometryStreams : IDisposable
    {
        private readonly string _directory;
        private readonly List<BinaryWriter> _writers = [];
        private readonly SortedDictionary<int, BinaryWriter> _materials = [];
        public readonly BinaryWriter Positions, Normals, Tangents, Colors;
        public readonly List<BinaryWriter> Uvs = [];

        public GeometryStreams(string directory)
        {
            _directory = directory;
            try
            {
                Positions = Writer("positions.bin"); Normals = Writer("normals.bin");
                Tangents = Writer("tangents.bin"); Colors = Writer("colors.bin");
            }
            catch { Dispose(); throw; }
        }
        private BinaryWriter Writer(string name)
        {
            var writer = new BinaryWriter(new FileStream(Path.Combine(_directory, name),
                FileMode.CreateNew, FileAccess.Write, FileShare.None, 262144, FileOptions.SequentialScan));
            _writers.Add(writer);
            return writer;
        }
        public void Vector(BinaryWriter writer, FVector value)
        { writer.Write(value.X); writer.Write(value.Y); writer.Write(value.Z); }
        public void EnsureUvs(int count, long previousVertices)
        {
            while (Uvs.Count < count)
            {
                var writer = Writer($"uv{Uvs.Count}.bin");
                writer.BaseStream.SetLength(previousVertices * 8);
                writer.BaseStream.Position = previousVertices * 8;
                Uvs.Add(writer);
            }
        }
        public BinaryWriter MaterialIndices(int index)
        {
            if (!_materials.TryGetValue(index, out var writer))
                _materials[index] = writer = Writer($"material-{index}.tmp");
            return writer;
        }
        public List<(int Index, long Count)> Complete(bool tangents)
        {
            foreach (var writer in _writers) writer.Dispose();
            var sections = new List<(int, long)>();
            using (var indices = new FileStream(Path.Combine(_directory, "indices.bin"), FileMode.CreateNew))
                foreach (var index in _materials.Keys)
                {
                    var path = Path.Combine(_directory, $"material-{index}.tmp");
                    using (var input = File.OpenRead(path))
                    {
                        sections.Add((index, input.Length / 4));
                        input.CopyTo(indices, 262144);
                    }
                    File.Delete(path);
                }
            if (!tangents) File.Delete(Path.Combine(_directory, "tangents.bin"));
            return sections;
        }
        public void Dispose() { foreach (var writer in _writers) writer.Dispose(); }
    }

    private sealed class PageCache : IDisposable
    {
        private readonly FNaniteResources _resources;
        private readonly int[] _lastUse;
        private readonly Dictionary<int, long> _sizes = [];
        private readonly Dictionary<int, long> _touches = [];
        private readonly Dictionary<int, long> _offsets = [];
        private readonly long _limit;
        private readonly bool _ordered;
        private readonly string _spillPath;
        private FileStream? _spill;
        private BinaryWriter? _writer;
        private BinaryReader? _reader;
        private long _clock;
        public long PeakBytes { get; private set; }
        public long SpillBytes { get; private set; }
        public int SpillReads { get; private set; }
        public PageCache(FNaniteResources resources, int cacheMiB, string directory)
        {
            _resources = resources;
            _spillPath = Path.Combine(directory, "references.tmp");
            _ordered = true;
            resources.LoadedPages = new FNaniteStreamableData[resources.PageStreamingStates.Length];
            _lastUse = Enumerable.Range(0, resources.PageStreamingStates.Length).ToArray();
            for (var i = 0; i < _lastUse.Length; i++)
            {
                var page = resources.PageStreamingStates[i];
                if ((long)page.DependenciesStart + page.DependenciesNum > resources.PageDependencies.Length)
                    throw new InvalidDataException("Nanite page dependency range is invalid.");
                for (var j = 0; j < page.DependenciesNum; j++)
                {
                    var dep = resources.PageDependencies[page.DependenciesStart + j];
                    if (dep >= _lastUse.Length) throw new InvalidDataException("Nanite page dependency is invalid.");
                    if (dep >= i) _ordered = false;
                    _lastUse[dep] = Math.Max(_lastUse[dep], i);
                }
            }
            if (!_ordered) ValidateAcyclicDependencies(resources);
            _limit = cacheMiB * 1024L * 1024;
        }
        private static void ValidateAcyclicDependencies(FNaniteResources resources)
        {
            var count = resources.PageStreamingStates.Length;
            var remaining = new int[count];
            var dependents = new List<int>?[count];
            for (var i = 0; i < count; i++)
            {
                var state = resources.PageStreamingStates[i];
                remaining[i] = checked((int)state.DependenciesNum);
                for (var j = 0; j < state.DependenciesNum; j++)
                {
                    var dep = resources.PageDependencies[state.DependenciesStart + j];
                    (dependents[dep] ??= []).Add(i);
                }
            }
            var queue = new Queue<int>(Enumerable.Range(0, count).Where(i => remaining[i] == 0));
            var visited = 0;
            while (queue.TryDequeue(out var page))
            {
                visited++;
                foreach (var dependent in dependents[page] ?? [])
                    if (--remaining[dependent] == 0) queue.Enqueue(dependent);
            }
            if (visited != count) throw new InvalidDataException("Nanite page dependencies contain a cycle.");
        }
        public void Prepare(int index)
        {
            if (!_ordered) return;
            var state = _resources.PageStreamingStates[index];
            for (var j = 0; j < state.DependenciesNum; j++)
            {
                var dep = (int)_resources.PageDependencies[state.DependenciesStart + j];
                if (_resources.LoadedPages[dep] is null)
                {
                    if (!_offsets.TryGetValue(dep, out var offset))
                        throw new InvalidDataException($"Nanite dependency page {dep} has no decoded vertex references.");
                    var restored = ReadReferences(offset);
                    _resources.LoadedPages[dep] = restored;
                    _sizes[dep] = Estimate(restored);
                }
                _touches[dep] = ++_clock;
            }
        }
        public void Observe(int index)
        {
            // Ordered dependencies have all been restored by Prepare; only
            // this primary page is newly decoded. Avoid scanning every page.
            var start = _ordered ? index : 0;
            var end = _ordered ? index + 1 : _resources.LoadedPages.Length;
            for (var i = start; i < end; i++)
                if (_resources.LoadedPages[i] is { } page && !_sizes.ContainsKey(i))
                {
                    _sizes[i] = Estimate(page);
                    _touches[i] = ++_clock;
                }
            PeakBytes = Math.Max(PeakBytes, _sizes.Values.Sum());
        }
        private static long Estimate(FNaniteStreamableData page) => page.Clusters.Sum(cluster =>
            (long)cluster.Vertices.Length * (128 + 8 * 8) + (cluster.TriIndices?.Length ?? 0) * 12L + 512);
        public void Trim(int index)
        {
            foreach (var key in _sizes.Keys.Where(key => _lastUse[key] <= index).ToArray()) Evict(key);
            var bytes = _sizes.Values.Sum();
            if (_limit > 0 && bytes > _limit)
                foreach (var key in _sizes.Keys.OrderBy(key => _touches[key]).ToArray())
                {
                    bytes -= _sizes[key]; Evict(key, preserve: _ordered);
                    if (bytes <= _limit) break;
                }
        }
        private void Evict(int index, bool preserve = false)
        {
            if (preserve && !_offsets.ContainsKey(index)) WriteReferences(index);
            _resources.LoadedPages[index] = null!;
            _sizes.Remove(index); _touches.Remove(index);
        }
        private void WriteReferences(int index)
        {
            if (_spill is null)
            {
                _spill = new FileStream(_spillPath, FileMode.CreateNew, FileAccess.ReadWrite, FileShare.None, 262144);
                _writer = new BinaryWriter(_spill, System.Text.Encoding.UTF8, leaveOpen: true);
                _reader = new BinaryReader(_spill, System.Text.Encoding.UTF8, leaveOpen: true);
            }
            _spill.Position = _spill.Length;
            _offsets[index] = _spill.Position;
            var clusters = _resources.LoadedPages[index]!.Clusters;
            _writer!.Write(clusters.Length);
            foreach (var cluster in clusters)
            {
                // Only RawPos and Attributes are read from a dependency by
                // CUE4Parse's ResolveVertexReferences; do not retain its topology.
                if (cluster.bSkinning || cluster.bVoxel || cluster.bCurve)
                    throw new NotSupportedException("Nanite reference spilling requires rigid triangle clusters.");
                _writer.Write(cluster.Vertices.Length);
                foreach (var vertex in cluster.Vertices)
                {
                    var attributes = vertex?.Attributes
                        ?? throw new InvalidDataException("Incomplete Nanite dependency vertex.");
                    _writer.Write(vertex!.RawPos.X); _writer.Write(vertex.RawPos.Y); _writer.Write(vertex.RawPos.Z);
                    _writer.Write(attributes.Normal.X); _writer.Write(attributes.Normal.Y); _writer.Write(attributes.Normal.Z);
                    var tangent = attributes.TangentXAndSign;
                    _writer.Write(tangent.X); _writer.Write(tangent.Y); _writer.Write(tangent.Z); _writer.Write(tangent.W);
                    _writer.Write(attributes.Color.R); _writer.Write(attributes.Color.G);
                    _writer.Write(attributes.Color.B); _writer.Write(attributes.Color.A);
                    if (attributes.UVs.Length > MaxUvChannels)
                        throw new InvalidDataException("Invalid Nanite dependency UV count.");
                    _writer.Write(attributes.UVs.Length);
                    foreach (var uv in attributes.UVs) { _writer.Write(uv.X); _writer.Write(uv.Y); }
                }
            }
            _writer.Flush();
            SpillBytes = _spill.Length;
        }
        private FNaniteStreamableData ReadReferences(long offset)
        {
            _spill!.Position = offset;
            var reader = _reader!;
            // These deliberately minimal objects are only used as reference
            // sources by the native decoder, never as primary/exportable pages.
            // Ordered page dependencies guarantee their primary export is past.
            var page = (FNaniteStreamableData)RuntimeHelpers.GetUninitializedObject(typeof(FNaniteStreamableData));
            page.Clusters = new FCluster[reader.ReadInt32()];
            for (var i = 0; i < page.Clusters.Length; i++)
            {
                var cluster = (FCluster)RuntimeHelpers.GetUninitializedObject(typeof(FCluster));
                cluster.Vertices = new FNaniteVertex[reader.ReadInt32()];
                for (var j = 0; j < cluster.Vertices.Length; j++)
                {
                    var vertex = new FNaniteVertex { RawPos = new FIntVector(reader.ReadInt32(), reader.ReadInt32(), reader.ReadInt32()) };
                    var attributes = new FNaniteVertexAttributes
                    {
                        Normal = new FVector(reader.ReadSingle(), reader.ReadSingle(), reader.ReadSingle()),
                        TangentXAndSign = new FVector4(reader.ReadSingle(), reader.ReadSingle(), reader.ReadSingle(), reader.ReadSingle()),
                        Color = new FColor(reader.ReadByte(), reader.ReadByte(), reader.ReadByte(), reader.ReadByte()),
                        UVs = new FVector2D[reader.ReadInt32()],
                    };
                    for (var uv = 0; uv < attributes.UVs.Length; uv++)
                        attributes.UVs[uv] = new FVector2D(reader.ReadSingle(), reader.ReadSingle());
                    vertex.Attributes = attributes;
                    cluster.Vertices[j] = vertex;
                }
                page.Clusters[i] = cluster;
            }
            SpillReads++;
            return page;
        }
        public void Dispose()
        {
            _reader?.Dispose(); _writer?.Dispose(); _spill?.Dispose();
            _reader = null; _writer = null; _spill = null;
            if (File.Exists(_spillPath)) File.Delete(_spillPath);
        }
    }
}

internal sealed class NaniteBudgetException(string message) : InvalidOperationException(message);
