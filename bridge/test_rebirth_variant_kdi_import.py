"""Verify SkeletalMesh import uses its variant-authored KineDriver reference."""

from __future__ import annotations

import sys
from pathlib import Path

import bpy


MESH = (
    "End/Content/Character/Player/PC0005_03_Yuffie_CostaClothing/"
    "Model/PC0005_03.uasset"
)
EXPECTED_KDI_NAME = "PC0005_03_KDI"


def main() -> None:
    repository, game_root, oodle_dll, usmap_path = (
        sys.argv[sys.argv.index("--") + 1:]
    )
    sys.path.insert(0, str(Path(repository).resolve()))
    assert bpy.ops.preferences.addon_enable(module="addon") == {"FINISHED"}
    bpy.context.preferences.filepaths.use_scripts_auto_execute = True

    preferences = bpy.context.preferences.addons["addon"].preferences
    preferences.rebirth_install_root = game_root
    preferences.oodle_dll = oodle_dll
    preferences.rebirth_usmap_path = usmap_path

    result = bpy.ops.import_scene.ff7r_rebirth_skeletal_mesh_game_packages(
        "EXEC_DEFAULT",
        virtual_path=MESH,
        build_skeleton=True,
        bind_active_armature=False,
        import_kdi=True,
        attachment_sockets="NONE",
        create_limbal_bone=False,
        create_variant_bone_collections=False,
    )
    assert result == {"FINISHED"}, result

    audit_names = [text.name for text in bpy.data.texts if text.name.startswith("KDI_AUDIT_")]
    assert any(EXPECTED_KDI_NAME in name for name in audit_names), audit_names
    assert not any("PC0005_00_KDI" in name for name in audit_names), audit_names
    print("REBIRTH_VARIANT_KDI_OK=" + ",".join(audit_names))


if __name__ == "__main__":
    main()
