"""Unreal color textures keep RGB when alpha contains a separate material mask."""
import json
from pathlib import Path
import struct
import sys
import zlib

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from addon.core.profiles import GamePaths
from addon.formats.unreal_mesh.session import GenericSession


def png_chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)


def masked_color_png():
    # Red with a zero mask, green with a full mask. Both RGB values must survive.
    return (b"\x89PNG\r\n\x1a\n"
            + png_chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 1, 8, 6, 0, 0, 0))
            + png_chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00\x00\x00\xff\x00\xff"))
            + png_chunk(b"IEND", b""))


class FixtureSession(GenericSession):
    def __init__(self):
        super().__init__(GamePaths(str(ROOT), "", "", ""), "GAME_UE5_5")
        self.requests = 0

    def request(self, payload, **kwargs):
        self.requests += 1
        path = Path(payload["ddsOutput"]).with_suffix(".png")
        path.write_bytes(masked_color_png())
        return {"dds": {"output": str(path), "fileExtension": "png", "pixelFormat": "PF_B8G8R8A8",
                        "srgb": True, "width": 2, "height": 1, "sourceWidth": 2, "sourceHeight": 1}}


path = "/Game/Fixture/MaskedColor.MaskedColor"
fresh = FixtureSession()
image = fresh(path)
assert image is not None and image.alpha_mode == "CHANNEL_PACKED"
assert image.packed_file is not None and tuple(image.size) == (2, 1)
pixels = list(image.pixels[:])
assert pixels[0] > 0.9 and pixels[3] == 0, pixels
assert pixels[5] > 0.9 and pixels[7] > 0.9, pixels

# Previously saved imports need the same correction when their packed image is reused.
image.alpha_mode = "STRAIGHT"
reused = FixtureSession()
assert reused(path) == image
assert reused.requests == 0
assert image.alpha_mode == "CHANNEL_PACKED"
assert image.packed_file is not None
assert list(image.pixels[:]) == pixels
print("GENERIC_TEXTURE_ALPHA_OK", json.dumps({"pixels": pixels, "reusedWithoutExtraction": True}), flush=True)
