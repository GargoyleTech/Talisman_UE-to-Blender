"""Verify a package SkeletalMesh import preserves its authored Bonamik BNM.

Usage:

```
blender --background --python bridge/test_rebirth_bnm_import.py -- \
  REPOSITORY GAME_ROOT OODLE_DLL USMAP
```
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy


MESH = (
    "End/Content/Character/Player/PC0000_00_Cloud_Standard/"
    "Model/PC0000_00.uasset"
)
BNM = (
    "End/Content/Character/Player/PC0000_00_Cloud_Standard/"
    "Model/PC0000_00_BNM.uasset"
)


def main() -> None:
    repository, game_root, oodle_dll, usmap_path = (
        sys.argv[sys.argv.index("--") + 1:]
    )
    sys.path.insert(0, str(Path(repository).resolve()))
    assert bpy.ops.preferences.addon_enable(module="addon") == {"FINISHED"}
    preferences = bpy.context.preferences.addons["addon"].preferences
    preferences.rebirth_install_root = game_root
    preferences.oodle_dll = oodle_dll
    preferences.rebirth_usmap_path = usmap_path

    result = bpy.ops.import_scene.ff7r_rebirth_skeletal_mesh_game_packages(
        "EXEC_DEFAULT",
        virtual_path=MESH,
        build_skeleton=True,
        bind_active_armature=False,
        import_kdi=False,
        attachment_sockets="NONE",
        create_limbal_bone=False,
        create_variant_bone_collections=False,
    )
    assert result == {"FINISHED"}, result

    from addon.formats.bnm import storage

    armature = next(
        (
            obj for obj in bpy.data.objects
            if obj.type == "ARMATURE" and storage.BNM_TEXTS_PROPERTY in obj
        ),
        None,
    )
    assert armature is not None
    source_records = json.loads(armature[storage.BNM_TEXTS_PROPERTY])
    assert [record["path"] for record in source_records] == [BNM], source_records
    assets = storage.stored_bnm_assets(armature)
    assert len(assets) == 1
    asset = assets[0]
    assert asset.name == "PC0000_00_BNM"
    assert len(asset.bodies) == 231
    first_bone = asset.bodies[0].skeleton_bone
    assert first_bone
    assert asset.physics_for_bone(first_bone).bodies
    print(
        "REBIRTH_BNM_IMPORT_OK=" + json.dumps(
            {
                "asset": asset.name,
                "bodies": len(asset.bodies),
                "anchor": first_bone,
                "textBlocks": [record["text"] for record in source_records],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
