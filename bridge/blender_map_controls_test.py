"""Discrete texture limits, saved choices, and native/fallback light exposure."""

import json
import math
from pathlib import Path
import sys
from types import SimpleNamespace

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
bpy.ops.preferences.addon_enable(module="addon")
import addon
from addon.formats.ue_map import lights as L, light_rig
from addon.ui.textures import texture_properties


class SQEX_OT_texture_limit_fixture(bpy.types.Operator):
    bl_idname = "wm.sqex_texture_limit_fixture"
    bl_label = "Texture limit fixture"
    __annotations__ = texture_properties()

    def execute(self, context):
        assert self.max_texture_resolution == 0
        assert self.max_texture_resolution_choice == "0"
        for value in (1, 2, 32, 256, 1024, 2048, 8192, 65536):
            self.max_texture_resolution_choice = str(value)
            assert self.max_texture_resolution == value
            self.max_texture_resolution = value
            assert self.max_texture_resolution_choice == str(value)
        self.max_texture_resolution = 3000  # Old saved arbitrary limits round down.
        assert self.max_texture_resolution == 2048
        assert self.max_texture_resolution_choice == "2048"
        self.max_texture_resolution_choice = "0"
        assert self.max_texture_resolution == 0
        return {"FINISHED"}


bpy.utils.register_class(SQEX_OT_texture_limit_fixture)
assert bpy.ops.wm.sqex_texture_limit_fixture() == {"FINISHED"}
bpy.utils.unregister_class(SQEX_OT_texture_limit_fixture)

# Existing remembered options override new fresh-install defaults.
cls = addon.generic_unreal_importer.SQEX_OT_import_generic_unreal_umap
prefs = bpy.context.preferences.addons["addon"].preferences
remembered = {
    "exposure": -2.0, "bake_light_parameters": False,
    "offset_opposite_faces": False, "nanite_mode": "NATIVE",
    "max_landscape_vertices": 750_000, "max_texture_resolution": 3000}
original = cls.execute
bpy.utils.unregister_class(cls)


def check_remembered(self, context):
    prefs.last_import_settings_json = json.dumps({self.bl_idname: remembered})
    self._load_last_import_settings(context)
    assert self.exposure == -2.0 and not self.bake_light_parameters
    assert not self.offset_opposite_faces and self.nanite_mode == "NATIVE"
    assert self.max_landscape_vertices == 750_000
    assert self.max_texture_resolution == 2048
    return {"FINISHED"}


cls.execute = check_remembered
bpy.utils.register_class(cls)
assert bpy.ops.import_scene.sqex_generic_unreal_umap() == {"FINISHED"}
bpy.utils.unregister_class(cls)
del cls.execute  # Restore the shared inherited execute method.
bpy.utils.register_class(cls)
assert cls.execute is original

for kind in ("POINT", "SPOT", "AREA", "SUN"):
    props = {"Intensity": 683, "IntensityUnits": "Lumens", "SourceLength": 100,
             "SoftSourceRadius": 20}
    baseline = L.create_static_light_data("Baseline " + kind, kind, props)
    data = L.create_static_light_data("Exposed " + kind, kind, props, exposure_mult=32)
    obj = bpy.data.objects.new(data.name, data)
    bpy.context.scene.collection.objects.link(obj)
    if kind != "SUN":
        L.apply_ue_light_object_properties(obj)
    bpy.context.view_layer.update()
    native = hasattr(data, "exposure")
    assert math.isclose(data.energy, baseline.energy * (1 if native else 32), rel_tol=1e-6)
    if native:
        assert math.isclose(data.exposure, 5, abs_tol=1e-6)
    if kind != "SUN":
        obj[L.UE_EXPOSURE_PROP] = 0.25
        obj.update_tag()
        bpy.context.view_layer.update()
        assert math.isclose(data.energy, baseline.energy * (1 if native else 0.25), rel_tol=1e-6)
        if native:
            assert math.isclose(data.exposure, -2, abs_tol=1e-6)
            for child in obj.children:
                assert math.isclose(child.data.exposure, -2, abs_tol=1e-6)
        assert light_rig.bake_static_light_parameters([obj]) == 1
        if native:
            assert math.isclose(data.exposure, -2, abs_tol=1e-6)

# Older Blender versions retain the original power multiplier path.
assert L.apply_light_exposure(SimpleNamespace(), 32) == 32
print("MAP_TEXTURE_EXPOSURE_CONTROLS_OK", flush=True)
addon.unregister()
