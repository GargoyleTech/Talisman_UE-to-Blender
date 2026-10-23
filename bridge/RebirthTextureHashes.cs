using System.Buffers.Binary;
using System.Text;
using System.Text.Json;
using CUE4Parse.UE4.Assets;

/// <summary>Build the loose-MEC lookup from cooked export headers, without decoding textures.</summary>
internal static class RebirthTextureHashes
{
    public static void Generate(CachedFileProvider provider, string output)
    {
        const string contentRoot = "End/Content/";
        var files = provider.Files.Values.Where(file =>
            file.Path.StartsWith(contentRoot, StringComparison.OrdinalIgnoreCase) &&
            file.Path.EndsWith(".uasset", StringComparison.OrdinalIgnoreCase)).ToArray();
        if (files.Length == 0)
            throw new InvalidOperationException("No Rebirth asset packages were mounted.");

        var hashes = new SortedDictionary<ulong, string>();
        int scanned = 0, failures = 0;
        foreach (var file in files)
        {
            try
            {
                if (provider.LoadPackage(file) is not IoPackage package)
                    throw new InvalidDataException("Expected a Rebirth IoStore package.");
                var packagePath = "/Game/" + file.Path[contentRoot.Length..^7];
                foreach (var export in package.ExportMap)
                {
                    // Export metadata includes the real import ID, including textures
                    // whose object name differs from the containing package's name.
                    var type = package.ResolveObjectIndex(export.ClassIndex)?.Name.Text;
                    if (type?.StartsWith("Texture", StringComparison.Ordinal) != true ||
                        !export.GlobalImportIndex.IsPackageImport)
                        continue;
                    var name = package.CreateFNameFromMappedName(export.ObjectName).Text;
                    var path = name == Path.GetFileName(packagePath) ? packagePath : $"{packagePath}.{name}";
                    hashes[export.GlobalImportIndex.TypeAndId] = path;
                }
            }
            catch
            {
                failures++;
            }
            scanned++;
            if (scanned % 256 == 0 || scanned == files.Length)
            {
                Console.WriteLine(JsonSerializer.Serialize(new { textureHashes = true,
                    scanned, total = files.Length, count = hashes.Count, failures }));
                Console.Out.Flush();
                provider.ClearPackageCache();
            }
        }
        if (hashes.Count == 0)
            throw new InvalidOperationException("No texture hashes could be read. Check the Rebirth mappings and Oodle library.");

        using (var writer = new StreamWriter(output, false, new UTF8Encoding(false)))
        {
            foreach (var (hash, path) in hashes)
            {
                byte[] bytes = new byte[8];
                BinaryPrimitives.WriteUInt64LittleEndian(bytes, hash);
                writer.WriteLine($"\"{path.Replace("\"", "\"\"")}\",{Convert.ToHexString(bytes)}");
            }
        }
        Console.WriteLine(JsonSerializer.Serialize(new { textureHashes = true, complete = true,
            scanned, total = files.Length, count = hashes.Count, failures }));
        Console.Out.Flush();
    }
}
