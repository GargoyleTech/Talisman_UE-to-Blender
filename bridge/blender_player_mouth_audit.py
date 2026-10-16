"""Read-only package audit of player mouth compatibility (excludes Red).

Run in background factory Blender with --enable-autoexec --python-exit-code 1,
then pass GAME_ROOT OODLE USMAP OUTPUT_JSON after --. Builds disposable rigs;
does not edit game files or an existing Blender scene.
"""
import importlib.util
import json
from pathlib import Path
import re
import sys
import tempfile

import bpy

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("talisman", root / "addon/__init__.py",
    submodule_search_locations=[str(root / "addon")])
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)
addon.register()
from talisman.games.rebirth.importers import packages as pkg
from talisman.core.blender import mouth_rig as jaw, lip_rig as lip
from talisman.core.blender.skeletons import build_armature_from_bones, _bones_from_gargoyle
from talisman.formats.kdi.drivers import COORDINATE_PROFILE_PACKAGE_SKELETON_ROLL_90

args = sys.argv[sys.argv.index("--")+1:]
game_args, output = args[:3], Path(args[3])
paths = [p for p in pkg.refresh_skeleton_index(*game_args) if "/Character/Player/" in p
         and not re.search(r"/PC(?:0|7)004_", p)]
kdis = pkg.refresh_kdi_index(*game_args)
results = []

def update(arm):
    arm.update_tag()
    bpy.context.view_layer.update()
    return {b.name: b.matrix.copy() for b in arm.pose.bones}

def matrix_error(a,b):
    return max(abs(a[r][c]-b[r][c]) for r in range(4) for c in range(4))

with pkg.PackageAssetSession(*game_args) as session:
    for path in paths:
        row = {"path": path, "character": path.split("/")[-3], "kdi": []}
        arm = None
        try:
            skeleton = session.skeleton_asset(path)
            row["bone_count"] = len(skeleton["bones"])
            arm = build_armature_from_bones(bpy.context, row["character"], _bones_from_gargoyle(skeleton))
            original = {b.name: (b.parent.name if b.parent else None,
                tuple(v for r in b.matrix_local for v in r)) for b in arm.data.bones}
            row["missing_required"] = [n for n in jaw.REQUIRED if n not in arm.data.bones]
            row["jaw_named_bones"] = [b.name for b in arm.data.bones if "jaw" in b.name.lower()]
            targets, matrix, width = jaw._profile(arm)
            lip_profile = lip._profile(arm)
            row["jaw_targets"] = len(targets)
            row["lip_targets"] = len(lip_profile[1]) if lip_profile else 0
            row["pivot"] = list(matrix.translation)
            row["jaw_width"] = width
            # Compare rest names/parents in every mesh variant sharing this skeleton.
            usage = session.skeleton_bone_usage(path, pkg._character_family_search_path(path))
            row["mesh_count"] = usage.get("parsedMeshCount")
            row["mesh_parse_failures"] = usage.get("failures", [])
            row["mesh_checks"] = []
            for mesh in usage.get("meshes", []):
                names = set(mesh.get("boneNames") or mesh.get("referenceBoneNames") or [])
                row["mesh_checks"].append({
                    "path": mesh.get("assetPath"), "keys": list(mesh),
                    "reference_bone_count": len(names),
                    "missing_jaw_required": [n for n in jaw.REQUIRED if n not in names] if names else None,
                    "missing_lip_targets": sorted(set(lip_profile[1]) - names) if names and lip_profile else None,
                })
            main = pkg._kdi_path_for_skeleton(path)
            layers = ([main] + pkg._secondary_kdi_paths_for_main(main, kdis)) if main in kdis else []
            with tempfile.TemporaryDirectory() as temp:
                for i, kdi_path in enumerate(layers):
                    try:
                        asset = session.kdi_asset(kdi_path)
                        local = Path(temp)/"audit_kdi.json"
                        local.write_text(json.dumps([asset]))
                        result = bpy.ops.import_scene.ff7r_kinedriver_json(filepath=str(local),
                            replace_previous_generated=i == 0, additive=i != 0,
                            translation_axis_order="YZX", scale_axis_order="YZX",
                            coordinate_profile=COORDINATE_PROFILE_PACKAGE_SKELETON_ROLL_90)
                        row["kdi"].append({"path": kdi_path, "result": sorted(result)})
                    except Exception as exc:
                        row["kdi"].append({"path": kdi_path, "error": str(exc)})
            before = update(arm)
            invalid_before = {d.data_path for d in arm.animation_data.drivers if not d.is_valid} if arm.animation_data else set()
            jaw.generate_mouth_rig(bpy.context, arm)
            neutral = update(arm)
            row["neutral_max_error"] = max(matrix_error(before[n], neutral[n]) for n in original)
            arm.pose.bones[jaw.CONTROL].rotation_euler.x = .2
            if lip_profile:
                arm.pose.bones[lip.UPPER[2]].location[0] = width * .02
                arm.pose.bones[lip.LEFT].location[2] = width * .03
            moved = update(arm)
            row["jaw_movement"] = (moved["C_Dteeth"].translation-neutral["C_Dteeth"].translation).length
            invalid_after = {d.data_path for d in arm.animation_data.drivers if not d.is_valid}
            row["new_invalid_drivers"] = sorted(invalid_after-invalid_before)
            row["preexisting_invalid_drivers"] = len(invalid_before)
            jaw.remove_mouth_rig(bpy.context, arm)
            restored = update(arm)
            row["removed_max_error"] = max(matrix_error(before[n],restored[n]) for n in original)
            row["hierarchy_preserved"] = original == {b.name: (b.parent.name if b.parent else None,
                tuple(v for r in b.matrix_local for v in r)) for b in arm.data.bones}
            row["status"] = "PASS" if (row["hierarchy_preserved"] and not row["new_invalid_drivers"]
                and row["neutral_max_error"] < 3e-5 and row["removed_max_error"] < 3e-5
                and row["jaw_movement"] > width*.01) else "REVIEW"
        except Exception as exc:
            row["status"] = "UNSUPPORTED" if isinstance(exc, ValueError) else "ERROR"
            row["reason"] = str(exc)
        finally:
            if arm:
                if arm.mode != "OBJECT":
                    bpy.ops.object.mode_set(mode="OBJECT")
                bpy.data.objects.remove(arm, do_unlink=True)
            results.append(row)
            output.write_text(json.dumps(results, indent=2))
            print("PLAYER_MOUTH_AUDIT", row["character"], row["status"], row.get("reason", ""), flush=True)
print("PLAYER_MOUTH_AUDIT_COMPLETE", len(results), flush=True)
