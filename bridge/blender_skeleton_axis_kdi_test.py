"""Compare Cloud/Tifa KDI deformation across source and Blender bone frames.

Uses the cached dist/mouth_PC000*_00.json fixtures, like the mouth/IK tests.
"""

import json
from pathlib import Path
import sys
import tempfile

import bpy
from mathutils import Matrix, Quaternion, Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import addon
addon.register()
from addon.core.blender import skeletons as skel
from addon.formats.kdi import drivers as kdi
from addon.games.rebirth.importers.animations import DISPLAY_CORRECTION


for character in ("PC0000_00", "PC0002_00"):
    fixture = json.loads((ROOT / "dist" / f"mouth_{character}.json").read_text())
    snapshots = {}
    # Evaluate each rig before building the next: KDI's existing runtime IDs
    # are derived from the source audit, so two copies share IDs in memory.
    for preserve in (False, True):
        rig = skel.build_armature_from_bones(
            bpy.context, character, skel._bones_from_gargoyle(fixture["skeleton"]),
            preserve_ue_axis_order=preserve)
        profile = (kdi.COORDINATE_PROFILE_SOURCE_AXES if preserve else
                   kdi.COORDINATE_PROFILE_PACKAGE_SKELETON_ROLL_90)
        order = kdi.coordinate_profile_axis_order(profile)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "kdi.json"
            path.write_text(json.dumps(fixture["kdis"]))
            assert bpy.ops.import_scene.sqex_kinedriver_json(
                filepath=str(path), translation_axis_order=order, scale_axis_order=order,
                coordinate_profile=profile) == {"FINISHED"}
        for angle in (0, 0.4, -0.7):
            rotation = Quaternion(Vector((0.2, 0.8, 0.3)).normalized(), angle).to_matrix().to_4x4()
            correction = Matrix.Identity(4) if preserve else DISPLAY_CORRECTION
            for name in ("L_UpperArm_a", "R_Thigh_a", "L_Forearm_a"):
                bone = rig.pose.bones.get(name)
                if bone:
                    bone.matrix_basis = correction.inverted() @ rotation @ correction
            rig.update_tag()
            bpy.context.view_layer.update()
            assert not any(not driver.is_valid for driver in rig.animation_data.drivers)
            snapshots[preserve, angle] = {
                bone.name: rig.pose.bones[bone.name].matrix @ bone.matrix_local.inverted()
                for bone in rig.data.bones}
        bpy.data.objects.remove(rig, do_unlink=True)
    for angle in (0, 0.4, -0.7):
        errors = []
        for name, actual in snapshots[True, angle].items():
            expected = snapshots[False, angle][name]
            error = max(abs(actual[row][col] - expected[row][col])
                        for row in range(4) for col in range(4))
            errors.append((error, name))
        worst = max(errors)
        assert worst[0] < 0.001, (character, angle, worst)
        print("KDI_AXIS_PARITY", character, angle, worst, flush=True)

addon.unregister()
print("SKELETON_AXIS_KDI_OK: Cloud/Tifa neutral and posed deformation in both frames")
