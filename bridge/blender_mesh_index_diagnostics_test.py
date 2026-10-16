"""Check unreadable-package hints, red reports and failed-index cache recovery."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import sys

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import addon
addon.register()

from addon.core.profiles import GamePaths
from addon.formats.unreal_package import indexing
from addon.formats.unreal_package.importer import PackageMeshOperator
from addon.formats.unreal_mesh import importer as generic


message = "Zero readable packages. The usmap file might be missing or invalid."
bad = {"staticMeshes": [], "skeletalMeshes": [], "failures": 23323, "readablePackages": 0}
for index in (bad, {"failures": ["broken"]}, {"failures": 1}):
    try:
        indexing.validate_mesh_index(index)
    except indexing.UnreadableMeshPackagesError as exc:
        assert str(exc) == message
    else:
        raise AssertionError("Unreadable packages must produce the mapping hint")

for index in (
    {"failures": 0},  # Empty folders / filters do not imply invalid mappings.
    {"failures": 23, "readablePackages": 1},  # Readable non-mesh packages.
    {"failures": 23, "staticMeshes": ["Static"]},
    {"failures": 23, "skeletalMeshes": ["Rig"]},
):
    indexing.validate_mesh_index(index)


paths = GamePaths("fixture", usmap_path="fixture.usmap")
profile = addon.rebirth_profile.PROFILE
index = indexing.MeshAssetIndex()
good = {"staticMeshes": ["Mesh"], "skeletalMeshes": [], "failures": 0, "readablePackages": 1}
request = Mock(return_value={"meshIndex": bad})
with (
    patch.object(indexing, "_mesh_package_signature", return_value=[]),
    patch.object(indexing, "_mesh_disk_cache_path", return_value=None),
    # Old releases wrote failed empty indexes to disk. They must be rescanned.
    patch.object(indexing, "_load_mesh_disk_cache", return_value=([], [])),
    patch.object(indexing, "_save_mesh_disk_cache") as save,
    patch.object(indexing, "_run_gargoyle_asset_request", request),
):
    for force in (False, True):
        try:
            index.refresh(paths, profile, force=force)
        except indexing.UnreadableMeshPackagesError:
            pass
        else:
            raise AssertionError("Expected unreadable index failure")
        assert index.cache_key is None
        assert index.static_meshes == index.skeletal_meshes == []
    assert request.call_count == 2
    save.assert_not_called()
    request.return_value = {"meshIndex": good}
    assert index.refresh(paths, profile) == (["Mesh"], [])
    assert save.call_count == 1
    # A failed forced refresh must not allow reuse of the previous good index.
    request.return_value = {"meshIndex": bad}
    try:
        index.refresh(paths, profile, force=True)
    except indexing.UnreadableMeshPackagesError:
        pass
    assert index.cache_key is None and not index.static_meshes


# All title mesh importers surface the shared exception as an ERROR report,
# which Blender displays in red in its Info log.
for cls in (
    addon.game_packages.FF7R_REBIRTH_OT_import_static_mesh_game_packages,
    addon.game_packages.FF7R_REBIRTH_OT_import_skeletal_mesh_game_packages,
    addon.crisis_core_static_mesh.FF7R_CRISIS_CORE_OT_import_static_mesh_game_packages,
):
    reports = []
    operator = SimpleNamespace(
        _mesh_source=cls._mesh_source, _load_last_import_settings=lambda context: None,
        report=lambda levels, text: reports.append((levels, text)),
    )
    with (
        patch.object(cls._mesh_source, "defaults", None),
        patch.object(cls._mesh_source, "browser_state",
                     side_effect=indexing.UnreadableMeshPackagesError(message)),
    ):
        assert PackageMeshOperator.invoke(operator, bpy.context, None) == {"CANCELLED"}
    assert len(reports) == 1 and reports[0][0] == {"ERROR"} and message in reports[0][1]


class Session:
    response = bad

    def __init__(self, *args): pass
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def request(self, *args): return {"meshIndex": self.response}


reports = []
operator = SimpleNamespace(mesh_kind="STATIC", path_filter="",
                           report=lambda levels, text: reports.append((levels, text)))
key = ("diagnostic-fixture",)
generic._INDEX[key] = good
with (
    patch.object(generic.session, "GenericSession", Session),
    patch.object(generic, "_paths", return_value=paths),
    patch.object(generic, "_game_version", return_value="GAME_UE4_27"),
    patch.object(generic, "_index_key", return_value=key),
    patch.object(generic.package_browser, "activate"),
):
    assert generic.SQEX_OT_index_generic_unreal.execute(operator, bpy.context) == {"CANCELLED"}
    assert reports[-1][0] == {"ERROR"} and message in reports[-1][1]
    assert key not in generic._INDEX
    Session.response = {"staticMeshes": [], "skeletalMeshes": [], "failures": 0, "readablePackages": 1}
    assert generic.SQEX_OT_index_generic_unreal.execute(operator, bpy.context) == {"FINISHED"}
    assert reports[-1][0] == {"INFO"} and message not in reports[-1][1]
generic._INDEX.pop(key, None)
addon.unregister()
print("MESH_INDEX_DIAGNOSTICS_OK: unreadable vs empty, red reports, failed-cache recovery, generic index")
