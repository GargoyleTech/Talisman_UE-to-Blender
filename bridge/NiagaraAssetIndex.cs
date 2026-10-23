using CUE4Parse.FileProvider;
using CUE4Parse.UE4.Assets;

/// <summary>Discover systems through IoStore class tables, without decoding scripts.</summary>
internal static class NiagaraAssetIndex
{
    public static object Read(DefaultFileProvider provider, string pathFilter)
    {
        var paths = new List<string>();
        var failures = 0;
        var readablePackages = 0;
        foreach (var path in provider.Files.Keys
                     .Where(path => path.EndsWith(".uasset", StringComparison.OrdinalIgnoreCase) &&
                         path.Contains(pathFilter, StringComparison.OrdinalIgnoreCase))
                     .OrderBy(path => path, StringComparer.OrdinalIgnoreCase))
        {
            try
            {
                // Do not enumerate GetExports(): the cooked system schema may
                // be opaque even though its class and mesh subexports survive.
                if (provider.LoadPackage(path) is not IoPackage package)
                    continue;
                if (package.ExportMap.Any(export => string.Equals(
                        package.ResolveObjectIndex(export.ClassIndex)?.Name.ToString(),
                        "NiagaraSystem", StringComparison.OrdinalIgnoreCase)))
                    paths.Add(path);
                readablePackages++;
            }
            catch { failures++; }
        }
        return new { paths, failures, readablePackages, source = "IoStore export class tables" };
    }
}
