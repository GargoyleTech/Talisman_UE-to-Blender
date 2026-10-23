"""Check one-time map skinning, shared group indices and independent rig poses."""

from copy import deepcopy
from dataclasses import replace
from functools import partial
from pathlib import Path
import sys
import time
from unittest.mock import patch

import bpy
import numpy as np
from mathutils import Euler, Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import addon
addon.register()

from addon.formats.ue_map import map_import
from addon.formats.unreal_mesh.maps import MapAssets
from addon.formats.unreal_package import mesh_import, resolvers
from addon.formats.unreal_package.binary_geometry import SkinWeights
from addon.games.remake.profile import PROFILE


class CountedWeights:
    def __init__(self, rows):
        self.rows, self.iterations = rows, 0

    def __len__(self):
        return len(self.rows)

    def __iter__(self):
        self.iterations += 1
        return iter(self.rows)


PAYLOAD = {
    "name": "SharedSkin", "positions": [[0, 0, 0], [10, 0, 0], [0, 0, 10]],
    "normals": [[0, -1, 0]] * 3, "indices": [0, 1, 2],
    "uvChannels": [[[0, 0], [1, 0], [0, 1]]],
    "sections": [], "boneNames": ["Root", "Child"],
    "weights": [[[0, 1.0]], [[0, 0.25], [1, 0.75]], [[1, 1.0]]],
    "inlineSkeleton": {"bones": [
        {"name": "Root", "parentIndex": -1, "translation": [0, 0, 0]},
        {"name": "Child", "parentIndex": 0, "translation": [0, 0, 5]},
    ]},
}


class Session:
    profile = PROFILE
    cache_namespace = "shared-skin-fixture"

    def __init__(self, payload):
        self.payload, self.mesh_reads = payload, 0

    def skeletal_mesh(self, path, **kwargs):
        self.mesh_reads += 1
        return self.payload

    def material_instance(self, path):
        return {"textures": []}


def weights_snapshot(mesh):
    return [[(entry.group, entry.weight) for entry in vertex.groups] for vertex in mesh.vertices]


def place(asset, name, *, game_features=False):
    return map_import.create_package_skeletal_mesh_instance(
        asset, name, Vector((2, -3, 4)), Euler((0.1, 0.2, -0.3)),
        bpy.context.collection, Vector((1.1, 1.1, 1.1)), game_features=game_features,
    )


def skin(root):
    return next(child for child in root.children if child.type == "MESH") if root.type == "ARMATURE" else root


def evaluated_vertices(obj):
    bpy.context.view_layer.update()
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        values = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
        mesh.vertices.foreach_get("co", values)
        return values
    finally:
        evaluated.to_mesh_clear()


def remove(root):
    for child in list(root.children):
        bpy.data.objects.remove(child, do_unlink=True)
    bpy.data.objects.remove(root, do_unlink=True)


def check_resolver(generic, typed):
    payload = deepcopy(PAYLOAD)
    if typed:
        rows = SkinWeights(np.array([0, 1, 3, 4], dtype=np.int32),
                           np.array([[0, 1], [0, .25], [1, .75], [1, 1]], dtype=np.float32))
    else:
        rows = payload["weights"]
    counted = CountedWeights(rows)
    payload["weights"] = counted
    session = Session(payload)
    resolver = MapAssets(bpy.context, session, .01).skeletal if generic else resolvers.PackageSkeletalMeshResolver(
        bpy.context, session, .01, build_materials=False,
    )
    asset = resolver("/Game/SharedSkin.SharedSkin")
    assert asset is resolver("/Game/SharedSkin.SharedSkin") and session.mesh_reads == 1
    assert asset.shared_weights is not None and counted.iterations == 1
    assert (asset.shared_weights.weighted_vertices, asset.shared_weights.influence_count) == (3, 4)
    before = weights_snapshot(asset.mesh)
    # Source objects have been discarded before even the first placement.
    assert asset.mesh.users == 0
    roots = [place(asset, f"Rig_{generic}_{typed}_{i}") for i in range(8)]
    assert counted.iterations == 1
    assert weights_snapshot(asset.mesh) == before
    for root in roots:
        obj = skin(root)
        assert obj.data == asset.mesh and root.data == asset.armature
        assert tuple(group.name for group in obj.vertex_groups) == ("Root", "Child")
        assert obj.parent == root and obj.matrix_parent_inverse.is_identity
        modifier, = [mod for mod in obj.modifiers if mod.type == "ARMATURE"]
        assert modifier.object == root and not modifier.use_deform_preserve_volume

    # Compare independent poses to a mesh whose weights were written normally.
    reference = place(replace(asset, mesh=asset.mesh.copy(), shared_weights=None), "Reference")
    rest = evaluated_vertices(skin(roots[0]))
    for i, root in enumerate(roots):
        translation = (i * .03, i * -.02, i * .01)
        root.pose.bones["Child"].location = translation
        reference.pose.bones["Child"].location = translation
        np.testing.assert_allclose(evaluated_vertices(skin(root)), evaluated_vertices(skin(reference)), atol=1e-6)
    assert not np.allclose(rest, evaluated_vertices(skin(roots[-1])))
    assert counted.iterations == 2  # Only the deliberately unshared reference rewrote weights.
    remove(reference)
    for root in roots:
        remove(root)

    # Title behavior still runs separately for every placed object.
    calls = []
    hooks = mesh_import.MeshImportHooks(configure_binding=lambda obj, rig: calls.append((obj, rig)) or 1)
    with patch.object(map_import, "_package_skeletal_mesh_binder",
                      partial(mesh_import.bind_skeletal_mesh_object, hooks=hooks)):
        first = place(asset, "HookA", game_features=True)
        second = place(asset, "HookB", game_features=True)
    assert calls == [(skin(first), first), (skin(second), second)]
    assert all(skin(root)["ff7r_limbal_eye_drivers"] == 1 for root in (first, second))
    assert all(skin(root).modifiers[0].use_deform_preserve_volume for root in (first, second))
    assert counted.iterations == 2
    remove(first)
    remove(second)


for generic in (False, True):
    for typed in (False, True):
        check_resolver(generic, typed)


# Non-bone groups precede deform groups, and meshes without a skeleton still
# retain the exact same weights and group indices after the source is deleted.
payload = deepcopy(PAYLOAD)
source = mesh_import.import_static_mesh_asset(bpy.context, payload, "/Game/Mask", game_features=False)
mask = source.vertex_groups.new(name="Mask")
mask.add([0, 2], .5, "REPLACE")
counts = mesh_import.bind_skeletal_mesh_object(source, payload)
shared = mesh_import.SharedSkinWeights.capture(source, payload, *counts)
asset = map_import.SkeletalMeshDatablocks(source.data, None, payload, "/Game/Mask", shared)
before = weights_snapshot(asset.mesh)
bpy.data.objects.remove(source, do_unlink=True)
first, second = place(asset, "NoRigA"), place(asset, "NoRigB")
assert tuple(group.name for group in first.vertex_groups) == ("Mask", "Root", "Child")
assert weights_snapshot(first.data) == before and not first.modifiers
assert abs(second.vertex_groups["Root"].weight(1) - .25) < 1e-6
assert abs(second.vertex_groups["Mask"].weight(0) - .5) < 1e-6

# Standalone binding reuses names, but still initializes its supplied weights.
assert mesh_import.bind_skeletal_mesh_object(first, payload) == counts
assert len(first.vertex_groups) == 3

# Reject a stale group layout or a different mesh before touching the weights.
objects_before = len(bpy.data.objects)
first.vertex_groups["Root"].name = "Renamed"
try:
    place(asset, "Stale")
    raise AssertionError("A changed group layout was accepted")
except ValueError:
    pass
assert len(bpy.data.objects) == objects_before
first.vertex_groups["Renamed"].name = "Root"
other = bpy.data.objects.new("OtherMesh", asset.mesh.copy())
try:
    mesh_import.bind_skeletal_mesh_object(other, payload, shared_weights=shared)
    raise AssertionError("A different shared mesh was accepted")
except ValueError:
    pass
bpy.data.objects.remove(other, do_unlink=True)
remove(first)
remove(second)


if "--benchmark" in sys.argv:
    # Time the same placement path with/without the explicit shared-weight state.
    # Includes creating/removing objects, rig binding and ordinary map metadata.
    payload = deepcopy(PAYLOAD)
    vertex_count, placements = 20_000, 40
    payload["positions"] = np.zeros((vertex_count, 3), dtype=np.float32)
    payload["normals"] = np.tile([0, 0, 1], (vertex_count, 1))
    payload["indices"] = np.array([0, 1, 2], dtype=np.int32)
    payload["uvChannels"] = []
    payload["weights"] = SkinWeights(np.arange(0, vertex_count * 2 + 1, 2, dtype=np.int32),
                                    np.tile([[0, .25], [1, .75]], (vertex_count, 1)).astype(np.float32))
    asset = MapAssets(bpy.context, Session(payload), .01).skeletal("/Game/Benchmark")
    timings = {}
    for shared in (False, True):
        target = asset if shared else replace(asset, mesh=asset.mesh.copy(), shared_weights=None)
        start = time.perf_counter()
        roots = [place(target, f"Bench_{shared}_{i}") for i in range(placements)]
        timings[shared] = time.perf_counter() - start
        assert len(skin(roots[0]).vertex_groups) == 2
        for root in roots:
            remove(root)
    print(f"SHARED_SKIN_BENCHMARK: {placements} placements, {vertex_count} vertices, "
          f"{vertex_count * 2} influences; repeated writes {timings[False]:.4f}s, "
          f"shared weights {timings[True]:.4f}s ({timings[False] / timings[True]:.1f}x)", flush=True)

addon.unregister()
print("SHARED_SKIN_WEIGHTS_OK: one weight pass, JSON/binary, title/generic sources, independent poses, masks, hooks, no rig, stale-layout rejection")
