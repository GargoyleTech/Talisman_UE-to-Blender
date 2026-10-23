"""Indexed lookup reuse, source isolation, deleted IDs, refreshes and scope cleanup."""

from pathlib import Path
from types import SimpleNamespace
import sys
import time

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import addon
addon.register()
from addon.core.blender.import_cache import (
    ImportCache, find_datablock, get_import_cache, import_cache_scope, remember_datablock,
)
from addon.core.blender.material_nodes import material_for_texture_source, refresh_material_textures
from addon.core.profiles import GamePaths
from addon.formats.unreal_mesh.session import GenericSession
from addon.formats.unreal_mesh.materials import build_material
from addon.formats.unreal_package.mesh_import import _static_mesh_material
from addon.games.crisis_core.materials import build_material as cc_material


session = GenericSession(GamePaths("fixture-cache"), "GAME_UE4_27")
foreign = bpy.data.materials.new("Foreign")
foreign["ue_source_id"] = foreign["ue_texture_namespace"] = "different-source"
foreign["ue_virtual_path"] = "/Game/M0.M0"
materials = []
for i in range(150):
    path = f"/Game/M{i}.M{i}"
    placeholder = _static_mesh_material(f"M{i}", path, session.texture_namespace, session)
    material = build_material(f"M{i}", path, {}, session)
    assert material == placeholder
    assert build_material(f"M{i}", path.upper(), {}, session) == material
    materials.append(material)
cache = get_import_cache(session)
assert cache.indices[("materials", "package-source")].scans == 1
assert cache.indices[("materials", "generic-material")].scans == 1

materials[0].name = "Renamed imported material"
assert build_material("M0", "/Game/M0.M0", {}, session) == materials[0]
bpy.data.materials.remove(materials[1])
replacement = bpy.data.materials.new("Replacement")
replacement["ue_source_id"] = session.cache_namespace
replacement["ue_texture_namespace"] = session.texture_namespace
replacement["ue_virtual_path"] = "/Game/M1.M1"
assert build_material("M1", "/Game/M1.M1", {}, session) == replacement
assert cache.indices[("materials", "generic-material")].scans == 2
other = GenericSession(GamePaths("different-fixture-cache"), "GAME_UE4_27")
assert build_material("M0", "/Game/M0.M0", {}, other) != materials[0]
no_textures = GenericSession(GamePaths("fixture-cache"), "GAME_UE4_27", import_textures=False)
assert build_material("M0", "/Game/M0.M0", {}, no_textures) != materials[0]


def image_for(path):
    image = bpy.data.images.new(path.rsplit("/", 1)[-1], width=4, height=4)
    image["ue_virtual_path"] = path
    image["ue_source_id"] = session.cache_namespace
    image["ue_texture_namespace"] = session.texture_namespace
    image["ue_texture_source_width"] = image["ue_texture_source_height"] = 4
    return image


first = image_for("/Game/T0.T0")
assert session("/Game/T0.T0") == first
for i in range(1, 100):
    path = f"/Game/T{i}.T{i}"
    image = image_for(path)
    remember_datablock("images", image, session)
    assert session(path) == image and session(path.upper()) == image
assert cache.indices[("images", "generic-texture")].scans == 1
bpy.data.images.remove(first)
replacement_image = image_for("/Game/T0.T0")
assert session("/Game/T0.T0") == replacement_image
assert cache.indices[("images", "generic-texture")].scans == 2


class Loader:
    texture_namespace = "refresh-source"
    max_texture_resolution = 16
    texture_mip_offset = 0
    import_textures = True

    def __init__(self):
        self.calls = []

    def __call__(self, path):
        self.calls.append(path)
        return replacement_image


loader = Loader()
material = material_for_texture_source("Refresh", "/Game/Refresh.Refresh", loader)
material.use_nodes = True
node = material.node_tree.nodes.new("ShaderNodeTexImage")
node["ue_texture_path"] = "/Game/T0.T0"
for i in range(20):
    refresh_material_textures(material, loader)
assert len(loader.calls) == 1
loader.max_texture_resolution = 32
refresh_material_textures(material, loader)
assert len(loader.calls) == 2
node2 = material.node_tree.nodes.new("ShaderNodeTexImage")
node2["ue_texture_path"] = "/Game/T0.T0"
refresh_material_textures(material, loader)
assert len(loader.calls) == 4
later = Loader()
refresh_material_textures(material, later)
assert len(later.calls) == 2  # Later imports refresh existing shared shaders.
manual_calls = []
with import_cache_scope():
    for _ in range(2):
        refresh_material_textures(material, lambda path: manual_calls.append(path))
assert len(manual_calls) == 4

# A removed shader must not survive a module-level title cache.
cc = cc_material("DeletedCC", "/Game/DeletedCC.DeletedCC", {}, loader)
bpy.data.materials.remove(cc)
assert cc_material("DeletedCC", "/Game/DeletedCC.DeletedCC", {}, loader).name

assert get_import_cache() is None
outer = ImportCache()
with import_cache_scope(outer):
    try:
        with import_cache_scope(ImportCache()):
            raise ValueError("fixture")
    except ValueError:
        pass
    assert get_import_cache() is outer
assert get_import_cache() is None

# Session exit, including failures, releases its active import scope.
session._start_process = lambda: None
session._stop_process = lambda: None
try:
    with session:
        assert get_import_cache() is session._import_datablocks
        raise ValueError("fixture")
except ValueError:
    pass
assert get_import_cache() is None

# Rebirth's existing-material migrations run once per import, while an edited
# template revision still forces its normal rebuild inside the same scope.
from addon.games.rebirth.materials import rmi_surface
master = rmi_surface._module_set()[0]["surface"]
rmi_cache = ImportCache()
migrations = []
migrate = rmi_surface._migrate_switch_status_properties


def counted_migration(material):
    migrations.append(material.name)
    return migrate(material)


rmi_surface._migrate_switch_status_properties = counted_migration
try:
    template = rmi_surface._ensure_master(master, import_cache=rmi_cache)
    count = len(migrations)
    for _ in range(10):
        assert rmi_surface._ensure_master(master, import_cache=rmi_cache) == template
    assert len(migrations) == count
    template["_RMI_Profile_Revision"] = 0
    template = rmi_surface._ensure_master(master, import_cache=rmi_cache)
    assert template["_RMI_Profile_Revision"] == master.PROFILE_REVISION
    assert len(migrations) > count
finally:
    rmi_surface._migrate_switch_status_properties = migrate

# Exercise sustained lookups against a populated collection and count scans.
identity = lambda item: (item.get("ue_source_id", ""), item.get("ue_virtual_path", "").casefold())
for i in range(1000):
    bpy.data.materials.new(f"Unrelated{i}")
owner = SimpleNamespace(texture_namespace=session.texture_namespace)
path = "/Game/M149.M149"
key = (session.cache_namespace, path.casefold())
times = []
for indexed in (False, True):
    start = time.perf_counter()
    for _ in range(1000):
        if indexed:
            result = find_datablock("materials", "benchmark", key, identity, owner)
        else:
            result = next((item for item in bpy.data.materials if identity(item) == key), None)
        assert result == materials[149]
    times.append(time.perf_counter() - start)
assert get_import_cache(owner).indices[("materials", "benchmark")].scans == 1
print("IMPORT_DATABLOCK_CACHE_OK", "lookupSeconds", times, flush=True)
addon.unregister()
