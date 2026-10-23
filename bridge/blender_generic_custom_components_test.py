"""Check real custom mesh-component coverage through the registered map importer.

Blender --background --factory-startup --python this_file -- --config private.json
--game hi_fi_rush --map <mounted-umap-path> [--report report.json]
[--save-blend scene.blend] [--before-export pre-fix-bridge-response.json].
Game roots, compression-library paths and keys belong in the ignored config.
"""

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import sys

import bpy


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def component_path(entry):
    return entry["Outer"]["ObjectPath"] + "." + entry["Name"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--game", required=True)
    parser.add_argument("--map", required=True)
    parser.add_argument("--report")
    parser.add_argument("--save-blend")
    parser.add_argument("--before-export")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    config = json.loads(Path(args.config).read_text())[args.game]
    bpy.ops.preferences.addon_enable(module="addon")
    import addon
    from addon.core.profiles import GamePaths
    from addon.formats.unreal_mesh.session import GenericSession
    from addon.ui.preferences import ensure_generic_unreal_profiles

    paths = GamePaths(config["root"], config.get("oodle", ""), config.get("usmap", ""), config.get("key", ""))
    with GenericSession(paths, config["version"]) as mounted:
        raw = mounted.request({"action": "generic_sequence", "assetPath": args.map})["sequence"]["exports"]
        payload = mounted.umap_actors(args.map)
    # Match complete serialized object identities, not just per-actor names.
    expected = {entry["ObjectPath"]: entry for entry in raw
                if entry["Type"] not in {"StaticMeshComponent", "SkeletalMeshComponent"}
                and entry["Type"].endswith(("StaticMeshComponent", "SkeletalMeshComponent"))
                and not entry["Type"].endswith("InstancedStaticMeshComponent")}
    assert expected, "This map has no custom rigid mesh components to exercise."
    exported = {component_path(entry): entry for entry in payload["actors"] if entry.get("Outer")}
    assert not expected.keys() - exported.keys(), sorted(expected.keys() - exported.keys())
    expected_meshes = {}
    for path, raw_entry in expected.items():
        entry = exported[path]
        kind = "SkeletalMeshComponent" if raw_entry["Type"].endswith("SkeletalMeshComponent") else "StaticMeshComponent"
        assert entry["Type"] == kind, entry
        reference = entry["Properties"].get("SkeletalMesh" if kind == "SkeletalMeshComponent" else "StaticMesh")
        # Fog helpers and runtime-created components can have no authored mesh.
        if reference and str(reference.get("ObjectPath", "")).casefold() not in {"", "none"}:
            expected_meshes[path] = raw_entry

    prefs = bpy.context.preferences.addons["addon"].preferences
    profile = ensure_generic_unreal_profiles(prefs).add()
    profile.profile_id = "custom_component_regression"
    profile.name = "Custom component regression"
    profile.game_path = paths.install_root
    profile.game_version = config["version"]
    profile.usmap_path = paths.usmap_path
    profile.aes_key = paths.aes_key
    prefs.oodle_dll = paths.oodle_dll
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)

    report = {"game": args.game, "map": args.map, "blender": bpy.app.version_string,
              "customComponents": dict(Counter(entry["Type"] for entry in expected.values())),
              "customComponentsWithoutMesh": len(expected) - len(expected_meshes)}
    if args.before_export:
        before = json.loads(Path(args.before_export).read_text())
        before_payload = next(item["umapActors"] for item in before["responses"] if "umapActors" in item)
        normal = GenericSession.umap_actors
        GenericSession.umap_actors = lambda _session, _path: before_payload
        try:
            assert bpy.ops.import_scene.sqex_generic_unreal_umap(
                cue4parse_profile=profile.profile_id, virtual_path=args.map,
                recursive_import=False, import_textures=False) == {"FINISHED"}
            report["before"] = dict(Counter(obj.type for obj in bpy.data.objects))
        finally:
            GenericSession.umap_actors = normal
        # The baseline has no geometry for custom components, but can contain
        # empties for native pickup meshes whose authored reference is null.
        bpy.ops.object.select_all(action="SELECT")
        bpy.ops.object.delete(use_global=False)

    result = bpy.ops.import_scene.sqex_generic_unreal_umap(
        cue4parse_profile=profile.profile_id, virtual_path=args.map,
        recursive_import=False, import_textures=True, max_texture_resolution=512)
    assert result == {"FINISHED"}, result
    objects = list(bpy.data.objects)
    placed = {obj.get("ue_component_path"): obj for obj in objects if obj.get("ue_component_path")}
    absent = []
    for path, entry in expected_meshes.items():
        obj = placed.get(path)
        if obj is None or not (obj.type == "MESH" or (obj.type == "ARMATURE" and any(c.type == "MESH" for c in obj.children))):
            absent.append(path)
            continue
        assert all(math.isfinite(value) for row in obj.matrix_world for value in row), path
        # Skeletal roots can also parent rigid socket attachments; only the
        # skinned children need an armature modifier and deform weights.
        skins = [obj] if obj.type == "MESH" else [child for child in obj.children
            if child.type == "MESH" and any(mod.type == "ARMATURE" and mod.object == obj for mod in child.modifiers)]
        assert skins, path
        for mesh in skins:
            assert len(mesh.data.vertices) and len(mesh.data.polygons), path
            if obj.type == "ARMATURE":
                assert len(obj.data.bones) and any(mod.type == "ARMATURE" for mod in mesh.modifiers), path
                assert all(vertex.groups for vertex in mesh.data.vertices), path
    assert not absent, absent
    roots = [obj for obj in objects if obj.get("sqex_map_import_root")]
    missing = sorted({asset for root in roots for asset in json.loads(root.get("ue_missing_assets", "[]"))})
    assert not missing, missing
    report.update(after=dict(Counter(obj.type for obj in objects)),
                  placedCustomComponents=len(expected_meshes), missingAssets=missing,
                  triangles=sum(len(obj.data.polygons) for obj in objects if obj.type == "MESH"))
    if args.save_blend:
        bpy.ops.wm.save_as_mainfile(filepath=str(Path(args.save_blend).resolve()), compress=True)
    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2))
    print("CUSTOM_COMPONENT_IMPORT_OK", json.dumps(report), flush=True)
    addon.unregister()


if __name__ == "__main__":
    main()
