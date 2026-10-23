"""Verify authored spline shape, source data, placement and generic UMAP controls."""

import copy
import json
from pathlib import Path
import sys
from unittest.mock import patch

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import addon
addon.register()
from addon.core.profiles import GamePaths
from addon.formats.ue_map import splines
from addon.formats.unreal_mesh import importer, maps


def ref(path):
    return {"ObjectPath": path, "ObjectName": f"Object'{path}'"}


def xyz(x, y=0, z=0):
    return {"X": x, "Y": y, "Z": z}


def point(key, co, arrive, leave, mode="CIM_CurveBreak"):
    return dict(InVal=key, OutVal=xyz(*co), ArriveTangent=xyz(*arrive),
                LeaveTangent=xyz(*leave), InterpMode=mode)


points = [
    point(.25, (10, 20, 30), (4, -12, 20), (70, 10, -20)),
    point(2.75, (160, -40, 70), (80, -20, 10), (5, 60, -10), "CIM_CurveAutoClamped"),
    point(4.5, (200, 70, 50), (-20, 60, 25), (-20, -45, -20)),
]
properties = {
    "SplineCurves": {
        "Position": {"Points": points, "bIsLooped": True, "LoopKeyOffset": 2.25},
        "Rotation": {"Points": [{"InVal": .25, "OutVal": dict(X=0, Y=.6, Z=0, W=.8)}]},
        "Scale": {"Points": [{"InVal": .25, "OutVal": xyz(2, 3, 4)}]},
        "ReparamTable": {"Points": [{"InVal": 100, "OutVal": 1.25}]},
    },
    "bClosedLoop": True, "bLoopPositionOverride": True, "LoopPosition": 6.75,
    "DefaultUpVector": xyz(0, 0, 1), "Duration": 4.0,
    "RelativeLocation": xyz(100, 50, 25), "RelativeRotation": {"Yaw": 25},
    "RelativeScale3D": xyz(1, 2, 3),
    "AttachParent": ref("/Game/Map.Map:PersistentLevel.Route.Root"),
}
curve_entry = dict(Type="SplineComponent", SourceType="TngSplineComponent", Name="Path",
                   Outer=ref("/Game/Map.Map:PersistentLevel.Route"), Properties=properties)
root_entry = dict(Type="SceneComponent", Name="Root", Outer=curve_entry["Outer"], Properties={
    "RelativeLocation": xyz(1000, 2000, -500), "RelativeRotation": {"Yaw": 90},
    "RelativeScale3D": xyz(2, 3, 4),
})
span_entry = dict(Type="SplineMeshComponent", SourceType="HbkSplineMeshComponent", Name="Span",
                  Outer=curve_entry["Outer"], Properties={
    "SplineParams": {"StartPos": xyz(10, 20, 30), "EndPos": xyz(300, 400, 500),
                     "StartTangent": xyz(100, 200, -50), "EndTangent": xyz(300, 20, 60),
                     "StartRoll": .3, "EndRoll": -.7, "StartScale": {"X": 2, "Y": 3}},
    "AttachParent": ref("/Game/Map.Map:PersistentLevel.Route.Path"),
    "StaticMesh": ref("/Game/Rail.Rail"), "ForwardAxis": "ESplineMeshAxis::Y",
    "SplineUpDir": xyz(0, 0, 1), "OverrideMaterials": [ref("/Game/RailMaterial.RailMaterial")],
})


class Session:
    cache_namespace = "spline-fixture"

    def umap_actors(self, path):
        # Parent follows its curve to exercise deferred attachment resolution.
        return {"actors": [span_entry, curve_entry, root_entry]}

    def static_mesh(self, path):
        raise AssertionError("Spline-only imports must not load meshes")

    skeletal_mesh = static_mesh


session = Session()
assets = maps.MapAssets(bpy.context, session, .01)
count, missing = maps.import_map(bpy.context, session, assets, "/Game/Map.umap",
                                 import_models=False, import_lights=False)
assert count == 3 and not missing, (count, missing)
obj = next(obj for obj in bpy.data.objects if obj.get("ue_spline_kind") == "PATH")
assert obj.get("source_type") == "TngSplineComponent"
assert obj.get("ue_component_path") == "/Game/Map.Map:PersistentLevel.Route.Path"
assert obj.parent.get("ue_component_path") == properties["AttachParent"]["ObjectPath"]
assert obj.parent.parent.get("sqex_map_import_root")
assert obj.get("ue_spline_closed_loop") and obj.get("ue_spline_point_count") == 3
assert json.loads(obj.data["ue_spline_properties"])["SplineCurves"] == properties["SplineCurves"]
assert obj.data["ue_spline_coordinate_scale"] == .01
assert json.loads(obj.data["ue_spline_point_indices"]) == [[0, 1, 2]]
assert obj.data.bevel_depth == 0 and not obj.modifiers
spline = obj.data.splines[0]
assert spline.use_cyclic_u and spline.type == "BEZIER"
assert all(p.handle_left_type == p.handle_right_type == "FREE" for p in spline.bezier_points)
span = next(obj for obj in bpy.data.objects if obj.get("ue_spline_kind") == "MESH_SPAN")
assert span.parent == obj and span.type == "CURVE" and not span.modifiers
assert json.loads(span.data["ue_spline_properties"]) == {
    key: value for key, value in span_entry["Properties"].items() if key != "AttachParent"}
bpy.context.view_layer.update()
assert (obj.matrix_world.translation - Vector((8.5, -22, -4))).length < 1e-5, obj.matrix_world
assert max(abs(a - b) for actual, expected in zip(span.matrix_world, obj.matrix_world)
           for a, b in zip(actual, expected)) < 1e-5, (span.matrix_world, obj.matrix_world)


def converted(value):
    return Vector((value["X"], -value["Y"], value["Z"])) * .01


def hermite(p0, p1, interval, t):
    return ((2*t**3 - 3*t**2 + 1) * converted(p0["OutVal"]) +
            (t**3 - 2*t**2 + t) * interval * converted(p0["LeaveTangent"]) +
            (-2*t**3 + 3*t**2) * converted(p1["OutVal"]) +
            (t**3 - t**2) * interval * converted(p1["ArriveTangent"]))


def bezier(p0, p1, t):
    return ((1-t)**3 * p0.co + 3*(1-t)**2*t * p0.handle_right +
            3*(1-t)*t**2 * p1.handle_left + t**3 * p1.co)


for i, j, interval in ((0, 1, 2.5), (1, 2, 1.75), (2, 0, 2.25)):
    for step in range(21):
        t = step / 20
        expected = hermite(points[i], points[j], interval, t)
        actual = bezier(spline.bezier_points[i], spline.bezier_points[j], t)
        assert (expected - actual).length < 2e-6, (i, t, expected, actual)
        assert ((obj.matrix_world @ expected) - (obj.matrix_world @ actual)).length < 1e-5

params = span_entry["Properties"]["SplineParams"]
for step in range(21):
    t = step / 20
    expected = hermite({"OutVal": params["StartPos"], "LeaveTangent": params["StartTangent"]},
                       {"OutVal": params["EndPos"], "ArriveTangent": params["EndTangent"]}, 1, t)
    assert (bezier(*span.data.splines[0].bezier_points, t) - expected).length < 2e-6

collection = obj.users_collection[0]

# PathRuntime's sampled cache is metadata, not a replacement for the authored
# Hermite curve. Preserve its identity and cache while keeping the exact shape.
path_entry = copy.deepcopy(curve_entry)
path_entry["SourceType"] = "PathComponent"
path_entry["Properties"].update(LinearizedPath=[xyz(9999, 8888, 7777)],
                                UUID="12345678-1234-5678-1234-567812345678")
path = splines.create_spline(path_entry, "PathRuntime", collection, .01)
assert path.type == "CURVE" and path.get("source_type") == "PathComponent"
retained = json.loads(path.data["ue_spline_properties"])
for field in ("SplineCurves", "LinearizedPath", "UUID"):
    assert retained[field] == path_entry["Properties"][field]
for actual, expected in zip(path.data.splines[0].bezier_points, spline.bezier_points):
    for field in ("co", "handle_left", "handle_right"):
        assert (getattr(actual, field) - getattr(expected, field)).length < 1e-7


def create_variant(name, source_points, **settings):
    entry = copy.deepcopy(curve_entry)
    entry["Properties"] = {"SplineCurves": {"Position": {"Points": source_points}}, **settings}
    return splines.create_spline(entry, name, collection, .01)


linear_points = copy.deepcopy(points[:2])
linear_points[0]["InterpMode"] = "CIM_Linear"
linear = create_variant("Linear", linear_points).data.splines[0]
for step in range(21):
    t = step / 20
    assert (bezier(*linear.bezier_points, t) -
            converted(points[0]["OutVal"]).lerp(converted(points[1]["OutVal"]), t)).length < 2e-6

constant_points = copy.deepcopy(points)
constant_points[0]["InterpMode"] = "CIM_Constant"
constant = create_variant("Constant", constant_points, bClosedLoop=True)
assert len(constant.data.splines) == 1 and not constant.data.splines[0].use_cyclic_u
assert json.loads(constant.data["ue_spline_point_indices"]) == [[1, 2, 0]]
constant = create_variant("ConstantOpen", constant_points)
assert json.loads(constant.data["ue_spline_point_indices"]) == [[0], [1, 2]]
assert [len(s.bezier_points) for s in constant.data.splines] == [1, 2]
single = create_variant("Single", points[:1])
assert len(single.data.splines[0].bezier_points) == 1
assert create_variant("Empty", []) is None
omitted_defaults = copy.deepcopy(span_entry)
del omitted_defaults["Properties"]["SplineParams"]["StartPos"]
default_span = splines.create_spline(omitted_defaults, "ZeroStart", collection, .01)
assert default_span.data.splines[0].bezier_points[0].co.length == 0

legacy = splines.create_spline({"Properties": {"SplineInfo": {"Points": linear_points}}},
                                "Legacy", collection, .01)
assert len(legacy.data.splines[0].bezier_points) == 2
try:
    create_variant("BadKeys", [points[1], points[0]])
except ValueError:
    pass
else:
    raise AssertionError("Invalid input-key order was accepted")

# Hiding curve geometry must not erase transforms used by remaining lights.
light_entry = dict(Type="PointLightComponent", Name="Light", Outer=curve_entry["Outer"],
                   Properties={"Intensity": 100, "AttachParent": span_entry["Properties"]["AttachParent"]})
before = set(bpy.data.objects)
maps.import_map(bpy.context, session, assets, "/Game/HiddenSplines.umap",
                import_models=False, import_splines=False,
                actor_payload={"actors": [light_entry, span_entry, curve_entry, root_entry]})
created = set(bpy.data.objects) - before
bpy.context.view_layer.update()
assert not any(o.type == "CURVE" for o in created)
light = next(o for o in created if o.type == "LIGHT")
assert light.parent.get("ue_component_name") == "Path"
assert (light.matrix_world.translation - obj.matrix_world.translation).length < 1e-5

# Exercise both registered generic UMAP entry points, not just the backend.
# The independent switch must work when all mesh/light import is disabled.
class MountedSession(Session):
    failed = failed_materials = 0
    nanite_fallbacks = {}

    def __init__(self, *args, **kwargs): pass
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def geometry_summary(self): return "No meshes requested."


with (
    patch.object(importer, "_paths", lambda *args: GamePaths("fixture")),
    patch.object(importer, "_game_version", lambda *args: "GAME_UE4_27"),
    patch.object(importer, "_pbr_mapping", lambda *args: {}),
    patch.object(importer, "_hidden_object_patterns", lambda *args: ()),
    patch.object(importer, "_current_index", lambda *args: None),
    patch.object(importer.session, "GenericSession", MountedSession),
):
    for operation, extra in ((bpy.ops.import_scene.sqex_generic_unreal_umap, {}),
                             (bpy.ops.import_scene.sqex_generic_unreal_mesh, {"mesh_kind": "UMAP"})):
        for enabled in (True, False):
            before = set(bpy.data.objects)
            assert operation(virtual_path="/Game/SplineOptions.umap", import_models=False,
                             import_point_lights=False, import_spot_lights=False, import_rect_lights=False,
                             import_splines=enabled, **extra) == {"FINISHED"}
            created = set(bpy.data.objects) - before
            assert len([o for o in created if o.type == "CURVE"]) == int(enabled) * 2

addon.unregister()
print("SPLINE_IMPORT_OK")
