using CUE4Parse.MappingsProvider;
using CUE4Parse.UE4.Assets.Exports;
using CUE4Parse.UE4.Assets.Objects;
using CUE4Parse.UE4.Assets.Objects.Properties;
using CUE4Parse.UE4.Assets.Objects.Unversioned;
using CUE4Parse.UE4.Assets.Readers;

/// <summary>
/// Diagnostic replacement for CUE4Parse's NiagaraSystem reader.  It records
/// the exact property index and byte range before handing each field to the
/// normal CUE4Parse property decoder.  This tells us whether an absent schema
/// entry or an earlier bad type definition first loses alignment.
/// </summary>
public sealed class ProbeNiagaraSystem : UObject
{
    public override void Deserialize(FAssetArchive ar, long validPos)
    {
        Properties = new List<FPropertyTag>();
        var headerStart = ar.Position;
        var header = new FUnversionedHeader(ar);
        Console.Error.WriteLine(
            $"NIAGARA_SYSTEM_HEADER start={headerStart} end={ar.Position} " +
            $"fragments={string.Join(',', header.Fragments.Select(fragment => $"{fragment.SkipNum}:{fragment.ValueNum}:{fragment.HasAnyZeroes}:{fragment.IsLast}"))}");

        if (!header.HasValues)
            return;

        if (ar.Owner.Mappings?.Types.TryGetValue("NiagaraSystem", out Struct? mapping) != true)
            throw new InvalidDataException("No NiagaraSystem mapping was loaded.");

        using var iterator = new FIterator(header);
        do
        {
            var (index, isNonZero) = iterator.Current;
            var fieldStart = ar.Position;
            if (!mapping.TryGetValue(index, out var info))
            {
                Console.Error.WriteLine($"NIAGARA_SYSTEM_FIELD index={index} nonzero={isNonZero} start={fieldStart} MISSING_SCHEMA");
                ProbeKnownSystemFieldCandidates(ar, mapping, fieldStart);
                if (isNonZero)
                    throw new InvalidDataException($"NiagaraSystem mapping has no property at index {index}.");
                continue;
            }

            Console.Error.WriteLine(
                $"NIAGARA_SYSTEM_FIELD index={index} nonzero={isNonZero} start={fieldStart} " +
                $"name={info.Name} type={DescribeType(info.MappingType)}");
            try
            {
                var tag = new FPropertyTag(ar, info, isNonZero ? ReadType.NORMAL : ReadType.ZERO);
                if (tag.Tag is null)
                    throw new InvalidDataException("CUE4Parse returned a null property value.");
                Properties.Add(tag);
                Console.Error.WriteLine(
                    $"NIAGARA_SYSTEM_FIELD_DONE index={index} end={ar.Position} bytes={ar.Position - fieldStart} value={tag.Tag}");
            }
            catch (Exception exception)
            {
                Console.Error.WriteLine(
                    $"NIAGARA_SYSTEM_FIELD_FAILED index={index} at={ar.Position} bytes={ar.Position - fieldStart} " +
                    $"exception={exception.GetType().Name}: {exception.Message}");
                throw;
            }
        }
        while (iterator.MoveNext());
    }

    private static string DescribeType(PropertyType type) => type.Type switch
    {
        "StructProperty" => $"Struct<{type.StructType}>",
        "ArrayProperty" => $"Array<{DescribeType(type.InnerType!)}>",
        "MapProperty" => $"Map<{DescribeType(type.InnerType!)},{DescribeType(type.ValueType!)}>",
        _ => type.Type,
    };

    private static void ProbeKnownSystemFieldCandidates(FAssetArchive ar, Struct mapping, long start)
    {
        // Test only fields whose format we already have in the mapping.  A
        // successful parse with a plausible byte count gives us an anchor for
        // restoring the missing schema slots without guessing their encoding.
        var candidates = mapping.Properties.Values.Where(info => info.Name is
                "EmitterHandles" or "ParameterCollectionOverrides" or
                "SystemSpawnScript" or "SystemUpdateScript" or
                "m_VfxRefDataInterfaceAssetMap" or "SystemCompiledData" or
                "ExposedParameters" or "FixedBounds" or "WarmupTime" or
                "WarmupTickCount" or "WarmupTickDelta")
            .Concat(new[]
            {
                new PropertyInfo(-1, "ProbeName", new PropertyType("NameProperty")),
                new PropertyInfo(-1, "ProbeText", new PropertyType("TextProperty")),
                new PropertyInfo(-1, "ProbeString", new PropertyType("StrProperty")),
                new PropertyInfo(-1, "ProbeBool", new PropertyType("BoolProperty")),
                new PropertyInfo(-1, "ProbeByte", new PropertyType("ByteProperty")),
                new PropertyInfo(-1, "ProbeInt64", new PropertyType("Int64Property")),
                new PropertyInfo(-1, "ProbeDouble", new PropertyType("DoubleProperty")),
                new PropertyInfo(-1, "ProbeSoftObject", new PropertyType("SoftObjectProperty")),
                new PropertyInfo(-1, "ProbeNames", new PropertyType("ArrayProperty", innerType: new PropertyType("NameProperty"))),
                new PropertyInfo(-1, "ProbeObjects", new PropertyType("ArrayProperty", innerType: new PropertyType("ObjectProperty"))),
            });

        foreach (var candidate in candidates)
        {
            try
            {
                ar.Position = start;
                var tag = new FPropertyTag(ar, candidate, ReadType.NORMAL);
                Console.Error.WriteLine(
                    $"NIAGARA_SYSTEM_CANDIDATE name={candidate.Name} type={DescribeType(candidate.MappingType)} " +
                    $"end={ar.Position} bytes={ar.Position - start} value={tag.Tag}");
            }
            catch (Exception exception)
            {
                Console.Error.WriteLine(
                    $"NIAGARA_SYSTEM_CANDIDATE_FAILED name={candidate.Name} at={ar.Position} " +
                    $"exception={exception.GetType().Name}: {exception.Message}");
            }
            finally
            {
                ar.Position = start;
            }
        }
    }
}
