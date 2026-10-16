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
