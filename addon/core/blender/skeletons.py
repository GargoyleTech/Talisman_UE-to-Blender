"""Build a Blender armature from package-decoded Skeleton/SkeletalMesh data.

Bone translation/rotation values are UE-space (centimeters, left-handed quaternions),
parent-relative, matching ``FTransform``. See ``ue_bone_transform_to_blender`` below
for the coordinate conversion and why it differs from the one in
``json/map_import.py``.
"""

from __future__ import annotations

import json
import math
from typing import Any

import bpy
from mathutils import Matrix, Quaternion, Vector

from ...formats.ue_map.map_import import location_from_relative, rotation_from_relative

MIN_BONE_LENGTH = 0.0005
DEGENERATE_LENGTH = 1.0e-5
DEFAULT_BONE_LENGTH = 0.05
LEAF_LENGTH_RATIO = 0.5

# The artist-facing limbal controller is placed one international foot in front
# of the character's eyes.  Package skeletons use Blender units after their
# centimeter-to-unit import scale, so this is deliberately a scene-unit value
# rather than a source-data distance.
LIMBAL_BONE_NAME = "C_Limbal"
# The root of the KineDriver helper-bone subtree: pure rigging machinery that
# drives shape-key/material parameters via bone transforms, not mesh skinning.
# It and every descendant must never deform geometry.
KDI_ROOT_BONE_NAME = "C_KDIRoot"
FACE_BASE_BONE_NAME = "C_FaceBase_a"
FACE_BASE_CHILD_WIDGET_NAME = "WGT_Cube"
LIMBAL_DISTANCE = 0.3048
EYE_BONE_NAMES: frozenset[str] = frozenset(("l_eye", "r_eye"))

# A bone's real successor in the skeleton chain sits exactly along its +X (measured
# at 0.00 degrees throughout Cloud's skeleton); accessory children -- cloth, armour,
# prop holders -- are all >= 3 degrees off. A small tolerance therefore separates
# "the next bone in the chain" from "something bolted onto this bone".
ALIGNED_CHILD_DEGREES = 5.0
ALIGNED_CHILD_COSINE = math.cos(math.radians(ALIGNED_CHILD_DEGREES))

# Per-bone maximum display length, chosen by name suffix. These bones are purely
# functional rigging machinery the user is not meant to grab, so they are kept
# short to cut visual clutter when the whole armature is visible. Matched
# case-insensitively against the bone name, longest suffix first.
BONE_LENGTH_CLAMPS: tuple[tuple[str, float], ...] = (
    ("Kdi", 0.02),
)

# KDI helper bones and "_Spo" pose-space helpers exist to be moved independently
# by KineDriver's generated drivers -- that is their entire purpose. Blender's
# "connected" mode locks a bone's head to its parent's tail, which would fight
# any driver trying to translate it. These must never be connected, regardless
# of the connect_bones option or how close they measure to the threshold.
NEVER_CONNECT_SUFFIXES: tuple[str, ...] = ("Kdi", "Spo")

# How close a bone's head must sit to its parent's (cosmetic, computed) tail before
# "connected" mode is allowed to snap them together. This is deliberately tight: a
# bone whose length was set to reach a single dominant aligned child (see the tail
# loop) lands its tail almost exactly on that child's head, so real chain joins are
# well inside this threshold; anything wider risks visibly relocating a head that
# was verified against the game data.
CONNECT_DISTANCE_THRESHOLD = 0.0001

# ``face_y_forward`` rotates the whole finished skeleton -90 degrees about Z, so a
# root bone originally aimed down Blender's +X (Unreal's own forward axis, once
# mirrored) ends up facing -Y instead (Blender's own forward convention). It is applied once to each root bone's
# armature-space matrix -- every descendant is composed from its parent's matrix
# (see ``_build_edit_bones``), so the rotation propagates through the whole
# hierarchy for free without needing a separate per-bone quaternion conversion.
Y_FORWARD_ROTATION = Matrix.Rotation(math.radians(-90.0), 4, "Z")

# The two forward-axis choices, and the armature property recording which one an
# import used. Defined here rather than next to the operator's enum so the
# animation importer can read the choice back without importing the UI module,
# and so the stored value and the enum value can never drift apart.
FACE_FORWARD_UNREAL = "UNREAL"
FACE_FORWARD_BLENDER = "BLENDER"
FACE_FORWARD_PROPERTY = "sqex_face_forward"
AXIS_ORDER_UNREAL = "UNREAL"
AXIS_ORDER_BLENDER = "BLENDER"
AXIS_ORDER_PROPERTY = "sqex_axis_order"
# Older "UNREAL" rigs still received the X-to-Y display correction. Keep an
# explicit frame marker so animation/KDI imports can distinguish saved rigs.
BONE_AXIS_FRAME_PROPERTY = "sqex_bone_axis_frame"
BONE_AXIS_FRAME_SOURCE = "SOURCE"
BONE_AXIS_FRAME_BLENDER = "BLENDER"


def preserves_source_bone_axes(armature_obj: Any) -> bool:
    if armature_obj is None:
        return False
    return armature_obj.get(
        BONE_AXIS_FRAME_PROPERTY, armature_obj.data.get(BONE_AXIS_FRAME_PROPERTY)
    ) == BONE_AXIS_FRAME_SOURCE


def armature_face_forward(armature_obj: Any) -> str:
    """Return the forward axis recorded on an imported armature."""
    return armature_obj[FACE_FORWARD_PROPERTY]


def apply_naive_ik(armature_obj: bpy.types.Object) -> tuple[int, int]:
    """Compatibility entry point for the optional target-and-pole IK generator."""
    from .ik_rig import generate_limb_ik
    return generate_limb_ik(armature_obj)


def max_length_for_bone(bone_name: str) -> float | None:
    """Return the display-length cap for this bone, or None if it is unclamped."""
    lowered = bone_name.casefold()
    for suffix, limit in BONE_LENGTH_CLAMPS:
        if lowered.endswith(suffix.casefold()):
            return limit
    return None


def allows_connect(bone_name: str) -> bool:
    """Whether this bone may ever be switched into Blender's "connected" mode."""
    lowered = bone_name.casefold()
    return not any(lowered.endswith(suffix.casefold()) for suffix in NEVER_CONNECT_SUFFIXES)


def ue_bone_transform_to_blender(
        translation: tuple[float, float, float],
        rotation: tuple[float, float, float, float],
        scale_factor: float,
        bone_scale: tuple[float, float, float] | None = None,
) -> Matrix:
    """Convert one parent-relative UE bone FTransform to a Blender matrix.

    UE (left-handed, Z-up) -> Blender (right-handed, Z-up) is the mirror
    M = diag(1, -1, 1). A transform is carried across by the similarity M T M^-1,
    which negates Y on a translation, and takes a quaternion (X, Y, Z, W) to
    (W, -X, Y, -Z) -- note it is X and Z that flip, not Y and Z.

    This deliberately differs from ``json/map_import.py``'s
    ``rotation_from_quaternion``, which negates Y and Z. The two forms agree
    exactly whenever X = Y = 0, i.e. for yaw-only rotations about Z -- which is
    what placed level actors overwhelmingly use, so the difference never
    surfaced there. Bone bind poses carry arbitrary 3D rotations, where only the
    form below is correct: it reproduces umodel's reference hierarchy for
    PC0000_00 to within 0.05mm across all 557 bones, whereas negating Y and Z
    builds the skeleton upside down.
    """
    tx, ty, tz = translation
    rx, ry, rz, rw = rotation
    location = Vector((tx * scale_factor, -ty * scale_factor, tz * scale_factor))
    orientation = Quaternion((rw, -rx, ry, -rz))
    orientation.normalize()
    result = Matrix.Translation(location) @ orientation.to_matrix().to_4x4()
    if bone_scale is not None:
        result = result @ Matrix.Diagonal((*bone_scale, 1.0))
    return result


def _bones_from_gargoyle(data: dict[str, Any]) -> list[dict[str, Any]]:
    bones = []
    for bone in data.get("bones") or []:
        translation = bone.get("translation") or (0.0, 0.0, 0.0)
        rotation = bone.get("rotation") or (0.0, 0.0, 0.0, 1.0)
        bones.append({
            "name": bone["name"],
            "parent_index": int(bone.get("parentIndex", -1)),
            "translation": tuple(translation),
            "rotation": tuple(rotation),
            "scale": tuple(bone.get("scale") or (1.0, 1.0, 1.0)),
        })
    return bones


def build_armature_from_bones(
        context: Any,
        name: str,
        bones: list[dict[str, Any]],
        sockets: list[dict[str, Any]] | None = None,
        scale_factor: float = 0.01,
        connect_bones: bool = False,
        create_socket_empties: bool = True,
        create_socket_bones: bool = False,
        setup_naive_ik: bool = False,
        face_y_forward: bool = False,
        create_limbal_bone: bool = False,
        preserve_ue_axis_order: bool = False,
        game_features: bool = True,
) -> bpy.types.Object:
    """Create a new armature object with one edit-bone per entry in `bones`.

    Each bone's head is placed by composing its parent-relative UE bind-pose
    transform down the hierarchy (bones must list parents before children,
    which FinalRefBoneInfo/the gargoyle always guarantee).

    The game data carries no notion of bone length, so lengths are derived from
    the children and leaf bones take a fraction of their parent's length.
    ``preserve_ue_axis_order`` keeps the converted source rotation intact: UE's
    chain continues along local X while Blender draws the bone along local Y.
    Otherwise the display frame is reoriented to point Blender Y down UE X.
    Neither choice changes the chain used to place children.

    ``connect_bones`` opts a bone into Blender's "connected" mode (no visible gap
    to its parent) whenever its head already sits within ``CONNECT_DISTANCE_THRESHOLD``
    of the parent's tail. The parent's tail is moved to the imported head first, so
    enabling connected mode never changes the child's 1:1 game-space position.
    KDI/"_Spo" bones are always excluded from this regardless of distance -- see
    ``allows_connect`` -- since KineDriver needs to translate them independently
    of their parent.

    ``create_socket_empties`` materializes each socket as a bone-parented Empty.
    ``create_socket_bones`` instead adds the sockets as non-deforming bones in a
    hidden ``Sockets`` bone collection.  Socket bones are preferable for package
    UMAP imports because their transform is part of the armature, not a separate
    scene object.  The raw socket data is stored on the armature either way.

    ``setup_naive_ik`` additionally calls ``apply_naive_ik`` -- see there for
    what it does.

    ``face_y_forward`` rotates the whole armature -90 degrees about Z so it
    faces Blender's -Y axis instead of the default +X -- see
    ``Y_FORWARD_ROTATION`` above.

    ``create_limbal_bone`` adds the non-deforming ``C_Limbal`` controller when
    the hierarchy contains ``L_Eye`` or ``R_Eye``.  It is placed from the
    character's forward convention, never from the eye bone's local axes.
    """

    if not bones:
        raise ValueError("No bones to import.")

    armature_data = bpy.data.armatures.new(f"{name}_Skeleton")
    armature_obj = bpy.data.objects.new(name, armature_data)
    context.collection.objects.link(armature_obj)
    for obj in context.selected_objects:
        obj.select_set(False)
    context.view_layer.objects.active = armature_obj
    armature_obj.select_set(True)

    bpy.ops.object.mode_set(mode="EDIT")
    try:
        armature_space = _build_edit_bones(
            armature_data, bones, scale_factor, connect_bones, face_y_forward,
            preserve_ue_axis_order, game_features,
        )
        socket_bone_names = (
                _build_socket_edit_bones(
                armature_data, sockets, bones, armature_space, scale_factor,
                preserve_ue_axis_order,
            )
            if sockets and create_socket_bones
            else {}
        )
        limbal_created = (
            _build_limbal_edit_bone(armature_data, bones, face_y_forward)
            if create_limbal_bone
            else False
        )
    except Exception:
        # Never leave a half-built armature behind for the user to clean up.
        bpy.ops.object.mode_set(mode="OBJECT")
        bpy.data.objects.remove(armature_obj)
        bpy.data.armatures.remove(armature_data)
        raise
    bpy.ops.object.mode_set(mode="OBJECT")

    # Record the forward axis: it is baked into the bone rest matrices and cannot
    # be recovered from them afterwards, but importing animation onto this rig
    # needs to know which convention its root bones were built in.
    armature_obj[FACE_FORWARD_PROPERTY] = (
        FACE_FORWARD_BLENDER if face_y_forward else FACE_FORWARD_UNREAL
    )
    armature_obj[AXIS_ORDER_PROPERTY] = (
        AXIS_ORDER_UNREAL if preserve_ue_axis_order else AXIS_ORDER_BLENDER
    )
    for target in (armature_obj, armature_data):
        target[BONE_AXIS_FRAME_PROPERTY] = (
            BONE_AXIS_FRAME_SOURCE if preserve_ue_axis_order else BONE_AXIS_FRAME_BLENDER
        )
    armature_obj["ue_import_scale"] = scale_factor

    if limbal_created:
        _add_limbal_face_constraint(context, armature_obj)
        _assign_face_base_child_custom_shapes(context, armature_obj)

    if sockets:
        armature_obj["sqex_sockets"] = json.dumps(sockets, ensure_ascii=False)
        if socket_bone_names:
            _finalize_socket_bones(armature_obj, socket_bone_names)
        if create_socket_empties and not socket_bone_names:
            _create_socket_empties(
                armature_obj, sockets, bones, armature_space, scale_factor
            )

    if setup_naive_ik:
        apply_naive_ik(armature_obj)

    return armature_obj


def _build_limbal_edit_bone(
        armature_data: Any,
        bones: list[dict[str, Any]],
        face_y_forward: bool,
) -> bool:
    """Add ``C_Limbal`` at eye height in front of the character, if possible.

    The source hierarchy's order is authoritative when both eyes are present:
    the first ``L_Eye``/``R_Eye`` encountered supplies the vertical level.  Its
    lateral position is intentionally discarded so the controller is centered
    on the character.  This makes the result independent of which eye appears
    first, and of the eye bone's local rotation.
    """
    edit_bones = armature_data.edit_bones
    if edit_bones.get(LIMBAL_BONE_NAME) is not None:
        return False

    eye_name = next(
        (str(bone.get("name", "")) for bone in bones
         if str(bone.get("name", "")).casefold() in EYE_BONE_NAMES),
        None,
    )
    eye_bone = edit_bones.get(eye_name) if eye_name else None
    if eye_bone is None:
        return False

    # Default imports face Unreal's +X; the optional Blender convention rotates
    # the complete character to face -Y.  Keep the other horizontal coordinate
    # at zero so this controller sits on the character's center line.
    if face_y_forward:
        head = Vector((0.0, eye_bone.head.y - LIMBAL_DISTANCE, eye_bone.head.z))
        forward = Vector((0.0, -1.0, 0.0))
    else:
        head = Vector((eye_bone.head.x + LIMBAL_DISTANCE, 0.0, eye_bone.head.z))
        forward = Vector((1.0, 0.0, 0.0))

    limbal = edit_bones.new(LIMBAL_BONE_NAME)
    limbal.head = head
    limbal.tail = head + forward * DEFAULT_BONE_LENGTH
    limbal.use_deform = False
    return True


def _add_limbal_face_constraint(context: Any, armature_obj: bpy.types.Object) -> bool:
    """Have the unparented ``C_Limbal`` follow ``C_FaceBase_a`` by default."""
    limbal = armature_obj.pose.bones.get(LIMBAL_BONE_NAME)
    face_base = armature_obj.pose.bones.get(FACE_BASE_BONE_NAME)
    if limbal is None or face_base is None:
        return False

    constraint = limbal.constraints.new(type="CHILD_OF")
    constraint.name = f"Child Of {FACE_BASE_BONE_NAME}"
    constraint.target = armature_obj
    constraint.subtarget = FACE_BASE_BONE_NAME
    constraint.target_space = "WORLD"
    constraint.owner_space = "WORLD"
    context.view_layer.update()
    constraint.inverse_matrix = (
        armature_obj.matrix_world @ face_base.matrix
    ).inverted()
    return True


def _assign_face_base_child_custom_shapes(context: Any, armature_obj: bpy.types.Object) -> int:
    """Set up widget display and collection membership for face-base children."""
    armature_data = armature_obj.data
    face_base = armature_data.bones.get(FACE_BASE_BONE_NAME)
    if face_base is None or not face_base.children:
        return 0
    face_collection = armature_data.collections.get("Face")
    if face_collection is None:
        face_collection = armature_data.collections.new("Face")

    shape = bpy.data.objects.get(FACE_BASE_CHILD_WIDGET_NAME)
    if shape is None:
        # The default Add > Mesh > Cube is a two-metre cube centered on origin.
        mesh = bpy.data.meshes.new(f"{FACE_BASE_CHILD_WIDGET_NAME}Mesh")
        vertices = [
            (-1.0, -1.0, -1.0), (1.0, -1.0, -1.0), (1.0, 1.0, -1.0), (-1.0, 1.0, -1.0),
            (-1.0, -1.0, 1.0), (1.0, -1.0, 1.0), (1.0, 1.0, 1.0), (-1.0, 1.0, 1.0),
        ]
        faces = [
            (0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
            (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7),
        ]
        mesh.from_pydata(vertices, [], faces)
        mesh.update()
        shape = bpy.data.objects.new(FACE_BASE_CHILD_WIDGET_NAME, mesh)
        context.collection.objects.link(shape)
    shape.display_type = "WIRE"
    shape.hide_render = True
    # The mesh exists solely as a pose-bone widget, not scene geometry.
    shape.hide_set(True)
    for child in face_base.children:
        if face_collection not in list(child.collections):
            face_collection.assign(child)
        child.show_wire = True
        pose_bone = armature_obj.pose.bones.get(child.name)
        if pose_bone is None:
            continue
        pose_bone.custom_shape = shape
        pose_bone.use_custom_shape_bone_size = False
        pose_bone.custom_shape_scale_xyz = (0.008, 0.003, 0.003)
    return len(face_base.children)


def _socket_local_matrix(socket: dict[str, Any], scale_factor: float) -> Matrix:
    """Convert one socket's bone-relative UE offset into a Blender-space matrix.

    Handles both export shapes: the gargoyle emits ``translation``/``rotation`` with
    the rotation already converted to a quaternion by CUE4Parse's own
    ``FRotator.Quaternion()``, while a raw FModel export carries
    ``relativeLocation``/``relativeRotation`` as a Pitch/Yaw/Roll Rotator in
    degrees. The Rotator path reuses ``json/map_import``'s
    ``rotation_from_relative``, which was verified against the quaternion path by
    full rotation-matrix comparison rather than by decomposed Euler angles.
    """
    if "translation" in socket or "rotation" in socket:
        return ue_bone_transform_to_blender(
            tuple(socket.get("translation") or (0.0, 0.0, 0.0)),
            tuple(socket.get("rotation") or (0.0, 0.0, 0.0, 1.0)),
            scale_factor,
        )

    location = location_from_relative(socket.get("relativeLocation") or {}, scale_factor)
    rotation = rotation_from_relative(socket.get("relativeRotation") or {})
    return Matrix.Translation(location) @ rotation.to_matrix().to_4x4()


def _create_socket_empties(
        armature_obj: bpy.types.Object,
        sockets: list[dict[str, Any]],
        bones: list[dict[str, Any]],
        armature_space: list[Matrix],
        scale_factor: float,
) -> int:
    """Create one bone-parented Empty per socket. Must be called in Object mode.

    The socket's offset is composed against ``armature_space`` -- the raw
    UE-converted bind transform -- and never against the edit bone's *display*
    matrix. That distinction matters: this importer aims bones down UE's local +X
    and adds a 90 degree roll, so a bone's displayed local axes are a permutation
    of the UE axes the socket offset is expressed in. Composing in UE-converted
    space and only then rebasing onto the finished bone (via ``rest_matrix``
    below, read back from Blender) keeps this correct without depending on what
    that permutation currently is.
    """
    bone_index_by_name = {bone["name"]: index for index, bone in enumerate(bones)}
    collection = armature_obj.users_collection[0] if armature_obj.users_collection else None
    created = 0

    for socket in sockets:
        socket_name = socket.get("name")
        bone_name = socket.get("boneName")
        if not socket_name or not bone_name:
            continue
        bone_index = bone_index_by_name.get(bone_name)
        bone = armature_obj.data.bones.get(bone_name)
        if bone_index is None or bone is None:
            print(f"[Talisman Skeleton] Socket '{socket_name}': bone '{bone_name}' not found; skipped.")
            continue

        socket_matrix = armature_space[bone_index] @ _socket_local_matrix(socket, scale_factor)

        empty = bpy.data.objects.new(f"{armature_obj.name}_{socket_name}", None)
        empty.empty_display_type = "PLAIN_AXES"
        empty.empty_display_size = 0.02
        empty["sqex_socket_bone"] = bone_name
        if collection is not None:
            collection.objects.link(empty)

        # Blender parents to a bone's TAIL, so the effective parent frame is the
        # bone's rest matrix shifted down its own +Y by the bone's length. Undo
        # exactly that shift so the Empty lands on the socket's true position;
        # leaving matrix_parent_inverse at identity keeps the resulting local
        # transform visible (and editable) in the N panel.
        parent_frame = bone.matrix_local @ Matrix.Translation((0.0, bone.length, 0.0))
        empty.parent = armature_obj
        empty.parent_type = "BONE"
        empty.parent_bone = bone_name
        empty.matrix_parent_inverse = Matrix.Identity(4)
        empty.matrix_basis = parent_frame.inverted() @ socket_matrix
        created += 1

    return created


def _build_socket_edit_bones(
        armature_data: bpy.types.Armature,
        sockets: list[dict[str, Any]],
        bones: list[dict[str, Any]],
        armature_space: list[Matrix],
        scale_factor: float,
        preserve_ue_axis_order: bool = False,
) -> dict[str, str]:
    """Add one non-deforming edit bone at each socket transform.

    The rest transforms are composed in exactly the same pre-display coordinate
    frame as the regular skeleton.  The bone is then aimed and rolled like an
    imported UE bone, so using it as a Blender attachment target has the same
    local axes as the socket's game transform.
    """
    bone_index_by_name = {bone["name"]: index for index, bone in enumerate(bones)}
    edit_bones = armature_data.edit_bones
    socket_bone_names: dict[str, str] = {}
    for socket in sockets:
        socket_name = socket.get("name")
        parent_name = socket.get("boneName")
        parent_index = bone_index_by_name.get(parent_name)
        parent_bone = edit_bones.get(parent_name) if parent_name else None
        if not socket_name or parent_index is None or parent_bone is None:
            print(f"[Talisman Skeleton] Socket '{socket_name}': bone '{parent_name}' not found; skipped.")
            continue

        socket_matrix = armature_space[parent_index] @ _socket_local_matrix(socket, scale_factor)
        socket_bone = edit_bones.new(socket_name)
        socket_bone.parent = parent_bone
        socket_bone.use_connect = False
        basis = socket_matrix.to_3x3()
        head = socket_matrix.translation
        socket_bone.head = head
        if preserve_ue_axis_order:
            aim = (basis @ Vector((0.0, 1.0, 0.0))).normalized()
            socket_bone.tail = head + aim * DEFAULT_BONE_LENGTH
            socket_bone.align_roll(basis @ Vector((0.0, 0.0, 1.0)))
        else:
            aim = (basis @ Vector((1.0, 0.0, 0.0))).normalized()
            socket_bone.tail = head + aim * DEFAULT_BONE_LENGTH
            socket_bone.align_roll(basis @ Vector((0.0, 0.0, 1.0)))
            socket_bone.roll += math.pi * 0.5
        socket_bone_names[socket_name] = socket_bone.name
    return socket_bone_names


def _finalize_socket_bones(
        armature_obj: bpy.types.Object,
        socket_bone_names: dict[str, str],
) -> None:
    """Move socket bones into a hidden collection and ensure they never deform."""
    armature_data = armature_obj.data
    socket_collection = armature_data.collections.get("Sockets")
    if socket_collection is None:
        socket_collection = armature_data.collections.new("Sockets")
    for socket_bone_name in socket_bone_names.values():
        bone = armature_data.bones.get(socket_bone_name)
        if bone is None:
            continue
        bone.use_deform = False
        for collection in list(bone.collections):
            collection.unassign(bone)
        socket_collection.assign(bone)
    socket_collection.is_visible = False


def _build_edit_bones(
        armature_data: Any,
        bones: list[dict[str, Any]],
        scale_factor: float,
        connect_bones: bool,
        face_y_forward: bool = False,
        preserve_ue_axis_order: bool = False,
        game_features: bool = True,
) -> list[Matrix]:
    """Populate an armature's edit bones. Must be called in Edit mode.

    Returns each bone's armature-space bind matrix in UE-converted axes (before
    the display-frame aim/roll applied to the edit bones), which socket placement
    needs in order to compose bone-relative UE offsets correctly.
    """
    edit_bones = armature_data.edit_bones
    created = []
    for bone in bones:
        edit_bone = edit_bones.new(bone["name"])
        edit_bone.head = (0.0, 0.0, 0.0)
        edit_bone.tail = (0.0, DEFAULT_BONE_LENGTH, 0.0)
        created.append(edit_bone)

    armature_space: list[Matrix] = [Matrix.Identity(4)] * len(bones)
    children_of: dict[int, list[int]] = {}
    for index, bone in enumerate(bones):
        local_matrix = ue_bone_transform_to_blender(
            bone["translation"], bone["rotation"], scale_factor,
            bone.get("scale") if not game_features else None,
        )
        parent_index = bone["parent_index"]
        if parent_index is not None and 0 <= parent_index < index:
            armature_space[index] = armature_space[parent_index] @ local_matrix
            created[index].parent = created[parent_index]
            children_of.setdefault(parent_index, []).append(index)
        else:
            # A root bone: this is the one place the -Y-forward rotation is
            # introduced. Every descendant's matrix is composed from its
            # parent's above, so the rotation carries through the whole
            # hierarchy automatically.
            armature_space[index] = Y_FORWARD_ROTATION @ local_matrix if face_y_forward else local_matrix
        created[index].matrix = armature_space[index]

    bone_length: dict[int, float] = {}
    for index, edit_bone in enumerate(created):
        basis = armature_space[index].to_3x3()
        head = armature_space[index].translation
        aim = (basis @ Vector((1.0, 0.0, 0.0))).normalized()

        # Reach the far end of this bone's own chain. Children are split by whether
        # they continue the chain (aligned with +X) or merely hang off it; taking the
        # longest aligned child skips past intermediate helpers like the deltoid and
        # femoris "_Spo" bones, which would otherwise cut an upper arm or thigh short.
        aligned: list[float] = []
        offset: list[float] = []
        for child in children_of.get(index, ()):
            delta = armature_space[child].translation - head
            distance = delta.length
            if distance < DEGENERATE_LENGTH:
                # Child sits exactly on this bone's head; it implies no length or
                # direction at all. Very common for helper/attachment bones.
                continue
            if delta.normalized().dot(aim) >= ALIGNED_CHILD_COSINE:
                aligned.append(distance)
            else:
                offset.append(distance)

        if aligned:
            length = max(aligned)
        elif offset:
            # Nothing continues the chain, so this bone only carries accessories.
            # The nearest keeps it from overshooting whatever it does hold.
            length = min(offset)
        else:
            # A leaf, or every child is coincident. Echo a fraction of the parent so
            # chain tips taper instead of collapsing into invisible stubs.
            parent_index = bones[index]["parent_index"]
            length = bone_length.get(parent_index, DEFAULT_BONE_LENGTH) * LEAF_LENGTH_RATIO
        cap = max_length_for_bone(bones[index]["name"]) if game_features else None
        if cap is not None:
            length = min(length, cap)
        length = max(length, MIN_BONE_LENGTH)
        # Store the clamped value so children inheriting a leaf length stay in
        # proportion with what is actually drawn.
        bone_length[index] = length

        # Blender defines a bone's local +Y as head->tail, but UE skeletal bones
        # run down their local +X (children are offset along the parent's +X).
        # Preserving source axes must bypass the X-to-Y reorientation entirely,
        # not merely its additional roll. Blender always draws along local Y,
        # so an unmodified source frame has its tail on source Y, while source X
        # still points down the authored skeleton chain.
        if preserve_ue_axis_order:
            # Reconstruct the unmodified source Y/Z frame explicitly. Merely
            # assigning .matrix loses roll precision for near-negative-Y bones.
            source_y = (basis @ Vector((0.0, 1.0, 0.0))).normalized()
            edit_bone.tail = head + source_y * length
            edit_bone.align_roll(basis @ Vector((0.0, 0.0, 1.0)))
        else:
            edit_bone.tail = head + aim * length
            edit_bone.align_roll(basis @ Vector((0.0, 0.0, 1.0)))
            edit_bone.roll += math.pi * 0.5

        if connect_bones and edit_bone.parent is not None and (not game_features or allows_connect(bones[index]["name"])):
            # Preserve the imported child head: move only the parent's tail before
            # enabling connected mode. Assigning use_connect first would snap the
            # child head onto the parent tail and lose its 1:1 game position.
            if (head - edit_bone.parent.tail).length <= CONNECT_DISTANCE_THRESHOLD:
                edit_bone.parent.tail = head
                edit_bone.use_connect = True

    if game_features:
        _disable_kdi_root_deform(bones, created, children_of)

    return armature_space


def _disable_kdi_root_deform(
        bones: list[dict[str, Any]],
        created: list[Any],
        children_of: dict[int, list[int]],
) -> None:
    """Turn off Deform on ``C_KDIRoot`` and every one of its descendants.

    KDI bones exist to be driven by KineDriver, not to skin geometry -- see
    ``KDI_ROOT_BONE_NAME``. Walks ``children_of`` (already built by the caller
    from each bone's parent index) rather than re-deriving the hierarchy.
    """
    root_index = next(
        (index for index, bone in enumerate(bones) if bone["name"] == KDI_ROOT_BONE_NAME),
        None,
    )
    if root_index is None:
        return

    stack = [root_index]
    while stack:
        index = stack.pop()
        created[index].use_deform = False
        stack.extend(children_of.get(index, ()))
