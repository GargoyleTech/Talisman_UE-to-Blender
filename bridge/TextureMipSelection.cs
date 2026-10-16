// Selection is based on dimensions, so missing/cooked-out mip levels do not
// count as full steps. Payloads are probed only as needed.
internal static class TextureMipSelection
{
    public static int Select((int Width, int Height)[] sizes, Func<int, bool> readable,
        int maxResolution = 0, int mipOffset = 0)
    {
        if (maxResolution < 0 || mipOffset > 0 || mipOffset < -16)
            throw new ArgumentOutOfRangeException(nameof(mipOffset), "Invalid texture resolution or mip offset.");
        var ordered = Enumerable.Range(0, sizes.Length)
            .Where(i => sizes[i].Width > 0 && sizes[i].Height > 0)
            .OrderByDescending(i => Math.Max(sizes[i].Width, sizes[i].Height)).ToArray();
        var baseline = Array.FindIndex(ordered, i => readable(i));
        if (baseline < 0) return -1;
        var first = ordered[baseline];
        if (maxResolution == 0 && mipOffset == 0) return first;
        var targetWidth = Math.Max(1, sizes[first].Width >> -mipOffset);
        var targetHeight = Math.Max(1, sizes[first].Height >> -mipOffset);
        for (var position = baseline; position < ordered.Length; position++)
        {
            var i = ordered[position];
            if (sizes[i].Width <= targetWidth && sizes[i].Height <= targetHeight &&
                (maxResolution == 0 || Math.Max(sizes[i].Width, sizes[i].Height) <= maxResolution) &&
                (i == first || readable(i))) return i;
        }
        // No readable level meets the request: keep the smallest available one.
        // Blender enforces a hard resolution cap for single-mip/truncated assets.
        for (var position = ordered.Length - 1; position > baseline; position--)
            if (readable(ordered[position])) return ordered[position];
        return first;
    }
}
