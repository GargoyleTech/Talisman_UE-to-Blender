"""Crisis Core's linked-Skeleton policy on the shared animation workflow."""

from ....formats.unreal_mesh import animations as animation_importer
from ....formats.unreal_package.indexing import AnimationAssetIndex
from ... import package_browser
from ...conventional_animation import make_animation_importer
from ..profile import PROFILE
from . import static_mesh


_ANIMATION_INDEX = AnimationAssetIndex()
_ANIMATION_BROWSER = package_browser.make_state(
    "compatible Crisis Core AnimSequence assets",
    initial_directory="CCFF7R/Content",
    file_icon="ARMATURE_DATA",
)


def refresh_animation_index(context, armature, *, force=False):
    skeleton_path = animation_importer.skeleton_path(armature)
    if not skeleton_path:
        raise ValueError(
            "The selected armature has no Crisis Core Skeleton source. "
            "Import its SkeletalMesh with Build Skeleton from Package enabled."
        )
    paths = static_mesh._configured_paths(context)
    return _ANIMATION_INDEX.refresh(
        paths, PROFILE, skeleton_path, use_registry=True, force=force,
    )


FF7R_CRISIS_CORE_OT_import_animation_game_packages = make_animation_importer(
    class_name="FF7R_CRISIS_CORE_OT_import_animation_game_packages",
    module_name=__name__,
    bl_idname="object.ff7r_crisis_core_import_animation_game_packages",
    game_name="Crisis Core",
    profile=PROFILE,
    configured_paths=static_mesh._configured_paths,
    compatible_paths=refresh_animation_index,
    import_animation=animation_importer.import_animation_asset,
    browser=_ANIMATION_BROWSER,
)

CLASSES = (FF7R_CRISIS_CORE_OT_import_animation_game_packages,)
