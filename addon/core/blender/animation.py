"""Action channels, sampling and timing shared by all animation importers."""

from __future__ import annotations

import math
from bisect import bisect_left
from typing import Iterable

import bpy
from mathutils import Quaternion, Vector

SKELETON_ASSET_PATH_PROPERTY = "sqex_skeleton_asset_path"


def scene_fps(scene) -> float:
    """Effective frame rate, respecting a fractional fps_base."""
    return float(scene.render.fps) / float(scene.render.fps_base or 1.0)


def _selected_armature_skeleton_path(armature: bpy.types.Object) -> str | None:
    """Get the source Skeleton path recorded by a package armature or bound mesh."""
    direct_path = armature.get(SKELETON_ASSET_PATH_PROPERTY)
    if isinstance(direct_path, str) and direct_path.strip():
        return direct_path

    # Older package imports did not tag their armature.  A bound package mesh
    # still carries the linked Skeleton path, which lets those existing scenes
    # use the picker without reimporting their character.
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        if not any(
            modifier.type == "ARMATURE" and modifier.object == armature
            for modifier in obj.modifiers
        ):
            continue
        linked_path = obj.get("sqex_linked_skeleton_path")
        if isinstance(linked_path, str) and linked_path.strip():
            return linked_path
    return None


def _vector(value: Iterable[float], fallback: tuple[float, float, float]) -> Vector:
    parts = tuple(float(part) for part in value)
    return Vector(parts[:3] if len(parts) >= 3 else fallback)


def _action_curves(action: bpy.types.Action, target: bpy.types.Object):
    """Return a curve factory for the action, plus the slot that owns the curves.

    Blender 4.4 moved an Action's curves into a slot/layer/strip channelbag and
    5.0 dropped the old ``Action.fcurves`` shortcut, so build the channelbag when
    the shortcut is gone.  The two collections name their group argument
    differently and both refuse positional arguments, hence the factory.
    """
    legacy = getattr(action, "fcurves", None)
    if legacy is not None:

        def new_curve(data_path, axis, group):
            return legacy.new(data_path, index=axis, action_group=group)

        return new_curve, None

    slot = action.slots.new(id_type=target.id_type, name=target.name)
    strip = action.layers.new("Layer").strips.new(type="KEYFRAME")
    curves = strip.channelbag(slot, ensure=True).fcurves

    def new_curve(data_path, axis, group):
        return curves.new(data_path, index=axis, group_name=group)

    return new_curve, slot


def _insert_keys(
    new_curve,
    bone_name: str,
    data_path: str,
    values: list[tuple[float, ...]],
    source_frames: list[float],
    frame_scale: float,
    start_frame: float,
) -> int:
    if not values:
        return 0
    dimensions = len(values[0])
    if not source_frames:
        source_frames = [0.0] * len(values)
    count = min(len(values), len(source_frames))
    for axis in range(dimensions):
        # ACL clips are uniformly sampled, but a channel can still be constant
        # for its whole duration.  Retaining its per-sample copies adds work to
        # Blender without changing evaluation.
        first_value = values[0][axis]
        is_constant = all(
            math.isclose(value[axis], first_value, rel_tol=1e-7, abs_tol=1e-6)
            for value in values[:count]
        )
        indices = (0,) if is_constant else range(count)
        curve = new_curve(data_path, axis, bone_name)
        points = curve.keyframe_points
        points.add(len(indices))
        points.foreach_set(
            "co",
            [
                coordinate
                for index in indices
                for coordinate in (
                    start_frame + source_frames[index] * frame_scale,
                    values[index][axis],
                )
            ],
        )
        for point in points:
            point.interpolation = "CONSTANT" if is_constant else "LINEAR"
        curve.update()
    return sum(
        1
        if all(
            math.isclose(value[axis], values[0][axis], rel_tol=1e-7, abs_tol=1e-6)
            for value in values[:count]
        )
        else count
        for axis in range(dimensions)
    )


def _key_times(values: list, frames: list[float], num_frames: int) -> list[float]:
    if not values:
        return []
    if len(frames) == len(values):
        return [float(frame) for frame in frames]
    if len(values) == 1:
        return [0.0]
    last_frame = max(1, num_frames - 1)
    return [index * last_frame / (len(values) - 1) for index in range(len(values))]


def _vector_sampler(values: list, frames: list[float], default: Vector):
    """Convert channel values once and sample them with a binary lookup."""
    if not values:
        return lambda _frame: default.copy()
    keys = [_vector(value, tuple(default)) for value in values]

    def sample(frame: float) -> Vector:
        index = bisect_left(frames, frame)
        if index <= 0:
            return keys[0]
        if index >= len(keys):
            return keys[-1]
        span = frames[index] - frames[index - 1]
        fraction = 0.0 if span <= 0 else (frame - frames[index - 1]) / span
        return keys[index - 1].lerp(keys[index], fraction)

    return sample


def _ue_quaternion_sampler(
    values: list,
    frames: list[float],
    default: tuple[float, float, float, float],
):
    """Convert quaternion keys once and sample them with a binary lookup."""

    def as_ue_quaternion(value) -> Quaternion:
        parts = tuple(float(part) for part in value)
        if len(parts) < 4:
            parts = default
        return Quaternion((parts[3], parts[0], parts[1], parts[2]))

    if not values:
        return lambda _frame: default
    keys = [as_ue_quaternion(value) for value in values]

    def sample(frame: float) -> tuple[float, float, float, float]:
        index = bisect_left(frames, frame)
        if index <= 0:
            result = keys[0]
        elif index >= len(keys):
            result = keys[-1]
        else:
            span = frames[index] - frames[index - 1]
            fraction = 0.0 if span <= 0 else (frame - frames[index - 1]) / span
            result = keys[index - 1].slerp(keys[index], fraction)
        return (result.x, result.y, result.z, result.w)

    return sample
