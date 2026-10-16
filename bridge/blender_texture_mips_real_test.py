"""Exercise mip selection and shared quality upgrades against an installed game."""

import argparse
import json
from pathlib import Path
import sys

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import addon
addon.register()
from addon.core.profiles import GamePaths
from addon.formats.unreal_mesh.session import GenericSession
from addon.formats.unreal_package.session import PackageAssetSession

parser = argparse.ArgumentParser()
parser.add_argument("--config", required=True)
parser.add_argument("--game", required=True)
parser.add_argument("--texture")
args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
config = json.loads(Path(args.config).read_text())[args.game]
paths = GamePaths(config["root"], config.get("oodle") or str(ROOT / ".local/oodle/oo2core_7_win64.dll"),
                  config.get("usmap", ""), config.get("key", ""))
if config.get("profile"):
    import importlib
    profile = importlib.import_module("addon.games." + config["profile"] + ".profile").PROFILE
    def make_session(cap, offset):
        return PackageAssetSession(paths.install_root, paths.oodle_dll, paths.usmap_path,
                                   profile=profile, aes_key=paths.aes_key,
                                   max_texture_resolution=cap, texture_mip_offset=offset)
else:
    def make_session(cap, offset):
        return GenericSession(paths, config["version"], max_texture_resolution=cap, texture_mip_offset=offset)
texture_path = args.texture or config.get("texture")
if not texture_path and config.get("mesh"):
    from addon.formats.unreal_package.paths import _game_asset_path_to_virtual_uasset
    def object_paths(value):
        if isinstance(value, dict):
            if value.get("ObjectPath"):
                yield value["ObjectPath"]
            for child in value.values():
                yield from object_paths(child)
        elif isinstance(value, list):
            for child in value:
                yield from object_paths(child)
    with make_session(256, -2) as session:
        mesh = session.static_mesh(config["mesh"])
        for section in mesh.get("sections") or []:
            asset = _game_asset_path_to_virtual_uasset(section.get("materialPath"), profile=profile)
            if not asset:
                continue
            material = session.material_instance(asset)
            for prop in material.get("properties") or []:
                if prop.get("name") == "TextureParameterValues":
                    texture_path = next(object_paths(prop.get("value")), None)
                    if texture_path:
                        break
            if texture_path:
                break
assert texture_path, "Supply --texture or a mesh with readable texture parameters."
print("REAL_TEXTURE_PATH", args.game, texture_path, flush=True)
shared = None
previous_size = (0, 0)
for cap, offset in ((256, -2), (1024, -1), (0, 0), (128, -3)):
    with make_session(cap, offset) as session:
        image = session(texture_path)
        assert image is not None, texture_path
        if shared is None:
            shared = image
            assert max(image.size) <= cap
            assert image["ue_texture_mip_level"] >= 2
        else:
            assert image == shared
            if cap:
                assert max(image.size) <= max(cap, max(previous_size)), (cap, tuple(image.size), previous_size)
        assert all(a >= b for a, b in zip(image.size, previous_size))
        assert image.packed_file
        if not cap:
            assert tuple(image.size) == (image["ue_texture_source_width"], image["ue_texture_source_height"])
            assert image["ue_texture_mip_level"] == 0
        previous_size = tuple(image.size)
        print("REAL_TEXTURE_MIP", cap, offset, tuple(image.size), image["ue_texture_mip_level"], flush=True)
addon.unregister()
print("REAL_TEXTURE_MIPS_OK")
