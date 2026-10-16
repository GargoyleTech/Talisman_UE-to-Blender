"""Search and apply Rebirth animation sequences to a selected package armature."""

from __future__ import annotations

import math
from typing import Iterable

import bpy
from mathutils import Matrix, Quaternion, Vector

from ....core.blender.animation import (
    _selected_armature_skeleton_path, _vector, _action_curves, _insert_keys,
    _key_times, _vector_sampler, _ue_quaternion_sampler,
)
from . import packages as game_packages
from ....core.blender import skeletons as skeleton_importer
from ... import package_browser
from ...conventional_animation import make_animation_importer
from ..profile import PROFILE


_ANIMATION_BROWSER = package_browser.make_state(
    "compatible AnimSequence assets",
    initial_directory="End/Content",
    file_icon="ARMATURE_DATA",
)


def _search_matching_animations(_self, _context, edit_text):
    return game_packages._search_virtual_animations(_self, _context, edit_text)


def _ue_location(value: Iterable[float]) -> Vector:
    """Centimetres in UE's left-handed frame to metres in Blender's."""
    location = _vector(value, (0.0, 0.0, 0.0)) * 0.01
    location.y = -location.y
    return location


def _quaternion(value: Iterable[float]) -> Quaternion:
    parts = tuple(float(part) for part in value)
    if len(parts) < 4:
        return Quaternion((1.0, 0.0, 0.0, 0.0))
    # CUE4Parse serializes FQuat as UE X/Y/Z/W.  This is the same mirror
    # conversion used for the imported Skeleton's bind transforms.
    result = Quaternion((parts[3], -parts[0], parts[1], -parts[2]))
    result.normalize()
    return result


# skeleton/importer.py frames each edit bone by aiming Blender's +Y down Unreal's
# local +X, aligning +Z to Unreal's +Z, then adding a 90 degree roll.  The net
# effect is a single constant change of basis: a package bone's ``matrix_local``
# equals the UE-converted armature-space bind matrix that the importer composes,
# times this rotation.  Derived by replaying that framing on synthetic bind
# matrices; identical for every bone to within 2e-6.
DISPLAY_CORRECTION = Matrix((
    (0.0, 1.0, 0.0, 0.0),
    (0.0, 0.0, -1.0, 0.0),
    (-1.0, 0.0, 0.0, 0.0),
    (0.0, 0.0, 0.0, 1.0),
))
DISPLAY_CORRECTION_INVERSE = DISPLAY_CORRECTION.inverted()

# With UE axis ordering preserved, the package bone's local +X still points
# down Blender's display-bone +Y and its local +Z stays the display +Z.  The
# Blender-oriented convention below adds a further +90-degree roll to this
# basis; see ``_build_edit_bones`` in ``core.blender.skeletons``.
PRESERVED_AXIS_CORRECTION = Matrix((
    (0.0, 1.0, 0.0, 0.0),
    (-1.0, 0.0, 0.0, 0.0),
    (0.0, 0.0, 1.0, 0.0),
    (0.0, 0.0, 0.0, 1.0),
))
PRESERVED_AXIS_CORRECTION_INVERSE = PRESERVED_AXIS_CORRECTION.inverted()

# The root track ("Trans") is not a bone-parented transform: its translation is
# the actor's world placement (thousands of centimetres from the origin for a
# cutscene clip, zero for a local action clip).  It is a component-to-world
# placement, so it does not carry the 90 degree display roll that
# skeleton/importer.py adds to each *bone's* frame, and applying that roll to it
# lays the whole character on its side -- hip-to-head pointing down world +X
# instead of +Z.  Undoing the roll is a -90 degree turn about the bone's own Y.
#
# That still left the character yawed 90 degrees, because the track's rotation is
# not neutral either: its rest value is 120 degrees about UE (-1, 1, -1)/sqrt(3)
# -- the value every frame of a clip without root motion carries, and the value
# root-motion clips animate away from.  A correct conversion has to send that
# rest value back to the bone's own rest frame, leaving an identity pose basis
# for a clip that does not move the root.  Solving ``R_rest @ C == matrix_local``
# for a Trans bone whose bind is the identity (so ``matrix_local`` is exactly
# DISPLAY_CORRECTION) gives the -90 Y turn above followed by a further 90 degrees
# about the bone's own X -- the axis that, for this bone, is world -Z, which is
# why the error read as a pure yaw with the character otherwise upright.
ROOT_TRACK_CORRECTION = (
    Matrix.Rotation(math.radians(-90.0), 4, "Y")
    @ Matrix.Rotation(math.radians(90.0), 4, "X")
)
ROOT_DISPLAY_CORRECTION = DISPLAY_CORRECTION @ ROOT_TRACK_CORRECTION
PRESERVED_ROOT_DISPLAY_CORRECTION = (
    PRESERVED_AXIS_CORRECTION @ ROOT_TRACK_CORRECTION
)

# Largest per-element difference tolerated between a bone's rest matrix and the
# bind pose the clip was authored against.  Connected bones nudge a parent's tail
# onto the child head, so an exact match is not expected.
REST_CONVENTION_TOLERANCE = 0.01


def _rest_local_matrix(bone: bpy.types.Bone) -> Matrix:
    if bone.parent is None:
        return bone.matrix_local.copy()
    return bone.parent.matrix_local.inverted_safe() @ bone.matrix_local


def _blender_basis_values(
        translation: Iterable[float],
        rotation: Iterable[float],
        scale: Iterable[float],
        basis_prefix: Matrix,
        display_target: Matrix,
) -> tuple[Vector, Quaternion, Vector]:
    """Convert a UE local track transform into this add-on's bone display basis.

    Write ``L`` for a parent-relative UE transform carried into Blender axes and
    ``D`` for :data:`DISPLAY_CORRECTION`.  A package bone's rest matrix is
    ``B_bind @ D`` and its posed matrix must be ``B_anim @ D``, so the
    parent-relative rest is ``D^-1 @ L_bind @ D``, the parent-relative pose is
    ``D^-1 @ L_anim @ D``, and

        matrix_basis = (D^-1 @ L_bind @ D)^-1 @ (D^-1 @ L_anim @ D)
                     = D^-1 @ L_bind^-1 @ L_anim @ D

    which is what this returns.  The same expression covers root bones, where
    both rest and pose instead pick up the importer's -Y-forward rotation and it
    cancels between them.

    Conjugating by ``D`` is the step that was missing: without it the UE delta
    gets applied in the display frame rather than being carried into it, which
    leaves poses that look plausible in scale but are rotated by ~100 degrees.
    """
    source_matrix = Matrix.LocRotScale(
        _ue_location(translation),
        _quaternion(rotation),
        _vector(scale, (1.0, 1.0, 1.0)),
    )
    basis = basis_prefix @ source_matrix @ display_target
    return basis.decompose()


def _display_corrections_for_armature(
        armature: bpy.types.Object,
) -> tuple[Matrix, Matrix, Matrix]:
    """Return the bone-frame corrections recorded on a package armature.

    Armatures created before axis ordering was recorded use the established
    Blender-oriented display roll.  That is also the safe fallback for rigs
    made elsewhere, whose bone frame cannot be inferred reliably.
    """
    if armature.get(skeleton_importer.AXIS_ORDER_PROPERTY) == skeleton_importer.AXIS_ORDER_UNREAL:
        return (
            PRESERVED_AXIS_CORRECTION,
            PRESERVED_AXIS_CORRECTION_INVERSE,
            PRESERVED_ROOT_DISPLAY_CORRECTION,
        )
    return (
        DISPLAY_CORRECTION,
        DISPLAY_CORRECTION_INVERSE,
        ROOT_DISPLAY_CORRECTION,
    )


def _rest_convention_error(
        bone: bpy.types.Bone,
        bind_matrix: Matrix,
        forward_rotation: Matrix,
        display_correction: Matrix = DISPLAY_CORRECTION,
) -> float:
    """How far this bone's rest pose is from the UE bind pose the clip assumes.

    Large values mean the armature was not built by this add-on's package
    importer, so the keys will land somewhere other than the animation intends.

    A root bone's rest is measured against the armature origin rather than a
    parent, so it also carries the importer's forward-axis rotation -- hence
    ``forward_rotation``.  Checking roots matters: the root is the one bone whose
    rest and animated frames are not related by ``DISPLAY_CORRECTION`` alone.
    """
    display_correction_inverse = display_correction.inverted_safe()
    rest = _rest_local_matrix(bone)
    if bone.parent is None:
        expected = forward_rotation @ bind_matrix @ display_correction
    else:
        expected = (
            display_correction_inverse @ bind_matrix @ display_correction
        )
    return max(abs(a - b) for row_a, row_b in zip(expected, rest) for a, b in zip(row_a, row_b))


def import_animation_asset(
        armature: bpy.types.Object,
        virtual_path: str,
        animation: dict,
        *,
        start_frame: float = 1.0,
        replace_current_action: bool = False,
        use_fake_user: bool = False,
        scene=None,
) -> tuple[bpy.types.Action, int, int, int, float]:
    """Create a tagged Action from one decoded package AnimSequence.

    This is deliberately independent of an operator so package cutscenes can
    load their own missing clips while the manual animation button retains the
    same conversion path.
    """
    if armature.type != 'ARMATURE':
        raise ValueError("Animation targets must be armature objects.")
    skeleton_path = _selected_armature_skeleton_path(armature)
    if not skeleton_path:
        raise ValueError(f"'{armature.name}' has no Rebirth Skeleton source.")
    scene = scene or bpy.context.scene
    source_fps = float(animation.get("framesPerSecond") or 0.0)
    if source_fps <= 0.0:
        source_fps = 30.0
    scene_fps = scene.render.fps / scene.render.fps_base
    frame_scale = scene_fps / source_fps
    action_name = f"{armature.name} | {animation.get('name') or virtual_path.rsplit('/', 1)[-1]}"
    action = bpy.data.actions.new(action_name)
    action.use_fake_user = use_fake_user
    new_curve, action_slot = _action_curves(action, armature)
    action["sqex_animation_virtual_path"] = virtual_path
    action["sqex_skeleton_asset_path"] = skeleton_path
    action["sqex_axis_order"] = armature.get(
        skeleton_importer.AXIS_ORDER_PROPERTY,
        skeleton_importer.AXIS_ORDER_BLENDER,
    )
    action["ff7r_source_fps"] = source_fps
    action["ff7r_source_duration"] = float(animation.get("duration") or 0.0)

    keyed_bones = 0
    skipped_bones = 0
    key_count = 0
    worst_rest_error = 0.0
    forward_rotation = (
        skeleton_importer.Y_FORWARD_ROTATION
        if skeleton_importer.armature_face_forward(armature) == skeleton_importer.FACE_FORWARD_BLENDER
        else Matrix.Identity(4)
    )
    display_correction, display_correction_inverse, root_display_correction = (
        _display_corrections_for_armature(armature)
    )
    for track in animation.get("tracks") or []:
        bone_name = track.get("boneName")
        bone = armature.data.bones.get(bone_name) if bone_name else None
        if bone is None:
            skipped_bones += 1
            continue
        source_translations = list(track.get("translations") or [])
        source_rotations = list(track.get("rotations") or [])
        source_scales = list(track.get("scales") or [])
        num_frames = int(animation.get("numFrames") or 1)
        translation_frames = _key_times(
            source_translations, list(track.get("translationFrames") or []), num_frames
        )
        rotation_frames = _key_times(
            source_rotations, list(track.get("rotationFrames") or []), num_frames
        )
        scale_frames = _key_times(
            source_scales, list(track.get("scaleFrames") or []), num_frames
        )
        source_frames = sorted(set(translation_frames + rotation_frames + scale_frames))
        if not source_frames:
            continue
        bind_translation = _vector(track.get("bindTranslation") or (), (0.0, 0.0, 0.0))
        bind_rotation = tuple(track.get("bindRotation") or (0.0, 0.0, 0.0, 1.0))
        bind_scale = _vector(track.get("bindScale") or (), (1.0, 1.0, 1.0))
        sample_translation = _vector_sampler(
            source_translations, translation_frames, bind_translation
        )
        sample_rotation = _ue_quaternion_sampler(
            source_rotations, rotation_frames, bind_rotation
        )
        sample_scale = _vector_sampler(source_scales, scale_frames, bind_scale)
        bind_matrix = Matrix.LocRotScale(
            _ue_location(bind_translation), _quaternion(bind_rotation), bind_scale
        )
        basis_prefix = display_correction_inverse @ bind_matrix.inverted_safe()
        display_target = (
            root_display_correction if bone.parent is None else display_correction
        )
        worst_rest_error = max(worst_rest_error, _rest_convention_error(
            bone,
            bind_matrix,
            forward_rotation,
            display_correction,
        ))
        bases = [
            _blender_basis_values(
                sample_translation(frame),
                sample_rotation(frame),
                sample_scale(frame),
                basis_prefix,
                display_target,
            )
            for frame in source_frames
        ]
        translations = [tuple(basis[0]) for basis in bases]
        rotations = [tuple(basis[1]) for basis in bases]
        scales = [tuple(basis[2]) for basis in bases]
        path = f'pose.bones["{bone.name}"]'
        key_count += _insert_keys(new_curve, bone.name, path + ".location", translations,
                                  source_frames, frame_scale, start_frame)
        key_count += _insert_keys(new_curve, bone.name, path + ".rotation_quaternion", rotations,
                                  source_frames, frame_scale, start_frame)
        key_count += _insert_keys(new_curve, bone.name, path + ".scale", scales,
                                  source_frames, frame_scale, start_frame)
        keyed_bones += 1

    if not key_count:
        bpy.data.actions.remove(action)
        raise ValueError("No animation tracks matched bones on the selected armature.")
    action.frame_start = start_frame
    action.frame_end = start_frame + max(0.0, float(animation.get("duration") or 0.0) * scene_fps)
    if replace_current_action:
        animation_data = armature.animation_data_create()
        animation_data.action = action
        if action_slot is not None:
            animation_data.action_slot = action_slot
    return action, keyed_bones, key_count, skipped_bones, worst_rest_error


def _configured_paths(context):
    preferences = game_packages._preferences(context)
    if preferences is None:
        raise RuntimeError("The add-on preferences are unavailable.")
    return PROFILE.paths_from_preferences(preferences, bpy.path.abspath)


def _compatible_paths(context, armature):
    skeleton_path = _selected_armature_skeleton_path(armature)
    if not skeleton_path:
        raise ValueError("The selected armature has no package Skeleton source. Import a package Skeleton first.")
    paths = _configured_paths(context)
    return game_packages.refresh_animation_index(
        paths.install_root, paths.oodle_dll, paths.usmap_path, skeleton_path,
        profile=PROFILE, aes_key=paths.aes_key,
    )


FF7R_REBIRTH_OT_apply_animation_game_packages = make_animation_importer(
    class_name="FF7R_REBIRTH_OT_apply_animation_game_packages", module_name=__name__,
    bl_idname="object.ff7r_rebirth_apply_animation_game_packages", game_name="Rebirth",
    profile=PROFILE, configured_paths=_configured_paths, compatible_paths=_compatible_paths,
    import_animation=import_animation_asset, browser=_ANIMATION_BROWSER,
    rest_tolerance=REST_CONVENTION_TOLERANCE,
)


CLASSES = (FF7R_REBIRTH_OT_apply_animation_game_packages,)
