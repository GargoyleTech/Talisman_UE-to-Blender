"""Static light baking preserves evaluated values, masks, helpers and animation."""
import math
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from addon.formats.ue_map import lights as L, light_rig as R, map_import


def near(a, b, tolerance=1e-5):
    assert math.isclose(a, b, rel_tol=tolerance, abs_tol=tolerance), (a, b)


def entry(kind, name, **props):
    return {'Type': kind + 'LightComponent', 'Name': name,
            'Properties': {'Intensity': 683, 'IntensityUnits': 'Lumens',
                           'RelativeLocation': {'Z': 200}, **props}}


bpy.ops.wm.read_factory_settings(use_empty=True)
owner = {'ObjectName': "Actor'BakeMap:PersistentLevel.Owner'"}
entries = [entry('Point', 'BakePoint', SourceRadius=10, SourceLength=100, SoftSourceRadius=20),
           entry('Spot', 'BakeSpot', SourceRadius=10, InnerConeAngle=15, OuterConeAngle=30,
                 RelativeScale3D={'X': 2, 'Y': 3, 'Z': 4}),
           entry('Rect', 'BakeArea', SourceWidth=200, SourceHeight=50, SourceTexture='/Game/Source.Source')]
entries[0]['Outer'] = owner
entries.append({'Type': 'MaterialParameterLightPlacedComponent', 'Name': 'Override', 'Outer': owner,
    'Properties': {'MaterialParameterLight': {'Intensity': 1366, 'Color': {'R': 128, 'G': 64, 'B': 255}}}})
image = bpy.data.images.new('Bake Source Texture', width=1, height=1, float_buffer=True)
image.pixels[:] = (0.5, 0.5, 0.5, 1)
scene = bpy.context.scene


def imported(bake=False, initializer=None, data=None):
    before = set(bpy.data.objects)
    map_import.import_map_entries(entries if data is None else data, 'BakeMap.umap', 2, 0.5,
        import_models=False, import_reflection_probes=False, bake_light_parameters=bake,
        component_initializer=initializer, light_texture_loader=lambda path: image)
    bpy.context.view_layer.update()
    return sorted((obj for obj in set(bpy.data.objects) - before
                   if obj.type == 'LIGHT' and not obj.get('ue_light_helper')), key=lambda obj: obj.data.type)


driven = imported()
assert all(not obj.get(R.BAKED_PROP) and obj.data.animation_data.drivers for obj in driven)


def snapshot(obj):
    objects = R._rig_objects(obj)
    values = []
    for item in objects:
        fields = ['energy', 'exposure', 'shadow_soft_size', 'cutoff_distance', 'use_custom_distance', 'temperature', 'use_temperature']
        fields += ['spot_size', 'spot_blend'] if item.data.type == 'SPOT' else []
        fields += ['size', 'size_y'] if item.data.type == 'AREA' else []
        values.append((item.get('ue_source_sample_key', 'primary'),
                       {field: getattr(item.data, field) for field in fields if hasattr(item.data, field)},
                       tuple(item.location), item.visible_glossy, item.hide_render,
                       tuple(item[L.UE_SAMPLE_OFFSET_PROP]), item[L.UE_SAMPLE_COUNT_PROP]))
    return sorted(values)


expected = [snapshot(obj) for obj in driven]
baked = imported(True)
for obj, before in zip(baked, expected):
    after = snapshot(obj)
    assert len(before) == len(after)
    for old, new in zip(before, after):
        assert old[0] == new[0] and old[3:] == new[3:], (old, new)
        for field, value in old[1].items():
            near(value, new[1][field])
        for a, b in zip(old[2], new[2]):
            near(a, b)
    for item in R._rig_owners(R._rig_objects(obj)):
        assert not item.animation_data or not item.animation_data.drivers, item.name
    assert obj.get(R.BAKED_PROP)
    assert any(node.type == 'GROUP' and node.node_tree.name == L.UE_LIGHT_ATTENUATION_GROUP_NAME
               for node in obj.data.node_tree.nodes)
point = next(obj for obj in baked if obj.data.type == 'POINT')
area = next(obj for obj in baked if obj.data.type == 'AREA')
native_exposure = hasattr(point.data, 'exposure')
near(point.data.energy, 2 if native_exposure else 4)
if native_exposure:
    near(point.data.exposure, 1)
assert area.data.node_tree.nodes['UE4 Rect Source Texture'].image == image
print('BAKED_LIGHT_VALUES_OK', flush=True)

# The whole rig is skipped when an action, NLA strip, user driver or external
# data user makes it unsafe to collapse parameters to a single static frame.
def animate(obj, _entry):
    obj.keyframe_insert(data_path=f'["{L.UE_INTENSITY_PROP}"]', frame=1)
    obj[L.UE_INTENSITY_PROP] *= 2
    obj.keyframe_insert(data_path=f'["{L.UE_INTENSITY_PROP}"]', frame=2)


animated = imported(True, animate, [entry('Spot', 'Animated')])[0]
assert not animated.get(R.BAKED_PROP) and animated.data.animation_data.drivers
scene.frame_set(1)
bpy.context.view_layer.update()
power = animated.data.energy
scene.frame_set(2)
bpy.context.view_layer.update()
near(animated.data.energy, power * 2)
action = animated.animation_data.action
track = animated.animation_data.nla_tracks.new()
track.strips.new(action.name, 1, action)
animated.animation_data.action = None
assert R.bake_static_light_parameters([animated]) == 0
foreign = imported(False, data=[entry('Point', 'ForeignDriver')])[0]
foreign.driver_add('location', 0).driver.expression = 'frame * 0.1'
assert R.bake_static_light_parameters([foreign]) == 0
shared = imported(False, data=[entry('Point', 'SharedData')])[0]
other = bpy.data.objects.new('Unrelated Shared User', shared.data)
scene.collection.objects.link(other)
assert R.bake_static_light_parameters([shared]) == 0


def animate_parent(obj, _entry):
    parent = bpy.data.objects.new('Animated Light Parent', None)
    scene.collection.objects.link(parent)
    obj.parent = parent
    parent.keyframe_insert(data_path='location', frame=1)


attached = imported(True, animate_parent, [entry('Point', 'AnimatedAttachment')])[0]
assert not attached.get(R.BAKED_PROP) and attached.data.animation_data.drivers
print('BAKED_LIGHT_ANIMATION_GUARDS_OK', flush=True)

# Power/radius/size remain editable after subsequent dependency-graph updates.
point.data.energy = 7
point.data.shadow_soft_size = 0.7
area.data.size = 3
area.data.size_y = 4
scene.frame_set(10)
bpy.context.view_layer.update()
near(point.data.energy, 7)
near(point.data.shadow_soft_size, 0.7)
near(area.data.size, 3)
near(area.data.size_y, 4)
print('BAKED_LIGHT_EDITABLE_OK', flush=True)

from addon.ui.light_attenuation import OBJECT_OT_sqex_refresh_light_source
point[L.UE_INTENSITY_PROP] *= 2
assert OBJECT_OT_sqex_refresh_light_source.execute(None, SimpleNamespace(object=point)) == {'FINISHED'}
bpy.context.view_layer.update()
assert point[R.BAKED_PROP]
near(point.data.energy, 4 if native_exposure else 8)
for helper in R._rig_objects(point)[1:]:
    near(helper.data.energy, 4 if native_exposure else 8)
    if native_exposure:
        near(helper.data.exposure, 1)
    assert not helper.data.animation_data or not helper.data.animation_data.drivers
print('BAKED_LIGHT_REFRESH_OK', flush=True)

# Compare an actual scene-linear render before and after freezing the same rig.
for obj in list(bpy.data.objects):
    if obj.type == 'LIGHT' and not obj.get('ue_light_helper'):
        obj.hide_render = True
        for helper in R._rig_objects(obj)[1:]:
            helper.hide_render = True
rendered = imported(False, data=[entry('Point', 'RenderBake', SourceRadius=10,
    SourceLength=100, SoftSourceRadius=20, Intensity=68300)])[0]
scene.render.engine = 'CYCLES'
scene.cycles.device = 'CPU'
scene.cycles.samples = 32
scene.cycles.max_bounces = 1
scene.render.resolution_x = scene.render.resolution_y = 16
scene.render.resolution_percentage = 100
scene.world = bpy.data.worlds.new('Bake Black World')
if bpy.app.version < (5, 0, 0):
    scene.world.use_nodes = True
scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value = 0
bpy.ops.mesh.primitive_plane_add(size=200)
plane = bpy.context.object
material = bpy.data.materials.new('Bake Diffuse')
if bpy.app.version < (5, 0, 0):
    material.use_nodes = True
material.node_tree.nodes.clear()
diffuse = material.node_tree.nodes.new('ShaderNodeBsdfDiffuse')
diffuse.inputs['Color'].default_value = (1, 1, 1, 1)
output = material.node_tree.nodes.new('ShaderNodeOutputMaterial')
material.node_tree.links.new(diffuse.outputs[0], output.inputs['Surface'])
plane.data.materials.append(material)
bpy.ops.object.camera_add(location=(0, 0, 1))
scene.camera = bpy.context.object
scene.camera.data.type = 'ORTHO'
scene.camera.data.ortho_scale = 0.0001


def render():
    bpy.context.view_layer.update()
    bpy.ops.render.render()
    path = str(Path(tempfile.gettempdir()) / 'talisman-baked-light.exr')
    scene.render.image_settings.file_format = 'OPEN_EXR'
    bpy.data.images['Render Result'].save_render(path, scene=scene)
    result = bpy.data.images.load(path, check_existing=False)
    value = result.pixels[(8 * 16 + 8) * 4]
    bpy.data.images.remove(result)
    return value


before = render()
assert before > 0
rendered[L.UE_EXPOSURE_PROP] = 1.0
rendered.update_tag()
near(render() / before, 0.5, 0.002)
rendered[L.UE_EXPOSURE_PROP] = 2.0
rendered.update_tag()
assert R.bake_static_light_parameters([rendered]) == 1
near(render(), before, 0.002)
print('BAKED_LIGHT_RENDER_OK', flush=True)

name = point.name
path = str(Path(tempfile.gettempdir()) / f'talisman-baked-lights-{bpy.app.version[0]}.blend')
bpy.ops.wm.save_as_mainfile(filepath=path)
bpy.ops.wm.open_mainfile(filepath=path)
point = bpy.data.objects[name]
bpy.context.scene.frame_set(20)
bpy.context.view_layer.update()
assert point[R.BAKED_PROP]
near(point.data.energy, 4 if native_exposure else 8)
point.data.energy = 10
bpy.context.view_layer.update()
near(point.data.energy, 10)
assert not point.data.animation_data or not point.data.animation_data.drivers
print('BAKED_LIGHT_SAVE_LOAD_OK', flush=True)
