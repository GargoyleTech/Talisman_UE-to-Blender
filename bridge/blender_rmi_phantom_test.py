"""Blender --background --factory-startup --disable-autoexec --python this_file."""
from pathlib import Path
import math
import sys
import tempfile

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from addon.games.rebirth.materials import rmi_surface

masters, helper, truth = rmi_surface._module_set()
surface = masters["surface"]
template = rmi_surface._ensure_master(surface)


def source(node, socket):
    links = node.inputs[socket].links
    assert len(links) == 1, (node.name, socket)
    return links[0].from_socket


def links(tree):
    return sorted((l.from_node.name, l.from_socket.identifier, l.to_node.name, l.to_socket.identifier)
                  for l in tree.links)


def assert_graph(material):
    tree = material.node_tree
    n = tree.nodes
    assert all(n.get(name) for name in surface.PHANTOM_NODES)
    assert not n.get("N_Detail Normalize")
    assert source(n["DetailLayer"], "Detail Normal").node == n["N_Detail"]
    assert not n["FF7R / Hologram Highlight / Color Only"].node_tree.nodes.get("View toward camera / normalize Incoming")
    assert not bpy.data.node_groups["FF7R Util/RNM"].nodes.get("detail_normalize")
    assert n["N_Base Normalize"].operation == n["N_Transition Normalize"].operation == "NORMALIZE"
    tone = n["ToneGradient UV"]
    assert len(tone.node_tree.nodes) == 20 and len(tone.node_tree.links) == 25
    assert tone.node_tree.nodes["Actual camera"].mute
    assert tone.node_tree.nodes["View vector to world"].mute
    assert source(tone, "Normal").node == n["N_SharedWorld"]
    assert source(tone, "Roughness").node == n["LayerBlend"]
    assert source(tone, "WideOcclusion").node == n["USE_WideOcclusion"]
    if n["TEX_ToneGradient"].bl_idname == "ShaderNodeTexImage":
        assert source(n["TEX_ToneGradient"], "Vector").node == tone
        assert n["TEX_ToneGradient"].interpolation == "Linear"
    assert source(n["PhantomOverride"], "B").node == n["Final linear RGB"]
    assert source(n["PhantomOverride"], "A").node == n["HologramOverride"]
    assert source(n["Emission"], "Color").node == n["PhantomOverride"]
    assert source(n["Principled BSDF"], "Base Color").node == n["PhantomOverride"]
    assert source(n["Principled BSDF"], "Alpha").node == n["AlphaWithoutBackfaces"]
    fade = n["Alpha = smooth depth fade"]
    assert fade.interpolation_type == "SMOOTHSTEP" and fade.clamp
    assert source(fade, "Value").name == "View Z Depth"
    assert source(fade, "From Max").node == n["Phantom Fade Distance"]
    assert n["RGB depth fade = alpha^8"].inputs[1].default_value == 8.0
    assert not any(node.label == "Depth Gap" for node in n)
    assert source(n["Transparent BSDF"], "Color").node == n["PhantomOpaque"]
    assert surface._in(n["PhantomOpaque"], "B").default_value == 0.0
    assert source(n["Math.003"], 0).node == source(n["Math.003"], 1).node == n["Math.002"]
    assert source(n["Mix Shader"], 0).node == n["Math.003"]
    assert source(n["Mix Shader (Cycles)"], 0).node == n["Math.004"]
    assert source(n["Math.004"], 0).node == n["Math.003"]
    assert tree.get_output_node("EEVEE") == n["Material Output"]
    assert tree.get_output_node("CYCLES") == n["Material Output (Cycles)"]
    assert source(n["Emissive"], "ExternalEmissiveContext").node == n["external_tint"]
    assert n["external_tint"].attribute_name == "ExternalEmissiveContext"
    assert n["external_tint"].attribute_type == "OBJECT"
    assert n["FRAME_Base Docs"].text.as_string() == surface.SURFACE_TEXTURE_DOC_TEXT
    assert all(l.is_valid for l in tree.links)


assert_graph(template)
assert template.node_tree.nodes["Phantom Fade Distance"].outputs[0].default_value == 5.0
for name, switches in truth.items():
    if "Phantom_" not in switches:
        continue
    for keep_all in (False, True):
        material = template.copy()
        helper.apply_variant(material, surface, name, set(switches), keep_all_switches=keep_all)
        assert_graph(material)
        assert material.surface_render_method == "BLENDED" and material.use_transparency_overlap
        if not keep_all:
            # Preserve the existing variant policy, rather than F10's saved unmuting.
            assert material.node_tree.nodes["BloodOverride"].mute
            assert material.node_tree.nodes["TEX_Color"].mute
            assert not material.node_tree.nodes["TEX_ToneGradient"].mute
            assert material.node_tree.nodes["TEX_Coverage"].mute == ("Coverage_" not in switches)
        bpy.data.materials.remove(material)


def make_legacy(material):
    tree = material.node_tree
    n = tree.nodes
    phantom = source(n["Math.004"], 1)
    tree.links.new(phantom, n["Math.003"].inputs[1])
    tree.links.new(n["Math.003"].outputs[0], n["Mix Shader (Cycles)"].inputs[0])
    tree.links.new(n["HologramOverride"].outputs[2], n["Emission"].inputs["Color"])
    tree.links.new(n["HologramOverride"].outputs[2], n["Principled BSDF"].inputs["Base Color"])
    tree.links.new(n["UV0"].outputs[0], n["TEX_ToneGradient"].inputs["Vector"])
    n["TEX_ToneGradient"].interpolation = "Closest"
    normal = n.new("ShaderNodeVectorMath")
    normal.name = "N_Detail Normalize"
    normal.operation = "NORMALIZE"
    tree.links.new(n["N_Detail"].outputs[0], normal.inputs[0])
    tree.links.new(normal.outputs[0], n["DetailLayer"].inputs["Detail Normal"])
    for name in surface.PHANTOM_NODES:
        n.remove(n[name])
    n["Transparent BSDF"].inputs["Color"].default_value = (1, 1, 1, 1)


legacy = template.copy()
legacy.name = "Legacy Phantom upgrade fixture"
legacy["Object Fade"] = 0.73
image = bpy.data.images.new("Preserved Phantom texture", 1, 1)
legacy.node_tree.nodes["TEX_ToneGradient"].image = image
legacy.node_tree.nodes["TEX_Color"].mute = True
make_legacy(legacy)
old_nodes = {n.name: (n.as_pointer(), tuple(n.location_absolute), n.mute)
             for n in legacy.node_tree.nodes if n.name != "N_Detail Normalize"}

# Reproduce old shared Emissive/RNM/highlight groups without rebuilding interfaces.
emissive = bpy.data.node_groups["FF7R Emissive"]
context = next(i for i in emissive.interface.items_tree if i.name == "ExternalEmissiveContext")
emissive.links.new(emissive.nodes["external_tint"].outputs["Color"], surface._in(emissive.nodes["external"], "B"))
emissive.interface.remove(context)
identifiers = [i.identifier for i in emissive.interface.items_tree]
eye = masters["eye"].build(uv_names=["Coordinate0", "Coordinate1"])
assert not eye.node_tree.nodes["Emissive"].inputs.get("ExternalEmissiveContext")
for group, name, original, target in (
        (bpy.data.node_groups["FF7R Util/RNM"], "detail_normalize", "detail_strength", "detail_xyz"),
        (bpy.data.node_groups["FF7R Hologram Highlight / Color Only"], "View toward camera / normalize Incoming",
         "Geometry shading normal + view direction", "World N dot view")):
    socket = group.nodes[target].inputs[0 if target == "detail_xyz" else 1]
    before = socket.links[0].from_socket
    normalize = group.nodes.new("ShaderNodeVectorMath")
    normalize.name, normalize.operation = name, "NORMALIZE"
    group.links.new(before, normalize.inputs[0])
    group.links.new(normalize.outputs[0], socket)

assert rmi_surface.refresh_hologram_material(legacy)
assert_graph(legacy)
assert legacy["Object Fade"] == 0.73
assert legacy.node_tree.nodes["TEX_ToneGradient"].image == image
for name, (pointer, location, muted) in old_nodes.items():
    node = legacy.node_tree.nodes[name]
    assert (node.as_pointer(), tuple(node.location_absolute), node.mute) == (pointer, location, muted), name
assert [i.identifier for i in emissive.interface.items_tree][:len(identifiers)] == identifiers
assert source(eye.node_tree.nodes["Emissive"], "ExternalEmissiveContext").node.attribute_name == "ExternalEmissiveContext"
legacy.node_tree.nodes["Phantom Fade Distance"].outputs[0].default_value = 7.25
before = links(legacy.node_tree)
assert rmi_surface.refresh_hologram_material(legacy)
assert links(legacy.node_tree) == before
assert legacy.node_tree.nodes["Phantom Fade Distance"].outputs[0].default_value == 7.25

# The frame owns a real Text datablock, survives reload, and reuses it on build.
legacy.use_fake_user = True
with tempfile.TemporaryDirectory(prefix="rmi_phantom_text_") as directory:
    path = str(Path(directory) / "reload.blend")
    bpy.ops.wm.save_as_mainfile(filepath=path)
    bpy.ops.wm.open_mainfile(filepath=path, use_scripts=False)
    restored = bpy.data.materials["Legacy Phantom upgrade fixture"]
    assert_graph(restored)
    old_text = restored.node_tree.nodes["FRAME_Base Docs"].text
    surface.build(uv_names=[f"Coordinate{i}" for i in range(4)])
    assert bpy.data.materials[surface.MAT_NAME].node_tree.nodes["FRAME_Base Docs"].text == old_text
    assert len([t for t in bpy.data.texts if t.name.startswith(surface.SURFACE_TEXTURE_DOC_NAME)]) == 1

assert not surface._LOG, surface._LOG

# Exercise the production Phantom output with an HDR 2-texel lookup and an
# opaque background. This checks LUT filtering, object tint, smooth depth^8,
# the Cycles selector and Phantom's black-transparency selection together.
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
bpy.ops.mesh.primitive_plane_add(size=4)
plane = bpy.context.object
plane.data.uv_layers[0].name = "Coordinate0"
plane["ExternalEmissiveContext"] = (1.0, 2.0, 3.0)
rendered_material = bpy.data.materials[surface.MAT_NAME].copy()
variant = "RMI_Surface_Unlit_Phantom_Coverage_Wide_Character"
helper.apply_variant(rendered_material, surface, variant, set(truth[variant]))
plane.data.materials.append(rendered_material)
image = bpy.data.images.new("Phantom two-texel HDR", 2, 1, float_buffer=True)
image.colorspace_settings.name = "Non-Color"
image.pixels[:] = (2, .5, .25, 1, 4, 1, .5, 1)
rendered_material.node_tree.nodes["TEX_ToneGradient"].image = image
tone = rendered_material.node_tree.nodes["ToneGradient UV"]
for name, value in (("Normal", (0, 0, 1)), ("Roughness", 0.0), ("WideOcclusion", .75)):
    for link in list(tone.inputs[name].links):
        rendered_material.node_tree.links.remove(link)
    tone.inputs[name].default_value = value
bpy.ops.mesh.primitive_plane_add(size=4, location=(0, 0, -1))
background = bpy.data.materials.new("Opaque Phantom test background")
tree = background.node_tree
tree.nodes.clear()
output = tree.nodes.new("ShaderNodeOutputMaterial")
emission = tree.nodes.new("ShaderNodeEmission")
emission.inputs["Color"].default_value = (.1, .1, .1, 1)
tree.links.new(emission.outputs[0], output.inputs["Surface"])
bpy.context.object.data.materials.append(background)
bpy.ops.object.camera_add(location=(0, 0, 10))
scene = bpy.context.scene
scene.camera = bpy.context.object
scene.camera.data.type = "ORTHO"
scene.camera.data.ortho_scale = 2
scene.render.engine = "CYCLES"
scene.cycles.device = "CPU"
scene.cycles.samples = 1
scene.cycles.use_denoising = False
scene.render.resolution_x = scene.render.resolution_y = 16
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "OPEN_EXR"
scene.render.image_settings.color_depth = "32"
scene.world.use_nodes = True
scene.world.node_tree.nodes["Background"].inputs["Color"].default_value = (0, 0, 0, 1)
coordinate = .75 - 1 + math.sqrt(.75)
weight = 2 * coordinate - .5
color = (2 + 2 * weight, 2 * (.5 + .5 * weight), 3 * (.25 + .25 * weight))
with tempfile.TemporaryDirectory(prefix="rmi_phantom_render_") as directory:
    for distance, fade in ((10, 1), (2.5, .5 ** 8)):
        scene.camera.location.z = distance
        scene.frame_set(scene.frame_current + 1)
        scene.render.filepath = str(Path(directory) / (str(distance) + ".exr"))
        bpy.ops.render.render(write_still=True)
        result = bpy.data.images.load(scene.render.filepath, check_existing=False)
        pixels = list(result.pixels)
        actual = pixels[4 * (8 * 16 + 8):4 * (8 * 16 + 8) + 3]
        expected = [channel * fade for channel in color]
        assert max(abs(a - b) for a, b in zip(actual, expected)) < 1e-4, (distance, actual, expected)
        bpy.data.images.remove(result)
        print("RMI_PHANTOM_RENDER_PASS", distance, actual)

print("RMI_PHANTOM_PASS: selected F01-F05/F07-F09; existing muting; three normalizers retired; shared users preserved; linked text save/reload")
