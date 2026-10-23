"""Reject corrupt/traversing native manifests before Blender sees their geometry."""

import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest

import numpy as np

path = Path(__file__).resolve().parents[1] / "addon/formats/unreal_package/binary_geometry.py"
spec = importlib.util.spec_from_file_location("binary_geometry", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BinaryGeometryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.directory = self.root / "mesh"
        self.directory.mkdir()
        streams = {}
        for name, data in {
            "positions": np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype="<f4"),
            "normals": np.array([[0, 0, 1]] * 3, dtype="<f4"),
            "indices": np.array([0, 1, 2], dtype="<i4"),
        }.items():
            data.tofile(self.directory / f"{name}.bin")
            streams[name] = {"file": f"{name}.bin", "dtype": data.dtype.str, "shape": list(data.shape)}
        self.payload = {"vertexCount": 3, "triangleCount": 1, "binaryGeometry": {
            "version": 1, "directory": str(self.directory), "streams": streams}}

    def load(self):
        return module.load_binary_geometry(self.payload, self.root)

    def test_roundtrip(self):
        loaded = self.load()
        self.assertEqual(loaded["indices"].tolist(), [0, 1, 2])
        self.assertNotIn("binaryGeometry", loaded)

    def add_weights(self):
        self.payload.update(boneNames=["root", "tip"], skinInfluenceCount=3)
        for name, data in {
            "weightOffsets": np.array([0, 2, 2, 3], dtype="<i4"),
            "weightPairs": np.array([[0, .25], [1, .75], [1, 1]], dtype="<f4"),
        }.items():
            data.tofile(self.directory / f"{name}.bin")
            self.payload["binaryGeometry"]["streams"][name] = {
                "file": f"{name}.bin", "dtype": data.dtype.str, "shape": list(data.shape)}

    def test_ragged_skin_weights(self):
        self.add_weights()
        weights = self.load()["weights"]
        self.assertEqual(len(weights), 3)
        self.assertEqual([row.tolist() for row in weights], [[[0, .25], [1, .75]], [], [[1, 1]]])
        self.assertEqual(weights[-1].tolist(), [[1, 1]])
        self.assertEqual([row.tolist() for row in weights[1:]], [[], [[1, 1]]])
        with self.assertRaises(IndexError): _ = weights[3]

    def test_reject_bad_weights(self):
        self.add_weights()
        for data in ([1, 2, 2, 3], [0, 2, 1, 3], [0, 2, 2, 4], [0, -1, 2, 3]):
            np.array(data, dtype="<i4").tofile(self.directory / "weightOffsets.bin")
            with self.subTest(offsets=data), self.assertRaises(ValueError): self.load()
        np.array([0, 2, 2, 3], dtype="<i4").tofile(self.directory / "weightOffsets.bin")
        for pair in ([2, 1], [.5, 1], [-1, 1], [0, float("nan")], [0, 0]):
            np.array([pair, [1, .75], [1, 1]], dtype="<f4").tofile(self.directory / "weightPairs.bin")
            with self.subTest(pair=pair), self.assertRaises(ValueError): self.load()
        self.payload["binaryGeometry"]["streams"].pop("weightPairs")
        with self.assertRaises(ValueError): self.load()

    def test_reject_bad_data(self):
        for data in (np.array([-1, 1, 2], dtype="<i4"), np.array([0, 1, 3], dtype="<i4"), np.array([0], dtype="<i4")):
            with self.subTest(data=data):
                data.tofile(self.directory / "indices.bin")
                with self.assertRaises(ValueError): self.load()

    def test_reject_nonfinite(self):
        np.full((3, 3), np.nan, dtype="<f4").tofile(self.directory / "positions.bin")
        with self.assertRaises(ValueError): self.load()

    def test_reject_manifest_changes(self):
        original = copy.deepcopy(self.payload)
        changes = (
            lambda m: m.update(version=99),
            lambda m: m.update(directory=str(self.root)),
            lambda m: m["streams"].pop("positions"),
            lambda m: m["streams"]["positions"].update(file="../positions.bin"),
            lambda m: m["streams"]["positions"].update(shape=[2, 3]),
            lambda m: m["streams"]["indices"].update(dtype="<i8"),
        )
        for change in changes:
            self.payload = copy.deepcopy(original)
            change(self.payload["binaryGeometry"])
            with self.subTest(change=change), self.assertRaises(ValueError): self.load()


if __name__ == "__main__": unittest.main()
