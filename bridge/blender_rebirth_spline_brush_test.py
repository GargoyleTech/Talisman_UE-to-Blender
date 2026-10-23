"""Validate real Rebirth brush curves through the title exporter and map importer."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
parser = argparse.ArgumentParser()
parser.add_argument("--config", required=True)
parser.add_argument("--inventory", required=True)
parser.add_argument("--report", required=True)
parser.add_argument("--save-blend")
args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
config = json.loads(Path(args.config).read_text())["rebirth"]
inventory = json.loads(Path(args.inventory).read_text())
bpy.ops.preferences.addon_enable(module="addon")
from addon.formats.unreal_package.session import PackageAssetSession
from addon.games.rebirth.profile import PROFILE
from addon.formats.ue_map import map_import


def point(v):
    return Vector((v.get("X", 0), -v.get("Y", 0), v.get("Z", 0))) * .01


def identify(obj, entry):
    if entry.get("Outer"):
        obj["fixture_component_path"] = entry["Outer"]["ObjectPath"] + "." + entry["Name"]


report = dict(blender=bpy.app.version_string, backend="rebirth", maps=[], curves=0,
              emptyOutlines=0, controlPoints=0, closedPaths=0, owners=Counter(),
              maxShapeErrorMeters=0.0, maxWorldPointErrorMeters=0.0)
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
with PackageAssetSession(config["root"], config.get("oodle", ""), config.get("usmap", ""),
                         profile=PROFILE, aes_key=config.get("key", ""), import_textures=False) as session:
    for mi, item in enumerate(inventory):
        path = item["path"]
        raw = session.request({"action": "generic_sequence", "assetPath": path})["sequence"]["exports"]
        expected = {e["ObjectPath"]: e for e in raw if e["Type"] == "EndSplineBrushComponent"}
        assert len(expected) == item["types"]["EndSplineBrushComponent"]
        payload = session.umap_actors(path)["actors"]
        exported = {e["Outer"]["ObjectPath"] + "." + e["Name"]: e for e in payload if e.get("Outer")}
        assert expected.keys() <= exported.keys()
        collection = bpy.data.collections.new(Path(path).stem)
        bpy.context.scene.collection.children.link(collection)
        before = set(bpy.data.objects)
        _, missing = map_import.import_map_entries(payload, path, 1, 1,
            import_models=False, import_lights=False, import_splines=True,
            import_reflection_probes=False, target_collection=collection, parent_to_root=False,
            game_features=True, component_initializer=identify)
        assert not missing
        bpy.context.view_layer.update()
        objects = {o.get("fixture_component_path"): o for o in set(bpy.data.objects)-before if o.get("fixture_component_path")}
        by_path = {e["ObjectPath"]: e for e in raw if e.get("ObjectPath")}

        def resolve(reference):
            value = reference.get("ObjectPath", "") if isinstance(reference, dict) else ""
            try:
                index = int(value.rsplit(".", 1)[1])
                return raw[index]
            except (IndexError, ValueError):
                return by_path.get(value)

        def world(e, seen=None):
            seen = set() if seen is None else seen
            assert e["ObjectPath"] not in seen
            seen.add(e["ObjectPath"])
            p = e["Properties"]
            local = Matrix.LocRotScale(point(p.get("RelativeLocation", {})),
                map_import.rotation_from_relative(p.get("RelativeRotation", {})).to_quaternion(),
                map_import.scale_from_entry(p))
            parent = resolve(p.get("AttachParent"))
            return world(parent, seen) @ local if parent else local

        for identity, original in expected.items():
            entry, obj = exported[identity], objects[identity]
            assert entry["Type"] == "SplineComponent" and entry["SourceType"] == "EndSplineBrushComponent"
            owner = by_path[original["OuterPath"]]
            assert entry["SplineBrushOwner"]["Type"] == owner["Type"]
            assert obj["ue_volume_type"] == owner["Type"] and obj["ue_spline_kind"] == "VOLUME_OUTLINE"
            assert json.loads(obj["ue_spline_brush_owner"]) == entry["SplineBrushOwner"]
            parent = resolve(original["Properties"]["AttachParent"])
            assert obj.parent == objects[parent["ObjectPath"]]
            vertices = original["Properties"].get("SplineCurves", {}).get("Position", {}).get("Points", [])
            report["owners"][owner["Type"]] += 1
            if not vertices:
                assert obj.type == "EMPTY" and obj["ue_spline_point_count"] == 0
                assert entry["SplineBrushOwner"]["Brush"]
                report["emptyOutlines"] += 1
                continue
            assert obj.type == "CURVE" and obj["source_type"] == "EndSplineBrushComponent"
            assert json.loads(obj.data["ue_spline_properties"])["SplineCurves"] == original["Properties"]["SplineCurves"]
            assert obj["ue_spline_closed_loop_inferred"] and obj.data["ue_spline_authored_space"] == "LOCAL"
            assert not obj.data.use_path and obj.data.bevel_depth == 0 and not obj.modifiers
            spline = obj.data.splines[0]
            assert len(obj.data.splines) == 1 and spline.use_cyclic_u and len(spline.bezier_points) == len(vertices)
            expected_world = world(original)
            for control, source in zip(spline.bezier_points, vertices):
                v = point(source["OutVal"])
                assert (control.co-v).length < .001
                actual, target = obj.matrix_world @ control.co, expected_world @ v
                error = (actual-target).length
                report["maxWorldPointErrorMeters"] = max(report["maxWorldPointErrorMeters"], error)
                assert error < max(.001, max(abs(c) for c in target)*5e-7), (identity, error)
            for i, a in enumerate(spline.bezier_points):
                b = spline.bezier_points[(i+1) % len(vertices)]
                for t in (.25, .5, .75):
                    actual = (1-t)**3*a.co+3*(1-t)**2*t*a.handle_right+3*(1-t)*t*t*b.handle_left+t**3*b.co
                    error = (actual-a.co.lerp(b.co, t)).length
                    report["maxShapeErrorMeters"] = max(report["maxShapeErrorMeters"], error)
                    assert error < .01, (identity, error)
            report["curves"] += 1
            report["closedPaths"] += 1
            report["controlPoints"] += len(vertices)
        report["maps"].append(dict(path=path, outlines=len(expected)))
        if (mi+1) % 10 == 0:
            print("BRUSH_PROGRESS", mi+1, len(inventory), flush=True)
if args.save_blend:
    bpy.ops.wm.save_as_mainfile(filepath=str(Path(args.save_blend).resolve()), compress=True)
Path(args.report).write_text(json.dumps(report, indent=2))
print("REBIRTH_SPLINE_BRUSH_OK", json.dumps({k:v for k,v in report.items() if k != "maps"}))
