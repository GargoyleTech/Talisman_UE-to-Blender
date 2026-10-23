"""Mesh bind-pose regression; optional real Rebirth GAME_ROOT OODLE_DLL USMAP.

Run with Blender --background --factory-startup --python-exit-code 1 --python.
"""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import addon
from addon.core.blender.skeletons import _bones_from_gargoyle, build_armature_from_bones
from addon.formats.unreal_package.skeleton_data import mesh_bind_skeleton
from addon.games.conventional_mesh import build_package_armature
from addon.games.rebirth.importers.packages import PackageAssetSession, PackageSkeletalMeshResolver



def bone(name, parent, translation=(0, 0, 0)):
    return dict(name=name, parentIndex=parent, translation=translation)


linked = dict(bones=[bone('Root', -1), bone('Helper', 0), bone('Hip', 0, (0, 0, 200))],
              sockets=[dict(name='Attach', boneName='Hip')])
inline = dict(bones=[bone('Root', -1), bone('Hip', 0, (0, 0, 600)), bone('MeshOnly', 1)])
original = deepcopy((linked, inline))
merged = mesh_bind_skeleton(dict(inlineSkeleton=inline), linked)
assert [b['name'] for b in merged['bones']] == ['Root', 'Hip', 'MeshOnly', 'Helper']
assert [b['parentIndex'] for b in merged['bones']] == [-1, 0, 1, 0]
assert merged['bones'][1]['translation'] == (0, 0, 600)
assert merged['sockets'] == linked['sockets']
assert (linked, inline) == original
assert mesh_bind_skeleton({}, linked) is linked
assert mesh_bind_skeleton(dict(inlineSkeleton=inline)) is inline

args = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
if args:
    addon.register()
    asset_path = 'End/Content/Character/NonPlayer/NP0132_01_GiNattak_Mural/Model/NP0132_01.uasset'
    operator = SimpleNamespace(import_mesh_referenced_bones_only=False,
        attachment_sockets='NONE', scale_factor=.01, connect_bones=False,
        setup_naive_ik=False, face_y_forward='UNREAL', preserve_ue_axis_order=False)

    with PackageAssetSession(*args[:3], import_textures=False) as session:
        definition = SimpleNamespace(profile=session.profile, game_name='Rebirth', supported_skeletal_options=set())
        payload = session.skeletal_mesh(asset_path)
        linked = session.skeleton_asset(payload['skeletonPath'])
        mesh_hip = next(b for b in payload['inlineSkeleton']['bones'] if b['name'] == 'C_Hip_a')
        shared_hip = next(b for b in linked['bones'] if b['name'] == 'C_Hip_a')
        assert abs(mesh_hip['translation'][2] / shared_hip['translation'][2] - 3) < 1e-6
        rig, path, source = build_package_armature(bpy.context, operator, definition, session, payload, asset_path)
        expected = Vector((mesh_hip['translation'][0], -mesh_hip['translation'][1], mesh_hip['translation'][2])) * .01
        assert (rig.data.bones['C_Hip_a'].head_local - expected).length < 1e-5
        assert len(rig.data.bones) == len(source['bones']) == 475
        # Verify every mesh bone, not only the hip, against the authored hierarchy.
        reference = build_armature_from_bones(bpy.context, 'MeshReference',
            _bones_from_gargoyle(payload['inlineSkeleton']), connect_bones=False)
        for b in reference.data.bones:
            assert (rig.data.bones[b.name].head_local - b.head_local).length < 2e-5, b.name
        resolver = PackageSkeletalMeshResolver(bpy.context, session, .01, build_materials=False)
        asset = resolver(asset_path)
        assert (asset.armature.bones['C_Hip_a'].head_local - expected).length < 1e-5
        # Two meshes can share a linked Skeleton while retaining different poses.
        base_payload = dict(payload, inlineSkeleton=linked)
        fake = SimpleNamespace(profile=session.profile, skeletal_mesh=lambda *a, **k: base_payload,
                               skeleton_asset=lambda *a: linked)
        resolver.session = fake
        second = resolver(asset_path.replace('NP0132_01.uasset', 'ScaleFixture.uasset'))
        assert second.armature != asset.armature
        assert abs(second.armature.bones['C_Hip_a'].head_local.z * 3 - expected.z) < 1e-5
        assert resolver(asset_path) is asset
        print('GINATTAK_BIND_POSE_OK', len(reference.data.bones), len(rig.data.bones), expected.z, flush=True)
    addon.unregister()
print('MESH_BIND_POSE_OK', flush=True)

