using System.Buffers.Binary;
using System.Text;

internal static class RemakeColorLut
{
    // Texture3D stores an inline half-float color cube ahead of the empty mip
    // array. Validate the record before exposing its samples to Blender.
    public static bool TryRead(byte[] source, long packageHeaderSize, out int size, out float[] pixels)
    {
        size = 0;
        pixels = [];
        var marker = Encoding.ASCII.GetBytes("PF_FloatRGBA\0");
        var search = 16;
        while (search < source.Length)
        {
            var relative = source.AsSpan(search).IndexOf(marker);
            if (relative < 0) return false;
            var position = search + relative;
            search = position + marker.Length;
            int Read(int offset) => BinaryPrimitives.ReadInt32LittleEndian(source.AsSpan(offset, 4));
            var n = Read(position - 16);
            if (Read(position - 4) != marker.Length || n < 2 || n > 256 ||
                Read(position - 12) != n || Read(position - 8) != n) continue;
            var record = position + marker.Length;
            if (record > source.Length - 44) continue;
            var bytes = checked(n * n * n * 8);
            var start = record + 32;
            if (Read(record) != 0 || Read(record + 4) != 1 || Read(record + 8) != 1 ||
                Read(record + 12) != 0x40 || Read(record + 16) != bytes || Read(record + 20) != bytes ||
                BinaryPrimitives.ReadInt64LittleEndian(source.AsSpan(record + 24, 8)) != packageHeaderSize + start ||
                bytes > source.Length - start - 12) continue;
            if (Read(start + bytes) != n || Read(start + bytes + 4) != n || Read(start + bytes + 8) != n) continue;
            var result = new float[n * n * n * 4];
            for (var i = 0; i < result.Length; i++)
            {
                var half = BinaryPrimitives.ReadUInt16LittleEndian(source.AsSpan(start + i * 2, 2));
                result[i] = (float)BitConverter.UInt16BitsToHalf(half);
                if (!float.IsFinite(result[i])) return false;
            }
            size = n;
            pixels = result;
            return true;
        }
        return false;
    }
}
