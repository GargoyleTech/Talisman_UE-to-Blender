using CUE4Parse.FileProvider;
using CUE4Parse.Compression;
using CUE4Parse.GameTypes.FF7.Assets.Exports;
using CUE4Parse.GameTypes.FF7.Assets.Objects.Properties;
using CUE4Parse.GameTypes.FF7.Objects;
using CUE4Parse.MappingsProvider;
using CUE4Parse.MappingsProvider.Usmap;
using CUE4Parse.UE4.Versions;
using CUE4Parse.UE4.Assets;
using CUE4Parse.UE4.Assets.Exports;
using CUE4Parse.UE4.Assets.Readers;
using CUE4Parse.UE4.Objects.UObject;
using CUE4Parse.UE4.Readers;
using Newtonsoft.Json;
using Serilog;
using Serilog.Core;
using Serilog.Events;

// Diagnostic only: use CUE4Parse's own serializer to distinguish native fields
// from the generic property list emitted by the main package bridge.
Log.Logger = new LoggerConfiguration().MinimumLevel.Debug().WriteTo.Sink(new ProbeLog()).CreateLogger();
ObjectTypeRegistry.RegisterClass("NiagaraSystem", typeof(ProbeNiagaraSystem));
ObjectTypeRegistry.RegisterClass("EndDataObjectCutSceneList", typeof(ProbeEndDataObject));
ObjectTypeRegistry.RegisterClass("EndDataObjectCutSceneListLevel", typeof(ProbeEndDataObject));
OodleHelper.Initialize(args[1]);
using var provider = new DefaultFileProvider(args[0], SearchOption.AllDirectories,
    new VersionContainer(EGame.GAME_FinalFantasy7Rebirth));
provider.MappingsContainer = new FileUsmapTypeMappingsProvider(args[2]);
provider.Initialize();
provider.Mount();
provider.PostMount();
foreach (var file in provider.Files.Values
             .Where(file => file.IsUePackage &&
                            file.Path.Contains("GOLDE_0500", StringComparison.OrdinalIgnoreCase))
             .OrderBy(file => file.Path, StringComparer.OrdinalIgnoreCase))
{
    Console.WriteLine("GOLDE_0500 " + file.Path);
}
foreach (var file in provider.Files.Values
             .Where(file => file.IsUePackage &&
                            file.Path.Contains("CutSceneList", StringComparison.OrdinalIgnoreCase))
             .OrderBy(file => file.Path, StringComparer.OrdinalIgnoreCase))
{
    Console.WriteLine("CUTSCENE_LIST " + file.Path);
}
foreach (var typeName in new[] {
    "NiagaraSystem", "NiagaraEmitter", "NiagaraScript", "NiagaraMeshRendererProperties",
    "NiagaraSpriteRendererProperties", "NiagaraVariable", "NiagaraVariableBase",
    "VFXNiagaraDataInterfaceFunctionLibrary", "VFXNiagaraDataInterfaceMaterial",
    "VFXNiagaraDataInterfaceMaterialParameter", "VFXNiagaraDataInterfaceSpawnEmitter",
    "VFXNiagaraDataInterfaceNoiseCurve", "EndNiagaraDataInterfaceTransformContext",
    "EndNiagaraDataInterfaceFunctionLibrary", "EndNiagaraDataInterfaceLight",
    "EndNiagaraDataInterfaceTrail", "EndNiagaraDataInterfaceLensFlare",
    "EndNiagaraDataInterfacePostProcessParameter",
    "NiagaraScriptExecutionParameterStore", "NiagaraTypeDefinition", "NiagaraEmitterHandle",
    "NiagaraSystemCompiledData", "NiagaraUserRedirectionParameterStore", "NiagaraParameterStore",
    "NiagaraMeshMaterialOverride", "NiagaraMaterialAttributeBinding", "NiagaraVariableWithOffset",
    "NiagaraRendererMaterialParameters", "NiagaraRendererMaterialParameter", "NiagaraDataSetID",
    "NiagaraDataSetCompiledData", "NiagaraVMExecutableData", "NiagaraScriptDataInterfaceInfo" })
{
    if (!provider.MappingsForGame.Types.TryGetValue(typeName, out var mapping))
        continue;
    Console.WriteLine("MAPPING " + typeName + " " + JsonConvert.SerializeObject(Describe(mapping)));
    if (typeName == "NiagaraSystem")
    {
        Console.WriteLine("SYSTEM_LOOKUP " + JsonConvert.SerializeObject(
            Enumerable.Range(0, 80).Select(index => DescribeLookup(mapping, index))));
    }
}
var package = provider.LoadPackage(args[3]);
if (package is IoPackage ioPackage)
{
    for (var index = 0; index < ioPackage.ExportMap.Length; index++)
    {
        var entry = ioPackage.ExportMap[index];
        var classObject = ioPackage.ResolveObjectIndex(entry.ClassIndex);
        var superObject = ioPackage.ResolveObjectIndex(entry.SuperIndex);
        Console.WriteLine($"EXPORT_MAP {index} name={ioPackage.CreateFNameFromMappedName(entry.ObjectName)} " +
            $"offset={entry.CookedSerialOffset} size={entry.CookedSerialSize} " +
            $"class={classObject?.GetFullName(includeClassPackage: true) ?? entry.ClassIndex.ToString()} " +
            $"super={superObject?.GetFullName(includeClassPackage: true) ?? entry.SuperIndex.ToString()}");
    }
}
var exports = package.GetExports().ToArray();
File.WriteAllText(args[4], JsonConvert.SerializeObject(exports, Formatting.Indented));
foreach (var export in exports)
    Console.WriteLine($"{export.ExportType} {export.Name}: clr={export.GetType().FullName}, taggedProperties={export.Properties.Count}");

static object Describe(Struct mapping) => new {
    mapping.Name, mapping.SuperType, mapping.PropertyCount,
    totalPropertyCount = mapping.CountProperties(includeSuper: true),
    properties = mapping.Properties.OrderBy(entry => entry.Key).Select(entry => new {
        index = entry.Key,
        entry.Value.Name,
        type = DescribeType(entry.Value.MappingType),
    }),
};

static object? DescribeType(PropertyType? type) => type is null ? null : new {
    type.Type, type.StructType, type.EnumName,
    inner = DescribeType(type.InnerType), value = DescribeType(type.ValueType),
};

static object DescribeLookup(Struct mapping, int index)
{
    var found = mapping.TryGetValue(index, out var property);
    return new { index, found, name = found ? property.Name : null };
}

sealed class ProbeLog : ILogEventSink
{
    public void Emit(LogEvent entry)
    {
        if (entry.Level < LogEventLevel.Warning) return;
        Console.Error.WriteLine(entry.RenderMessage());
        if (entry.Exception != null) Console.Error.WriteLine(entry.Exception);
    }
}

sealed class ProbeEndDataObject : UObject
{
    public Dictionary<string, FF7StructProperty> DataTable = [];
    public List<string> StructDefinition = [];

    protected override void WriteJson(JsonWriter writer, JsonSerializer serializer)
    {
        base.WriteJson(writer, serializer);
        writer.WritePropertyName(nameof(StructDefinition));
        serializer.Serialize(writer, StructDefinition);
        writer.WritePropertyName(nameof(DataTable));
        serializer.Serialize(writer, DataTable);
    }

    public override void Deserialize(FAssetArchive Ar, long validPos)
    {
        base.Deserialize(Ar, validPos);

        var headerOffset = Ar.Position;
        var frozenSize = Ar.Read<uint>();
        var serializedSize = Ar.Read<uint>();
        var format = Ar.Read<ushort>();
        var padding = Ar.Read<ushort>();
        Console.WriteLine($"CUTSCENE_DATA headerOffset={headerOffset} frozenSize={frozenSize} serializedSize={serializedSize} format={format} padding={padding}");

        Ar.Position += padding;
        var frozenObject = Ar.ReadBytes((int)frozenSize);
        var patchOffset = Ar.Position;
        var vtableGroups = Ar.Read<int>();
        var scriptNameGroups = Ar.Read<int>();
        var minimalNameGroups = Ar.Read<int>();
        Console.WriteLine($"CUTSCENE_DATA patchOffset={patchOffset} vtableGroups={vtableGroups} scriptNameGroups={scriptNameGroups} minimalNameGroups={minimalNameGroups}");

        // Unlike UE's shader-memory images, Rebirth writes every name patch as
        // FName + int32 count + count * int32 frozen-object offsets.  CUE4Parse
        // currently reads these as FString records, which moves the archive out
        // of alignment before the table body is available.
        for (var i = 0; i < vtableGroups; i++)
        {
            Ar.Position += sizeof(ulong);
            var count = Ar.Read<int>();
            Ar.Position += count * sizeof(int) * 2;
        }

        var names = new Dictionary<int, (FName Name, bool IsScriptName)>();
        ReadNamePatchGroups(Ar, scriptNameGroups, true, names);
        ReadNamePatchGroups(Ar, minimalNameGroups, false, names);
        Console.WriteLine($"CUTSCENE_DATA namePatches={names.Count}");

        var inner = new FMemoryMappedImageArchive(new FByteArchive("GOLDE CutSceneList", frozenObject, Ar.Versions))
        {
            Names = names,
        };
        var keys = inner.ReadTSparseArray(() => new FKey(inner), 20).ToArray();
        _ = inner.ReadArray<int>();
        var definition = inner.ReadArray(() => new FF7Property(inner));
        StructDefinition = definition.Select(property => $"{property.Name.Text}:{property.UnderlyingType}").ToList();
        var values = inner.ReadArray(() => inner.DeserializeProperties(definition));
        Console.WriteLine($"CUTSCENE_DATA rows={keys.Length} values={values.Length} fields={definition.Length}");

        for (var index = 0; index < Math.Min(keys.Length, values.Length); index++)
        {
            var rowName = keys[index].Name.Text;
            DataTable[rowName] = values[index];
            if (rowName.Contains("GOLDE_0500", StringComparison.OrdinalIgnoreCase))
                Console.WriteLine("CUTSCENE_DATA row " + rowName + " = " + JsonConvert.SerializeObject(values[index]));
        }
    }

    private static void ReadNamePatchGroups(
        FAssetArchive archive,
        int groupCount,
        bool isScriptName,
        Dictionary<int, (FName Name, bool IsScriptName)> names)
    {
        for (var groupIndex = 0; groupIndex < groupCount; groupIndex++)
        {
            var name = archive.ReadFName();
            var patchCount = archive.Read<int>();
            for (var patchIndex = 0; patchIndex < patchCount; patchIndex++)
                names[archive.Read<int>()] = (name, isScriptName);
        }
    }
}
