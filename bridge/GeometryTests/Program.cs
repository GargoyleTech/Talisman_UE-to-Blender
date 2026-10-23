using System.Reflection;
using System.Text.Json;
using CUE4Parse.FileProvider.Objects;
using CUE4Parse.Compression;
using CUE4Parse.UE4.Assets;
using CUE4Parse.UE4.Assets.Objects;
using CUE4Parse.UE4.Readers;
using CUE4Parse.UE4.Versions;

static void Check(bool value, string message)
{
    if (!value) throw new Exception(message);
}

var directory = Path.GetFullPath(args[0]);
Directory.CreateDirectory(directory);
var mesh = new Dictionary<string, object?>
{
    ["name"] = "BinaryFixture", ["vertexCount"] = 3, ["triangleCount"] = 1,
    ["positions"] = new[] { new[] { 0f, 0f, 0f }, new[] { 1f, 0f, 0f }, new[] { 0f, 1f, 0f } },
    ["normals"] = Enumerable.Repeat(new[] { 0f, 0f, 1f }, 3).ToArray(),
    ["tangents"] = Enumerable.Repeat(new[] { 1f, 0f, 0f, -1f }, 3).ToArray(),
    ["uvChannels"] = new object[] { new[] { new[] { 0f, 0f }, new[] { 1f, 0f }, new[] { 0f, 1f } } },
    ["colors"] = new[] { new[] { 255, 0, 0, 128 }, new[] { 0, 255, 0, 64 }, new[] { 0, 0, 255, 255 } },
    ["indices"] = new uint[] { 0, 1, 2 },
    ["sections"] = new[] { new { materialIndex = 0, firstIndex = 0, triangleCount = 1 } },
    ["boneNames"] = new[] { "root", "tip" },
    ["weights"] = new object[] { new[] { new[] { 0f, .25f }, new[] { 1f, .75f } },
        Array.Empty<float[]>(), new[] { new[] { 1f, 1f } } },
};
var binary = BinaryGeometryExporter.Export(mesh, directory);
Check(!binary.ContainsKey("positions") && !binary.ContainsKey("weights"), "Numeric data remained in JSON");
Check(mesh.ContainsKey("positions"), "Legacy payload was mutated");
File.WriteAllText(Path.Combine(directory, "fixture.json"), JsonSerializer.Serialize(binary));
var manifest = JsonSerializer.SerializeToElement(binary).GetProperty("binaryGeometry");
var geometryDirectory = manifest.GetProperty("directory").GetString()!;
Check(File.ReadAllBytes(Path.Combine(geometryDirectory, "weightOffsets.bin"))
    .SequenceEqual(new byte[] { 0, 0, 0, 0, 2, 0, 0, 0, 2, 0, 0, 0, 3, 0, 0, 0 }),
    "Ragged offsets changed");
using (var reader = new BinaryReader(File.OpenRead(Path.Combine(geometryDirectory, "weightPairs.bin"))))
    foreach (var expected in new[] { 0f, .25f, 1f, .75f, 1f, 1f })
        Check(reader.ReadSingle() == expected, "Skin influence changed");
Check(File.ReadAllBytes(Path.Combine(geometryDirectory, "colors.bin"))
    .SequenceEqual(new byte[] { 255, 0, 0, 128, 0, 255, 0, 64, 0, 0, 255, 255 }), "Colors changed");
var before = Directory.GetDirectories(directory).Length;
var broken = new Dictionary<string, object?>(mesh) { ["indices"] = new[] { 0, 1, 9 } };
try { BinaryGeometryExporter.Export(broken, directory); throw new Exception("Accepted invalid index"); }
catch (InvalidDataException) { }
Check(Directory.GetDirectories(directory).Length == before, "Partial geometry directory leaked");

using var provider = new CachedFileProvider(directory, SearchOption.TopDirectoryOnly,
    new VersionContainer(EGame.GAME_UE4_27), StringComparer.OrdinalIgnoreCase);
var package = DispatchProxy.Create<IPackage, EmptyPackage>();
var file = new FixtureFile("Map.umap");
var reads = 0;
IPackage Read() { reads++; return package; }
Check(ReferenceEquals(provider.GetOrLoad(file, Read), provider.GetOrLoad(file, Read)) && reads == 1,
    "Repeated package was loaded again");
for (var i = 0; i < 40; i++) provider.GetOrLoad(new FixtureFile($"Mesh{i}.uasset"), Read);
using (var stats = JsonDocument.Parse(JsonSerializer.Serialize(provider.PackageCacheStats())))
    Check(stats.RootElement.GetProperty("entries").GetInt32() == 32 &&
        stats.RootElement.GetProperty("evictions").GetInt64() == 9, "LRU entry bound failed");
provider.GetOrLoad(file, Read);
Check(reads == 42, "LRU eviction did not reload its package");
provider.ClearPackageCache();
var failed = new FixtureFile("Failed.uasset");
try { provider.GetOrLoad(failed, () => throw new IOException("fixture")); }
catch (IOException) { }
provider.GetOrLoad(failed, Read);
var huge = new FixtureFile("Huge.umap", 300L * 1024 * 1024);
provider.GetOrLoad(huge, Read); provider.GetOrLoad(huge, Read);
Check(reads == 45, "Failure or oversize request was cached");
provider.ClearPackageCache();
for (var i = 0; i < 3; i++) provider.GetOrLoad(new FixtureFile($"Big{i}.umap", 100L * 1024 * 1024), Read);
using (var stats = JsonDocument.Parse(JsonSerializer.Serialize(provider.PackageCacheStats())))
    Check(stats.RootElement.GetProperty("entries").GetInt32() == 2, "Serialized byte bound failed");
provider.ClearPackageCache();
Console.WriteLine("GEOMETRY_AND_PACKAGE_CACHE_OK");

var inventoryCache = new MaterialInventoryCache();
var inventoriesBuilt = 0;
MaterialInventoryCache.Inventory Inventory() { inventoriesBuilt++; return new("material", "type", [new("/Game/T.T", "Albedo")], ["/Game/Parent.Parent"], []); }
var inventory = inventoryCache.GetOrAdd("object:/Game/M.M", Inventory);
Check(ReferenceEquals(inventory, inventoryCache.GetOrAdd("OBJECT:/game/m.m", Inventory)) && inventoriesBuilt == 1,
    "Shared inventory was rebuilt or its path matching changed");
for (var i = 0; i < 4100; i++) inventoryCache.GetOrAdd($"object:{i}", Inventory);
inventoryCache.GetOrAdd("object:/Game/M.M", Inventory);
Check(inventoriesBuilt == 4102, "Material inventory bound did not evict old entries");
var graphCache = new MaterialInventoryCache();
graphCache.CacheResolvedGraph(new Dictionary<string, MaterialInventoryCache.Inventory>
{
    ["parent"] = new("Parent", "Material", [new("/Game/T.T", "BaseColor")], ["function"], []),
    ["function"] = new("Function", "MaterialFunction", [new("/Game/N.N", "Normal"), new("/Game/T.T")], ["parent"], []),
    ["incomplete"] = new("Incomplete", "Material", [], ["missing"], []),
});
Check(graphCache.TryGet("resolved:parent", out var resolvedGraph) && resolvedGraph.Textures.Length == 2 &&
    resolvedGraph.Dependencies.Length == 0 && resolvedGraph.Textures.Any(t => t.Label == "BaseColor"),
    "Shared/cyclic material closure lost a parameter label or dependency texture");
Check(!graphCache.TryGet("resolved:incomplete", out _), "An incomplete material traversal was cached as complete");
var sourceFile = new FixtureFile("Source.uasset");
Check(ReferenceEquals(provider.ReadSource(sourceFile), provider.ReadSource(sourceFile)) && sourceFile.ReadCount == 1,
    "Primary source buffer was decompressed twice");
provider.ClearPackageCache();
provider.ReadSource(sourceFile);
Check(sourceFile.ReadCount == 2, "Source cleanup retained raw bytes");
var transform = new CUE4Parse.UE4.Objects.Core.Math.FTransform(
    new CUE4Parse.UE4.Objects.Core.Math.FQuat(0, 0, 0, 1),
    new CUE4Parse.UE4.Objects.Core.Math.FVector(1, 2, 3),
    new CUE4Parse.UE4.Objects.Core.Math.FVector(4, 5, 6));
var instances = JsonSerializer.SerializeToElement(InstanceTransformExporter.Export(new[] { transform }, directory)).GetProperty("binaryInstances");
using (var reader = new BinaryReader(File.OpenRead(Path.Combine(directory, instances.GetProperty("file").GetString()!))))
    foreach (var expected in new[] { 1f, 2f, 3f, 1f, 0f, 0f, 0f, 4f, 5f, 6f })
        Check(reader.ReadSingle() == expected, "Native instance stream layout changed");
using (var batch = new InstanceTransformExporter(directory))
{
    var first = JsonSerializer.SerializeToElement(batch.Write(new[] { transform })).GetProperty("binaryInstances");
    var second = JsonSerializer.SerializeToElement(batch.Write(new[] { transform, transform })).GetProperty("binaryInstances");
    Check(first.GetProperty("file").GetString() == second.GetProperty("file").GetString() &&
        second.GetProperty("byteOffset").GetInt64() == 40, "Foliage components did not share a correctly bounded stream");
    batch.Complete();
    Check(new FileInfo(Path.Combine(directory, first.GetProperty("file").GetString()!)).Length == 120,
        "Batched foliage stream has an incorrect byte length");
}
Console.WriteLine("MATERIAL_SOURCE_AND_INSTANCE_CACHE_OK");

// Exercise the bundled bridge's actual property converter. Moss ships a fern
// with ComponentVelocity=(NaN, NaN, -Infinity); unrelated placement data must
// remain usable and its JSON must still parse with the default strict reader.
var bridgeAssembly = Assembly.LoadFrom(Path.Combine(AppContext.BaseDirectory, "TalismanGameAssetBridge.dll"));
var propertyConverter = bridgeAssembly.GetType("Program")!
    .GetMethods(BindingFlags.NonPublic | BindingFlags.Static)
    .Single(method => method.Name.Contains("g__ConvertValue|", StringComparison.Ordinal));
object? ConvertProperty(object value) => propertyConverter.Invoke(null, [value, 0]);
var previousCulture = System.Globalization.CultureInfo.CurrentCulture;
try
{
    System.Globalization.CultureInfo.CurrentCulture = System.Globalization.CultureInfo.GetCultureInfo("fr-FR");
    var actor = new Dictionary<string, object?>
    {
        ["Name"] = "SM_Fern_0",
        ["Properties"] = new Dictionary<string, object?>
        {
            ["ComponentVelocity"] = ConvertProperty(new CUE4Parse.UE4.Objects.Core.Math.FVector(
                float.NaN, float.NaN, float.NegativeInfinity)),
            ["RelativeLocation"] = ConvertProperty(new CUE4Parse.UE4.Objects.Core.Math.FVector(
                2071.8198f, 222.32147f, 502.24307f)),
            ["SpecialNumbers"] = ConvertProperty(new object[]
            {
                float.PositiveInfinity, double.NaN, double.PositiveInfinity, double.NegativeInfinity,
                15470.784f, double.MaxValue,
            }),
        },
    };
    using var document = JsonDocument.Parse(JsonSerializer.Serialize(new { ok = true, actors = new[] { actor } }));
    var properties = document.RootElement.GetProperty("actors")[0].GetProperty("Properties");
    var velocity = properties.GetProperty("ComponentVelocity");
    Check(velocity.GetProperty("X").GetString() == "NaN" &&
        velocity.GetProperty("Y").GetString() == "NaN" &&
        velocity.GetProperty("Z").GetString() == "-Infinity", "Non-finite vector values were not preserved as text");
    var location = properties.GetProperty("RelativeLocation");
    Check(location.GetProperty("X").GetSingle() == 2071.8198f &&
        location.GetProperty("Y").GetSingle() == 222.32147f &&
        location.GetProperty("Z").GetSingle() == 502.24307f, "Finite placement values changed");
    var numbers = properties.GetProperty("SpecialNumbers");
    Check(numbers[0].GetString() == "Infinity" && numbers[1].GetString() == "NaN" &&
        numbers[2].GetString() == "Infinity" && numbers[3].GetString() == "-Infinity",
        "Non-finite scalar values changed with culture or precision");
    Check(numbers[4].GetSingle() == 15470.784f && numbers[5].GetDouble() == double.MaxValue,
        "Finite HDR or double values were clamped or converted to text");
}
finally { System.Globalization.CultureInfo.CurrentCulture = previousCulture; }
Console.WriteLine("NONFINITE_PROPERTY_JSON_OK");

// Hi-Fi Rush's native subclasses deserialize as plain UObject. Their serialized
// mesh references still use the ordinary UE contract and must reach placement.
var componentClassifier = bridgeAssembly.GetType("GenericUnreal")!
    .GetMethod("ComponentType", BindingFlags.Public | BindingFlags.Static)!;
string? ClassifyComponent(string className)
{
    var component = new CUE4Parse.UE4.Assets.Exports.UObject
    {
        Class = new ResolvedLoadedObject(new CUE4Parse.UE4.Objects.UObject.UScriptClass(className)),
    };
    return (string?)componentClassifier.Invoke(null, [component]);
}
Check(ClassifyComponent("HbkStaticMeshComponent") == "StaticMeshComponent",
    "Custom static components were silently omitted");
Check(ClassifyComponent("HbkSkeletalMeshComponent") == "SkeletalMeshComponent",
    "Custom skeletal components were silently omitted");
  Check(ClassifyComponent("HbkSplineMeshComponent") == "SplineMeshComponent" &&
      ClassifyComponent("SplineMeshComponent") == "SplineMeshComponent",
    "Spline geometry was incorrectly exported as a rigid placement");
  Check(ClassifyComponent("SplineComponent") == "SplineComponent" &&
      ClassifyComponent("TngSplineComponent") == "SplineComponent",
      "Authored spline paths were silently omitted");
Check(ClassifyComponent("SQEX_SplineComponent") == "SplineComponent" &&
      ClassifyComponent("SQEX_SplineRootComponent") == "SceneComponent" &&
      ClassifyComponent("LevelStreamingKismet") == "LevelStreamingKismet",
    "SQEX spline hierarchy or legacy sublevel references were omitted");
Check(ClassifyComponent("PathComponent") == "SplineComponent" &&
      ClassifyComponent("PathFollowingComponent") is null &&
      ClassifyComponent("CustomPathComponent") is null,
    "Authored PathRuntime curves must import without treating pathfinding systems as splines");
Check(ClassifyComponent("EndSplineBrushComponent") == "SplineComponent" &&
      ClassifyComponent("EndStreamingVolume") is null,
    "Rebirth brush outlines must reach curve import without converting volume actors to paths");
Check(ClassifyComponent("CustomInstancedStaticMeshComponent") is null,
    "An unparsed native instance stream was collapsed to a single mesh");
Check(ClassifyComponent("HbkStaticMeshActor") is null &&
    ClassifyComponent("HbkGimmickAnimationComponent") is null,
    "Non-mesh actors or behavior components were classified as mesh components");
Console.WriteLine("CUSTOM_MAP_COMPONENT_TYPES_OK");

public class EmptyPackage : DispatchProxy
{
    protected override object? Invoke(MethodInfo? method, object?[]? args) => null;
}

sealed class FixtureFile : GameFile
{
    public int ReadCount;
    public FixtureFile(string path, long size = 100) : base(path, size) { }
    public override bool IsEncrypted => false;
    public override CompressionMethod CompressionMethod => CompressionMethod.None;
    public override byte[] Read(FByteBulkDataHeader? header = null) { ReadCount++; return new byte[Size]; }
    public override FArchive CreateReader(FByteBulkDataHeader? header = null) => throw new NotSupportedException();
}
