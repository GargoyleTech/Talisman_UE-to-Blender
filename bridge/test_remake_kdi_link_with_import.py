"""Smoke-test Remake's keyed ConnectLinkWith adapter with Aerith's Guard Rod.

Usage:
    blender --background --factory-startup --python test_remake_kdi_link_with_import.py -- \\
        REPOSITORY_ROOT GAME_ROOT REMAKE_USMAP
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy


MESH = "End/Content/GameContents/Character/Weapon/WE0003_00_Aerith_GuardRod/Model/WE0003_00.uasset"
KDI = "End/Content/GameContents/Character/Weapon/WE0003_00_Aerith_GuardRod/Model/WE0003_00_KDI.uasset"


def main() -> None:
    args = sys.argv[sys.argv.index("--") + 1:]
    if len(args) != 3:
        raise SystemExit(
            "Usage: blender --background --factory-startup --python "
            "test_remake_kdi_link_with_import.py -- REPOSITORY_ROOT GAME_ROOT REMAKE_USMAP"
        )
    repository_root, game_root, usmap_path = args
    sys.path.insert(0, str(Path(repository_root).resolve()))

    result = bpy.ops.preferences.addon_enable(module="addon")
    assert result == {"FINISHED"}, result
    bpy.context.preferences.filepaths.use_scripts_auto_execute = True
    preferences = bpy.context.preferences.addons["addon"].preferences
    preferences.remake_install_root = game_root
    preferences.remake_oodle_dll = ""
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
    drivers = armature.animation_data.drivers if armature.animation_data else []
    expressions = [curve.driver.expression for curve in drivers]
    summary = {
        "linkWithEffectorCount": sum(
            node["operator_type"] == "EffectorLinkWith" for node in graph["nodes"]
        ),
        "scalarDriverCount": sum(
            expression.startswith("kdi_scalar(") for expression in expressions
        ),
        "invalidDriverCount": sum(not curve.is_valid for curve in drivers),
    }
    assert summary["linkWithEffectorCount"] > 0, summary
    assert summary["scalarDriverCount"] > 0, summary
    assert summary["invalidDriverCount"] == 0, summary
    print("REMAKE_KDI_LINK_WITH_IMPORT_RESULT=" + json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
