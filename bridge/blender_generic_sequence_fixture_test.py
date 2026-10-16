"""Neutral Sequencer regression fixtures; no game data or local paths required."""

from pathlib import Path
import copy
import sys

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import addon
addon.register()
from addon.formats.unreal_mesh.sequence_data import Channel, Graph, bounds, rate
from addon.formats.unreal_mesh.sequence_import import Importer
from addon.games.rebirth.importers.packages import _active_collection


def span(lower, upper):
    return {"Value": {"LowerBound": {"Type": "Inclusive", "Value": {"Value": lower}},
                      "UpperBound": {"Type": "Exclusive", "Value": {"Value": upper}}}}


class Builder:
    def __init__(self, path, ticks=1000, end=8000):
        self.path, self.exports = path, []
        self.add("LevelSequence", MovieScene={"ObjectPath": path + ".1"})
        self.add("MovieScene", TickResolution={"Numerator": ticks}, DisplayRate={"Numerator": 30},
                 PlaybackRange=span(0, end), Spawnables=[], Possessables=[], ObjectBindings=[], MasterTracks=[])

    def add(self, kind, **props):
        index = len(self.exports)
        self.exports.append({"Type": kind, "Name": kind + str(index), "Package": self.path, "Properties": props})
        return {"ObjectPath": self.path + "." + str(index)}

    def spawn(self, binding_id, name, template, tracks):
        props = self.exports[1]['Properties']
        props['Spawnables'].append({"Guid": binding_id, "Name": name, "ObjectTemplate": {"ObjectPath": template}})
        props['ObjectBindings'].append({"ObjectGuid": binding_id, "BindingName": name, "Tracks": tracks})

    def payload(self):
        return {"exports": self.exports, "warnings": []}


def curve(start, end, a, b):
    return {"Times": [{"Value": start}, {"Value": end}], "Values": [
        {"Value": a, "InterpMode": "RCIM_Linear"}, {"Value": b, "InterpMode": "RCIM_Linear"}]}


root = Builder('/Game/Root')
child = Builder('/Game/Child', ticks=2000, end=4000)
transform_section = child.add('MovieScene3DTransformSection', Translation=curve(0, 4000, 0, 200), SectionRange=span(0, 4000))
transform_track = child.add('MovieScene3DTransformTrack', Sections=[transform_section])
float_section = child.add('MovieSceneFloatSection', FloatCurve=curve(0, 4000, 20, 60), SectionRange=span(0, 4000))
float_track = child.add('MovieSceneFloatTrack', PropertyBinding={'PropertyName': 'CurrentFocalLength'}, Sections=[float_section])
child.spawn('CA', 'Camera', '/Game/Templates.camera', [transform_track, float_track])
cut = child.add('MovieSceneCameraCutSection', CameraBindingID={'Guid': 'CA', 'ResolveParentIndex': 0}, SectionRange=span(0, 4000))
child.exports[1]['Properties']['CameraCutTrack'] = child.add('MovieSceneCameraCutTrack', Sections=[cut])
sub = root.add('MovieSceneSubSection', SubSequence={'ObjectPath': '/Game/Child.Child'},
               Parameters={'StartFrameOffset': {'Value': 500}, 'TimeScale': 2}, SectionRange=span(1000, 5000))
root.exports[1]['Properties']['MasterTracks'].append(root.add('MovieSceneSubTrack', Sections=[sub]))
anim_sections = [root.add('MovieSceneSkeletalAnimationSection', Params={'Animation': {'ObjectPath': path},
    'Weight': {'DefaultValue': 0.5, 'bHasDefaultValue': True}}, SectionRange=span(lo, hi))
    for path, lo, hi in (('/Game/One.One', 0, 4000), ('/Game/Three.Three', 2000, 6000))]
anim_track = root.add('MovieSceneSkeletalAnimationTrack', AnimationSections=anim_sections)
spawn_section = root.add('MovieSceneSpawnSection', BoolCurve={'DefaultValue': True, 'bHasDefaultValue': True}, SectionRange=span(0, 6000))
spawn_track = root.add('MovieSceneSpawnTrack', Sections=[spawn_section])
root.spawn('RI', 'Robot', '/Game/Templates.robot', [anim_track, spawn_track])
event_section = root.add('MovieSceneEventTriggerSection', EventChannel={'Times': [{'Value': 2000}]}, SectionRange=span(0, 8000))
root.exports[1]['Properties']['MasterTracks'].append(root.add('MovieSceneEventTrack', Sections=[event_section]))

SKELETON = {'bones': [{'name': 'Root', 'parentIndex': -1, 'translation': [0, 0, 0], 'rotation': [0, 0, 0, 1], 'scale': [1, 1, 1]}]}
MESH = {'name': 'Robot', 'positions': [[0, 0, 0], [10, 0, 0], [0, 0, 10]], 'normals': [[0, 1, 0]] * 3,
        'indices': [0, 1, 2], 'uvChannels': [[[0, 0], [1, 0], [0, 1]]], 'sections': [],
        'boneNames': ['Root'], 'weights': [[[0, 1.0]]] * 3, 'inlineSkeleton': SKELETON,
        'skeletonPath': '/Game/RobotSkeleton', 'linkedSkeletonPath': '/Game/RobotSkeleton.RobotSkeleton'}


class Mounted:
    cache_namespace = 'sequence-fixture'
    mount_info = {'contentRoot': '/Game/'}
    game_version = 'GAME_UE4_27'
    pbr_mapping = {}

    def request(self, request):
        if request['action'] == 'generic_sequence':
            return {'sequence': child.payload() if 'Child' in request['assetPath'] else root.payload()}
        if request['action'] == 'generic_actor_template':
            camera = request['objectPath'].endswith('camera')
            path = request['objectPath']
            return {'template': {'actor': {'Type': 'CineCameraActor' if camera else 'SkeletalMeshActor', 'Name': 'Template',
                'ObjectPath': path, 'Properties': {'RootComponent': {'ObjectPath': path + '.Component'}}},
                'components': [{'Type': 'CineCameraComponent' if camera else 'SkeletalMeshComponent', 'Name': 'Component',
                    'ObjectPath': path + '.Component', 'Properties': {'CurrentFocalLength': 35} if camera else
                    {'SkeletalMesh': {'ObjectPath': '/Game/Robot.Robot'}}}], 'warnings': []}}
        raise AssertionError(request)

    def skeletal_mesh(self, path, **kwargs):
        return MESH

    def animation_asset(self, path):
        x = 100 if 'One' in path else 300
        return {'name': path, 'skeletonPath': '/Game/RobotSkeleton', 'referenceSkeleton': SKELETON,
            'numFrames': 2, 'framesPerSecond': 1, 'duration': 1,
            'tracks': [{'boneName': 'Root', 'translations': [[x, 0, 0]] * 2, 'rotations': [[0, 0, 0, 1]] * 2, 'scales': [[1, 1, 1]] * 2}]}

    def skeleton_asset(self, path):
        return {'sockets': [{'name': 'HandSocket', 'boneName': 'Root', 'translation': [10, 20, 30],
                             'rotation': [0, 0, 0, 1], 'scale': [1, 1, 1]}]}


graph = Graph(lambda path: child.payload() if 'Child' in path else root.payload(), '/Game/Root')
assert graph.duration == 8 and len(graph.instances) == 2
instance = graph.instances[1]
assert abs(instance.root_time(500) - 1) < 1e-9
assert abs(instance.root_time(4000) - 1.875) < 1e-9
assert abs(instance.local_time(1.5) - 2500) < 1e-9
looping = copy.deepcopy(root.payload())
looping['exports'][int(sub['ObjectPath'].rsplit('.', 1)[-1])]['Properties']['Parameters']['bCanLoop'] = True
loop_graph = Graph(lambda path: child.payload() if 'Child' in path else looping, '/Game/Root')
assert len(loop_graph.instances) == 6 and abs(loop_graph.instances[-1].clip[1] - 5) < 1e-9
cyclic = copy.deepcopy(root.payload())
cyclic['exports'][int(sub['ObjectPath'].rsplit('.', 1)[-1])]['Properties']['SubSequence'] = {'ObjectPath': '/Game/Root.Root'}
cycle_graph = Graph(lambda _path: cyclic, '/Game/Root')
assert len(cycle_graph.instances) == 1 and any('Cyclic' in warning for warning in cycle_graph.warnings)
assert abs(float(rate({'Numerator': 30000, 'Denominator': 1001}, 30)) - 30000/1001) < 1e-10
assert Channel(curve(0, 10, 2, 12)).sample(5) == 7
assert Channel({'Times': [0, 0], 'Values': [False, True]}).sample(0) == 1
assert bounds({'SectionRange': {'Value': {'LowerBound': {'Type': 'Exclusive', 'Value': 2}, 'UpperBound': {'Type': 'Inclusive', 'Value': 4}}}}, (0, 10)) == (3, 5)

bpy.context.scene.render.fps = 24
runner = Importer(bpy.context, Mounted(), '/Game/Root', start_frame=11)
with _active_collection(bpy.context, runner.collection):
    report = runner.run()
print('FIXTURE_REPORT', report, flush=True)
assert report['resolvedBindings'] == 2 and report['animationStrips'] == 2 and report['cameraCuts'] == 3
assert report['unsupportedTracks'] == 1 and not report['unresolvedBindings']
camera = next(obj for obj in runner.collection.all_objects if obj.type == 'CAMERA')
rig = next(obj for obj in runner.collection.all_objects if obj.type == 'ARMATURE')
bpy.context.scene.frame_set(47)  # 1.5 seconds after the requested start.
bpy.context.view_layer.update()
assert abs(camera.matrix_world.translation.x - 1.25) < 1e-4, camera.matrix_world
assert abs(camera.data.lens - 45) < 1e-4, camera.data.lens
assert (camera.matrix_world.to_3x3() @ __import__('mathutils').Vector((0, 0, -1))).x > 0.99
bpy.context.scene.frame_set(83)  # 3 seconds: two half-weight absolute clips.
bpy.context.view_layer.update()
assert abs(rig.pose.bones['Root'].head.x - 2) < 1e-4, rig.pose.bones['Root'].head
assert rig.animation_data.action is None
bpy.context.scene.frame_set(11+24*7)
bpy.context.view_layer.update()
assert rig.hide_render
assert bpy.data.texts.get(runner.collection['ue_import_report'])
runner.rollback()
assert not any(col.get('ue_sequence_path') for col in bpy.data.collections)
assert not any(action.get('ue_sequence_path') for action in bpy.data.actions)

# Occupied animation targets are skipped unless explicitly authorized; a
# fatal import after replacement restores the user's original data.
existing = bpy.data.objects.new('Existing', None)
bpy.context.scene.collection.objects.link(existing)
existing.location = (9, 8, 7)
existing.rotation_mode = 'XYZ'
old_action = bpy.data.actions.new('User Action')
data = existing.animation_data_create()
data.action = old_action
old_track = data.nla_tracks.new()
old_track.name = 'User Track'
probe = Importer(bpy.context, Mounted(), '/Game/Root', start_frame=11)
assert not probe.available(existing)
assert data.action == old_action and not old_track.mute
probe.rollback()
probe = Importer(bpy.context, Mounted(), '/Game/Root', start_frame=11, replace_existing=True)
assert probe.available(existing)
assert data.action is None and old_track.mute
probe.add_action(existing, {'location': [(0, 0, 0), (1, 0, 0)]}, [11, 203])
existing.rotation_mode = 'QUATERNION'
probe.rollback()
assert data.action == old_action and not old_track.mute and not old_action.use_fake_user
assert existing.rotation_mode == 'XYZ' and tuple(existing.location) == (9, 8, 7)

# Moving clips expose time-mapping errors that constant-pose blend fixtures
# cannot: parent speed, trim, first-loop offset, seams and reverse playback.
moving_root = Builder('/Game/MovingRoot')
moving_child = Builder('/Game/MovingChild', ticks=2000, end=4000)
moving_section = moving_child.add('MovieSceneSkeletalAnimationSection', Params={
    'Animation': {'ObjectPath': '/Game/Moving.Moving'}, 'PlayRate': 1.5,
    'StartFrameOffset': {'Value': 500}, 'EndFrameOffset': {'Value': 500},
    'FirstLoopStartFrameOffset': {'Value': 200}}, SectionRange=span(0, 4000))
moving_track = moving_child.add('MovieSceneSkeletalAnimationTrack', Sections=[moving_section])
moving_child.spawn('RI', 'MovingRobot', '/Game/Templates.robot', [moving_track])
moving_sub = moving_root.add('MovieSceneSubSection', SubSequence={'ObjectPath': '/Game/MovingChild.MovingChild'},
    Parameters={'StartFrameOffset': {'Value': 500}, 'TimeScale': 2}, SectionRange=span(1000, 5000))
moving_root.exports[1]['Properties']['MasterTracks'].append(moving_root.add('MovieSceneSubTrack', Sections=[moving_sub]))


class MovingMounted(Mounted):
    def request(self, request):
        if request['action'] == 'generic_sequence':
            return {'sequence': moving_child.payload() if 'MovingChild' in request['assetPath'] else moving_root.payload()}
        return super().request(request)

    def animation_asset(self, path):
        animation = super().animation_asset(path)
        animation['numFrames'], animation['framesPerSecond'] = 3, 2
        animation['tracks'][0]['translations'] = [[0, 0, 0], [50, 0, 0], [100, 0, 0]]
        animation['tracks'][0]['rotations'] = [[0, 0, 0, 1]] * 3
        animation['tracks'][0]['scales'] = [[1, 1, 1]] * 3
        return animation


for reverse in (False, True):
    moving_child.exports[int(moving_section['ObjectPath'].rsplit('.', 1)[-1])]['Properties']['Params']['bReverse'] = reverse
    probe = Importer(bpy.context, MovingMounted(), '/Game/MovingRoot', start_frame=11)
    with _active_collection(bpy.context, probe.collection):
        result = probe.run()
    assert result['animationStrips'] == 1
    rig = next(obj for obj in probe.collection.all_objects if obj.type == 'ARMATURE')
    bone_anchor = probe.socket_target(rig, 'Root')
    socket_anchor = probe.socket_target(rig, 'HandSocket')
    assert bone_anchor is not None and socket_anchor is not None
    prop = bpy.data.objects.new('Socket Prop', None)
    probe.collection.objects.link(prop)
    prop.location.z = 0.4
    attachment = {'Name': 'Socket attachment', 'Properties': {
        'ConstraintBindingID': {'Guid': 'RI'}, 'AttachSocketName': 'HandSocket'}}
    probe.attach_specs.append((prop, probe.graph.instances[1], attachment, 1.0, 1.75))
    probe.import_attachments()
    assert probe.stats['attachments'] == 1
    for seconds in (1.1, 1.5):
        frame = 11 + seconds * 24
        bpy.context.scene.frame_set(int(frame), subframe=frame % 1)
        bpy.context.view_layer.update()
        phase = (0.1 + (seconds-0.875) * 3) % 0.5
        expected = 0.75-phase if reverse else 0.25+phase
        assert abs(rig.pose.bones['Root'].head.x - expected) < 2e-4, (seconds, reverse, rig.pose.bones['Root'].head, expected)
        assert (bone_anchor.matrix_world.translation - __import__('mathutils').Vector((expected, 0, 0))).length < 2e-4, bone_anchor.matrix_world
        assert (socket_anchor.matrix_world.translation - __import__('mathutils').Vector((expected+0.1, -0.2, 0.3))).length < 2e-4, socket_anchor.matrix_world
        assert (prop.matrix_world.translation - __import__('mathutils').Vector((expected+0.1, -0.2, 0.7))).length < 2e-4, prop.matrix_world
    bpy.context.scene.frame_set(59)  # Attachment ends after 1.75 seconds.
    assert abs(prop.matrix_world.translation.z-0.4) < 2e-4, prop.matrix_world
    probe.rollback()

# An explicitly bound camera must not animate another object's shared data.
camera_data = bpy.data.cameras.new('Shared Lens')
bound_camera = bpy.data.objects.new('Bound Camera', camera_data)
other_camera = bpy.data.objects.new('Other Camera', camera_data)
for obj in (bound_camera, other_camera):
    bpy.context.scene.collection.objects.link(obj)
probe = Importer(bpy.context, Mounted(), '/Game/Root', start_frame=11, overrides={'CA': bound_camera})
with _active_collection(bpy.context, probe.collection):
    result = probe.run()
assert bound_camera.data != other_camera.data
bpy.context.scene.frame_set(47)
assert abs(bound_camera.data.lens-45) < 1e-4 and abs(other_camera.data.lens-50) < 1e-4
probe.rollback()
assert bound_camera.data == camera_data == other_camera.data

# Reuse an exact map binding only from this source, and never guess when
# duplicated imports leave two otherwise identical candidate actor roots.
actor_path = '/Game/Map.Map:PersistentLevel.Actor'
map_actor = bpy.data.objects.new('Map Actor', None)
foreign_actor = bpy.data.objects.new('Other Game Actor', None)
for obj, source in ((map_actor, Mounted.cache_namespace), (foreign_actor, 'other-game')):
    bpy.context.scene.collection.objects.link(obj)
    obj['ue_actor_path'], obj['ue_source_id'] = actor_path, source
probe = Importer(bpy.context, Mounted(), '/Game/Root')
assert probe.resolver.existing(actor_path) == map_actor
probe.rollback()
foreign_actor['ue_source_id'] = Mounted.cache_namespace
probe = Importer(bpy.context, Mounted(), '/Game/Root')
assert probe.resolver.existing(actor_path) is None
probe.rollback()
print('GENERIC_SEQUENCE_FIXTURE_OK: nested timing, camera axes/cuts/shared data, weighted NLA clips, reverse/loops, socket attachments, visibility, rollback')
