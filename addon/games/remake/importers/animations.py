"""Remake's clip compatibility policy on the shared animation workflow."""

from ... import package_browser
from ...conventional_animation import make_animation_importer
from ...rebirth.importers import animations as animation_importer
from ...rebirth.importers import packages as ff7_packages
from ..profile import PROFILE
from . import static_mesh


_ANIMATION_BROWSER = package_browser.make_state(
    "compatible Remake AnimSequence assets",
    initial_directory="End/Content",
    file_icon="ARMATURE_DATA",
)


def _compatible_paths(context, armature):
    skeleton_path = animation_importer._selected_armature_skeleton_path(armature)
    if not skeleton_path:
        raise ValueError(
            "The selected armature has no Remake Skeleton source. Import its package Skeleton first."
        )
    paths = static_mesh._configured_paths(context)
    return ff7_packages.refresh_animation_index(
        paths.install_root,
        paths.oodle_dll,
        paths.usmap_path,
        skeleton_path,
        profile=PROFILE,
        aes_key=paths.aes_key,
        include_unlinked=True,
    )


FF7R_REMAKE_OT_apply_animation_game_packages = make_animation_importer(
    class_name="FF7R_REMAKE_OT_apply_animation_game_packages",
    module_name=__name__,
    bl_idname="object.ff7r_remake_apply_animation_game_packages",
    game_name="Remake",
    profile=PROFILE,
    configured_paths=static_mesh._configured_paths,
    compatible_paths=_compatible_paths,
    import_animation=animation_importer.import_animation_asset,
    browser=_ANIMATION_BROWSER,
)

CLASSES = (FF7R_REMAKE_OT_apply_animation_game_packages,)
