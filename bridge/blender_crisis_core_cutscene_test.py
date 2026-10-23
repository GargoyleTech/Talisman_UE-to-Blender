"""Real-game Crisis Core cutscene regression; paths stay in an ignored config.

Blender --background --factory-startup --python-exit-code 1 --python this_file
-- --config .local/texture-limit-game-tests.json [--sequence PACKAGE]
"""

import argparse
import importlib
import json
import math
from pathlib import Path
import sys

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--sequence", default=(
        "CCFF7R/Content/Fair/Camera/Event/s99_eve99B/LS_s99_eve99B_Master.uasset"))
    parser.add_argument("--save-blend")
    parser.add_argument("--report")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    config = json.loads(Path(args.config).read_text())["crisis_core"]
    bpy.ops.preferences.addon_enable(module="addon")
    import addon
    from addon.games.crisis_core.importers import cutscenes
    prefs = bpy.context.preferences.addons["addon"].preferences
    prefs.crisis_core_install_root = config["root"]
    prefs.crisis_core_usmap_path = config["usmap"]
    prefs.oodle_dll = config.get("oodle", "")
    indexed = cutscenes.refresh_cutscene_index(bpy.context)
    assert args.sequence in indexed, args.sequence
    bpy.context.scene.render.fps = 24
    bpy.context.scene.render.fps_base = 1.001
    result = bpy.ops.import_scene.ff7r_crisis_core_cutscene_game_packages(
        virtual_path=args.sequence, start_frame=11, scale_factor=0.025)
    assert result == {"FINISHED"}, result
    collection = next(col for col in bpy.context.scene.collection.children if col.get("ue_sequence_path"))
    stats = json.loads(bpy.data.texts[collection["ue_import_report"]].as_string())
    assert stats["sequenceInstances"] > 1 and stats["objects"] > 0, stats
    assert stats["cameraCuts"] > 0, stats
    assert not stats["unresolvedBindings"], stats["unresolvedBindings"]
    assert stats["textureFailures"] == stats["materialFailures"] == 0, stats
    if stats["authoredAnimationSections"]:
        assert stats["animationStrips"] > 0, stats
    cameras = [obj for obj in collection.all_objects if obj.type == "CAMERA"]
    rigs = [obj for obj in collection.all_objects if obj.type == "ARMATURE"]
    assert cameras
    for frame in (11, (11 + bpy.context.scene.frame_end) // 2, bpy.context.scene.frame_end):
        bpy.context.scene.frame_set(frame)
        bpy.context.view_layer.update()
        for obj in collection.all_objects:
            assert all(math.isfinite(value) for row in obj.matrix_world for value in row), obj.name
        for rig in rigs:
            assert all(math.isfinite(v) for bone in rig.pose.bones for v in bone.head), rig.name
    meshes = [obj for obj in collection.all_objects if obj.type == "MESH"]
    assert all(mat.get("ff7r_crisis_core_material") for obj in meshes for mat in obj.data.materials if mat)
    stats.update(indexed=len(indexed), cameras=len(cameras), rigs=len(rigs), meshes=len(meshes))
    if args.save_blend:
        bpy.ops.wm.save_as_mainfile(filepath=str(Path(args.save_blend).resolve()))
    if args.report:
        Path(args.report).write_text(json.dumps(stats, indent=2))
    # Reload registration must include the new operator, without duplicates.
    importlib.reload(addon)
    addon.register()
    assert bpy.ops.import_scene.ff7r_crisis_core_cutscene_game_packages.get_rna_type()
    addon.unregister()
    print("CRISIS_CORE_CUTSCENE_OK", json.dumps({
        key: value for key, value in stats.items() if key not in ("warnings", "unresolvedBindings")
    }), flush=True)


if __name__ == "__main__":
    main()
