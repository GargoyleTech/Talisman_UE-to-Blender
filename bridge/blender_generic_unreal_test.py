"""Exercise the generic importer against locally supplied game packages.

Run Blender in background mode with this script, then -- --config <ignored-json>
--game <config-entry> [--index-only]. Each entry has root/version/key and optional
usmap/oodle. No game paths or keys belong in this source file.
"""

import argparse
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
    parser.add_argument("--index-only", action="store_true")
    parser.add_argument("--static")
    parser.add_argument("--skeletal")
    parser.add_argument("--save-blend")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    config = json.loads(Path(args.config).read_text())[args.game]

    bpy.ops.preferences.addon_enable(module="addon")
    import addon
    from addon.core.profiles import GamePaths
    from addon.formats.unreal_mesh.session import GenericSession
    paths = GamePaths(
        config["root"], config.get("oodle") or str(ROOT / ".local/oodle/oo2core_7_win64.dll"),
        config.get("usmap", ""), config.get("key", ""),
    )
    options = dict(package_root=paths.install_root, game_version=config["version"],
                   oodle_dll=paths.oodle_dll, usmap_path=paths.usmap_path, aes_key=paths.aes_key)
    if "cue4parse_profile" in bpy.ops.import_scene.sqex_generic_unreal_mesh.get_rna_type().properties:
        prefs = bpy.context.preferences.addons["addon"].preferences
        from addon.ui.preferences import ensure_generic_unreal_profiles
        profiles = ensure_generic_unreal_profiles(prefs)
        profile = profiles.add()
        profile.profile_id = "mesh_smoke_fixture"
        profile.name = "Mesh Smoke Fixture"
        profile.game_path = paths.install_root
        profile.game_version = config["version"]
        profile.usmap_path = paths.usmap_path
        profile.aes_key = paths.aes_key
        prefs.oodle_dll = paths.oodle_dll
        options = dict(cue4parse_profile=profile.profile_id)
    # Exercise the dialog's indexing button and shared checklist, not just
    # the gargoyle request used by direct scripted imports.
    result = bpy.ops.wm.sqex_index_generic_unreal(
        **options,
    )
    assert result == {"FINISHED"}, result
    with GenericSession(paths, config["version"]) as mounted:
        response = mounted.request({"action": "generic_mesh_index"})
        index = response["meshIndex"]
    report = {
        "game": args.game, "mount": response.get("mount"),
        "staticCount": len(index.get("staticMeshes") or []),
        "skeletalCount": len(index.get("skeletalMeshes") or []),
        "indexFailures": index.get("failures"), "indexSource": index.get("source"),
        "staticSample": (index.get("staticMeshes") or [])[:12],
        "skeletalSample": (index.get("skeletalMeshes") or [])[:12],
    }
    (ROOT / ".local" / f"{args.game}-index.json").write_text(json.dumps(index, indent=2))
    print("GENERIC_INDEX", json.dumps(report), flush=True)
    assert report["staticCount"] and report["skeletalCount"], report
    if not args.index_only:
        report["imports"] = []
        for kind, explicit, key in (
            ("STATIC", args.static, "staticMeshes"), ("SKELETAL", args.skeletal, "skeletalMeshes"),
        ):
            asset = explicit or index[key][0]
            before = set(bpy.data.objects)
            result = bpy.ops.import_scene.sqex_generic_unreal_mesh(
                **options,
                mesh_kind=kind, virtual_path=asset,
            )
            assert result == {"FINISHED"}, (asset, result)
            new = set(bpy.data.objects) - before
            mesh = next(obj for obj in new if obj.type == "MESH")
            assert len(mesh.data.vertices) and len(mesh.data.polygons), asset
            inventories = []
            for material in mesh.data.materials:
                assert material.node_tree is not None, material.name
                assert len(material.node_tree.links) == 0, material.name
                textures = [node for node in material.node_tree.nodes if node.type == "TEX_IMAGE"]
                inventories.append({
                    "name": material.name, "textureNodes": len(textures),
                    "loadedImages": sum(node.image is not None for node in textures),
                    "warnings": json.loads(material.get("ue_texture_warnings", "[]")),
                })
                for node in textures:
                    assert node.get("ue_texture_path"), node.name
                    if node.image is not None:
                        assert node.image.packed_file is not None, node.image.name
            item = {"kind": kind, "asset": asset, "vertices": len(mesh.data.vertices),
                    "triangles": len(mesh.data.polygons), "uvLayers": len(mesh.data.uv_layers),
                    "materials": inventories}
            if kind == "SKELETAL":
                assert mesh.parent is not None and mesh.parent.type == "ARMATURE"
                assert any(modifier.type == "ARMATURE" for modifier in mesh.modifiers)
                assert any(vertex.groups for vertex in mesh.data.vertices)
                item["bones"] = len(mesh.parent.data.bones)
                item["weightedVertices"] = sum(bool(vertex.groups) for vertex in mesh.data.vertices)
                assert item["weightedVertices"] == item["vertices"], item
                assert all(bone.use_deform for bone in mesh.parent.data.bones)
            report["imports"].append(item)
            print("GENERIC_IMPORT", json.dumps(item), flush=True)
        if args.save_blend:
            bpy.ops.wm.save_as_mainfile(filepath=str(Path(args.save_blend).resolve()))
    (ROOT / ".local" / f"{args.game}-report.json").write_text(json.dumps(report, indent=2))
    print("GENERIC_UNREAL_SMOKE_OK", args.game, flush=True)
    addon.unregister()


if __name__ == "__main__":
    main()
