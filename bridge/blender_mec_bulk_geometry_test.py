"""Bulk MEC triangle construction preserves legacy topology, UVs and normals."""

from pathlib import Path
import sys
import time

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from addon.core.blender.mesh_geometry import populate_triangle_mesh


def values(collection, field, width=1, dtype=np.float32):
    result = np.empty(len(collection) * width, dtype=dtype)
    collection.foreach_get(field, result)
    return result.reshape(-1, width)


def build(vertices, faces, normals, uvs, bulk):
    mesh = bpy.data.meshes.new("Bulk" if bulk else "Legacy")
    if bulk:
        populate_triangle_mesh(mesh, vertices, faces)
    else:
        mesh.from_pydata(vertices.tolist(), [], faces.tolist())
    for channel in range(2):
        layer = mesh.uv_layers.new(name=f"UV{channel}", do_init=not bulk)
        layer.data.foreach_set("uv", np.ascontiguousarray(uvs[faces.reshape(-1), channel*2:channel*2+2]).ravel())
    mesh.normals_split_custom_set_from_vertices(normals.tolist())
    return mesh


vertices = np.array([[0, 0, 0], [2, 0, 0], [0, 2, 0], [0, 0, 2], [9, 9, 9]], dtype=np.float32)
normals = np.tile([.1, .2, 1], (len(vertices), 1)).astype(np.float32)
uvs = np.arange(len(vertices)*4, dtype=np.float32).reshape(-1, 4) / 16
for faces in (np.array([[0, 1, 2], [0, 3, 1]], dtype=np.int32),
              np.array([[0, 1, 2], [2, 1, 0], [0, 0, 1]], dtype=np.int32),
              np.empty((0, 3), dtype=np.int32)):
    a, b = [build(vertices, faces, normals, uvs, bulk) for bulk in (False, True)]
    for collection, field, width, dtype in (
        ("vertices", "co", 3, np.float32), ("loops", "vertex_index", 1, np.int32),
        ("polygons", "loop_start", 1, np.int32), ("polygons", "loop_total", 1, np.int32),
        ("polygons", "use_smooth", 1, np.bool_), ("corner_normals", "vector", 3, np.float32),
    ):
        np.testing.assert_array_equal(values(getattr(a, collection), field, width, dtype),
                                      values(getattr(b, collection), field, width, dtype))
    assert len(a.edges) == len(b.edges)
    for i in range(2):
        np.testing.assert_array_equal(values(a.uv_layers[i].data, "uv", 2), values(b.uv_layers[i].data, "uv", 2))
    for mesh in (a, b):
        obj = bpy.data.objects.new("ShapeKeyFixture", mesh)
        obj.shape_key_add(name="Basis")
        key = obj.shape_key_add(name="Sway_000")
        key.data.foreach_set("co", (vertices + .1).ravel())
        np.testing.assert_array_equal(values(key.data, "co", 3), vertices + .1)
        bpy.data.objects.remove(obj)

rng = np.random.default_rng(42)
vertices = rng.random((300_000, 3), dtype=np.float32)
faces = np.arange(len(vertices), dtype=np.int32).reshape(-1, 3)
normals = np.tile([0, 0, 1], (len(vertices), 1)).astype(np.float32)
uvs = rng.random((len(vertices), 4), dtype=np.float32)
times = []
for bulk in (False, True):
    start = time.perf_counter()
    mesh = build(vertices, faces, normals, uvs, bulk)
    times.append(time.perf_counter() - start)
    bpy.data.meshes.remove(mesh)
print("MEC_BULK_GEOMETRY_OK", "triangles", len(faces), "seconds", times,
      "speedup", times[0] / times[1], flush=True)
