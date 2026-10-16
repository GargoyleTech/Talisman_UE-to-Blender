"""Smoke-test a package skeleton reduced to mesh-referenced bones and ancestors."""

import bpy


SKELETON = "End/Content/Character/Player/PC0000_00_Cloud_Standard/Model/PC0000_00_Skeleton.uasset"

if "talisman" not in bpy.context.preferences.addons:
    bpy.ops.preferences.addon_enable(module="talisman")
prefs = bpy.context.preferences.addons["talisman"].preferences
prefs.rebirth_install_root = r"G:\SteamLibrary\steamapps\common\FINAL FANTASY VII REBIRTH"
prefs.oodle_dll = r"G:\Games\Final Fantasy VII - Remake Intergrade\Engine\Binaries\ThirdParty\Oodle\Win64\oo2core_7_win64.dll"
prefs.rebirth_usmap_path = r"C:\Users\Ghouls\Downloads\Rebirth_v05.usmap"

from talisman import game_packages

# The SkeletalMesh importers now hand their selected mesh's own ReferenceSkeleton
# straight to the reducer.  Verify the shared reducer retains only that bone and
# its ancestor chain, and drops sockets whose parent no longer remains.
fixture = {
    "bones": [
        {"name": "Root", "parentIndex": -1},
        {"name": "Spine", "parentIndex": 0},
        {"name": "Hand", "parentIndex": 1},
        {"name": "Unused", "parentIndex": 0},
    ],
    "sockets": [
        {"name": "HandSocket", "boneName": "Hand"},
        {"name": "UnusedSocket", "boneName": "Unused"},
    ],
}
reduced, referenced_count, retained_count = (
    game_packages._restrict_skeleton_to_referenced_bones(fixture, {"Hand"})
)
if (
    referenced_count != 1
    or retained_count != 3
    or [bone["name"] for bone in reduced["bones"]] != ["Root", "Spine", "Hand"]
    or [socket["name"] for socket in reduced["sockets"]] != ["HandSocket"]
):
    raise SystemExit("Selected SkeletalMesh ReferenceSkeleton reduction failed.")

result = bpy.ops.import_scene.ff7r_rebirth_skeleton_game_packages(
    "EXEC_DEFAULT",
    virtual_path=SKELETON,
    armature_name="Cloud_Mesh_Referenced",
    import_kdi=False,
    create_variant_bone_collections=True,
    import_mesh_referenced_bones_only=True,
)
armature_obj = bpy.data.objects.get("Cloud_Mesh_Referenced")
bones = armature_obj.data.bones if armature_obj else ()
bone_names = {bone.name for bone in bones}
missing_parents = [
    bone.name for bone in bones
    if bone.parent is not None and bone.parent.name not in bone_names
]
print("MESH_REFERENCED_RESULT", result)
print("MESH_REFERENCED_BONES", len(bones), "MISSING_PARENTS", missing_parents)
if not armature_obj or len(bones) != 557 or missing_parents:
    raise SystemExit("Reduced mesh-referenced skeleton verification failed.")
