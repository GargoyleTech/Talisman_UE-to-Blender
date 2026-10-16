"""Check shared UMAP controls and their runtime behavior without game files."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import importlib
import sys

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import addon
addon.register()

from addon.ui.map_importer import draw_package_map_options
from addon.formats.ue_map.package_importer import MAP_OPTION_NAMES, load_map_import_settings, PackageMapOperator
from addon.formats.ue_map import map_import
from addon.formats.ue_map import package_importer
from addon.formats.ue_map.streaming import StreamingMapQueue
from addon.formats.unreal_mesh import importer, maps
from addon.formats.unreal_mesh.session import GenericSession
from addon.formats.unreal_package.session import PackageAssetSession
from addon.formats import unreal_package
from addon.games import conventional_map
from addon.core.profiles import GamePaths


def rna(cls):
    category, name = cls.bl_idname.split(".")
    return getattr(getattr(bpy.ops, category), name).get_rna_type()


map_classes = [
    addon.remake_static_mesh.FF7R_REMAKE_OT_import_umap_game_packages,
    addon.crisis_core_static_mesh.FF7R_CRISIS_CORE_OT_import_umap_game_packages,
    addon.kingdom_hearts_iii_static_mesh.SQEX_KH3_OT_import_umap_game_packages,
    addon.kingdom_hearts_0_2_static_mesh.SQEX_KH02_OT_import_umap_game_packages,
    addon.game_packages.FF7R_REBIRTH_OT_import_mec_game_packages,
    importer.SQEX_OT_import_generic_unreal_umap,
]
for cls in map_classes:
    assert cls.draw is PackageMapOperator.draw
    assert cls.invoke is PackageMapOperator.invoke
    assert cls.check is PackageMapOperator.check
    assert cls.cancel is PackageMapOperator.cancel
    assert cls.execute is PackageMapOperator.execute
    properties = rna(cls).properties
    assert set(MAP_OPTION_NAMES) <= set(properties.keys()), cls.bl_idname
    assert "mesh_kind" not in properties
    assert not ({"build_skeleton", "bind_active_armature", "face_y_forward"} & set(properties.keys()))
    assert properties["import_lights"].is_hidden
    assert set(MAP_OPTION_NAMES) <= set(cls._persisted_props)

static = rna(importer.SQEX_OT_import_generic_unreal_static_mesh).properties
skeletal = rna(importer.SQEX_OT_import_generic_unreal_skeletal_mesh).properties
assert "build_skeleton" not in static and "import_lights" not in static
assert "build_skeleton" in skeletal and "import_lights" not in skeletal
assert "recursive_import" not in static and "recursive_import" not in skeletal
assert "mesh_kind" not in static and "mesh_kind" not in skeletal
assert "mesh_kind" in rna(importer.SQEX_OT_import_generic_unreal_mesh).properties


class Layout:
    def __init__(self, parent=None, kind="root"):
        self.parent, self.kind = parent, kind
        self.enabled = True
        self.children = []
        self.props = []

    def child(self, kind):
        child = Layout(self, kind)
        self.children.append(child)
        return child

    def row(self, **kwargs): return self.child("row")
    def column(self, **kwargs): return self.child("column")
    def box(self): return self.child("box")
    def separator(self): pass
    def label(self, **kwargs): pass
    def prop(self, operator, name, **kwargs):
        assert hasattr(operator, name), name
        self.props.append(name)

    def all_props(self):
        return self.props + [name for child in self.children for name in child.all_props()]


for cls in map_classes:
    operator = SimpleNamespace(**{
        name: prop.default for name, prop in rna(cls).properties.items()
        if name in {*MAP_OPTION_NAMES, "import_originals", "import_sway", "lod_mode", "lod_quality", "lod_level"}
    })
    layout = Layout()
    rebirth = cls is addon.game_packages.FF7R_REBIRTH_OT_import_mec_game_packages
    draw_package_map_options(layout, operator, massive_environment=rebirth)
    rows = [child.all_props() for child in layout.children if child.kind == "row"]
    assert rows == [
        ["recursive_import", "scale_factor"],
        ["import_models", "offset_opposite_faces", "import_textures"],
        ["import_point_lights", "import_spot_lights", "always_cast_shadows"],
        ["exposure", "attenuation_radius_mult", "import_light_probes"],
    ], rows
    assert set(MAP_OPTION_NAMES) == set(layout.all_props()) & set(MAP_OPTION_NAMES)
    assert ("lod_mode" in layout.all_props()) == rebirth
    operator.import_models = False
    operator.import_point_lights = operator.import_spot_lights = False
    layout = Layout()
    draw_package_map_options(layout, operator, massive_environment=rebirth)
    rows = [child for child in layout.children if child.kind == "row"]
    assert not rows[1].children[1].enabled and not rows[1].children[2].enabled
    assert not rows[2].children[2].enabled
    assert not rows[3].children[0].enabled and not rows[3].children[1].enabled
    assert rows[3].children[2].enabled  # Probes are independent of local lights.

migration = SimpleNamespace(import_lights=False, import_point_lights=True, import_spot_lights=True,
                            _load_last_import_settings=lambda context: None)
load_map_import_settings(migration, None)
assert migration.import_lights and not migration.import_point_lights and not migration.import_spot_lights


# Changing one width must affect every game and generic Unreal. Their lifecycle
# also saves settings on cancel and on success, never after a failed import.
for cls in map_classes:
    saved = []
    widths = []
    source = cls._map_source
    operator = SimpleNamespace(
        _map_source=source, bl_idname=cls.bl_idname, import_lights=True,
        _load_last_import_settings=lambda context: None,
        _save_last_import_settings=lambda context: saved.append(True),
    )
    context = SimpleNamespace(window_manager=SimpleNamespace(
        invoke_props_dialog=lambda operator, *, width: widths.append(width) or {"RUNNING_MODAL"}))
    state = package_importer.MapBrowserState({}, ["Fixture.umap"], key="fixture")
    with (
        patch.object(source, "defaults", None),
        patch.object(source, "browser_state", lambda *args, **kwargs: state),
        patch.object(package_importer.package_browser, "activate"),
        patch.object(package_importer, "UMAP_DIALOG_WIDTH", 1234),
        patch.object(source, "execute", lambda *args: {"FINISHED"}),
    ):
        assert cls.invoke(operator, context, None) == {"RUNNING_MODAL"}
        assert widths == [1234]
        cls.cancel(operator, context)
        assert cls.execute(operator, context) == {"FINISHED"}
        assert len(saved) == 2
    with patch.object(source, "execute", lambda *args: {"CANCELLED"}):
        assert cls.execute(operator, context) == {"CANCELLED"}
        assert len(saved) == 2


def streaming(reference):
    return {"Type": "LevelStreamingDynamic", "Properties": {"WorldAsset": {"AssetPathName": reference}}}


paths = ["KINGDOM HEARTS 0.2/Content/Maps/A.umap", "KINGDOM HEARTS 0.2/Content/Maps/B.umap",
         "KINGDOM HEARTS 0.2/Plugins/Feature/Content/Maps/C.umap"]
queue = StreamingMapQueue([paths[0], paths[0].upper()], paths,
                          content_root="KINGDOM HEARTS 0.2/Content")
queue.extend([streaming("/Game/Maps/B.B"), streaming("World'/Game/Maps/B.B'")])
queue.extend([streaming("/Game/Maps/A.A"), streaming("/Feature/Maps/C.C")])
assert queue.paths == paths, queue.paths


entries = [
    {"Type": kind + "LightComponent", "Name": kind, "Properties": {"Intensity": 100}}
    for kind in ("Point", "Spot")
]
for point, spot in ((True, False), (False, True), (False, False), (True, True)):
    before = set(bpy.data.objects)
    count, missing = map_import.import_map_entries(
        entries, f"LightOptions{point}{spot}.umap", 1.0, 1.0,
        import_models=False, import_reflection_probes=False,
        import_point_lights=point, import_spot_lights=spot,
    )
    lights = {obj.data.type for obj in set(bpy.data.objects) - before if obj.type == "LIGHT"}
    expected = ({"POINT"} if point else set()) | ({"SPOT"} if spot else set())
    assert lights == expected and count == int(point) + int(spot), (lights, count)

profile = addon.remake_profile.PROFILE
for mounted in (
    PackageAssetSession("fixture", "", "", profile=profile, import_textures=False),
    GenericSession(GamePaths("fixture"), "GAME_UE4_27", import_textures=False),
):
    def unexpected_request(*args, **kwargs):
        raise AssertionError("Disabled textures must not read any package images")
    mounted.request = unexpected_request
    assert mounted("/Game/Texture.Texture") is None
    assert mounted.failed == mounted.loaded == 0
    assert mounted.texture_namespace.endswith(":no-textures")


# Exercise the actual registered operators, including newly separated generic
# mesh properties and recursive lights-only imports through all three routes.
class SessionFixture:
    cache_namespace = "map-options-runtime"
    game_version = "GAME_UE4_27"
    mount_info = {"contentRoot": "Fixture/Content/"}
    failed = failed_materials = 0
    calls = []
    settings = []
    payload = {
        "name": "OptionsMesh", "positions": [[0, 0, 0], [10, 0, 0], [0, 0, 10]],
        "normals": [[0, 1, 0]] * 3, "indices": [0, 1, 2], "sections": [],
        "boneNames": ["Root"], "weights": [[[0, 1.0]]] * 3,
        "inlineSkeleton": {"bones": [{"name": "Root", "parentIndex": -1}]},
    }

    def __init__(self, *args, **kwargs):
        self.settings.append(kwargs)

    def __enter__(self): return self
    def __exit__(self, *args): pass
    def static_mesh(self, path): return self.payload
    def skeletal_mesh(self, path, **kwargs): return self.payload
    def extract_raw(self, *args, **kwargs): pass
    def release_batch_memory(self): pass

    def umap_actors(self, path):
        self.calls.append(path)
        other = "B" if path.endswith("A.umap") else "A"
        return {"actors": [*entries, streaming(f"/Game/Maps/{other}.{other}")]}

    def umap_data(self, path): return [], self.umap_actors(path)


runtime_paths = ["Fixture/Content/Maps/A.umap", "Fixture/Content/Maps/B.umap"]
options = dict(virtual_path=runtime_paths[0], import_models=False, import_textures=False,
               import_point_lights=False, import_spot_lights=True, import_light_probes=False,
               recursive_import=True)
with (
    patch.object(importer, "_paths", lambda *args: GamePaths("fixture")),
    patch.object(importer, "_game_version", lambda *args: "GAME_UE4_27"),
    patch.object(importer, "_pbr_mapping", lambda *args: {}),
    patch.object(importer, "_current_index", lambda *args: {"umaps": runtime_paths}),
    patch.object(importer.session, "GenericSession", SessionFixture),
):
    assert bpy.ops.import_scene.sqex_generic_unreal_static_mesh(virtual_path="/Game/Mesh.Mesh") == {"FINISHED"}
    assert bpy.ops.import_scene.sqex_generic_unreal_skeletal_mesh(virtual_path="/Game/Rig.Rig") == {"FINISHED"}
    assert bpy.ops.import_scene.sqex_generic_unreal_umap(**options) == {"FINISHED"}
    assert SessionFixture.calls == runtime_paths
    assert SessionFixture.settings[-1]["import_textures"] is False
    SessionFixture.calls.clear()
    assert bpy.ops.import_scene.sqex_generic_unreal_mesh(mesh_kind="UMAP", **options) == {"FINISHED"}
    assert SessionFixture.calls == runtime_paths

test_cls = conventional_map.make_umap_importer(
    class_name="SQEX_OT_fixture_umap", bl_idname="import_scene.sqex_fixture_umap",
    game_label="Fixture", profile=addon.remake_profile.PROFILE,
    configured_paths=lambda context: GamePaths("fixture"))
bpy.utils.register_class(test_cls)
try:
    SessionFixture.calls.clear()
    with (
        patch.object(unreal_package, "_package_config_key", lambda *args: ("fixture",)),
        patch.object(unreal_package, "_run_gargoyle_asset_request", lambda *args, **kwargs: {"umaps": runtime_paths}),
        patch.object(unreal_package, "PackageAssetSession", SessionFixture),
    ):
        # Conventional maps resolve /Game references using their title root.
        runtime_paths[:] = [path.replace("Fixture/Content", "End/Content") for path in runtime_paths]
        assert bpy.ops.import_scene.sqex_fixture_umap(**dict(options, virtual_path=runtime_paths[0])) == {"FINISHED"}
        assert SessionFixture.calls == runtime_paths
finally:
    bpy.utils.unregister_class(test_cls)

rebirth = addon.game_packages
SessionFixture.calls.clear()
with (
    patch.object(rebirth, "_preferences", lambda context: SimpleNamespace(
        rebirth_install_root="fixture", oodle_dll="", rebirth_usmap_path="")),
    patch.object(rebirth, "_VIRTUAL_UMAPS", list(runtime_paths)),
    patch.object(rebirth, "PackageAssetSession", SessionFixture),
    patch.object(rebirth, "import_umap_paths", side_effect=AssertionError("Models disabled must skip MEC")),
):
    assert bpy.ops.import_scene.ff7r_rebirth_mec_game_packages(**dict(options, virtual_path=runtime_paths[0])) == {"FINISHED"}
    assert SessionFixture.calls == runtime_paths

# Registration and hot reload must keep all three concrete generic operators.
addon.unregister()
importlib.reload(addon)
addon.register()
assert "recursive_import" in rna(addon.generic_unreal_importer.SQEX_OT_import_generic_unreal_umap).properties
addon.unregister()
print("MAP_IMPORT_OPTIONS_OK")
