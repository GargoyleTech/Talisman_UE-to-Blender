"""Blender --background --factory-startup --python this_file; no game files.

Audit every variant and render real imported slot graphs in Cycles and Eevee.
"""
from pathlib import Path
import sys
import tempfile

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from addon.games.rebirth.materials import rmi_surface as rmi


class Loader:
    texture_namespace = "fallback-fixture"

    def __init__(self, image=None):
        self.image = image

    def __call__(self, path):
        return self.image


def payload(variant, textures=None, vectors=None):
    return {"properties": [
        {"name": "Parent", "value": {"ObjectPath": "/Game/Materials/" + variant}},
        {"name": "TextureParameterValues", "value": [
            {"ParameterInfo": {"Name": role}, "ParameterValue": {"ObjectPath": path}}
            for role, path in (textures or {}).items()]},
        {"name": "VectorParameterValues", "value": [
            {"ParameterInfo": {"Name": role}, "ParameterValue": colour}
            for role, colour in (vectors or {}).items()]},
    ]}


def near(actual, expected, tol=1e-6):
    if isinstance(actual, (float, int)):
        actual, expected = (actual,), (expected,)
    assert all(abs(a - b) < tol for a, b in zip(actual, expected)), (list(actual), expected)


masters, helper, truth = rmi._module_set()
lookup_keep, lookup_replace = rmi._import_all_material_switches, rmi._replace_empty_image_textures
try:
    rmi._replace_empty_image_textures = lambda: False
    # Includes active empty samplers, inactive ones, and all three profiles.
    count = 0
    for keep in (False, True):
        rmi._import_all_material_switches = lambda: keep
        for variant, switches in truth.items():
            master = rmi._master_for_switches(switches)
            mat = rmi.build_material(variant, "/Game/Fallback/" + variant,
                                     payload(variant), Loader())
            for _frame, role, kind, _space, default in master.ROLES:
                node = mat.node_tree.nodes["TEX_" + role]
                assert node.bl_idname == "ShaderNodeTexImage" and node.image is None and node.mute
                a, b = helper._mix_ab(mat.node_tree.nodes["USE_" + role])
                near(a.default_value, default)
                near(b.default_value, default)
            bpy.data.materials.remove(mat)
            count += 1
    assert count == 208

    # Explicit constants: sRGB is decoded, data formats stay linear, HDR
    # vectors keep values >1, and a failed image can still use a vector value.
    near(rmi._renderer_constant_texture("8080FFFF_sRGB"), (0.2158605, 0.2158605, 1, 1))
    near(rmi._renderer_constant_texture("8080FFFF_BC5"), (128 / 255, 128 / 255, 1, 1))
    near(rmi._renderer_constant_texture("FFFFFFFF_BC4"), (1, 1, 1, 1))
    near(rmi._renderer_constant_texture("8080FFFF_HDR"), (128 / 255, 128 / 255, 1, 1))
    near(rmi._colour({"R": 0.1, "G": 3.3, "B": 2.3, "A": 1.0}), (0.1, 3.3, 2.3, 1))
    near(rmi._colour({"R": 128, "G": 64, "B": 255, "A": 255}), (128 / 255, 64 / 255, 1, 1))

    # Cache retry restores active vs. variant-muted state independently.
    rmi._import_all_material_switches = lambda: False
    variant = next(v for v, flags in truth.items() if "Color_" in flags and "Normal_" in flags
                   and "ToneGradient_" not in flags and rmi._master_for_switches(flags).PROFILE_NAME == "surface")
    data = payload(variant, {"Normal": "/Game/Unavailable", "ToneGradient": "/Game/UnavailableTone"})
    mat = rmi.build_material("Retry", "/Game/Retry", data, Loader())
    assert mat.node_tree.nodes["TEX_Normal"].mute
    image = bpy.data.images.new("Now available", width=1, height=1)
    assert rmi.build_material("Retry", "/Game/Retry", data, Loader(image)) == mat
    assert mat.node_tree.nodes["TEX_Normal"].image == image
    assert not mat.node_tree.nodes["TEX_Normal"].mute
    assert mat.node_tree.nodes["TEX_ToneGradient"].mute
    assert image.colorspace_settings.name == "Non-Color"
    bpy.data.materials.remove(mat)

    # Read the actual USE_<role> results through emission. Both the image
    # link and real material-switch drivers remain connected during renders.
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    bpy.ops.mesh.primitive_plane_add(size=4)
    plane = bpy.context.object
    bpy.ops.object.camera_add(location=(0, 0, 2))
    scene = bpy.context.scene
    scene.camera = bpy.context.object
    scene.camera.data.type = "ORTHO"
    scene.camera.data.ortho_scale = 2
    scene.render.resolution_x = scene.render.resolution_y = 4
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "OPEN_EXR"
    scene.render.image_settings.color_depth = "32"
    scene.cycles.samples = 1
    scene.cycles.use_denoising = False
    engines = {item.identifier for item in scene.render.bl_rna.properties["engine"].enum_items}
    eevee = "BLENDER_EEVEE" if "BLENDER_EEVEE" in engines else "BLENDER_EEVEE_NEXT"
    rmi._import_all_material_switches = lambda: True
    rendered = 0
    with tempfile.TemporaryDirectory(prefix="rmi-fallback-") as temp:
        for profile, master in masters.items():
            variant = next(v for v, flags in truth.items() if rmi._master_for_switches(flags) is master)
            scalar = next(role for _frame, role, kind, _space, _default in master.ROLES
                          if kind == "val" and master.SWITCH_FOR_ROLE.get(role) in master.CONTROL_FOR_SWITCH)
            for replace in (False, True):
                rmi._replace_empty_image_textures = lambda: replace
                data = payload(variant,
                               {"Normal": "/Game/8080FFFF_BC5", scalar: "/Game/Missing"},
                               {"Color": [0.2, 3.3, 0.8, 1.0], scalar: [0.65, 0.2, 0.1, 1.0]})
                mat = rmi.build_material("Render " + profile, "/Game/Render/" + profile, data, Loader())
                tree = mat.node_tree
                output = tree.nodes.new("ShaderNodeOutputMaterial")
                output.target = "ALL"
                for old in list(tree.nodes):
                    if old.bl_idname == "ShaderNodeOutputMaterial" and old != output:
                        tree.nodes.remove(old)
                emission = tree.nodes.new("ShaderNodeEmission")
                tree.links.new(emission.outputs[0], output.inputs["Surface"])
                plane.data.materials.clear()
                plane.data.materials.append(mat)
                for role, expected in (("Color", (0.2, 3.3, 0.8)),
                                       ("Normal", (128 / 255, 128 / 255, 1)),
                                       (scalar, (0.65,) * 3)):
                    mat[master.CONTROL_FOR_SWITCH[master.SWITCH_FOR_ROLE[role]]] = True
                    mix = tree.nodes["USE_" + role]
                    tree.links.new(next(s for s in mix.outputs if s.enabled), emission.inputs["Color"])
                    bpy.context.view_layer.update()
                    for engine in ("CYCLES", eevee):
                        scene.render.engine = engine
                        scene.render.filepath = str(Path(temp) / "sample.exr")
                        bpy.ops.render.render(write_still=True)
                        result = bpy.data.images.load(scene.render.filepath, check_existing=False)
                        near(result.pixels[:3], expected, tol=0.004)
                        bpy.data.images.remove(result)
                        rendered += 1
                bpy.data.materials.remove(mat)
    assert rendered == 36
    print("RMI_FALLBACK_PASS: 208 variants/policies; UE defaults; HDR; cache retry; 36 Cycles/Eevee renders", flush=True)
finally:
    rmi._import_all_material_switches, rmi._replace_empty_image_textures = lookup_keep, lookup_replace
