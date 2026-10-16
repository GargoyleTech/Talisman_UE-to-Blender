"""Game-neutral package import runtime.

Title adapters supply profiles, material builders and optional mesh hooks.
Legacy helper names remain exported so existing scripts can migrate gradually.
"""

from .session import (
    PackageAssetSession,
    _gargoyle_command,
    _run_gargoyle,
    _run_gargoyle_asset_request,
)
from .indexing import (
    _package_config_key,
    _mesh_package_signature,
    _mesh_disk_cache_path,
    _natural_path_key,
    _load_mesh_disk_cache,
    _save_mesh_disk_cache,
    _package_search_terms,
    _path_matches_package_search,
    _search_virtual_paths,
)
from .paths import _texture_package_path, _game_asset_path_to_virtual_uasset
from .options import (
    KDI_COORDINATE_PROFILE_PROPERTY,
    SKELETON_ASSET_PATH_PROPERTY,
    COORDINATE_PROFILE_PACKAGE_SKELETON_ROLL_90,
    COORDINATE_PROFILE_REFERENCE,
    OFFSET_FACES_NONE,
    OFFSET_FACES_BAKED,
    OFFSET_FACES_MODIFIER,
    OFFSET_FACES_ITEMS,
    ATTACHMENT_SOCKETS_NONE,
    ATTACHMENT_SOCKETS_EMPTIES,
    ATTACHMENT_SOCKETS_BONES,
    ATTACHMENT_SOCKETS_ITEMS,
    FACE_FORWARD_ITEMS,
    FACE_FORWARD_UNREAL,
    FACE_FORWARD_BLENDER,
    _normalize_offset_faces_mode,
    _face_y_forward_enabled,
)
from .mesh_import import (
    MeshImportHooks,
    _static_mesh_material,
    _apply_face_y_forward,
    import_static_mesh_asset,
    import_skeletal_mesh_asset,
    bind_skeletal_mesh_object,
)
from .resolvers import PackageStaticMeshResolver, PackageSkeletalMeshResolver
from .skeleton_data import (
    _create_variant_bone_collections,
    _restrict_skeleton_to_referenced_bones,
)
from ...core.blender.collections import (
    _ensure_scene_collection,
    _layer_collection_for,
    _active_collection,
    _adopt_new_scene_collections,
)

__all__ = [
    "PackageAssetSession",
    "_gargoyle_command",
    "_run_gargoyle",
    "_run_gargoyle_asset_request",
    "_package_config_key",
    "_mesh_package_signature",
    "_mesh_disk_cache_path",
    "_natural_path_key",
    "_load_mesh_disk_cache",
    "_save_mesh_disk_cache",
    "_package_search_terms",
    "_path_matches_package_search",
    "_search_virtual_paths",
    "_texture_package_path",
    "_game_asset_path_to_virtual_uasset",
    "KDI_COORDINATE_PROFILE_PROPERTY",
    "SKELETON_ASSET_PATH_PROPERTY",
    "COORDINATE_PROFILE_PACKAGE_SKELETON_ROLL_90",
    "COORDINATE_PROFILE_REFERENCE",
    "OFFSET_FACES_NONE",
    "OFFSET_FACES_BAKED",
    "OFFSET_FACES_MODIFIER",
    "OFFSET_FACES_ITEMS",
    "ATTACHMENT_SOCKETS_NONE",
    "ATTACHMENT_SOCKETS_EMPTIES",
    "ATTACHMENT_SOCKETS_BONES",
    "ATTACHMENT_SOCKETS_ITEMS",
    "FACE_FORWARD_ITEMS",
    "FACE_FORWARD_UNREAL",
    "FACE_FORWARD_BLENDER",
    "_normalize_offset_faces_mode",
    "_face_y_forward_enabled",
    "MeshImportHooks",
    "_static_mesh_material",
    "_apply_face_y_forward",
    "import_static_mesh_asset",
    "import_skeletal_mesh_asset",
    "bind_skeletal_mesh_object",
    "PackageStaticMeshResolver",
    "PackageSkeletalMeshResolver",
    "_create_variant_bone_collections",
    "_restrict_skeleton_to_referenced_bones",
    "_ensure_scene_collection",
    "_layer_collection_for",
    "_active_collection",
    "_adopt_new_scene_collections",
]
