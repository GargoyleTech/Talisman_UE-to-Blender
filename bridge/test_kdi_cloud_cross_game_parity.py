"""Compare Cloud's neutral femoris KDI pose between Remake and Rebirth.

Usage:
    blender --background --factory-startup --python test_kdi_cloud_cross_game_parity.py -- \\
        REPOSITORY_ROOT REMAKE_ROOT REMAKE_USMAP REBIRTH_ROOT REBIRTH_OODLE REBIRTH_USMAP
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Quaternion


REMAKE_MESH = (
    "End/Content/GameContents/Character/Player/PC0000_00_Cloud_Standard/"
    "Model/PC0000_00.uasset"
)
REMAKE_KDI = (
    "End/Content/GameContents/Character/Player/PC0000_00_Cloud_Standard/"
    "Model/PC0000_00_KDI.uasset"
)
REBIRTH_SKELETON = (
    "End/Content/Character/Player/PC0000_00_Cloud_Standard/"
    "Model/PC0000_00_Skeleton.uasset"
)
REBIRTH_KDI = (
    "End/Content/Character/Player/PC0000_00_Cloud_Standard/"
    "Model/PC0000_00_KDI.uasset"
)
TEST_BONES = ("L_FemorisB_Spo", "L_StdFemorisB_Spo")


def active_armature_after(before: set[str]):
    created = [
        obj for obj in bpy.context.scene.objects
        if obj.type == "ARMATURE" and obj.name not in before
    ]
    assert len(created) == 1, [obj.name for obj in created]
    armature = created[0]
    bpy.ops.object.select_all(action="DESELECT")
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature
    return armature


def quaternions(armature) -> dict[str, list[float]]:
    bpy.context.view_layer.update()
    return {
        name: list(armature.pose.bones[name].rotation_quaternion)
        for name in TEST_BONES
    }


def sampled_poses(armature) -> dict[str, dict[str, list[float]]]:
    source = armature.pose.bones["L_UpperLeg_a"]
    source.rotation_mode = "QUATERNION"
    samples = {"neutral": quaternions(armature)}
    for label, axis in (
        ("localX20", (1.0, 0.0, 0.0)),
        ("localY20", (0.0, 1.0, 0.0)),
        ("localZ20", (0.0, 0.0, 1.0)),
    ):
        source.rotation_quaternion = Quaternion(axis, math.radians(20.0))
        bpy.context.view_layer.update()
        samples[label] = quaternions(armature)
    source.rotation_quaternion = Quaternion()
    bpy.context.view_layer.update()
    return samples


def quaternion_angle(a: list[float], b: list[float]) -> float:
    dot = abs(sum(x * y for x, y in zip(a, b)))
    return 2.0 * math.acos(max(-1.0, min(1.0, dot)))


def main() -> None:
    args = sys.argv[sys.argv.index("--") + 1:]
    if len(args) != 6:
        raise SystemExit(
            "Expected REPOSITORY_ROOT REMAKE_ROOT REMAKE_USMAP "
            "REBIRTH_ROOT REBIRTH_OODLE REBIRTH_USMAP"
        )
    repository, remake_root, remake_usmap, rebirth_root, rebirth_oodle, rebirth_usmap = args
    sys.path.insert(0, str(Path(repository).resolve()))

    assert bpy.ops.preferences.addon_enable(module="addon") == {"FINISHED"}
    bpy.context.preferences.filepaths.use_scripts_auto_execute = True
    preferences = bpy.context.preferences.addons["addon"].preferences
    preferences.remake_install_root = remake_root
    preferences.oodle_dll = ""
    preferences.remake_usmap_path = remake_usmap
    preferences.rebirth_install_root = rebirth_root
    preferences.oodle_dll = rebirth_oodle
    preferences.rebirth_usmap_path = rebirth_usmap

    before = {obj.name for obj in bpy.context.scene.objects}
    assert bpy.ops.import_scene.ff7r_remake_skeletal_mesh_game_packages(
        "EXEC_DEFAULT",
        virtual_path=REMAKE_MESH,
        build_skeleton=True,
        bind_active_armature=False,
    ) == {"FINISHED"}
    remake = active_armature_after(before)
    assert bpy.ops.import_scene.ff7r_remake_kdi_game_packages(
        "EXEC_DEFAULT", virtual_path=REMAKE_KDI
    ) == {"FINISHED"}
    remake_samples = sampled_poses(remake)

    before = {obj.name for obj in bpy.context.scene.objects}
    assert bpy.ops.import_scene.ff7r_rebirth_skeleton_game_packages(
        "EXEC_DEFAULT",
        virtual_path=REBIRTH_SKELETON,
        armature_name="Rebirth_Cloud",
        import_kdi=False,
        create_variant_bone_collections=False,
    ) == {"FINISHED"}
    rebirth = active_armature_after(before)
    assert bpy.ops.import_scene.ff7r_rebirth_kdi_game_packages(
        "EXEC_DEFAULT", virtual_path=REBIRTH_KDI
    ) == {"FINISHED"}
    rebirth_samples = sampled_poses(rebirth)

    angular_errors = {
        sample: {
            name: quaternion_angle(
                remake_samples[sample][name], rebirth_samples[sample][name]
            )
            for name in TEST_BONES
        }
        for sample in remake_samples
    }
    summary = {
        "remake": remake_samples,
        "rebirth": rebirth_samples,
        "angularErrorsRadians": angular_errors,
    }
    # The two shipped KDI records and rest transforms for these bones are
    # equivalent. Their generated neutral pose should therefore agree to well
    # below a hundredth of a degree.
    assert max(
        error for sample in angular_errors.values() for error in sample.values()
    ) < math.radians(0.01), summary
    print("KDI_CLOUD_CROSS_GAME_PARITY=" + json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
