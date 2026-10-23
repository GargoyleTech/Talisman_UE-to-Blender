"""Retry unreadable real meshes using an ignored probe manifest.

Blender --background --factory-startup --python this_file -- --config private.json
--game hi_fi_rush --baseline geometry.json --report report.json
The baseline is an array of {path, status}; every non-readable entry is retried.
"""

import argparse
import json
from pathlib import Path
import sys

import bpy
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--game", required=True)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    config = json.loads(Path(args.config).read_text())[args.game]
    failed = [entry["path"] for entry in json.loads(Path(args.baseline).read_text())
              if entry["status"] != "readable"]
    assert failed, "The supplied baseline has no failures to exercise."
    bpy.ops.preferences.addon_enable(module="addon")
    import addon
    from addon.core.profiles import GamePaths
    from addon.formats.unreal_mesh.session import GenericSession
    from addon.formats.unreal_package.mesh_import import import_static_mesh_asset
    paths = GamePaths(config["root"], config.get("oodle", ""), config.get("usmap", ""), config.get("key", ""))
    results = []
    with GenericSession(paths, config["version"], import_textures=False) as mounted:
        for path in failed:
            payload = mounted.static_mesh(path)
            obj = import_static_mesh_asset(bpy.context, payload, path, game_features=False)
            mesh = obj.data
            assert len(mesh.vertices) == payload["vertexCount"] > 0, path
            assert len(mesh.polygons) == payload["triangleCount"] > 0, path
            assert len(mesh.uv_layers) == len(payload["uvChannels"]), path
            actual = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
            mesh.vertices.foreach_get("co", actual)
            expected = np.asarray(payload["positions"], dtype=np.float32) * (0.01, -0.01, 0.01)
            assert np.isfinite(actual).all() and np.allclose(actual.reshape(-1, 3), expected, atol=1e-5), path
            assert all(0 <= p.material_index < len(mesh.materials) for p in mesh.polygons), path
            assert all(section.get("materialPath") for section in payload["sections"]), path
            for layer in mesh.uv_layers:
                uv = np.empty(len(layer.data) * 2, dtype=np.float32)
                layer.data.foreach_get("uv", uv)
                assert np.isfinite(uv).all(), path
            item = {"path": path, "vertices": len(mesh.vertices), "triangles": len(mesh.polygons),
                    "uvSets": len(mesh.uv_layers), "materials": len(mesh.materials)}
            results.append(item)
            bpy.data.objects.remove(obj, do_unlink=True)
            bpy.data.meshes.remove(mesh)
            print("DECODED_MESH_IMPORT_OK", json.dumps(item), flush=True)
    report = {"game": args.game, "blender": bpy.app.version_string, "imported": len(results),
              "vertices": sum(x["vertices"] for x in results), "triangles": sum(x["triangles"] for x in results),
              "meshes": results}
    Path(args.report).write_text(json.dumps(report, indent=2))
    addon.unregister()
    print("MESH_DECODE_REGRESSION_OK", report["imported"], flush=True)


if __name__ == "__main__":
    main()
