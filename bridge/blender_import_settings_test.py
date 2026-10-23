"""Round-trip importer choices through real RNA operators and preferences."""

import json
from pathlib import Path
import sys

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import addon

addon.register()
entry = bpy.context.preferences.addons.new()
entry.module = "addon"
prefs = entry.preferences
prefs.last_import_settings_json = "{}"

# Animation importers poll for an active rig, even though this fixture never
# decodes a package or applies animation.
rig = bpy.data.objects.new("SettingsFixture", bpy.data.armatures.new("SettingsFixture"))
bpy.context.scene.collection.objects.link(rig)
bpy.context.view_layer.objects.active = rig

classes = [cls for cls in addon.classes if getattr(cls, "_persisted_props", ())
           and getattr(cls, "bl_idname", "").startswith(("import_scene.", "object.sqex_import_"))]
mesh_classes = [cls for cls in classes if getattr(cls, "mesh_kind", None) in {"STATIC", "SKELETAL"}]
assert len(mesh_classes) == 12
assert addon.generic_unreal_animations.SQEX_OT_import_generic_unreal_animation in classes
assert addon.generic_sequences.SQEX_OT_import_generic_unreal_sequence in classes
assert addon.remake_cutscenes.FF7R_REMAKE_OT_import_cutscene_game_packages in classes
assert addon.game_packages.FF7R_REBIRTH_OT_import_cutscene_game_packages in classes


def plain(value):
    return list(value) if not isinstance(value, (str, bool, int, float)) else value


def alternative(operator, name):
    value = getattr(operator, name)
    prop = operator.properties.bl_rna.properties[name]
    if prop.type == "BOOLEAN":
        return not value
    if prop.type in {"INT", "FLOAT"}:
        if prop.is_array:
            return [min(prop.hard_max, max(prop.hard_min, item + 1)) for item in value]
        return min(prop.hard_max, max(prop.hard_min, value + 1))
    if prop.type == "ENUM":
        return next((item.identifier for item in prop.enum_items if item.identifier != value), value)
    if prop.type == "STRING":
        return "settings fixture"
    raise AssertionError((name, prop.type))


expected = {}
phase = "save"


def exercise(self, context):
    before = prefs.last_import_settings_json
    context.preferences.is_dirty = False
    # Programmatic EXEC calls must leave the user's interactive choices alone.
    self._save_last_import_settings(context)
    assert prefs.last_import_settings_json == before and not context.preferences.is_dirty
    self._load_last_import_settings(context)
    if phase == "save":
        for name in self._persisted_props:
            setattr(self, name, alternative(self, name))
        expected[self.bl_idname] = {name: plain(getattr(self, name)) for name in self._persisted_props}
        self.cancel(context)
        assert context.preferences.is_dirty, self.bl_idname
        stored = json.loads(prefs.last_import_settings_json)[self.bl_idname]
        assert stored == expected[self.bl_idname]
        assert not {"virtual_path", "filepath", "files", "start_frame", "binding_overrides"} & stored.keys()
    else:
        restored = {name: plain(getattr(self, name)) for name in self._persisted_props}
        assert restored == expected[self.bl_idname], (self.bl_idname, restored)
        self._save_last_import_settings(context)
        assert not context.preferences.is_dirty  # No preference change on an identical save.
    return {"FINISHED"}


for cls in classes:
    # Replace only the package backend entry point. Blender still constructs a
    # fresh real operator for each call, with its original RNA options and
    # persistence/cancel methods; no game installations are needed.
    own_execute = cls.__dict__.get("execute")
    bpy.utils.unregister_class(cls)
    cls.execute = exercise
    bpy.utils.register_class(cls)
    try:
        category, name = cls.bl_idname.split(".")
        operation = getattr(getattr(bpy.ops, category), name)
        phase = "save"
        assert operation() == {"FINISHED"}
        phase = "load"
        assert operation() == {"FINISHED"}
    finally:
        bpy.utils.unregister_class(cls)
        if own_execute is None:
            del cls.execute
        else:
            cls.execute = own_execute
        bpy.utils.register_class(cls)

assert len(json.loads(prefs.last_import_settings_json)) == len(classes)

# One stale enum value must not discard all the other remembered options.
cls = addon.game_packages.FF7R_REBIRTH_OT_import_skeletal_mesh_game_packages
own_execute = cls.__dict__.get("execute")


def stale_settings(self, context):
    for broken in ("not json", "[]", "null"):
        prefs.last_import_settings_json = broken
        self._load_last_import_settings(context)
        self._save_last_import_settings(context)
        assert isinstance(json.loads(prefs.last_import_settings_json), dict)
    prefs.last_import_settings_json = json.dumps({self.bl_idname: {
        "face_y_forward": "REMOVED_ENUM_ITEM", "attachment_sockets": "REMOVED_ENUM_ITEM",
        "connect_bones": True, "generate_mouth_controls": True,
    }})
    self._load_last_import_settings(context)
    assert self.connect_bones and self.generate_mouth_controls
    return {"FINISHED"}


bpy.utils.unregister_class(cls)
cls.execute = stale_settings
bpy.utils.register_class(cls)
try:
    assert bpy.ops.import_scene.ff7r_rebirth_skeletal_mesh_game_packages() == {"FINISHED"}
finally:
    bpy.utils.unregister_class(cls)
    if own_execute is None:
        del cls.execute
    else:
        cls.execute = own_execute
    bpy.utils.register_class(cls)

print("IMPORT_SETTINGS_OK", len(classes), "importers", len(mesh_classes), "mesh importers")
addon.unregister()
