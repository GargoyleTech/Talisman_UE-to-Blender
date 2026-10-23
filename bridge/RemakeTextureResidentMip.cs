using System.Buffers.Binary;
using System.Text;

// Remake serializes a resident mip (sometimes an entire packed chain) before
// its ordinary mip array. CUE4Parse reads this record but does not retain it.
internal static class RemakeTextureResidentMip
{
    public static bool TryReadInline(byte[] source, long packageHeaderSize, string format,
        int bytesPerBlock, out int width, out int height, out byte[] data)
    {
        width = height = 0;
        data = [];
        if (bytesPerBlock <= 0) return false;
        var marker = Encoding.ASCII.GetBytes(format + "\0");
        var searchOffset = 16;
        while (searchOffset < source.Length)
        {
            var relative = source.AsSpan(searchOffset).IndexOf(marker);
            if (relative < 0) return false;
            var position = searchOffset + relative;
            searchOffset = position + marker.Length;
            int ReadInt(int offset) => BinaryPrimitives.ReadInt32LittleEndian(source.AsSpan(offset, 4));
            if (ReadInt(position - 4) != marker.Length) continue;
            var sizeX = ReadInt(position - 16);
            var sizeY = ReadInt(position - 12);
            // Only the plain single-slice platform layout has this header.
            if (sizeX <= 0 || sizeY <= 0 || sizeX > 65536 || sizeY > 65536 ||
                ReadInt(position - 8) != 1) continue;
            var record = position + marker.Length;
            if (record > source.Length - 40) continue;
            var firstMip = ReadInt(record);
            var mipCount = ReadInt(record + 4);
            var cooked = ReadInt(record + 8);
            var flags = ReadInt(record + 12);
            var elements = ReadInt(record + 16);
            var payloadSize = ReadInt(record + 20);
            var payloadOffset = BinaryPrimitives.ReadInt64LittleEndian(source.AsSpan(record + 24, 8));
            var payloadStart = record + 32;
            // FORCE_INLINE_PAYLOAD, with no compressed, unused, or external
            // storage flags. Validate the offset, dimensions, and byte range.
            if (firstMip < 0 || firstMip > 32 || mipCount <= 0 || mipCount > 32 || cooked != 1 ||
                flags != 0x40 || payloadSize <= 0 || elements != payloadSize ||
                payloadOffset != packageHeaderSize + payloadStart ||
                payloadSize > source.Length - payloadStart - 8) continue;
            var end = payloadStart + payloadSize;
            if (ReadInt(end) != sizeX || ReadInt(end + 4) != sizeY) continue;
            var required = checked((long)((sizeX + 3) / 4) * ((sizeY + 3) / 4) * bytesPerBlock);
            if (required > payloadSize) continue;
            width = sizeX;
            height = sizeY;
            data = source.AsSpan(payloadStart, checked((int)required)).ToArray();
            return true;
        }
        return false;
    }
}
