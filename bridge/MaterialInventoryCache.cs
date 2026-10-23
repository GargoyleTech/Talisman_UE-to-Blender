/// <summary>Bounded, provider-local inventories; never retain packages or UObjects.</summary>
internal sealed class MaterialInventoryCache
{
    internal sealed record Texture(string Path, string? Label = null);
    internal sealed record Inventory(string Name, string Type, Texture[] Textures,
        string[] Dependencies, string[] Warnings)
    {
        public long Characters => Name.Length + Type.Length +
            Textures.Sum(t => (long)t.Path.Length + (t.Label?.Length ?? 0)) +
            Dependencies.Sum(s => (long)s.Length) + Warnings.Sum(s => (long)s.Length);
    }

    private readonly Dictionary<string, LinkedListNode<(string Key, Inventory Value)>> _items = new(StringComparer.OrdinalIgnoreCase);
    private readonly LinkedList<(string Key, Inventory Value)> _lru = new();
    private const int MaxEntries = 4096;
    private const long MaxCharacters = 8 * 1024 * 1024;
    private long _characters, _hits, _misses;

    public bool TryGet(string key, out Inventory value)
    {
        if (_items.TryGetValue(key, out var entry))
        {
            _lru.Remove(entry);
            _lru.AddFirst(entry);
            value = entry.Value.Value;
            _hits++;
            return true;
        }
        _misses++;
        value = null!;
        return false;
    }

    public Inventory GetOrAdd(string key, Func<Inventory> create)
    {
        if (TryGet(key, out var value)) return value;
        value = create(); // Failed reads do not poison the cache.
        var characters = value.Characters;
        if (characters > MaxCharacters) return value;
        _items.Add(key, _lru.AddFirst((key, value)));
        _characters += characters;
        while (_items.Count > MaxEntries || _characters > MaxCharacters)
        {
            var last = _lru.Last!;
            _characters -= last.Value.Value.Characters;
            _items.Remove(last.Value.Key);
            _lru.RemoveLast();
        }
        return value;
    }

    public void CacheResolvedGraph(IReadOnlyDictionary<string, Inventory> graph)
    {
        // Memoize complete dependency unions as well as direct records. Shared
        // masters/functions then bypass their whole traversal on later assets.
        // Incomplete/failed/truncated graphs must never become complete hits.
        foreach (var (root, own) in graph)
        {
            var visited = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            var queue = new Queue<string>();
            var textures = new Dictionary<string, (string Path, HashSet<string> Labels)>(StringComparer.OrdinalIgnoreCase);
            var warnings = new List<string>();
            queue.Enqueue(root);
            var complete = true;
            while (queue.Count > 0)
            {
                var path = queue.Dequeue();
                if (!visited.Add(path)) continue;
                if (!TryGet("resolved:" + path, out var inventory) && !graph.TryGetValue(path, out inventory!))
                { complete = false; break; }
                foreach (var texture in inventory.Textures)
                {
                    if (!textures.TryGetValue(texture.Path, out var value))
                        value = (texture.Path, new HashSet<string>(StringComparer.Ordinal));
                    if (!string.IsNullOrEmpty(texture.Label)) value.Labels.Add(texture.Label);
                    textures[texture.Path] = value;
                }
                warnings.AddRange(inventory.Warnings);
                foreach (var dependency in inventory.Dependencies) queue.Enqueue(dependency);
            }
            if (!complete) continue;
            var records = textures.Values.SelectMany(value => value.Labels.Count == 0
                ? new[] { new Texture(value.Path) }
                : value.Labels.Select(label => new Texture(value.Path, label))).ToArray();
            GetOrAdd("resolved:" + root, () => new(own.Name, own.Type, records, [], warnings.ToArray()));
        }
    }

    public object Stats() => new { entries = _items.Count, characters = _characters, hits = _hits, misses = _misses };
}
