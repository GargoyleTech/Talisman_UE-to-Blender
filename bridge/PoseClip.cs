using System.Buffers.Binary;

namespace Ff7r.Acl;

/// <summary>
/// Rebirth's uncompressed single-pose bone codec, used by AnimSequences flagged
/// <c>bPoseAnimation</c> (prop and environment actors: BG*, FA*, some WE*).
/// </summary>
/// <remarks>
/// These clips carry no ACL <c>compressed_clip</c>; their bone codec id is
/// <c>EF2036B0 5494F406</c> where ACL's is <c>30AF2F90 5494F406</c> (the high half is
/// shared, the low half selects the codec).  Despite that, BoneCompressionSettings
/// still points at the ACL settings asset, so the <c>bPoseAnimation</c> property is
/// the only reliable signal.
///
/// Layout, after the same descriptor the ACL path skips:
/// <code>
///   int32  totalSize
///   uint16 0, uint16 1, uint16 alignment (16), uint16 padCount
///   padCount bytes
///   int32  flags (0x61), int32 0, int32 dataSize, int32 dataSize, int32 0 x4
///   uint64 codec id
///   int32  0 ...                       // to the table
///   int32  table[4 * tracks - 1]       // alternating key count (always 1) and a
///                                      // byte offset stepping by 12
///   key data: 2 * tracks entries of 12 bytes, per track
///       FVector translation (3 floats)
///       dropped-W quaternion (3 floats); W = sqrt(max(0, 1 - x^2 - y^2 - z^2))
/// </code>
/// Scale is not stored and is implicitly 1.  Each sub-track holds a single key, so the
/// pose is held for the clip's whole duration.
///
/// Verified against EV_GOLDE_0500_BG2099_00_C0010 (pillow, 2 tracks) and
/// EV_GOLDE_0500_FA0052_00_C0030 (dummy locator, 4 tracks): every reconstructed
/// quaternion is unit length to 1e-6, and the dummy's root translation is a
/// world-space position in centimetres consistent with the rest of the scene.
/// </remarks>
public sealed class PoseClip
{
    public required float[][] Translations { get; init; }   // [track][3]
    public required float[][] Rotations { get; init; }      // [track][4] xyzw
    public required float[][] Scales { get; init; }         // [track][3]
    public int NumTracks => Translations.Length;

    public static PoseClip? Decode(byte[] payload, int trackCount, out string? error)
    {
        error = null;
        if (trackCount <= 0)
        {
            error = "Pose animation has no tracks.";
            return null;
        }
        if (payload.Length < 64)
        {
            error = $"Pose payload is only {payload.Length} bytes.";
            return null;
        }

        var padCount = BinaryPrimitives.ReadUInt16LittleEndian(payload.AsSpan(10));
        // 12-byte header + padding, then eight int32 fields, the 8-byte codec id and
        // three zero words before the table.
        var dataStart = 12 + padCount + 8 * 4 + 8 + 12;
        var sizeAt = 12 + padCount + 8;
        if (sizeAt + 4 > payload.Length || dataStart >= payload.Length)
        {
            error = "Pose payload is too short for its descriptor.";
            return null;
        }
        var dataSize = BinaryPrimitives.ReadInt32LittleEndian(payload.AsSpan(sizeAt));

        // Most pose clips store two sub-tracks per bone (translation, rotation) but
        // some add a third for scale, which shifts every key.  Try both and let the
        // unit-quaternion check decide, rather than assuming one layout.
        foreach (var subTracks in (int[]) [2, 3])
        {
            var keyBytes = subTracks * trackCount * 12;
            var candidates = new List<int>();
            var fromSize = dataStart + (dataSize - 4 - keyBytes);
            if (fromSize >= dataStart) candidates.Add(fromSize);
            for (var at = dataStart; at + keyBytes <= payload.Length; at += 4)
                if (at != fromSize)
                    candidates.Add(at);

            foreach (var keysAt in candidates)
            {
                if (keysAt < dataStart || keysAt + keyBytes > payload.Length)
                    continue;
                if (TryReadKeys(payload, keysAt, trackCount, subTracks,
                        out var translations, out var rotations, out var scales))
                {
                    return new PoseClip
                    {
                        Translations = translations!,
                        Rotations = rotations!,
                        Scales = scales!,
                    };
                }
            }
        }

        error = $"No pose key block in {payload.Length} bytes yielding {trackCount} unit " +
                $"dropped-W quaternion(s) (dataSize {dataSize}, data at {dataStart}).";
        return null;
    }

    private static bool TryReadKeys(
        byte[] payload, int keysAt, int trackCount, int subTracks,
        out float[][]? translations, out float[][]? rotations, out float[][]? scales)
    {
        translations = null;
        rotations = null;
        scales = null;
        var t = new float[trackCount][];
        var r = new float[trackCount][];
        var sc = new float[trackCount][];

        static bool Vec(byte[] data, int at, out float x, out float y, out float z)
        {
            x = BitConverter.ToSingle(data, at);
            y = BitConverter.ToSingle(data, at + 4);
            z = BitConverter.ToSingle(data, at + 8);
            return float.IsFinite(x) && float.IsFinite(y) && float.IsFinite(z);
        }

        for (var track = 0; track < trackCount; track++)
        {
            var baseAt = keysAt + track * subTracks * 12;
            if (!Vec(payload, baseAt, out var tx, out var ty, out var tz))
                return false;
            if (!Vec(payload, baseAt + 12, out var x, out var y, out var z))
                return false;
            var lengthSquared = x * x + y * y + z * z;
            if (lengthSquared > 1.0f + 1e-3f)
                return false;

            var scale = new float[] { 1.0f, 1.0f, 1.0f };
            if (subTracks >= 3)
            {
                if (!Vec(payload, baseAt + 24, out var sx, out var sy, out var sz))
                    return false;
                // A plausible scale keeps the search from locking onto noise.
                if (sx is <= 0.0f or > 1000.0f || sy is <= 0.0f or > 1000.0f ||
                    sz is <= 0.0f or > 1000.0f)
                    return false;
                scale = [sx, sy, sz];
            }

            t[track] = [tx, ty, tz];
            r[track] = [x, y, z, MathF.Sqrt(MathF.Max(0.0f, 1.0f - lengthSquared))];
            sc[track] = scale;
        }
        translations = t;
        rotations = r;
        scales = sc;
        return true;
    }
}
