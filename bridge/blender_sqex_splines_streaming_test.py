"""Check SQEX world-space paths/root transforms and legacy streaming traversal."""
import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import addon
addon.register()
from addon.core.profiles import GamePaths
from addon.formats import unreal_package
from addon.formats.ue_map import map_import
from addon.formats.ue_map.package_importer import MAP_OPTION_NAMES
from addon.formats.ue_map.streaming import StreamingMapQueue
from addon.games import conventional_map


def ref(path):
    return {"ObjectPath": path, "ObjectName": f"Object'{path}'"}


def vector(value):
    return Vector((value.get("X", 0), -value.get("Y", 0), value.get("Z", 0))) * .01


actor = "/Game/Fixture.Fixture:PersistentLevel.PathActor"
points = [
    {"InVal": .25, "OutVal": {"X": 1000, "Y": 2000, "Z": -500},
     "ArriveTangent": {"X": 40, "Y": -30}, "LeaveTangent": {"X": 160, "Y": 20}, "InterpMode": "CIM_CurveUser"},
    {"InVal": 2.75, "OutVal": {"X": 1400, "Y": 2400, "Z": -300},
     "ArriveTangent": {"X": 50, "Y": 70, "Z": 90}, "LeaveTangent": {"X": 100}, "InterpMode": "CIM_CurveUser"},
]
root = {"Type": "SQEX_SplineRootComponent", "Name": "Root", "Outer": ref(actor), "Properties": {
    "RelativeLocation": points[0]["OutVal"], "RelativeRotation": {"Pitch": 30, "Yaw": 60},
    "RelativeScale3D": {"X": 6.5, "Y": 2, "Z": .5}}}
path = {"Type": "SQEX_SplineComponent", "Name": "Path", "Outer": ref(actor), "Properties": {
    "SplineInfo": {"Points": points}, "SplineReparamTable": {"Points": [{"InVal": 0, "OutVal": .25}]},
    "m_qBaseQuat": {"W": .8, "Z": .6}, "AttachParent": ref(actor + ".Root")}}


def initialize(obj, entry):
    obj["fixture_component"] = entry["Name"]


for normalized in (False, True):
    entries = copy.deepcopy([path, root])  # Deliberately place the parent last.
    if normalized:
        entries[0].update(Type="SplineComponent", SourceType="SQEX_SplineComponent")
        entries[1].update(Type="SceneComponent", SourceType="SQEX_SplineRootComponent", AttachmentParentOnly=True)
    before = set(bpy.data.objects)
    count, missing = map_import.import_map_entries(entries, f"SQEX{normalized}.umap", 1, 1,
        import_models=False, import_lights=False, import_splines=True, game_features=True,
        component_initializer=initialize, import_reflection_probes=False)
    assert count == 2 and not missing
    objects = set(bpy.data.objects) - before
    curve = next(o for o in objects if o.type == "CURVE")
    parent = next(o for o in objects if o.get("fixture_component") == "Root")
    assert parent.type == "EMPTY" and curve.parent == parent
    assert parent["source_type"] == "SQEX_SplineRootComponent"
    assert curve["source_type"] == "SQEX_SplineComponent"
    assert not curve.data.use_path
    saved = json.loads(curve.data["ue_spline_properties"])
    assert saved["SplineInfo"]["Points"] == points and saved["m_qBaseQuat"] == path["Properties"]["m_qBaseQuat"]
    bpy.context.view_layer.update()
    a, b = curve.data.splines[0].bezier_points
    assert a.co.length < 1e-4  # Root origin is the first authored WORLD point.
    for i in range(21):
        t = i / 20
        expected = ((2*t**3-3*t**2+1)*vector(points[0]["OutVal"]) + (-2*t**3+3*t**2)*vector(points[1]["OutVal"]) +
                    (t**3-2*t**2+t)*2.5*vector(points[0]["LeaveTangent"]) + (t**3-t**2)*2.5*vector(points[1]["ArriveTangent"]))
        local = (1-t)**3*a.co + 3*(1-t)**2*t*a.handle_right + 3*(1-t)*t*t*b.handle_left + t**3*b.co
        assert (curve.matrix_world @ local - expected).length < 2e-5
    original = curve.matrix_world @ b.co
    parent.location.x += 3
    bpy.context.view_layer.update()
    assert (curve.matrix_world @ b.co - original - Vector((3, 0, 0))).length < 2e-5

    before = set(bpy.data.objects)
    count, _ = map_import.import_map_entries(entries, f"Disabled{normalized}.umap", 1, 1,
        import_models=True, import_lights=False, import_splines=False, game_features=True,
        component_initializer=initialize, import_reflection_probes=False)
    objects = set(bpy.data.objects) - before
    assert count == 2 and all(o.type == "EMPTY" for o in objects)
    count, _ = map_import.import_map_entries(entries, "EverythingOff.umap", 1, 1,
        import_models=False, import_lights=False, import_splines=False, import_reflection_probes=False)
    assert count == 0

# Rebirth brush outlines use LOCAL points under scale-compensating roots.
# Their omitted loop flag means a closed volume outline, unlike ordinary paths.
brush_actor = "/Game/Brush.Brush:PersistentLevel.Volume"
brush_root = {"Type": "SceneComponent", "Name": "BrushRoot", "Outer": ref(brush_actor),
              "AttachmentParentOnly": True, "Properties": {
                  "RelativeLocation": {"X": 100000, "Y": -20000, "Z": 4000},
                  "RelativeRotation": {"Yaw": 30},
                  "RelativeScale3D": {"X": 10240, "Y": 10240, "Z": 512}}}
brush = {"Type": "EndSplineBrushComponent", "Name": "Outline", "Outer": ref(brush_actor),
         "SplineBrushOwner": {"Type": "EndNaviMapVolume", "ObjectPath": brush_actor,
                              "Brush": ref(brush_actor + ".Model_0")},
         "Properties": {"SplineCurves": {"Position": {"Points": [
             {"InVal": i, "OutVal": {"X": x, "Y": y, "Z": 0}, "InterpMode": "CIM_Linear"}
             for i, (x, y) in enumerate(((0, 0), (10000, 0), (10000, 20000), (0, 20000)))]}},
             "RelativeScale3D": {"X": 1/10240, "Y": 1/10240, "Z": 1/512},
             "AttachParent": ref(brush_actor + ".BrushRoot")}}
for normalized, import_models in ((False, False), (True, False), (False, True), (True, True)):
    entry = copy.deepcopy(brush)
    if normalized:
        entry.update(Type="SplineComponent", SourceType="EndSplineBrushComponent")
    before = set(bpy.data.objects)
    count, missing = map_import.import_map_entries([entry, brush_root], "Brush.umap", 1, 1,
        import_models=import_models, import_lights=False, import_splines=True,
        import_reflection_probes=False, game_features=True, parent_to_root=False)
    made = set(bpy.data.objects) - before
    outline = next(o for o in made if o.type == "CURVE")
    assert count == 2 and not missing and outline.parent is not None
    assert outline.parent.users_collection == outline.users_collection
    assert outline.users_collection[0].name.endswith("_Splines")
    assert outline["source_type"] == "EndSplineBrushComponent"
    assert outline["ue_spline_kind"] == "VOLUME_OUTLINE" and outline["ue_volume_type"] == "EndNaviMapVolume"
    assert json.loads(outline["ue_spline_brush_owner"]) == brush["SplineBrushOwner"]
    assert outline["ue_spline_closed_loop_inferred"] and outline.data.splines[0].use_cyclic_u
    assert outline.data["ue_spline_authored_space"] == "LOCAL"
    bpy.context.view_layer.update()
    a, b = outline.data.splines[0].bezier_points[:2]
    assert abs((outline.matrix_world @ b.co - outline.matrix_world @ a.co).length - 100) < .001
    # The final linear edge must close the polygon with straight handles.
    last, first = outline.data.splines[0].bezier_points[-1], a
    midpoint = (last.co + first.co) / 2
    evaluated = (last.co + 3*last.handle_right + 3*first.handle_left + first.co) / 8
    assert (evaluated - midpoint).length < .001

    explicit = copy.deepcopy(entry)
    explicit["Properties"]["bClosedLoop"] = False
    from addon.formats.ue_map import splines
    opened = splines.create_spline(explicit, "ExplicitOpen", outline.users_collection[0], .01)
    assert not opened.data.splines[0].use_cyclic_u and not opened["ue_spline_closed_loop_inferred"]
    empty = copy.deepcopy(entry)
    del empty["Properties"]["SplineCurves"]
    before = set(bpy.data.objects)
    map_import.import_map_entries([empty, brush_root], "EmptyBrush.umap", 1, 1,
        import_models=False, import_lights=False, import_splines=True,
        import_reflection_probes=False, game_features=True, parent_to_root=False)
    helper = next(o for o in set(bpy.data.objects)-before if o.get("source_type") == "EndSplineBrushComponent")
    assert helper.type == "EMPTY" and helper.parent is not None and helper["ue_spline_point_count"] == 0
    assert helper.parent.users_collection == helper.users_collection
    assert json.loads(helper["ue_spline_brush_owner"]) == brush["SplineBrushOwner"]
    before = set(bpy.data.objects)
    map_import.import_map_entries([entry, brush_root], "DisabledBrush.umap", 1, 1,
        import_models=True, import_lights=False, import_splines=False, import_reflection_probes=False)
    assert all(o.type != "CURVE" for o in set(bpy.data.objects)-before)

paths = ["KINGDOM HEARTS 0.2/Content/Maps/A.umap", "KINGDOM HEARTS 0.2/Content/Maps/B.umap",
         "KINGDOM HEARTS 0.2/Plugins/Feature/Content/Maps/C.umap"]
streams = [
    {"Type": "LevelStreamingKismet", "Properties": {"WorldAsset": "/Game/Maps/B.B"}},
    {"Type": "LevelStreamingKismet", "Properties": {"WorldAsset": {"AssetPathName": "World'/Feature/Maps/C.C'"}}},
    {"Type": "LevelStreamingKismet", "Properties": {"WorldAsset": "None", "PackageNameToLoad": "/Game/Maps/B"}},
    {"Type": "LevelStreamingKismet", "Properties": {"WorldAsset": 42}},
]
queue = StreamingMapQueue([paths[0], paths[0].upper()], paths, content_root="KINGDOM HEARTS 0.2/Content")
queue.extend(streams)
queue.extend([{ "Type": "LevelStreamingKismet", "Properties": {"WorldAsset": "/Game/Maps/A.A"}}])
queue.extend(streams)
assert queue.paths == paths, queue.paths

# A real registered conventional UMAP operator must follow the Kismet edge
# and import a spline-only child map with model and light conversion disabled.
runtime_paths = ["KINGDOM HEARTS III/Content/Maps/A.umap", "KINGDOM HEARTS III/Content/Maps/B.umap"]
class Session:
    calls = []
    def __init__(self, *args, **kwargs): self.profile = kwargs["profile"]
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def __call__(self, path): return None
    def color_lut(self, path): return None
    def umap_actors(self, path):
        self.calls.append(path)
        return {"actors": [{"Type": "LevelStreamingKismet", "Properties": {"WorldAsset": "/Game/Maps/B.B"}}] if path == runtime_paths[0] else [root, path_entry]}

path_entry = copy.deepcopy(path)
profile = addon.kingdom_hearts_iii_static_mesh.PROFILE
cls = conventional_map.make_umap_importer(class_name="SQEX_SplineStreamingFixture", bl_idname="import_scene.sqex_spline_streaming_fixture",
    game_label="Spline fixture", profile=profile, configured_paths=lambda context: GamePaths("fixture"))
bpy.utils.register_class(cls)
try:
    with (patch.object(unreal_package, "_package_config_key", lambda *args: ("fixture",)),
          patch.object(unreal_package, "_run_gargoyle_asset_request", lambda *args, **kwargs: {"umaps": runtime_paths}),
          patch.object(unreal_package, "PackageAssetSession", Session)):
        before = set(bpy.data.objects)
        result = bpy.ops.import_scene.sqex_spline_streaming_fixture(virtual_path=runtime_paths[0], recursive_import=True,
            import_models=False, import_lights=False, import_splines=True, import_light_probes=False)
        assert result == {"FINISHED"} and Session.calls == runtime_paths
        assert len([o for o in set(bpy.data.objects)-before if o.type == "CURVE"]) == 1
finally:
    bpy.utils.unregister_class(cls)
assert "import_splines" in MAP_OPTION_NAMES
addon.unregister()
print("SQEX_SPLINES_STREAMING_OK")
