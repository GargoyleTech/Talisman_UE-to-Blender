"""Compare the Unreal node with native Image Texture sampling in Cycles."""

from pathlib import Path
import sys
import tempfile

import bpy
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
bpy.ops.preferences.addon_enable(module="addon")
import addon

scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.device = "CPU"
scene.cycles.samples = 1
scene.cycles.use_denoising = False
scene.render.resolution_x = scene.render.resolution_y = 24
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.view_settings.view_transform = "Standard"
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
bpy.ops.mesh.primitive_plane_add(size=2)
plane = bpy.context.object
material = bpy.data.materials.new("Texture sampling comparison")
if bpy.app.version < (5, 0, 0):
    material.use_nodes = True
plane.data.materials.append(material)
tree = material.node_tree
tree.nodes.clear()
image = bpy.data.images.new("Four corners", width=2, height=2, alpha=True)
image.pixels[:] = [1, 0, 0, 1, 0, 1, 0, 1, 0, 0, 1, 1, 1, 1, 0, 1]
image.pack()
custom = tree.nodes.new("SQEX_ShaderNodeUnrealTexture")
custom.image = image
custom.interpolation = "Closest"
custom.browser_open = False
native = tree.nodes.new("ShaderNodeTexImage")
native.image = image
native.interpolation = "Closest"
emission = tree.nodes.new("ShaderNodeEmission")
output = tree.nodes.new("ShaderNodeOutputMaterial")
tree.links.new(emission.outputs[0], output.inputs["Surface"])
coordinates = tree.nodes.new("ShaderNodeTexCoord")
mapping = tree.nodes.new("ShaderNodeVectorMath")
mapping.operation = "SCALE"
mapping.inputs["Scale"].default_value = 0.5
tree.links.new(coordinates.outputs["UV"], mapping.inputs[0])
camera_data = bpy.data.cameras.new("Camera")
camera_data.type = "ORTHO"
camera_data.ortho_scale = 2
camera = bpy.data.objects.new("Camera", camera_data)
scene.collection.objects.link(camera)
camera.location = (0, 0, 2)
scene.camera = camera

with tempfile.TemporaryDirectory(prefix="ue_texture_render_") as directory:
    def render(texture, name):
        tree.links.new(texture.outputs["Color"], emission.inputs["Color"])
        scene.render.filepath = str(Path(directory) / (name + ".png"))
        bpy.ops.render.render(write_still=True)
        result = bpy.data.images.load(scene.render.filepath, check_existing=False)
        pixels = np.array(result.pixels[:])
        bpy.data.images.remove(result)
        return pixels
    native_uv = render(native, "native_uv")
    custom_uv = render(custom, "custom_uv")
    assert np.max(np.abs(native_uv - custom_uv)) < 1e-5
    tree.links.new(mapping.outputs["Vector"], native.inputs["Vector"])
    custom_link = tree.links.new(mapping.outputs["Vector"], custom.inputs["Vector"])
    native_mapped = render(native, "native_mapped")
    custom_mapped = render(custom, "custom_mapped")
    assert np.max(np.abs(native_mapped - custom_mapped)) < 1e-5
    assert np.max(np.abs(custom_uv - custom_mapped)) > 0.5
    tree.links.remove(custom_link)
    restored = render(custom, "restored_uv")
    assert np.max(np.abs(restored - native_uv)) < 1e-5

addon.unregister()
print("TEXTURE_NODE_RENDER_OK (UV defaults, explicit Vector, unlink restores UV)")
