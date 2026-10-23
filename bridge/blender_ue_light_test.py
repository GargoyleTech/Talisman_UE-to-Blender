"""UE 4.27 light regression: authoring controls, drivers, and Cycles masks."""
import math
from pathlib import Path
import sys

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from addon.formats.ue_map import lights as L, light_photometry as P, light_rig


def make(kind, **props):
    data = L.create_static_light_data('UE fixture ' + kind, kind, props)
    obj = bpy.data.objects.new(data.name, data)
    bpy.context.scene.collection.objects.link(obj)
    L.apply_ue_light_object_properties(obj)
    bpy.context.view_layer.update()
    return obj


def near(value, expected, tolerance=1e-5):
    assert math.isclose(value, expected, rel_tol=tolerance, abs_tol=tolerance), (value, expected)


bpy.ops.wm.read_factory_settings(use_empty=True)
point = make('POINT', Intensity=683, IntensityUnits='Lumens', LightColor={'R': 128, 'G': 255, 'B': 0})
near(point.data.energy, 1)
near(point.data.color[0], 0.2158605001)
near(point[L.UE_ATTENUATION_RADIUS_PROP], 10)
near(point.data.shadow_soft_size, 0)
near(point[L.UE_DISTANCE_BIAS_PROP], 0.0001)
assert not point[L.UE_USE_TEMPERATURE_PROP]
spot = make('SPOT', Intensity=683, IntensityUnits='Lumens', InnerConeAngle=15, OuterConeAngle=30)
near(spot.data.energy, 2 / (1 - math.cos(math.radians(30))))
near(spot.data.spot_size, math.radians(60))
near(spot.data.spot_blend, 0)
full = make('SPOT', InnerFullConeAngle=60)
near(full.data.spot_size, math.radians(90))
native = make('SPOT')
near(native.data.spot_size, math.radians(88))
near(native[L.UE_INTENSITY_PROP], 5000)
near(make('POINT', Intensity=683, IntensityUnits='Candelas').data.energy, 4 * math.pi)
near(make('AREA', Intensity=683, IntensityUnits='Candelas').data.energy, math.pi)
near(make('POINT', Intensity=683).data.energy, 64 * math.pi * 0.0001)
near(make('POINT', Intensity=683, bUseInverseSquaredFalloff=False).data.energy, 4 * math.pi)
area = make('AREA', Intensity=683, IntensityUnits='Lumens', SourceWidth=200, SourceHeight=50)
near(area.data.energy, 1)
near(area.data.size, 2)
near(area.data.size_y, 0.5)
# Remake's laboratory map uses Candela/Lumen, unlike stock UE's plural enum
# names. These must reach the physical-unit drivers rather than Unitless.
for kind in ('POINT', 'SPOT', 'AREA'):
    for alias, canonical, code in (('ELightUnits::Candela', 'Candelas', 1),
                                    ('ELightUnits::Lumen', 'Lumens', 2),
                                    ('Nit', 'Nits', 3)):
        authored = dict(Intensity=200, SourceRadius=10, OuterConeAngle=40)
        singular = make(kind, IntensityUnits=alias, **authored)
        plural = make(kind, IntensityUnits=canonical, **authored)
        assert singular[L.UE_UNIT_CODE_PROP] == code
        near(singular.data.energy, plural.data.energy)
near(make('POINT', Intensity=200, IntensityUnits='ELightUnits::Candela').data.energy,
     200 * 4 * math.pi / 683)
for obj in (point, spot, full, native, area):
    for curve in obj.data.animation_data.drivers:
        assert curve.driver.is_valid, (obj.name, curve.data_path, curve.driver.expression)
linear = make('POINT', LinearLightColor={'R': 2, 'G': 0.2, 'B': 1})
near(linear.data.color[0], 2)
tube = make('POINT', SourceLength=100, SourceRadius=10, SoftSourceRadius=20)
assert len(tube.children) == 9
near(tube[L.UE_SAMPLE_COUNT_PROP], 5)
light_rig.ensure_source_helpers(tube)
assert len(tube.children) == 9
bpy.context.view_layer.update()
for child in tube.children:
    for curve in child.animation_data.drivers:
        assert curve.driver.is_valid, (child.name, curve.data_path, curve.driver.expression)
print('UE_LIGHT_CONTROLS_OK', flush=True)

# Measure scene-linear irradiance, not display-transformed PNG brightness.
# Each comparison uses the same Cycles emitter/sample sequence with the group
# replaced by strength 1, so native area integration cancels from the ratio.
bpy.ops.wm.read_factory_settings(use_empty=True)
s = bpy.context.scene
s.render.engine = 'CYCLES'
s.cycles.device = 'CPU'
s.cycles.samples = 32
s.cycles.max_bounces = 1
s.render.resolution_x = s.render.resolution_y = 16
s.render.resolution_percentage = 100
s.world = bpy.data.worlds.new('Black')
if bpy.app.version < (5, 0, 0):
    s.world.use_nodes = True
s.world.node_tree.nodes.get('Background').inputs['Strength'].default_value = 0
bpy.ops.mesh.primitive_plane_add(size=200)
plane = bpy.context.object
material = bpy.data.materials.new('Diffuse measurement')
if bpy.app.version < (5, 0, 0):
    material.use_nodes = True
material.node_tree.nodes.clear()
diffuse = material.node_tree.nodes.new('ShaderNodeBsdfDiffuse')
diffuse.inputs['Color'].default_value = (1, 1, 1, 1)
output = material.node_tree.nodes.new('ShaderNodeOutputMaterial')
material.node_tree.links.new(diffuse.outputs[0], output.inputs['Surface'])
plane.data.materials.append(material)
bpy.ops.object.camera_add(location=(0, 0, 1))
s.camera = bpy.context.object
s.camera.data.type = 'ORTHO'
s.camera.data.ortho_scale = 0.0001


def render():
    import tempfile
    bpy.context.view_layer.update()
    bpy.ops.render.render()
    path = str(Path(tempfile.gettempdir()) / 'talisman-ue-light-test.exr')
    s.render.image_settings.file_format = 'OPEN_EXR'
    bpy.data.images['Render Result'].save_render(path, scene=s)
    image = bpy.data.images.load(path, check_existing=False)
    value = float(image.pixels[(8 * 16 + 8) * 4])
    bpy.data.images.remove(image)
    return value


def ratio(obj):
    value = render()
    tree = obj.data.node_tree
    node = next(node for node in tree.nodes if node.type == 'GROUP')
    targets = [link.to_socket for link in node.outputs['Strength'].links]
    one = tree.nodes.new('ShaderNodeValue')
    one.outputs[0].default_value = 1
    for target in targets:
        tree.links.new(one.outputs[0], target)
    reference = render()
    for target in targets:
        tree.links.new(node.outputs['Strength'], target)
    tree.nodes.remove(one)
    assert reference > 0, reference
    return value / reference


obj = make('POINT', Intensity=68300, IntensityUnits='Lumens', AttenuationRadius=400)
obj.location.z = 2
measured = ratio(obj)
near(measured, (1 - 0.5 ** 4) ** 2 * 4 / 4.0001, 0.002)
print('UE_LIGHT_INVERSE_RENDER_OK', measured, flush=True)
obj[L.UE_INVERSE_SQUARED_FALLOFF_PROP] = False
obj.update_tag()
measured = ratio(obj)
near(measured, 4 * (1 - 0.5 ** 2) ** 8, 0.002)
print('UE_LIGHT_EXPONENT_RENDER_OK', measured, flush=True)
obj.hide_render = True

obj = make('SPOT', Intensity=68300, IntensityUnits='Lumens', AttenuationRadius=100000,
           InnerConeAngle=20, OuterConeAngle=50)
obj.location.z = 2
s.camera.location.x = 2 * math.tan(math.radians(40))
measured = ratio(obj)
expected = ((math.cos(math.radians(40)) - math.cos(math.radians(50))) /
            (math.cos(math.radians(20)) - math.cos(math.radians(50)))) ** 2
near(measured, expected, 0.002)
print('UE_LIGHT_CONE_RENDER_OK', measured, flush=True)
obj.scale = (2, 0.5, 3)
near(ratio(obj), expected, 0.002)
print('UE_LIGHT_SCALED_CONE_RENDER_OK', flush=True)
obj.hide_render = True
s.camera.location.x = 0

obj = make('AREA', Intensity=68300, IntensityUnits='Lumens', AttenuationRadius=400,
           SourceWidth=400, SourceHeight=300)
obj.location.z = 2
measured = ratio(obj)
near(measured, (1 - 0.5 ** 4) ** 2, 0.002)
print('UE_LIGHT_AREA_CENTER_RENDER_OK', measured, flush=True)
obj[L.UE_ATTENUATION_RADIUS_PROP] = 2
obj.update_tag()
near(ratio(obj), 0, 0.00001)
obj[L.UE_ATTENUATION_RADIUS_PROP] = 1000
obj[L.UE_SOURCE_WIDTH_PROP] = 2
obj[L.UE_SOURCE_HEIGHT_PROP] = 2
obj[L.UE_BARN_ANGLE_PROP] = 0.0
obj[L.UE_BARN_LENGTH_PROP] = 1.0
obj.update_tag()
s.camera.location.x = 3
near(ratio(obj), 0, 0.001)
obj[L.UE_BARN_ANGLE_PROP] = math.radians(60)
obj.update_tag()
near(ratio(obj), 1, 0.002)
print('UE_LIGHT_BARN_DOOR_RENDER_OK', flush=True)

s.camera.location.x = 0
obj[L.UE_BARN_ANGLE_PROP] = math.radians(88)
obj.update_tag()
reference = render()
image = bpy.data.images.new('Rect source fixture', width=1, height=1, float_buffer=True)
image.colorspace_settings.name = 'Non-Color'
image.pixels[:] = (0.25, 0.25, 0.25, 1)
obj.data['ue_source_texture'] = '/Game/Fixture.Source'
assert L.apply_source_texture(obj, lambda path: image)
near(render() / reference, 0.25, 0.002)
print('UE_LIGHT_TEXTURE_RENDER_OK', flush=True)
obj.hide_render = True

# A tube collapsed to zero length must conserve radiant power. Changing its
# glossy-only soft source must not brighten diffuse lighting or its shadows.
obj = make('POINT', Intensity=68300, IntensityUnits='Lumens', AttenuationRadius=100000)
obj.location.z = 2
reference = render()
near(reference, 100 / (16 * math.pi * math.pi), 0.005)
light_rig.ensure_source_helpers(obj, animated_length=True, animated_soft_radius=True)
obj.update_tag()
near(render() / reference, 1, 0.006)
obj[L.UE_SOFT_SOURCE_RADIUS_PROP] = 0.5
obj.update_tag()
near(render() / reference, 1, 0.006)
obj.hide_render = True
near(render(), 0, 1e-6)
print('UE_LIGHT_SOURCE_POWER_RENDER_OK', flush=True)
