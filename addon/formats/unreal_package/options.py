"""Options and persisted metadata used by package mesh importers."""

from ...language import tooltips

from ...core.blender.skeletons import FACE_FORWARD_BLENDER, FACE_FORWARD_UNREAL
from ..kdi.drivers import (
    COORDINATE_PROFILE_PACKAGE_SKELETON_ROLL_90 as COORDINATE_PROFILE_PACKAGE_SKELETON_ROLL_90,
    COORDINATE_PROFILE_REFERENCE as COORDINATE_PROFILE_REFERENCE,
)

KDI_COORDINATE_PROFILE_PROPERTY = "sqex_kdi_coordinate_profile"
SKELETON_ASSET_PATH_PROPERTY = "sqex_skeleton_asset_path"

OFFSET_FACES_NONE = "NONE"
OFFSET_FACES_BAKED = "BAKED"
OFFSET_FACES_MODIFIER = "MODIFIER"
OFFSET_FACES_ITEMS = (
    (OFFSET_FACES_NONE, "None", tooltips.SHARED_OFFSET_FACES_NONE),
    (OFFSET_FACES_BAKED, "Baked", tooltips.SHARED_OFFSET_FACES_BAKED),
    (
        OFFSET_FACES_MODIFIER,
        "Modifier",
        tooltips.SHARED_OFFSET_FACES_MODIFIER,
    ),
)

ATTACHMENT_SOCKETS_NONE = "NONE"
ATTACHMENT_SOCKETS_EMPTIES = "EMPTIES"
ATTACHMENT_SOCKETS_BONES = "BONES"
ATTACHMENT_SOCKETS_ITEMS = (
    (
        ATTACHMENT_SOCKETS_NONE,
        "None",
        tooltips.SHARED_ATTACHMENT_SOCKETS_NONE,
    ),
    (
        ATTACHMENT_SOCKETS_EMPTIES,
        "Empties",
        tooltips.SHARED_ATTACHMENT_SOCKETS_EMPTIES,
    ),
    (
        ATTACHMENT_SOCKETS_BONES,
        "Bones",
        tooltips.SHARED_ATTACHMENT_SOCKETS_BONES,
    ),
)

FACE_FORWARD_ITEMS = (
    (
        FACE_FORWARD_UNREAL,
        "+X (Unreal)",
        tooltips.SHARED_FACE_FORWARD_UNREAL,
    ),
    (
        FACE_FORWARD_BLENDER,
        "-Y (Blender)",
        tooltips.SHARED_FACE_FORWARD_BLENDER,
    ),
)


def _normalize_offset_faces_mode(value: bool | str | None) -> str:
    """Accept the legacy boolean flag as well as the mesh-import enum values."""
    if value is True:
        return OFFSET_FACES_BAKED
    if value in {OFFSET_FACES_NONE, OFFSET_FACES_BAKED, OFFSET_FACES_MODIFIER}:
        return value
    return OFFSET_FACES_NONE


def _face_y_forward_enabled(value: bool | str | None) -> bool:
    """Accept the legacy boolean flag as well as the forward-axis enum values."""
    return value is True or value == FACE_FORWARD_BLENDER
