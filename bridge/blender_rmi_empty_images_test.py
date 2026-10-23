"""Blender --background --factory-startup --python this_file; no game files."""
from pathlib import Path
import sys

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import addon
from addon.games.rebirth.materials import rmi_surface
from addon.language import strings

addon.generic_unreal_importer._VERSION_ITEMS[:] = [
    ("GAME_UE4_26", "UE4_26", "GAME_UE4_26", 0x041A0000),
]
addon.generic_unreal_importer._VERSIONS_LOADED = True
addon.register()
addon_entry = bpy.context.preferences.addons.new()
addon_entry.module = "addon"


class Session:
    texture_namespace = "empty-images-fixture"

    def __init__(self):
        self.image = bpy.data.images.new("Loaded texture", width=1, height=1)

    def __call__(self, path):
        return self.image if path == "/Game/Loaded" else None


try:
    prefs = addon_entry.preferences
    assert prefs.rebirth_replace_empty_image_textures is False
    prop = prefs.bl_rna.properties["rebirth_replace_empty_image_textures"]
    assert prop.default is False
    assert prop.description == strings.PREFERENCES_REBIRTH_REPLACE_EMPTY_IMAGE_TEXTURES
    prefs.rebirth_import_all_material_switches = True
    masters, _helper, truth = rmi_surface._module_set()
    session = Session()
    for profile, master in masters.items():
        variant = next(name for name, switches in truth.items()
                       if rmi_surface._master_for_switches(switches) is master)
        template = rmi_surface._ensure_master(master)
        roles = [role for _frame, role, _kind, _space, _default in master.ROLES
                 if template.node_tree.nodes.get("TEX_" + role) is not None]
        loaded, missing, renderer, vector, unassigned = roles[:5]
        data = {"properties": [
            {"name": "Parent", "value": {"ObjectPath": "/Game/Materials/" + variant}},
            {"name": "TextureParameterValues", "value": [
                {"ParameterInfo": {"Name": role}, "ParameterValue": {"ObjectPath": path}}
                for role, path in ((loaded, "/Game/Loaded"), (missing, "/Game/Missing"),
                                   (renderer, "/Game/FFFFFFFF_BC4"))
            ]},
            {"name": "VectorParameterValues", "value": [
                {"ParameterInfo": {"Name": vector}, "ParameterValue": [0.2, 0.3, 0.4, 1.0]},
            ]},
        ]}
        path = "/Game/EmptyImagesFixture/" + profile
        prefs.rebirth_replace_empty_image_textures = False
        original = rmi_surface.build_material(profile, path, data, session)
        nodes = original.node_tree.nodes
        for role in (missing, unassigned):
            assert nodes["TEX_" + role].bl_idname == "ShaderNodeTexImage"
            assert nodes["TEX_" + role].image is None
            assert nodes["TEX_" + role].mute
        assert nodes["TEX_" + loaded].image == session.image
        for role in (renderer, vector):
            assert nodes["TEX_" + role].bl_idname == "ShaderNodeTexImage"
            assert nodes["TEX_" + role].mute
        assert original["ff7r_rmi_color_constants"] == len(roles) - 1
        for role in roles:
            a, b = _helper._mix_ab(nodes["USE_" + role])
            spec = next(info for info in master.ROLES if info[1] == role)
            expected = rmi_surface._role_default_colour(spec[2], spec[4])
            if role == renderer:
                expected = (1.0, 1.0, 1.0, 1.0)
            elif role == vector:
                expected = (0.2, 0.3, 0.4, 1.0)
            if role != loaded:
                actual = (b.default_value,) if spec[2] == "val" else b.default_value
                assert all(abs(x - y) < 1e-6 for x, y in zip(actual, expected)), (profile, role)
            neutral = rmi_surface._role_default_colour(spec[2], spec[4])
            actual_a = (a.default_value,) if spec[2] == "val" else a.default_value
            assert all(abs(x - y) < 1e-6 for x, y in zip(actual_a, neutral))
        consumers = [(link.to_node.name, link.to_socket.identifier)
                     for link in nodes["TEX_" + unassigned].outputs["Color"].links]
        assert consumers

        prefs.rebirth_replace_empty_image_textures = True
        replaced = rmi_surface.build_material(profile, path, data, session)
        assert replaced != original
        for role in (renderer, vector):
            assert replaced.node_tree.nodes["TEX_" + role].bl_idname == "ShaderNodeRGB"
        for role in (missing, unassigned):
            node = replaced.node_tree.nodes["TEX_" + role]
            assert node.bl_idname == "ShaderNodeRGB"
            role_info = next(info for info in master.ROLES if info[1] == role)
            expected = rmi_surface._role_default_colour(role_info[2], role_info[4])
            assert all(abs(a - b) < 1e-6 for a, b in zip(node.outputs[0].default_value, expected))
        assert consumers == [(link.to_node.name, link.to_socket.identifier)
                             for link in replaced.node_tree.nodes["TEX_" + unassigned].outputs["Color"].links]
        assert replaced.node_tree.nodes["TEX_" + loaded].image == session.image
        assert nodes["TEX_" + unassigned].bl_idname == "ShaderNodeTexImage"
        replaced.node_tree.nodes["TEX_" + unassigned].outputs[0].default_value = (0.7, 0.6, 0.5, 1)
        assert rmi_surface.build_material(profile, path, data, session) == replaced
        assert abs(replaced.node_tree.nodes["TEX_" + unassigned].outputs[0].default_value[0] - 0.7) < 1e-6
        prefs.rebirth_replace_empty_image_textures = False
        assert rmi_surface.build_material(profile, path, data, session) == original
    print("RMI_EMPTY_IMAGES_PASS: default off; surface/eye/hair; missing/unassigned; explicit colors; loaded images; links; cache isolation")
finally:
    bpy.context.preferences.addons.remove(addon_entry)
    addon.unregister()
    assert rmi_surface._replace_empty_image_textures() is False
