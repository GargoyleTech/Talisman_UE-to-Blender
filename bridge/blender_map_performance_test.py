"""Compare bulk foliage with the original mathutils placement and mesh sources."""

from pathlib import Path
import json
import sys
import tempfile
import time

import bpy
import numpy as np
from mathutils import Euler, Matrix, Quaternion, Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import addon
addon.register()
from addon.formats.ue_map.instance_geometry import foliage_transform_arrays, load_map_instances
from addon.formats.ue_map.map_import import transform_location_rotation_scale
from addon.formats.unreal_package.mesh_import import import_static_mesh_datablock


def legacy(rows, component, scale):
    locations, rotations, scales = [], [], []
    for row in rows:
        transform = {"Translation": dict(zip("XYZ", row[:3])), "Rotation": dict(zip("WXYZ", row[3:7])),
                     "Scale3D": dict(zip("XYZ", row[7:]))}
        loc, rot, size = transform_location_rotation_scale(transform, scale)
        loc, quat, size = (component @ Matrix.LocRotScale(loc, rot, size)).decompose()
        locations.append(tuple(loc)); rotations.append(tuple(quat.to_euler("XYZ"))); scales.append(tuple(size))
    return tuple(np.asarray(values) for values in (locations, rotations, scales))


rng = np.random.default_rng(1337)
rows = rng.normal(size=(600, 10)).astype(np.float32)
rows[:, :3] *= 1000
rows[:, 7:] *= 2
rows[0, 3:7] = 0
rows[1, 7:] = 0
rows[2, 3:7] = (np.sqrt(.5), 0, np.sqrt(.5), 0)
rows[3, 3:7] *= 100
for size in ((1, 1, 1), (2, 2, 2), (2, .5, 3), (-1, 2, .25), (0, 0, 0)):
    component = Matrix.LocRotScale(Vector((3, 4, 5)), Euler((.3, -.7, 1.2)), Vector(size))
    for scale in (.01, 1):
        expected = legacy(rows, component, scale)
        actual = foliage_transform_arrays(rows, component, scale)
        assert np.allclose(actual[0], expected[0], atol=.001, rtol=2e-6), np.max(np.abs(actual[0]-expected[0]))
        for index in range(len(rows)):
            a = Matrix.LocRotScale(None, Euler(actual[1][index]), Vector(actual[2][index]))
            b = Matrix.LocRotScale(None, Euler(expected[1][index]), Vector(expected[2][index]))
            assert np.allclose(a, b, atol=4e-5, rtol=4e-5), (size, index, rows[index], a, b)

with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "instances.bin"
    rows.tofile(path)
    descriptor = {"binaryInstances": {"version": 1, "file": path.name, "shape": [len(rows), 10], "dtype": "<f4"}}
    def payload(): return {"actors": [{"Properties": {"PerInstanceSMData": descriptor}}]}
    data = load_map_instances(payload(), directory)["actors"][0]["Properties"]["PerInstanceSMData"]
    assert np.array_equal(data, rows)
    batch = {"actors": [{"Properties": {"PerInstanceSMData": {"binaryInstances": {
        "version": 1, "file": path.name, "shape": [200, 10], "dtype": "<f4", "byteOffset": offset}}}}
        for offset in (0, 200 * 40, 400 * 40)]}
    loaded = load_map_instances(batch, directory)
    arrays = [entry["Properties"]["PerInstanceSMData"] for entry in loaded["actors"]]
    assert all(np.array_equal(array, expected) for array, expected in zip(arrays, np.split(rows, 3)))
    assert arrays[0].base is arrays[1].base is arrays[2].base
    path.write_bytes(path.read_bytes()[:-1])
    try:
        load_map_instances(payload(), directory)
        raise AssertionError("Accepted truncated instances")
    except ValueError:
        pass
    descriptor["binaryInstances"]["file"] = "../outside.bin"
    try:
        load_map_instances(payload(), directory)
        raise AssertionError("Accepted a foliage path outside the temporary folder")
    except ValueError:
        pass
    descriptor["binaryInstances"]["file"] = path.name
    rows.tofile(path)
    descriptor["binaryInstances"]["byteOffset"] = rows.nbytes
    try:
        load_map_instances(payload(), directory)
        raise AssertionError("Accepted a foliage range beyond the stream")
    except ValueError:
        pass
    descriptor["binaryInstances"].pop("byteOffset")
    invalid = rows.copy(); invalid[0, 0] = np.nan; invalid.tofile(path)
    try:
        load_map_instances(payload(), directory)
        raise AssertionError("Accepted non-finite foliage coordinates")
    except ValueError:
        pass
assert np.array_equal(data, rows) # Arrays survive temporary-directory cleanup.

selected = bpy.context.object
before_objects = set(bpy.data.objects)
payload = {"positions": [[0, 0, 0], [100, 0, 0], [0, 100, 0]],
           "normals": [[0, 0, 1]] * 3, "indices": [0, 1, 2], "sections": [], "uvChannels": []}
mesh = import_static_mesh_datablock(bpy.context, payload, "/Game/Fixture.Fixture", game_features=False)
assert set(bpy.data.objects) == before_objects and bpy.context.object == selected
assert mesh.users == 0 and len(mesh.vertices) == 3 and len(mesh.polygons) == 1

large = np.tile(rows[4:], (168, 1))[:100_000]
component = Matrix.Identity(4)
start = time.perf_counter(); old = legacy(large, component, .01); old_time = time.perf_counter()-start
start = time.perf_counter(); new = foliage_transform_arrays(large, component, .01); new_time = time.perf_counter()-start
report = dict(instances=len(large), legacySeconds=old_time, bulkSeconds=new_time, speedup=old_time/new_time)
output = ROOT / ".local/map-speed"
output.mkdir(exist_ok=True)
(output / "foliage.json").write_text(json.dumps(report, indent=2))
print("MAP_PERFORMANCE_FIXTURE_OK", json.dumps(report), flush=True)
addon.unregister()
