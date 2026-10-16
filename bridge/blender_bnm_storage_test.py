"""Headless Blender smoke test for persistent, non-simulated BNM data.

Run from the repository root with a Blender executable, for example:

```
blender --background --python bridge/blender_bnm_storage_test.py
```
"""

from __future__ import annotations

import os
import sys

import bpy


REPOSITORY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPOSITORY not in sys.path:
    sys.path.insert(0, REPOSITORY)

bpy.ops.preferences.addon_enable(module="addon")

from addon.formats.bnm import parser, storage


source = {
    "Type": "SQEX_BonamikAsset",
    "Name": "Storage_Test_BNM",
    "Package": "/Game/Test/Storage_Test_BNM",
    "Properties": {
        "mBodies": [{
            "mName": "BonamikBody_0",
            "mParentName": "C_Test_Phy",
            "mGroupName": "default",
            "m_Damping": 1.25,
        }],
    },
}
owner = bpy.data.objects.new("BNM Storage Test", None)
bpy.context.scene.collection.objects.link(owner)
storage.store_bnm_assets(
    owner,
    [("End/Content/Test/Storage_Test_BNM.uasset", parser.parse_bnm(source))],
    source_mesh_path="End/Content/Test/TestMesh.uasset",
)
stored = storage.stored_bnm_assets(owner)
assert len(stored) == 1
assert parser.physics_values_for_bone(stored[0], "C_Test_Phy") == ({"m_Damping": 1.25},)
assert owner.get(storage.BNM_TEXTS_PROPERTY)
assert len(bpy.data.texts) == 1
print("BNM_STORAGE_OK")
