"""Backward-compatible import location for the shared mesh importer layout."""

from .mesh_importer import draw_package_mesh_importer


def draw_package_skeletal_mesh_importer(
    layout,
    context,
    **kwargs,
) -> None:
    """Delegate legacy callers to the unified SkeletalMesh dialog."""
    kwargs.pop("show_limbal_controller", None)
    kwargs.pop("show_mouth_controls", None)
    draw_package_mesh_importer(
        layout,
        context,
        mesh_kind="SKELETAL",
        supported_skeletal_options=kwargs.pop("supported_skeletal_options", frozenset()),
        **kwargs,
    )
