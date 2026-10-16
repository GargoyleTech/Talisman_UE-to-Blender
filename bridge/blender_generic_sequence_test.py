"""Real-game generic cutscene operator smoke test; credentials live in ignored JSON."""

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
    parser.add_argument('--sequence', required=True)
    parser.add_argument('--save-blend')
    parser.add_argument('--report')
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    config = json.loads(Path(args.config).read_text())[args.game]
    bpy.ops.preferences.addon_enable(module='addon')
    from addon.ui.preferences import ensure_generic_unreal_profiles
    prefs = bpy.context.preferences.addons['addon'].preferences
    profile = ensure_generic_unreal_profiles(prefs).add()
    profile.profile_id, profile.name = 'generic_sequence_smoke', 'Generic Cutscene Test'
    profile.game_path, profile.game_version, profile.aes_key = config['root'], config['version'], config.get('key', '')
    profile.usmap_path = config.get('usmap', '')
    prefs.oodle_dll = config.get('oodle') or str(ROOT / '.local/oodle/oo2core_7_win64.dll')
    settings = {'cue4parse_profile': profile.profile_id, 'virtual_path': args.sequence}
    result = bpy.ops.wm.sqex_index_generic_unreal_sequence(cue4parse_profile=profile.profile_id,
                                                        path_filter=args.sequence.rsplit('/', 1)[-1].split('.')[0])
    assert result == {'FINISHED'}, result
    result = bpy.ops.wm.sqex_inspect_generic_sequence_bindings(**settings)
    assert result == {'FINISHED'}, result
    assert len(bpy.context.window_manager.sqex_generic_sequence_bindings)
    before = set(bpy.data.collections)
    result = bpy.ops.import_scene.sqex_generic_unreal_sequence(**settings, start_frame=11)
    assert result == {'FINISHED'}, result
    collection = next(col for col in set(bpy.data.collections)-before if col.get('ue_sequence_path'))
    report = json.loads(bpy.data.texts[collection['ue_import_report']].as_string())
    assert report['objects'] > 0 and report['resolvedBindings'] > 0, report
    cameras = [obj for obj in collection.all_objects if obj.type == 'CAMERA']
    rigs = [obj for obj in collection.all_objects if obj.type == 'ARMATURE']
    meshes = [obj for obj in collection.all_objects if obj.type == 'MESH']
    report.update(game=args.game, sequence=args.sequence, cameras=len(cameras), armatures=len(rigs), meshes=len(meshes))
    for frame in (bpy.context.scene.frame_start, (bpy.context.scene.frame_start+bpy.context.scene.frame_end)//2,
                  bpy.context.scene.frame_end):
        bpy.context.scene.frame_set(frame)
        bpy.context.view_layer.update()
        for obj in collection.all_objects:
            assert all(math.isfinite(value) for row in obj.matrix_world for value in row), obj.name
        for rig in rigs:
            assert all(math.isfinite(value) for bone in rig.pose.bones for value in bone.head), rig.name
    if report['authoredAnimationSections']:
        assert report['animationStrips'] > 0, report
    if cameras:
        assert report['cameraCuts'] > 0, report
    if args.save_blend:
        bpy.ops.wm.save_as_mainfile(filepath=str(Path(args.save_blend).resolve()))
    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2))
    print('GENERIC_SEQUENCE_SMOKE_OK', json.dumps({key: value for key, value in report.items() if key not in ('warnings', 'unresolvedBindings')}), flush=True)


if __name__ == '__main__':
    main()
