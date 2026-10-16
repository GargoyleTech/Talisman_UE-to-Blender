"""Smoke-test the Remake package KDI adapter against Cloud's shipped rig.

Usage:
    blender --background --factory-startup --python test_remake_kdi_import.py -- \
        REPOSITORY_ROOT GAME_ROOT REMAKE_USMAP
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy


MESH = "End/Content/GameContents/Character/Player/PC0000_00_Cloud_Standard/Model/PC0000_00.uasset"
KDI = "End/Content/GameContents/Character/Player/PC0000_00_Cloud_Standard/Model/PC0000_00_KDI.uasset"


def main() -> None:
    args = sys.argv[sys.argv.index("--") + 1:]
    if len(args) != 3:
        raise SystemExit(
            "Usage: blender --background --factory-startup --python "
            "test_remake_kdi_import.py -- REPOSITORY_ROOT GAME_ROOT REMAKE_USMAP"
        )
    repository_root, game_root, usmap_path = args
    sys.path.insert(0, str(Path(repository_root).resolve()))

    enabled = bpy.ops.preferences.addon_enable(module="addon")
    assert enabled == {"FINISHED"}, enabled
    bpy.context.preferences.filepaths.use_scripts_auto_execute = True
    preferences = bpy.context.preferences.addons["addon"].preferences
    preferences.remake_install_root = game_root
    preferences.oodle_dll = ""
    preferences.remake_usmap_path = usmap_path

    result = bpy.ops.import_scene.ff7r_remake_skeletal_mesh_game_packages(
        "EXEC_DEFAULT",
        virtual_path=MESH,
        build_skeleton=True,
        bind_active_armature=False,
    )
    assert result == {"FINISHED"}, result
    armatures = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
    assert len(armatures) == 1, [obj.name for obj in armatures]
    armature = armatures[0]
    bpy.ops.object.select_all(action="DESELECT")
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature

    result = bpy.ops.import_scene.ff7r_remake_kdi_game_packages(
        "EXEC_DEFAULT", virtual_path=KDI
    )
    assert result == {"FINISHED"}, result

    audits = [
        json.loads(text.as_string())
        for text in bpy.data.texts
        if text.name.startswith("KDI_AUDIT_")
    ]
    assert audits, "No KDI audit report was saved"
    graph = audits[-1]["graph"]
    ownership = json.loads(armature["kdi_scalar_generated_json"])
    drivers = armature.animation_data.drivers if armature.animation_data else []
    expressions = [curve.driver.expression for curve in drivers]
    bpy.context.view_layer.update()
    summary = {
        "boneCount": len(armature.data.bones),
        "legacyConnectionAdapterCount": graph["summary"]["legacy_connection_adapter_count"],
        "driverLinkCount": graph["summary"]["driver_link_count"],
        "driverCount": len(drivers),
        "scalarDriverCount": sum(expression.startswith("kdi_scalar(") for expression in expressions),
        "rotationDriverCount": sum(expression.startswith("kdi_rotation(") for expression in expressions),
        "anchorDriverCount": sum(expression.startswith("kdi_anchor(") for expression in expressions),
        "invalidDriverCount": sum(not curve.is_valid for curve in drivers),
        "coordinateProfile": ownership["coordinate_profile"],
        "translationAxisOrder": ownership["translation_axis_order"],
        "scaleAxisOrder": ownership["scale_axis_order"],
        "femorisQuaternion": list(armature.pose.bones["L_FemorisB_Spo"].rotation_quaternion),
        "standardFemorisQuaternion": list(
            armature.pose.bones["L_StdFemorisB_Spo"].rotation_quaternion
        ),
    }
    # The SkeletalMesh carries its mesh-specific ReferenceSkeleton rather than
    # the 1,350-bone master Skeleton package.  It still contains every bone the
    # matching KDI references, as proven by the successful audit below.
    assert summary["boneCount"] >= 500, summary
    assert summary["legacyConnectionAdapterCount"] == 235, summary
    assert summary["driverLinkCount"] == 235, summary
    assert summary["scalarDriverCount"] > 0, summary
    assert summary["invalidDriverCount"] == 0, summary
    assert summary["coordinateProfile"] == "PACKAGE_SKELETON_ROLL_90", summary
    assert summary["translationAxisOrder"] == "YZX", summary
    assert summary["scaleAxisOrder"] == "YZX", summary
    print("REMAKE_KDI_IMPORT_RESULT=" + json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
