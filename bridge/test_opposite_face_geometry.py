"""Compare optimized face matching against the original coordinate-tuple rule."""

import ast
from collections import defaultdict
from pathlib import Path
import sys
import time
import unittest

import numpy as np


# Exercise the numerical helper without requiring Blender to import the parser.
source = Path(__file__).resolve().parents[1] / "addon/formats/mec/parser.py"
tree = ast.parse(source.read_text(encoding="utf-8"))
nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef)
         and node.name == "offset_opposite_face_geometry"]
namespace = dict(np=np, OPPOSITE_FACE_OFFSET=.0005, OPPOSITE_FACE_POSITION_DECIMALS=6,
                 OPPOSITE_FACE_DOT_THRESHOLD=-.99)
exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), namespace)
optimized = namespace["offset_opposite_face_geometry"]


def original(vertices, normals, faces, *, offset=.0005):
    if offset == 0 or not len(vertices) or not len(faces):
        return 0
    groups = defaultdict(list)
    for index, face in enumerate(faces):
        key = tuple(sorted(tuple(round(float(c), 6) for c in vertices[int(v)]) for v in face))
        groups[key].append(index)
    points = vertices[faces]
    face_normals = np.cross(points[:, 1] - points[:, 0], points[:, 2] - points[:, 0]).astype(np.float32)
    lengths = np.sqrt((face_normals * face_normals).sum(axis=1))
    valid = lengths > 1e-30
    face_normals[valid] /= lengths[valid, None]
    affected = set()
    for group in groups.values():
        for position, a in enumerate(group):
            for b in group[position + 1:]:
                if valid[a] and valid[b] and float(np.dot(face_normals[a], face_normals[b])) < -.99:
                    affected.update(int(v) for v in faces[a])
                    affected.update(int(v) for v in faces[b])
    if not affected:
        return 0
    indices = np.array(sorted(affected), dtype=np.int32)
    directions = normals[indices].astype(np.float32, copy=True)
    lengths = np.sqrt((directions * directions).sum(axis=1))
    valid = lengths > 1e-30
    directions[valid] /= lengths[valid, None]
    vertices[indices[valid]] += directions[valid] * float(offset)
    return int(valid.sum())


class OppositeFacesTest(unittest.TestCase):
    def compare(self, vertices, faces, normals=None, offset=.0005):
        vertices = np.asarray(vertices)
        normals = np.ones_like(vertices) if normals is None else normals
        a, b = vertices.copy(), vertices.copy()
        self.assertEqual(original(a, normals, faces, offset=offset), optimized(b, normals, faces, offset=offset))
        np.testing.assert_array_equal(a, b)

    def test_coincident_unwelded_and_degenerate_faces(self):
        points = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]] * 2, dtype=np.float32)
        faces = np.array([[0, 1, 2], [5, 4, 3], [3, 4, 5], [0, 0, 0], [1, 1, 1]])
        self.compare(points, faces)
        self.compare(points, faces, np.zeros_like(points))
        self.compare(points, faces, offset=0)
        self.compare(points, faces, offset=-.002)
        self.compare(points, np.empty((0, 3), dtype=np.int32))

    def test_random_duplicate_groups(self):
        for seed in range(30):
            rng = np.random.default_rng(seed)
            points = rng.uniform(-50, 50, (300, 3)).astype(np.float32)
            faces = np.arange(300).reshape(-1, 3)
            points = np.concatenate([points, points, points + 1e-8])
            faces = np.concatenate([faces, faces[:, ::-1] + 300, faces + 600])
            rng.shuffle(faces)
            normals = rng.normal(size=points.shape).astype(np.float32)
            self.compare(points, faces, normals)

    def test_decimal_rounding_boundaries(self):
        for dtype in (np.float32, np.float64):
            for value in (.0078125, .0234375, 16.055, .0000005, -.0000015, 123.4567895):
                for direction in (-np.inf, np.inf):
                    x = np.nextafter(dtype(value), dtype(direction), dtype=dtype)
                    points = np.array([[x, 0, 0], [1, 0, 0], [0, 1, 0],
                                       [round(float(x), 6), 0, 0]], dtype=dtype)
                    self.compare(points, np.array([[0, 1, 2], [2, 1, 3]]))


if __name__ == "__main__":
    benchmark = "--benchmark" in sys.argv
    if benchmark:
        sys.argv.remove("--benchmark")
    result = unittest.main(exit=False).result
    if not result.wasSuccessful():
        raise SystemExit(1)
    if benchmark:
        rng = np.random.default_rng(42)
        vertices = rng.uniform(-100, 100, (300_000, 3)).astype(np.float32)
        normals = np.ones_like(vertices)
        faces = np.arange(len(vertices), dtype=np.int32).reshape(-1, 3)
        durations = []
        for function in (original, optimized):
            start = time.perf_counter()
            assert function(vertices.copy(), normals, faces) == 0
            durations.append(time.perf_counter() - start)
        print(f"OPPOSITE_FACE_BENCHMARK triangles={len(faces)} original={durations[0]:.3f}s "
              f"optimized={durations[1]:.3f}s speedup={durations[0] / durations[1]:.2f}x")
