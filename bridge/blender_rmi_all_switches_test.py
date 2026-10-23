"""Blender --background --factory-startup --python this_file; no game files."""
import json
from pathlib import Path
import sys

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import addon
from addon.games.rebirth.materials import rmi_surface
from addon.language import strings

# Registration must not launch the bridge to enumerate versions in this test.
addon.generic_unreal_importer._VERSION_ITEMS[:] = [
    (name, name, name, index) for index, name in enumerate((
        "GAME_UE4_26", "GAME_UE4_27", "GAME_HogwartsLegacy", "GAME_UE5_5", "GAME_MarvelRivals"))
]
addon.generic_unreal_importer._VERSIONS_LOADED = True
addon.register()
addon_entry = bpy.context.preferences.addons.new()
addon_entry.module = "addon"


class Session:
    texture_namespace = "all-switches-fixture"

    def __call__(self, _path):
        return None


try:
    prefs = bpy.context.preferences.addons["addon"].preferences
    assert prefs.rebirth_import_all_material_switches is False
    prop = prefs.bl_rna.properties["rebirth_import_all_material_switches"]
    assert prop.name == "Always Import All Material Switches"
    assert prop.description == strings.PREFERENCES_REBIRTH_IMPORT_ALL_MATERIAL_SWITCHES
    assert not rmi_surface._import_all_material_switches()

    masters, helper, truth = rmi_surface._module_set()
    count = 0
    for variant, switches in truth.items():
        builder = rmi_surface._master_for_switches(switches)
        template = rmi_surface._ensure_master(builder)
        material = template.copy()
        stats = helper.apply_variant(material, builder, variant, set(switches), keep_all_switches=True)
        assert stats["removed"] == [] and stats["muted"] == 0 and stats["ladder"] == 0
        assert material["Shading Model"] == helper.shading_model_for(set(switches))
        curves = {curve.data_path: curve for curve in material.node_tree.animation_data.drivers}
        for control, members, _default in builder.SWITCH_CONTROLS:
            assert control in material
            assert material[control] is any(member in switches for member in members)
            node = material.node_tree.nodes["SW_" + members[0]]
            curve = curves[node.path_from_id() + ".outputs[0].default_value"]
            assert not curve.mute and curve.driver.type == "AVERAGE"
            target = curve.driver.variables[0].targets[0]
            assert target.id == material and target.data_path == '[' + json.dumps(control) + ']'
            assert "disabled" not in node.label
        assert all(prop[0] in material for prop in builder.ENUM_PROPS + builder.FLOAT_PROPS)
        assert not any(node.mute for node in material.node_tree.nodes)
        assert list(material["_RMI_Variant_Switches"]) == sorted(switches)
        bpy.data.materials.remove(material)
        count += 1
    assert count == 104

    # Exercise the actual preference lookup through the package material
    # builder, including reuse and changing the preference in one session.
    variant = next(name for name, switches in truth.items()
                   if rmi_surface._master_for_switches(switches).PROFILE_NAME == "surface"
                   and "Hologram_" not in switches and "Blood_" not in switches)
    data = {"properties": [{"name": "Parent", "value": {
        "ObjectPath": "/Game/Renderer/MaterialInstance/Surface/" + variant}}]}
    session = Session()
    path = "/Game/AllSwitchesFixture/Material"
    control = masters["surface"].CONTROL_FOR_SWITCH["Hologram_"]

    trimmed = rmi_surface.build_material("Switch fixture", path, data, session)
    assert control not in trimmed
    assert trimmed.node_tree.nodes["BloodOverride"].mute
    prefs.rebirth_import_all_material_switches = True
    assert rmi_surface._import_all_material_switches()
    complete = rmi_surface.build_material("Switch fixture", path, data, session)
    assert complete != trimmed
    assert control in complete and complete[control] is False
    assert control not in trimmed
    assert not any(node.mute for node in complete.node_tree.nodes
                   if node.bl_idname != "ShaderNodeTexImage")
    assert all(node.mute for node in complete.node_tree.nodes
               if node.bl_idname == "ShaderNodeTexImage" and node.image is None)
    complete[control] = True
    assert rmi_surface.build_material("Switch fixture", path, data, session) == complete
    assert complete[control] is True, "Cached imports must preserve artist edits"
    prefs.rebirth_import_all_material_switches = False
    assert rmi_surface.build_material("Switch fixture", path, data, session) == trimmed
    assert complete[control] is True
    print("RMI_ALL_SWITCHES_PASS: preference RNA; 104 variants; live drivers and paths; cache isolation; preserved edits")
finally:
    bpy.context.preferences.addons.remove(addon_entry)
    addon.unregister()
