using CUE4Parse;
using CUE4Parse.Compression;
using CUE4Parse.Encryption.Aes;
using CUE4Parse.FileProvider;
using CUE4Parse.MappingsProvider.Usmap;
using CUE4Parse.UE4.Assets;
using CUE4Parse.UE4.Assets.Exports.SkeletalMesh;
using CUE4Parse.UE4.Objects.Core.Misc;
using CUE4Parse.UE4.Objects.UObject;
using CUE4Parse.UE4.Versions;

/// <summary>A read-only probe, isolated from import sessions and their caches.</summary>
internal static class GenericProfileTest
{
    public static object Run(string[] args)
    {
        var messages = new List<object>();
        var suppliedKey = args.Length > 11 ? args[11].Trim() : "";
        void Message(string level, string text) => messages.Add(new { level, text });
        // Parser exceptions can include key bytes. Never put them in diagnostics.
        string Detail(Exception error)
        {
            var text = error.GetBaseException().Message;
            if (suppliedKey.Length >= 16)
            {
                text = text.Replace(suppliedKey, "[AES key]", StringComparison.OrdinalIgnoreCase);
                var hex = suppliedKey.StartsWith("0x", StringComparison.OrdinalIgnoreCase) ? suppliedKey[2..] : suppliedKey;
                if (hex.Length > 0) text = text.Replace(hex, "[AES key]", StringComparison.OrdinalIgnoreCase);
            }
            return text;
        }
        var aesStatus = "not_needed";
        var mappingsStatus = "not_supplied";
        var testedPackages = 0;
        var failedPackages = 0;
        string? sample = null;
        object? mount = null;
        object Result() => new { success = sample != null, aesStatus, mappingsStatus, sample,
            testedPackages, failedPackages, mount, messages };

        FAesKey? key = null;
        if (suppliedKey.Length > 0)
        {
            try
            {
                key = new FAesKey(suppliedKey.StartsWith("0X") ? "0x" + suppliedKey[2..] : suppliedKey);
                aesStatus = "unverified";
            }
            catch
            {
                aesStatus = "invalid_format";
                Message("ERROR", "AES key is invalid: use 64 hexadecimal digits, optionally prefixed with 0x.");
            }
        }
        // Usmap files may themselves be Oodle-compressed.
        if (args.Length > 2 && !string.IsNullOrWhiteSpace(args[2]))
        {
            try
            {
                if (!File.Exists(args[2])) throw new FileNotFoundException("Configured Oodle library does not exist.");
                OodleHelper.Initialize(args[2]);
            }
            catch (Exception error) { Message("ERROR", "Compression library could not be loaded: " + Detail(error)); }
        }
        FileUsmapTypeMappingsProvider? mappings = null;
        if (args.Length > 5 && !string.IsNullOrWhiteSpace(args[5]))
        {
            try
            {
                mappings = new FileUsmapTypeMappingsProvider(args[5]);
                if (mappings.MappingsForGame?.Types.Count is not > 0)
                    throw new InvalidDataException("The file contains no property mappings.");
                mappingsStatus = "loaded";
                Message("INFO", "Mappings (.usmap) file parsed. Compatibility will be checked while reading a mesh.");
            }
            catch (Exception error)
            {
                mappings = null;
                mappingsStatus = "invalid";
                Message("ERROR", "Mappings (.usmap) file could not be read or seems invalid: " + Detail(error));
            }
        }

        try
        {
            var directory = GenericUnreal.PackageDirectory(args[0]);
            using var provider = new DefaultFileProvider(directory, SearchOption.AllDirectories,
                new VersionContainer(GenericUnreal.ParseVersion(args[10])), StringComparer.OrdinalIgnoreCase);
            provider.MappingsContainer = mappings;
            provider.Initialize();
            // Unencrypted indexes can still contain encrypted assets.
            if (key != null)
                foreach (var reader in provider.UnloadedVfs.Where(reader => !reader.IsEncrypted)) reader.AesKey = key;
            provider.Mount();
            if (key != null)
                provider.SubmitKeys(provider.RequiredKeys.Select(guid => new KeyValuePair<FGuid, FAesKey>(guid, key)).ToArray());
            provider.PostMount();
            var locked = provider.UnloadedVfs.Count(reader => reader.IsEncrypted || reader.EncryptedFileCount > 0);
            var encryptedFiles = provider.MountedVfs.Any(reader => reader.IsEncrypted || reader.EncryptedFileCount > 0);
            if (locked > 0 || (encryptedFiles && key == null))
            {
                if (aesStatus != "invalid_format") aesStatus = key == null ? "required" : "rejected";
                Message("ERROR", key == null
                    ? "An AES key is needed: encrypted packages or files are locked."
                    : "Encrypted packages remain locked. The AES key may be invalid or additional package keys may be needed.");
            }
            else if (provider.MountedVfs.Any(reader => reader.IsEncrypted) && key != null) aesStatus = "accepted";
            mount = GenericUnreal.MountInfo(provider);
            if (provider.Files.Count == 0 || provider.MountedVfs.Count == 0)
            {
                Message("ERROR", "No package containers could be read. Check the folder, game version, AES key and compression library.");
                return Result();
            }
            provider.LoadVirtualPaths();

            // Prefer registry candidates, but inspect package headers too: a registry
            // may be missing, outdated, or cover only part of the selected directory.
            var registry = GenericUnreal.RegistryMeshIndex(provider, null);
            var candidates = registry?["skeletalMeshes"] as IEnumerable<string> ?? [];
            var paths = candidates.Concat(provider.Files.Keys.Where(path => path.EndsWith(".uasset", StringComparison.OrdinalIgnoreCase)))
                .Distinct(StringComparer.OrdinalIgnoreCase);
            var mappingFailure = false;
            var cryptoFailure = false;
            string? firstFailure = null;
            var oldFatal = Globals.FatalObjectSerializationErrors;
            Globals.FatalObjectSerializationErrors = true;
            try
            {
                foreach (var path in paths)
                {
                    testedPackages++;
                    try
                    {
                        var package = provider.LoadPackage(path);
                        for (var index = 0; index < package.ExportMapLength; index++)
                        {
                            var type = package switch
                            {
                                Package legacy => legacy.ExportMap[index].ClassName,
                                IoPackage io => io.ResolveObjectIndex(io.ExportMap[index].ClassIndex)?.Name.ToString(),
                                _ => null,
                            };
                            if (!string.Equals(type, "SkeletalMesh", StringComparison.OrdinalIgnoreCase)) continue;
                            var unversioned = package.HasFlags(EPackageFlags.PKG_UnversionedProperties);
                            if (unversioned && mappings == null)
                            {
                                mappingFailure = true;
                                continue;
                            }
                            try
                            {
                                if (package.GetExport(index) is not USkeletalMesh mesh ||
                                    !(mesh.LODModels ?? []).Any(lod => !lod.SkipLod &&
                                        (lod.VertexBufferGPUSkin.VertsFloat.Length > 0 || lod.VertexBufferGPUSkin.VertsHalf.Length > 0) &&
                                        lod.Indices?.Buffer is { Length: > 0 }))
                                    throw new InvalidDataException("SkeletalMesh has no readable conventional geometry LOD.");
                                sample = path;
                                if (unversioned) mappingsStatus = "verified";
                                break;
                            }
                            catch (Exception error)
                            {
                                if (unversioned) mappingFailure = true;
                                RecordFailure(error);
                            }
                        }
                        if (sample != null) break;
                    }
                    catch (Exception error) { RecordFailure(error); }
                }
            }
            finally { Globals.FatalObjectSerializationErrors = oldFatal; }

            void RecordFailure(Exception error)
            {
                failedPackages++;
                firstFailure ??= Detail(error);
                for (Exception? current = error; current != null; current = current.InnerException)
                {
                    if (current.GetType().Name.Contains("Mapping", StringComparison.OrdinalIgnoreCase)) mappingFailure = true;
                    if (current.GetType().Name.Contains("Aes", StringComparison.OrdinalIgnoreCase)) cryptoFailure = true;
                }
            }
            if (cryptoFailure)
            {
                if (aesStatus != "invalid_format") aesStatus = key == null ? "required" : "rejected";
                Message("ERROR", key == null ? "Encrypted asset data needs an AES key."
                    : "The AES key could not decrypt asset data; check the key for this game's packages.");
            }
            if (aesStatus == "unverified" && sample == null && encryptedFiles && failedPackages > 0)
                Message("WARNING", "Encrypted asset data could not be verified. The AES key may be invalid; also check the compression library and game version.");
            if (mappingFailure && mappingsStatus != "verified" && mappingsStatus != "invalid")
            {
                mappingsStatus = mappings == null ? "required" : "suspect";
                Message("WARNING", mappings == null
                    ? "Unversioned skeletal mesh properties need a valid .usmap file."
                    : "The .usmap file parses, but skeletal mesh properties could not be read. It may belong to another game/build; also check the selected game version.");
            }
            if (sample != null)
            {
                Message("INFO", "Readable skeletal mesh found: " + sample);
                if (mappingsStatus == "verified") Message("INFO", "Mappings (.usmap) worked for this unversioned skeletal mesh.");
                else if (mappingsStatus == "loaded") Message("INFO", "This mesh did not require mappings; .usmap compatibility is still unverified.");
            }
            else
            {
                Message("WARNING", $"No readable skeletal mesh found after checking {testedPackages} packages ({failedPackages} read failures).");
                if (firstFailure != null) Message("INFO", "First read failure: " + firstFailure);
                Message("INFO", "This can also mean the folder has no skeletal meshes, the game version is wrong, or the game's mesh format is unsupported.");
            }
            if (aesStatus == "unverified") Message("INFO", "No encrypted data was verified; the supplied AES key remains untested.");
        }
        catch (Exception error) { Message("ERROR", "Profile test could not finish: " + Detail(error)); }
        return Result();
    }
}
