"""Typed foliage transport and bulk transforms, with exact mathutils fallback for shear."""

from pathlib import Path

import numpy as np
from mathutils import Matrix, Quaternion, Vector


def load_map_instances(payload, output_root):
    root = Path(output_root).resolve()
    streams = {}
    for entry in payload.get("actors") or []:
        if not isinstance(entry, dict):
            continue
        props = entry.get("Properties") or {}
        if not isinstance(props, dict):
            continue
        descriptor = props.get("PerInstanceSMData")
        if not isinstance(descriptor, dict) or "binaryInstances" not in descriptor:
            continue
        info = descriptor["binaryInstances"]
        shape = info.get("shape")
        if (info.get("version") != 1 or info.get("dtype") != "<f4" or not isinstance(shape, list)
                or len(shape) != 2 or any(type(size) is not int for size in shape) or shape[1] != 10
                or not 0 < shape[0] <= 2**31 - 1):
            raise ValueError("Invalid foliage instance stream descriptor.")
        name, offset = info.get("file"), info.get("byteOffset", 0)
        if not isinstance(name, str) or type(offset) is not int or offset < 0 or offset % 40:
            raise ValueError("Invalid foliage instance stream range.")
        if name not in streams:
            path = (root / name).resolve()
            if path.parent != root or path.suffix != ".bin" or path.stat().st_size % 40:
                raise ValueError("Invalid or incomplete foliage instance stream.")
            values = np.fromfile(path, dtype="<f4")
            if not np.isfinite(values).all():
                raise ValueError("Non-finite foliage instance transform.")
            streams[name] = values
        values = streams[name]
        start, end = offset // 4, offset // 4 + shape[0] * 10
        if end > len(values) or ("byteOffset" not in info and end != len(values)):
            raise ValueError("Incomplete foliage instance stream range.")
        props["PerInstanceSMData"] = values[start:end].reshape(shape)
    return payload


def _number(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def transform_rows(transforms):
    if isinstance(transforms, np.ndarray):
        if transforms.ndim != 2 or transforms.shape[1] != 10:
            raise ValueError("Invalid foliage transform array.")
        return transforms
    rows = []
    for transform in transforms:
        if not isinstance(transform, dict):
            continue
        values = []
        for key, axes, default in (("Translation", "XYZ", 0), ("Rotation", "WXYZ", 0), ("Scale3D", "XYZ", 1)):
            source = transform.get(key)
            source = source if isinstance(source, dict) else {}
            values.extend(_number(source.get(axis, 1 if key == "Rotation" and axis == "W" else default),
                                  1 if key == "Rotation" and axis == "W" else default) for axis in axes)
        rows.append(values)
    return np.asarray(rows, dtype=np.float32).reshape(-1, 10)


def foliage_transform_arrays(transforms, component_matrix, location_scale):
    rows = transform_rows(transforms)
    count = len(rows)
    if not count:
        return tuple(np.empty((0, 3), dtype=np.float32) for _ in range(3))
    component = np.asarray(component_matrix, dtype=np.float32)
    locations = rows[:, :3].copy()
    locations *= location_scale
    locations[:, 1] *= -1
    locations = locations @ component[:3, :3].T + component[:3, 3]
    quats = rows[:, 3:7].copy()
    quats[:, 2:] *= -1
    lengths = np.linalg.norm(quats, axis=1)
    valid = lengths > 1e-30
    quats[valid] /= lengths[valid, None]
    if not valid.all():
        zero = Quaternion((0, 0, 0, 0))
        zero.normalize()
        quats[~valid] = tuple(zero)
    w, x, y, z = quats.T
    rotations = np.empty((count, 3, 3), dtype=np.float32)
    rotations[:, 0, 0] = 1 - 2 * (y*y + z*z)
    rotations[:, 0, 1] = 2 * (x*y - z*w)
    rotations[:, 0, 2] = 2 * (x*z + y*w)
    rotations[:, 1, 0] = 2 * (x*y + z*w)
    rotations[:, 1, 1] = 1 - 2 * (x*x + z*z)
    rotations[:, 1, 2] = 2 * (y*z - x*w)
    rotations[:, 2, 0] = 2 * (x*z - y*w)
    rotations[:, 2, 1] = 2 * (y*z + x*w)
    rotations[:, 2, 2] = 1 - 2 * (x*x + y*y)
    input_cy = np.hypot(rotations[:, 0, 0], rotations[:, 1, 0])
    matrices = np.matmul(component[:3, :3], rotations * rows[:, None, 7:10])
    scales = np.linalg.norm(matrices, axis=1)
    scales[np.linalg.det(matrices) < 0] *= -1
    normalized = matrices / np.where(np.abs(scales[:, None, :]) > 1e-30, scales[:, None, :], 1)
    gram = np.matmul(normalized.transpose(0, 2, 1), normalized)
    ordinary = np.max(np.abs(gram - np.eye(3, dtype=np.float32)), axis=(1, 2)) < 2e-5
    # Orthogonal matrices have a direct XYZ conversion. Sheared or degenerate
    # transforms use Blender's own quaternion decomposition, preserving its
    # handling of nonuniform/negative component scales and zero-size instances.
    cy = np.hypot(normalized[:, 0, 0], normalized[:, 1, 0])
    # Blender's quaternion->Euler->matrix round trip loses precision near
    # gimbal lock. Keep that established result for those exceptional rows.
    ordinary &= (input_cy >= .01) & (cy >= .01)
    eulers = np.column_stack((np.arctan2(normalized[:, 2, 1], normalized[:, 2, 2]),
                             np.arctan2(-normalized[:, 2, 0], cy),
                             np.arctan2(normalized[:, 1, 0], normalized[:, 0, 0])))
    singular = cy < 1e-6
    eulers[singular, 0] = np.arctan2(-normalized[singular, 1, 2], normalized[singular, 1, 1])
    eulers[singular, 2] = 0
    for index in np.flatnonzero(~ordinary):
        row = rows[index]
        quat = Quaternion((row[3], row[4], -row[5], -row[6]))
        quat.normalize()
        loc = Vector((float(row[0]) * location_scale, -float(row[1]) * location_scale, float(row[2]) * location_scale))
        location, rotation, scale = (component_matrix @ Matrix.LocRotScale(
            loc, quat.to_euler("XYZ"), Vector(row[7:10]))).decompose()
        locations[index] = location
        eulers[index] = rotation.to_euler("XYZ")
        scales[index] = scale
    return tuple(np.ascontiguousarray(values, dtype=np.float32) for values in (locations, eulers, scales))
