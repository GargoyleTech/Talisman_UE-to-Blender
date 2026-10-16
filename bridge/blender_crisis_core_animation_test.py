"""Real-game Crisis Core animation regression; installation paths stay local.

Run with Blender --background --factory-startup --python-exit-code 1
--python this_file -- --config .local/texture-limit-game-tests.json
[--scale 0.025] [--preserve-ue-axes] [--save-blend .local/crisis-core-animation.blend]
"""

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Matrix, Quaternion, Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MESH = "CCFF7R/Content/Fair/Character/01_named/zack_s21/Mesh/SK_CH_zack_s21.uasset"
CLIPS = [
    "CCFF7R/Content/Fair/Character/01_named/zack_s21/Animation/General/AS_zack_s21_gnm_walk.uasset",
    "CCFF7R/Content/Fair/Character/01_named/zack_s21/Animation/Battle/AS_zack_s21_btm_idle1.uasset",
]


def source_matrix(translation, rotation, scale, factor):
    x, y, z = translation
    rx, ry, rz, rw = rotation
    return Matrix.LocRotScale(
        Vector((x * factor, -y * factor, z * factor)),
        Quaternion((rw, -rx, ry, -rz)), Vector(scale),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--scale", type=float, default=0.025)
    parser.add_argument("--preserve-ue-axes", action="store_true")
    parser.add_argument("--save-blend")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    config = json.loads(Path(args.config).read_text())["crisis_core"]
    bpy.ops.preferences.addon_enable(module="addon")
    import addon
    from addon.core.blender import skeletons
    from addon.formats.unreal_package import PackageAssetSession, indexing
    from addon.games.crisis_core.importers import animations

    cache_root = ROOT / ".local/shared-runtime-index-cache"
    cache_root.mkdir(parents=True, exist_ok=True)
    indexing._mesh_disk_cache_path = lambda key: cache_root / (
        hashlib.sha256(repr(key).encode()).hexdigest() + ".json"
    )
    preferences = bpy.context.preferences.addons["addon"].preferences
    preferences.crisis_core_install_root = config["root"]
    preferences.crisis_core_usmap_path = config["usmap"]
    preferences.oodle_dll = config.get("oodle", "")
    assert not bpy.ops.object.ff7r_crisis_core_import_animation_game_packages.poll()
    assert bpy.ops.import_scene.ff7r_crisis_core_skeletal_mesh_game_packages(
        virtual_path=MESH, scale_factor=args.scale,
        face_y_forward=skeletons.FACE_FORWARD_BLENDER,
        preserve_ue_axis_order=args.preserve_ue_axes,
    ) == {"FINISHED"}
    mesh = bpy.context.active_object
    armature = mesh.parent
    assert mesh.type == "MESH" and armature.type == "ARMATURE"
    assert math.isclose(armature["ue_import_scale"], args.scale, rel_tol=1e-6)
    bpy.context.view_layer.objects.active = armature
    armature.select_set(True)
    assert bpy.ops.object.ff7r_crisis_core_import_animation_game_packages.poll()
    compatible = animations.refresh_animation_index(bpy.context, armature)
    assert all(clip.casefold() in {p.casefold() for p in compatible} for clip in CLIPS)
    bpy.context.scene.render.fps = 24
    bpy.context.scene.render.fps_base = 1.001
    scene_fps = 24 / 1.001
    report = {"compatibleClips": len(compatible), "bones": len(armature.data.bones),
              "scale": args.scale, "preserveUEAxes": args.preserve_ue_axes, "clips": []}
    with PackageAssetSession(config["root"], config.get("oodle", ""), config["usmap"],
                             profile=animations.PROFILE) as session:
        for clip in CLIPS:
            source = session.animation_asset(clip)
            assert bpy.ops.object.ff7r_crisis_core_import_animation_game_packages(
                virtual_path=clip, start_frame=11,
            ) == {"FINISHED"}
            action = armature.animation_data.action
            assert action["ue_animation_path"] == clip and action.use_fake_user
            assert math.isclose(action["ue_import_scale"], args.scale, rel_tol=1e-6)
            assert math.isclose(action.frame_end, 11 + source["duration"] * scene_fps,
                                rel_tol=1e-5)
            samples = []
            for sample in (0, source["numFrames"] // 2, source["numFrames"] - 1):
                frame = 11 + sample / source["framesPerSecond"] * scene_fps
                bpy.context.scene.frame_set(int(frame), subframe=frame % 1)
                bpy.context.view_layer.update()
                heads = [bone.head.copy() for bone in armature.pose.bones]
                assert all(math.isfinite(value) for head in heads for value in head)
                # Compare source root motion directly, without Final Fantasy VII
                # Remake/Rebirth's special root display correction.
                root = source["referenceSkeleton"]["bones"][0]
                track = next(t for t in source["tracks"] if t["boneName"] == root["name"])
                bind = source_matrix(root["translation"], root["rotation"], root["scale"], args.scale)
                posed = source_matrix(track["translations"][sample], track["rotations"][sample],
                                      track["scales"][sample], args.scale)
                forward = skeletons.Y_FORWARD_ROTATION
                expected = forward @ posed @ bind.inverted_safe() @ forward.inverted_safe() @ armature.data.bones[root["name"]].matrix_local
                actual = armature.pose.bones[root["name"]].matrix
                error = max(abs(a - b) for row_a, row_b in zip(expected, actual)
                            for a, b in zip(row_a, row_b))
                assert error < 2e-3, (clip, sample, error)
                evaluated = mesh.evaluated_get(bpy.context.evaluated_depsgraph_get())
                geometry = evaluated.to_mesh()
                assert len(geometry.vertices) == len(mesh.data.vertices)
                extent = max(vertex.co.length for vertex in geometry.vertices)
                evaluated.to_mesh_clear()
                assert math.isfinite(extent) and extent < 1000
                samples.append(heads)
            motion = max((a - b).length for a, b in zip(samples[0], samples[1]))
            assert motion > 1e-5, (clip, motion)
            before = len(bpy.data.actions)
            wrong_skeleton = copy.deepcopy(source)
            wrong_skeleton["skeletonPath"] = "/Game/Other/Skeleton"
            wrong_skeleton["linkedSkeletonPath"] = "/Game/Other/Skeleton"
            try:
                animations.animation_importer.import_animation_asset(armature, clip, wrong_skeleton)
                raise AssertionError("Unrelated Skeleton accepted")
            except ValueError:
                assert len(bpy.data.actions) == before
            report["clips"].append({"path": clip, "frames": source["numFrames"],
                                    "sourceFPS": source["framesPerSecond"], "boneMotion": motion})
    # The picker can import a batch as retained, separate Actions too.
    from addon.games import package_browser
    package_browser.activate(bpy.context, animations._ANIMATION_BROWSER, compatible)
    animations._ANIMATION_BROWSER["selected"].update(CLIPS)
    before = len(bpy.data.actions)
    assert bpy.ops.object.ff7r_crisis_core_import_animation_game_packages(
        start_frame=17, replace_current_action=False,
    ) == {"FINISHED"}
    assert len(bpy.data.actions) == before + len(CLIPS)
    if args.save_blend:
        bpy.ops.wm.save_as_mainfile(filepath=str(Path(args.save_blend).resolve()))
    print("CRISIS_CORE_ANIMATION_OK", json.dumps(report), flush=True)
    addon.unregister()


if __name__ == "__main__":
    main()
