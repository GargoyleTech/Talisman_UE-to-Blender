"""Texture limits, stored DDS mip selection, in-place upgrades, and shader reuse."""

from pathlib import Path
import struct
import sys
import tempfile
import zlib

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import addon
addon.register()
from addon.core.blender.material_nodes import load_packed_image, refresh_material_textures
from addon.core.profiles import GamePaths
from addon.formats.mec import material as loose
from addon.formats.mec.texture_mips import select_dds_mip
from addon.formats.unreal_package.session import PackageAssetSession
from addon.formats.unreal_mesh.session import GenericSession
from addon.formats.unreal_mesh import materials as generic_materials
from addon.games.rebirth.profile import PROFILE
from addon.games.remake import materials as remake_materials
from addon.games.crisis_core import materials as cc_materials
from addon.games.kingdom_hearts import materials as kh_materials


def dds(path):
    header = bytearray(128)
    header[:4] = b"DDS "
    for offset, value in ((4, 124), (8, 0xA1007), (12, 32), (16, 64),
                          (20, 1024), (28, 7), (76, 32), (80, 4), (108, 0x401008)):
        struct.pack_into("<I", header, offset, value)
    header[84:88] = b"DXT1"
    payload = bytearray()
    for level in range(7):
        width, height = max(1, 64 >> level), max(1, 32 >> level)
        color = (0xF800, 0x07E0, 0x001F)[level % 3]
        payload += struct.pack("<HHI", color, 0, 0) * (((width + 3) // 4) * ((height + 3) // 4))
    path.write_bytes(header + payload)


class RequestFixture:
    def request(self, payload, **kwargs):
        output = payload["ddsOutput"]
        info = select_dds_mip(self.seed, output, payload["maxTextureResolution"], payload["textureMipOffset"])
        if Path(info["path"]) == self.seed:
            Path(output).write_bytes(self.seed.read_bytes())
        level = info["mipIndex"]
        return {"dds": {**info, "output": output, "width": max(1, 64 >> level),
                        "height": max(1, 32 >> level), "byteLength": Path(output).stat().st_size,
                        "pixelFormat": "PF_DXT1", "fileExtension": "dds", "srgb": True}}


class PackageFixture(RequestFixture, PackageAssetSession):
    pass


class GenericFixture(RequestFixture, GenericSession):
    pass


class PngPackageFixture(PackageAssetSession):
    def request(self, payload, **kwargs):
        # CUE4Parse can encode uncompressed mips as PNG. The returned
        # path can differ from the caller's requested .dds path, even for a tiny
        # image whose entire PNG is shorter than a DDS header.
        def chunk(kind, data):
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
        output = Path(payload["ddsOutput"]).with_suffix(".png")
        pixels = b"\0" + bytes((255, 127, 0, 255)) * 2
        data = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 6, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(pixels * 2)) + chunk(b"IEND", b""))
        assert len(data) < 128
        output.write_bytes(data)
        return {"dds": {"output": str(output), "width": 2, "height": 2,
                        "byteLength": len(data), "pixelFormat": "PF_B8G8R8A8", "fileExtension": "png"}}


with tempfile.TemporaryDirectory(prefix="talisman_mip_test_") as directory:
    root = Path(directory)
    seed = root / "T.dds"
    dds(seed)
    png_loader = PngPackageFixture(str(root), "", "", profile=PROFILE)
    png = png_loader("/Game/Test/Uncompressed.Uncompressed")
    assert png is not None and tuple(png.size) == (2, 2)
    assert png.packed_file.data.startswith(b"\x89PNG\r\n\x1a\n")
    reduced = root / "selected.dds"
    info = select_dds_mip(seed, reduced, 16, -1)
    assert info["mipIndex"] == 2
    assert reduced.read_bytes()[128:136] == struct.pack("<HHI", 0x001F, 0, 0)
    factories = (
        lambda cap, offset: PackageFixture(str(root), "", "", profile=PROFILE,
                                          max_texture_resolution=cap, texture_mip_offset=offset),
        lambda cap, offset: GenericFixture(GamePaths(str(root), "", "", ""), "GAME_UE4_27",
                                          max_texture_resolution=cap, texture_mip_offset=offset),
    )
    for factory in factories:
        path = "/Game/Test/T.T"
        low = factory(16, -1)
        low.seed = seed
        image = low(path)
        assert tuple(image.size) == (16, 8), tuple(image.size)
        assert image["ue_texture_mip_level"] == 2
        assert image.packed_file.data[:4] == b"DDS "
        pointer = image.as_pointer()
        material = bpy.data.materials.new("UpgradeUsers")
        material.use_nodes = True
        node = material.node_tree.nodes.new("ShaderNodeTexImage")
        node.image = image
        image.colorspace_settings.name = "Non-Color"
        for cap, offset, size in ((32, 0, (32, 16)), (8, -3, (32, 16)), (0, 0, (64, 32)), (16, -2, (64, 32))):
            session = factory(cap, offset)
            session.seed = seed
            result = session(path)
            assert result.as_pointer() == pointer and node.image == image
            assert tuple(image.size) == size, (cap, offset, tuple(image.size))
            assert image.colorspace_settings.name == "Non-Color"
            assert image.packed_file.data[:4] == b"DDS "
        assert image["ue_texture_mip_level"] == 0
        assert image["ue_texture_mip_offset"] == 0  # Lower request must not overwrite metadata.
        # A cached material must still request its textures during manual imports.
        seen = []
        def loader(path):
            seen.append(path)
            return image
        refresh_material_textures(material, loader)
        assert seen == [path]

    # All title shader caches, plus the generic shader cache, must trigger upgrades.
    for index, builder in enumerate((remake_materials.build_material, cc_materials.build_material,
                                     kh_materials.build_material, generic_materials.build_material)):
        low = factories[0](16, -2)
        low.seed = seed
        high = factories[0](0, 0)
        high.seed = seed
        path = f"/Game/Cache{index}.T"
        texture = low(path)
        name, material_path = f"Cached{index}", f"/Game/Material{index}.Material{index}"
        material = builder(name, material_path, {}, low)
        node = material.node_tree.nodes.new("ShaderNodeTexImage")
        node.image = texture
        again = builder(name, material_path, {}, high)
        assert again == material and node.image == texture
        assert tuple(texture.size) == (64, 32), (builder, tuple(texture.size))

    # Loose DDS files obey both controls and the same no-downgrade rule.
    with loose.texture_limits(16, -1):
        image = loose.load_image("/Game/T.T", str(root), "dds")
    assert tuple(image.size) == (16, 8)
    with loose.texture_limits(0, 0):
        assert loose.load_image("/Game/T.T", str(root), "dds") == image
    assert tuple(image.size) == (64, 32)
    with loose.texture_limits(8, -3):
        assert loose.load_image("/Game/T.T", str(root), "dds") == image
    assert tuple(image.size) == (64, 32)

    # Single-level assets still honor a hard, aspect-preserving cap and repack it.
    single_dds = root / "Single.dds"
    single_bytes = bytearray(seed.read_bytes()[:128 + 1024])
    struct.pack_into("<I", single_bytes, 28, 1)
    single_dds.write_bytes(single_bytes)
    capped_dds = load_packed_image(single_dds, "SingleDDS", max_resolution=8)
    assert tuple(capped_dds.size) == (8, 4)
    promoted_dds = load_packed_image(single_dds, "SingleDDS", max_resolution=16, existing=capped_dds)
    assert promoted_dds == capped_dds
    assert tuple(promoted_dds.size) == (16, 8), tuple(promoted_dds.size)
    promoted_dds.colorspace_settings.name = "Non-Color"
    assert tuple(promoted_dds.size) == (16, 8)
    capped_noncolor = load_packed_image(single_dds, "SingleNonColor", max_resolution=8, color_space="Non-Color")
    assert tuple(capped_noncolor.size) == (8, 4)
    packed_dds_copy = root / "packed-dds.png"
    packed_dds_copy.write_bytes(promoted_dds.packed_file.data)
    packed_dds_decoded = bpy.data.images.load(str(packed_dds_copy), check_existing=False)
    assert tuple(packed_dds_decoded.size) == (16, 8)
    png = root / "Single.png"
    generated = bpy.data.images.new("Single", width=64, height=32)
    generated.filepath_raw = str(png)
    generated.file_format = "PNG"
    generated.save()
    bpy.data.images.remove(generated)
    capped = load_packed_image(png, "Single", max_resolution=20)
    assert tuple(capped.size) == (20, 10)
    packed_copy = root / "packed.png"
    packed_copy.write_bytes(capped.packed_file.data)
    decoded = bpy.data.images.load(str(packed_copy), check_existing=False)
    assert tuple(decoded.size) == (20, 10), tuple(decoded.size)

    operators = [addon.formats.mec.importer.FF7R_REBIRTH_OT_import_mec_umap,
                 addon.games.rebirth.importers.packages.FF7R_REBIRTH_OT_import_mec_game_packages,
                 addon.formats.unreal_mesh.importer.SQEX_OT_import_generic_unreal_mesh]
    from addon.games.remake.importers import static_mesh as remake
    from addon.games.crisis_core.importers import static_mesh as cc
    from addon.games.kingdom_hearts_iii.importers import static_mesh as kh3
    from addon.games.kingdom_hearts_0_2.importers import static_mesh as kh02
    operators += [remake.FF7R_REMAKE_OT_import_umap_game_packages, cc.FF7R_CRISIS_CORE_OT_import_umap_game_packages,
                  kh3.SQEX_KH3_OT_import_umap_game_packages, kh02.SQEX_KH02_OT_import_umap_game_packages]
    for operator in operators:
        category, name = operator.bl_idname.split(".")
        properties = getattr(getattr(bpy.ops, category), name).get_rna_type().properties
        assert {"max_texture_resolution", "texture_mip_offset"} <= set(properties.keys()), operator
        assert {"max_texture_resolution", "texture_mip_offset"} <= set(operator._persisted_props), operator

addon.unregister()
print("TEXTURE_MIPS_BLENDER_OK")
