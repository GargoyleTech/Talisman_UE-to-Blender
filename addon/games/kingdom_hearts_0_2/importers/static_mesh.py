"""Kingdom Hearts 0.2 binding for the shared static-mesh importer."""

from ...kingdom_hearts.importers import static_mesh as shared_static_mesh
from ...kingdom_hearts.importers import matinee as shared_matinee
from ...kingdom_hearts import materials as kh_materials
from ...conventional_map import make_umap_importer
from ..profile import PROFILE


DEFINITION = shared_static_mesh.make_definition(
    PROFILE,
    game_name="Kingdom Hearts 0.2",
    default_virtual_path=(
        "KINGDOM HEARTS 0.2 Birth by Sleep/Content/Maps/di/uasset/Meshes/"
        "SM_di_Env_RockB.uasset"
    ),
    default_skeletal_mesh_path=(
        "KINGDOM HEARTS 0.2 Birth by Sleep/Content/Character/enemy/e_dw401/mdl/"
        "e_dw401_0.uasset"
    ),
    initial_directory="KINGDOM HEARTS 0.2 Birth by Sleep/Content",
)


def refresh_static_mesh_index(context, *, force=False) -> list[str]:
    return shared_static_mesh.refresh_static_mesh_index(context, DEFINITION, force=force)


def _configured_paths(context):
    return shared_static_mesh._configured_paths(context, DEFINITION)


def _is_gameplay_umap(path: str) -> bool:
    return path.replace("\\", "/").casefold().startswith(
        "kingdom hearts 0.2 birth by sleep/content/maps/"
    )


SQEX_KH02_OT_import_static_mesh_game_packages = shared_static_mesh.make_static_mesh_importer(
    class_name="SQEX_KH02_OT_import_static_mesh_game_packages",
    module_name=__name__,
    bl_idname="import_scene.sqex_kh02_static_mesh_game_packages",
    definition=DEFINITION,
)

SQEX_KH02_OT_import_skeletal_mesh_game_packages = shared_static_mesh.make_skeletal_mesh_importer(
    class_name="SQEX_KH02_OT_import_skeletal_mesh_game_packages",
    module_name=__name__,
    bl_idname="import_scene.sqex_kh02_skeletal_mesh_game_packages",
    definition=DEFINITION,
)

SQEX_KH02_OT_import_kdi_game_packages = shared_static_mesh.make_kdi_importer(
    class_name="SQEX_KH02_OT_import_kdi_game_packages",
    module_name=__name__,
    bl_idname="import_scene.sqex_kh02_kdi_game_packages",
    definition=DEFINITION,
)

SQEX_KH02_OT_import_animation_game_packages = shared_static_mesh.make_animation_importer(
    class_name="SQEX_KH02_OT_import_animation_game_packages",
    module_name=__name__,
    bl_idname="object.sqex_kh02_import_animation_game_packages",
    definition=DEFINITION,
)

SQEX_KH02_OT_import_umap_game_packages = make_umap_importer(
    class_name="SQEX_KH02_OT_import_umap_game_packages",
    bl_idname="import_scene.sqex_kh02_umap_game_packages",
    game_label="Kingdom Hearts 0.2",
    profile=PROFILE,
    configured_paths=_configured_paths,
    material_builder=kh_materials.build_material,
    initial_directory="KINGDOM HEARTS 0.2 Birth by Sleep/Content/Maps",
    umap_path_filter=_is_gameplay_umap,
)

SQEX_KH02_OT_import_matinee_cutscene_game_packages = shared_matinee.make_matinee_importer(
    class_name="SQEX_KH02_OT_import_matinee_cutscene_game_packages",
    bl_idname="import_scene.sqex_kh02_matinee_cutscene_game_packages",
    game_label="Kingdom Hearts 0.2",
    definition=DEFINITION,
)


CLASSES = (
    SQEX_KH02_OT_import_static_mesh_game_packages,
    SQEX_KH02_OT_import_skeletal_mesh_game_packages,
    SQEX_KH02_OT_import_kdi_game_packages,
    SQEX_KH02_OT_import_animation_game_packages,
    SQEX_KH02_OT_import_umap_game_packages,
    SQEX_KH02_OT_import_matinee_cutscene_game_packages,
)
