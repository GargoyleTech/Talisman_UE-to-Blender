"""Read one conventional block-compressed DDS mip without decoding larger levels."""

import os
import struct


def select_dds_mip(source, output, max_resolution=0, mip_offset=0):
    """Write a single-mip DDS when a lower stored level exists; return source info."""
    with open(source, "rb") as stream:
        header = bytearray(stream.read(128))
        if len(header) != 128 or header[:4] != b"DDS ":
            return None
        height, width = struct.unpack_from("<II", header, 12)
        count = max(1, struct.unpack_from("<I", header, 28)[0])
        caps2 = struct.unpack_from("<I", header, 112)[0]
        if width <= 0 or height <= 0 or caps2 & 0x20FE00:
            return None  # Cube/volume data has a different subresource layout.
        fourcc = bytes(header[84:88])
        block_bytes = {b"DXT1": 8, b"DXT3": 16, b"DXT5": 16,
                       b"ATI1": 8, b"BC4U": 8, b"BC4S": 8,
                       b"ATI2": 16, b"BC5U": 16, b"BC5S": 16}.get(fourcc)
        extra = b""
        if fourcc == b"DX10":
            extra = stream.read(20)
            if len(extra) != 20:
                return None
            fmt, dimension, misc, array_size, _ = struct.unpack("<5I", extra)
            if dimension != 3 or array_size != 1 or misc & 4:
                return None
            block_bytes = (8 if fmt in (71, 72, 80, 81) else
                           16 if fmt in (74, 75, 77, 78, 83, 84, 95, 96, 98, 99) else None)
        if block_bytes is None:
            return None
        source_width, source_height = width, height
        target_width = max(1, width >> -mip_offset)
        target_height = max(1, height >> -mip_offset)
        offset = 128 + len(extra)
        length = os.fstat(stream.fileno()).st_size
        selected = None
        for level in range(min(count, 32)):
            size = ((width + 3) // 4) * ((height + 3) // 4) * block_bytes
            if offset + size > length:
                break
            selected = (level, width, height, offset, size)
            if (width <= target_width and height <= target_height
                    and (not max_resolution or max(width, height) <= max_resolution)):
                break
            offset += size
            width, height = max(1, width // 2), max(1, height // 2)
        if selected is None:
            return None
        level, width, height, offset, size = selected
        if level:
            struct.pack_into("<I", header, 8, (struct.unpack_from("<I", header, 8)[0] & ~0x20000) | 0x80000)
            struct.pack_into("<IIII", header, 12, height, width, size, 0)
            struct.pack_into("<I", header, 28, 1)
            struct.pack_into("<I", header, 108, 0x1000)
            stream.seek(offset)
            with open(output, "wb") as destination:
                destination.write(header + extra + stream.read(size))
        return {"path": output if level else source, "mipIndex": level,
                "sourceWidth": source_width, "sourceHeight": source_height}

