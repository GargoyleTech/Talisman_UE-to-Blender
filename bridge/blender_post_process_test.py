"""Numerically verify compositor LUT sampling and saved post-process data."""
from pathlib import Path
import sys
import tempfile
import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from addon.formats.ue_map.post_process import create_lut_group, import_camera_regions
from addon.formats.ue_map.map_import import rotation_from_relative

# A non-identity cube swaps axes and remaps ranges, detecting atlas orientation
# mistakes as well as missing blue-slice interpolation.
n = 4
image = bpy.data.images.new('Analytic LUT', width=n * n, height=n, float_buffer=True)
image.colorspace_settings.name = 'Non-Color'
pixels = np.zeros((n, n, n, 4), dtype=np.float32)
for y in range(n):
    for z in range(n):
        for x in range(n):
            pixels[y, z, x] = (.1 + .5 * z / (n - 1), .2 + .4 * x / (n - 1), .3 + .3 * y / (n - 1), 1)
image.pixels.foreach_set(pixels.ravel())
image['ue_lut_size'] = n
image.pack()
group = create_lut_group('Analytic LUT Group', image)
assert group.use_fake_user
props = {'CameraISO': 800, 'CameraFStop': 11., 'CameraShutterSpeed': .625,
         'bOverride_CameraISO': True, 'BlendTime': 3., 'Priority': 'Effect',
         'RelativeLocation': {'X': 100, 'Y': 200, 'Z': 300},
         'RelativeScale3D': {'X': 10, 'Y': 20, 'Z': 30}}
entries = [
    {'Type': 'PostProcessCameraComponent', 'Name': 'CameraSettings', 'Outer': {'ObjectPath': '/Map.CameraA'}, 'Properties': props},
    {'Type': 'PostProcessCameraComponent', 'Name': 'CameraSettings', 'Outer': {'ObjectPath': '/Map.CameraB'}, 'Properties': dict(props)},
    {'Type': 'PostProcessColorCorrectionComponent', 'Properties': dict(props,
        ColorCorrectionLUTHDR={'ObjectPath': '/Game/TestLUT.TestLUT'})},
]
assert import_camera_regions(entries, 'Fixture.umap', .01, rotation_from_relative, lambda path: image) == 2
camera_a, camera_b = bpy.data.objects['CameraA'], bpy.data.objects['CameraB']
assert camera_a.type == 'EMPTY' and tuple(camera_a.location) == (1., -2., 3.)
assert camera_a['CameraISO'] == 800 and camera_a['bOverride_CameraISO']
assert camera_a['ue_compositor_group'] != camera_b['ue_compositor_group']
assert all(bpy.data.node_groups[o['ue_compositor_group']].use_fake_user for o in (camera_a, camera_b))

# Drive the group from a 4x4 image with endpoints and fractional sample points.
source = bpy.data.images.new('LUT test input', width=4, height=4, float_buffer=True)
source.colorspace_settings.name = 'Non-Color'
values = np.array([(r, g, b, .6) for r, g, b in [
    (0, 0, 0), (1, 1, 1), (.2, .4, .6), (.8, .1, .7),
    (1, 0, 0), (0, 1, 0), (0, 0, 1), (.5, .5, .5),
    (.11, .22, .33), (.9, .8, .7), (.3, .6, .9), (.99, .01, .49),
    (0, 0, .5), (.5, 0, 0), (0, .5, 0), (.17, .63, .81),
]], dtype=np.float32)
source.pixels.foreach_set(values.ravel())
source.pack()
scene = bpy.context.scene
if bpy.app.version >= (5, 0, 0):
    tree = bpy.data.node_groups.new('LUT Render Test', 'CompositorNodeTree')
    tree.interface.new_socket(name='Image', in_out='OUTPUT', socket_type='NodeSocketColor')
    scene.compositing_node_group = tree
    output = tree.nodes.new('NodeGroupOutput')
else:
    scene.use_nodes = True
    tree = scene.node_tree
    tree.nodes.clear()
    output = tree.nodes.new('CompositorNodeComposite')
input_node = tree.nodes.new('CompositorNodeImage')
input_node.image = source
apply = tree.nodes.new('CompositorNodeGroup')
apply.node_tree = group
tree.links.new(input_node.outputs[0], apply.inputs['Image'])
tree.links.new(apply.outputs[0], output.inputs[0])
scene.render.engine = 'CYCLES'
scene.cycles.samples = 1
scene.cycles.use_denoising = False
scene.render.resolution_x = scene.render.resolution_y = 4
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = 'OPEN_EXR'
scene.render.image_settings.color_depth = '32'
scene.render.image_settings.color_mode = 'RGBA'
with tempfile.TemporaryDirectory(prefix='talisman_lut_test_') as directory:
    result_path = str(Path(directory) / 'lut.exr')
    scene.render.filepath = result_path
    bpy.ops.render.render(write_still=True)
    result = bpy.data.images.load(result_path, check_existing=False)
    actual = np.array(result.pixels[:]).reshape(-1, 4)
    expected = np.column_stack((.1 + .5 * values[:, 2], .2 + .4 * values[:, 0],
                                .3 + .3 * values[:, 1], values[:, 3]))
    assert np.allclose(actual, expected, atol=2e-4), (actual.tolist(), expected.tolist())
    print('COMPOSITOR_LUT_NUMERIC_OK max error', float(abs(actual - expected).max()), flush=True)
    scene.render.filepath = str(Path(directory) / 'bypass.exr')
    apply.inputs['LUT Strength'].default_value = 0
    bpy.ops.render.render(write_still=True)
    bypass = bpy.data.images.load(scene.render.filepath, check_existing=False)
    assert np.allclose(np.array(bypass.pixels[:]).reshape(-1, 4), values, atol=2e-4)
    scene.render.filepath = ''
    if bpy.app.version >= (5, 0, 0):
        scene.compositing_node_group = None
    saved_name = group.name
    bpy.context.preferences.filepaths.save_version = 0
    filepath = str(Path(directory) / 'persistent.blend')
    bpy.ops.wm.save_as_mainfile(filepath=filepath)
    bpy.ops.wm.open_mainfile(filepath=filepath)
    saved = bpy.data.node_groups[saved_name]
    assert saved.use_fake_user
    assert any(node.type == 'IMAGE' and node.image.packed_file for node in saved.nodes)
    assert bpy.data.objects['CameraA']['CameraISO'] == 800
print('POST_PROCESS_PERSISTENCE_OK', flush=True)
