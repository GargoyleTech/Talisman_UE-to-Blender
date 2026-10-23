"""Optional additive jaw controls for the flat Rebirth human facial skeleton.

Original bones retain their parents, rest transforms, animation and drivers.
A helper at the face frame becomes the jaw delta in CUSTOM face space; a
BEFORE_FULL Copy Transforms constraint applies that delta to the incoming pose.
Unlike world-space parenting, this does not apply the head transform twice.
"""

from __future__ import annotations

from ...language import strings

from contextlib import contextmanager
import json

import bpy
from mathutils import Matrix


RIG_PROPERTY = "sqex_mouth_rig"
VERSION = 1
FACE = "C_FaceBase_a"
CONTROL = "SQEX_Jaw_CTRL"
DELTA = "SQEX_Jaw_Delta"
CONSTRAINT = "SQEX Mouth Follow"
REQUIRED = (FACE, "C_Chin", "C_Dteeth", "L_Gonion", "R_Gonion", "L_Eye", "R_Eye")
LIPS = tuple(
    [f"C_Dlip{suffix}" for suffix in ("", "in", "out")]
    + [f"{side}_Dlip{part}_{suffix}"
       for side in ("L", "R") for part in ("", "in", "out") for suffix in ("A", "B")]
)
CORNERS = tuple(f"{side}_Dcor{suffix}" for side in ("L", "R") for suffix in ("", "in"))


@contextmanager
def _edit_context(context, armature):
    """Temporarily activate the armature, preserving selection and pose mode."""
    active = context.view_layer.objects.active
    selected = list(context.selected_objects)
    mode = active.mode if active else "OBJECT"
    if mode not in {"OBJECT", "POSE"}:
        raise ValueError("Leave Edit Mode before generating or removing mouth controls.")
    if active and active.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for obj in selected:
        obj.select_set(False)
    armature.select_set(True)
    context.view_layer.objects.active = armature
    try:
        yield
    finally:
        if armature.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        armature.select_set(False)
        for obj in selected:
            obj.select_set(True)
        context.view_layer.objects.active = active
        if active and mode != "OBJECT":
            bpy.ops.object.mode_set(mode=mode)


def _profile(armature):
    bones = armature.data.bones
    missing = [name for name in REQUIRED if name not in bones]
    if missing:
        raise ValueError("Human mouth profile is missing: " + ", ".join(missing))
    candidates = {
        "C_Chin": None, "C_Dteeth": None,
        "C_Tongroot": None, "C_Tongtip": None,
        "L_Gonion": "jaw_side_follow", "R_Gonion": "jaw_side_follow",
        **dict.fromkeys(LIPS, "lip_follow"),
        **dict.fromkeys(CORNERS, "corner_follow"),
    }
    targets = {}
    for name, follow in candidates.items():
        bone = bones.get(name)
        if bone is None:
            continue
        # A nested tongue/lip chain needs a different mapping to avoid applying
        # the same delta twice. Refuse it rather than guessing at inheritance.
        if bone.parent != bones[FACE] or bone.use_connect:
            raise ValueError(f"Mouth bone '{name}' must be an unconnected child of {FACE}.")
        targets[name] = follow
    if not any(name in targets for name in LIPS):
        raise ValueError("Human mouth profile has no recognized lower-lip bones.")

    left, right = (bones[name].head_local for name in ("L_Gonion", "R_Gonion"))
    lateral = left - right
    width = lateral.length
    if width < 1e-6:
        raise ValueError("Cannot estimate a jaw hinge from coincident jaw landmarks.")
    lateral.normalize()
    eye_midpoint = (bones["L_Eye"].head_local + bones["R_Eye"].head_local) * 0.5
    up = eye_midpoint - bones["C_Chin"].head_local
    up -= lateral * up.dot(lateral)
    if up.length < width * 0.1:
        raise ValueError("Cannot estimate the mouth orientation from facial landmarks.")
    up.normalize()
    forward = lateral.cross(up).normalized()
    # Gonion is the jaw angle, not the hinge. Move the provisional hinge back
    # and up, in proportion to this character's jaw width. Artists can refine
    # the new control's pivot in Edit Mode without editing any original bone.
    pivot = (left + right) * 0.5 - forward * width * 0.15 + up * width * 0.2
    matrix = Matrix((lateral, forward, -up)).transposed().to_4x4()
    matrix.translation = pivot
    return targets, matrix, width


def _property(pose_bone, name, default, description):
    pose_bone[name] = default
    pose_bone.id_properties_ui(name).update(
        min=0.0, max=1.0, soft_min=0.0, soft_max=1.0, description=description,
    )


def _add_jaw_constraint(armature, name, follow, manifest):
    constraint = armature.pose.bones[name].constraints.new("COPY_TRANSFORMS")
    constraint.name = CONSTRAINT
    constraint.target = armature
    constraint.subtarget = DELTA
    manifest["constraints"].append([name, constraint.name])
    constraint.owner_space = constraint.target_space = "CUSTOM"
    constraint.space_object = armature
    constraint.space_subtarget = FACE
    constraint.mix_mode = "BEFORE_FULL"
    driver = constraint.driver_add("influence").driver
    driver.type = "SCRIPTED"
    control = armature.pose.bones[CONTROL]
    for prop in ("influence", follow) if follow else ("influence",):
        variable = driver.variables.new()
        variable.name = prop
        variable.type = "SINGLE_PROP"
        variable.targets[0].id = armature
        variable.targets[0].data_path = control.path_from_id() + f'["{prop}"]'
    driver.expression = "influence" + (f" * {follow}" if follow else "")
    return constraint


def _remove_owned(armature, manifest):
    """Remove only recorded generated data; caller owns the active context."""
    for bone_name, constraint_name in manifest.get("constraints", []):
        pose = armature.pose.bones.get(bone_name)
        constraint = pose.constraints.get(constraint_name) if pose else None
        if (constraint and constraint.type == "COPY_TRANSFORMS"
                and constraint.target == armature and constraint.subtarget == DELTA):
            constraint.driver_remove("influence")
            pose.constraints.remove(constraint)
    bpy.ops.object.mode_set(mode="EDIT")
    for name in reversed(manifest.get("bones", [])):
        bone = armature.data.edit_bones.get(name)
        if bone is not None:
            armature.data.edit_bones.remove(bone)
    bpy.ops.object.mode_set(mode="OBJECT")
    for name in manifest.get("collections", []):
        collection = armature.data.collections.get(name)
        if collection and not collection.bones:
            armature.data.collections.remove(collection)
    widget = bpy.data.objects.get(manifest.get("widget", ""))
    if widget and widget.get(RIG_PROPERTY):
        mesh = widget.data
        bpy.data.objects.remove(widget, do_unlink=True)
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)
    # Widget construction can fail before the object exists.
    mesh = bpy.data.meshes.get(manifest.get("widget_mesh", ""))
    if mesh and mesh.users == 0:
        bpy.data.meshes.remove(mesh)


def remove_mouth_rig(context, armature):
    if armature.data.users != 1:
        raise ValueError("Make the armature data single-user before removing mouth controls.")
    raw = armature.get(RIG_PROPERTY)
    if not raw:
        return False
    manifest = json.loads(raw)
    if manifest.get("version") != VERSION:
        raise ValueError("This mouth rig was generated by a different version of the add-on.")
    # Do not remove helpers that now parent user-created or original bones.
    owned = set(manifest["bones"])
    for name in owned:
        bone = armature.data.bones.get(name)
        if bone and any(child.name not in owned for child in bone.children):
            raise ValueError(f"'{name}' has additional children; detach them before removal.")
    from .lip_rig import remove_lip_rig
    remove_lip_rig(context, armature)
    with _edit_context(context, armature):
        _remove_owned(armature, manifest)
        del armature[RIG_PROPERTY]
    return True


def generate_mouth_rig(context, armature, *, create_lip_controls=True):
    """Build the experimental jaw layer; return the number of driven bones.

    Safe to call repeatedly. Unsupported skeletons raise ValueError before
    mutation; construction failures roll back all newly generated data.
    Call after KDI import so neutral-pose validation includes existing drivers.
    """
    if armature.type != "ARMATURE" or armature.data.users != 1:
        raise ValueError("Mouth controls require an armature with single-user data.")
    raw = armature.get(RIG_PROPERTY)
    if raw:
        manifest = json.loads(raw)
        if (manifest.get("version") == VERSION
                and all(name in armature.data.bones for name in manifest["bones"])
                and all(armature.pose.bones.get(name)
                        and armature.pose.bones[name].constraints.get(constraint)
                        for name, constraint in manifest["constraints"])):
            if create_lip_controls:
                from .lip_rig import generate_lip_rig
                generate_lip_rig(context, armature)
            return len(manifest["constraints"])
        raise ValueError("Existing mouth controls are incomplete; remove them before rebuilding.")
    targets, jaw_matrix, width = _profile(armature)
    for name in (CONTROL, DELTA):
        if name in armature.data.bones:
            raise ValueError(f"Reserved mouth bone '{name}' already exists.")
    for name in targets:
        if armature.pose.bones[name].constraints.get(CONSTRAINT):
            raise ValueError(f"Reserved mouth constraint already exists on '{name}'.")

    context.view_layer.update()
    incoming = {bone.name: bone.matrix.copy() for bone in armature.pose.bones}
    manifest = {"version": VERSION, "bones": [], "constraints": [], "collections": []}
    with _edit_context(context, armature):
        try:
            bpy.ops.object.mode_set(mode="EDIT")
            bones = armature.data.edit_bones
            control = bones.new(CONTROL)
            manifest["bones"].append(control.name)
            control.length = width * 0.8
            control.matrix = jaw_matrix
            control.parent = bones[FACE]
            control.use_deform = False
            delta = bones.new(DELTA)
            manifest["bones"].append(delta.name)
            delta.length = width * 0.1
            delta.matrix = bones[FACE].matrix.copy()
            delta.parent = control
            delta.use_deform = False
            bpy.ops.object.mode_set(mode="OBJECT")

            for label, bone_name, visible in (
                ("Mouth Controls", CONTROL, True), ("Mouth Helpers", DELTA, False),
            ):
                collection = armature.data.collections.new(label)
                manifest["collections"].append(collection.name)
                bone = armature.data.bones[bone_name]
                for previous in list(bone.collections):
                    previous.unassign(bone)
                collection.assign(bone)
                collection.is_visible = visible

            control = armature.pose.bones[CONTROL]
            control.rotation_mode = "XYZ"
            control.lock_rotation = (False, True, True)
            control.lock_location = (True, True, True)
            control.lock_scale = (True, True, True)
            control.bone.color.palette = "THEME04"
            _property(control, "influence", 1.0, strings.SCENE_TOOLS_INFLUENCE)
            _property(control, "lip_follow", 0.9, strings.SCENE_TOOLS_LIP_FOLLOW)
            _property(control, "corner_follow", 0.35, strings.SCENE_TOOLS_CORNER_FOLLOW)
            _property(control, "jaw_side_follow", 0.35, strings.SCENE_TOOLS_JAW_SIDE_FOLLOW)

            widget_mesh = bpy.data.meshes.new(f"WGT_{armature.name}_Jaw")
            manifest["widget_mesh"] = widget_mesh.name
            # A broad handle beneath the chin; its geometry is in control space.
            chin = jaw_matrix.inverted() @ armature.data.bones["C_Chin"].head_local
            y, z = chin.y / width, chin.z / width + 0.18
            widget_mesh.from_pydata(
                [(-0.55, y - 0.12, z), (0.55, y - 0.12, z),
                 (0.55, y + 0.12, z), (-0.55, y + 0.12, z)],
                [(0, 1), (1, 2), (2, 3), (3, 0)], [],
            )
            widget = bpy.data.objects.new(widget_mesh.name, widget_mesh)
            manifest["widget"] = widget.name
            widget[RIG_PROPERTY] = VERSION
            context.collection.objects.link(widget)
            widget.hide_render = True
            widget.hide_set(True)
            control.custom_shape = widget
            control.use_custom_shape_bone_size = False
            control.custom_shape_scale_xyz = (width,) * 3

            for name, follow in targets.items():
                _add_jaw_constraint(armature, name, follow, manifest)

            armature.update_tag()
            context.view_layer.update()
            # Never accept a setup that shifts the current pose at zero opening.
            for name, matrix in incoming.items():
                result = armature.pose.bones[name].matrix
                location_error = (result.translation - matrix.translation).length
                basis_error = max(abs(result[r][c] - matrix[r][c]) for r in range(3) for c in range(3))
                if location_error > width * 1e-4 or basis_error > 1e-4:
                    raise ValueError(f"Mouth setup changed the neutral pose of '{name}'; setup was removed.")
            armature[RIG_PROPERTY] = json.dumps(manifest)
        except Exception:
            if armature.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            _remove_owned(armature, manifest)
            raise
    if create_lip_controls:
        try:
            from .lip_rig import generate_lip_rig
            generate_lip_rig(context, armature)
        except Exception:
            remove_mouth_rig(context, armature)
            raise
    return len(targets)
