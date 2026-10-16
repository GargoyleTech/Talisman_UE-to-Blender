"""Ordinary-Python smoke test for the read-only Bonamik parser.

Run from the repository root with ``python bridge/test_bnm_parser.py``.  It
does not need Blender, a game install, or the package gargoyle.
"""

from __future__ import annotations

import importlib.util
import os
import sys


REPOSITORY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARSER_PATH = os.path.join(REPOSITORY, "addon", "formats", "bnm", "parser.py")
SPEC = importlib.util.spec_from_file_location("ff7r_test_bnm_parser", PARSER_PATH)
assert SPEC is not None and SPEC.loader is not None
bnm = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = bnm
SPEC.loader.exec_module(bnm)


SOURCE = {
    "Type": "SQEX_BonamikAsset",
    "Name": "Test_BNM",
    "Package": "/Game/Test/Test_BNM",
    "Properties": {
        "m_VersionNo": 30713,
        "mSceneManager": {"m_Dt": 1.0 / 30.0},
        "mGroups": [{"m_GroupName": "Hair", "m_IsEnable": True}],
        "mBodies": [
            {
                "mName": "BonamikBody_Root",
                "mParentName": "C_HairRoot_Phy",
                "mGroupName": "Hair",
                "m_IsKinematic": False,
                "m_IsCollision": False,
                "m_Damping": 3.0,
                "m_Mass": 0.7,
            },
            {
                "mName": "BonamikBody_Child",
                "mParentName": "BonamikBody_Root",
                "mGroupName": "Hair",
                "m_IsKinematic": False,
                "m_IsCollision": True,
                "m_Damping": 2.0,
                "m_Mass": 0.5,
            },
        ],
        "mLinks": [{"mA": "BonamikBody_Root", "mB": "BonamikBody_Child"}],
        "mCones": [{"mA": "BonamikBody_Root", "mB": "BonamikBody_Child"}],
        "mKDIs": [{"mA": "BonamikBody_Root", "mB": "BonamikBody_Child"}],
        "mShapes": [{"mShapeId": 4, "mBodies": ["BonamikBody_Child"]}],
        "mCollisionCliques": [{"mShapeIds": [4]}],
    },
}


asset = bnm.parse_bnm(SOURCE)
assert asset.name == "Test_BNM"
assert [body.skeleton_bone for body in asset.bodies] == [
    "C_HairRoot_Phy",
    "C_HairRoot_Phy",
]
physics = asset.physics_for_bone("c_hairroot_phy")
assert [body.name for body in physics.bodies] == [
    "BonamikBody_Root",
    "BonamikBody_Child",
]
assert [values["m_Damping"] for values in physics.body_values] == [3.0, 2.0]
assert len(physics.groups) == len(physics.links) == len(physics.cones) == 1
assert len(physics.kdis) == len(physics.shapes) == len(physics.collision_cliques) == 1
assert bnm.associated_bnm_paths({"bnmPaths": [
    " /End/Content/Test_BNM.uasset ",
    "End\\Content\\Test_BNM.uasset",
    5,
]}) == ("End/Content/Test_BNM.uasset",)

print("BNM_PARSER_OK")
