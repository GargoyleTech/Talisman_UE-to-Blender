"""Light controls through EndCinema and generic Sequencer, including save/load."""
import math
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from addon.formats.ue_map import lights as L, cutscene_import as C
from addon.formats.unreal_mesh.sequence_import import Importer


def near(value, expected):
    assert math.isclose(value, expected, rel_tol=1e-5, abs_tol=1e-5), (value, expected)


def curve(a, b, start=0, end=1000):
    return {'Times': [{'Value': start}, {'Value': end}], 'Values': [
        {'Value': a, 'InterpMode': 'RCIM_Linear'}, {'Value': b, 'InterpMode': 'RCIM_Linear'}]}


def span(lo=0, hi=2000):
    return {'Value': {'LowerBound': {'Type': 'Inclusive', 'Value': {'Value': lo}},
                      'UpperBound': {'Type': 'Exclusive', 'Value': {'Value': hi}}}}


class Fixture:
    def __init__(self):
        self.exports = []
        self.tracks = []

    def add(self, kind, **props):
        index = len(self.exports)
        self.exports.append({'Type': kind, 'Name': kind + str(index), 'Package': '/Game/Lights', 'Properties': props})
        return {'ObjectPath': '/Game/Lights.' + str(index)}

    def channel(self, name, a, b, boolean=False):
        values = {'Times': [0, 1000], 'Values': [a, b]} if boolean else curve(a, b)
        section = self.add('MovieSceneBoolSection' if boolean else 'MovieSceneFloatSection',
            SectionRange=span(), **{'BoolCurve' if boolean else 'FloatCurve': values})
        track = self.add('MovieSceneBoolTrack' if boolean else 'MovieSceneFloatTrack',
                         PropertyBinding={'PropertyName': name}, Sections=[section])
        self.tracks.append(track)


bpy.ops.wm.read_factory_settings(use_empty=True)
fixture = Fixture()
fixture.channel('Intensity', 683, 1366)
fixture.channel('AttenuationRadius', 400, 800)
fixture.channel('InnerFullConeAngle', 20, 40)
fixture.channel('OuterFullConeAngle', 60, 100)
fixture.channel('SourceRadius', 0, 10)
fixture.channel('SourceLength', 0, 100)
fixture.channel('SoftSourceRadius', 0, 20)
fixture.channel('Temperature', 3200, 6500)
fixture.channel('bUseTemperature', False, True, True)
fixture.channel('bUseInverseSquaredFalloff', True, False, True)
fixture.channel('CastShadows', True, False, True)
data = L.create_static_light_data('EndCinemaLight', 'SPOT', {})
obj = bpy.data.objects.new('EndCinemaLight', data)
bpy.context.scene.collection.objects.link(obj)
C.ALWAYS_CAST_LIGHT_SHADOWS = False
C._configure_animated_light(obj, fixture.exports, [ref['ObjectPath'] for ref in fixture.tracks],
                           SimpleNamespace(tick_num=1000, scene_fps=24), {'IntensityUnits': 'Lumens'})
scene = bpy.context.scene
scene.frame_set(12)
bpy.context.view_layer.update()
near(obj[L.UE_INTENSITY_PROP], 1024.5)
near(obj[L.UE_ATTENUATION_RADIUS_PROP], 6)
near(obj[L.UE_INNER_CONE_PROP], math.radians(15))
near(obj[L.UE_OUTER_CONE_PROP], math.radians(40))
near(obj.data.energy, 1.5 * 2 / (1 - math.cos(math.radians(40))))
near(obj.data.shadow_soft_size, 0.05)
near(obj[L.UE_SOURCE_LENGTH_PROP], 0.5)
assert len(obj.children) == 9
assert not obj[L.UE_USE_TEMPERATURE_PROP] and obj.data.use_shadow
scene.frame_set(24)
bpy.context.view_layer.update()
near(obj.data.energy, 2 * 4 * math.pi)
assert obj[L.UE_USE_TEMPERATURE_PROP] and not obj.data.use_shadow
assert not obj[L.UE_INVERSE_SQUARED_FALLOFF_PROP]
for child in obj.children:
    near(child[L.UE_SOURCE_LENGTH_PROP], 1)
    assert child.parent == obj
print('ENDCINEMA_LIGHT_ANIMATION_OK', flush=True)

# A neutral sequence uses the same object controls and respects import scale.
bpy.ops.wm.read_factory_settings(use_empty=True)
fixture = Fixture()
fixture.add('LevelSequence', MovieScene={'ObjectPath': '/Game/Lights.1'})
fixture.add('MovieScene', TickResolution={'Numerator': 1000}, DisplayRate={'Numerator': 24},
            PlaybackRange=span(), Spawnables=[], Possessables=[], ObjectBindings=[], MasterTracks=[])
fixture.channel('Intensity', 683, 1366)
fixture.channel('SourceWidth', 100, 300)
fixture.channel('SourceHeight', 100, 200)
fixture.channel('BarnDoorAngle', 30, 60)
fixture.channel('BarnDoorLength', 10, 30)
fixture.channel('AttenuationRadius', 400, 800)
fixture.channel('bUseTemperature', False, True, True)
color = fixture.add('MovieSceneColorSection', SectionRange=span(),
                    RedCurve=curve(1, 3), GreenCurve=curve(0.2, 0.4), BlueCurve=curve(1, 1))
fixture.tracks.append(fixture.add('MovieSceneColorTrack', PropertyBinding={'PropertyName': 'LightColor'}, Sections=[color]))
fixture.exports[1]['Properties'].update(
    Spawnables=[{'Guid': 'L', 'Name': 'AnimatedRect', 'ObjectTemplate': {'ObjectPath': '/Game/Template.light'}}],
    ObjectBindings=[{'ObjectGuid': 'L', 'Tracks': fixture.tracks}])


class Mounted:
    cache_namespace = 'light-animation-fixture'
    mount_info = {'contentRoot': '/Game/'}
    game_version = 'GAME_UE4_27'
    pbr_mapping = {}

    def request(self, request):
        if request['action'] == 'generic_sequence':
            return {'sequence': {'exports': fixture.exports, 'warnings': []}}
        if request['action'] == 'generic_actor_template':
            return {'template': {'actor': {'Type': 'RectLight', 'Name': 'Rect', 'ObjectPath': '/Game/Template.light',
                'Properties': {'RootComponent': {'ObjectPath': '/Game/Template.light.Component'}}},
                'components': [{'Type': 'RectLightComponent', 'Name': 'Component', 'ObjectPath': '/Game/Template.light.Component',
                    'Properties': {'Intensity': 683, 'IntensityUnits': 'Lumens'}}], 'warnings': []}}
        raise AssertionError(request)


bpy.context.scene.render.fps = 24
runner = Importer(bpy.context, Mounted(), '/Game/Lights', factor=0.02, start_frame=1)
report = runner.run()
assert report['unsupportedTracks'] == 0, report
obj = next(obj for obj in runner.collection.all_objects if obj.type == 'LIGHT')
bpy.context.scene.frame_set(13)
bpy.context.view_layer.update()
near(obj.data.energy, 6)
near(obj.data.size, 4)
near(obj.data.size_y, 3)
near(obj[L.UE_ATTENUATION_RADIUS_PROP], 12)
near(obj[L.UE_BARN_ANGLE_PROP], math.radians(45))
near(obj[L.UE_BARN_LENGTH_PROP], 0.4)
near(obj.data.color[0], 2)
near(obj.data.color[1], 0.3)
assert not obj[L.UE_USE_TEMPERATURE_PROP]
assert (obj.matrix_world.to_3x3() @ Vector((0, 0, -1))).x > 0.99
bpy.context.scene.frame_set(25)
bpy.context.view_layer.update()
assert obj[L.UE_USE_TEMPERATURE_PROP]
near(obj.data.energy, 8)
print('GENERIC_LIGHT_ANIMATION_OK', flush=True)

path = str(Path(tempfile.gettempdir()) / ('talisman-light-animation-' + str(bpy.app.version[0]) + '.blend'))
name = obj.name
bpy.ops.wm.save_as_mainfile(filepath=path)
bpy.ops.wm.open_mainfile(filepath=path)
obj = bpy.data.objects[name]
bpy.context.scene.frame_set(13)
bpy.context.view_layer.update()
near(obj.data.energy, 6)
for fcurve in obj.data.animation_data.drivers:
    assert fcurve.driver.is_valid, fcurve.data_path
print('UE_LIGHT_SAVE_LOAD_OK', flush=True)

# Tube samples must not make the generic resolver see multiple independent
# light components; rollback must remove all samples with the imported actor.
bpy.ops.wm.read_factory_settings(use_empty=True)
fixture.channel('SourceLength', 0, 100)
fixture.channel('SoftSourceRadius', 0, 20)


class PointMounted(Mounted):
    def request(self, request):
        result = super().request(request)
        if request['action'] == 'generic_actor_template':
            result['template']['components'][0]['Type'] = 'PointLightComponent'
            result['template']['components'][0]['Properties']['SourceLength'] = 20
        return result


bpy.context.scene.render.fps = 24
runner = Importer(bpy.context, PointMounted(), '/Game/Lights', factor=0.02, start_frame=1)
report = runner.run()
assert report['unsupportedTracks'] == 0 and not report['unresolvedBindings'], report
obj = next(obj for obj in runner.collection.all_objects if obj.type == 'LIGHT' and not obj.get('ue_light_helper'))
bpy.context.scene.frame_set(13)
bpy.context.view_layer.update()
near(obj[L.UE_SOURCE_LENGTH_PROP], 1)
near(obj[L.UE_SOFT_SOURCE_RADIUS_PROP], 0.2)
near(obj.data.energy, 6)
assert len(obj.children) == 9
assert (obj.matrix_world.to_3x3() @ Vector((0, 0, 1))).z > 0.99
runner.rollback()
assert not any(obj.type == 'LIGHT' for obj in bpy.data.objects)
print('GENERIC_LIGHT_SOURCE_ROLLBACK_OK', flush=True)
