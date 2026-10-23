"""Generic virtual/volume images retain their layout; runtime targets explain missing pixels."""
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
from addon.formats.unreal_mesh.materials import build_material


def png_chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)


def fixture_png():
    rows = b"".join(b"\0" + bytes([255, y * 64, 127, 255]) * 4 for y in range(4))
    return (b"\x89PNG\r\n\x1a\n"
            + png_chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 4, 8, 6, 0, 0, 0))
            + png_chunk(b"IDAT", zlib.compress(rows)) + png_chunk(b"IEND", b""))


class FixtureSession(GenericSession):
    def __init__(self):
        super().__init__(GamePaths(str(ROOT), "", "", ""), "GAME_UE4_27", max_texture_resolution=2)
        self.requests = {}

    def request(self, payload, **kwargs):
        asset = payload["assetPath"]
        self.requests[asset] = self.requests.get(asset, 0) + 1
        if "Runtime" in asset:
            return {"ok": True, "dds": {"status": "unavailable", "textureType": "TextureRenderTarget2DArray",
                "unavailableReason": "runtime_generated", "reason": "Runtime render target has no stored image pixels."}}
        path = Path(payload["ddsOutput"]).with_suffix(".png")
        path.write_bytes(fixture_png())
        volume = "Volume" in asset
        return {"ok": True, "dds": {"status": "ready", "output": str(path), "fileExtension": "png",
            "textureType": "VolumeTexture" if volume else "Texture2D",
            "textureLayout": "VOLUME_ATLAS" if volume else "VIRTUAL_2D", "pixelFormat": "PF_B8G8R8A8",
            "srgb": False, "width": 4, "height": 4, "sourceWidth": 4, "sourceHeight": 4, "mipIndex": 0}}


session = FixtureSession()
paths = ["/Game/Fixture/Virtual.Virtual", "/Game/Fixture/Volume.Volume", "/Game/Fixture/Runtime.Runtime"]
material = build_material("LayoutFixture", "/Game/LayoutFixture.LayoutFixture",
    {"textures": [{"path": path, "labels": [path.rsplit("/", 1)[-1]]} for path in paths]}, session)
nodes = {n["ue_texture_path"]: n for n in material.node_tree.nodes if n.type == "TEX_IMAGE"}
for path, layout in zip(paths, ["VIRTUAL_2D", "VOLUME_ATLAS"]):
    image = nodes[path].image
    assert image is not None and image.packed_file and tuple(image.size) == (2, 2)
    assert image["ue_texture_layout"] == layout and image.alpha_mode == "CHANNEL_PACKED"
assert nodes[paths[1]]["ue_texture_layout"] == "VOLUME_ATLAS"
assert "Volume slice atlas" in nodes[paths[1]].label
runtime = nodes[paths[2]]
assert runtime.image is None and runtime["ue_texture_unavailable"]
assert runtime["ue_texture_type"] == "TextureRenderTarget2DArray"
assert "no stored image pixels" in runtime["ue_texture_unavailable_reason"]
assert any("no stored image pixels" in warning for warning in json.loads(material["ue_texture_warnings"]))
assert session.loaded == 2 and session.failed == 1
assert session(paths[2]) is None and session.requests[paths[2]] == 1
print("GENERIC_TEXTURE_LAYOUT_OK", flush=True)
