"""Probe or import generic UMAPs using the ignored local game test config."""

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

import bpy


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--game", required=True)
    parser.add_argument("--map", action="append", default=[])
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--save-blend")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    config = json.loads(Path(args.config).read_text())[args.game]
    bpy.ops.preferences.addon_enable(module="addon")
    import addon
    from addon.core.profiles import GamePaths
    from addon.formats.unreal_mesh.session import GenericSession
    paths = GamePaths(config["root"], config.get("oodle") or str(ROOT / ".local/oodle/oo2core_7_win64.dll"),
                      config.get("usmap", ""), config.get("key", ""))
    options = dict(package_root=paths.install_root, game_version=config["version"],
                   oodle_dll=paths.oodle_dll, usmap_path=paths.usmap_path, aes_key=paths.aes_key, mesh_kind="UMAP")
    if "cue4parse_profile" in bpy.ops.import_scene.sqex_generic_unreal_mesh.get_rna_type().properties:
        prefs = bpy.context.preferences.addons["addon"].preferences
        from addon.ui.preferences import ensure_generic_unreal_profiles
        profiles = ensure_generic_unreal_profiles(prefs)
        profile = profiles.add()
        profile.profile_id = "umap_smoke_fixture"
        profile.name = "UMAP Smoke Fixture"
        profile.game_path = paths.install_root
        profile.game_version = config["version"]
        profile.usmap_path = paths.usmap_path
        profile.aes_key = paths.aes_key
        prefs.oodle_dll = paths.oodle_dll
        options = dict(cue4parse_profile=profile.profile_id, mesh_kind="UMAP")
    assert bpy.ops.wm.sqex_index_generic_unreal(**options) == {"FINISHED"}
    with GenericSession(paths, config["version"]) as mounted:
        maps = mounted.request({"action": "umap_index"})["umaps"]
        (ROOT / ".local" / f"{args.game}-umaps.json").write_text(json.dumps(maps, indent=2))
        print("GENERIC_UMAP_INDEX", len(maps), json.dumps(maps[:30]), flush=True)
        if args.probe:
            for path in args.map:
                data = mounted.umap_actors(path)
                (ROOT / ".local" / f"{Path(path).stem}-actors.json").write_text(json.dumps(data, indent=2))
                print("GENERIC_UMAP_PROBE", path, dict(Counter(entry["Type"] for entry in data.get("actors") or [])), flush=True)
    if not args.probe:
        for path in args.map:
            before = set(bpy.data.objects)
            assert bpy.ops.import_scene.sqex_generic_unreal_mesh(**options, virtual_path=path) == {"FINISHED"}
            objects = set(bpy.data.objects) - before
            meshes = [obj for obj in objects if obj.type == "MESH" and not obj.get("sqex_foliage_source")]
            lights = [obj for obj in objects if obj.type == "LIGHT"]
            rigs = [obj for obj in objects if obj.type == "ARMATURE"]
            assert meshes or lights, path
            roots = [obj for obj in objects if obj.get("sqex_map_import_root")]
            assert len(roots) == 1, roots
            for obj in objects:
                assert obj.get("ue_source_id"), obj.name
                for material in obj.data.materials if obj.type == "MESH" else []:
                    assert material.node_tree is not None and len(material.node_tree.links) == 0, material.name
                    for node in material.node_tree.nodes:
                        if node.type == "TEX_IMAGE" and node.image is not None:
                            assert node.image.packed_file
                if obj.type == "ARMATURE":
                    assert all(bone.use_deform for bone in obj.data.bones)
            counts = Counter(obj.data.as_pointer() for obj in meshes)
            report = {"path": path, "objects": len(objects), "meshObjects": len(meshes), "lights": len(lights),
                      "armatures": len(rigs), "uniqueMeshes": len(counts),
                      "reusedMeshPlacements": sum(count - 1 for count in counts.values()),
                      "missing": json.loads(roots[0].get("ue_missing_assets", "[]"))}
            print("GENERIC_UMAP_IMPORT", json.dumps(report), flush=True)
        if args.save_blend:
            bpy.ops.wm.save_as_mainfile(filepath=str(Path(args.save_blend).resolve()))
    addon.unregister()
    print("GENERIC_UMAP_OK", args.game, flush=True)


if __name__ == "__main__":
    main()
