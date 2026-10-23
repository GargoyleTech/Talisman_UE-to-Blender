"""Check real spline exports/curves; credentials stay in an ignored config file."""

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Matrix, Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def converted(value, scale):
    return Vector((value.get("X", 0), -value.get("Y", 0), value.get("Z", 0))) * scale


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--game", required=True)
    parser.add_argument("--inventory")
    parser.add_argument("--map", action="append", default=[])
    parser.add_argument("--source-type", action="append", default=[],
                        help="Restrict validation to these raw source classes, including aliases such as PathComponent")
    parser.add_argument("--report", required=True)
    parser.add_argument("--save-blend")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    config = json.loads(Path(args.config).read_text())[args.game]
    def included(source_type):
        return (source_type in args.source_type if args.source_type else
                source_type.endswith(("SplineComponent", "SplineMeshComponent")))
    paths = list(args.map)
    if args.inventory:
        inventory = json.loads(Path(args.inventory).read_text())
        paths.extend(item["path"] for item in inventory["maps"] if any(
            included(name) for name in item["types"]))
    paths = list(dict.fromkeys(paths))
    assert paths
    bpy.ops.preferences.addon_enable(module="addon")
    from addon.core.profiles import GamePaths
    from addon.formats.ue_map import map_import
    from addon.formats.unreal_mesh import maps
    from addon.formats.unreal_mesh.session import GenericSession

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    report = {"game": args.game, "version": config["version"], "blender": bpy.app.version_string,
              "maps": [], "types": Counter(), "curves": 0, "controlPoints": 0,
              "closedPaths": 0, "maxShapeErrorMeters": 0.0}
    game_paths = GamePaths(config["root"], config.get("oodle", ""), config.get("usmap", ""), config.get("key", ""))
    with GenericSession(game_paths, config["version"], import_textures=False) as mounted:
        assets = maps.MapAssets(bpy.context, mounted, .01)
        for path in paths:
            raw = mounted.request({"action": "generic_sequence", "assetPath": path})["sequence"]["exports"]
            expected = {entry["ObjectPath"]: entry for entry in raw
                        if included(entry["Type"])}
            payload = mounted.umap_actors(path)
            exported = {entry["Outer"]["ObjectPath"] + "." + entry["Name"]: entry
                        for entry in payload["actors"] if entry.get("Outer")}
            assert expected.keys() <= exported.keys(), sorted(expected.keys() - exported.keys())
            before = set(bpy.data.objects)
            _count, missing = maps.import_map(bpy.context, mounted, assets, path,
                import_models=False, import_lights=False, actor_payload=payload)
            assert not missing
            bpy.context.view_layer.update()
            placed = {obj.get("ue_component_path"): obj for obj in set(bpy.data.objects) - before
                      if obj.get("ue_component_path")}
            key_paths = {key: identity for identity, entry in exported.items()
                         for key in map_import._entry_component_reference_keys(entry)}
            map_report = {"path": path, "curves": 0, "controlPoints": 0}
            for identity, raw_entry in expected.items():
                obj = placed.get(identity)
                assert obj is not None and obj.type == "CURVE", identity
                entry = exported[identity]
                props = entry["Properties"]
                if raw_entry["Type"] == "PathComponent":
                    assert entry["Type"] == "SplineComponent" and entry["SourceType"] == "PathComponent"
                    assert obj.get("source_type") == "PathComponent"
                    retained = json.loads(obj.data["ue_spline_properties"])
                    for field in ("LinearizedPath", "UUID"):
                        if field in props:
                            assert retained[field] == props[field], (identity, field)
                if props.get("AttachParent"):
                    parent_path = next((key_paths[key] for key in map_import._object_reference_lookup_keys(
                        props["AttachParent"]) if key in key_paths), None)
                    assert parent_path is not None, (identity, props["AttachParent"])
                    assert obj.parent == placed.get(parent_path), (identity, parent_path, obj.parent)
                assert all(math.isfinite(value) for row in obj.matrix_world for value in row), identity
                local = Matrix.LocRotScale(
                    map_import.location_from_relative(props.get("RelativeLocation", {})),
                    map_import.rotation_from_relative(props.get("RelativeRotation", {})).to_quaternion(),
                    map_import.scale_from_entry(props),
                )
                expected_world = obj.parent.matrix_world @ local if obj.parent else local
                assert max(abs(a - b) for actual, expected_row in zip(obj.matrix_world, expected_world)
                           for a, b in zip(actual, expected_row)) < .0003, identity
                assert not obj.data.use_path, identity
                if entry["Type"] == "SplineMeshComponent":
                    params = props["SplineParams"]
                    points = [{"InVal": 0, "OutVal": params.get("StartPos", {}), "LeaveTangent": params.get("StartTangent", {})},
                              {"InVal": 1, "OutVal": params.get("EndPos", {}), "ArriveTangent": params.get("EndTangent", {})}]
                    position = {}
                else:
                    position = props["SplineCurves"]["Position"]
                    points = position["Points"]
                indices = json.loads(obj.data["ue_spline_point_indices"])
                assert sum(len(run) for run in indices) == len(points)
                for spline, run in zip(obj.data.splines, indices):
                    for control, index in zip(spline.bezier_points, run):
                        assert (control.co - converted(points[index]["OutVal"], .01)).length < 2e-4, identity
                    pairs = list(zip(range(len(run) - 1), range(1, len(run))))
                    if spline.use_cyclic_u:
                        pairs.append((len(run) - 1, 0))
                    for left, right in pairs:
                        i, j = run[left], run[right]
                        a, b = points[i], points[j]
                        interval = b["InVal"] - a["InVal"] if j > i else position.get("LoopKeyOffset", 1)
                        if j < i and props.get("bLoopPositionOverride"):
                            interval = props["LoopPosition"] - a["InVal"]
                        p0, p1 = spline.bezier_points[left], spline.bezier_points[right]
                        for step in range(11):
                            t = step / 10
                            v0, v1 = converted(a["OutVal"], .01), converted(b["OutVal"], .01)
                            if a.get("InterpMode") in {0, "CIM_Linear"}:
                                expected_position = v0.lerp(v1, t)
                            else:
                                expected_position = ((2*t**3 - 3*t**2 + 1)*v0 + (-2*t**3 + 3*t**2)*v1 +
                                    (t**3 - 2*t**2 + t)*interval*converted(a.get("LeaveTangent", {}), .01) +
                                    (t**3 - t**2)*interval*converted(b.get("ArriveTangent", {}), .01))
                            actual = ((1-t)**3*p0.co + 3*(1-t)**2*t*p0.handle_right +
                                      3*(1-t)*t**2*p1.handle_left + t**3*p1.co)
                            error = (expected_position - actual).length
                            report["maxShapeErrorMeters"] = max(report["maxShapeErrorMeters"], error)
                            assert error < .0003, (identity, i, t, error)
                report["types"][raw_entry["Type"]] += 1
                report["closedPaths"] += int(obj.get("ue_spline_closed_loop", False))
                map_report["curves"] += 1
                map_report["controlPoints"] += len(points)
            report["curves"] += map_report["curves"]
            report["controlPoints"] += map_report["controlPoints"]
            report["maps"].append(map_report)
    if args.save_blend:
        bpy.ops.wm.save_as_mainfile(filepath=str(Path(args.save_blend).resolve()), compress=True)
    Path(args.report).write_text(json.dumps(report, indent=2))
    print("SPLINE_GAME_IMPORT_OK", json.dumps({key: value for key, value in report.items() if key != "maps"}))


main()
