"""Verify the mouth checkbox on real package imports.

Usage: blender --background --factory-startup --enable-autoexec
--python-exit-code 1 --python blender_mouth_import_test.py -- GAME_ROOT OODLE USMAP
"""

import importlib.util
import json
from pathlib import Path
import sys

import bpy


root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "talisman", root / "addon/__init__.py",
    submodule_search_locations=[str(root / "addon")],
)
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)
bpy.ops.preferences.addon_enable(module=spec.name)
from talisman.games.rebirth.importers import packages
from talisman.core.blender import mouth_rig

args = sys.argv[sys.argv.index("--") + 1:]
game_root, oodle, usmap = args[:3]
prefs = bpy.context.preferences.addons[spec.name].preferences
prefs.rebirth_install_root = game_root
prefs.oodle_dll = oodle
prefs.rebirth_usmap_path = usmap

with packages.PackageAssetSession(game_root, oodle, usmap) as session:
    meshes = [session.skeletal_mesh(
        f"End/Content/Character/Player/{char}_{name}_Standard/Model/{char}.uasset"
    ) for char, name in (("PC0000_00", "Cloud"), ("PC0002_00", "Tifa"))]
packages._VIRTUAL_SKELETONS[:] = [m["skeletonPath"] for m in meshes]
packages._VIRTUAL_KDIS[:] = [p for m in meshes for p in m["kdiPaths"]]

for mesh in meshes:
    for enabled in (False, True):
        options = dict(
            virtual_path=mesh["skeletonPath"],
            create_variant_bone_collections=False,
            import_mesh_referenced_bones_only=True,
            referenced_bone_names_json=json.dumps(mesh["boneNames"]),
            import_kdi=True, attachment_sockets="NONE",
        )
        if enabled:
            options["generate_mouth_controls"] = True
        result = bpy.ops.import_scene.ff7r_rebirth_skeleton_game_packages(**options)
        assert result == {"FINISHED"}
        arm = bpy.context.object
        assert (mouth_rig.CONTROL in arm.data.bones) == enabled
        assert bool(arm.get(mouth_rig.RIG_PROPERTY)) == enabled
        if enabled:
            assert len(json.loads(arm[mouth_rig.RIG_PROPERTY])["constraints"]) == 25
        print("MOUTH_IMPORT_PASS", mesh["name"], enabled, len(arm.data.bones), flush=True)
        bpy.data.objects.remove(arm, do_unlink=True)
print("MOUTH_IMPORT_TESTS_PASSED", flush=True)
