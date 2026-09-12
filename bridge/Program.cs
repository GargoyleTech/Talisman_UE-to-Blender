using System.Text.Json;
using System.Text.RegularExpressions;
using System.Text;
using System.Collections;
using System.Reflection;
using System.Buffers.Binary;
using System.Runtime;
using CUE4Parse.FileProvider;
using CUE4Parse.Encryption.Aes;
using CUE4Parse.Compression;
using CUE4Parse.MappingsProvider;
using CUE4Parse.MappingsProvider.Usmap;
using CUE4Parse.UE4.Versions;
using CUE4Parse.UE4.Assets;
using CUE4Parse.UE4.Assets.Exports.Animation;
using CUE4Parse.UE4.Assets.Exports;
using CUE4Parse.UE4.Assets.Exports.Component.SkeletalMesh;
using CUE4Parse.UE4.Assets.Exports.Component;
using CUE4Parse.UE4.Assets.Exports.Component.StaticMesh;
using CUE4Parse.UE4.Assets.Exports.SkeletalMesh;
using CUE4Parse.UE4.Assets.Exports.StaticMesh;
using CUE4Parse.UE4.Assets.Exports.Texture;
using CUE4Parse.UE4.AssetRegistry;
using CUE4Parse.UE4.Assets.Objects;
using CUE4Parse.UE4.Assets.Readers;
using CUE4Parse.UE4.IO.Objects;
using CUE4Parse.UE4.Objects.Engine;
using CUE4Parse.UE4.Objects.Core.Math;
using CUE4Parse.UE4.Objects.Core.Misc;
using CUE4Parse.UE4.Objects.Meshes;
using CUE4Parse.UE4.Readers;
using CUE4Parse.UE4.Objects.UObject;
using CUE4Parse_Conversion.Textures;
using Ff7r.Acl;
using Ff7r.Rebirth;

if (args.Length < 1)
{
    Console.Error.WriteLine("Usage: FF7RGameAssetBridge <game-directory> [output-json|-] [oodle-dll] [path-filter] [asset-path] [usmap] [dds-output] [raw-output] [summary] [game-profile]");
    Console.Error.WriteLine("game-profile: auto (default), rebirth, remake, or crisis-core");
    return 2;
}

static string ResolvePackageDirectory(string gameDirectory)
{
    // Accept an install root, a game's Content folder, or the Paks directory
    // itself.  Rebirth and Remake share End/Content/Paks; Crisis Core uses
    // CCFF7R/Content/Paks.
    var candidates = new[]
    {
        gameDirectory,
        Path.Combine(gameDirectory, "End", "Content", "Paks"),
        Path.Combine(gameDirectory, "CCFF7R", "Content", "Paks"),
        Path.Combine(gameDirectory, "Content", "Paks"),
        Path.Combine(gameDirectory, "Paks"),
    };
    return candidates.FirstOrDefault(candidate =>
        Directory.Exists(candidate) &&
        Directory.EnumerateFiles(candidate, "*.pak", SearchOption.TopDirectoryOnly).Any())
        ?? throw new DirectoryNotFoundException(
            "Could not find a Paks directory beneath the supplied game directory.");
}

static (string Name, EGame Version, string? AesKey) ResolveGameProfile(
    string gameDirectory, string packageDirectory, string? requestedProfile)
{
    var requested = requestedProfile?.Trim().ToLowerInvariant();
    if (requested is not null and not "" and not "auto")
    {
        return requested switch
        {
            "rebirth" => ("Final Fantasy VII Rebirth", EGame.GAME_FinalFantasy7Rebirth, null),
            "remake" or "remake-intergrade" => (
                "Final Fantasy VII Remake Intergrade",
                EGame.GAME_FinalFantasy7Remake,
                "0x23989837645C9D28BA58072B2076E895B853A7C9E1C5591B814C4FD2A2D7B782"),
            "crisis-core" or "crisiscore" or "ccff7r" => (
                "Crisis Core -Final Fantasy VII- Reunion",
                EGame.GAME_UE4_27,
                "0x277041CBB2888087611DB5CBFEA119462920E1F67092C87E87825725E38B320F"),
            _ => throw new ArgumentException(
                $"Unknown game profile '{requestedProfile}'. Use auto, rebirth, remake, or crisis-core."),
        };
    }

    if (gameDirectory.EndsWith("CCFF7R", StringComparison.OrdinalIgnoreCase) ||
        packageDirectory.Contains("CCFF7R", StringComparison.OrdinalIgnoreCase) ||
        File.Exists(Path.Combine(gameDirectory, "CCFF7R.exe")))
    {
        return (
            "Crisis Core -Final Fantasy VII- Reunion",
            EGame.GAME_UE4_27,
            "0x277041CBB2888087611DB5CBFEA119462920E1F67092C87E87825725E38B320F");
    }

    if (File.Exists(Path.Combine(gameDirectory, "ff7remake.exe")) ||
        Directory.EnumerateFiles(packageDirectory, "pakchunk0_s*-WindowsNoEditor.pak").Any())
    {
        return (
            "Final Fantasy VII Remake Intergrade",
            EGame.GAME_FinalFantasy7Remake,
            "0x23989837645C9D28BA58072B2076E895B853A7C9E1C5591B814C4FD2A2D7B782");
    }

    return ("Final Fantasy VII Rebirth", EGame.GAME_FinalFantasy7Rebirth, null);
}

var gameDirectory = Path.GetFullPath(args[0]);
if (!Directory.Exists(gameDirectory))
{
    Console.Error.WriteLine($"Game directory does not exist: {gameDirectory}");
    return 2;
}

static object? ConvertValue(object? value, int depth = 0)
{
    if (value is null || depth > 32)
        return value?.ToString();
    if (value is string || value is bool || value is byte || value is sbyte ||
        value is short || value is ushort || value is int || value is uint ||
        value is long || value is ulong || value is float || value is double ||
        value is decimal)
        return value;
    if (value is Enum)
        return value.ToString();
    if (value.GetType().IsGenericType && value.GetType().GetGenericTypeDefinition() == typeof(Lazy<>))
        return ConvertValue(value.GetType().GetProperty("Value")?.GetValue(value), depth + 1);

    var type = value.GetType();
    if (type.Name == "FGuid")
        return value.ToString();
    if (value is FSoftObjectPath softObjectPath)
    {
        // Owner is a package back-reference. Reflecting it recursively expands
        // the package's entire import/export maps once per soft reference.
        return new Dictionary<string, object?>
        {
            ["AssetPathName"] = softObjectPath.AssetPathName.ToString(),
            ["SubPathString"] = softObjectPath.SubPathString,
        };
    }
    if (value is FPackageIndex packageIndex)
    {
        if (PropertyConversionContext.PackageIndexConverter is not null)
            return PropertyConversionContext.PackageIndexConverter(packageIndex);
        var resolved = packageIndex.ResolvedObject;
        var objectPath = resolved?.GetPathName() ?? packageIndex.Name.ToString();
        if (string.IsNullOrWhiteSpace(objectPath))
            return null;
        return new Dictionary<string, object?>
        {
            // The Blender asset linker keys by UE object/datablock name. Keep the
            // full path separately for diagnostics and future pak-mesh loading.
            ["ObjectName"] = $"Object'{packageIndex.Name}'",
            ["ObjectPath"] = objectPath,
        };
    }
    if (type.Name == "StructProperty")
    {
        var genericValue = type.GetProperty("GenericValue", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)?.GetValue(value)
            ?? type.GetProperty("Value", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)?.GetValue(value);
        if (genericValue is not null && !ReferenceEquals(genericValue, value))
            return ConvertValue(genericValue, depth + 1);
    }
    // FPropertyTag must be matched by exact type name before the FStructFallback
    // heuristic below: FPropertyTag.ToString() embeds its wrapped value's own
    // description, and for a struct-typed tag (e.g. InPortInfo/OutPortInfo) that
    // description contains the literal text "(FStructFallback, StructProperty)".
    // That previously fooled the ToString-based FStructFallback check into treating
    // the *tag itself* as the struct, silently dropping the tag's name/value.
    if (type.Name == "FPropertyTag")
        return ConvertFPropertyTag(value, type, depth);
    if (type.Name == "FStructFallback" || type.FullName?.Contains("FStructFallback", StringComparison.Ordinal) == true)
    {
        var propertiesMember = type.GetMember("Properties", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
            .FirstOrDefault() ?? type.GetMembers(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
            .FirstOrDefault(member => member switch
            {
                System.Reflection.PropertyInfo property => property.GetIndexParameters().Length == 0 && typeof(IEnumerable).IsAssignableFrom(property.PropertyType),
                FieldInfo field => typeof(IEnumerable).IsAssignableFrom(field.FieldType),
                _ => false
            });
        var tags = propertiesMember switch
        {
            System.Reflection.PropertyInfo property => property.GetValue(value) as IEnumerable,
            FieldInfo field => field.GetValue(value) as IEnumerable,
            _ => null
        };
        var structValues = new Dictionary<string, object?>();
        if (tags is not null)
        {
            foreach (var tag in tags)
            {
                var converted = ConvertValue(tag, depth + 1) as Dictionary<string, object?>;
                if (converted is not null && converted.TryGetValue("name", out var name) && name is not null)
                    structValues[name.ToString()!] = converted.TryGetValue("value", out var item) ? item : converted;
            }
        }
        // CUE4Parse represents an untagged struct-array element as a fallback
        // containing one synthetic StructType property.  The JSON exporter used
        // by the existing KDI importer writes that inner struct directly.
        if (structValues.Count == 1 && structValues.TryGetValue("StructType", out var innerStruct) &&
            innerStruct is Dictionary<string, object?> innerValues)
            return innerValues;
        return structValues;
    }
    if (type.Name is "ArrayProperty" or "FArrayProperty" or "UScriptArray")
    {
        var itemsMember = type.GetMember("Properties", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
            .FirstOrDefault();
        var items = itemsMember switch
        {
            System.Reflection.PropertyInfo property => property.GetValue(value) as IEnumerable,
            FieldInfo field => field.GetValue(value) as IEnumerable,
            _ => null
        };
        if (items is null)
            return new List<object?>();
        var convertedItems = new List<object?>();
        foreach (var item in items)
            convertedItems.Add(ConvertValue(item, depth + 1));
        return convertedItems;
    }
    if (type.Name is "MapProperty" or "FMapProperty")
    {
        var itemsMember = type.GetMember("Properties", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
            .FirstOrDefault();
        var items = itemsMember switch
        {
            System.Reflection.PropertyInfo property => property.GetValue(value),
            FieldInfo field => field.GetValue(value),
            _ => null,
        };
        return ConvertValue(items, depth + 1);
    }
    if (type.Name.EndsWith("Property", StringComparison.Ordinal) &&
        type.Name is not "FPropertyTag" and not "StructProperty")
    {
        var genericValue = type.GetProperty("GenericValue", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)?.GetValue(value)
            ?? type.GetProperty("Value", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)?.GetValue(value);
        if (genericValue is not null && !ReferenceEquals(genericValue, value))
            return ConvertValue(genericValue, depth + 1);
    }
    if (value is IDictionary dictionary)
    {
        var entries = new List<object?>();
        foreach (DictionaryEntry entry in dictionary)
        {
            entries.Add(new Dictionary<string, object?>
            {
                ["Key"] = ConvertValue(entry.Key, depth + 1),
                ["Value"] = ConvertValue(entry.Value, depth + 1),
            });
        }
        return entries;
    }
    if (value is IEnumerable sequence && value is not string &&
        !value.ToString()!.Contains("FStructFallback", StringComparison.Ordinal))
    {
        var items = new List<object?>();
        foreach (var item in sequence)
            items.Add(ConvertValue(item, depth + 1));
        return items;
    }

    if (type.Name == "FName")
        return value.ToString();

    // Unreal object references and unsupported reader types are still useful as text.
    var fields = type.GetFields(BindingFlags.Instance | BindingFlags.Public)
        .Where(field => !field.IsStatic)
        .ToArray();
    if (fields.Length == 0)
        return value.ToString();
    var result = new Dictionary<string, object?>();
    foreach (var field in fields)
        result[field.Name] = ConvertValue(field.GetValue(value), depth + 1);
    return result;
}

static object? ReadPublicMember(object? instance, string memberName)
{
    if (instance is null)
        return null;
    var type = instance.GetType();
    return type.GetProperty(memberName, BindingFlags.Instance | BindingFlags.Public)?.GetValue(instance)
        ?? type.GetField(memberName, BindingFlags.Instance | BindingFlags.Public)?.GetValue(instance);
}

static object CollectBatchMemory(long restartThresholdBytes)
{
    // UMAP deserialization produces many large temporary arrays. Compact the
    // large-object heap after a small batch has been handed to Blender. If
    // CUE4Parse still retains package/export state, the caller can recycle this
    // process while preserving everything already created in Blender.
    var workingSetBeforeBytes = Environment.WorkingSet;
    var managedBeforeBytes = GC.GetTotalMemory(forceFullCollection: false);
    GCSettings.LargeObjectHeapCompactionMode = GCLargeObjectHeapCompactionMode.CompactOnce;
    GC.Collect(GC.MaxGeneration, GCCollectionMode.Aggressive, blocking: true, compacting: true);
    GC.WaitForPendingFinalizers();
    GC.Collect(GC.MaxGeneration, GCCollectionMode.Aggressive, blocking: true, compacting: true);
    var workingSetBytes = Environment.WorkingSet;
    var managedBytes = GC.GetTotalMemory(forceFullCollection: false);
    return new
    {
        workingSetBeforeBytes,
        managedBeforeBytes,
        workingSetBytes,
        managedBytes,
        restartRecommended = restartThresholdBytes > 0 &&
            Math.Max(workingSetBytes, managedBytes) > restartThresholdBytes,
    };
}

static List<object?> DescribeMappingProperties(object mapping)
{
    if (ReadPublicMember(mapping, "Properties") is not IEnumerable properties)
        return [];
    var results = new List<object?>();
    foreach (var entry in properties)
    {
        var property = ReadPublicMember(entry, "Value") ?? entry;
        var mappingType = ReadPublicMember(property, "MappingType");
        results.Add(new Dictionary<string, object?>
        {
            ["entry"] = entry?.ToString(),
            ["name"] = ReadPublicMember(property, "Name")?.ToString(),
            ["type"] = mappingType?.ToString(),
            ["mappingType"] = mappingType is null ? null : ConvertValue(mappingType, 1)
        });
    }
    return results;
}

static Dictionary<string, object?> ConvertFPropertyTag(object value, Type type, int depth)
{
    var allInstanceFields = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
    var tag = type.GetField("Tag", allInstanceFields)?.GetValue(value)
        ?? type.GetField("TagData", allInstanceFields)?.GetValue(value);
    var generic = tag?.GetType().GetProperty("GenericValue", allInstanceFields)?.GetValue(tag)
        ?? tag?.GetType().GetField("GenericValue", allInstanceFields)?.GetValue(tag)
        ?? tag;
    // UE serializes a static-array UPROPERTY (e.g. MovieScene3DTransformSection's
    // "FMovieSceneDoubleChannel Translation[3]") as one tag per element, all
    // sharing the same FName and distinguished only by ArrayIndex.  Without the
    // suffix every element collapses onto a single dictionary key and only the
    // last one survives -- which silently zeroed cutscene light/camera Y and Z.
    // FModel's own JSON writer suffixes indices past the first, and the Blender
    // importers were written against that naming ("Translation", "Translation[1]",
    // "Translation[2]"), so match it exactly.
    var tagName = type.GetField("Name")?.GetValue(value)?.ToString();
    var arrayIndex = type.GetField("ArrayIndex", allInstanceFields)?.GetValue(value) as int?;
    if (tagName is not null && arrayIndex is > 0)
        tagName = $"{tagName}[{arrayIndex}]";
    return new Dictionary<string, object?>
    {
        ["name"] = tagName,
        ["propertyType"] = type.GetField("PropertyType")?.GetValue(value)?.ToString(),
        ["value"] = ConvertValue(generic, depth + 1)
    };
}

static object? NormalizeKdiValue(object? value)
{
    if (value is Dictionary<string, object?> dictionary)
    {
        var normalized = dictionary.ToDictionary(
            entry => entry.Key,
            entry => NormalizeKdiValue(entry.Value));
        if (normalized.Count == 1 && normalized.TryGetValue("StructType", out var inner))
            return inner;
        // CUE4Parse stores MapProperty entries beneath its own ``Properties``
        // member. FModel's JSON writes that member's entries directly, which is
        // what the existing cutscene importer expects for BindingReferences and
        // MovieScene ObjectBindings.
        if (normalized.Count == 1 && normalized.TryGetValue("Properties", out inner) &&
            inner is List<object?>)
            return inner;
        return normalized;
    }
    if (value is List<object?> list)
        return list.Select(NormalizeKdiValue).ToList();
    return value;
}

// Cooked MaterialInstanceConstant exports only serialize the parameters an
// instance itself overrides. A character-specific instance (e.g.
// PC0011_00_BodyB) commonly only overrides its unique diffuse/normal
// textures and inherits shared parameters -- like a "DetailCoverage" mask
// constant -- from a parent instance further up the chain. Without this,
// Blender never sees that parameter at all, so its Image Texture node is
// left with no image and no fallback constant.
//
// This walks Parent up to the root, collecting each ancestor's own
// TextureParameterValues/VectorParameterValues/ScalarParameterValues, and
// merges them into *properties* with the root-most ancestor's entries first
// and the material's own entries last. Python's role lookup keeps the
// *last* entry for a given parameter name when it builds its name->value
// map, so this ordering makes a more-derived instance's own override win
// over an inherited default -- matching Unreal's own resolution order --
// while still filling in anything the instance never overrode.
static void MergeInheritedMaterialParameters(
    CUE4Parse.UE4.Assets.Exports.UObject material,
    List<object?> properties)
{
    string[] MaterialParameterArrayPropertyNames =
    [
        "TextureParameterValues",
        "VectorParameterValues",
        "ScalarParameterValues",
    ];

    var ancestorArrays = new List<Dictionary<string, List<object?>>>();
    var visited = new HashSet<CUE4Parse.UE4.Assets.Exports.UObject> { material };
    var parent = material.GetOrDefault<FPackageIndex>("Parent", new FPackageIndex()).Load();
    while (parent != null && visited.Add(parent))
    {
        var arrays = new Dictionary<string, List<object?>>();
        foreach (var property in parent.Properties)
        {
            if (Array.IndexOf(MaterialParameterArrayPropertyNames, property.Name.Text) < 0)
                continue;
            if (ConvertValue(property) is Dictionary<string, object?> converted &&
                converted.GetValueOrDefault("value") is List<object?> entries)
            {
                arrays[property.Name.Text] = entries;
            }
        }
        ancestorArrays.Add(arrays);
        parent = parent.GetOrDefault<FPackageIndex>("Parent", new FPackageIndex()).Load();
    }
    ancestorArrays.Reverse();

    foreach (var parameterArrayName in MaterialParameterArrayPropertyNames)
    {
        var mergedValues = new List<object?>();
        foreach (var arrays in ancestorArrays)
        {
            if (arrays.TryGetValue(parameterArrayName, out var entries))
                mergedValues.AddRange(entries);
        }

        var ownEntry = properties
            .OfType<Dictionary<string, object?>>()
            .FirstOrDefault(entry => entry.GetValueOrDefault("name") as string == parameterArrayName);
        if (ownEntry?.GetValueOrDefault("value") is List<object?> ownValues)
            mergedValues.AddRange(ownValues);

        if (mergedValues.Count == 0)
            continue;

        if (ownEntry != null)
            ownEntry["value"] = mergedValues;
        else
            properties.Add(new Dictionary<string, object?> { ["name"] = parameterArrayName, ["value"] = mergedValues });
    }
}

static Dictionary<string, object?> ExportMaterialInstancePackage(CUE4Parse.UE4.Assets.IPackage package)
{
    // Keep this intentionally mapping-agnostic. Rebirth's MaterialInstance
    // parameter structs are available through the active usmap, while their
    // C# export classes have varied across CUE4Parse releases. The existing
    // generic FPropertyTag converter gives Blender the cooked Parent,
    // TextureParameterValues, VectorParameterValues, and scalar values.
    var material = package.GetExports().FirstOrDefault(export =>
        export.ExportType.ToString().Contains("MaterialInstance", StringComparison.OrdinalIgnoreCase));
    if (material is null)
        throw new InvalidOperationException("Package does not contain a MaterialInstance export.");
    var properties = material.Properties.Select(property => ConvertValue(property)).ToList();
    MergeInheritedMaterialParameters(material, properties);
    return new Dictionary<string, object?>
    {
        ["name"] = material.Name.ToString(),
        ["type"] = material.ExportType,
        ["properties"] = properties,
    };
}

static bool IsNiagaraExport(CUE4Parse.UE4.Assets.Exports.UObject export)
    => export.ExportType.ToString().Contains("Niagara", StringComparison.OrdinalIgnoreCase);

static Dictionary<string, object?> ExportNiagaraPackage(CUE4Parse.UE4.Assets.IPackage package)
{
    // Rebirth's supplied usmap has no entries for the first active fields in
    // UNiagaraSystem (the first one requested by the cooked header is field 75,
    // while the map only describes fields through 47). CUE4Parse therefore
    // cannot advance through the owning system object. Its emitter, renderer,
    // and script subexports still deserialize independently, frequently with
    // useful authored settings before any unsupported nested Niagara type.
    // Keep those properties available, but represent every result as partial so
    // callers do not mistake this for a complete Niagara graph decoder.
    var allExports = package.GetExports().ToArray();
    var exports = new List<object?>();
    var systems = new List<object?>();

    for (var exportIndex = 0; exportIndex < allExports.Length; exportIndex++)
    {
        var export = allExports[exportIndex];
        if (!IsNiagaraExport(export))
            continue;

        var type = export.ExportType.ToString();
        var properties = new List<object?>();
        foreach (var property in export.Properties)
        {
            try
            {
                properties.Add(ConvertValue(property));
            }
            catch (Exception exception)
            {
                // One bad nested value must not hide the rest of this exported
                // object. The failure is included in the report rather than
                // treated as a fabricated default property.
                properties.Add(new Dictionary<string, object?>
                {
                    ["status"] = "unreadable",
                    ["property"] = property.Name.Text,
                    ["error"] = exception.Message,
                });
            }
        }

        var isSystem = string.Equals(type, "NiagaraSystem", StringComparison.OrdinalIgnoreCase);
        var status = isSystem && properties.Count == 0
            ? "opaque_missing_schema"
            : "partial";
        var item = new Dictionary<string, object?>
        {
            ["exportIndex"] = exportIndex,
            ["name"] = export.Name.ToString(),
            ["type"] = type,
            ["fullName"] = export.GetFullName(),
            ["propertyStatus"] = status,
            ["properties"] = properties,
        };
        exports.Add(item);
        if (isSystem)
            systems.Add(item);
    }

    return new Dictionary<string, object?>
    {
        ["sourceType"] = "partial CUE4Parse Niagara package export",
        ["exportCount"] = exports.Count,
        ["systemStatus"] = systems.Count == 0
            ? "no NiagaraSystem export"
            : "opaque system fields due to incomplete Rebirth NiagaraSystem schema",
        ["limitations"] = new[]
        {
            "The Rebirth usmap does not describe the first active cooked NiagaraSystem field, so system-level emitter handles, parameter overrides, compiled data, and exposed parameters cannot be decoded safely.",
            "Emitter, renderer, script, and data-interface subexports are independently deserialized and may stop after a nested unsupported Niagara type. Their returned properties are therefore partial, not defaults.",
        },
        ["systems"] = systems,
        ["exports"] = exports,
    };
}

static byte[] WrapBlockCompressedAsDds(
    int width,
    int height,
    byte[] blockData,
    EPixelFormat format,
    bool srgb)
{
    const uint ddsMagic = 0x20534444; // "DDS "
    const uint ddsdCapsHeightWidthPixelFormatLinearSize = 0x00081007;
    const uint ddpfFourCc = 0x00000004;
    const uint ddsCapsTexture = 0x00001000;
    uint fourCc;
    uint? dxgiFormat = null;
    switch (format)
    {
        case EPixelFormat.PF_DXT1: fourCc = 0x31545844; break; // DXT1
        case EPixelFormat.PF_DXT3: fourCc = 0x33545844; break; // DXT3
        case EPixelFormat.PF_DXT5: fourCc = 0x35545844; break; // DXT5
        case EPixelFormat.PF_BC4: fourCc = 0x31495441; break;  // ATI1
        case EPixelFormat.PF_BC5: fourCc = 0x32495441; break;  // ATI2
        case EPixelFormat.PF_BC6H:
            fourCc = 0x30315844; // DX10
            dxgiFormat = 95;     // DXGI_FORMAT_BC6H_UF16
            break;
        case EPixelFormat.PF_BC7:
            fourCc = 0x30315844; // DX10
            dxgiFormat = srgb ? 99u : 98u; // BC7_UNORM_SRGB / BC7_UNORM
            break;
        default:
            throw new NotSupportedException($"DDS block wrapper does not support {format}.");
    }

    var headerLength = dxgiFormat.HasValue ? 148 : 128;
    var output = new byte[headerLength + blockData.Length];
    var header = output.AsSpan(0, 128);
    BinaryPrimitives.WriteUInt32LittleEndian(header[0..4], ddsMagic);
    BinaryPrimitives.WriteUInt32LittleEndian(header[4..8], 124);
    BinaryPrimitives.WriteUInt32LittleEndian(header[8..12], ddsdCapsHeightWidthPixelFormatLinearSize);
    BinaryPrimitives.WriteUInt32LittleEndian(header[12..16], (uint)height);
    BinaryPrimitives.WriteUInt32LittleEndian(header[16..20], (uint)width);
    BinaryPrimitives.WriteUInt32LittleEndian(header[20..24], (uint)blockData.Length);
    BinaryPrimitives.WriteUInt32LittleEndian(header[76..80], 32);
    BinaryPrimitives.WriteUInt32LittleEndian(header[80..84], ddpfFourCc);
    BinaryPrimitives.WriteUInt32LittleEndian(header[84..88], fourCc);
    BinaryPrimitives.WriteUInt32LittleEndian(header[108..112], ddsCapsTexture);
    if (dxgiFormat.HasValue)
    {
        var dx10 = output.AsSpan(128, 20);
        BinaryPrimitives.WriteUInt32LittleEndian(dx10[0..4], dxgiFormat.Value);
        BinaryPrimitives.WriteUInt32LittleEndian(dx10[4..8], 3);  // DDS_DIMENSION_TEXTURE2D
        BinaryPrimitives.WriteUInt32LittleEndian(dx10[12..16], 1); // array size
    }
    blockData.CopyTo(output.AsSpan(headerLength));
    return output;
}

static bool TryReadRemakeResidentMip(
    DefaultFileProvider provider,
    string assetPath,
    UTexture2D texture,
    out int width,
    out int height,
    out byte[] mipData,
    out EPixelFormat format)
{
    width = texture.PlatformData?.SizeX > 0 ? texture.PlatformData.SizeX : texture.ImportedSize.X;
    height = texture.PlatformData?.SizeY > 0 ? texture.PlatformData.SizeY : texture.ImportedSize.Y;
    mipData = [];
    format = texture.Format;
    if (format == EPixelFormat.PF_Unknown)
    {
        // Remake's custom platform-data layout is skipped by the parser, but its
        // pixel format name is still stored verbatim in the package's sidecars.
        // Use that self-describing marker rather than a filename heuristic.
        var formatNames = new Dictionary<string, EPixelFormat>(StringComparer.Ordinal)
        {
            ["PF_DXT1"] = EPixelFormat.PF_DXT1,
            ["PF_DXT3"] = EPixelFormat.PF_DXT3,
            ["PF_DXT5"] = EPixelFormat.PF_DXT5,
            ["PF_BC4"] = EPixelFormat.PF_BC4,
            ["PF_BC5"] = EPixelFormat.PF_BC5,
            ["PF_BC6H"] = EPixelFormat.PF_BC6H,
            ["PF_BC7"] = EPixelFormat.PF_BC7,
        };
        foreach (var sidecar in new[] { assetPath, Path.ChangeExtension(assetPath, ".uexp") })
        {
            if (!provider.Files.TryGetValue(sidecar.Replace('\\', '/'), out var file)) continue;
            var bytes = file.Read(null);
            // Some Remake packages place FName text in the ordinary ANSI name
            // table while others store it as UTF-16.  Both forms occur in the
            // shipped assets, including the 7th Slum rubble textures.
            var asciiText = Encoding.ASCII.GetString(bytes);
            var unicodeText = Encoding.Unicode.GetString(bytes);
            var match = formatNames.FirstOrDefault(pair =>
                asciiText.Contains(pair.Key, StringComparison.Ordinal) ||
                unicodeText.Contains(pair.Key, StringComparison.Ordinal));
            if (!string.IsNullOrEmpty(match.Key))
            {
                format = match.Value;
                break;
            }
        }
        if (format == EPixelFormat.PF_Unknown)
        {
            // A minority of Remake textures omit the platform format string
            // entirely. Their cooked naming convention is consistent for the
            // material channels supported by the add-on, so use it only as a
            // last resort after both package-string representations failed.
            var textureName = Path.GetFileNameWithoutExtension(assetPath);
            format = textureName.Contains("_N", StringComparison.OrdinalIgnoreCase)
                ? EPixelFormat.PF_BC5
                : textureName.Contains("_O", StringComparison.OrdinalIgnoreCase) ||
                  textureName.Contains("Coverage", StringComparison.OrdinalIgnoreCase)
                    ? EPixelFormat.PF_BC4
                    : EPixelFormat.PF_DXT1;
        }
    }
    var bytesPerBlock = format switch
    {
        EPixelFormat.PF_DXT1 or EPixelFormat.PF_BC4 => 8,
        EPixelFormat.PF_DXT3 or EPixelFormat.PF_DXT5 or EPixelFormat.PF_BC5 or
            EPixelFormat.PF_BC6H or EPixelFormat.PF_BC7 => 16,
        _ => 0,
    };
    if (width <= 0 || height <= 0 || bytesPerBlock == 0)
        return false;

    // Remake's platform record places the resident top mip before the normal
    // mip array. CUE4Parse currently reads that record but discards it. The
    // corresponding .ubulk payload begins with that mip, so recover exactly
    // its block-compressed byte range without guessing at later mip offsets.
    var bulkPath = Path.ChangeExtension(assetPath, ".ubulk").Replace('\\', '/');
    if (!provider.Files.TryGetValue(bulkPath, out var bulkFile))
        return false;
    var bulk = bulkFile.Read(null);
    // Some streamed Remake textures retain only a lower resident mip in the
    // bulk container.  Export the largest complete resident level instead of
    // rejecting an otherwise usable texture because its imported size names a
    // streamed top level.
    long requiredBytes;
    while (true)
    {
        requiredBytes = checked((long)((width + 3) / 4) * ((height + 3) / 4) * bytesPerBlock);
        if (bulk.Length >= requiredBytes || (width <= 4 && height <= 4))
            break;
        width = Math.Max(4, width / 2);
        height = Math.Max(4, height / 2);
    }
    if (bulk.Length < requiredBytes)
        return false;
    mipData = bulk.AsSpan(0, checked((int)requiredBytes)).ToArray();
    return true;
}

static bool TryReadInlinePackageMip(
    DefaultFileProvider provider,
    string assetPath,
    UTexture2D texture,
    out int width,
    out int height,
    out byte[] mipData)
{
    width = height = 0;
    mipData = [];
    var format = texture.Format;
    var bytesPerBlock = format switch
    {
        EPixelFormat.PF_DXT1 or EPixelFormat.PF_BC4 => 8,
        EPixelFormat.PF_DXT3 or EPixelFormat.PF_DXT5 or EPixelFormat.PF_BC5 or
            EPixelFormat.PF_BC6H or EPixelFormat.PF_BC7 => 16,
        _ => 0,
    };
    if (bytesPerBlock == 0) return false;

    var uassetPath = assetPath.Replace('\\', '/');
    var uexpPath = Path.ChangeExtension(uassetPath, ".uexp");
    if (!provider.Files.TryGetValue(uassetPath, out var uassetFile) ||
        !provider.Files.TryGetValue(uexpPath, out var uexpFile))
        return false;
    var uassetLength = uassetFile.Read(null).Length;
    var uexp = uexpFile.Read(null);

    // Small cooked textures can keep their mips at offsets in the package
    // sidecar. CUE4Parse exposes those headers even when its deferred bulk
    // reader returns no Data, so honour the header rather than assuming every
    // mip lives in a .ubulk companion.
    foreach (var candidate in texture.PlatformData?.Mips ?? [])
    {
        if (candidate?.BulkData is not { } bulk || candidate.SizeX <= 0 || candidate.SizeY <= 0)
            continue;
        var header = bulk.Header;
        if (header.SizeOnDisk == 0 || (header.BulkDataFlags &
            (CUE4Parse.UE4.Assets.Objects.EBulkDataFlags.BULKDATA_SerializeCompressedZLIB |
             CUE4Parse.UE4.Assets.Objects.EBulkDataFlags.BULKDATA_CompressedLZO)) != 0)
            continue;
        var requiredBytes = checked(((candidate.SizeX + 3) / 4) * ((candidate.SizeY + 3) / 4) * bytesPerBlock);
        if (header.SizeOnDisk < requiredBytes) continue;
        foreach (var dataOffset in new[] { header.OffsetInFile - uassetLength, header.OffsetInFile })
        {
            if (dataOffset < 0 || dataOffset + requiredBytes > uexp.Length) continue;
            width = candidate.SizeX;
            height = candidate.SizeY;
            mipData = uexp.AsSpan(checked((int)dataOffset), requiredBytes).ToArray();
            return true;
        }
    }
    return false;
}

static Dictionary<string, object?> ExportTextureDds(
    DefaultFileProvider provider,
    string assetPath,
    CUE4Parse.UE4.Assets.IPackage package,
    string? ddsOutput)
{
    var texture = package.GetExports().OfType<UTexture2D>().FirstOrDefault();
    if (texture is null)
        throw new InvalidOperationException("Package does not contain a Texture2D export.");
    var mips = texture.PlatformData?.Mips ?? [];
    var mip = mips.FirstOrDefault(candidate => candidate?.BulkData?.Data is { Length: > 0 });
    var pixelFormat = texture.Format;
    int width;
    int height;
    byte[] mipData;
    if (mip is null)
    {
        if (TryReadInlinePackageMip(provider, assetPath, texture, out width, out height, out mipData))
        {
            // Texture.Format already describes the recovered conventional mip.
        }
        else if (TryReadRemakeResidentMip(provider, assetPath, texture, out width, out height, out mipData, out var remakeFormat))
        {
            pixelFormat = remakeFormat;
        }
        else
        {
            var expectedBulkPath = Path.ChangeExtension(assetPath, ".ubulk").Replace('\\', '/');
            var relatedFiles = string.Join(", ", provider.Files.Keys
                .Where(path => path.Contains(Path.GetFileNameWithoutExtension(assetPath), StringComparison.OrdinalIgnoreCase))
                .Take(8));
            var mipHeaders = string.Join("; ", mips
                .Where(candidate => candidate?.BulkData is not null)
                .Select(candidate =>
                {
                    var header = candidate!.BulkData!.Header;
                    return $"{candidate.SizeX}x{candidate.SizeY} flags=0x{(uint)header.BulkDataFlags:X} size={header.SizeOnDisk} offset={header.OffsetInFile}";
                }));
            throw new InvalidOperationException(
                $"Texture has no readable mip (platform data: {(texture.PlatformData is null ? "null" : "present")}, mips: {mips.Length}, " +
                $"format: {texture.Format}, platform size: {texture.PlatformData?.SizeX}x{texture.PlatformData?.SizeY}, " +
                $"imported size: {texture.ImportedSize.X}x{texture.ImportedSize.Y}, expected bulk: {expectedBulkPath}, " +
                $"bulk exists: {provider.Files.ContainsKey(expectedBulkPath)}, related files: {relatedFiles}, mip headers: {mipHeaders}).");
        }
    }
    else
    {
        width = mip.SizeX;
        height = mip.SizeY;
        mipData = mip.BulkData.Data!;
    }
    var blockCompressed = pixelFormat is
        EPixelFormat.PF_DXT1 or EPixelFormat.PF_DXT3 or EPixelFormat.PF_DXT5 or
        EPixelFormat.PF_BC4 or EPixelFormat.PF_BC5 or EPixelFormat.PF_BC6H or
        EPixelFormat.PF_BC7;
    var ddsBytes = blockCompressed
        ? WrapBlockCompressedAsDds(width, height, mipData, pixelFormat, texture.SRGB)
        : TextureEncoder.Encode(
            new CTexture(width, height, pixelFormat, mipData),
            ETextureFormat.Dds,
            texture.SRGB,
            out _);
    if (!string.IsNullOrWhiteSpace(ddsOutput))
        File.WriteAllBytes(Path.GetFullPath(ddsOutput), ddsBytes);
    return new Dictionary<string, object?>
    {
        ["width"] = width,
        ["height"] = height,
        ["pixelFormat"] = pixelFormat.ToString(),
        ["srgb"] = texture.SRGB,
        ["fileExtension"] = "dds",
        ["byteLength"] = ddsBytes.Length,
        ["output"] = ddsOutput
    };
}

static Dictionary<string, object?> ExportStaticMeshLod(
    string meshName,
    FStaticMeshLODResources sourceLod,
    FStaticMaterial[] staticMaterials,
    ResolvedObject?[] fallbackMaterials,
    int lodIndex,
    string sourceType,
    string renderData)
{
    var positions = sourceLod.PositionVertexBuffer?.Verts
        ?? throw new InvalidOperationException("StaticMesh position data is unavailable.");
    var vertexBuffer = sourceLod.VertexBuffer
        ?? throw new InvalidOperationException("StaticMesh vertex attributes are unavailable.");
    var vertexItems = vertexBuffer.UV;
    var indices = sourceLod.IndexBuffer?.Buffer
        ?? throw new InvalidOperationException("StaticMesh index data is unavailable.");
    var colors = sourceLod.ColorVertexBuffer?.Data;
    if (positions.Length != vertexItems.Length)
        throw new InvalidOperationException(
            $"StaticMesh position/attribute count mismatch ({positions.Length} vs {vertexItems.Length}).");
    if (colors is { Length: > 0 } && colors.Length != positions.Length)
        throw new InvalidOperationException(
            $"StaticMesh position/color count mismatch ({positions.Length} vs {colors.Length}).");

    var uvChannels = new List<object?>();
    for (var channelIndex = 0; channelIndex < vertexBuffer.NumTexCoords; channelIndex++)
    {
        var capturedChannel = channelIndex;
        uvChannels.Add(vertexItems.Select(item =>
        {
            var uv = item.UV[capturedChannel];
            return new[] { uv.U, uv.V };
        }).ToArray());
    }

    var sections = sourceLod.Sections.Select(section =>
    {
        var staticMaterial = section.MaterialIndex >= 0 && section.MaterialIndex < staticMaterials.Length
            ? staticMaterials[section.MaterialIndex]
            : null;
        var fallbackMaterial = section.MaterialIndex >= 0 && section.MaterialIndex < fallbackMaterials.Length
            ? fallbackMaterials[section.MaterialIndex]
            : null;
        var materialPath = staticMaterial?.MaterialInterface?.GetPathName() ?? fallbackMaterial?.GetPathName();
        var materialName = MaterialNameFromSlotOrPath(
            staticMaterial?.MaterialSlotName.Text ?? fallbackMaterial?.Name.Text,
            materialPath);
        return (object?)new Dictionary<string, object?>
        {
            ["materialIndex"] = section.MaterialIndex,
            ["materialName"] = materialName,
            ["materialPath"] = materialPath,
            ["firstIndex"] = section.FirstIndex,
            ["triangleCount"] = section.NumTriangles,
            ["castShadow"] = section.bCastShadow,
        };
    }).ToList();

    return new Dictionary<string, object?>
    {
        ["sourceType"] = sourceType,
        ["name"] = meshName,
        ["renderData"] = renderData,
        ["lodIndex"] = lodIndex,
        ["vertexCount"] = positions.Length,
        ["triangleCount"] = indices.Length / 3,
        ["positions"] = positions.Select(position =>
            new[] { position.X, position.Y, position.Z }).ToArray(),
        ["normals"] = vertexItems.Select(item =>
            new[] { item.Normal[2].X, item.Normal[2].Y, item.Normal[2].Z }).ToArray(),
        ["tangents"] = vertexItems.Select(item =>
            new[] { item.Normal[0].X, item.Normal[0].Y, item.Normal[0].Z, item.Normal[2].W }).ToArray(),
        ["uvChannels"] = uvChannels,
        ["colors"] = colors is { Length: > 0 }
            ? colors.Select(color =>
                new[] { (int) color.R, (int) color.G, (int) color.B, (int) color.A }).ToArray()
            : null,
        ["indices"] = indices,
        ["sections"] = sections,
    };
}

// Remake's cooked mesh records can omit MaterialSlotName even though their
// MaterialInterface reference is intact.  Use that object's asset name before
// letting the Blender importer fall back to Material_0, Material_1, etc.
static string? MaterialNameFromSlotOrPath(string? slotName, string? materialPath)
{
    if (!string.IsNullOrWhiteSpace(slotName) &&
        !string.Equals(slotName, "None", StringComparison.OrdinalIgnoreCase))
        return slotName;
    if (string.IsNullOrWhiteSpace(materialPath))
        return null;

    var path = materialPath.Trim().Trim('\'');
    var extensionIndex = path.LastIndexOf('.');
    var assetName = extensionIndex >= 0 ? path[(extensionIndex + 1)..] : Path.GetFileName(path);
    return string.IsNullOrWhiteSpace(assetName) ? null : assetName;
}

static Dictionary<string, object?> ExportStaticMeshAsset(UStaticMesh sourceMesh)
{
    var lods = sourceMesh.RenderData?.LODs
        ?? throw new InvalidOperationException(
            "StaticMesh render data is unavailable. Packed layouts require " +
            "CUE4Parse's packed-tangent support from 2026-08-28 or newer.");
    var lodIndex = Array.FindIndex(lods, lod =>
        !lod.SkipLod && lod.PositionVertexBuffer is { NumVertices: > 0 } &&
        lod.VertexBuffer is { NumVertices: > 0 } && lod.IndexBuffer is { Length: > 0 });
    if (lodIndex < 0)
        throw new InvalidOperationException("StaticMesh has no importable conventional LOD.");
    // Remake serializes these as cooked UPROPERTY data. Its native render-data
    // reader can consume the empty legacy array that follows instead, leaving
    // UStaticMesh.StaticMaterials blank even though the mapped property has
    // every MaterialInterface reference intact.
    var staticMaterials = sourceMesh.StaticMaterials ?? [];
    if (staticMaterials.Length == 0)
        staticMaterials = sourceMesh.GetOrDefault<FStaticMaterial[]>("StaticMaterials", []);
    return ExportStaticMeshLod(
        sourceMesh.Name.ToString(), lods[lodIndex], staticMaterials, sourceMesh.Materials ?? [],
        lodIndex, "UStaticMesh", "ConventionalLOD");
}

static Dictionary<string, object?> ExportRebirthFlattenedStaticMesh(
    DefaultFileProvider provider,
    string assetPath,
    CUE4Parse.UE4.Assets.IoPackage package)
{
    // Rebirth 1.005 moved the static-mesh GPU streams into one flat bulk payload.
    // Unlike UE's normal cooked layout, that payload has no per-buffer headers;
    // the sizes and FF7 meshlet-table counts live in the uasset export instead.
    var meshName = Path.GetFileNameWithoutExtension(assetPath);
    var meshIndex = Array.FindIndex(package.ExportMap,
        entry => package.CreateFNameFromMappedName(entry.ObjectName).Text == meshName);
    if (meshIndex < 0)
        throw new InvalidOperationException($"Could not locate StaticMesh export '{meshName}'.");

    var rawPackage = provider.Files[assetPath].Read(null);
    using var archive = new FAssetArchive(
        new FByteArchive(assetPath, rawPackage, provider.Versions), package);
    var summary = archive.Read<FPackageSummary>();
    archive.Position = summary.ExportBundlesOffset;
    var remainingBundleEntryCount =
        (summary.GraphDataOffset - summary.ExportBundlesOffset) / (sizeof(int) * 2);
    var foundBundleEntryCount = 0;
    var bundleHeaders = new List<FExportBundleHeader>();
    while (foundBundleEntryCount < remainingBundleEntryCount)
    {
        remainingBundleEntryCount--;
        var header = new FExportBundleHeader(archive);
        foundBundleEntryCount += (int) header.EntryCount;
        bundleHeaders.Add(header);
    }
    if (foundBundleEntryCount != remainingBundleEntryCount)
        throw new InvalidOperationException("Could not decode the IoStore export-bundle table.");
    var bundleEntries = archive.ReadArray<FExportBundleEntry>(foundBundleEntryCount);
    var exportPosition = summary.GraphDataOffset + summary.GraphDataSize;
    var foundPosition = -1;
    foreach (var bundle in bundleHeaders)
    {
        for (var index = 0u; index < bundle.EntryCount; index++)
        {
            var entry = bundleEntries[bundle.FirstEntryIndex + index];
            if (entry.CommandType != EExportCommandType.ExportCommandType_Serialize)
                continue;
            if (entry.LocalExportIndex == meshIndex)
                foundPosition = exportPosition;
            exportPosition += (int) package.ExportMap[entry.LocalExportIndex].CookedSerialSize;
        }
    }
    if (foundPosition < 0)
        throw new InvalidOperationException($"No serialized export-bundle entry was found for '{meshName}'.");

    var export = package.ExportMap[meshIndex];
    archive.AbsoluteOffset = (int) export.CookedSerialOffset - foundPosition;
    archive.Position = foundPosition;
    var validPosition = archive.Position + (long) export.CookedSerialSize;

    // Deserialize only UObject's property header. UStaticMesh's stock reader
    // cannot cross the flat 1.005 render-data payload yet.
    var propertyReader = new UObject
    {
        Name = meshName,
        Class = package.ResolveObjectIndex(export.ClassIndex),
        Outer = package.ResolveObjectIndex(export.OuterIndex),
        Super = package.ResolveObjectIndex(export.SuperIndex),
        Template = package.ResolveObjectIndex(export.TemplateIndex),
        Flags = export.ObjectFlags,
    };
    propertyReader.Deserialize(archive, validPosition);

    _ = new FStripDataFlags(archive);
    var cooked = archive.ReadBoolean();
    _ = new FPackageIndex(archive); // BodySetup
    if (archive.Versions["StaticMesh.HasNavCollision"])
        _ = new FPackageIndex(archive);
    archive.Position += 16; // LightingGuid
    _ = archive.ReadArray(() => new FPackageIndex(archive)); // Sockets
    if (!cooked)
        throw new InvalidOperationException("StaticMesh has no cooked render data.");

    var lodCount = archive.Read<int>();
    if (lodCount is < 1 or > 8)
        throw new InvalidOperationException($"Unexpected Rebirth static-mesh LOD count {lodCount}.");

    // The first conventional LOD is the import target. This is also what FModel
    // exported for the reference asset before the 1.005 layout change.
    var lodStart = archive.Position;
    _ = new FStripDataFlags(archive);
    var sourceSections = archive.ReadArray(() => new FStaticMeshSection(archive));
    _ = archive.Read<float>(); // MaxDeviation
    var cookedOut = archive.ReadBoolean();
    var inlined = archive.ReadBoolean();
    // FByteBulkData handles both inlined payloads and payloads kept in the
    // matching .ubulk.  Only cooked-out data has no usable render payload.
    if (cookedOut)
        throw new InvalidOperationException(
            $"Unsupported Rebirth LOD flags (cookedOut={cookedOut}, inlined={inlined}).");

    if (inlined)
    {
        Dictionary<string, object?> ExportInlinePackedMesh()
        {
        // The August NuGet build predates Rebirth's four-byte packed tangent
        // frame. Parse the conventional inline streams here using the same
        // representation as the flattened-layout decoder below.
        _ = new FStripDataFlags(archive); // buffer strip flags

        var positionStride = archive.Read<int>();
        var vertexCount = archive.Read<int>();
        var positionItemSize = archive.Read<int>();
        var positionCount = archive.Read<int>();
        if (positionStride != 12 || positionItemSize != 12 ||
            vertexCount <= 0 || positionCount != vertexCount)
            throw new InvalidOperationException(
                $"Unsupported inline StaticMesh position metadata " +
                $"({positionCount}/{vertexCount} vertices, stride={positionStride}, item={positionItemSize}).");
        var positions = archive.ReadArray(vertexCount, () =>
        {
            var position = archive.Read<FVector>();
            return new[] { position.X, position.Y, position.Z };
        });

        _ = new FStripDataFlags(
            archive,
            FPackageFileVersion.CreateUE4Version(
                EUnrealEngineObjectUE4Version.STATIC_SKELETAL_MESH_SERIALIZATION_FIX));
        var uvChannelCount = archive.Read<int>();
        var attributeVertexCount = archive.Read<int>();
        var fullPrecisionUvs = archive.ReadBoolean();
        var highPrecisionTangents = archive.ReadBoolean();
        var tangentItemSize = archive.Read<int>();
        var tangentCount = archive.Read<int>();
        if (uvChannelCount is < 1 or > 8 || attributeVertexCount != vertexCount ||
            fullPrecisionUvs || highPrecisionTangents ||
            tangentItemSize != sizeof(uint) || tangentCount != vertexCount)
            throw new InvalidOperationException(
                "Unsupported inline StaticMesh vertex metadata " +
                $"(vertices={attributeVertexCount}/{vertexCount}, uvs={uvChannelCount}, " +
                $"fullUV={fullPrecisionUvs}, highTangent={highPrecisionTangents}, " +
                $"tangents={tangentCount}x{tangentItemSize}).");

        var normals = new float[vertexCount][];
        var tangents = new float[vertexCount][];
        for (var vertex = 0; vertex < vertexCount; vertex++)
        {
            var packedFrame = archive.Read<uint>();
            var u = (packedFrame & 1023) / 1023.0;
            var v = ((packedFrame >> 10) & 1023) / 1023.0;
            var nx = u - v;
            var ny = u + v - 1.0;
            var nz = 1.0 - Math.Abs(nx) - Math.Abs(ny);
            if ((packedFrame & (1u << 30)) == 0) nz = -nz;
            var normalLength = Math.Sqrt(nx * nx + ny * ny + nz * nz);
            nx /= normalLength;
            ny /= normalLength;
            nz /= normalLength;
            normals[vertex] = [(float) nx, (float) ny, (float) nz];

            var sign = nz >= 0.0 ? -1.0 : 1.0;
            var a = 1.0 / (nz - sign);
            var e1x = 1.0 + sign * nx * nx * a;
            var e1y = sign * nx * ny * a;
            var e1z = sign * nx;
            var e2x = nx * ny * a;
            var e2y = sign + ny * ny * a;
            var e2z = ny;
            var angle = (packedFrame >> 20) & 1023;
            var t = (angle & 255) / 255.0;
            var cx = (angle & 256) != 0 ? t : -t;
            var cy = (angle & 512) != 0 ? 1.0 - t : -(1.0 - t);
            var circleLength = Math.Sqrt(cx * cx + cy * cy);
            cx /= circleLength;
            cy /= circleLength;
            tangents[vertex] =
            [
                (float) (e1x * cx + e2x * cy),
                (float) (e1y * cx + e2y * cy),
                (float) (e1z * cx + e2z * cy),
                (packedFrame & (1u << 31)) != 0 ? 1.0f : -1.0f,
            ];
        }

        var uvItemSize = archive.Read<int>();
        var uvItemCount = archive.Read<int>();
        if (uvItemSize != 4 || uvItemCount != vertexCount * uvChannelCount)
            throw new InvalidOperationException(
                $"Unsupported inline StaticMesh UV metadata ({uvItemCount}x{uvItemSize}).");
        var uvChannels = Enumerable.Range(0, uvChannelCount)
            .Select(_ => new float[vertexCount][]).ToArray();
        for (var vertex = 0; vertex < vertexCount; vertex++)
        for (var channel = 0; channel < uvChannelCount; channel++)
            uvChannels[channel][vertex] =
            [
                (float) archive.Read<Half>(),
                (float) archive.Read<Half>(),
            ];

        _ = new FStripDataFlags(
            archive,
            FPackageFileVersion.CreateUE4Version(
                EUnrealEngineObjectUE4Version.STATIC_SKELETAL_MESH_SERIALIZATION_FIX));
        var colorStride = archive.Read<int>();
        var colorCount = archive.Read<int>();
        int[][]? colors = null;
        if (colorCount > 0)
        {
            var colorItemSize = archive.Read<int>();
            var serializedColorCount = archive.Read<int>();
            if (colorStride != 4 || colorItemSize != 4 ||
                colorCount != vertexCount || serializedColorCount != colorCount)
                throw new InvalidOperationException(
                    $"Unsupported inline StaticMesh color metadata ({serializedColorCount}/{colorCount}x{colorItemSize}).");
            colors = archive.ReadArray(colorCount, () =>
            {
                var color = archive.Read<FColor>();
                return new[] { (int) color.R, (int) color.G, (int) color.B, (int) color.A };
            });
        }

        var uses32BitIndices = archive.ReadBoolean();
        var indexItemSize = archive.Read<int>();
        var indexByteCount = archive.Read<int>();
        var expectedIndexItemSize = uses32BitIndices ? 4 : 2;
        if (indexItemSize != 1 || indexByteCount <= 0 ||
            indexByteCount % expectedIndexItemSize != 0)
            throw new InvalidOperationException(
                $"Unsupported inline StaticMesh index metadata ({indexByteCount} bytes, " +
                $"item={indexItemSize}, index32={uses32BitIndices}).");
        var indexCount = indexByteCount / expectedIndexItemSize;
        var indices = uses32BitIndices
            ? archive.ReadArray(indexCount, archive.Read<uint>)
            : archive.ReadArray(indexCount, () => (uint) archive.Read<ushort>());

        var requiredIndexCount = sourceSections.Max(section =>
            checked((int) section.FirstIndex + (int) section.NumTriangles * 3));
        if (requiredIndexCount <= 0 || requiredIndexCount > indices.Length ||
            indices.Any(index => index >= vertexCount))
            throw new InvalidOperationException(
                $"Inline StaticMesh index ranges are invalid ({requiredIndexCount}/{indices.Length}).");

        var inlineMaterials = propertyReader.GetOrDefault<FStaticMaterial[]>("StaticMaterials", []);
        var outputSections = sourceSections.Select(section =>
        {
            var staticMaterial = section.MaterialIndex >= 0 && section.MaterialIndex < inlineMaterials.Length
                ? inlineMaterials[section.MaterialIndex]
                : null;
            return (object?) new Dictionary<string, object?>
            {
                ["materialIndex"] = section.MaterialIndex,
                ["materialName"] = staticMaterial?.MaterialSlotName.ToString(),
                ["materialPath"] = staticMaterial?.MaterialInterface?.GetPathName(),
                ["firstIndex"] = section.FirstIndex,
                ["triangleCount"] = section.NumTriangles,
                ["castShadow"] = section.bCastShadow,
            };
        }).ToList();
            return new Dictionary<string, object?>
            {
            ["sourceType"] = "FF7 Rebirth inline UStaticMesh",
            ["name"] = meshName,
            ["renderData"] = "InlinePackedTangents",
            ["lodIndex"] = 0,
            ["vertexCount"] = vertexCount,
            ["triangleCount"] = requiredIndexCount / 3,
            ["positions"] = positions,
            ["normals"] = normals,
            ["tangents"] = tangents,
            ["uvChannels"] = uvChannels,
            ["colors"] = colors,
            ["indices"] = indices.Take(requiredIndexCount).ToArray(),
                ["sections"] = outputSections,
            };
        }

        return ExportInlinePackedMesh();
    }

    var bulk = new FByteBulkData(archive);
    var bulkData = bulk.Data;
    if (bulkData is null)
    {
        // A hand-opened IoStore export archive does not inherit the package
        // reader's payload callback. Resolve its virtual ubulk directly.
        var bulkPath = Path.ChangeExtension(assetPath, ".ubulk").Replace('\\', '/');
        if (!provider.Files.TryGetValue(bulkPath, out var bulkFile))
            throw new InvalidOperationException($"StaticMesh bulk payload '{bulkPath}' is unavailable.");
        var completeBulk = bulkFile.Read(null);
        var size = checked((int) bulk.Header.SizeOnDisk);
        var offset = completeBulk.Length == size ? 0 : checked((int) bulk.Header.OffsetInFile);
        if (offset < 0 || size <= 0 || offset + size > completeBulk.Length)
            throw new InvalidOperationException("StaticMesh bulk payload range is invalid.");
        bulkData = completeBulk.AsSpan(offset, size).ToArray();
    }

    _ = archive.Read<int>(); // DepthOnlyNumTriangles
    _ = archive.Read<int>(); // packed index-buffer flags
    var uvChannelCount = archive.Read<int>();
    var vertexCount = archive.Read<int>();
    var fullPrecisionUvs = archive.ReadBoolean();
    var highPrecisionTangents = archive.ReadBoolean();
    var positionStride = archive.Read<int>();
    var positionCount = archive.Read<int>();
    var colorStride = archive.Read<int>();
    var colorCount = archive.Read<int>();
    var legacyIndexBufferField = archive.Read<int>();
    var legacyUses32BitIndices = archive.ReadBoolean();

    var batchCount = archive.Read<int>();
    var meshletIndexCount = archive.Read<int>();
    var packedTriangleCount = archive.Read<int>();
    _ = archive.Read<int>(); // batch-info count
    _ = archive.Read<int>(); // internal LOD table count
    var batchIndexCount = archive.Read<int>();
    var auxiliaryStructCount = archive.Read<int>();
    var zeroIndex = archive.Read<int>();

    if (vertexCount <= 0 || positionCount != vertexCount || positionStride != 12 ||
        uvChannelCount is < 1 or > 8 || fullPrecisionUvs || highPrecisionTangents ||
        colorStride is not (0 or 4) || colorCount is not (0) && colorCount != vertexCount)
        throw new InvalidOperationException(
            "Unsupported flattened StaticMesh vertex-buffer metadata " +
            $"(vertices={vertexCount}, positions={positionCount}x{positionStride}, " +
            $"uvs={uvChannelCount}, fullUV={fullPrecisionUvs}, highTangent={highPrecisionTangents}, " +
            $"colors={colorCount}x{colorStride}).");
    var hasMeshlets = batchCount > 0 && meshletIndexCount > 0 && packedTriangleCount > 0;
    var hasNoMeshlets = batchCount == 0 && meshletIndexCount == 0 && packedTriangleCount == 0 &&
        batchIndexCount == 0 && auxiliaryStructCount == 0 && zeroIndex == 0;
    if ((!hasMeshlets && !hasNoMeshlets) || batchIndexCount < 0 ||
        auxiliaryStructCount != 0 || zeroIndex != 0)
        throw new InvalidOperationException(
            "Unsupported flattened StaticMesh meshlet metadata " +
            $"(batches={batchCount}, meshletIndices={meshletIndexCount}, " +
            $"packedTriangles={packedTriangleCount}, batchIndices={batchIndexCount}, " +
            $"auxiliary={auxiliaryStructCount}, zeroIndex={zeroIndex}).");

    var tangentStride = 4; // 1.005 R10G10B10A2_UNORM tangent frame
    var uvStride = 4; // two half floats
    var positionOffset = 0;
    var tangentOffset = checked(positionOffset + vertexCount * positionStride);
    var uvOffset = checked(tangentOffset + vertexCount * tangentStride);
    var colorOffset = checked(uvOffset + vertexCount * uvChannelCount * uvStride);
    var vertexPayloadEnd = checked(colorOffset + colorCount * colorStride);
    if (vertexPayloadEnd > bulkData.Length)
        throw new InvalidOperationException("Flattened StaticMesh vertex buffers exceed the bulk payload.");

    var sectionLodIndices = Array.Empty<int>();
    var lodInfos = Array.Empty<(int BatchesOffset, int BatchesCount, int VerticesOffset, int VerticesCount)>();
    var batchRange = (Offset: 0, Size: 0);
    var meshletIndexRange = (Offset: 0, Size: 0);
    var packedTriangleRange = (Offset: 0, Size: 0);
    var batchIndexRange = (Offset: 0, Size: 0);
    if (hasMeshlets)
    {
        // The updated FF7LodInfo tail uses 2/5/6 elements for its
        // ushort/float arrays (76 bytes total), rather than the older shape.
        archive.Position += 24; // retail-only opaque render-data header
        sectionLodIndices = archive.ReadArray<int>();
        var lodInfoCount = archive.Read<int>();
        if (lodInfoCount is < 1 or > 4096)
            throw new InvalidOperationException($"Unexpected FF7 LOD-info count {lodInfoCount}.");
        lodInfos = new (int BatchesOffset, int BatchesCount, int VerticesOffset, int VerticesCount)[lodInfoCount];
        for (var index = 0; index < lodInfoCount; index++)
        {
            _ = archive.Read<int>(); // Index
            _ = archive.Read<int>(); // unknown
            _ = archive.Read<int>(); // Offset
            _ = archive.Read<int>(); // Count
            _ = archive.Read<int>(); // IndicesOffset
            _ = archive.Read<int>(); // IndicesCount
            var batchesOffset = archive.Read<int>();
            var batchesCount = archive.Read<int>();
            var verticesOffset = archive.Read<int>();
            var verticesCount = archive.Read<int>();
            archive.Position += 36; // ushort[2], float[5], ushort[6]
            lodInfos[index] = (batchesOffset, batchesCount, verticesOffset, verticesCount);
        }
        if (sectionLodIndices.Length != sourceSections.Length ||
            sectionLodIndices.Any(index => index < 0 || index >= lodInfos.Length))
            throw new InvalidOperationException("FF7 section-to-LOD mapping is invalid.");

        _ = archive.ReadArray<int>(); // secondary section indices
        var secondaryLodInfoCount = archive.Read<int>();
        if (secondaryLodInfoCount is < 0 or > 4096)
            throw new InvalidOperationException($"Unexpected secondary FF7 LOD-info count {secondaryLodInfoCount}.");
        archive.Position += secondaryLodInfoCount * 76L;
        var trailingIndexCount = archive.Read<int>();
        var flattenedVersion = archive.Read<int>();
        var flattenedFlags = archive.Read<int>();
        if (trailingIndexCount != 0 || flattenedVersion != 1 || flattenedFlags != 0)
            throw new InvalidOperationException("Unsupported flattened StaticMesh buffer-table header.");

        archive.Position += 44; // conventional buffer descriptors
        (int Offset, int Size) ReadRange() => (archive.Read<int>(), archive.Read<int>());
        batchRange = ReadRange();
        _ = ReadRange(); // batch-info/internal-LOD data
        meshletIndexRange = ReadRange();
        packedTriangleRange = ReadRange();
        _ = ReadRange(); // auxiliary meshlet data A
        _ = ReadRange(); // auxiliary meshlet data B
        batchIndexRange = ReadRange();
    }
    else
    {
        var requiredIndexCount = sourceSections.Max(section =>
            checked((int) section.FirstIndex + (int) section.NumTriangles * 3));
        if (legacyIndexBufferField < requiredIndexCount)
            throw new InvalidOperationException(
                $"Legacy index count {legacyIndexBufferField} is smaller than the section ranges ({requiredIndexCount}).");
        var indexStride = legacyUses32BitIndices ? 4 : 2;
        if (vertexPayloadEnd + checked(legacyIndexBufferField * indexStride) > bulkData.Length)
            throw new InvalidOperationException("Legacy StaticMesh indices exceed the bulk payload.");
    }

    var batchOffset = batchRange.Offset;
    var meshletIndexOffset = meshletIndexRange.Offset;
    var packedTriangleOffset = packedTriangleRange.Offset;
    if (hasMeshlets && (batchOffset != vertexPayloadEnd ||
        batchRange.Size != checked(batchCount * 16) ||
        meshletIndexRange.Size != checked(meshletIndexCount * sizeof(uint)) ||
        packedTriangleRange.Size != checked(packedTriangleCount * sizeof(uint)) ||
        batchIndexRange.Size != checked(batchIndexCount * sizeof(uint)) ||
        batchOffset < 0 || meshletIndexOffset < batchOffset + batchRange.Size ||
        packedTriangleOffset < meshletIndexOffset + meshletIndexRange.Size ||
        packedTriangleOffset + packedTriangleRange.Size > bulkData.Length))
        throw new InvalidOperationException("Flattened StaticMesh bulk-buffer ranges overlap or exceed the payload.");

    static uint ReadU32(byte[] data, int offset) =>
        BinaryPrimitives.ReadUInt32LittleEndian(data.AsSpan(offset, sizeof(uint)));
    static int ReadI32(byte[] data, int offset) => unchecked((int) ReadU32(data, offset));
    static float ReadF32(byte[] data, int offset) =>
        BitConverter.Int32BitsToSingle(ReadI32(data, offset));

    var positions = new float[vertexCount][];
    var normals = new float[vertexCount][];
    var tangents = new float[vertexCount][];
    var uvChannels = Enumerable.Range(0, uvChannelCount)
        .Select(_ => new float[vertexCount][]).ToArray();
    byte[][]? colors = colorCount > 0 ? new byte[vertexCount][] : null;
    for (var vertex = 0; vertex < vertexCount; vertex++)
    {
        var position = positionOffset + vertex * positionStride;
        positions[vertex] = [ReadF32(bulkData, position), ReadF32(bulkData, position + 4), ReadF32(bulkData, position + 8)];

        var packedFrame = ReadU32(bulkData, tangentOffset + vertex * tangentStride);
        var u = (packedFrame & 1023) / 1023.0;
        var v = ((packedFrame >> 10) & 1023) / 1023.0;
        var nx = u - v;
        var ny = u + v - 1.0;
        var nz = 1.0 - Math.Abs(nx) - Math.Abs(ny);
        if ((packedFrame & (1u << 30)) == 0) nz = -nz;
        var normalLength = Math.Sqrt(nx * nx + ny * ny + nz * nz);
        nx /= normalLength;
        ny /= normalLength;
        nz /= normalLength;
        normals[vertex] = [(float) nx, (float) ny, (float) nz];

        var sign = nz >= 0.0 ? -1.0 : 1.0;
        var a = 1.0 / (nz - sign);
        var e1x = 1.0 + sign * nx * nx * a;
        var e1y = sign * nx * ny * a;
        var e1z = sign * nx;
        var e2x = nx * ny * a;
        var e2y = sign + ny * ny * a;
        var e2z = ny;
        var angle = (packedFrame >> 20) & 1023;
        var t = (angle & 255) / 255.0;
        var cx = (angle & 256) != 0 ? t : -t;
        var cy = (angle & 512) != 0 ? 1.0 - t : -(1.0 - t);
        var circleLength = Math.Sqrt(cx * cx + cy * cy);
        cx /= circleLength;
        cy /= circleLength;
        tangents[vertex] =
        [
            (float) (e1x * cx + e2x * cy),
            (float) (e1y * cx + e2y * cy),
            (float) (e1z * cx + e2z * cy),
            (packedFrame & (1u << 31)) != 0 ? 1.0f : -1.0f,
        ];

        for (var channel = 0; channel < uvChannelCount; channel++)
        {
            var uv = uvOffset + (vertex * uvChannelCount + channel) * uvStride;
            uvChannels[channel][vertex] =
            [
                (float) BitConverter.UInt16BitsToHalf(BinaryPrimitives.ReadUInt16LittleEndian(bulkData.AsSpan(uv, 2))),
                (float) BitConverter.UInt16BitsToHalf(BinaryPrimitives.ReadUInt16LittleEndian(bulkData.AsSpan(uv + 2, 2))),
            ];
        }
        if (colors is not null)
        {
            var color = colorOffset + vertex * colorStride;
            colors[vertex] = [bulkData[color], bulkData[color + 1], bulkData[color + 2], bulkData[color + 3]];
        }
    }

    var fullIndices = new List<uint>(hasMeshlets ? packedTriangleCount * 3 : legacyIndexBufferField);
    if (!hasMeshlets)
    {
        var indexStride = legacyUses32BitIndices ? 4 : 2;
        for (var index = 0; index < legacyIndexBufferField; index++)
        {
            var offset = vertexPayloadEnd + index * indexStride;
            var vertexIndex = legacyUses32BitIndices
                ? ReadU32(bulkData, offset)
                : BinaryPrimitives.ReadUInt16LittleEndian(bulkData.AsSpan(offset, 2));
            if (vertexIndex >= vertexCount)
                throw new InvalidOperationException(
                    $"Legacy StaticMesh index {index} references vertex {vertexIndex}/{vertexCount}.");
            fullIndices.Add(vertexIndex);
        }
    }
    else
    {
        for (var batch = 0; batch < batchCount; batch++)
        {
            var offset = batchOffset + batch * 16;
            var totalVertices = ReadI32(bulkData, offset + 4);
            var triangleCount = ReadI32(bulkData, offset + 8);
            var totalTriangles = ReadI32(bulkData, offset + 12);
            if (totalVertices < 0 || triangleCount < 0 || totalTriangles < 0 ||
                totalTriangles + triangleCount > packedTriangleCount)
                throw new InvalidOperationException($"Invalid FF7 meshlet batch {batch}.");
            for (var triangle = 0; triangle < triangleCount; triangle++)
            {
                var packed = ReadU32(bulkData, packedTriangleOffset + (totalTriangles + triangle) * 4);
                var local0 = (int) (packed & 0x3ff);
                var local1 = (int) ((packed >> 10) & 0x3ff);
                var local2 = (int) ((packed >> 20) & 0x3ff);
                foreach (var local in new[] { local0, local1, local2 })
                {
                    var meshletIndex = totalVertices + local;
                    if (meshletIndex < 0 || meshletIndex >= meshletIndexCount)
                        throw new InvalidOperationException($"FF7 meshlet {batch} has an invalid local vertex index.");
                    var vertexIndex = ReadU32(bulkData, meshletIndexOffset + meshletIndex * 4);
                    if (vertexIndex >= vertexCount)
                        throw new InvalidOperationException($"FF7 meshlet {batch} references vertex {vertexIndex}/{vertexCount}.");
                    fullIndices.Add(vertexIndex);
                }
            }
        }
    }

    var selectedIndices = new List<uint>();
    var outputSections = new List<object?>();
    var staticMaterials = propertyReader.GetOrDefault<FStaticMaterial[]>("StaticMaterials", []);
    for (var sectionIndex = 0; sectionIndex < sourceSections.Length; sectionIndex++)
    {
        var sourceSection = sourceSections[sectionIndex];
        var firstIndex = selectedIndices.Count;
        var sourceFirstIndex = hasMeshlets
            ? checked(lodInfos[sectionLodIndices[sectionIndex]].BatchesOffset * 3)
            : checked((int) sourceSection.FirstIndex);
        var sourceTriangleCount = hasMeshlets
            ? lodInfos[sectionLodIndices[sectionIndex]].BatchesCount
            : checked((int) sourceSection.NumTriangles);
        var sourceIndexCount = checked(sourceTriangleCount * 3);
        if (sourceFirstIndex < 0 || sourceIndexCount < 0 ||
            sourceFirstIndex + sourceIndexCount > fullIndices.Count)
            throw new InvalidOperationException($"FF7 section {sectionIndex} index range is invalid.");
        selectedIndices.AddRange(fullIndices.GetRange(sourceFirstIndex, sourceIndexCount));

        var staticMaterial = sourceSection.MaterialIndex >= 0 && sourceSection.MaterialIndex < staticMaterials.Length
            ? staticMaterials[sourceSection.MaterialIndex]
            : null;
        outputSections.Add(new Dictionary<string, object?>
        {
            ["materialIndex"] = sourceSection.MaterialIndex,
            ["materialName"] = staticMaterial?.MaterialSlotName.ToString(),
            ["materialPath"] = staticMaterial?.MaterialInterface?.GetPathName(),
            ["firstIndex"] = firstIndex,
            ["triangleCount"] = sourceTriangleCount,
            ["castShadow"] = sourceSection.bCastShadow,
        });
    }

    // The flat payload contains vertices for every internal FF7 LOD. Remove
    // vertices unused by the selected conventional LOD so Blender gets no loose
    // geometry and the JSON remains compact.
    var usedVertices = selectedIndices.Distinct().OrderBy(index => index).ToArray();
    var remap = new Dictionary<uint, uint>(usedVertices.Length);
    for (var index = 0; index < usedVertices.Length; index++)
        remap[usedVertices[index]] = (uint) index;
    var remappedIndices = selectedIndices.Select(index => remap[index]).ToArray();
    var compactPositions = usedVertices.Select(index => positions[index]).ToArray();
    var compactNormals = usedVertices.Select(index => normals[index]).ToArray();
    var compactTangents = usedVertices.Select(index => tangents[index]).ToArray();
    var compactUvs = uvChannels.Select(channel =>
        usedVertices.Select(index => channel[index]).ToArray()).ToArray();
    // System.Text.Json serializes byte[] as base64 strings. Promote the four
    // channels so Blender receives the intended numeric RGBA arrays.
    var compactColors = colors is null
        ? null
        : usedVertices.Select(index =>
            colors[index].Select(component => (int) component).ToArray()).ToArray();

    return new Dictionary<string, object?>
    {
        ["sourceType"] = hasMeshlets
            ? "FF7 Rebirth flattened UStaticMesh"
            : "FF7 Rebirth legacy-indexed flattened UStaticMesh",
        ["name"] = meshName,
        ["renderData"] = hasMeshlets ? "FlattenedMeshlets" : "FlattenedLegacyIndices",
        ["lodIndex"] = 0,
        ["vertexCount"] = compactPositions.Length,
        ["triangleCount"] = remappedIndices.Length / 3,
        ["positions"] = compactPositions,
        ["normals"] = compactNormals,
        ["tangents"] = compactTangents,
        ["uvChannels"] = compactUvs,
        ["colors"] = compactColors,
        ["indices"] = remappedIndices,
        ["sections"] = outputSections,
    };
}

static Dictionary<string, object?> ExportRebirthStaticMesh(
    DefaultFileProvider provider,
    string assetPath,
    CUE4Parse.UE4.Assets.IoPackage package)
{
    try
    {
        return ExportRebirthFlattenedStaticMesh(provider, assetPath, package);
    }
    catch (Exception flattenedError)
    {
        // Before the flattened update, Rebirth used CUE4Parse's conventional
        // buffer layout (including the older 8-byte packed tangent frame).
        // Retain that route as a fallback so both generations remain usable.
        try
        {
            var sourceMesh = ((CUE4Parse.UE4.Assets.IPackage) package)
                .GetExports().OfType<UStaticMesh>().FirstOrDefault()
                ?? throw new InvalidOperationException("The package contains no UStaticMesh export.");
            return ExportStaticMeshAsset(sourceMesh);
        }
        catch (Exception conventionalError)
        {
            throw new InvalidOperationException(
                "StaticMesh could not be decoded as either Rebirth's updated flattened " +
                $"layout ({flattenedError.Message}) or its earlier conventional layout " +
                $"({conventionalError.Message}).",
                new AggregateException(flattenedError, conventionalError));
        }
    }
}

static bool TryDecodeRebirthSkeletalPackedFrames(
    DefaultFileProvider provider,
    string assetPath,
    IReadOnlyList<float[]> positions,
    float expectedFirstU,
    float expectedFirstV,
    out float[][] normals,
    out float[][] tangents)
{
    normals = [];
    tangents = [];
    if (positions.Count == 0)
        return false;
    var bulkData = provider.SavePackage(assetPath)
        .FirstOrDefault(entry => entry.Key.EndsWith(".ubulk", StringComparison.OrdinalIgnoreCase)).Value;
    if (bulkData is null || bulkData.Length == 0)
        return false;

    // The position stream starts at an arbitrary place in the bulk file. Find
    // two consecutive vertices instead of assuming offset zero, then verify
    // that the following 4-byte stream lands on the UV CUE4Parse already read.
    var prefixCount = Math.Min(2, positions.Count);
    var positionPrefix = new byte[prefixCount * 12];
    for (var vertexIndex = 0; vertexIndex < prefixCount; vertexIndex++)
    {
        for (var component = 0; component < 3; component++)
            BitConverter.GetBytes(positions[vertexIndex][component])
                .CopyTo(positionPrefix, vertexIndex * 12 + component * 4);
    }
    var positionOffset = -1;
    for (var offset = 0; offset <= bulkData.Length - positionPrefix.Length; offset++)
    {
        if (bulkData.AsSpan(offset, positionPrefix.Length).SequenceEqual(positionPrefix))
        {
            positionOffset = offset;
            break;
        }
    }
    if (positionOffset < 0)
        return false;
    var tangentOffset = checked(positionOffset + positions.Count * 12);
    var uvOffset = checked(tangentOffset + positions.Count * 4);
    if (uvOffset + 4 > bulkData.Length)
        return false;
    var packedFirstU = (float) BitConverter.UInt16BitsToHalf(
        BinaryPrimitives.ReadUInt16LittleEndian(bulkData.AsSpan(uvOffset, 2)));
    var packedFirstV = (float) BitConverter.UInt16BitsToHalf(
        BinaryPrimitives.ReadUInt16LittleEndian(bulkData.AsSpan(uvOffset + 2, 2)));
    if (MathF.Abs(packedFirstU - expectedFirstU) > 0.001f ||
        MathF.Abs(packedFirstV - expectedFirstV) > 0.001f)
        return false; // Earlier builds retain the conventional 8-byte frame.

    normals = new float[positions.Count][];
    tangents = new float[positions.Count][];
    for (var vertexIndex = 0; vertexIndex < positions.Count; vertexIndex++)
    {
        var packedFrame = BinaryPrimitives.ReadUInt32LittleEndian(
            bulkData.AsSpan(tangentOffset + vertexIndex * 4, 4));
        var u = (packedFrame & 1023) / 1023.0f;
        var v = ((packedFrame >> 10) & 1023) / 1023.0f;
        var nx = u - v;
        var ny = u + v - 1.0f;
        var nz = 1.0f - MathF.Abs(nx) - MathF.Abs(ny);
        if ((packedFrame & (1u << 30)) == 0)
            nz = -nz;
        var normalLength = MathF.Sqrt(nx * nx + ny * ny + nz * nz);
        if (normalLength <= float.Epsilon)
            return false;
        nx /= normalLength;
        ny /= normalLength;
        nz /= normalLength;
        normals[vertexIndex] = [nx, ny, nz];

        var sign = nz >= 0.0f ? -1.0f : 1.0f;
        var a = 1.0f / (nz - sign);
        var e1x = 1.0f + sign * nx * nx * a;
        var e1y = sign * nx * ny * a;
        var e1z = sign * nx;
        var e2x = nx * ny * a;
        var e2y = sign + ny * ny * a;
        var e2z = ny;
        var angle = (packedFrame >> 20) & 1023;
        var t = (angle & 255) / 255.0f;
        var cx = (angle & 256) != 0 ? t : -t;
        var cy = (angle & 512) != 0 ? 1.0f - t : -(1.0f - t);
        var circleLength = MathF.Sqrt(cx * cx + cy * cy);
        cx /= circleLength;
        cy /= circleLength;
        tangents[vertexIndex] =
        [
            e1x * cx + e2x * cy,
            e1y * cx + e2y * cy,
            e1z * cx + e2z * cy,
            (packedFrame & (1u << 31)) != 0 ? 1.0f : -1.0f,
        ];
    }
    return true;
}

static Dictionary<string, object?> ExportSkeletalMeshAsset(
    USkeletalMesh sourceMesh,
    CUE4Parse.UE4.Assets.IPackage package,
    string gameName,
    string contentRoot)
{
    var lods = sourceMesh.LODModels ?? [];
    var lodIndex = Array.FindIndex(lods, lod =>
        !lod.SkipLod &&
        (lod.VertexBufferGPUSkin.VertsFloat.Length > 0 || lod.VertexBufferGPUSkin.VertsHalf.Length > 0) &&
        lod.Indices?.Buffer is { Length: > 0 });
    if (lodIndex < 0)
        throw new InvalidOperationException("SkeletalMesh has no importable conventional LOD.");

    var sourceLod = lods[lodIndex];
    // FF7 Remake environment SkeletalMeshes commonly use half-precision UVs.
    // CUE4Parse stores those in VertsHalf rather than VertsFloat, despite both
    // being ordinary FSkelMeshVertexBase streams with the same position,
    // normal, influence, and decoded-UV surface needed by the exporter.
    dynamic[] vertices = (sourceLod.VertexBufferGPUSkin.VertsFloat.Length > 0
        ? sourceLod.VertexBufferGPUSkin.VertsFloat.Cast<dynamic>()
        : sourceLod.VertexBufferGPUSkin.VertsHalf.Cast<dynamic>()).ToArray();
    var indices = sourceLod.Indices!.Buffer!;
    var referenceBones = sourceMesh.ReferenceSkeleton.FinalRefBoneInfo;
    var vertexSections = Enumerable.Repeat(-1, vertices.Length).ToArray();
    for (var sectionIndex = 0; sectionIndex < sourceLod.Sections.Length; sectionIndex++)
    {
        var section = sourceLod.Sections[sectionIndex];
        var firstVertex = checked((int)section.BaseVertexIndex);
        var lastVertex = checked(firstVertex + section.NumVertices);
        if (firstVertex < 0 || lastVertex > vertices.Length)
            throw new InvalidOperationException($"SkeletalMesh section {sectionIndex} vertex range is invalid.");
        for (var vertexIndex = firstVertex; vertexIndex < lastVertex; vertexIndex++)
            vertexSections[vertexIndex] = sectionIndex;
    }
    if (vertexSections.Any(sectionIndex => sectionIndex < 0))
        throw new InvalidOperationException("SkeletalMesh has vertices outside all render sections.");

    // Conventional FF7 titles can reconstruct the GPU vertex buffer from the
    // legacy render-item streams.  That reconstruction sets the LOD's UV count
    // but does not copy it onto VertexBufferGPUSkin.NumTexCoords, even though
    // each FGPUVertFloat still contains its UV array.  Prefer the LOD metadata,
    // validate it against the decoded vertices, and fall back to that decoded
    // stream when the metadata is absent.
    var encodedUvChannelCount = vertices.Min(vertex => vertex.UV.Length);
    var declaredUvChannelCount = Math.Max(
        sourceLod.NumTexCoords,
        sourceLod.VertexBufferGPUSkin.NumTexCoords);
    var uvChannelCount = declaredUvChannelCount is > 0 and <= 8 &&
        declaredUvChannelCount <= encodedUvChannelCount
        ? declaredUvChannelCount
        : encodedUvChannelCount;
    var uvChannels = new List<object?>();
    for (var channelIndex = 0; channelIndex < uvChannelCount; channelIndex++)
    {
        var capturedChannel = channelIndex;
        uvChannels.Add(vertices.Select(vertex =>
        {
            var uv = vertex.UV[capturedChannel];
            return new[] { uv.U, uv.V };
        }).ToArray());
    }

    var weights = new List<object?>(vertices.Length);
    for (var vertexIndex = 0; vertexIndex < vertices.Length; vertexIndex++)
    {
        var influence = vertices[vertexIndex].Infs;
        var section = sourceLod.Sections[vertexSections[vertexIndex]];
        var vertexWeights = new List<object?>();
        if (influence is not null)
        {
            var divisor = influence.bUse16BitBoneWeight ? 65535.0f : 255.0f;
            for (var influenceIndex = 0; influenceIndex < influence.BoneIndex.Length; influenceIndex++)
            {
                var weight = influence.BoneWeight[influenceIndex];
                if (weight == 0)
                    continue;
                var localBoneIndex = influence.BoneIndex[influenceIndex];
                if (localBoneIndex >= section.BoneMap.Length)
                    throw new InvalidOperationException(
                        $"SkeletalMesh vertex {vertexIndex} has an invalid section-local bone index.");
                var skeletonBoneIndex = section.BoneMap[localBoneIndex];
                if (skeletonBoneIndex >= referenceBones.Length)
                    throw new InvalidOperationException(
                        $"SkeletalMesh vertex {vertexIndex} references an invalid skeleton bone.");
                vertexWeights.Add(new[] { (float)skeletonBoneIndex, weight / divisor });
            }
        }
        weights.Add(vertexWeights);
    }

    var materials = sourceMesh.SkeletalMaterials;
    var sections = sourceLod.Sections.Select(section =>
    {
        var material = section.MaterialIndex >= 0 && section.MaterialIndex < materials.Length
            ? materials[section.MaterialIndex]
            : null;
        var materialPath = material?.Material?.GetPathName();
        return (object?)new Dictionary<string, object?>
        {
            ["materialIndex"] = section.MaterialIndex,
            ["materialName"] = MaterialNameFromSlotOrPath(material?.MaterialSlotName.Text, materialPath),
            ["materialPath"] = materialPath,
            ["firstIndex"] = section.BaseIndex,
            ["triangleCount"] = section.NumTriangles,
            ["castShadow"] = section.bCastShadow,
            ["recomputeTangents"] = section.bRecomputeTangent,
            ["recomputeTangentMaskChannel"] = section.RecomputeTangentsVertexMaskChannel.ToString(),
        };
    }).ToList();

    var colors = sourceLod.ColorVertexBuffer.Data;
    if (colors.Length != 0 && colors.Length != vertices.Length)
        throw new InvalidOperationException("SkeletalMesh color stream does not match its vertex stream.");
    var linkedSkeletonPath = GetLinkedSkeletonPath(sourceMesh);
    return new Dictionary<string, object?>
    {
        ["sourceType"] = $"{gameName} USkeletalMesh",
        ["name"] = sourceMesh.Name.ToString(),
        ["lodIndex"] = lodIndex,
        ["vertexCount"] = vertices.Length,
        ["triangleCount"] = indices.Length / 3,
        ["positions"] = vertices.Select(vertex =>
            new[] { vertex.Pos.X, vertex.Pos.Y, vertex.Pos.Z }).ToArray(),
        ["normals"] = vertices.Select(vertex =>
            new[] { vertex.Normal[2].X, vertex.Normal[2].Y, vertex.Normal[2].Z }).ToArray(),
        ["tangents"] = vertices.Select(vertex =>
            new[] { vertex.Normal[0].X, vertex.Normal[0].Y, vertex.Normal[0].Z, vertex.Normal[2].W }).ToArray(),
        ["normalFormat"] = "legacy FPackedNormal frame",
        ["uvChannels"] = uvChannels,
        ["colors"] = colors.Length == 0 ? null : colors.Select(color =>
            new[] { (int)color.R, (int)color.G, (int)color.B, (int)color.A }).ToArray(),
        ["indices"] = indices,
        ["sections"] = sections,
        ["boneNames"] = referenceBones.Select(bone => bone.Name.ToString()).ToArray(),
        ["weights"] = weights,
        // Some Crisis Core meshes resolve a Skeleton object path that is not
        // exposed as an independently loadable mounted package.  Preserve the
        // mesh's own bind-pose reference skeleton so Blender can still build
        // and bind an armature without that secondary package request.
        ["inlineSkeleton"] = ExportReferenceSkeleton(sourceMesh.ReferenceSkeleton),
        ["linkedSkeletonPath"] = linkedSkeletonPath,
        ["skeletonPath"] = ObjectPathToVirtualAssetPath(linkedSkeletonPath, contentRoot),
        ["kdiPaths"] = ExportKineDriverAssetPaths(package, contentRoot),
    };
}

static Dictionary<string, object?> ExportRebirthSkeletalMesh(
    DefaultFileProvider provider,
    string assetPath,
    CUE4Parse.UE4.Assets.IPackage package)
{
    var sourceMesh = package.GetExports().OfType<USkeletalMesh>().FirstOrDefault()
        ?? throw new InvalidOperationException("Package does not contain a SkeletalMesh export.");
    var lods = sourceMesh.LODModels ?? [];
    var lodIndex = Array.FindIndex(lods, lod =>
        !lod.SkipLod && lod.VertexBufferGPUSkin.VertsFloat.Length > 0 &&
        lod.Indices?.Buffer is { Length: > 0 });
    if (lodIndex < 0)
    {
        if (package is CUE4Parse.UE4.Assets.IoPackage ioPackage)
            return ExportRebirthInlineSkeletalMesh(provider, assetPath, ioPackage, sourceMesh);
        throw new InvalidOperationException("SkeletalMesh has no importable Rebirth LOD.");
    }

    var sourceLod = lods[lodIndex];
    var vertices = sourceLod.VertexBufferGPUSkin.VertsFloat;
    var indices = sourceLod.Indices!.Buffer!;
    var positions = vertices.Select(vertex =>
        new[] { vertex.Pos.X, vertex.Pos.Y, vertex.Pos.Z }).ToArray();
    var hasPackedFrames = TryDecodeRebirthSkeletalPackedFrames(
        provider,
        assetPath,
        positions,
        vertices[0].UV[0].U,
        vertices[0].UV[0].V,
        out var packedNormals,
        out var packedTangents);
    var referenceBones = sourceMesh.ReferenceSkeleton.FinalRefBoneInfo;
    var vertexSections = Enumerable.Repeat(-1, vertices.Length).ToArray();
    for (var sectionIndex = 0; sectionIndex < sourceLod.Sections.Length; sectionIndex++)
    {
        var section = sourceLod.Sections[sectionIndex];
        var firstVertex = checked((int)section.BaseVertexIndex);
        var lastVertex = checked(firstVertex + section.NumVertices);
        if (firstVertex < 0 || lastVertex > vertices.Length)
            throw new InvalidOperationException($"SkeletalMesh section {sectionIndex} vertex range is invalid.");
        for (var vertexIndex = firstVertex; vertexIndex < lastVertex; vertexIndex++)
            vertexSections[vertexIndex] = sectionIndex;
    }
    if (vertexSections.Any(sectionIndex => sectionIndex < 0))
        throw new InvalidOperationException("SkeletalMesh has vertices outside all render sections.");
    var uvChannelCount = sourceLod.VertexBufferGPUSkin.NumTexCoords;
    var uvChannels = new List<object?>();
    for (var channelIndex = 0; channelIndex < uvChannelCount; channelIndex++)
    {
        var capturedChannel = channelIndex;
        uvChannels.Add(vertices.Select(vertex =>
        {
            var uv = vertex.UV[capturedChannel];
            return new[] { uv.U, uv.V };
        }).ToArray());
    }

    var weights = new List<object?>(vertices.Length);
    for (var vertexIndex = 0; vertexIndex < vertices.Length; vertexIndex++)
    {
        var influence = vertices[vertexIndex].Infs;
        var section = sourceLod.Sections[vertexSections[vertexIndex]];
        var vertexWeights = new List<object?>();
        if (influence is not null)
        {
            var divisor = influence.bUse16BitBoneWeight ? 65535.0f : 255.0f;
            for (var influenceIndex = 0; influenceIndex < influence.BoneIndex.Length; influenceIndex++)
            {
                var weight = influence.BoneWeight[influenceIndex];
                if (weight == 0)
                    continue;
                var localBoneIndex = influence.BoneIndex[influenceIndex];
                if (localBoneIndex >= section.BoneMap.Length)
                    throw new InvalidOperationException(
                        $"SkeletalMesh vertex {vertexIndex} has an invalid section-local bone index.");
                var skeletonBoneIndex = section.BoneMap[localBoneIndex];
                if (skeletonBoneIndex >= referenceBones.Length)
                    throw new InvalidOperationException(
                        $"SkeletalMesh vertex {vertexIndex} references an invalid skeleton bone.");
                vertexWeights.Add(new[] { (float)skeletonBoneIndex, weight / divisor });
            }
        }
        weights.Add(vertexWeights);
    }

    var materials = sourceMesh.SkeletalMaterials;
    var sections = sourceLod.Sections.Select(section =>
    {
        var material = section.MaterialIndex >= 0 && section.MaterialIndex < materials.Length
            ? materials[section.MaterialIndex]
            : null;
        return (object?)new Dictionary<string, object?>
        {
            ["materialIndex"] = section.MaterialIndex,
            ["materialName"] = material?.MaterialSlotName.ToString(),
            ["materialPath"] = material?.Material?.GetPathName(),
            ["firstIndex"] = section.BaseIndex,
            ["triangleCount"] = section.NumTriangles,
            ["castShadow"] = section.bCastShadow,
            ["recomputeTangents"] = section.bRecomputeTangent,
            ["recomputeTangentMaskChannel"] = section.RecomputeTangentsVertexMaskChannel.ToString(),
        };
    }).ToList();

    var colors = sourceLod.ColorVertexBuffer.Data;
    var colorStreamSource = "CUE4Parse";
    var declaredColorCount = colors.Length;
    var colorStreamOffset = -1;
    var colorStreamBulkBytes = 0;
    // Rebirth records its color stream in the cooked LOD metadata even when
    // LODInfo.bHasPerLODVertexColors is absent.  CUE4Parse uses that property
    // as a gate and consequently leaves ColorVertexBuffer empty for assets
    // such as PC0000_00.  Recover the explicitly declared stream instead of
    // treating the optional property as authoritative.
    if (colors.Length == 0 && package is CUE4Parse.UE4.Assets.IoPackage colorIoPackage &&
        TryReadRebirthSkeletalColorStream(provider, assetPath, colorIoPackage, vertices.Length,
            out var recoveredColorStream))
    {
        colors = recoveredColorStream.Colors;
        colorStreamSource = "Rebirth cooked LOD metadata";
        declaredColorCount = recoveredColorStream.DeclaredCount;
        colorStreamOffset = recoveredColorStream.Offset;
        colorStreamBulkBytes = recoveredColorStream.BulkByteLength;
    }
    if (colors.Length != 0 && colors.Length != vertices.Length)
        throw new InvalidOperationException("SkeletalMesh color stream does not match its vertex stream.");
    return new Dictionary<string, object?>
    {
        ["sourceType"] = "FF7 Rebirth USkeletalMesh",
        ["name"] = sourceMesh.Name.ToString(),
        ["lodIndex"] = lodIndex,
        ["vertexCount"] = vertices.Length,
        ["triangleCount"] = indices.Length / 3,
        ["positions"] = positions,
        ["normals"] = hasPackedFrames ? packedNormals : vertices.Select(vertex =>
            new[] { vertex.Normal[2].X, vertex.Normal[2].Y, vertex.Normal[2].Z }).ToArray(),
        ["tangents"] = hasPackedFrames ? packedTangents : vertices.Select(vertex =>
            new[] { vertex.Normal[0].X, vertex.Normal[0].Y, vertex.Normal[0].Z, vertex.Normal[2].W }).ToArray(),
        ["normalFormat"] = hasPackedFrames ? "R10G10B10A2 packed tangent frame" : "legacy FPackedNormal frame",
        ["uvChannels"] = uvChannels,
        ["colors"] = colors.Length == 0 ? null : colors.Select(color =>
            new[] { (int)color.R, (int)color.G, (int)color.B, (int)color.A }).ToArray(),
        ["colorStream"] = new Dictionary<string, object?>
        {
            ["source"] = colorStreamSource,
            ["declaredVertexCount"] = declaredColorCount,
            ["decodedVertexCount"] = colors.Length,
            ["meshVertexCount"] = vertices.Length,
            ["coverage"] = vertices.Length == 0 ? 0.0 : (double)colors.Length / vertices.Length,
            ["offset"] = colorStreamOffset,
            ["bulkByteLength"] = colorStreamBulkBytes,
        },
        ["indices"] = indices,
        ["sections"] = sections,
        ["boneNames"] = referenceBones.Select(bone => bone.Name.ToString()).ToArray(),
        ["weights"] = weights,
        ["linkedSkeletonPath"] = GetLinkedSkeletonPath(sourceMesh),
        ["skeletonPath"] = ObjectPathToVirtualAssetPath(GetLinkedSkeletonPath(sourceMesh)),
        ["kdiPaths"] = ExportKineDriverAssetPaths(package),
    };
}

static Dictionary<string, object?> ExportRebirthInlineSkeletalMesh(
    DefaultFileProvider provider,
    string assetPath,
    CUE4Parse.UE4.Assets.IoPackage package,
    USkeletalMesh sourceMesh)
{
    var usage = ReadRebirthMeshUsage(provider, assetPath, package);
    var payload = usage.Reader.InlineLod
        ?? throw new InvalidOperationException("SkeletalMesh has no supported inline Rebirth LOD.");
    var sourceLod = usage.Reader.Lods.FirstOrDefault()
        ?? throw new InvalidOperationException("SkeletalMesh has no inline render-section data.");
    var vertices = payload.Positions;
    var indices = payload.Indices;
    if (vertices.Length == 0 || indices.Length == 0)
        throw new InvalidOperationException("SkeletalMesh inline payload has no render geometry.");
    if (payload.PackedFrames.Length != vertices.Length || payload.Weights.Length != vertices.Length)
        throw new InvalidOperationException("SkeletalMesh inline vertex streams have inconsistent lengths.");

    var vertexSections = Enumerable.Repeat(-1, vertices.Length).ToArray();
    for (var sectionIndex = 0; sectionIndex < sourceLod.Sections.Length; sectionIndex++)
    {
        var section = sourceLod.Sections[sectionIndex];
        var firstVertex = checked((int)section.BaseVertexIndex);
        var lastVertex = checked(firstVertex + section.NumVertices);
        if (firstVertex < 0 || lastVertex > vertices.Length)
            throw new InvalidOperationException($"SkeletalMesh section {sectionIndex} vertex range is invalid.");
        for (var vertexIndex = firstVertex; vertexIndex < lastVertex; vertexIndex++)
            vertexSections[vertexIndex] = sectionIndex;
    }
    if (vertexSections.Any(sectionIndex => sectionIndex < 0) || indices.Any(index => index >= vertices.Length))
        throw new InvalidOperationException("SkeletalMesh inline geometry has invalid vertex references.");

    var requiredIndexCount = sourceLod.Sections.Length == 0 ? indices.Length : sourceLod.Sections.Max(section =>
        checked((int)section.BaseIndex + section.NumTriangles * 3));
    if (requiredIndexCount <= 0 || requiredIndexCount > indices.Length)
        throw new InvalidOperationException("SkeletalMesh inline section index ranges are invalid.");

    var normals = new float[vertices.Length][];
    var tangents = new float[vertices.Length][];
    for (var vertexIndex = 0; vertexIndex < vertices.Length; vertexIndex++)
        DecodeRebirthPackedFrame(payload.PackedFrames[vertexIndex], out normals[vertexIndex], out tangents[vertexIndex]);

    var referenceBones = usage.Reader.ReferenceSkeleton.FinalRefBoneInfo;
    var weights = new List<object?>(vertices.Length);
    for (var vertexIndex = 0; vertexIndex < vertices.Length; vertexIndex++)
    {
        var influence = payload.Weights[vertexIndex];
        var section = sourceLod.Sections[vertexSections[vertexIndex]];
        var divisor = influence.bUse16BitBoneWeight ? 65535.0f : 255.0f;
        var vertexWeights = new List<object?>();
        for (var influenceIndex = 0; influenceIndex < influence.BoneIndex.Length; influenceIndex++)
        {
            var weight = influence.BoneWeight[influenceIndex];
            if (weight == 0)
                continue;
            var localBoneIndex = influence.BoneIndex[influenceIndex];
            if (localBoneIndex >= section.BoneMap.Length)
                throw new InvalidOperationException($"SkeletalMesh vertex {vertexIndex} has an invalid section-local bone index.");
            var skeletonBoneIndex = section.BoneMap[localBoneIndex];
            if (skeletonBoneIndex >= referenceBones.Length)
                throw new InvalidOperationException($"SkeletalMesh vertex {vertexIndex} references an invalid skeleton bone.");
            vertexWeights.Add(new[] { (float)skeletonBoneIndex, weight / divisor });
        }
        weights.Add(vertexWeights);
    }

    var materials = sourceMesh.SkeletalMaterials;
    var sections = sourceLod.Sections.Select(section =>
    {
        var material = section.MaterialIndex >= 0 && section.MaterialIndex < materials.Length
            ? materials[section.MaterialIndex]
            : null;
        return (object?)new Dictionary<string, object?>
        {
            ["materialIndex"] = section.MaterialIndex,
            ["materialName"] = material?.MaterialSlotName.ToString(),
            ["materialPath"] = material?.Material?.GetPathName(),
            ["firstIndex"] = section.BaseIndex,
            ["triangleCount"] = section.NumTriangles,
            ["castShadow"] = section.bCastShadow,
        };
    }).ToList();

    return new Dictionary<string, object?>
    {
        ["sourceType"] = "FF7 Rebirth inline USkeletalMesh",
        ["name"] = sourceMesh.Name.ToString(),
        ["lodIndex"] = 0,
        ["vertexCount"] = vertices.Length,
        ["triangleCount"] = requiredIndexCount / 3,
        ["positions"] = vertices.Select(vertex => new[] { vertex.X, vertex.Y, vertex.Z }).ToArray(),
        ["normals"] = normals,
        ["tangents"] = tangents,
        ["normalFormat"] = "R10G10B10A2 packed tangent frame",
        ["uvChannels"] = payload.UvChannels,
        ["colors"] = payload.Colors.Length == 0 ? null : payload.Colors.Select(color =>
            new[] { (int)color.R, (int)color.G, (int)color.B, (int)color.A }).ToArray(),
        ["indices"] = indices.Take(requiredIndexCount).ToArray(),
        ["sections"] = sections,
        ["boneNames"] = referenceBones.Select(bone => bone.Name.ToString()).ToArray(),
        ["weights"] = weights,
        ["linkedSkeletonPath"] = GetLinkedSkeletonPath(sourceMesh),
        ["skeletonPath"] = ObjectPathToVirtualAssetPath(GetLinkedSkeletonPath(sourceMesh)),
        ["kdiPaths"] = ExportKineDriverAssetPaths(package),
    };
}

static void DecodeRebirthPackedFrame(uint packedFrame, out float[] normal, out float[] tangent)
{
    var u = (packedFrame & 1023) / 1023.0f;
    var v = ((packedFrame >> 10) & 1023) / 1023.0f;
    var nx = u - v;
    var ny = u + v - 1.0f;
    var nz = 1.0f - MathF.Abs(nx) - MathF.Abs(ny);
    if ((packedFrame & (1u << 30)) == 0)
        nz = -nz;
    var normalLength = MathF.Sqrt(nx * nx + ny * ny + nz * nz);
    if (normalLength <= float.Epsilon)
        throw new InvalidOperationException("SkeletalMesh inline payload contains a degenerate tangent frame.");
    nx /= normalLength;
    ny /= normalLength;
    nz /= normalLength;
    normal = [nx, ny, nz];

    var sign = nz >= 0.0f ? -1.0f : 1.0f;
    var a = 1.0f / (nz - sign);
    var e1x = 1.0f + sign * nx * nx * a;
    var e1y = sign * nx * ny * a;
    var e1z = sign * nx;
    var e2x = nx * ny * a;
    var e2y = sign + ny * ny * a;
    var e2z = ny;
    var angle = (packedFrame >> 20) & 1023;
    var t = (angle & 255) / 255.0f;
    var cx = (angle & 256) != 0 ? t : -t;
    var cy = (angle & 512) != 0 ? 1.0f - t : -(1.0f - t);
    var circleLength = MathF.Sqrt(cx * cx + cy * cy);
    if (circleLength <= float.Epsilon)
        throw new InvalidOperationException("SkeletalMesh inline payload contains a degenerate tangent direction.");
    cx /= circleLength;
    cy /= circleLength;
    tangent =
    [
        e1x * cx + e2x * cy,
        e1y * cx + e2y * cy,
        e1z * cx + e2z * cy,
        (packedFrame & (1u << 31)) != 0 ? 1.0f : -1.0f,
    ];
}

static Dictionary<string, object?> ExportKdiAsset(CUE4Parse.UE4.Assets.IPackage package)
{
    var export = package.GetExports().FirstOrDefault()
        ?? throw new InvalidOperationException("KDI package has no exports.");
    var properties = new Dictionary<string, object?>();
    foreach (var property in export.Properties)
    {
        if (ConvertValue(property) is not Dictionary<string, object?> converted)
            continue;
        if (!converted.TryGetValue("name", out var name) || name is null)
            continue;
        properties[name.ToString()!] = converted.TryGetValue("value", out var value)
            ? NormalizeKdiValue(value)
            : null;
    }
    return new Dictionary<string, object?>
    {
        ["Type"] = export.ExportType,
        ["Name"] = export.Name.ToString(),
        ["Class"] = $"UScriptClass'{export.ExportType}'",
        ["Package"] = package.Name,
        ["Properties"] = properties
    };
}

// Walk a component's Template chain looking for the first non-null value of
// any of the given properties. Blueprint-derived component instances often
// omit their asset reference from their own serialized properties; the value
// instead lives on some ancestor in the Template chain -- typically the
// Blueprint's class-default-object subobject (e.g. a Gimmick prop's chair
// mesh, which fmodel shows serialized on Default__BG2202_00_Chair_Standard_C's
// own "SkeletalMeshComponent0", never on the level-placed instance).
//
// This walks plain UObject rather than a specific component subclass
// (compare the typed UStaticMeshComponent.GetStaticMesh() usage below) because
// this game's custom component classes (e.g. "EndSkeletalMeshComponent") do
// not reliably construct as their matching native CUE4Parse type, which made
// a typed Template-walk helper silently miss these values.
static FPackageIndex? ResolveInheritedComponentProperty(
    CUE4Parse.UE4.Assets.Exports.UObject component,
    params string[] propertyNames)
{
    var visited = new HashSet<CUE4Parse.UE4.Assets.Exports.UObject>();
    var current = component;
    while (current != null && visited.Add(current))
    {
        foreach (var propertyName in propertyNames)
        {
            var value = current.GetOrDefault<FPackageIndex>(propertyName, new FPackageIndex());
            if (!value.IsNull)
                return value;
        }
        current = current.Template?.Load();
    }
    return null;
}

static Dictionary<string, object?> ExportUmapActors(CUE4Parse.UE4.Assets.IPackage package)
{
    var supportedTypes = new HashSet<string>(StringComparer.Ordinal)
    {
        "EndEnvironmentStaticMeshComponent",
        "StaticMeshComponent",
        "EndStaticMeshPhysicsPartsComponent",
        "EndSkeletalMeshComponent",
        "SkeletalMeshComponent",
        "PointLightComponent",
        "SpotLightComponent",
        "BoxReflectionCaptureComponent",
        "MaterialParameterLightPlacedComponent",
        "MaterialInstanceDynamic",
        "LevelStreamingAlwaysLoaded",
        "LevelStreamingDynamic",
        "EndStreamingVolume",
    };
    var actors = new List<object?>();
    foreach (var export in package.GetExports().Where(export => supportedTypes.Contains(export.ExportType)))
    {
        var properties = new Dictionary<string, object?>();
        foreach (var property in export.Properties)
        {
            try
            {
                if (ConvertValue(property) is not Dictionary<string, object?> converted ||
                    !converted.TryGetValue("name", out var name) || name is null)
                    continue;
                properties[name.ToString()!] = converted.TryGetValue("value", out var value)
                    ? NormalizeKdiValue(value)
                    : null;
            }
            catch (Exception exc)
            {
                // A malformed/unmapped property must not discard the MovieScene
                // export that contains the rest of the sequence's usable data.
                Console.Error.WriteLine($"Cutscene property skipped ({export.Name}): {exc.Message}");
            }
        }

        // Blueprint-derived component instances commonly omit StaticMesh from
        // their own serialized properties. UStaticMeshComponent resolves that
        // inherited value through its Template chain, so expose the resolved
        // package reference in the same shape as an explicit property.
        if (export is UStaticMeshComponent staticMeshComponent &&
            !properties.ContainsKey("StaticMesh"))
        {
            var staticMesh = staticMeshComponent.GetStaticMesh();
            if (!staticMesh.IsNull)
                properties["StaticMesh"] = ConvertValue(staticMesh);
        }

        // EndSkeletalMeshComponent instances have the same template-inheritance
        // behavior. Export the resolved asset reference so Blender can build the
        // mesh-and-armature source collection instead of creating an empty.
        if ((export.ExportType == "EndSkeletalMeshComponent" ||
             export.ExportType == "SkeletalMeshComponent") &&
            !properties.ContainsKey("SkeletalMesh") &&
            !properties.ContainsKey("SkinnedAsset"))
        {
            var skeletalMesh = ResolveInheritedComponentProperty(export, "SkeletalMesh", "SkinnedAsset");
            if (skeletalMesh != null)
                properties["SkeletalMesh"] = ConvertValue(skeletalMesh);
        }

        // Preserve full ownership paths so dynamic material overrides can be
        // associated with their mesh component and its attached lights.
        var actor = new Dictionary<string, object?>
        {
            ["Type"] = export.ExportType,
            ["Name"] = export.Name.ToString(),
            ["Outer"] = export.Outer is null ? null : new Dictionary<string, object?>
            {
                ["ObjectName"] = $"Object'{export.Outer.GetPathName()}'",
                ["ObjectPath"] = export.Outer.GetPathName(),
            },
            ["Properties"] = properties,
        };
        if (export is CUE4Parse.UE4.Assets.Exports.Component.Lights.ULightComponentBase light)
        {
            properties.TryAdd("Intensity", light.Intensity);
            actor["IntensityNits"] = light.GetNitIntensity();
        }
        actors.Add(actor);
    }
    return new Dictionary<string, object?>
    {
        ["sourceType"] = "UMAP package actor export",
        ["actorCount"] = actors.Count,
        ["actors"] = actors,
    };
}

static Dictionary<string, object?> ExportStreamingProbe(CUE4Parse.UE4.Assets.IPackage package)
{
    static float[] Vector3(FVector value) => [value.X, value.Y, value.Z];
    static (FVector Min, FVector Max)? TransformBounds(UBrushComponent? component, FBoxSphereBounds? bounds)
    {
        if (component is null || bounds is null)
            return null;
        var localMin = bounds.Origin - bounds.BoxExtent;
        var localMax = bounds.Origin + bounds.BoxExtent;
        var transform = component.GetComponentTransform();
        var transformed = new[]
        {
            transform.TransformPosition(new FVector(localMin.X, localMin.Y, localMin.Z)),
            transform.TransformPosition(new FVector(localMin.X, localMin.Y, localMax.Z)),
            transform.TransformPosition(new FVector(localMin.X, localMax.Y, localMin.Z)),
            transform.TransformPosition(new FVector(localMin.X, localMax.Y, localMax.Z)),
            transform.TransformPosition(new FVector(localMax.X, localMin.Y, localMin.Z)),
            transform.TransformPosition(new FVector(localMax.X, localMin.Y, localMax.Z)),
            transform.TransformPosition(new FVector(localMax.X, localMax.Y, localMin.Z)),
            transform.TransformPosition(new FVector(localMax.X, localMax.Y, localMax.Z)),
        };
        return (
            new FVector(transformed.Min(point => point.X), transformed.Min(point => point.Y), transformed.Min(point => point.Z)),
            new FVector(transformed.Max(point => point.X), transformed.Max(point => point.Y), transformed.Max(point => point.Z))
        );
    }

    var exports = package.GetExports().ToArray();
    var records = new List<object?>();
    foreach (var volume in exports.Where(export => export.ExportType == "EndStreamingVolume"))
    {
        var properties = new Dictionary<string, object?>();
        foreach (var property in volume.Properties)
        {
            if (ConvertValue(property) is not Dictionary<string, object?> converted ||
                !converted.TryGetValue("name", out var name) || name is null)
                continue;
            properties[name.ToString()!] = converted.TryGetValue("value", out var value) ? value : null;
        }

        var brushIndex = volume.GetOrDefault<FPackageIndex>("BrushComponent", new FPackageIndex());
        var brushComponent = brushIndex.Load<UBrushComponent>();
        var model = brushComponent?.GetBrush();
        var bounds = model?.Bounds;
        var worldBounds = TransformBounds(brushComponent, bounds);
        records.Add(new Dictionary<string, object?>
        {
            ["name"] = volume.Name.ToString(),
            ["properties"] = properties,
            ["brushComponent"] = brushComponent?.GetPathName(),
            ["brushModel"] = model?.GetPathName(),
            ["brushRelativeLocation"] = brushComponent is null ? null : Vector3(brushComponent.GetRelativeLocation()),
            ["boundsOrigin"] = bounds is null ? null : Vector3(bounds.Origin),
            ["boundsExtent"] = bounds is null ? null : Vector3(bounds.BoxExtent),
            ["boundsMin"] = bounds is null ? null : Vector3(bounds.Origin - bounds.BoxExtent),
            ["boundsMax"] = bounds is null ? null : Vector3(bounds.Origin + bounds.BoxExtent),
            ["boundsWorldMin"] = worldBounds is null ? null : Vector3(worldBounds.Value.Min),
            ["boundsWorldMax"] = worldBounds is null ? null : Vector3(worldBounds.Value.Max),
            ["pointCount"] = model?.Points?.Length ?? 0,
        });
    }

    var grids = exports
        .Where(export => export.ExportType == "EndStreamingGrid")
        .Select(export => new Dictionary<string, object?>
        {
            ["name"] = export.Name.ToString(),
            ["properties"] = export.Properties
                .Select(ConvertValue)
                .OfType<Dictionary<string, object?>>()
                .ToArray(),
        })
        .ToArray();
    return new Dictionary<string, object?>
    {
        ["package"] = package.Name,
        ["streamingVolumes"] = records,
        ["streamingGrids"] = grids,
    };
}

static object? RewriteCutsceneObjectPaths(
    object? value,
    IReadOnlyDictionary<string, int> exportIndices)
{
    if (value is Dictionary<string, object?> dictionary)
    {
        var rewritten = new Dictionary<string, object?>();
        foreach (var (key, item) in dictionary)
        {
            if (key == "ObjectPath" && item is string objectPath &&
                exportIndices.TryGetValue(objectPath, out var exportIndex))
            {
                // The established cutscene importer addresses its flat export
                // list using the final numeric ObjectPath segment from FModel.
                rewritten[key] = $"Package.{exportIndex}";
            }
            else
            {
                rewritten[key] = RewriteCutsceneObjectPaths(item, exportIndices);
            }
        }
        return rewritten;
    }
    if (value is List<object?> list)
        return list.Select(item => RewriteCutsceneObjectPaths(item, exportIndices)).ToList();
    return value;
}

static (string ExportType, string Name) GetCutsceneExportMetadata(
    CUE4Parse.UE4.Assets.IPackage package,
    int index)
{
    if (package is CUE4Parse.UE4.Assets.IoPackage ioPackage)
    {
        var entry = ioPackage.ExportMap[index];
        var exportType = ioPackage.ResolveObjectIndex(entry.ClassIndex)?.Name.ToString()
            ?? string.Empty;
        var name = ioPackage.CreateFNameFromMappedName(entry.ObjectName).ToString();
        return (exportType, name);
    }
    if (package is CUE4Parse.UE4.Assets.Package legacyPackage)
    {
        var entry = legacyPackage.ExportMap[index];
        return (entry.ClassName ?? string.Empty, entry.ObjectName.ToString());
    }

    var export = package.GetExport(index);
    return (export.ExportType, export.Name.ToString());
}

static bool TryReadSerializedString(byte[] data, ref int offset, out string value)
{
    value = string.Empty;
    if (offset < 0 || offset + 4 > data.Length)
        return false;
    var length = BitConverter.ToInt32(data, offset);
    offset += 4;
    if (length <= 1 || offset + length > data.Length || data[offset + length - 1] != 0)
        return false;
    value = System.Text.Encoding.ASCII.GetString(data, offset, length - 1);
    offset += length;
    return value.All(character => character is >= ' ' and <= '~');
}

static bool TryReadAttachmentPayload(byte[] data, int start, out (string Actor, string Parent, string Socket, bool Detach) attachment)
{
    attachment = default;
    var offset = start;
    bool ReadName(string prefix, out string name)
    {
        name = string.Empty;
        return TryReadSerializedString(data, ref offset, out var field) && field.StartsWith(prefix, StringComparison.Ordinal) &&
            TryReadSerializedString(data, ref offset, out var type) && type == "NameProperty" &&
            offset + 9 <= data.Length && (offset += 9) >= 0 &&
            TryReadSerializedString(data, ref offset, out name);
    }
    if (!ReadName("ActorName_", out var actor) || !ReadName("ParentName_", out var parent) ||
        !ReadName("SocketName_", out var socket) ||
        !TryReadSerializedString(data, ref offset, out var detachField) || !detachField.StartsWith("Detach_", StringComparison.Ordinal) ||
        !TryReadSerializedString(data, ref offset, out var detachType) || detachType != "BoolProperty" || offset + 9 > data.Length)
        return false;
    // BoolProperty stores its value after size and array index, before the GUID flag.
    attachment = (actor, parent, socket, data[offset + 8] != 0);
    return actor.StartsWith("EV_", StringComparison.Ordinal) && parent.StartsWith("EV_", StringComparison.Ordinal);
}

static List<Dictionary<string, object?>> DecodeConstraintAttachments(byte[]? rawData, List<object?> exports)
{
    var attachments = new List<Dictionary<string, object?>>();
    if (rawData is null)
        return attachments;
    var seen = new HashSet<string>(StringComparer.Ordinal);
    for (var index = 4; index < rawData.Length; index++)
    {
        if (!rawData.AsSpan(index).StartsWith("ActorName_"u8) ||
            !TryReadAttachmentPayload(rawData, index - 4, out var item))
            continue;
        var key = $"{item.Actor}\u001f{item.Parent}\u001f{item.Socket}\u001f{item.Detach}";
        if (!seen.Add(key))
            continue;
        attachments.Add(new Dictionary<string, object?>
        {
            ["actor"] = item.Actor,
            ["parent"] = item.Parent,
            ["socket"] = item.Socket,
            ["detach"] = item.Detach,
        });
    }
    var times = exports.OfType<Dictionary<string, object?>>()
        .Where(export => export.GetValueOrDefault("Type") as string == "MovieSceneEndEventSection")
        .SelectMany(export => ((export.GetValueOrDefault("Properties") as Dictionary<string, object?>)?.GetValueOrDefault("EventData") as Dictionary<string, object?>)?.GetValueOrDefault("Times") as List<object?> ?? [])
        .OfType<Dictionary<string, object?>>()
        .Select(time => Convert.ToInt32(time.GetValueOrDefault("Value")))
        .OrderBy(time => time).ToList();
    if (times.Count != attachments.Count)
        return [];
    for (var index = 0; index < attachments.Count; index++)
        attachments[index]["tick"] = times[index];
    return attachments;
}

static Dictionary<string, object?> ExportCutscenePackage(
    CUE4Parse.UE4.Assets.IPackage package, byte[]? rawData = null)
{
    // EndCinemaSequence packages rely on MovieScene subexports referenced by
    // numeric ObjectPath suffixes (for example "/Game/.../Sequence.12").
    // Preserve package export order so Blender can reuse the established
    // FModel-JSON sequencer importer.
    // Sequence packages also contain compiled evaluation fields and runtime-only
    // exports.  They are often much larger than the authored tracks and Blender
    // never reads them.  Keep a placeholder for every export so numeric
    // ObjectPath indices remain stable, but only convert the properties consumed
    // by json/cutscene_import.py.
    var propertyNamesByType = new Dictionary<string, HashSet<string>>(StringComparer.Ordinal)
    {
        ["EndCinemaSequence"] = new(StringComparer.Ordinal)
        {
            "BindingReferences",
        },
        ["MovieScene"] = new(StringComparer.Ordinal)
        {
            "Spawnables", "Possessables", "ObjectBindings", "MasterTracks",
            "PlaybackRange", "TickResolution", "DisplayRate",
        },
        ["MovieScene3DTransformTrack"] = new(StringComparer.Ordinal)
        {
            "Sections",
        },
        ["MovieScene3DTransformSection"] = new(StringComparer.Ordinal)
        {
            "Translation", "Translation[1]", "Translation[2]",
            "Rotation", "Rotation[1]", "Rotation[2]",
            "Scale", "Scale[1]", "Scale[2]", "SectionRange",
        },
        ["MovieSceneFloatTrack"] = new(StringComparer.Ordinal)
        {
            "PropertyBinding", "Sections",
        },
        ["MovieSceneFloatSection"] = new(StringComparer.Ordinal)
        {
            "FloatCurve", "SectionRange",
        },
        ["MovieSceneColorTrack"] = new(StringComparer.Ordinal)
        {
            "PropertyBinding", "Sections",
        },
        ["MovieSceneColorSection"] = new(StringComparer.Ordinal)
        {
            "RedCurve", "GreenCurve", "BlueCurve", "SectionRange",
        },
        ["MovieSceneBoolTrack"] = new(StringComparer.Ordinal)
        {
            "PropertyBinding", "Sections",
        },
        ["MovieSceneBoolSection"] = new(StringComparer.Ordinal)
        {
            "BoolCurve", "SectionRange",
        },
        ["MovieSceneCameraCutTrack"] = new(StringComparer.Ordinal)
        {
            "Sections",
        },
        ["MovieSceneCameraCutSection"] = new(StringComparer.Ordinal)
        {
            "CameraBindingID", "SectionRange",
        },
        ["MovieSceneSkeletalAnimationTrack"] = new(StringComparer.Ordinal)
        {
            "AnimationSections",
        },
        ["MovieSceneSkeletalAnimationSection"] = new(StringComparer.Ordinal)
        {
            "Params", "SectionRange",
        },
        ["EndCinemaVisibilityTrack"] = new(StringComparer.Ordinal)
        {
            "Sections",
        },
        ["EndCinemaAttachTrack"] = new(StringComparer.Ordinal)
        {
            "ConstraintSections",
        },
        ["EndCinemaAttachSection"] = new(StringComparer.Ordinal)
        {
            "AttachActorName", "SectionRange",
        },
        // The _Voice / _Text / _CutEvent sequences are master-track event lists.
        // Only the trigger times survive cooking -- each key's Parameters struct
        // reads back null -- but the times are what the voice-line importer needs.
        ["MovieSceneEndEventTrack"] = new(StringComparer.Ordinal)
        {
            "Sections",
        },
        ["MovieSceneEndEventSection"] = new(StringComparer.Ordinal)
        {
            "EventData", "SectionRange",
        },
    };
    var exportMetadata = new (string ExportType, string Name)[package.ExportMapLength];
    for (var index = 0; index < exportMetadata.Length; index++)
    {
        exportMetadata[index] = GetCutsceneExportMetadata(package, index);
    }
    var packageExports = new CUE4Parse.UE4.Assets.Exports.UObject?[package.ExportMapLength];
    for (var index = 0; index < exportMetadata.Length; index++)
    {
        if (propertyNamesByType.ContainsKey(exportMetadata[index].ExportType))
        {
            packageExports[index] = package.GetExport(index);
        }
    }
    var exportIndices = packageExports
        .Select((export, index) => new { path = export?.GetPathName(), index })
        .Where(entry => !string.IsNullOrWhiteSpace(entry.path))
        .ToDictionary(entry => entry.path!, entry => entry.index, StringComparer.OrdinalIgnoreCase);
    var exports = new List<object?>();
    var previousPackageIndexConverter = PropertyConversionContext.PackageIndexConverter;
    PropertyConversionContext.PackageIndexConverter = packageIndex =>
    {
        if (packageIndex.IsNull)
            return null;
        if (packageIndex.IsExport)
        {
            var exportIndex = packageIndex.Index - 1;
            if (exportIndex >= 0 && exportIndex < exportMetadata.Length)
            {
                var referenced = exportMetadata[exportIndex];
                return new Dictionary<string, object?>
                {
                    ["ObjectName"] = $"{referenced.ExportType}'{referenced.Name}'",
                    ["ObjectPath"] = $"{package.Name}.{exportIndex}",
                };
            }
        }
        var unresolvedName = packageIndex.Name.ToString();
        return new Dictionary<string, object?>
        {
            ["ObjectName"] = $"Object'{unresolvedName}'",
            ["ObjectPath"] = unresolvedName,
        };
    };
    try
    {
        for (var index = 0; index < packageExports.Length; index++)
        {
            var export = packageExports[index];
            var metadata = exportMetadata[index];
            var properties = new Dictionary<string, object?>();
            if (export is not null && metadata.ExportType == "MovieSceneEndEventSection")
            {
                Console.Error.WriteLine($"DEBUG {metadata.ExportType} clr={export.GetType().FullName} tags={export.Properties.Count}");
                foreach (var dp in export.Properties)
                    Console.Error.WriteLine($"DEBUG   tag {dp.Name.Text} : {dp.PropertyType.Text}");
                foreach (var df in export.GetType().GetFields(System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Instance))
                    Console.Error.WriteLine($"DEBUG   native {df.FieldType.Name} {df.Name}");
            }
            if (export is not null &&
                propertyNamesByType.TryGetValue(metadata.ExportType, out var allowedProperties))
            {
                foreach (var property in export.Properties)
                {
                    if (!allowedProperties.Contains(property.Name.Text))
                        continue;
                    try
                    {
                        if (ConvertValue(property) is not Dictionary<string, object?> converted ||
                            !converted.TryGetValue("name", out var name) || name is null)
                            continue;
                        var propertyValue = converted.TryGetValue("value", out var value)
                            ? NormalizeKdiValue(value)
                            : null;
                        properties[name.ToString()!] = RewriteCutsceneObjectPaths(propertyValue, exportIndices);
                    }
                    catch (Exception exc)
                    {
                        Console.Error.WriteLine($"Cutscene property skipped ({export.Name}): {exc.Message}");
                    }
                }
            }
            exports.Add(new Dictionary<string, object?>
            {
                ["Type"] = metadata.ExportType,
                ["Name"] = metadata.Name,
                ["Package"] = package.Name,
                ["Properties"] = properties,
            });
        }
    }
    finally
    {
        PropertyConversionContext.PackageIndexConverter = previousPackageIndexConverter;
    }
    return new Dictionary<string, object?>
    {
        ["sourceType"] = "EndCinemaSequence package export",
        ["exportCount"] = exports.Count,
        ["exports"] = exports,
        ["attachmentEvents"] = DecodeConstraintAttachments(rawData, exports),
    };
}

static string?[] ExportImportNames(CUE4Parse.UE4.Assets.IPackage package)
{
    return Enumerable.Range(0, package.ImportMapLength)
        .Select(index => package.ResolvePackageIndex(new FPackageIndex(package, -index - 1)))
        .Select(resolved => resolved?.GetPathName() ?? resolved?.Name.ToString())
        .ToArray();
}

static Dictionary<string, object?> ExportBoneTransform(CUE4Parse.UE4.Objects.Core.Math.FTransform transform)
{
    return new Dictionary<string, object?>
    {
        ["translation"] = new[] { transform.Translation.X, transform.Translation.Y, transform.Translation.Z },
        ["rotation"] = new[] { transform.Rotation.X, transform.Rotation.Y, transform.Rotation.Z, transform.Rotation.W },
        ["scale"] = new[] { transform.Scale3D.X, transform.Scale3D.Y, transform.Scale3D.Z },
    };
}

static Dictionary<string, object?> ExportReferenceSkeleton(FReferenceSkeleton referenceSkeleton)
{
    var bones = new List<object?>();
    var boneInfo = referenceSkeleton.FinalRefBoneInfo;
    var bonePose = referenceSkeleton.FinalRefBonePose;
    for (var index = 0; index < boneInfo.Length; index++)
    {
        var bone = index < bonePose.Length
            ? ExportBoneTransform(bonePose[index])
            : ExportBoneTransform(default);
        bone["name"] = boneInfo[index].Name.ToString();
        bone["parentIndex"] = boneInfo[index].ParentIndex;
        bones.Add(bone);
    }
    return new Dictionary<string, object?>
    {
        ["boneCount"] = bones.Count,
        ["bones"] = bones,
    };
}

static List<object?> ExportSockets(FPackageIndex[]? socketRefs)
{
    var sockets = new List<object?>();
    if (socketRefs is null)
        return sockets;
    foreach (var socketRef in socketRefs)
    {
        USkeletalMeshSocket? socket;
        try
        {
            socket = socketRef.Load<USkeletalMeshSocket>();
        }
        catch
        {
            continue;
        }
        if (socket is null)
            continue;
        var rotation = socket.RelativeRotation.Quaternion();
        sockets.Add(new Dictionary<string, object?>
        {
            ["name"] = socket.SocketName.ToString(),
            ["boneName"] = socket.BoneName.ToString(),
            ["translation"] = new[] { socket.RelativeLocation.X, socket.RelativeLocation.Y, socket.RelativeLocation.Z },
            ["rotation"] = new[] { rotation.X, rotation.Y, rotation.Z, rotation.W },
            ["scale"] = new[] { socket.RelativeScale.X, socket.RelativeScale.Y, socket.RelativeScale.Z },
        });
    }
    return sockets;
}

static Dictionary<string, object?> ExportSkeletonPackage(CUE4Parse.UE4.Assets.IPackage package)
{
    var skeleton = package.GetExports().OfType<USkeleton>().FirstOrDefault();
    if (skeleton is not null)
    {
        var result = ExportReferenceSkeleton(skeleton.ReferenceSkeleton);
        result["sourceType"] = "USkeleton";
        result["sockets"] = ExportSockets(skeleton.Sockets);
        return result;
    }

    var mesh = package.GetExports().OfType<USkeletalMesh>().FirstOrDefault()
        ?? throw new InvalidOperationException("Package does not contain a Skeleton or SkeletalMesh export.");
    if (mesh.ReferenceSkeleton is null)
        throw new InvalidOperationException(
            "This SkeletalMesh's own ReferenceSkeleton is not populated (its bind pose data may live outside " +
            "the mounted package). Import its linked Skeleton asset instead.");
    var meshResult = ExportReferenceSkeleton(mesh.ReferenceSkeleton);
    meshResult["sourceType"] = "USkeletalMesh";
    meshResult["sockets"] = ExportSockets(mesh.Sockets);
    if (!mesh.Skeleton.IsNull)
    {
        try
        {
            meshResult["linkedSkeletonPath"] = mesh.Skeleton.ResolvedObject?.GetPathName();
        }
        catch
        {
            // Best-effort only; the mesh's own ReferenceSkeleton above is already complete.
        }
    }
    return meshResult;
}

static string? GetLinkedSkeletonPath(USkeletalMesh mesh)
{
    if (mesh.Skeleton is null || mesh.Skeleton.IsNull)
        return null;
    try
    {
        return mesh.Skeleton.ResolvedObject?.GetPathName();
    }
    catch
    {
        return null;
    }
}

static string? ObjectPathToVirtualAssetPath(
    string? objectPath,
    string contentRoot = "End/Content/")
{
    if (string.IsNullOrWhiteSpace(objectPath) ||
        !objectPath.StartsWith("/Game/", StringComparison.OrdinalIgnoreCase))
        return null;
    var packagePath = objectPath[6..];
    var objectSeparator = packagePath.LastIndexOf('.');
    if (objectSeparator >= 0)
        packagePath = packagePath[..objectSeparator];
    return contentRoot + packagePath + ".uasset";
}

static List<string> ExportKineDriverAssetPaths(
    CUE4Parse.UE4.Assets.IPackage package,
    string contentRoot = "End/Content/")
{
    // The Skeleton is commonly shared by every costume, while the mesh's
    // SQEX_KBD_AssetUserData names the KineDriver authored for this exact
    // variant. Preserve that source-of-truth reference for Blender instead of
    // guessing from the Skeleton filename.
    var objectPaths = new List<string>();

    static void CollectObjectPaths(object? value, List<string> paths)
    {
        if (value is Dictionary<string, object?> dictionary)
        {
            if (dictionary.TryGetValue("ObjectPath", out var path) && path is string text)
                paths.Add(text);
            foreach (var child in dictionary.Values)
                CollectObjectPaths(child, paths);
        }
        else if (value is IEnumerable sequence && value is not string)
        {
            foreach (var child in sequence)
                CollectObjectPaths(child, paths);
        }
    }

    foreach (var export in package.GetExports())
    {
        foreach (var property in export.Properties)
        {
            if (!string.Equals(
                    property.Name.Text, "KineDriverDataList",
                    StringComparison.OrdinalIgnoreCase))
                continue;
            try
            {
                CollectObjectPaths(ConvertValue(property), objectPaths);
            }
            catch (Exception exc)
            {
                Console.Error.WriteLine(
                    $"KineDriverDataList skipped ({export.Name}): {exc.Message}");
            }
        }
    }

    var paths = new List<string>();
    var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
    foreach (var objectPath in objectPaths)
    {
        var virtualPath = ObjectPathToVirtualAssetPath(objectPath, contentRoot);
        if (virtualPath is not null &&
            Regex.IsMatch(
                virtualPath,
                @"_KDI(?:_[A-Za-z0-9_]+)?\.uasset$",
                RegexOptions.IgnoreCase) &&
            seen.Add(virtualPath))
            paths.Add(virtualPath);
    }
    return paths;
}

static List<int> ExportBoneIndices(IEnumerable<short>? indices)
{
    return indices?.Select(index => (int)index).ToList() ?? new List<int>();
}

static List<int> ExportUnsignedBoneIndices(IEnumerable<ushort>? indices)
{
    return indices?.Select(index => (int)index).ToList() ?? new List<int>();
}

static Dictionary<string, object?> ExportMeshUsagePackage(CUE4Parse.UE4.Assets.IPackage package)
{
    var mesh = package.GetExports().OfType<USkeletalMesh>().FirstOrDefault()
        ?? throw new InvalidOperationException("Package does not contain a SkeletalMesh export.");

    var lods = new List<object?>();
    foreach (var lod in mesh.LODModels ?? Array.Empty<FStaticLODModel>())
    {
        if (lod is null)
            continue;
        var sections = new List<object?>();
        foreach (var section in lod.Sections ?? Array.Empty<FSkelMeshSection>())
        {
            if (section is null)
                continue;
            sections.Add(new Dictionary<string, object?>
            {
                ["boneMap"] = ExportUnsignedBoneIndices(section.BoneMap),
                ["baseVertexIndex"] = section.BaseVertexIndex,
                ["vertexCount"] = section.NumVertices,
                ["maxBoneInfluences"] = section.MaxBoneInfluences,
            });
        }
        lods.Add(new Dictionary<string, object?>
        {
            ["activeBoneIndices"] = ExportBoneIndices(lod.ActiveBoneIndices),
            ["requiredBones"] = ExportBoneIndices(lod.RequiredBones),
            ["sections"] = sections,
            ["vertexCount"] = lod.NumVertices,
        });
    }

    var result = new Dictionary<string, object?>
    {
        ["sourceType"] = "USkeletalMesh",
        ["meshReferenceSkeletonPresent"] = mesh.ReferenceSkeleton is not null,
        ["linkedSkeletonPath"] = GetLinkedSkeletonPath(mesh),
        ["lods"] = lods,
    };
    if (mesh.ReferenceSkeleton is not null)
        result["meshReferenceSkeleton"] = ExportReferenceSkeleton(mesh.ReferenceSkeleton);
    return result;
}

static CUE4Parse.UE4.Assets.IPackage LoadPackageWithoutEditorFiltering(
    DefaultFileProvider provider,
    string assetPath)
{
    var files = provider.SavePackage(assetPath);
    byte[]? GetPart(string extension) => files
        .FirstOrDefault(entry => entry.Key.EndsWith(extension, StringComparison.OrdinalIgnoreCase)).Value;
    var uasset = GetPart(".uasset")
        ?? throw new FileNotFoundException("The package has no UAsset payload.", assetPath);
    return new CUE4Parse.UE4.Assets.Package(
        assetPath,
        uasset,
        GetPart(".uexp"),
        GetPart(".ubulk"),
        GetPart(".uptnl"),
        provider,
        false);
}

static (RebirthSkeletalMeshUsageReader Reader, string MeshName, long ExportOffset, long ExportSize) ReadRebirthMeshUsage(
    DefaultFileProvider provider,
    string assetPath,
    CUE4Parse.UE4.Assets.IoPackage package)
{
    var parsedMesh = ((CUE4Parse.UE4.Assets.IPackage)package)
        .GetExports().OfType<USkeletalMesh>().FirstOrDefault()
        ?? throw new InvalidOperationException("Package has no SkeletalMesh export.");
    var meshName = parsedMesh.Name;
    var meshIndex = Array.FindIndex(package.ExportMap,
        entry => package.CreateFNameFromMappedName(entry.ObjectName).Text == meshName);
    if (meshIndex < 0)
        throw new InvalidOperationException($"Could not locate SkeletalMesh export '{meshName}'.");

    var rawPackage = provider.Files[assetPath].Read(null);
    var archive = new FAssetArchive(
        new FByteArchive(assetPath, rawPackage, provider.Versions), package);
    var summary = archive.Read<FPackageSummary>();
    archive.Position = summary.ExportBundlesOffset;
    var remainingBundleEntryCount =
        (summary.GraphDataOffset - summary.ExportBundlesOffset) / (sizeof(int) * 2);
    var foundBundleEntryCount = 0;
    var bundleHeaders = new List<FExportBundleHeader>();
    while (foundBundleEntryCount < remainingBundleEntryCount)
    {
        remainingBundleEntryCount--;
        var header = new FExportBundleHeader(archive);
        foundBundleEntryCount += (int)header.EntryCount;
        bundleHeaders.Add(header);
    }
    if (foundBundleEntryCount != remainingBundleEntryCount)
        throw new InvalidOperationException("Could not decode the IoStore export-bundle table.");
    var bundleEntries = archive.ReadArray<FExportBundleEntry>(foundBundleEntryCount);
    var exportPosition = summary.GraphDataOffset + summary.GraphDataSize;
    var foundPosition = -1;
    foreach (var bundle in bundleHeaders)
    {
        for (var index = 0u; index < bundle.EntryCount; index++)
        {
            var entry = bundleEntries[bundle.FirstEntryIndex + index];
            if (entry.CommandType == EExportCommandType.ExportCommandType_Serialize)
            {
                if (entry.LocalExportIndex == meshIndex)
                    foundPosition = exportPosition;
                exportPosition += (int)package.ExportMap[entry.LocalExportIndex].CookedSerialSize;
            }
        }
    }
    if (foundPosition < 0)
        throw new InvalidOperationException($"No serialized export-bundle entry was found for '{meshName}'.");

    var export = package.ExportMap[meshIndex];
    archive.AbsoluteOffset = (int)export.CookedSerialOffset - foundPosition;
    archive.Position = foundPosition;
    var reader = new RebirthSkeletalMeshUsageReader();
    reader.Name = meshName;
    reader.Class = parsedMesh.Class;
    reader.Outer = parsedMesh.Outer;
    reader.Super = parsedMesh.Super;
    reader.Template = parsedMesh.Template;
    reader.Flags = parsedMesh.Flags;
    reader.Deserialize(archive, archive.Position + (long)export.CookedSerialSize);

    return (reader, meshName, foundPosition, (long)export.CookedSerialSize);
}

static bool TryReadRebirthSkeletalColorStream(
    DefaultFileProvider provider,
    string assetPath,
    CUE4Parse.UE4.Assets.IoPackage package,
    int meshVertexCount,
    out RebirthSkeletalColorStream colorStream)
{
    colorStream = null!;
    try
    {
        var usage = ReadRebirthMeshUsage(provider, assetPath, package);
        var recovered = usage.Reader.BulkColorStream;
        if (recovered is null || recovered.DeclaredCount != meshVertexCount)
            return false;
        var colors = recovered.Colors ?? ReadRebirthSkeletalBulkColors(provider, assetPath, recovered);
        if (colors is null || colors.Length != meshVertexCount)
            return false;
        colorStream = new RebirthSkeletalColorStream(
            colors, recovered.DeclaredCount, recovered.Offset, recovered.BulkByteLength,
            recovered.SizeOnDisk, recovered.OffsetInFile);
        return true;
    }
    // The stock CUE4Parse path remains usable for layouts this narrow reader
    // does not cover.  A failed recovery must not turn a mesh that has no
    // color stream into an import failure.
    catch (Exception)
    {
        return false;
    }
}

static FColor[]? ReadRebirthSkeletalBulkColors(
    DefaultFileProvider provider,
    string assetPath,
    RebirthSkeletalColorStream stream)
{
    var bulkPath = Path.ChangeExtension(assetPath, ".ubulk").Replace('\\', '/');
    if (!provider.Files.TryGetValue(bulkPath, out var bulkFile))
        return null;
    var completeBulk = bulkFile.Read(null);
    var size = checked((int)stream.SizeOnDisk);
    var offset = completeBulk.Length == size ? 0 : checked((int)stream.OffsetInFile);
    if (size <= 0 || offset < 0 || offset > completeBulk.Length - size ||
        stream.Offset > size - checked(stream.DeclaredCount * sizeof(uint)))
        return null;
    using var bulk = new FByteArchive(
        "RebirthSkeletalColorStream", completeBulk.AsSpan(offset, size).ToArray(), provider.Versions);
    bulk.Position = stream.Offset;
    return bulk.ReadArray<FColor>(stream.DeclaredCount);
}

static Dictionary<string, object?> ExportRebirthMeshUsage(
    DefaultFileProvider provider,
    string assetPath,
    CUE4Parse.UE4.Assets.IoPackage package)
{
    var usage = ReadRebirthMeshUsage(provider, assetPath, package);
    var reader = usage.Reader;
    var result = ExportReferenceSkeleton(reader.ReferenceSkeleton);
    result["sourceType"] = "USkeletalMesh (Rebirth narrow reader)";
    result["nativeExportOffset"] = usage.ExportOffset;
    result["nativeExportSize"] = usage.ExportSize;
    result["cookedLodPayloads"] = reader.CookedLodPayloads;
    result["lods"] = reader.Lods.Select(lod => (object?)new Dictionary<string, object?>
    {
        ["requiredBones"] = ExportBoneIndices(lod.RequiredBones),
        ["activeBoneIndices"] = ExportBoneIndices(lod.ActiveBoneIndices),
        ["sections"] = lod.Sections.Select(section => (object?)new Dictionary<string, object?>
        {
            ["boneMap"] = ExportUnsignedBoneIndices(section.BoneMap),
            ["baseVertexIndex"] = section.BaseVertexIndex,
            ["vertexCount"] = section.NumVertices,
        }).ToList(),
    }).ToList();
    return result;
}

static List<string> BoneNamesForIndices(FReferenceSkeleton skeleton, IEnumerable<int> indices)
{
    var boneInfo = skeleton.FinalRefBoneInfo;
    return indices
        .Where(index => index >= 0 && index < boneInfo.Length)
        .Select(index => boneInfo[index].Name.ToString())
        .Distinct(StringComparer.OrdinalIgnoreCase)
        .OrderBy(name => name, StringComparer.OrdinalIgnoreCase)
        .ToList();
}

static string VariantIdForAssetPath(string assetPath)
{
    var match = Regex.Match(assetPath, @"PC\d{4}_\d{2}", RegexOptions.IgnoreCase);
    return match.Success ? match.Value.ToUpperInvariant() : "Unknown";
}

static Dictionary<string, object?> ExportRebirthMeshBoneUsage(
    DefaultFileProvider provider,
    string assetPath,
    CUE4Parse.UE4.Assets.IoPackage package)
{
    var usage = ReadRebirthMeshUsage(provider, assetPath, package);
    var reader = usage.Reader;
    var lod = reader.Lods.FirstOrDefault();
    var weightedIndices = lod?.Sections
        .SelectMany(section => section.BoneMap ?? Array.Empty<ushort>())
        .Select(index => (int)index)
        .Distinct()
        .ToList() ?? new List<int>();
    var activeIndices = lod?.ActiveBoneIndices
        .Select(index => (int)index)
        .Distinct()
        .ToList() ?? new List<int>();
    var requiredIndices = lod?.RequiredBones
        .Select(index => (int)index)
        .Distinct()
        .ToList() ?? new List<int>();
    var variantFolderEnd = assetPath.IndexOf("/Model/", StringComparison.OrdinalIgnoreCase);
    return new Dictionary<string, object?>
    {
        ["assetPath"] = assetPath,
        ["meshName"] = usage.MeshName,
        ["variantFolder"] = variantFolderEnd >= 0 ? assetPath[..variantFolderEnd] : null,
        ["variantId"] = VariantIdForAssetPath(assetPath),
        ["meshReferenceBoneCount"] = reader.ReferenceSkeleton.FinalRefBoneInfo.Length,
        // This is the authoritative mesh-specific skeleton subset used by FModel
        // and umodel. It deliberately contains unweighted KDI/helper bones.
        ["referenceBoneNames"] = BoneNamesForIndices(
            reader.ReferenceSkeleton,
            Enumerable.Range(0, reader.ReferenceSkeleton.FinalRefBoneInfo.Length)
        ),
        // Section BoneMaps identify bones directly referenced by vertex influences.
        ["weightedBoneNames"] = BoneNamesForIndices(reader.ReferenceSkeleton, weightedIndices),
        // Active/required also include evaluation dependencies such as ancestor chains.
        ["activeBoneNames"] = BoneNamesForIndices(reader.ReferenceSkeleton, activeIndices),
        ["requiredBoneNames"] = BoneNamesForIndices(reader.ReferenceSkeleton, requiredIndices),
    };
}

static string VirtualAssetToObjectPath(string virtualPath)
{
    var normalized = virtualPath.Replace('\\', '/').TrimStart('/');
    const string contentPrefix = "End/Content/";
    if (!normalized.StartsWith(contentPrefix, StringComparison.OrdinalIgnoreCase))
        throw new ArgumentException("Expected an End/Content asset path.", nameof(virtualPath));
    var packagePath = normalized[contentPrefix.Length..];
    if (packagePath.EndsWith(".uasset", StringComparison.OrdinalIgnoreCase))
        packagePath = packagePath[..^".uasset".Length];
    var objectName = packagePath[(packagePath.LastIndexOf('/') + 1)..];
    return $"/Game/{packagePath}.{objectName}";
}

static Dictionary<string, object?>? FindMeshAssetsFromRegistry(
    DefaultFileProvider provider,
    string? pathFilter)
{
    var registryFile = provider.Files.FirstOrDefault(entry =>
        entry.Key.EndsWith("AssetRegistry.bin", StringComparison.OrdinalIgnoreCase)).Value;
    if (registryFile is null)
        return null;

    var packagePaths = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
    foreach (var path in provider.Files.Keys.Where(path =>
                 path.EndsWith(".uasset", StringComparison.OrdinalIgnoreCase)))
    {
        var normalized = path.Replace('\\', '/');
        string? packageName = null;
        if (normalized.StartsWith("End/Content/", StringComparison.OrdinalIgnoreCase))
            packageName = "/Game/" + normalized["End/Content/".Length..^".uasset".Length];
        else if (normalized.StartsWith("CCFF7R/Content/", StringComparison.OrdinalIgnoreCase))
            packageName = "/Game/" + normalized["CCFF7R/Content/".Length..^".uasset".Length];
        else if (normalized.StartsWith("Engine/Content/", StringComparison.OrdinalIgnoreCase))
            packageName = "/Engine/" + normalized["Engine/Content/".Length..^".uasset".Length];
        if (packageName is not null)
            packagePaths.TryAdd(packageName, path);
    }

    using var archive = new FByteArchive(
        registryFile.Path, registryFile.Read(null), provider.Versions);
    var registry = new FAssetRegistryState(archive);
    var staticMeshes = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
    var skeletalMeshes = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
    foreach (var asset in registry.PreallocatedAssetDataBuffers)
    {
        if (!packagePaths.TryGetValue(asset.PackageName.ToString(), out var path) ||
            (!string.IsNullOrWhiteSpace(pathFilter) &&
             !path.Contains(pathFilter, StringComparison.OrdinalIgnoreCase)))
            continue;
        var assetClass = asset.AssetClass.ToString();
        if (assetClass.EndsWith("StaticMesh", StringComparison.OrdinalIgnoreCase))
            staticMeshes.Add(path);
        else if (assetClass.EndsWith("SkeletalMesh", StringComparison.OrdinalIgnoreCase))
            skeletalMeshes.Add(path);
    }

    return new Dictionary<string, object?>
    {
        ["source"] = "AssetRegistry.bin",
        ["registryAssetCount"] = registry.PreallocatedAssetDataBuffers.Length,
        ["mappedPackageCount"] = packagePaths.Count,
        ["registryPackageSample"] = registry.PreallocatedAssetDataBuffers
            .Select(asset => asset.PackageName.ToString())
            .FirstOrDefault(name => !string.IsNullOrWhiteSpace(name)),
        ["providerPackageSample"] = provider.Files.Keys.FirstOrDefault(path =>
            path.EndsWith(".uasset", StringComparison.OrdinalIgnoreCase)),
        ["staticMeshes"] = staticMeshes.OrderBy(path => path, StringComparer.OrdinalIgnoreCase).ToList(),
        ["skeletalMeshes"] = skeletalMeshes.OrderBy(path => path, StringComparer.OrdinalIgnoreCase).ToList(),
        ["failures"] = 0,
    };
}

static Dictionary<string, object?> FindMeshAssetsByExportType(
    DefaultFileProvider provider,
    string? pathFilter = null,
    bool preferAssetRegistry = false)
{
    if (preferAssetRegistry)
    {
        var registryIndex = FindMeshAssetsFromRegistry(provider, pathFilter);
        if (registryIndex is not null)
            return registryIndex;
    }

    // IoStore exposes export classes directly in its package tables. Traditional
    // pak packages (Remake) require loading exports, but this is limited to the
    // caller's /Model/ filter and cached by Blender after the first scan.
    var staticMeshes = new List<string>();
    var skeletalMeshes = new List<string>();
    var failures = 0;
    foreach (var path in provider.Files.Keys
        .Where(path => path.EndsWith(".uasset", StringComparison.OrdinalIgnoreCase))
        .Where(path => string.IsNullOrWhiteSpace(pathFilter) ||
            path.Contains(pathFilter, StringComparison.OrdinalIgnoreCase))
        .OrderBy(path => path, StringComparer.OrdinalIgnoreCase))
    {
        try
        {
            var loadedPackage = provider.LoadPackage(path);
            var exportTypes = loadedPackage is CUE4Parse.UE4.Assets.IoPackage ioPackage
                ? ioPackage.ExportMap
                    .Select(export => ioPackage.ResolveObjectIndex(export.ClassIndex)?.Name.ToString())
                    .Where(name => !string.IsNullOrWhiteSpace(name))
                    .ToHashSet(StringComparer.OrdinalIgnoreCase)
                : loadedPackage.GetExports()
                    .Select(export => export.ExportType)
                    .ToHashSet(StringComparer.OrdinalIgnoreCase);
            if (exportTypes.Contains("StaticMesh"))
                staticMeshes.Add(path);
            if (exportTypes.Contains("SkeletalMesh"))
                skeletalMeshes.Add(path);
        }
        catch
        {
            failures++;
        }
    }
    return new Dictionary<string, object?>
    {
        ["staticMeshes"] = staticMeshes,
        ["skeletalMeshes"] = skeletalMeshes,
        ["failures"] = failures,
    };
}

static string? GetAnimationSkeletonPath(UAnimationAsset animation)
{
    try
    {
        return animation.Skeleton?.ResolvedObject?.GetPathName();
    }
    catch
    {
        return null;
    }
}

static Dictionary<string, object?> FindAnimationAssetsForSkeleton(
    DefaultFileProvider provider,
    string skeletonAssetPath,
    string? searchPath = null,
    string? searchToken = null)
{
    var targetObjectPath = VirtualAssetToObjectPath(skeletonAssetPath);
    var animations = new List<object?>();
    var failures = 0;

    // Package export maps are inexpensive to inspect.  Deserialize only files
    // which actually contain an AnimSequence export, then resolve the Skeleton
    // property to keep the Blender picker limited to the selected rig.
    foreach (var path in provider.Files.Keys
        .Where(path => path.EndsWith(".uasset", StringComparison.OrdinalIgnoreCase))
        .Where(path => string.IsNullOrWhiteSpace(searchPath) ||
            path.StartsWith(searchPath, StringComparison.OrdinalIgnoreCase))
        .Where(path => string.IsNullOrWhiteSpace(searchToken) ||
            path.Contains(searchToken, StringComparison.OrdinalIgnoreCase))
        .OrderBy(path => path, StringComparer.OrdinalIgnoreCase))
    {
        try
        {
            if (provider.LoadPackage(path) is not CUE4Parse.UE4.Assets.IoPackage package)
                continue;
            var hasAnimSequence = package.ExportMap.Any(export => string.Equals(
                package.ResolveObjectIndex(export.ClassIndex)?.Name.ToString(),
                "AnimSequence", StringComparison.OrdinalIgnoreCase));
            if (!hasAnimSequence)
                continue;

            foreach (var animation in ((CUE4Parse.UE4.Assets.IPackage) package)
                .GetExports().OfType<URebirthAnimSequence>())
            {
                var linkedSkeletonPath = GetAnimationSkeletonPath(animation);
                if (!string.Equals(linkedSkeletonPath, targetObjectPath,
                    StringComparison.OrdinalIgnoreCase))
                    continue;
                animations.Add(new Dictionary<string, object?>
                {
                    ["assetPath"] = path,
                    ["name"] = animation.Name.ToString(),
                    ["type"] = animation.ExportType,
                    ["skeletonPath"] = skeletonAssetPath,
                });
            }
        }
        catch
        {
            // Cooked packages which cannot be read are unrelated to this picker's
            // result.  Keep scanning so one bad asset cannot hide a character's clips.
            failures++;
        }
    }
    return new Dictionary<string, object?>
    {
        ["animations"] = animations,
        ["failures"] = failures,
    };
}

static float[] ExportVector(CUE4Parse.UE4.Objects.Core.Math.FVector value)
    => [value.X, value.Y, value.Z];

static float[] ExportQuaternion(CUE4Parse.UE4.Objects.Core.Math.FQuat value)
    => [value.X, value.Y, value.Z, value.W];

// Diagnostic for AnimSequences whose payload holds no ACL 1.x clip (prop and
// environment animation, e.g. BG*/FA* actors).  Reports the payload shape and the
// tagged properties so the alternative encoding can be identified without guessing.
// A bPoseAnimation clip holds one transform per bone, held for the clip's whole
// duration, so it is emitted as a single key per channel.  The add-on's samplers
// hold the last key at or before the current frame, which reproduces that exactly.
static Dictionary<string, object?> ExportPoseAnimation(
    URebirthAnimSequence source,
    USkeleton skeleton,
    PoseClip pose)
{
    var trackMap = source.TrackToBoneIndex;
    var boneInfo = skeleton.ReferenceSkeleton.FinalRefBoneInfo;
    var bonePose = skeleton.ReferenceSkeleton.FinalRefBonePose;
    float[] frames = [0.0f];

    var tracks = new List<object?>();
    for (var track = 0; track < pose.NumTracks && track < trackMap.Length; track++)
    {
        var boneIndex = trackMap[track];
        if (boneIndex < 0 || boneIndex >= boneInfo.Length)
            continue;
        tracks.Add(new Dictionary<string, object?>
        {
            ["boneName"] = boneInfo[boneIndex].Name.ToString(),
            ["bindTranslation"] = boneIndex < bonePose.Length ? ExportVector(bonePose[boneIndex].Translation) : new float[] { 0, 0, 0 },
            ["bindRotation"] = boneIndex < bonePose.Length ? ExportQuaternion(bonePose[boneIndex].Rotation) : new float[] { 0, 0, 0, 1 },
            ["bindScale"] = boneIndex < bonePose.Length ? ExportVector(bonePose[boneIndex].Scale3D) : new float[] { 1, 1, 1 },
            ["translations"] = new[] { pose.Translations[track] },
            ["translationFrames"] = frames,
            ["rotations"] = new[] { pose.Rotations[track] },
            ["rotationFrames"] = frames,
            ["scales"] = new[] { pose.Scales[track] },
            ["scaleFrames"] = frames,
        });
    }

    var sampleRate = source.SequenceLength > 0.0f && source.NumFrames > 0
        ? source.NumFrames / source.SequenceLength
        : 30.0f;
    return new Dictionary<string, object?>
    {
        ["name"] = source.Name,
        ["skeletonPath"] = ObjectPathToVirtualAssetPath(GetAnimationSkeletonPath(source)),
        ["numFrames"] = source.NumFrames,
        ["duration"] = source.SequenceLength,
        ["framesPerSecond"] = sampleRate,
        ["poseAnimation"] = true,
        ["tracks"] = tracks,
    };
}

static Dictionary<string, object?> ExportAnimationPayloadInfo(CUE4Parse.UE4.Assets.IPackage package)
{
    var source = package.GetExports().OfType<URebirthAnimSequence>().FirstOrDefault()
        ?? throw new InvalidOperationException("Package does not contain a UAnimSequence export.");
    var payload = source.CompressedPayload;

    static List<int> FindTag(byte[] data, uint tag)
    {
        var hits = new List<int>();
        for (var i = 0; i + 4 <= data.Length; i++)
            if (System.Buffers.Binary.BinaryPrimitives.ReadUInt32LittleEndian(data.AsSpan(i)) == tag)
                hits.Add(i);
        return hits;
    }

    var props = new List<object?>();
    foreach (var property in source.Properties)
    {
        string? preview = null;
        try { preview = property.Tag?.GenericValue?.ToString(); } catch { }
        if (preview is { Length: > 120 })
            preview = preview[..120];
        props.Add(new Dictionary<string, object?>
        {
            ["name"] = property.Name.Text,
            ["type"] = property.PropertyType.Text,
            ["value"] = preview,
        });
    }

    return new Dictionary<string, object?>
    {
        ["name"] = source.Name,
        ["numFrames"] = source.NumFrames,
        ["trackCount"] = source.TrackToBoneIndex.Length,
        ["payloadLength"] = payload.Length,
        ["payloadHeadHex"] = Convert.ToHexString(payload.AsSpan(0, Math.Min(1024, payload.Length))),
        ["payloadTailHex"] = payload.Length > 160
            ? Convert.ToHexString(payload.AsSpan(Math.Max(0, payload.Length - 64)))
            : "",
        ["aclV1TagOffsets"] = FindTag(payload, 0xAC10AC10u),
        ["aclV2TagOffsets"] = FindTag(payload, 0xAC11AC11u),
        ["properties"] = props,
    };
}

static Dictionary<string, object?> ExportAnimationPackage(CUE4Parse.UE4.Assets.IPackage package)
{
    var source = package.GetExports().OfType<URebirthAnimSequence>().FirstOrDefault()
        ?? throw new InvalidOperationException("Package does not contain a UAnimSequence export.");
    var skeleton = source.Skeleton?.Load<USkeleton>()
        ?? throw new InvalidOperationException("Animation does not resolve a USkeleton.");

    // Rebirth stores prop/environment clips flagged bPoseAnimation with a different
    // bone codec (id EF2036B0..., vs ACL's 30AF2F90...) whose payload holds no ACL
    // compressed_clip.  Those are not decodable yet, but the tagged properties --
    // crucially Skeleton -- read fine, so report the clip as undecodable metadata
    // instead of throwing.  Callers can then still build the actor at its bind pose
    // rather than dropping it from the scene entirely.
    var clip = AclClip.Find(source.CompressedPayload, out var clipError);
    if (clip is null)
    {
        var poseAnimation = source.GetOrDefault<bool>("bPoseAnimation");
        if (poseAnimation)
        {
            var pose = PoseClip.Decode(source.CompressedPayload, source.TrackToBoneIndex.Length,
                out var poseError);
            if (pose is not null)
                return ExportPoseAnimation(source, skeleton, pose);
            clipError = poseError ?? clipError;
        }
        return new Dictionary<string, object?>
        {
            ["name"] = source.Name,
            ["skeletonPath"] = ObjectPathToVirtualAssetPath(GetAnimationSkeletonPath(source)),
            ["numFrames"] = source.NumFrames,
            ["duration"] = source.SequenceLength,
            ["framesPerSecond"] = source.SequenceLength > 0.0f
                ? source.NumFrames / source.SequenceLength
                : 30.0f,
            ["tracks"] = new List<object?>(),
            ["undecodable"] = clipError,
            ["poseAnimation"] = poseAnimation,
            ["payloadLength"] = source.CompressedPayload.Length,
        };
    }
    var decompressor = new AclDecompressor(clip);

    var trackMap = source.TrackToBoneIndex;
    if (trackMap.Length != decompressor.NumBones)
        throw new InvalidOperationException(
            $"Animation has {trackMap.Length} track(s) in TrackToSkeletonMapTable but its ACL clip " +
            $"holds {decompressor.NumBones}; the clip does not belong to this AnimSequence.");

    var boneInfo = skeleton.ReferenceSkeleton.FinalRefBoneInfo;
    var bonePose = skeleton.ReferenceSkeleton.FinalRefBonePose;
    var numSamples = decompressor.NumSamples;
    var numTracks = decompressor.NumBones;

    // Decompress pose by pose, then transpose: ACL stores whole poses, the add-on wants
    // whole tracks.
    var translations = new float[numTracks][][];
    var rotations = new float[numTracks][][];
    var scales = new float[numTracks][][];
    for (var track = 0; track < numTracks; track++)
    {
        translations[track] = new float[numSamples][];
        rotations[track] = new float[numSamples][];
        scales[track] = new float[numSamples][];
    }

    var poseRotations = new System.Numerics.Quaternion[numTracks];
    var poseTranslations = new System.Numerics.Vector3[numTracks];
    var poseScales = new System.Numerics.Vector3[numTracks];
    for (var sample = 0; sample < numSamples; sample++)
    {
        decompressor.DecompressPose(sample, poseRotations, poseTranslations, poseScales);
        for (var track = 0; track < numTracks; track++)
        {
            translations[track][sample] = [poseTranslations[track].X, poseTranslations[track].Y, poseTranslations[track].Z];
            rotations[track][sample] = [poseRotations[track].X, poseRotations[track].Y, poseRotations[track].Z, poseRotations[track].W];
            scales[track][sample] = [poseScales[track].X, poseScales[track].Y, poseScales[track].Z];
        }
    }

    // Every track is sampled on every frame, so all three channels share one frame list.
    var frames = Enumerable.Range(0, numSamples).Select(index => (float) index).ToArray();

    var tracks = new List<object?>();
    for (var track = 0; track < numTracks; track++)
    {
        var boneIndex = trackMap[track];
        if (boneIndex < 0 || boneIndex >= boneInfo.Length)
            continue;
        tracks.Add(new Dictionary<string, object?>
        {
            ["boneName"] = boneInfo[boneIndex].Name.ToString(),
            ["bindTranslation"] = boneIndex < bonePose.Length ? ExportVector(bonePose[boneIndex].Translation) : new float[] { 0, 0, 0 },
            ["bindRotation"] = boneIndex < bonePose.Length ? ExportQuaternion(bonePose[boneIndex].Rotation) : new float[] { 0, 0, 0, 1 },
            ["bindScale"] = boneIndex < bonePose.Length ? ExportVector(bonePose[boneIndex].Scale3D) : new float[] { 1, 1, 1 },
            ["translations"] = translations[track],
            ["translationFrames"] = frames,
            ["rotations"] = rotations[track],
            ["rotationFrames"] = frames,
            ["scales"] = scales[track],
            ["scaleFrames"] = frames,
        });
    }

    var sampleRate = decompressor.SampleRate > 0.0f ? decompressor.SampleRate : 30.0f;
    var duration = source.SequenceLength > 0.0f
        ? source.SequenceLength
        : Math.Max(0, numSamples - 1) / sampleRate;
    return new Dictionary<string, object?>
    {
        ["name"] = source.Name,
        ["skeletonPath"] = ObjectPathToVirtualAssetPath(GetAnimationSkeletonPath(source)),
        ["numFrames"] = numSamples,
        ["duration"] = duration,
        ["framesPerSecond"] = sampleRate,
        ["tracks"] = tracks,
    };
}

static List<object?> FindSkeletonUsers(
    DefaultFileProvider provider,
    string skeletonAssetPath,
    string searchPath)
{
    if (string.IsNullOrWhiteSpace(searchPath))
        throw new ArgumentException("A character-family searchPath is required to avoid scanning every game asset.");

    var targetObjectPath = VirtualAssetToObjectPath(skeletonAssetPath);
    var results = new List<object?>();
    foreach (var path in provider.Files.Keys
        .Where(path => path.EndsWith(".uasset", StringComparison.OrdinalIgnoreCase))
        .Where(path => path.Contains(searchPath, StringComparison.OrdinalIgnoreCase))
        .Where(path => path.Contains("/Model/", StringComparison.OrdinalIgnoreCase))
        .OrderBy(path => path, StringComparer.OrdinalIgnoreCase))
    {
        try
        {
            var package = provider.LoadPackage(path);
            var mesh = package.GetExports().OfType<USkeletalMesh>().FirstOrDefault();
            if (mesh is null)
                continue;
            var imports = Enumerable.Range(0, package.ImportMapLength)
                .Select(index => package.ResolvePackageIndex(new FPackageIndex(package, -index - 1)))
                .Select(resolved => resolved?.GetPathName())
                .Where(importPath => !string.IsNullOrWhiteSpace(importPath));
            if (!imports.Any(importPath => string.Equals(
                    importPath, targetObjectPath, StringComparison.OrdinalIgnoreCase)))
                continue;
            results.Add(new Dictionary<string, object?>
            {
                ["assetPath"] = path,
                ["meshName"] = mesh.Name,
                ["variantFolder"] = path[..path.IndexOf("/Model/", StringComparison.OrdinalIgnoreCase)],
            });
        }
        catch
        {
            // Some unrelated assets in the family may use unsupported cooked layouts.
        }
    }
    return results;
}

static Dictionary<string, object?> ExportSkeletonBoneUsage(
    DefaultFileProvider provider,
    string skeletonAssetPath,
    string searchPath)
{
    var users = FindSkeletonUsers(provider, skeletonAssetPath, searchPath);
    var meshes = new List<Dictionary<string, object?>>();
    var failures = new List<object?>();
    foreach (var user in users.OfType<Dictionary<string, object?>>())
    {
        var assetPath = user.TryGetValue("assetPath", out var assetPathValue)
            ? assetPathValue as string
            : null;
        if (string.IsNullOrWhiteSpace(assetPath))
            continue;
        try
        {
            var package = provider.LoadPackage(assetPath) as CUE4Parse.UE4.Assets.IoPackage
                ?? throw new InvalidOperationException("The mesh is not an IoStore package.");
            meshes.Add(ExportRebirthMeshBoneUsage(provider, assetPath, package));
        }
        catch (Exception error)
        {
            failures.Add(new Dictionary<string, object?>
            {
                ["assetPath"] = assetPath,
                ["error"] = error.Message,
            });
        }
    }

    var variants = new Dictionary<string, HashSet<string>>(StringComparer.OrdinalIgnoreCase);
    foreach (var mesh in meshes)
    {
        var variant = mesh["variantId"] as string ?? "Unknown";
        if (!variants.TryGetValue(variant, out var bones))
        {
            bones = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            variants[variant] = bones;
        }
        if (mesh["weightedBoneNames"] is IEnumerable<string> weightedNames)
            bones.UnionWith(weightedNames);
    }

    var variantResults = new Dictionary<string, object?>();
    foreach (var variant in variants.OrderBy(entry => entry.Key, StringComparer.OrdinalIgnoreCase))
    {
        var sharedWithOtherVariants = variants
            .Where(other => !string.Equals(other.Key, variant.Key, StringComparison.OrdinalIgnoreCase))
            .SelectMany(other => other.Value)
            .ToHashSet(StringComparer.OrdinalIgnoreCase);
        variantResults[variant.Key] = new Dictionary<string, object?>
        {
            ["weightedBoneNames"] = variant.Value.OrderBy(name => name, StringComparer.OrdinalIgnoreCase).ToList(),
            ["exclusiveWeightedBoneNames"] = variant.Value
                .Where(name => !sharedWithOtherVariants.Contains(name))
                .OrderBy(name => name, StringComparer.OrdinalIgnoreCase)
                .ToList(),
        };
    }

    return new Dictionary<string, object?>
    {
        ["sourceType"] = "Rebirth narrow skeletal-mesh bone usage",
        ["skeletonAssetPath"] = skeletonAssetPath,
        ["searchedMeshCount"] = users.Count,
        ["parsedMeshCount"] = meshes.Count,
        ["meshes"] = meshes,
        ["variants"] = variantResults,
        ["failures"] = failures,
    };
}

try
{
    var oodlePath = args.Length > 2 && !string.IsNullOrWhiteSpace(args[2])
        ? Path.GetFullPath(args[2])
        : null;
    if (!string.IsNullOrWhiteSpace(oodlePath))
    {
        if (!File.Exists(oodlePath))
            throw new FileNotFoundException("Oodle DLL was not found.", oodlePath);
        OodleHelper.Initialize(oodlePath);
    }
    var pakDirectory = ResolvePackageDirectory(gameDirectory);
    var requestedProfile = args.Length > 10 ? args[10] : null;
    var gameProfile = ResolveGameProfile(gameDirectory, pakDirectory, requestedProfile);

    // Rebirth lays out AnimSequence bytes differently from stock UE4.26; see
    // docs/REBIRTH_ANIMSEQUENCE_FORMAT.md.  This registration is harmless for
    // the other mount-only profiles; their import paths are not enabled yet.
    ObjectTypeRegistry.RegisterClass("AnimSequence", typeof(URebirthAnimSequence));
    var provider = new DefaultFileProvider(
        pakDirectory,
        SearchOption.AllDirectories,
        new VersionContainer(gameProfile.Version));
    var usmapPath = args.Length > 5 && !string.IsNullOrWhiteSpace(args[5])
        ? Path.GetFullPath(args[5])
        : null;
    if (!string.IsNullOrWhiteSpace(usmapPath))
    {
        if (!File.Exists(usmapPath))
            throw new FileNotFoundException("usmap file was not found.", usmapPath);
        provider.MappingsContainer = new FileUsmapTypeMappingsProvider(usmapPath);
    }
    provider.Initialize();
    var mountedCount = provider.Mount();
    if (!string.IsNullOrWhiteSpace(gameProfile.AesKey))
    {
        var encryptionKey = new FAesKey(gameProfile.AesKey);
        var requiredKeys = provider.RequiredKeys.ToArray();
        if (requiredKeys.Length > 0)
        {
            mountedCount += provider.SubmitKeys(requiredKeys.Select(guid =>
                new KeyValuePair<FGuid, FAesKey>(guid, encryptionKey)));
        }
    }
    provider.PostMount();

    var operationMode = args.Length > 9 ? args[9] : null;
    if (string.Equals(operationMode, "asset-server", StringComparison.OrdinalIgnoreCase) ||
        string.Equals(operationMode, "texture-server", StringComparison.OrdinalIgnoreCase))
    {
        string? requestLine;
        while ((requestLine = Console.ReadLine()) is not null)
        {
            if (string.IsNullOrWhiteSpace(requestLine))
                continue;
            try
            {
                using var request = JsonDocument.Parse(requestLine);
                var requestRoot = request.RootElement;
                var action = requestRoot.TryGetProperty("action", out var actionElement)
                    ? actionElement.GetString() ?? "texture"
                    : "texture";
                if (string.Equals(action, "release_batch_memory", StringComparison.OrdinalIgnoreCase))
                {
                    var restartThresholdBytes = requestRoot.TryGetProperty("restartThresholdBytes", out var thresholdElement)
                        ? thresholdElement.GetInt64()
                        : 0L;
                    Console.WriteLine(JsonSerializer.Serialize(new
                    {
                        ok = true,
                        action,
                        memory = CollectBatchMemory(restartThresholdBytes),
                    }));
                    Console.Out.Flush();
                    continue;
                }
                if (string.Equals(action, "mesh_index", StringComparison.OrdinalIgnoreCase))
                {
                    var requestPathFilter = requestRoot.TryGetProperty("pathFilter", out var pathFilterElement)
                        ? pathFilterElement.GetString()
                        : null;
                    Console.WriteLine(JsonSerializer.Serialize(new
                    {
                        ok = true,
                        action,
                        meshIndex = FindMeshAssetsByExportType(
                            provider,
                            requestPathFilter,
                            !string.Equals(
                                gameProfile.Name,
                                "Final Fantasy VII Rebirth",
                                StringComparison.Ordinal)),
                    }));
                    Console.Out.Flush();
                    continue;
                }
                if (string.Equals(action, "umap_index", StringComparison.OrdinalIgnoreCase))
                {
                    var umaps = provider.Files.Keys
                        .Where(path => path.EndsWith(".umap", StringComparison.OrdinalIgnoreCase))
                        .OrderBy(path => path, StringComparer.OrdinalIgnoreCase)
                        .ToList();
                    Console.WriteLine(JsonSerializer.Serialize(new
                    {
                        ok = true,
                        action,
                        umaps,
                    }));
                    Console.Out.Flush();
                    continue;
                }
                if (string.Equals(action, "animation_index", StringComparison.OrdinalIgnoreCase))
                {
                    var skeletonAssetPath = requestRoot.GetProperty("skeletonAssetPath").GetString()
                        ?? throw new ArgumentException("Animation index request has no skeletonAssetPath.");
                    var searchPath = requestRoot.TryGetProperty("searchPath", out var searchPathElement)
                        ? searchPathElement.GetString()
                        : null;
                    var searchToken = requestRoot.TryGetProperty("searchToken", out var searchTokenElement)
                        ? searchTokenElement.GetString()
                        : null;
                    Console.WriteLine(JsonSerializer.Serialize(new
                    {
                        ok = true,
                        action,
                        animationIndex = FindAnimationAssetsForSkeleton(provider, skeletonAssetPath, searchPath, searchToken),
                    }));
                    Console.Out.Flush();
                    continue;
                }
                var requestAsset = requestRoot.GetProperty("assetPath").GetString()
                    ?? throw new ArgumentException("Asset request has no assetPath.");
                if (string.Equals(action, "raw", StringComparison.OrdinalIgnoreCase))
                {
                    var requestOutput = requestRoot.GetProperty("output").GetString()
                        ?? throw new ArgumentException("Raw request has no output path.");
                    if (!provider.Files.TryGetValue(requestAsset, out var gameFile))
                        throw new FileNotFoundException("Virtual asset path was not found.", requestAsset);
                    var rawBytes = gameFile.Read(null);
                    File.WriteAllBytes(Path.GetFullPath(requestOutput), rawBytes);
                    Console.WriteLine(JsonSerializer.Serialize(new
                    {
                        ok = true,
                        action,
                        assetPath = requestAsset,
                        rawByteLength = rawBytes.Length
                    }));
                }
                else if (string.Equals(action, "metadata", StringComparison.OrdinalIgnoreCase))
                {
                    var requestPackage = provider.LoadPackage(requestAsset);
                    Console.WriteLine(JsonSerializer.Serialize(new
                    {
                        ok = true,
                        action,
                        assetPath = requestAsset,
                        importNames = ExportImportNames(requestPackage)
                    }));
                }
                else if (string.Equals(action, "kdi", StringComparison.OrdinalIgnoreCase))
                {
                    var requestPackage = provider.LoadPackage(requestAsset);
                    Console.WriteLine(JsonSerializer.Serialize(new
                    {
                        ok = true,
                        action,
                        assetPath = requestAsset,
                        kdi = ExportKdiAsset(requestPackage)
                    }));
                }
                else if (string.Equals(action, "umap_actors", StringComparison.OrdinalIgnoreCase))
                {
                    var requestPackage = provider.LoadPackage(requestAsset);
                    Console.WriteLine(JsonSerializer.Serialize(new
                    {
                        ok = true,
                        action,
                        assetPath = requestAsset,
                        umapActors = ExportUmapActors(requestPackage)
                    }));
                }
                else if (string.Equals(action, "streaming_probe", StringComparison.OrdinalIgnoreCase))
                {
                    var requestPackage = provider.LoadPackage(requestAsset);
                    Console.WriteLine(JsonSerializer.Serialize(new
                    {
                        ok = true,
                        action,
                        assetPath = requestAsset,
                        streamingProbe = ExportStreamingProbe(requestPackage)
                    }));
                }
                else if (string.Equals(action, "umap_data", StringComparison.OrdinalIgnoreCase))
                {
                    // Metadata and actor properties share one package deserialize;
                    // package UMAP imports previously paid this cost twice.
                    var requestPackage = provider.LoadPackage(requestAsset);
                    Console.WriteLine(JsonSerializer.Serialize(new
                    {
                        ok = true,
                        action,
                        assetPath = requestAsset,
                        importNames = ExportImportNames(requestPackage),
                        umapActors = ExportUmapActors(requestPackage)
                    }));
                }
                else if (string.Equals(action, "cutscene", StringComparison.OrdinalIgnoreCase))
                {
                    var requestPackage = provider.LoadPackage(requestAsset);
                    var rawData = provider.Files.TryGetValue(requestAsset, out var cutsceneFile)
                        ? cutsceneFile.Read(null)
                        : null;
                    Console.WriteLine(JsonSerializer.Serialize(new
                    {
                        ok = true,
                        action,
                        assetPath = requestAsset,
                        cutscene = ExportCutscenePackage(requestPackage, rawData)
                    }));
                }
                else if (string.Equals(action, "anim_payload", StringComparison.OrdinalIgnoreCase))
                {
                    var requestPackage = provider.LoadPackage(requestAsset);
                    Console.WriteLine(JsonSerializer.Serialize(new
                    {
                        ok = true,
                        action,
                        assetPath = requestAsset,
                        animPayload = ExportAnimationPayloadInfo(requestPackage)
                    }));
                }
                else if (string.Equals(action, "skeleton", StringComparison.OrdinalIgnoreCase))
                {
                    var requestPackage = provider.LoadPackage(requestAsset);
                    Console.WriteLine(JsonSerializer.Serialize(new
                    {
                        ok = true,
                        action,
                        assetPath = requestAsset,
                        skeleton = ExportSkeletonPackage(requestPackage)
                    }));
                }
                else if (string.Equals(action, "animation", StringComparison.OrdinalIgnoreCase))
                {
                    var requestPackage = provider.LoadPackage(requestAsset);
                    Console.WriteLine(JsonSerializer.Serialize(new
                    {
                        ok = true,
                        action,
                        assetPath = requestAsset,
                        animation = ExportAnimationPackage(requestPackage)
                    }));
                }
                else if (string.Equals(action, "static_mesh", StringComparison.OrdinalIgnoreCase))
                {
                    var requestPackage = provider.LoadPackage(requestAsset);
                    Dictionary<string, object?> staticMesh;
                    if (!string.Equals(gameProfile.Name, "Final Fantasy VII Rebirth", StringComparison.Ordinal))
                    {
                        var sourceMesh = requestPackage.GetExports().OfType<UStaticMesh>().FirstOrDefault()
                            ?? throw new InvalidOperationException("The package contains no UStaticMesh export.");
                        staticMesh = ExportStaticMeshAsset(sourceMesh);
                    }
                    else
                    {
                        var ioPackage = requestPackage as CUE4Parse.UE4.Assets.IoPackage
                            ?? throw new InvalidOperationException("Rebirth StaticMesh import requires an IoStore package.");
                        staticMesh = ExportRebirthStaticMesh(provider, requestAsset, ioPackage);
                    }
                    Console.WriteLine(JsonSerializer.Serialize(new
                    {
                        ok = true,
                        action,
                        assetPath = requestAsset,
                        staticMesh
                    }));
                }
                else if (string.Equals(action, "material", StringComparison.OrdinalIgnoreCase))
                {
                    var requestPackage = provider.LoadPackage(requestAsset);
                    Console.WriteLine(JsonSerializer.Serialize(new
                    {
                        ok = true,
                        action,
                        assetPath = requestAsset,
                        material = ExportMaterialInstancePackage(requestPackage),
                    }));
                }
                else if (string.Equals(action, "niagara", StringComparison.OrdinalIgnoreCase))
                {
                    var requestPackage = provider.LoadPackage(requestAsset);
                    Console.WriteLine(JsonSerializer.Serialize(new
                    {
                        ok = true,
                        action,
                        assetPath = requestAsset,
                        niagara = ExportNiagaraPackage(requestPackage),
                    }));
                }
                else if (string.Equals(action, "skeletal_mesh", StringComparison.OrdinalIgnoreCase))
                {
                    var requestPackage = provider.LoadPackage(requestAsset);
                    Dictionary<string, object?> skeletalMesh;
                    if (string.Equals(gameProfile.Name, "Final Fantasy VII Rebirth", StringComparison.Ordinal))
                    {
                        skeletalMesh = ExportRebirthSkeletalMesh(provider, requestAsset, requestPackage);
                    }
                    else
                    {
                        var sourceMesh = requestPackage.GetExports().OfType<USkeletalMesh>().FirstOrDefault()
                            ?? throw new InvalidOperationException("The package contains no USkeletalMesh export.");
                        skeletalMesh = ExportSkeletalMeshAsset(
                            sourceMesh,
                            requestPackage,
                            gameProfile.Name,
                            string.Equals(gameProfile.Name, "Crisis Core -Final Fantasy VII- Reunion", StringComparison.Ordinal)
                                ? "CCFF7R/Content/"
                                : "End/Content/");
                    }
                    Console.WriteLine(JsonSerializer.Serialize(new
                    {
                        ok = true,
                        action,
                        assetPath = requestAsset,
                        skeletalMesh
                    }));
                }
                else if (string.Equals(action, "mesh_usage", StringComparison.OrdinalIgnoreCase))
                {
                    var requestPackage = provider.LoadPackage(requestAsset);
                    Console.WriteLine(JsonSerializer.Serialize(new
                    {
                        ok = true,
                        action,
                        assetPath = requestAsset,
                        meshUsage = ExportMeshUsagePackage(requestPackage)
                    }));
                }
                else if (string.Equals(action, "rebirth_mesh_usage", StringComparison.OrdinalIgnoreCase))
                {
                    var requestPackage = provider.LoadPackage(requestAsset) as CUE4Parse.UE4.Assets.IoPackage
                        ?? throw new InvalidOperationException("Rebirth mesh usage requires an IoStore package.");
                    Console.WriteLine(JsonSerializer.Serialize(new
                    {
                        ok = true,
                        action,
                        assetPath = requestAsset,
                        meshUsage = ExportRebirthMeshUsage(provider, requestAsset, requestPackage)
                    }));
                }
                else if (string.Equals(action, "mesh_usage_unfiltered", StringComparison.OrdinalIgnoreCase))
                {
                    var requestPackage = LoadPackageWithoutEditorFiltering(provider, requestAsset);
                    Console.WriteLine(JsonSerializer.Serialize(new
                    {
                        ok = true,
                        action,
                        assetPath = requestAsset,
                        meshUsage = ExportMeshUsagePackage(requestPackage)
                    }));
                }
                else if (string.Equals(action, "package_parts", StringComparison.OrdinalIgnoreCase))
                {
                    var parts = provider.SavePackage(requestAsset)
                        .Select(entry => new { path = entry.Key, byteLength = entry.Value.Length });
                    Console.WriteLine(JsonSerializer.Serialize(new
                    {
                        ok = true,
                        action,
                        assetPath = requestAsset,
                        parts,
                    }));
                }
                else if (string.Equals(action, "skeleton_users", StringComparison.OrdinalIgnoreCase))
                {
                    var searchPath = requestRoot.TryGetProperty("searchPath", out var searchPathElement)
                        ? searchPathElement.GetString() ?? string.Empty
                        : string.Empty;
                    Console.WriteLine(JsonSerializer.Serialize(new
                    {
                        ok = true,
                        action,
                        skeletonAssetPath = requestAsset,
                        users = FindSkeletonUsers(provider, requestAsset, searchPath)
                    }));
                }
                else if (string.Equals(action, "skeleton_bone_usage", StringComparison.OrdinalIgnoreCase))
                {
                    var searchPath = requestRoot.TryGetProperty("searchPath", out var searchPathElement)
                        ? searchPathElement.GetString() ?? string.Empty
                        : string.Empty;
                    Console.WriteLine(JsonSerializer.Serialize(new
                    {
                        ok = true,
                        action,
                        skeletonBoneUsage = ExportSkeletonBoneUsage(provider, requestAsset, searchPath)
                    }));
                }
                else if (string.Equals(action, "mapping_type", StringComparison.OrdinalIgnoreCase))
                {
                    if (!request.RootElement.TryGetProperty("typeName", out var typeNameElement))
                        throw new ArgumentException("mapping_type requires a typeName.");
                    var typeName = typeNameElement.GetString();
                    if (string.IsNullOrWhiteSpace(typeName) || !provider.MappingsForGame.Types.TryGetValue(typeName, out var mapping))
                    {
                        Console.WriteLine(JsonSerializer.Serialize(new
                        {
                            ok = false,
                            action,
                            error = $"No mapping was found for '{typeName}'.",
                            relatedTypes = provider.MappingsForGame.Types.Keys
                                .Where(key => key.Contains("Skeletal", StringComparison.OrdinalIgnoreCase))
                                .OrderBy(key => key, StringComparer.OrdinalIgnoreCase)
                                .ToArray()
                        }));
                        continue;
                    }
                    Console.WriteLine(JsonSerializer.Serialize(new
                    {
                        ok = true,
                        action,
                        typeName,
                        properties = DescribeMappingProperties(mapping),
                        relatedTypes = provider.MappingsForGame.Types.Keys
                            .Where(key => key.Contains("Skeletal", StringComparison.OrdinalIgnoreCase))
                            .OrderBy(key => key, StringComparer.OrdinalIgnoreCase)
                        .ToArray()
                    }));
                }
                else
                {
                    var requestOutput = requestRoot.GetProperty("ddsOutput").GetString()
                        ?? throw new ArgumentException("Texture request has no ddsOutput.");
                    var requestPackage = provider.LoadPackage(requestAsset);
                    var textureInfo = ExportTextureDds(provider, requestAsset, requestPackage, requestOutput);
                    Console.WriteLine(JsonSerializer.Serialize(new { ok = true, action = "texture", assetPath = requestAsset, dds = textureInfo }));
                }
            }
            catch (Exception requestError)
            {
                Console.WriteLine(JsonSerializer.Serialize(new
                {
                    ok = false,
                    error = requestError.Message,
                    errorDetails = requestError.ToString()
                }));
            }
            Console.Out.Flush();
        }
        return 0;
    }

    var pathFilter = args.Length > 3 ? args[3] : null;
    var files = provider.Files.Keys
        .OrderBy(path => path, StringComparer.OrdinalIgnoreCase)
        .Where(path => string.IsNullOrWhiteSpace(pathFilter) || path.Contains(pathFilter, StringComparison.OrdinalIgnoreCase))
        .ToArray();
    var assetPath = args.Length > 4 ? args[4] : null;
    object? asset = null;
    if (!string.IsNullOrWhiteSpace(assetPath))
    {
        var rawOutputArg = args.Length > 7 ? args[7] : null;
        var rawOutput = string.IsNullOrWhiteSpace(rawOutputArg) ? null : Path.GetFullPath(rawOutputArg);
        if (!string.IsNullOrWhiteSpace(rawOutput))
        {
            if (!provider.Files.TryGetValue(assetPath, out var gameFile))
                throw new FileNotFoundException("Virtual asset path was not found.", assetPath);
            var rawBytes = gameFile.Read(null);
            File.WriteAllBytes(rawOutput, rawBytes);
            asset = new { path = assetPath, rawByteLength = rawBytes.Length, rawOutput };
        }
        else
        {
        var summaryOnly = args.Length > 8 && string.Equals(args[8], "summary", StringComparison.OrdinalIgnoreCase);
        var package = provider.LoadPackage(assetPath);
        var importNames = Enumerable.Range(0, package.ImportMapLength)
            .Select(index => package.ResolvePackageIndex(new FPackageIndex(package, -index - 1)))
            .Select(resolved => resolved?.GetPathName() ?? resolved?.Name.ToString())
            .ToArray();
        object? dds = null;
        if (package.GetExports().OfType<UTexture2D>().Any())
        {
            var ddsOutputArg = args.Length > 6 ? args[6] : null;
            var ddsOutput = string.IsNullOrWhiteSpace(ddsOutputArg) ? null : Path.GetFullPath(ddsOutputArg);
            dds = ExportTextureDds(provider, assetPath, package, ddsOutput);
        }
        asset = new
        {
            path = assetPath,
            packageName = package.Name,
            canDeserialize = package.CanDeserialize,
            exportCount = package.ExportMapLength,
            importNames,
            dds,
            exports = package.GetExports().Select(export => new
            {
                name = export.Name,
                type = export.ExportType,
                fullName = export.GetFullName(),
                properties = summaryOnly
                    ? export.Properties.Select(property => property.ToString()).ToArray()
                    : export.Properties.Select(property => ConvertValue(property)).ToArray()
            }).ToArray()
        };
        }
    }
    var result = new
    {
        gameDirectory,
        packageDirectory = pakDirectory,
        oodleDll = oodlePath,
        usmap = usmapPath,
        pathFilter,
        gameProfile = gameProfile.Name,
        unrealVersion = gameProfile.Version.ToString(),
        mountResult = mountedCount,
        mountedVfsCount = provider.MountedVfs.Count,
        unloadedVfsCount = provider.UnloadedVfs.Count,
        mountedVfs = provider.MountedVfs.Select(v => new
        {
            type = v.GetType().FullName,
            encrypted = v.IsEncrypted,
            encryptedFileCount = v.EncryptedFileCount
        }).ToArray(),
        unloadedVfs = provider.UnloadedVfs.Select(v => new
        {
            type = v.GetType().FullName,
            encrypted = v.IsEncrypted,
            encryptedFileCount = v.EncryptedFileCount
        }).ToArray(),
        fileCount = files.Length,
        files,
        asset
    };
    var json = JsonSerializer.Serialize(result, new JsonSerializerOptions { WriteIndented = true });
    if (args.Length > 1 && args[1] != "-")
        File.WriteAllText(Path.GetFullPath(args[1]), json);
    else
        Console.WriteLine(json);
    return 0;
}
catch (Exception ex)
{
    Console.Error.WriteLine(ex.ToString());
    return 1;
}

/// <summary>
/// Reads the Rebirth skeletal render header plus the inline render layout used by
/// small environment rigs.  Larger meshes still use CUE4Parse's bulk decoder.
/// </summary>
sealed class RebirthSkeletalMeshUsageReader : UObject
{
    public FReferenceSkeleton ReferenceSkeleton { get; private set; } = null!;
    public List<FStaticLODModel> Lods { get; } = [];
    public List<Dictionary<string, object?>> CookedLodPayloads { get; } = [];
    public RebirthInlineSkeletalLod? InlineLod { get; private set; }
    public RebirthSkeletalColorStream? BulkColorStream { get; private set; }

    public override void Deserialize(FAssetArchive archive, long validPos)
    {
        base.Deserialize(archive, validPos);
        // Rebirth's cooked USkeletalMesh never tags the legacy mesh-wide
        // bHasVertexColors bool -- only LODInfo[lodIndex].bHasPerLODVertexColors
        // is present (the engine version this game is built on moved vertex-color
        // presence to a per-LOD flag so it can be stripped per-LOD). The cooked
        // LOD this reader decodes is always LOD 0. Reading the legacy flag as a
        // fallback keeps this working if some asset still carries it instead.
        var lodInfos = GetOrDefault<FStructFallback[]>("LODInfo", []);
        var hasVertexColors = GetOrDefault<bool>("bHasVertexColors") ||
            (lodInfos.Length > 0 && lodInfos[0].GetOrDefault<bool>("bHasPerLODVertexColors"));
        var vertexColorChannels = GetOrDefault<byte>("NumVertexColorChannels");
        var stripDataFlags = new FStripDataFlags(archive);
        _ = new CUE4Parse.UE4.Objects.Core.Math.FBoxSphereBounds(archive);
        _ = archive.ReadArray(() => new FSkeletalMaterial(archive));
        ReferenceSkeleton = new FReferenceSkeleton(archive);

        if (FSkeletalMeshCustomVersion.Get(archive) < FSkeletalMeshCustomVersion.Type.SplitModelAndRenderData)
        {
            var count = archive.Read<int>();
            for (var index = 0; index < count; index++)
                Lods.Add(new FStaticLODModel(archive, hasVertexColors));
            return;
        }

        if (!stripDataFlags.IsEditorDataStripped())
        {
            var editorLodCount = archive.Read<int>();
            for (var index = 0; index < editorLodCount; index++)
                _ = new FStaticLODModel(archive, hasVertexColors);
        }

        var isCooked = archive.ReadBoolean();
        if (!isCooked)
            return;

        // Rebirth retains UE4.26's desktop/mobile minimum-LOD setting.  It is
        // serialized between bCooked and the cooked LOD array.
        if (archive.Versions["SkeletalMesh.KeepMobileMinLODSettingOnDesktop"])
            _ = archive.Read<int>();

        var cookedLodCount = archive.Read<int>();
        if (cookedLodCount > 0)
            Lods.Add(ReadCookedLod(archive, CookedLodPayloads, hasVertexColors));

        // The remaining streamed LOD payload contains the changed vertex format,
        // including normal packing. LOD 0 provides the full mesh's used-bone set,
        // so deliberately stop before that payload.
        _ = vertexColorChannels;
    }

    private FStaticLODModel ReadCookedLod(
        FAssetArchive archive,
        List<Dictionary<string, object?>> cookedLodPayloads,
        bool hasVertexColors)
    {
        var lod = new FStaticLODModel();
        var stripDataFlags = new FStripDataFlags(archive);
        var isCookedOut = archive.ReadBoolean();
        var isInlined = archive.ReadBoolean();
        lod.RequiredBones = archive.ReadArray<short>();
        if (isCookedOut)
            return lod;

        lod.Sections = archive.ReadArray(() =>
        {
            var section = new FSkelMeshSection();
            section.SerializeRenderItem(archive);
            return section;
        });
        lod.ActiveBoneIndices = archive.ReadArray<short>();
        _ = archive.Read<uint>(); // BuffersSize
        if (isInlined)
        {
            var payloadOffset = archive.Position;
            InlineLod = ReadInlineLodPayload(archive, hasVertexColors);
            cookedLodPayloads.Add(new Dictionary<string, object?>
            {
                ["inlined"] = true,
                ["payloadOffset"] = payloadOffset,
                ["vertexCount"] = InlineLod.Positions.Length,
                ["indexCount"] = InlineLod.Indices.Length,
                ["hasVertexColors"] = hasVertexColors,
                ["colorCount"] = InlineLod.Colors.Length,
            });
            return lod;
        }
        var bulkData = new FByteBulkData(archive);
        var data = bulkData.Data;
        // FF7's bulk LOD header includes the color count and its byte offset.
        // Read it regardless of bHasVertexColors: that UProperty is omitted
        // from valid Rebirth meshes, while this serialized descriptor is the
        // actual source of truth for the render stream.
        var colorStream = TryReadRebirthBulkColorStream(
            archive, data, bulkData.Header.SizeOnDisk, bulkData.Header.OffsetInFile);
        if (colorStream is not null)
            BulkColorStream = colorStream;
        cookedLodPayloads.Add(new Dictionary<string, object?>
        {
            ["inlined"] = false,
            ["flags"] = bulkData.BulkDataFlags.ToString(),
            ["elementCount"] = bulkData.Header.ElementCount,
            ["sizeOnDisk"] = bulkData.Header.SizeOnDisk,
            ["offsetInFile"] = bulkData.Header.OffsetInFile,
            ["dataLength"] = data?.Length,
            ["colorDeclaredVertexCount"] = colorStream?.DeclaredCount ?? 0,
            ["colorDecodedVertexCount"] = colorStream?.Colors?.Length ?? 0,
            ["colorOffset"] = colorStream?.Offset ?? -1,
            ["colorCoverage"] = colorStream is null || colorStream.DeclaredCount == 0
                ? 0.0
                : (double)colorStream.Colors.Length / colorStream.DeclaredCount,
        });
        return lod;
    }

    private static RebirthSkeletalColorStream? TryReadRebirthBulkColorStream(
        FAssetArchive archive,
        byte[]? bulkData,
        long sizeOnDisk,
        long offsetInFile)
    {
        // CUE4Parse's FF7FStaticLodModel reads this fixed 161-byte metadata
        // descriptor to locate every bulk stream.  Its color branch is gated
        // on bHasVertexColors; preserve the descriptor parsing but remove that
        // gate.  A negative offset is the explicit "no color stream" marker.
        using var metadata = new FByteArchive("RebirthSkeletalLodMetadata", archive.ReadBytes(161));
        _ = metadata.Read<byte>();       // index stride
        _ = metadata.Read<int>();        // index count
        _ = metadata.Read<int>();        // UV channel count
        _ = metadata.Read<int>();        // vertex count
        _ = metadata.ReadBoolean();      // full precision UVs
        _ = metadata.ReadBoolean();      // high precision tangents
        _ = metadata.Read<int>();        // tangent offset
        _ = metadata.Read<int>();        // tangent stride
        _ = metadata.Read<int>();        // tangent count
        var colorCount = metadata.Read<int>();
        _ = metadata.ReadBoolean();
        _ = metadata.Read<int>();        // max bone influences
        _ = metadata.Read<int>();        // skin-weight stride
        _ = metadata.Read<int>();        // skin-weight count
        _ = metadata.ReadBoolean();      // 16-bit bone indices
        _ = metadata.Read<int>();        // skin-weight padding/offset field
        _ = metadata.ReadArray(archive.ReadFName);
        _ = metadata.Read<int>();        // position offset
        _ = metadata.Read<int>();
        _ = metadata.Read<int>();        // tangent stream offset
        _ = metadata.Read<int>();
        _ = metadata.Read<int>();        // UV stream offset
        _ = metadata.Read<int>();
        metadata.Position += 8;
        _ = metadata.Read<int>();        // skin-weight offset
        _ = metadata.Read<int>();
        var colorOffset = metadata.Read<int>();

        if (bulkData is null || colorCount <= 0 || colorOffset < 0)
            return new RebirthSkeletalColorStream(
                null, colorCount, colorOffset, checked((int)sizeOnDisk), sizeOnDisk, offsetInFile);
        if (colorOffset > bulkData.Length - checked(colorCount * sizeof(uint)))
            return null;

        using var bulk = new FByteArchive("RebirthSkeletalColorStream", bulkData, archive.Versions);
        bulk.Position = colorOffset;
        var colors = bulk.ReadArray<FColor>(colorCount);
        return new RebirthSkeletalColorStream(
            colors, colorCount, colorOffset, bulkData.Length, sizeOnDisk, offsetInFile);
    }

    private static RebirthInlineSkeletalLod ReadInlineLodPayload(FAssetArchive archive, bool hasVertexColors)
    {
        _ = new FStripDataFlags(archive);
        var indexBuffer = new FMultisizeIndexContainer(archive);
        var indices = indexBuffer.Buffer ?? throw new InvalidOperationException("Inline SkeletalMesh has no index stream.");
        var positions = new FPositionVertexBuffer(archive).Verts;

        _ = new FStripDataFlags(
            archive,
            FPackageFileVersion.CreateUE4Version(
                EUnrealEngineObjectUE4Version.STATIC_SKELETAL_MESH_SERIALIZATION_FIX));
        var uvChannelCount = archive.Read<int>();
        var attributeVertexCount = archive.Read<int>();
        var fullPrecisionUvs = archive.ReadBoolean();
        var highPrecisionTangents = archive.ReadBoolean();
        var tangentItemSize = archive.Read<int>();
        var tangentItemCount = archive.Read<int>();
        if (positions.Length == 0 || attributeVertexCount != positions.Length ||
            uvChannelCount is < 1 or > 8 || fullPrecisionUvs || highPrecisionTangents ||
            tangentItemSize != sizeof(uint) || tangentItemCount != positions.Length)
            throw new InvalidOperationException(
                "Unsupported inline Rebirth SkeletalMesh vertex metadata " +
                $"(vertices={attributeVertexCount}/{positions.Length}, uvs={uvChannelCount}, " +
                $"fullUV={fullPrecisionUvs}, highTangent={highPrecisionTangents}, " +
                $"tangents={tangentItemCount}x{tangentItemSize}).");
        var packedFrames = archive.ReadArray<uint>(tangentItemCount);

        var uvItemSize = archive.Read<int>();
        var uvItemCount = archive.Read<int>();
        if (uvItemSize != sizeof(ushort) * 2 || uvItemCount != positions.Length * uvChannelCount)
            throw new InvalidOperationException(
                $"Unsupported inline Rebirth SkeletalMesh UV metadata ({uvItemCount}x{uvItemSize}).");
        var uvChannels = Enumerable.Range(0, uvChannelCount)
            .Select(_ => new float[positions.Length][]).ToArray();
        for (var vertexIndex = 0; vertexIndex < positions.Length; vertexIndex++)
        for (var channelIndex = 0; channelIndex < uvChannelCount; channelIndex++)
            uvChannels[channelIndex][vertexIndex] =
            [
                (float)archive.Read<Half>(),
                (float)archive.Read<Half>(),
            ];

        // Vertex colors sit between the tangent/UV block and the skin-weight
        // buffer, matching the GPU vertex-factory declaration order. The mesh's
        // bHasVertexColors flag (read once for the whole USkeletalMesh) gates
        // whether this buffer is present at all, unlike the static-mesh
        // ColorVertexBuffer, which always writes a (possibly empty) header.
        var colors = Array.Empty<FColor>();
        if (hasVertexColors)
        {
            var colorBuffer = new FColorVertexBuffer(archive);
            if (colorBuffer.Data.Length != 0 && colorBuffer.Data.Length != positions.Length)
                throw new InvalidOperationException(
                    $"Inline Rebirth SkeletalMesh color count {colorBuffer.Data.Length} does not match {positions.Length} vertices.");
            colors = colorBuffer.Data;
        }

        var weights = new FSkinWeightVertexBuffer(archive, false).Weights;
        if (weights.Length != positions.Length)
            throw new InvalidOperationException(
                $"Inline Rebirth SkeletalMesh weight count {weights.Length} does not match {positions.Length} vertices.");
        return new RebirthInlineSkeletalLod(indices, positions, packedFrames, uvChannels, weights, colors);
    }
}

sealed class RebirthInlineSkeletalLod(
    uint[] indices,
    FVector[] positions,
    uint[] packedFrames,
    float[][][] uvChannels,
    FSkinWeightInfo[] weights,
    FColor[] colors)
{
    public uint[] Indices { get; } = indices;
    public FVector[] Positions { get; } = positions;
    public uint[] PackedFrames { get; } = packedFrames;
    public float[][][] UvChannels { get; } = uvChannels;
    public FSkinWeightInfo[] Weights { get; } = weights;
    public FColor[] Colors { get; } = colors;
}

sealed class RebirthSkeletalColorStream(
    FColor[]? colors,
    int declaredCount,
    int offset,
    int bulkByteLength,
    long sizeOnDisk,
    long offsetInFile)
{
    public FColor[]? Colors { get; } = colors;
    public int DeclaredCount { get; } = declaredCount;
    public int Offset { get; } = offset;
    public int BulkByteLength { get; } = bulkByteLength;
    public long SizeOnDisk { get; } = sizeOnDisk;
    public long OffsetInFile { get; } = offsetInFile;
}

static class PropertyConversionContext
{
    [ThreadStatic]
    public static Func<FPackageIndex, object?>? PackageIndexConverter;
}
