// Selection is based on dimensions, so missing/cooked-out mip levels do not
// count as full steps. Payloads are probed only as needed.
internal static class TextureMipSelection
{
    public static int Select((int Width, int Height)[] sizes, Func<int, bool> readable,
        int maxResolution = 0, int mipOffset = 0, Func<int, bool?>? available = null,
        Action<int>? baselineSelected = null)
    {
        if (maxResolution < 0 || mipOffset > 0 || mipOffset < -16)
            throw new ArgumentOutOfRangeException(nameof(mipOffset), "Invalid texture resolution or mip offset.");
        var ordered = Enumerable.Range(0, sizes.Length)
            .Where(i => sizes[i].Width > 0 && sizes[i].Height > 0)
            .OrderByDescending(i => Math.Max(sizes[i].Width, sizes[i].Height)).ToArray();
        var results = new Dictionary<int, bool>();
        bool Read(int i)
        {
            if (!results.TryGetValue(i, out var result)) results[i] = result = readable(i);
            return result;
        }
        var baseline = Array.FindIndex(ordered, i => available?.Invoke(i) ?? Read(i));
        if (baseline < 0) return -1;
        var first = ordered[baseline];
        baselineSelected?.Invoke(first);
        if (maxResolution == 0 && mipOffset == 0)
            return Read(first) ? first : Select(sizes, Read, maxResolution, mipOffset, baselineSelected: baselineSelected);
        var targetWidth = Math.Max(1, sizes[first].Width >> -mipOffset);
        var targetHeight = Math.Max(1, sizes[first].Height >> -mipOffset);
        for (var position = baseline; position < ordered.Length; position++)
        {
            var i = ordered[position];
            if (sizes[i].Width <= targetWidth && sizes[i].Height <= targetHeight &&
                (maxResolution == 0 || Math.Max(sizes[i].Width, sizes[i].Height) <= maxResolution) &&
                Read(i)) return i;
        }
        // No readable level meets the request: keep the smallest available one.
        // Blender enforces a hard resolution cap for single-mip/truncated assets.
        for (var position = ordered.Length - 1; position > baseline; position--)
            if (Read(ordered[position])) return ordered[position];
        // A metadata availability hint can be invalidated by a failed payload
        // read. Reestablish the original highest-readable baseline in that case.
        return Read(first) ? first : Select(sizes, Read, maxResolution, mipOffset, baselineSelected: baselineSelected);
    }
}
