static void Check(int expected, (int, int)[] sizes, int cap = 0, int offset = 0, params int[] missing)
{
    var result = TextureMipSelection.Select(sizes, i => !missing.Contains(i), cap, offset);
    if (result != expected) throw new Exception($"Expected mip {expected}, got {result}; cap={cap}, offset={offset}.");
}

var chain = new[] { (4096, 2048), (2048, 1024), (1024, 512), (512, 256), (256, 128) };
Check(0, chain);
Check(1, chain, offset: -1);
Check(2, chain, offset: -2);
Check(4, chain, offset: -16);
Check(2, chain, cap: 1024);
Check(3, chain, cap: 768);
Check(3, chain, cap: 512, offset: -1); // Both limits apply to the original size.
Check(3, chain, cap: 2048, offset: -3);
Check(4, chain, cap: 1); // Truncated chain: smallest readable level.
Check(2, chain, offset: -1, missing: [0]); // Offset from highest readable mip.
Check(3, chain, offset: -2, missing: [2]); // Missing intermediate payload.
Check(1, chain, offset: -16, missing: [2, 3, 4]);
Check(-1, chain, missing: [0, 1, 2, 3, 4]);
Check(0, [(1024, 512)], cap: 128, offset: -2);
Check(1, [(1024, 4096), (512, 2048), (256, 1024)], cap: 2048);
Check(0, [(256, 128), (1024, 512)], offset: -2); // Header order is not assumed.
Check(-1, []);
Console.WriteLine("TEXTURE_MIP_SELECTION_OK (17 cases)");
var probed = new List<int>();
var selected = TextureMipSelection.Select(chain, i => { probed.Add(i); return true; }, 512, 0, i => true);
if (selected != 3 || !probed.SequenceEqual(new[] { 3 })) throw new Exception("Capped import read an unnecessary high mip");
// Metadata-only availability must retain every original missing-mip result.
for (var mask = 0; mask < 32; mask++)
    foreach (var cap in new[] { 0, 1, 512, 1024, 8192 })
        foreach (var offset in new[] { 0, -1, -3, -16 })
        {
            bool Readable(int i) => (mask & (1 << i)) == 0;
            var original = TextureMipSelection.Select(chain, Readable, cap, offset);
            var hinted = TextureMipSelection.Select(chain, Readable, cap, offset, i => Readable(i));
            if (original != hinted) throw new Exception("Metadata availability changed missing-mip selection");
        }
Console.WriteLine("TEXTURE_MIP_AVAILABILITY_OK (640 cases)");

// Inline resident BC4 chain: the ordinary mip headers contain no payload.
var resident = new byte[16 + 7 + 32 + 40 + 8];
void PutInt(int offset, int value) => System.Buffers.Binary.BinaryPrimitives.WriteInt32LittleEndian(resident.AsSpan(offset, 4), value);
PutInt(0, 8); PutInt(4, 8); PutInt(8, 1); PutInt(12, 7);
System.Text.Encoding.ASCII.GetBytes("PF_BC4\0").CopyTo(resident, 16);
const int record = 23;
PutInt(record, 0); PutInt(record + 4, 2); PutInt(record + 8, 1);
PutInt(record + 12, 0x40); PutInt(record + 16, 40); PutInt(record + 20, 40);
System.Buffers.Binary.BinaryPrimitives.WriteInt64LittleEndian(resident.AsSpan(record + 24, 8), 932 + record + 32);
for (var i = 0; i < 40; i++) resident[record + 32 + i] = (byte)i;
PutInt(record + 72, 8); PutInt(record + 76, 8);
if (!RemakeTextureResidentMip.TryReadInline(resident, 932, "PF_BC4", 8, out var w, out var h, out var pixels) ||
    w != 8 || h != 8 || !pixels.SequenceEqual(Enumerable.Range(0, 32).Select(i => (byte)i)))
    throw new Exception("Resident top mip was not recovered from the inline chain");
for (var length = 0; length < resident.Length; length++)
    if (RemakeTextureResidentMip.TryReadInline(resident[..length], 932, "PF_BC4", 8, out _, out _, out _))
        throw new Exception("Accepted truncated resident record");
if (RemakeTextureResidentMip.TryReadInline(resident, 933, "PF_BC4", 8, out _, out _, out _) ||
    RemakeTextureResidentMip.TryReadInline(resident, 932, "PF_DXT1", 8, out _, out _, out _))
    throw new Exception("Accepted mismatched resident metadata");
foreach (var invalidFlags in new[] { 0, 0x20, 0x42, 0x140 })
{
    PutInt(record + 12, invalidFlags);
    if (RemakeTextureResidentMip.TryReadInline(resident, 932, "PF_BC4", 8, out _, out _, out _))
        throw new Exception("Accepted non-inline resident payload");
}
Console.WriteLine("REMAKE_INLINE_RESIDENT_MIP_OK (chain, truncation, metadata, storage flags)");

var lut = new byte[16 + 13 + 32 + 64 + 12];
void LutInt(int offset, int value) => System.Buffers.Binary.BinaryPrimitives.WriteInt32LittleEndian(lut.AsSpan(offset, 4), value);
LutInt(0, 2); LutInt(4, 2); LutInt(8, 2); LutInt(12, 13);
System.Text.Encoding.ASCII.GetBytes("PF_FloatRGBA\0").CopyTo(lut, 16);
LutInt(29, 0); LutInt(33, 1); LutInt(37, 1); LutInt(41, 0x40); LutInt(45, 64); LutInt(49, 64);
System.Buffers.Binary.BinaryPrimitives.WriteInt64LittleEndian(lut.AsSpan(53, 8), 1000 + 61);
for (var i = 0; i < 32; i++)
    System.Buffers.Binary.BinaryPrimitives.WriteUInt16LittleEndian(lut.AsSpan(61 + i * 2, 2),
        BitConverter.HalfToUInt16Bits((Half)(i / 8.0f)));
LutInt(125, 2); LutInt(129, 2); LutInt(133, 2);
if (!RemakeColorLut.TryRead(lut, 1000, out var cubeSize, out var cube) || cubeSize != 2 ||
    !cube.SequenceEqual(Enumerable.Range(0, 32).Select(i => i / 8.0f)))
    throw new Exception("HDR LUT samples were not decoded");
for (var length = 0; length < lut.Length; length++)
    if (RemakeColorLut.TryRead(lut[..length], 1000, out _, out _))
        throw new Exception("Accepted truncated HDR LUT");
if (RemakeColorLut.TryRead(lut, 999, out _, out _)) throw new Exception("Accepted wrong LUT offset");
LutInt(41, 0x20);
if (RemakeColorLut.TryRead(lut, 1000, out _, out _)) throw new Exception("Accepted unused LUT payload");
Console.WriteLine("REMAKE_HDR_LUT_OK (half floats, dimensions, truncation, offset, flags)");
