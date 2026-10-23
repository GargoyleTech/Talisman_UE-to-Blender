"""Bulk construction of triangle topology shared by package and MEC imports."""

import numpy as np


def populate_triangle_mesh(mesh, vertices, indices, *, smooth=False):
    vertices = np.ascontiguousarray(vertices, dtype=np.float32)
    indices = np.ascontiguousarray(indices, dtype=np.int32).reshape(-1)
    face_count = indices.size // 3
    mesh.vertices.add(len(vertices))
    mesh.vertices.foreach_set("co", vertices.reshape(-1))
    mesh.loops.add(indices.size)
    mesh.loops.foreach_set("vertex_index", indices)
    mesh.polygons.add(face_count)
    mesh.polygons.foreach_set("loop_start", np.arange(0, indices.size, 3, dtype=np.int32))
    mesh.polygons.foreach_set("loop_total", np.full(face_count, 3, dtype=np.int32))
    # Blender 4.1+ stores flat shading in the sharp_face attribute. Explicitly
    # write both modes: newly allocated polygons can otherwise remain smooth.
    mesh.polygons.foreach_set("use_smooth", np.full(face_count, smooth, dtype=np.bool_))
    mesh.update(calc_edges=True)
