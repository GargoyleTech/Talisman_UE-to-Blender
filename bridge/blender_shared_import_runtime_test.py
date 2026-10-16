"""Regression fixtures for shared package workflows; no game content required."""

from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
import copy
import hashlib
import importlib
import json
import sys
import tempfile

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import addon

addon.register()

from addon.core.profiles import GamePaths
from addon.formats import unreal_package
from addon.formats.unreal_package import indexing, mesh_import, resolvers
from addon.games import conventional_animation, package_browser
from addon.games.rebirth.importers import (
    animations as ff7_animation,
    packages as rebirth,
)
from addon.games.remake.importers import static_mesh as remake
from addon.games.crisis_core.importers import static_mesh as crisis_core
from addon.games.kingdom_hearts.importers import static_mesh as kh_shared
from addon.games.kingdom_hearts_iii.importers import static_mesh as kh3
from addon.games.kingdom_hearts_0_2.importers import static_mesh as kh02


BONES = [
    {"name": "Root", "parentIndex": -1, "translation": [0, 0, 0]},
    {"name": "Unused", "parentIndex": 0, "translation": [0, 10, 0]},
    {"name": "Child", "parentIndex": 0, "translation": [10, 0, 0]},
]
SKELETON = {
    "name": "SharedSkeleton",
    "bones": BONES,
    "sockets": [
        {"name": "Attach", "boneName": "Child", "translation": [1, 0, 0]},
    ],
}
MESH = {
    "name": "SharedMesh",
    "positions": [[0, 0, 0], [10, 0, 0], [0, 0, 10]],
    "normals": [[0, -1, 0]] * 3,
    "tangents": [[1, 0, 0, 1]] * 3,
    "indices": [0, 1, 2],
    "uvChannels": [[[0, 0], [1, 0], [0, 1]]],
    "sections": [
        {
            "materialIndex": 0,
            "firstIndex": 0,
            "triangleCount": 1,
            "materialName": "SharedMaterial",
            "materialPath": "/Game/Test/M.M",
        }
    ],
    "boneNames": ["Child"],
    "weights": [[[0, 1.0]]] * 3,
    "inlineSkeleton": SKELETON,
}


def index_fixtures(directory):
    requests = []

    def request(*args, profile, aes_key):
        payload = args[3]
        requests.append((profile.gargoyle_profile, aes_key, payload))
        return {
            "meshIndex": {
                "staticMeshes": ["Mesh_10", "Mesh_2"],
                "skeletalMeshes": ["Rig"],
                "failures": [],
            },
            "animationIndex": {
                "animations": [{"assetPath": "Clip_2"}, {"assetPath": "Clip_1"}]
            },
            "index": {"paths": ["Clip_10", "Clip_2", "Clip_2"], "warnings": []},
        }

    def cache_path(key):
        digest = hashlib.sha256(json.dumps(key).encode()).hexdigest()
        return Path(directory) / (digest + ".json")

    paths = GamePaths(directory, aes_key="a" * 64)
    with (
        patch.object(indexing, "_run_gargoyle_asset_request", request),
        patch.object(indexing, "_mesh_package_signature", lambda *a, **k: []),
        patch.object(indexing, "_mesh_disk_cache_path", cache_path),
    ):
        meshes = indexing.MeshAssetIndex()
        assert meshes.refresh(paths, remake.PROFILE)[0] == ["Mesh_2", "Mesh_10"]
        meshes.refresh(paths, remake.PROFILE)
        assert len(requests) == 1
        cached = indexing.MeshAssetIndex()
        cached.refresh(paths, remake.PROFILE)
        assert cached.source == "disk cache" and len(requests) == 1
        cached.refresh(paths, crisis_core.PROFILE)
        cached.refresh(replace(paths, aes_key="b" * 64), crisis_core.PROFILE)
        cached.refresh(paths, crisis_core.PROFILE, path_filter="/Model/")
        assert len(requests) == 4, requests
        assert all(
            paths.aes_key not in p.read_text() for p in Path(directory).glob("*.json")
        )
        clips = indexing.AnimationAssetIndex()
        for include in (False, False, True):
            assert clips.refresh(
                paths, remake.PROFILE, "Skeleton", include_unlinked=include
            ) == ["Clip_1", "Clip_2"]
        assert len(requests) == 6
        assert clips.refresh(
            paths, crisis_core.PROFILE, "Skeleton", use_registry=True
        ) == ["Clip_2", "Clip_10"]
        assert requests[-1][2]["action"] == "generic_animation_index"
        clips.refresh(paths, crisis_core.PROFILE, "Skeleton", use_registry=True)
        assert len(requests) == 7
        clips.refresh(paths, crisis_core.PROFILE, "OtherSkeleton", use_registry=True)
        assert len(requests) == 8


class Session:
    """Small decoded payload source that exercises the actual Blender paths."""

    def __init__(self, *args, profile, **kwargs):
        self.profile = profile
        self.cache_namespace = "shared-fixture-" + profile.key

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def static_mesh(self, path):
        payload = copy.deepcopy(MESH)
        payload["name"] = self.profile.key + "_" + Path(path).stem
        return payload

    def skeletal_mesh(self, path, **kwargs):
        payload = self.static_mesh(path)
        payload["skeletonPath"] = (
            self.profile.mounted_content_root
            + "/Character/Player/PC0000_00/Model/PC0000_Skeleton.uasset"
        )
        return payload

    def skeleton_asset(self, path):
        return copy.deepcopy(SKELETON)

    def skeleton_bone_usage(self, *args):
        return {
            "variants": {"FixtureVariant": {"exclusiveWeightedBoneNames": ["Child"]}}
        }

    def material_instance(self, path):
        return {}

    def animation_asset(self, path):
        if path.endswith("Broken.uasset"):
            raise ValueError("Injected clip failure")
        return {
            "name": Path(path).stem,
            "numFrames": 2,
            "framesPerSecond": 30,
            "duration": 1 / 30,
            "tracks": [
                {
                    "boneName": "Root",
                    "translations": [[0, 0, 0], [1, 0, 0]],
                    "rotations": [[0, 0, 0, 1]] * 2,
                    "scales": [[1, 1, 1]] * 2,
                    "bindTranslation": [0, 0, 0],
                    "bindRotation": [0, 0, 0, 1],
                    "bindScale": [1, 1, 1],
                }
            ],
        }

    def __call__(self, path):
        return None


def operator_fixtures(directory):
    titles = [
        (remake, "ff7r_remake"),
        (crisis_core, "ff7r_crisis_core"),
        (kh3, "sqex_kh3"),
        (kh02, "sqex_kh02"),
    ]
    with ExitStack() as stack:
        stack.enter_context(
            patch.object(unreal_package, "PackageAssetSession", Session)
        )
        for title, prefix in titles:
            definition = title.DEFINITION
            static_paths = [
                definition.profile.mounted_content_root + "/Props/Prop_1.uasset",
                definition.profile.mounted_content_root + "/Props/Prop_2.uasset",
            ]
            rig_path = definition.profile.mounted_content_root + "/Character/Rig.uasset"
            stack.enter_context(
                patch.object(
                    definition, "configured_paths", lambda context: GamePaths(directory)
                )
            )
            stack.enter_context(
                patch.object(
                    definition.mesh_index,
                    "refresh",
                    lambda *a, _paths=static_paths, _rig=rig_path, **k: (
                        _paths,
                        [_rig],
                    ),
                )
            )
            static_operator = getattr(
                bpy.ops.import_scene, prefix + "_static_mesh_game_packages"
            )
            rig_operator = getattr(
                bpy.ops.import_scene, prefix + "_skeletal_mesh_game_packages"
            )
            package_browser.activate(bpy.context, definition.browser, static_paths)
            definition.browser["selected"].update(static_paths)
            assert static_operator() == {"FINISHED"}
            objects = [
                obj
                for obj in bpy.context.scene.objects
                if obj.get("sqex_virtual_path") in static_paths
            ]
            assert len(objects) == 2
            assert all(obj.data.attributes.get("ff7r_tangent") for obj in objects)
            assert rig_operator(
                virtual_path=rig_path, import_kdi=False, preserve_ue_axis_order=True
            ) == {"FINISHED"}
            rig = bpy.context.active_object.parent
            assert rig and rig.type == "ARMATURE"
            assert (
                rig["sqex_kdi_coordinate_profile"]
                == unreal_package.COORDINATE_PROFILE_REFERENCE
            )
            assert set(rig.data.bones.keys()) == {"Root", "Unused", "Child"}
            if title is remake:
                assert rig.data.collections.get("FixtureVariant")
            if title in (kh3, kh02):
                assert rig.data.bones["Child"][kh_shared.KDI_OBJECT_INDEX_PROPERTY] == 2
                assert rig["sqex_skeletal_mesh_asset_path"] == rig_path
            assert rig_operator(
                virtual_path=rig_path,
                import_kdi=False,
                import_mesh_referenced_bones_only=True,
            ) == {"FINISHED"}
            reduced = bpy.context.active_object.parent
            assert {"Root", "Child"}.issubset(reduced.data.bones.keys())
            assert "Unused" not in reduced.data.bones
            if title in (kh3, kh02):
                assert (
                    reduced.data.bones["Child"][kh_shared.KDI_OBJECT_INDEX_PROPERTY]
                    == 2
                )
            bpy.context.view_layer.objects.active = reduced
            assert rig_operator(
                virtual_path=rig_path,
                build_skeleton=False,
                bind_active_armature=True,
                import_kdi=False,
            ) == {"FINISHED"}
            assert bpy.context.active_object.parent == reduced

        browser = package_browser.make_state("Shared animation fixture")
        clips = [
            "Test/Content/One.uasset",
            "Test/Content/Broken.uasset",
            "Test/Content/Two.uasset",
        ]
        cls = conventional_animation.make_animation_importer(
            class_name="TEST_OT_shared_animation",
            module_name=__name__,
            bl_idname="object.test_shared_animation",
            game_name="Fixture",
            profile=remake.PROFILE,
            configured_paths=lambda context: GamePaths(directory),
            compatible_paths=lambda context, rig: clips,
            import_animation=ff7_animation.import_animation_asset,
            browser=browser,
        )
        bpy.utils.register_class(cls)
        try:
            bpy.context.view_layer.objects.active = reduced
            package_browser.activate(bpy.context, browser, clips)
            browser["selected"].update(clips)
            before = len(bpy.data.actions)
            assert bpy.ops.object.test_shared_animation(start_frame=7) == {"FINISHED"}
            assert len(bpy.data.actions) == before + 2
            assert reduced.animation_data.action.use_fake_user
            assert reduced.animation_data.action[
                "sqex_animation_virtual_path"
            ].endswith("Two.uasset")
            assert reduced.animation_data.action.frame_start == 7
        finally:
            bpy.utils.unregister_class(cls)


def hooks_and_resolvers():
    events = []

    def initialize(obj):
        events.append("initialize")
        obj["test_hook"] = True

    def binding(obj, rig):
        events.append("binding")
        return 1

    hooks = mesh_import.MeshImportHooks(
        initialize_object=initialize, configure_binding=binding
    )
    source = Session(profile=remake.PROFILE)
    static = resolvers.PackageStaticMeshResolver(
        bpy.context, source, 0.01, build_materials=False, hooks=hooks
    )
    first = static("/Game/Prop.Prop")
    assert static("/Game/Prop.Prop") == first and events == ["initialize"]
    skeletal = resolvers.PackageSkeletalMeshResolver(
        bpy.context, source, 0.01, build_materials=False, hooks=hooks
    )
    asset = skeletal("/Game/Rig.Rig")
    assert asset == skeletal("/Game/Rig.Rig") and asset.armature
    assert events == ["initialize", "initialize", "binding"]
    # The Rebirth adapter continues to inject its title behavior, while the
    # neutral pipeline is usable without importing a title shader at all.
    with patch.object(
        rebirth.rmi_surface, "initialize_external_emissive_context", initialize
    ):
        obj = rebirth.import_static_mesh_asset(bpy.context, MESH, "/Game/Legacy")
        assert obj["test_hook"]
    neutral = unreal_package.import_static_mesh_asset(
        bpy.context, MESH, "/Game/Neutral"
    )
    assert not neutral.get("test_hook")


with tempfile.TemporaryDirectory(prefix="talisman-shared-fixtures-") as directory:
    index_fixtures(directory)
    operator_fixtures(directory)
hooks_and_resolvers()
remake._VIRTUAL_STATIC_MESHES = ["Stale previous implementation"]
crisis_core._MESH_CACHE_SOURCE = "Stale previous implementation"
addon = importlib.reload(addon)
addon.register()
assert remake._VIRTUAL_STATIC_MESHES is remake.DEFINITION.virtual_static_meshes
assert crisis_core._MESH_CACHE_SOURCE == crisis_core.DEFINITION.mesh_cache_source
assert bpy.ops.import_scene.ff7r_remake_skeletal_mesh_game_packages.get_rna_type()
assert bpy.ops.object.ff7r_rebirth_apply_animation_game_packages.get_rna_type()
addon.unregister()
print(
    "SHARED_IMPORT_RUNTIME_OK: source-isolated indexes, four title workflows, KDI indices, variants, mesh subsets, binding, clip failure isolation, mesh hooks, resolver reuse, reload"
)
