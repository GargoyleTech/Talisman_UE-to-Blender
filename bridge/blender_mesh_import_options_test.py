"""Check universal mesh operators, capability filtering and native UE sockets."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import importlib
import sys

import bpy
from mathutils import Matrix

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import addon
addon.register()

from addon.core.profiles import GamePaths
from addon.formats import unreal_package
from addon.formats.unreal_package import importer as shared
from addon.formats.unreal_mesh import importer as generic
from addon.ui.mesh_importer import CORE_SKELETAL_OPTIONS, GAME_SKELETAL_OPTIONS, draw_package_mesh_options
from addon.ui.nanite import NANITE_OPTION_NAMES


def rna(cls):
    category, name = cls.bl_idname.split(".")
    return getattr(getattr(bpy.ops, category), name).get_rna_type()


titles = (
    addon.remake_static_mesh, addon.crisis_core_static_mesh,
    addon.kingdom_hearts_iii_static_mesh, addon.kingdom_hearts_0_2_static_mesh,
    addon.game_packages, generic,
)
classes = [cls for title in titles for cls in title.CLASSES
           if getattr(cls, "bl_idname", "").endswith(("_static_mesh_game_packages", "_skeletal_mesh_game_packages",
                                      "_generic_unreal_static_mesh", "_generic_unreal_skeletal_mesh"))]
assert len(classes) == 12


class Layout:
    def __init__(self, parent=None):
        self.parent = parent
        self.enabled = True
        self.children, self.props, self.labels = [], [], []

    def child(self):
        child = Layout(self)
        self.children.append(child)
        return child

    def box(self): return self.child()
    def row(self, **kwargs): return self.child()
    def column(self, **kwargs): return self.child()
    def prop(self, operator, name, **kwargs):
        assert hasattr(operator, name), name
        self.props.append(name)
    def label(self, *, text, **kwargs): self.labels.append(text)
    def all_props(self):
        return self.props + [name for child in self.children for name in child.all_props()]


for cls in classes:
    for method in ("invoke", "check", "draw", "execute", "cancel"):
        assert getattr(cls, method) is getattr(shared.PackageMeshOperator, method), (cls, method)
    properties = rna(cls).properties
    assert set(shared.MESH_OPTION_NAMES) <= set(properties.keys())
    assert "mesh_kind" not in properties
    skeletal = cls.mesh_kind == "SKELETAL"
    source = cls._mesh_source
    if skeletal:
        assert set(shared.SKELETAL_OPTION_NAMES) <= set(properties.keys())
        assert not properties["attachment_sockets"].is_hidden
        assert properties["preserve_ue_axis_order"].default is (
            cls is generic.SQEX_OT_import_generic_unreal_skeletal_mesh
        ), cls.bl_idname
        for name in GAME_SKELETAL_OPTIONS:
            applicable = name in source.game_options
            assert properties[name].is_hidden != applicable, (cls, name)
            assert (name in cls._persisted_props) == applicable
    else:
        assert not set(shared.SKELETAL_OPTION_NAMES) & set(properties.keys())

    names = {*shared.MESH_OPTION_NAMES, *shared.SKELETAL_OPTION_NAMES, *GAME_SKELETAL_OPTIONS, *NANITE_OPTION_NAMES}
    operator = SimpleNamespace(**{name: prop.default for name, prop in properties.items() if name in names})
    layout = Layout()
    draw_package_mesh_options(layout, operator, mesh_kind=cls.mesh_kind,
                              game_label=source.game_label, game_options=source.game_options)
    core = {*shared.MESH_OPTION_NAMES, *(shared.SKELETAL_OPTION_NAMES if skeletal else ())}
    assert set(layout.children[0].all_props()) == core
    applicable = set(GAME_SKELETAL_OPTIONS) & source.game_options if skeletal else set()
    has_nanite = cls is generic.SQEX_OT_import_generic_unreal_static_mesh
    assert bool(set(NANITE_OPTION_NAMES) & set(properties.keys())) == has_nanite
    assert len(layout.children) == 1 + bool(applicable) + has_nanite
    if has_nanite:
        assert set(layout.children[1].all_props()) == set(NANITE_OPTION_NAMES)
        assert set(NANITE_OPTION_NAMES) <= set(cls._persisted_props)
    if applicable:
        assert set(layout.children[1].all_props()) == applicable
        assert layout.children[1].labels == [f"{source.game_label} options"]
    if skeletal:
        operator.build_skeleton = False
        layout = Layout()
        draw_package_mesh_options(layout, operator, mesh_kind=cls.mesh_kind,
                                  game_label=source.game_label, game_options=source.game_options)
        assert not layout.children[0].children[-1].enabled
        if applicable:
            assert not layout.children[1].children[0].enabled

    saved, widths = [], []
    operator = SimpleNamespace(
        mesh_kind=cls.mesh_kind, _mesh_source=source, bl_idname=cls.bl_idname,
        _load_last_import_settings=lambda context: None,
        _save_last_import_settings=lambda context: saved.append(True),
    )
    context = SimpleNamespace(window_manager=SimpleNamespace(
        invoke_props_dialog=lambda operator, *, width: widths.append(width) or {"RUNNING_MODAL"}))
    with (
        patch.object(source, "defaults", None),
        patch.object(source, "browser_state", lambda *args, **kwargs: shared.MeshBrowserState({}, ["Mesh.uasset"])),
        patch.object(shared.package_browser, "activate"),
        patch.object(shared, "MESH_DIALOG_WIDTH", 1234),
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


assert rna(generic.SQEX_OT_import_generic_unreal_mesh).properties["preserve_ue_axis_order"].default is True
assert rna(addon.game_packages.FF7R_REBIRTH_OT_import_skeleton_game_packages).properties["preserve_ue_axis_order"].default is False


SKELETON = {
    "name": "SocketFixture", "bones": [
        {"name": "Root", "parentIndex": -1},
        {"name": "Child", "parentIndex": 0, "translation": [10, 0, 0]},
        {"name": "Unused", "parentIndex": 0, "translation": [0, 20, 0]},
    ],
    "sockets": [{"name": "Attach", "boneName": "Child", "translation": [1, 0, 0]}],
}
PAYLOAD = {
    "name": "SocketMesh", "positions": [[0, 0, 0], [10, 0, 0], [0, 0, 10]],
    "normals": [[0, 1, 0]] * 3, "indices": [0, 1, 2], "sections": [],
    "boneNames": ["Child"], "weights": [[[0, 1.0]]] * 3,
    "inlineSkeleton": SKELETON,
}


class Session:
    cache_namespace = "universal-mesh-options"
    hidden_object_patterns = ()
    failed = failed_materials = 0
    nanite_fallbacks = {}
    def geometry_summary(self): return "Fixture geometry."

    def __init__(self, *args, **kwargs): pass
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def static_mesh(self, path): return deepcopy(PAYLOAD)
    def skeletal_mesh(self, path): return deepcopy(PAYLOAD)
    def skeleton_asset(self, path): return deepcopy(SKELETON)


def check_socket_modes(operator, path):
    for mode in ("NONE", "EMPTIES", "BONES"):
        before = set(bpy.data.objects)
        assert operator(virtual_path=path, attachment_sockets=mode, import_mesh_referenced_bones_only=True,
                        connect_bones=True, preserve_ue_axis_order=False, import_kdi=False) == {"FINISHED"}
        added = set(bpy.data.objects) - before
        armature = next(obj for obj in added if obj.type == "ARMATURE")
        assert "Unused" not in armature.data.bones
        assert armature.data.bones["Child"].use_connect
        empties = [obj for obj in added if obj.get("sqex_socket_bone")]
        assert len(empties) == (1 if mode == "EMPTIES" else 0), (mode, empties)
        assert ("Attach" in armature.data.bones) == (mode == "BONES")
        if mode == "BONES":
            assert not armature.data.bones["Attach"].use_deform


# Crisis Core exposes native socket modes and bone controls.
definition = addon.crisis_core_static_mesh.DEFINITION
mesh_path = definition.profile.mounted_content_root + "/Fixture/Mesh.uasset"
with (
    patch.object(definition, "configured_paths", lambda context: GamePaths("fixture")),
    patch.object(definition.mesh_index, "refresh", lambda *args, **kwargs: ([], [mesh_path])),
    patch.object(unreal_package, "PackageAssetSession", Session),
):
    check_socket_modes(bpy.ops.import_scene.ff7r_crisis_core_skeletal_mesh_game_packages, mesh_path)

with (
    patch.object(generic, "_paths", lambda *args: GamePaths("fixture")),
    patch.object(generic, "_game_version", lambda *args: "GAME_UE4_27"),
    patch.object(generic, "_pbr_mapping", lambda *args: {}),
    patch.object(generic, "_hidden_object_patterns", lambda *args: ()),
    patch.object(generic.session, "GenericSession", Session),
):
    check_socket_modes(bpy.ops.import_scene.sqex_generic_unreal_skeletal_mesh, "/Game/Fixture.Mesh")
    # The old public operator ID still dispatches through the same mesh backend.
    assert bpy.ops.import_scene.sqex_generic_unreal_mesh(
        mesh_kind="STATIC", virtual_path="/Game/Fixture.Mesh") == {"FINISHED"}

    # Exercise the public generic operators used by the menu and legacy callers.
    # Preserving axes must bypass the X-to-Y correction, not just its roll.
    for operator, kwargs in (
        (bpy.ops.import_scene.sqex_generic_unreal_skeletal_mesh, {}),
        (bpy.ops.import_scene.sqex_generic_unreal_mesh, {"mesh_kind": "SKELETAL"}),
    ):
        for facing in ("UNREAL", "BLENDER"):
            frames = {}
            tails = {}
            positions = {}
            for preserve in (True, False):
                before = set(bpy.data.objects)
                assert operator(
                    virtual_path="/Game/Fixture.Mesh", build_skeleton=True,
                    preserve_ue_axis_order=preserve, face_y_forward=facing,
                    attachment_sockets="BONES", connect_bones=False, **kwargs,
                ) == {"FINISHED"}
                added = set(bpy.data.objects) - before
                rig = next(obj for obj in added if obj.type == "ARMATURE")
                mesh = next(obj for obj in added if obj.type == "MESH")
                assert mesh.parent == rig
                for target in (rig, rig.data):
                    assert target["sqex_axis_order"] == ("UNREAL" if preserve else "BLENDER")
                    assert target["sqex_face_forward"] == facing
                    assert target["sqex_bone_axis_frame"] == ("SOURCE" if preserve else "BLENDER")
                frames[preserve] = {bone.name: bone.matrix_local.copy() for bone in rig.data.bones}
                tails[preserve] = {bone.name: bone.tail_local.copy() for bone in rig.data.bones}
                positions[preserve] = [vertex.co.copy() for vertex in mesh.data.vertices]
            for name, preserved in frames[True].items():
                expected = preserved @ Matrix((
                    (0, 1, 0, 0), (0, 0, -1, 0), (-1, 0, 0, 0), (0, 0, 0, 1)))
                actual = frames[False][name]
                assert max(abs(a - b) for row_a, row_b in zip(actual, expected)
                           for a, b in zip(row_a, row_b)) < 1e-5, (facing, name, actual, expected)
                assert (tails[True][name] - tails[False][name]).length > 1e-5
            assert all((a - b).length < 1e-6 for a, b in zip(positions[True], positions[False]))

# Rebirth's public mesh operators must reach its skeleton builder and
# material/BNM hooks through the shared definition.
rebirth = addon.game_packages
rig_path = "End/Content/Fixture/Rig.uasset"
skeleton_path = "End/Content/Fixture/Skeleton.uasset"
payload = deepcopy(PAYLOAD)
payload["skeletonPath"] = skeleton_path
with (
    patch.object(rebirth, "_preferences", lambda context: SimpleNamespace(
        rebirth_install_root="fixture", oodle_dll="", rebirth_usmap_path="")),
    patch.object(rebirth, "refresh_mesh_indices", lambda *args, **kwargs: ([mesh_path], [rig_path])),
    patch.object(rebirth, "_VIRTUAL_SKELETONS", [skeleton_path]),
    patch.object(rebirth, "PackageAssetSession", Session),
    patch.object(Session, "skeletal_mesh", lambda self, path: deepcopy(payload)),
    patch.object(rebirth, "_load_skeletal_mesh_bnm_assets", lambda *args: []),
):
    assert bpy.ops.import_scene.ff7r_rebirth_static_mesh_game_packages(virtual_path=mesh_path) == {"FINISHED"}
    assert bpy.ops.import_scene.ff7r_rebirth_skeletal_mesh_game_packages(
        virtual_path=rig_path, import_kdi=False, create_variant_bone_collections=False,
        attachment_sockets="BONES", import_mesh_referenced_bones_only=True) == {"FINISHED"}
    armature = bpy.context.active_object.parent
    assert armature is not None and "Attach" in armature.data.bones

addon.unregister()
importlib.reload(addon)
addon.register()
assert addon.game_packages.FF7R_REBIRTH_OT_import_static_mesh_game_packages.draw is addon.package_mesh_importer.PackageMeshOperator.draw
assert addon.generic_unreal_importer.SQEX_OT_import_generic_unreal_skeletal_mesh.draw is addon.package_mesh_importer.PackageMeshOperator.draw
addon.unregister()
print("MESH_IMPORT_OPTIONS_OK: twelve shared operators, UE4-first layout, hidden extras, sockets, subsets, lifecycle, reload")
