using System.Reflection;
using CUE4Parse.UE4.Assets.Exports;
using CUE4Parse.UE4.Assets.Exports.StaticMesh;
using CUE4Parse.UE4.Assets.Readers;
using CUE4Parse.UE4.Objects.Core.Misc;
using CUE4Parse.UE4.Objects.Engine;
using CUE4Parse.UE4.Objects.UObject;
using CUE4Parse.UE4.Versions;

/// <summary>Hi-Fi Rush omits BodySetup when its bTngUseBodySetup property is false.</summary>
internal sealed class UHifiRushStaticMesh : UStaticMesh
{
    private static readonly Dictionary<string, PropertyInfo> NativeProperties = typeof(UStaticMesh)
        .GetProperties(BindingFlags.Public | BindingFlags.Instance).Where(p => p.SetMethod is not null)
        .ToDictionary(p => p.Name);
    private static readonly PropertyInfo GuidProperty = typeof(UObject).GetProperty(nameof(ObjectGuid))!;

    public override void Deserialize(FAssetArchive ar, long validPos)
    {
        if (ar.Game != EGame.GAME_UE4_27)
        {
            base.Deserialize(ar, validPos);
            return;
        }
        using var propertiesReader = (FAssetArchive)ar.Clone();
        var properties = new UObject { Name = Name, Class = Class, Outer = Outer, Flags = Flags };
        properties.Deserialize(propertiesReader, validPos);
        if (!properties.TryGetValue(out bool useBodySetup, "bTngUseBodySetup") || useBodySetup)
        {
            base.Deserialize(ar, validPos);
            return;
        }

        Properties = properties.Properties;
        GuidProperty.SetValue(this, properties.ObjectGuid);
        ar.Position = propertiesReader.Position;
        var stripFlags = new FStripDataFlags(ar);
        var cooked = ar.ReadBoolean();
        if (!cooked || !stripFlags.IsEditorDataStripped() || !ar.IsFilterEditorOnly)
            throw new NotSupportedException("Hi-Fi Rush's optional BodySetup reader requires cooked UE4.27 mesh data.");

        // The stock reader consumes BodySetup unconditionally. Here the next
        // index is NavCollision; consuming another index misaligns every LOD.
        Set(nameof(bCooked), true);
        Set(nameof(HasTangents), true);
        Set(nameof(BodySetup), new FPackageIndex());
        Set(nameof(NavCollision), ar.Versions["StaticMesh.HasNavCollision"] ? new FPackageIndex(ar) : new FPackageIndex());
        Set(nameof(LightingGuid), ar.Read<FGuid>());
        Set(nameof(Sockets), ar.ReadArray(() => new FPackageIndex(ar)));
        Set(nameof(LODForCollision), GetOrDefault(nameof(LODForCollision), 0));
        Set(nameof(RenderData), new FStaticMeshRenderData(ar));

        if (ar.ReadBoolean()) // bHasOccluderData
        {
            ar.SkipFixedArray(12); // FVector vertices
            ar.SkipFixedArray(2); // uint16 indices
        }
        var speedTree = ar.ReadBoolean();
        var materials = GetOrDefault<FStaticMaterial[]>("StaticMaterials", []);
        if (speedTree)
            ar.Position = validPos;
        else if (FEditorObjectVersion.Get(ar) >= FEditorObjectVersion.Type.RefactorMeshEditorMaterials)
        {
            var nativeMaterials = ar.ReadArray(() => new FStaticMaterial(ar));
            if (nativeMaterials.Length > 0) materials = nativeMaterials;
        }
        if (ar.Position > validPos)
            throw new InvalidDataException("Hi-Fi Rush StaticMesh data exceeded its export boundary.");
        Set(nameof(StaticMaterials), materials);
        Set(nameof(Materials), materials.Select(m => m.MaterialInterface).ToArray());
    }

    // CUE4Parse exposes these native fields with private setters. Keep its
    // standard mesh/LOD types so all existing export and material paths work.
    private void Set(string name, object? value) => NativeProperties[name].SetValue(this, value);
}
