"""Real-game generic animation smoke test; all paths/keys stay in ignored config.

blender --background --factory-startup --python-exit-code 1 --python <this> --
    --config .local/generic-test-games.json --game <entry> --mesh <package>
    --clip <package> [--clip <another>] [--save-blend <ignored-output>]
"""

import argparse
import json
import math
from pathlib import Path
import sys

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--game', required=True)
    parser.add_argument('--mesh', required=True)
    parser.add_argument('--clip', required=True, action='append')
    parser.add_argument('--save-blend')
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    config = json.loads(Path(args.config).read_text())[args.game]
    bpy.ops.preferences.addon_enable(module='addon')
    import addon
    from addon.formats.unreal_mesh import animations
    from addon.ui.preferences import ensure_generic_unreal_profiles
    prefs = bpy.context.preferences.addons['addon'].preferences
    profile = ensure_generic_unreal_profiles(prefs).add()
    profile.profile_id = 'generic_animation_smoke'
    profile.name = 'Animation Smoke Test'
    profile.game_path = config['root']
    profile.game_version = config['version']
    profile.usmap_path = config.get('usmap', '')
    profile.aes_key = config.get('key', '')
    prefs.oodle_dll = config.get('oodle') or str(ROOT / '.local/oodle/oo2core_7_win64.dll')
    result = bpy.ops.import_scene.sqex_generic_unreal_mesh(cue4parse_profile=profile.profile_id,
        mesh_kind='SKELETAL', virtual_path=args.mesh, scale_factor=0.01)
    assert result == {'FINISHED'}, result
    armature = next(obj for obj in bpy.context.scene.objects if obj.type == 'ARMATURE')
    mesh = next(obj for obj in bpy.context.scene.objects if obj.type == 'MESH' and obj.parent == armature)
    bpy.context.view_layer.objects.active = armature
    armature.select_set(True)
    assert math.isclose(armature['ue_import_scale'], 0.01, rel_tol=1e-6)
    assert armature.data['ue_profile_id'] == profile.profile_id
    result = bpy.ops.wm.sqex_index_generic_unreal_animation(cue4parse_profile=profile.profile_id)
    assert result == {'FINISHED'}, result
    index = next(iter(animations._INDEX.values()))
    compatible = index['paths']
    assert len(compatible) > 0 and all(clip in compatible for clip in args.clip), args.clip
    report = {'game': args.game, 'mesh': args.mesh, 'bones': len(armature.data.bones),
              'compatibleClips': len(compatible), 'indexWarnings': index.get('warnings'), 'clips': []}
    bpy.context.scene.render.fps = 24
    for clip in args.clip:
        result = bpy.ops.object.sqex_import_generic_unreal_animation(cue4parse_profile=profile.profile_id,
            virtual_path=clip, start_frame=11, use_fake_user=True)
        assert result == {'FINISHED'}, result
        action = armature.animation_data.action
        assert action and action['ue_animation_path'] == clip and action.use_fake_user
        samples = []
        for frame in (11, (11 + action.frame_end) / 2, action.frame_end):
            bpy.context.scene.frame_set(int(frame), subframe=frame % 1)
            bpy.context.view_layer.update()
            heads = [tuple(bone.head) for bone in armature.pose.bones]
            assert all(math.isfinite(value) for xyz in heads for value in xyz)
            depsgraph = bpy.context.evaluated_depsgraph_get()
            evaluated = mesh.evaluated_get(depsgraph)
            geometry = evaluated.to_mesh()
            assert len(geometry.vertices) == len(mesh.data.vertices)
            extent = max(vertex.co.length for vertex in geometry.vertices)
            evaluated.to_mesh_clear()
            assert math.isfinite(extent) and extent < 1000, extent
            samples.append(heads)
        motion = max((sum((a-b)**2 for a,b in zip(first, second)))**0.5
                     for first, second in zip(samples[0], samples[1]))
        assert motion > 1e-5, motion
        item = {'path': clip, 'fps': action['ue_source_fps'], 'duration': action['ue_source_duration'],
                'frameEnd': action.frame_end, 'midpointBoneMotion': motion, 'additiveBaked': action['ue_additive_baked']}
        report['clips'].append(item)
        print('GENERIC_ANIMATION_CLIP_OK', json.dumps(item), flush=True)
    (ROOT / f'.local/{args.game}-animation-report.json').write_text(json.dumps(report, indent=2))
    if args.save_blend:
        bpy.ops.wm.save_as_mainfile(filepath=str(Path(args.save_blend).resolve()))
    addon.unregister()
    print('GENERIC_ANIMATION_SMOKE_OK', json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
