"""Native typed arrays preserve attributes, sections and legacy geometry behavior."""

from pathlib import Path
from types import SimpleNamespace
import sys

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import addon
addon.register()

from addon.formats.unreal_package.mesh_import import import_static_mesh_asset
from addon.formats.unreal_mesh.session import GenericSession
from addon.core.profiles import GamePaths
from addon.formats.unreal_package.binary_geometry import SkinWeights
from addon.formats.unreal_package.mesh_import import import_skeletal_mesh_asset
from addon.formats.unreal_package.session import PackageAssetSession


payload = {
    "name": "NativeFixture", "geometrySource": "NANITE",
    "positions": np.array([[0, 0, 0], [10, 0, 0], [0, 0, 10], [10, 0, 10]], dtype=np.float32),
    "normals": np.array([[0, -1, 0]] * 4, dtype=np.float32),
    "tangents": np.array([[1, 0, 0, -1]] * 4, dtype=np.float32),
    "colors": np.array([[255, 0, 0, 255], [0, 255, 0, 64], [0, 0, 255, 128], [255, 255, 255, 0]], dtype=np.uint8),
    "uvChannels": [np.array([[0, 0], [1, 0], [0, 1], [1, 1]], dtype=np.float32), np.full((4, 2), .25, dtype=np.float32)],
    "indices": np.array([0, 1, 2, 1, 3, 2], dtype=np.int32),
    "sections": [{"materialIndex": 2, "firstIndex": 0, "triangleCount": 1},
                 {"materialIndex": 0, "firstIndex": 3, "triangleCount": 1}],
    "nanite": {"totalPages": 2, "complete": True, "finestClusters": 2},
}


def values(collection, name, width, dtype=np.float32):
    result = np.empty(len(collection) * width, dtype=dtype)
    collection.foreach_get(name, result)
    return result.reshape(-1, width)


for forward in (False, True):
    native = import_static_mesh_asset(bpy.context, payload, "/Game/Native.Native", face_y_forward=forward)
    legacy_payload = {key: value.tolist() if isinstance(value, np.ndarray) else value for key, value in payload.items()}
    legacy_payload["uvChannels"] = [channel.tolist() for channel in payload["uvChannels"]]
    legacy = import_static_mesh_asset(bpy.context, legacy_payload, "/Game/Legacy.Legacy", face_y_forward=forward)
    a, b = native.data, legacy.data
    assert len(a.vertices) == 4 and len(a.polygons) == 2 and len(a.edges) == 5
    for collection, field, width in (("vertices", "co", 3), ("loops", "vertex_index", 1), ("polygons", "material_index", 1)):
        assert np.allclose(values(getattr(a, collection), field, width), values(getattr(b, collection), field, width))
    assert [p.material_index for p in a.polygons] == [2, 0]
    assert all(p.use_smooth for p in a.polygons)
    for i, channel in enumerate(payload["uvChannels"]):
        expected = channel[payload["indices"]].copy()
        expected[:, 1] = 1 - expected[:, 1]
        assert np.allclose(values(a.uv_layers[i].data, "uv", 2), expected)
    assert np.allclose(values(a.color_attributes["Color"].data, "color", 4), payload["colors"] / 255, atol=.005)
    assert np.allclose(values(a.attributes["ff7r_tangent_sign"].data, "value", 1), 1)
    expected_normal = [1, 0, 0] if forward else [0, 1, 0]
    assert all(np.allclose(normal.vector, expected_normal, atol=1e-4) for normal in a.corner_normals)
    assert native["ue_geometry_source"] == a["ue_geometry_source"] == "NANITE"
    assert a["ue_nanite"]["complete"]

# Binary ragged influence rows must bind exactly like legacy JSON pairs.
skin = dict(payload, boneNames=["root", "tip"], weights=SkinWeights(
    np.array([0, 2, 2, 3, 4], dtype=np.int32),
    np.array([[0, .25], [1, .75], [1, 1], [0, 1]], dtype=np.float32)))
skinned, weighted, influences = import_skeletal_mesh_asset(bpy.context, skin, "/Game/Skin.Skin")
assert (weighted, influences) == (3, 4)
assert skinned.vertex_groups["root"].weight(0) == .25
assert skinned.vertex_groups["tip"].weight(0) == .75
assert skinned.vertex_groups["tip"].weight(2) == 1

# The shared session must load both payload types before deleting temporary files.
transport = PackageAssetSession("fixture", "", "", profile=GenericSession(GamePaths("fixture"), "GAME_UE5_5").profile)
request_directories = []


def binary_response(request, **kwargs):
    root = Path(request["geometryOutput"])
    directory = root / "mesh"
    directory.mkdir()
    request_directories.append(root)
    streams = {}
    arrays = {key: payload[key] for key in ("positions", "normals", "indices")}
    skeletal = request["action"] == "skeletal_mesh"
    if skeletal:
        arrays.update(weightOffsets=skin["weights"].offsets, weightPairs=skin["weights"].pairs)
    for name, data in arrays.items():
        data.tofile(directory / f"{name}.bin")
        streams[name] = {"file": f"{name}.bin", "dtype": data.dtype.str, "shape": list(data.shape)}
    mesh = {"vertexCount": 4, "triangleCount": 2, "boneNames": ["root", "tip"],
            "skinInfluenceCount": 4, "binaryGeometry": {"version": 1, "directory": str(directory), "streams": streams}}
    return {"staticMesh" if not skeletal else "skeletalMesh": mesh}


transport.request = binary_response
static = transport.static_mesh("/Game/Static.Static")
skeletal = transport.skeletal_mesh("/Game/Skeletal.Skeletal", report_errors=False)
assert np.array_equal(static["positions"], payload["positions"])
assert isinstance(skeletal["weights"], SkinWeights)
assert [row.tolist() for row in skeletal["weights"]] == [row.tolist() for row in skin["weights"]]
assert all(not directory.exists() for directory in request_directories)

# Geometry quality must not partition material sharing, or reuse a lower-detail mesh.
paths = GamePaths("fixture")
auto = GenericSession(paths, "GAME_UE5_5")
full = GenericSession(paths, "GAME_UE5_5", nanite_mode="NATIVE", max_nanite_triangles=0)
cache = GenericSession(paths, "GAME_UE5_5", nanite_cache_mb=32)
assert auto.cache_namespace == full.cache_namespace == cache.cache_namespace
assert auto.geometry_namespace != full.geometry_namespace
assert auto.geometry_namespace == cache.geometry_namespace
# An older bridge must not silently turn a native request into a fallback.
full.request = lambda request: {"staticMesh": {"positions": [[0, 0, 0]]}}
try:
    full.static_mesh("/Game/LegacyBridge.LegacyBridge")
    raise AssertionError("An old bridge silently ignored the Native mode request")
except RuntimeError as error:
    assert "matching add-on and bridge" in str(error)
print("NANITE_BLENDER_GEOMETRY_OK")
