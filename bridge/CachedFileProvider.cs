using CUE4Parse.FileProvider;
using CUE4Parse.FileProvider.Objects;
using CUE4Parse.UE4.Assets;
using CUE4Parse.UE4.Versions;
using CUE4Parse.UE4.Assets.Objects;
using CUE4Parse.UE4.IO.Objects;
using CUE4Parse.UE4.Readers;

/// <summary>Reuse package headers and lazy exports, including dependency loads.</summary>
internal sealed class CachedFileProvider : DefaultFileProvider
{
    private const int MaxEntries = 32;
    // A serialized-byte budget, not a process/decoded-object memory ceiling.
    private const long MaxSourceBytes = 256L * 1024 * 1024;
    private readonly object _gate = new();
    private readonly Dictionary<GameFile, LinkedListNode<Entry>> _packages = new();
    private readonly LinkedList<Entry> _lru = new();
    private long _sourceBytes, _hits, _misses, _evictions;
    private readonly Dictionary<GameFile, byte[]> _sources = new();
    private long _retainedSourceBytes, _sourceReads, _sourceHits;
    private const long MaxRawBytes = 64L * 1024 * 1024;
    private readonly bool _reusePackageSources;
    private sealed record Entry(GameFile File, IPackage Package, long Bytes);

    public CachedFileProvider(string directory, SearchOption searchOption,
        VersionContainer versions, StringComparer comparer, bool reusePackageSources = false)
        : base(directory, searchOption, versions, comparer) { _reusePackageSources = reusePackageSources; }

    public override IPackage LoadPackage(GameFile file)
        => GetOrLoad(file, () => LoadFromSource(file));

    private IPackage LoadFromSource(GameFile file)
    {
        // Only Rebirth's raw-export path needs shared primary byte buffers.
        // Other profiles keep CUE4Parse's native archive/partial-read behavior.
        if (!_reusePackageSources || file is not FIoStoreEntry io || !file.IsUePackage) return base.LoadPackage(file);
        Files.FindPayloads(file, out _, out var bulks, out var optional, false);
        var source = new FByteArchive(file.Path, ReadSource(file), Versions);
        Func<FByteBulkDataHeader?, FArchive?>? bulkReader = bulks.Count > 0 ? header => bulks[0].SafeCreateReader(header) : null;
        Func<FByteBulkDataHeader?, FArchive?>? optionalReader = optional.Count > 0 ? header => optional[0].SafeCreateReader(header) : null;
        return new IoPackage(source, io.IoStoreReader.ContainerHeader, bulkReader, optionalReader, this);
    }

    public byte[] ReadSource(GameFile file)
    {
        lock (_gate)
            if (_sources.TryGetValue(file, out var existing)) { _sourceHits++; return existing; }
        var bytes = file.Read(null);
        // Raw bytes are immutable and may already be owned by a lazy package.
        // Keep only a small recent working set; oversize bulk files bypass it.
        lock (_gate)
        {
            _sourceReads++;
            if (_sources.TryGetValue(file, out var existing)) return existing;
            if (bytes.LongLength <= MaxRawBytes)
            {
                while (_sources.Count >= 8 || _retainedSourceBytes + bytes.LongLength > MaxRawBytes)
                {
                    var oldest = _sources.First();
                    _retainedSourceBytes -= oldest.Value.LongLength;
                    _sources.Remove(oldest.Key);
                }
                _sources.Add(file, bytes);
                _retainedSourceBytes += bytes.LongLength;
            }
        }
        return bytes;
    }

    internal IPackage GetOrLoad(GameFile file, Func<IPackage> load)
    {
        lock (_gate)
        {
            if (_packages.TryGetValue(file, out var cached))
            {
                _lru.Remove(cached);
                _lru.AddFirst(cached);
                _hits++;
                return cached.Value.Package;
            }
            _misses++;
        }
        // Do not hold a cache lock while CUE4Parse resolves package dependencies.
        // Failed loads never enter the cache.
        var package = load();
        var bytes = Math.Max(0, file.Size);
        if (Files.TryGetValue(file.PathWithoutExtension + ".uexp", out var exports))
            bytes += Math.Max(0, exports.Size);
        if (bytes > MaxSourceBytes) return package;
        lock (_gate)
        {
            if (_packages.TryGetValue(file, out var existing)) return existing.Value.Package;
            var node = _lru.AddFirst(new Entry(file, package, bytes));
            _packages.Add(file, node);
            _sourceBytes += bytes;
            while (_packages.Count > MaxEntries || _sourceBytes > MaxSourceBytes)
            {
                var last = _lru.Last!;
                _packages.Remove(last.Value.File);
                _sourceBytes -= last.Value.Bytes;
                _lru.RemoveLast();
                _evictions++;
            }
        }
        return package;
    }

    public void ClearPackageCache()
    {
        lock (_gate)
        {
            // Live UObject references may still own these packages. Eviction
            // releases cache ownership; it must not dispose their archives.
            _packages.Clear();
            _lru.Clear();
            _sourceBytes = 0;
            _sources.Clear();
            _retainedSourceBytes = 0;
        }
    }

    public object PackageCacheStats()
    {
        lock (_gate) return new { entries = _packages.Count, sourceBytes = _sourceBytes,
            hits = _hits, misses = _misses, evictions = _evictions, maxEntries = MaxEntries,
            maxSourceBytes = MaxSourceBytes, rawEntries = _sources.Count, rawBytes = _retainedSourceBytes,
            sourceReads = _sourceReads, sourceHits = _sourceHits };
    }
}
