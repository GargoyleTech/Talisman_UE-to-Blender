"""Timeline helpers for Unreal cutscene imports."""

from __future__ import annotations

import bpy


ARMATURE_ACTION_FPS: float = 30.0


def scene_fps(scene) -> float:
    """Return the scene's effective frame rate, respecting fps_base."""
    fps = float(scene.render.fps)
    fps_base = float(scene.render.fps_base) if scene.render.fps_base else 1.0
    return fps / fps_base


def clear_scene_cameras(scene) -> int:
    """Remove all camera objects from *scene* and return the number removed."""
    cameras = [obj for obj in scene.objects if obj.type == "CAMERA"]
    for obj in cameras:
        bpy.data.objects.remove(obj, do_unlink=True)
    return len(cameras)


def ue_tick_to_frame(tick: int, tick_num: int, display_rate: int) -> float:
    """Convert a UE sequencer tick to a Blender frame number."""
    return tick * display_rate / tick_num


def source_to_scene_time_scale(
        display_rate: float | int,
        source_display_rate: float | int | None,
) -> float:
    """Scale authored source frames onto the Blender scene display rate."""
    if not source_display_rate:
        return 1.0
    return float(display_rate) / float(source_display_rate)


def find_loaded_action_by_name(action_name: str):
    """Return a currently loaded action, including Blender duplicate suffixes."""
    action = bpy.data.actions.get(action_name)
    if action is not None:
        return action
    matches = sorted(
        (action for action in bpy.data.actions
         if action.name == action_name or action.name.startswith(f"{action_name}.")),
        key=lambda action: action.name,
    )
    return matches[0] if matches else None
