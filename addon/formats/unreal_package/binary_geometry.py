"""Validate and load bounded, temporary bridge geometry streams as typed arrays."""

from pathlib import Path

import numpy as np


class SkinWeights:
    """Ragged influence rows backed by typed arrays, without Python pair lists."""

    def __init__(self, offsets, pairs):
        self.offsets, self.pairs = offsets, pairs

    def __len__(self):
        return len(self.offsets) - 1

    def __iter__(self):
        for start, end in zip(self.offsets[:-1], self.offsets[1:]):
            yield self.pairs[start:end]

    def __getitem__(self, index):
        if isinstance(index, slice):
            return [self[row] for row in range(*index.indices(len(self)))]
        if index < 0:
            index += len(self)
        if not 0 <= index < len(self):
            raise IndexError(index)
        return self.pairs[self.offsets[index]:self.offsets[index + 1]]


def load_binary_geometry(payload, output_root):
    manifest = payload.get("binaryGeometry")
    if not manifest:
        return payload
    if manifest.get("version") != 1:
        raise ValueError("Unsupported binary geometry format.")
    root = Path(output_root).resolve()
    directory = Path(manifest["directory"]).resolve()
    if directory.parent != root:
        raise ValueError("Geometry directory is outside this request's output folder.")
    vertices, triangles = int(payload["vertexCount"]), int(payload["triangleCount"])
    if vertices <= 0 or triangles <= 0 or max(vertices, triangles * 3) > 2**31 - 1:
        raise ValueError("Geometry exceeds Blender's mesh index limits.")
    allowed = {
        "positions": ("<f4", [vertices, 3]), "normals": ("<f4", [vertices, 3]),
        "tangents": ("<f4", [vertices, 4]), "colors": ("|u1", [vertices, 4]),
        "indices": ("<i4", [triangles * 3]),
        **{f"uv{i}": ("<f4", [vertices, 2]) for i in range(8)},
    }
    streams = manifest.get("streams") or {}
    influence_count = int(payload.get("skinInfluenceCount", 0))
    if not 0 <= influence_count <= 2**31 - 1:
        raise ValueError("Invalid skin influence count.")
    allowed.update({
        "weightOffsets": ("<i4", [vertices + 1]),
        "weightPairs": ("<f4", [influence_count, 2]),
    })
    if not {"positions", "normals", "indices"} <= streams.keys():
        raise ValueError("Geometry is missing required streams.")
    loaded = {}
    for name, info in streams.items():
        if name not in allowed or (info.get("dtype"), info.get("shape")) != allowed[name]:
            raise ValueError(f"Invalid geometry stream descriptor: {name}.")
        path = (directory / info["file"]).resolve()
        if path.parent != directory or path.suffix != ".bin":
            raise ValueError("Invalid geometry stream path.")
        dtype, shape = allowed[name]
        count = int(np.prod(shape, dtype=np.int64))
        if path.stat().st_size != count * np.dtype(dtype).itemsize:
            raise ValueError(f"Incomplete geometry stream: {name}.")
        values = np.fromfile(path, dtype=dtype, count=count).reshape(shape)
        if values.dtype.kind == "f" and not np.isfinite(values).all():
            raise ValueError(f"Non-finite geometry stream: {name}.")
        loaded[name] = values
    uv_names = [name for name in loaded if name.startswith("uv")]
    if set(uv_names) != {f"uv{i}" for i in range(len(uv_names))}:
        raise ValueError("Geometry UV channels are not consecutive.")
    indices = loaded["indices"]
    if indices.min() < 0 or indices.max() >= vertices:
        raise ValueError("Geometry contains out-of-range indices.")
    result = dict(payload)
    result.update({name: values for name, values in loaded.items()
                   if not name.startswith(("uv", "weight"))})
    result["uvChannels"] = [loaded[f"uv{i}"] for i in range(len(uv_names))]
    if {"weightOffsets", "weightPairs"} & loaded.keys():
        if not {"weightOffsets", "weightPairs"} <= loaded.keys():
            raise ValueError("Incomplete skin-weight streams.")
        offsets, pairs = loaded["weightOffsets"], loaded["weightPairs"]
        if offsets[0] != 0 or offsets[-1] != influence_count or np.any(offsets[1:] < offsets[:-1]):
            raise ValueError("Invalid skin-weight offsets.")
        bones = len(payload.get("boneNames") or [])
        if (np.any(pairs[:, 0] < 0) or np.any(pairs[:, 0] >= bones)
                or np.any(pairs[:, 0] != np.floor(pairs[:, 0])) or np.any(pairs[:, 1] <= 0)):
            raise ValueError("Invalid skin influences.")
        result["weights"] = SkinWeights(offsets, pairs)
    if "lods" in result:
        result["lods"] = [load_binary_geometry(lod, output_root) for lod in result["lods"]]
    result.pop("binaryGeometry")
    return result
