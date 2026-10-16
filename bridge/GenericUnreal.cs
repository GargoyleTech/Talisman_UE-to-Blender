using System.Text.Json;
using CUE4Parse.FileProvider;
using CUE4Parse.UE4.Assets;
using CUE4Parse.UE4.Assets.Exports;
using CUE4Parse.UE4.Assets.Exports.Component;
using CUE4Parse.UE4.Assets.Exports.Component.StaticMesh;
using CUE4Parse.UE4.Assets.Exports.Component.SkeletalMesh;
using CUE4Parse.UE4.Assets.Exports.Material;
using CUE4Parse.UE4.Assets.Exports.Texture;
using CUE4Parse.UE4.Assets.Exports.Animation;
using CUE4Parse.UE4.Assets.Objects;
using CUE4Parse.UE4.AssetRegistry;
using CUE4Parse.UE4.Objects.UObject;
using CUE4Parse.UE4.Readers;
using CUE4Parse.UE4.Versions;

/// <summary>Conventional Unreal package access without title adapters.</summary>
internal static class GenericUnreal
{
    public const string ProfilePrefix = "generic:";

    public static bool IsProfile(string? profile) =>
        profile?.StartsWith(ProfilePrefix, StringComparison.OrdinalIgnoreCase) == true;

    public static EGame ParseVersion(string profile)
    {
        var name = profile[ProfilePrefix.Length..];
        if (!Enum.TryParse<EGame>(name, true, out var version) ||
            !Enum.IsDefined(version) || version < EGame.GAME_UE4_0)
            throw new ArgumentException($"Unknown CUE4Parse UE4/UE5 profile '{name}'.");
        return version;
    }

    public static string PackageDirectory(string directory)
    {
        static bool HasContainers(string path) => Directory.Exists(path) &&
            Directory.EnumerateFiles(path).Any(file =>
                file.EndsWith(".pak", StringComparison.OrdinalIgnoreCase) ||
                file.EndsWith(".utoc", StringComparison.OrdinalIgnoreCase));
        if (HasContainers(directory)) return directory;
        var candidates = Directory.EnumerateDirectories(directory, "Paks", SearchOption.AllDirectories)
            .Where(path => !Path.GetRelativePath(directory, path).Split(Path.DirectorySeparatorChar)
                .Any(part => part.Equals("Engine", StringComparison.OrdinalIgnoreCase)))
            .Where(HasContainers).ToArray();
        return candidates.Length switch
        {
            1 => candidates[0],
            > 1 => throw new ArgumentException("Several game package folders were found. Choose the intended Content/Paks folder directly."),
            _ => throw new DirectoryNotFoundException("No pak or IoStore containers found. Choose the folder containing the game's .pak or .utoc files."),
        };
    }

    public static string Capabilities() => JsonSerializer.Serialize(new
    {
        protocolVersion = 1,
        gameVersions = Enum.GetNames<EGame>()
            .Where(name => !name.EndsWith("_LATEST", StringComparison.OrdinalIgnoreCase))
            .Select(name => new { id = name, version = Enum.Parse<EGame>(name) })
            .Where(item => item.version >= EGame.GAME_UE4_0)
            .Select(item => new { item.id, label = item.id[5..], value = (uint)item.version }),
    });

    public static string ResolveAsset(DefaultFileProvider provider, string objectPath)
    {
        var path = objectPath.Trim().Replace('\\', '/');
        if (path.Contains('\''))
            path = path[(path.IndexOf('\'') + 1)..].TrimEnd('\'');
        path = path.Split(':', 2)[0];
        var dot = path.LastIndexOf('.');
        if (dot > path.LastIndexOf('/') &&
            !path.EndsWith(".uasset", StringComparison.OrdinalIgnoreCase) &&
            !path.EndsWith(".umap", StringComparison.OrdinalIgnoreCase))
            path = path[..dot];
        var resolved = provider.FixPath(path);
        if (!provider.Files.ContainsKey(resolved) && resolved.EndsWith(".uasset", StringComparison.OrdinalIgnoreCase))
        {
            var map = Path.ChangeExtension(resolved, ".umap").Replace('\\', '/');
            if (provider.Files.ContainsKey(map)) return map;
        }
        return resolved;
    }

    public static string? ComponentType(UObject export)
    {
        // Spline meshes require vertex deformation, not a rigid placement.
        if (export.ExportType.Contains("SplineMeshComponent", StringComparison.Ordinal)) return null;
        if (export is UInstancedStaticMeshComponent) return "FoliageInstancedStaticMeshComponent";
        if (export is UStaticMeshComponent) return "StaticMeshComponent";
        if (export is USkinnedMeshComponent) return "SkeletalMeshComponent";
        return export.ExportType switch
        {
            "StaticMeshComponent" or "SkeletalMeshComponent" or "PointLightComponent" or
            "SpotLightComponent" or "BoxReflectionCaptureComponent" or "SphereReflectionCaptureComponent" or
            "LevelStreamingAlwaysLoaded" or "LevelStreamingDynamic" => export.ExportType,
            _ => null,
        };
    }

    public static object MountInfo(DefaultFileProvider provider) => new
    {
        mountedVfsCount = provider.MountedVfs.Count,
        unloadedVfsCount = provider.UnloadedVfs.Count,
        fileCount = provider.Files.Count,
        contentRoot = provider.FixPath("/Game/"),
        requiredKeyCount = provider.RequiredKeys.Count(),
        assetRegistryPaths = provider.Files.Keys.Where(path => path.EndsWith("AssetRegistry.bin", StringComparison.OrdinalIgnoreCase)).ToArray(),
    };

    public static Dictionary<string, object?>? RegistryMeshIndex(DefaultFileProvider provider, string? filter)
    {
        var registries = provider.Files.Where(entry =>
            entry.Key.EndsWith("AssetRegistry.bin", StringComparison.OrdinalIgnoreCase)).ToArray();
        if (registries.Length == 0) return null;
        var staticMeshes = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var skeletalMeshes = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var warnings = new List<string>();
        var parsedRegistries = 0;
        var assetCount = 0;
        foreach (var entry in registries)
        {
            try
            {
                using var archive = new FByteArchive(entry.Key, entry.Value.Read(null), provider.Versions);
                var registry = new FAssetRegistryState(archive);
                foreach (var asset in registry.PreallocatedAssetDataBuffers)
                {
                    var path = provider.FixPath(asset.PackageName.ToString());
                    if (!provider.Files.ContainsKey(path) ||
                        (!string.IsNullOrWhiteSpace(filter) && !path.Contains(filter, StringComparison.OrdinalIgnoreCase)))
                        continue;
                    var type = asset.AssetClass.ToString();
                    if (type.EndsWith("StaticMesh", StringComparison.OrdinalIgnoreCase)) staticMeshes.Add(path);
                    else if (type.EndsWith("SkeletalMesh", StringComparison.OrdinalIgnoreCase)) skeletalMeshes.Add(path);
                }
                parsedRegistries++;
                assetCount += registry.PreallocatedAssetDataBuffers.Length;
            }
            catch (Exception ex) { warnings.Add($"{entry.Key}: {ex.Message}"); }
        }
        if (parsedRegistries == 0) return null;
        return new Dictionary<string, object?>
        {
            ["source"] = "AssetRegistry.bin",
            ["registryCount"] = parsedRegistries,
            ["registryAssetCount"] = assetCount,
            ["staticMeshes"] = staticMeshes.OrderBy(path => path, StringComparer.OrdinalIgnoreCase).ToList(),
            ["skeletalMeshes"] = skeletalMeshes.OrderBy(path => path, StringComparer.OrdinalIgnoreCase).ToList(),
            ["failures"] = 0,
            ["warnings"] = warnings,
        };
    }

    public static Dictionary<string, object?> AssetIndex(DefaultFileProvider provider, string assetClass, string? filter)
    {
        var assets = new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase);
        var warnings = new List<string>();
        var registriesRead = 0;
        foreach (var entry in provider.Files.Where(entry => entry.Key.EndsWith("AssetRegistry.bin", StringComparison.OrdinalIgnoreCase)))
        {
            try
            {
                using var archive = new FByteArchive(entry.Key, entry.Value.Read(null), provider.Versions);
                var registry = new FAssetRegistryState(archive);
                foreach (var asset in registry.PreallocatedAssetDataBuffers)
                {
                    var path = ResolveAsset(provider, asset.PackageName.ToString());
                    if (!asset.AssetClass.Text.Equals(assetClass, StringComparison.OrdinalIgnoreCase) ||
                        !provider.Files.ContainsKey(path) ||
                        (!string.IsNullOrWhiteSpace(filter) && !path.Contains(filter, StringComparison.OrdinalIgnoreCase))) continue;
                    assets[path] = new Dictionary<string, object?>
                    {
                        ["path"] = path, ["class"] = asset.AssetClass.Text,
                        ["tags"] = asset.TagsAndValues.ToDictionary(tag => tag.Key.Text, tag => tag.Value),
                    };
                }
                registriesRead++;
            }
            catch (Exception ex) { warnings.Add($"{entry.Key}: {ex.Message}"); }
        }
        if (registriesRead == 0)
        {
            // Header-only fallback; do not guess an animation's class from its filename.
            warnings.Add("No readable asset registry; scanning package exports instead.");
            foreach (var path in provider.Files.Keys.Where(path => path.EndsWith(".uasset", StringComparison.OrdinalIgnoreCase) &&
                         (string.IsNullOrWhiteSpace(filter) || path.Contains(filter, StringComparison.OrdinalIgnoreCase))))
            {
                try
                {
                    if (provider.LoadPackage(path).GetExports().Any(export => export.ExportType.Equals(assetClass, StringComparison.OrdinalIgnoreCase)))
                        assets[path] = new Dictionary<string, object?> { ["path"] = path, ["class"] = assetClass, ["tags"] = new Dictionary<string, string>() };
                }
                catch (Exception ex) { warnings.Add($"{path}: {ex.Message}"); }
            }
        }
        return new Dictionary<string, object?>
        {
            ["assets"] = assets.OrderBy(entry => entry.Key, StringComparer.OrdinalIgnoreCase).Select(entry => entry.Value).ToArray(),
            ["registryCount"] = registriesRead, ["warnings"] = warnings,
        };
    }

    public static Dictionary<string, object?> AnimationIndex(DefaultFileProvider provider, string skeletonPath, string? filter)
    {
        var index = AssetIndex(provider, "AnimSequence", filter);
        var target = ResolveAsset(provider, skeletonPath);
        if (!provider.Files.ContainsKey(target)) throw new FileNotFoundException("The target Skeleton is not present in this game's mounted packages.", target);
        var paths = new List<string>();
        var warnings = (List<string>)index["warnings"]!;
        foreach (var item in (object[])index["assets"]!)
        {
            var asset = (Dictionary<string, object?>)item;
            var path = (string)asset["path"]!;
            var tags = (Dictionary<string, string>)asset["tags"]!;
            try
            {
                // Cooked registries usually retain the Skeleton tag. Missing tags
                // are checked against the actual animation, never a naming heuristic.
                var linked = tags.GetValueOrDefault("Skeleton");
                if (string.IsNullOrWhiteSpace(linked) || linked.Equals("None", StringComparison.OrdinalIgnoreCase))
                    linked = provider.LoadPackage(path).GetExports().OfType<UAnimSequence>().FirstOrDefault()?.Skeleton?.ResolvedObject?.GetPathName();
                if (!string.IsNullOrWhiteSpace(linked) && ResolveAsset(provider, linked).Equals(target, StringComparison.OrdinalIgnoreCase)) paths.Add(path);
            }
            catch (Exception ex) { warnings.Add($"{path}: {ex.Message}"); }
        }
        return new Dictionary<string, object?> { ["paths"] = paths, ["skeletonPath"] = target, ["warnings"] = warnings };
    }

    public static Dictionary<string, object?> MaterialTextures(
        DefaultFileProvider provider, string assetPath, string? objectPath)
    {
        var package = provider.LoadPackage(assetPath);
        var material = package.GetExports().FirstOrDefault(export =>
            (export is UMaterialInterface || export.ExportType.Contains("Material", StringComparison.OrdinalIgnoreCase)) &&
            (string.IsNullOrWhiteSpace(objectPath) ||
             string.Equals(export.GetPathName(), objectPath, StringComparison.OrdinalIgnoreCase)));
        if (material is null)
            throw new InvalidOperationException("Package contains no matching material export.");

        var references = new Dictionary<string, (string Path, HashSet<string> Labels)>(StringComparer.OrdinalIgnoreCase);
        var visited = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var warnings = new List<string>();
        var queue = new Queue<UObject>();
        queue.Enqueue(material);

        void Add(string? path, string? label = null)
        {
            if (string.IsNullOrWhiteSpace(path)) return;
            if (!references.TryGetValue(path, out var entry))
                entry = (path, new HashSet<string>(StringComparer.Ordinal));
            if (!string.IsNullOrWhiteSpace(label)) entry.Labels.Add(label);
            references[path] = entry;
        }

        void Inspect(ResolvedObject? resolved)
        {
            if (resolved is null) return;
            var type = resolved.Class?.Name.Text ?? "";
            if (type.StartsWith("Texture", StringComparison.OrdinalIgnoreCase))
                Add(resolved.GetPathName());
            else if (type.Contains("MaterialFunction", StringComparison.OrdinalIgnoreCase) &&
                     resolved.Load() is { } function)
                queue.Enqueue(function);
        }

        while (queue.Count > 0 && visited.Count < 256)
        {
            var current = queue.Dequeue();
            if (!visited.Add(current.GetPathName())) continue;
            try
            {
                foreach (var parameter in current.GetOrDefault<FTextureParameterValue[]>("TextureParameterValues", []))
                    Add(parameter.ParameterValue?.ResolvedObject?.GetPathName(), parameter.Name);
            }
            catch (Exception ex) { warnings.Add($"Texture parameters in {current.Name}: {ex.Message}"); }
            try
            {
                if (current.GetOrDefault<FPackageIndex>("Parent")?.Load() is { } parent)
                    queue.Enqueue(parent);
            }
            catch (Exception ex) { warnings.Add($"Parent of {current.Name}: {ex.Message}"); }
            if (current is UMaterial baseMaterial)
                foreach (var texture in baseMaterial.ReferencedTextures)
                    if (texture is not null) Add(texture.GetPathName());

            // Class metadata identifies textures without loading their bulk data.
            var owner = current.Owner;
            if (owner is null) continue;
            for (var index = 0; index < owner.ImportMapLength; index++)
            {
                try { Inspect(owner.ResolvePackageIndex(new FPackageIndex(owner, -index - 1))); }
                catch (Exception ex) { warnings.Add($"Import {index} in {owner.Name}: {ex.Message}"); }
            }
            try
            {
                foreach (var export in owner.GetExports())
                    if (export is UTexture texture) Add(texture.GetPathName());
            }
            catch (Exception ex) { warnings.Add($"Embedded textures in {owner.Name}: {ex.Message}"); }
        }
        if (queue.Count > 0) warnings.Add("Material dependency traversal stopped after 256 objects.");
        return new Dictionary<string, object?>
        {
            ["name"] = material.Name.ToString(),
            ["type"] = material.ExportType,
            ["textures"] = references.Values.OrderBy(entry => entry.Path, StringComparer.OrdinalIgnoreCase)
                .Select(entry => new { path = entry.Path, labels = entry.Labels.OrderBy(label => label).ToArray() }).ToArray(),
            ["warnings"] = warnings,
        };
    }
}
