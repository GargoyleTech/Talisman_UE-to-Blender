using CUE4Parse.UE4.Assets.Exports.Animation;
using CUE4Parse.UE4.Assets.Readers;
using CUE4Parse.UE4.Objects.Core.Serialization;
using CUE4Parse.UE4.Versions;

namespace Ff7r.Remake;

/// <summary>
/// Remake's cooked AnimSequence writes an obsolete Framework custom-version
/// value while retaining the UE 4.18 compressed-data layout.
/// </summary>
/// <remarks>
/// CUE4Parse normally trusts that custom version and consequently takes its
/// pre-DDC animation branch, which only reads a byte stream and leaves all
/// track offsets empty.  Correct the version only while this export is read,
/// allowing the stock UE 4.18 decoder and converter to do the rest.
/// </remarks>
public sealed class URemakeAnimSequence : UAnimSequence
{
    /// <summary>Diagnostic proof that the UE4.18 layout override was active.</summary>
    public int EffectiveFrameworkVersion;
    public int EffectiveFrameworkVersionAfterRead;

    public override void Deserialize(FAssetArchive Ar, long validPos)
    {
        var originalVersions = Ar.Versions.CustomVersions;
        var inheritedVersions = originalVersions?.Versions ?? [];
        var fixedVersions = inheritedVersions
            .Where(version => version.Key != FFrameworkObjectVersion.GUID)
            .Append(new FCustomVersion(
                FFrameworkObjectVersion.GUID,
                (int) FFrameworkObjectVersion.Type.UserDefinedStructsBlueprintVisible));
        Ar.Versions.CustomVersions = new FCustomVersionContainer(fixedVersions);
        try
        {
            EffectiveFrameworkVersion = (int) FFrameworkObjectVersion.Get(Ar);
            base.Deserialize(Ar, validPos);
            EffectiveFrameworkVersionAfterRead = (int) FFrameworkObjectVersion.Get(Ar);
        }
        finally
        {
            Ar.Versions.CustomVersions = originalVersions;
        }
    }
}
