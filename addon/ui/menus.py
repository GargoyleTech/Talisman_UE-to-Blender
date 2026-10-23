"""Top-bar, object, pose, and armature menus."""

from bpy.types import Menu

from ..core.package_utils import addon_package_name
from ..core.blender import z_fighting
from ..formats.kdi import drivers as kdi_drivers
from ..formats.kdi import nodetree as kdi_nodetree
from ..formats.mec import importer as mec_importer
from ..games.crisis_core.importers import static_mesh as crisis_core_static_mesh
from ..games.crisis_core.importers import animations as crisis_core_animations
from ..games.crisis_core.importers import cutscenes as crisis_core_cutscenes
from ..games.crisis_core import profile as crisis_core_profile
from ..games.kingdom_hearts_0_2.importers import static_mesh as kingdom_hearts_0_2_static_mesh
from ..games.kingdom_hearts_0_2 import profile as kingdom_hearts_0_2_profile
from ..games.kingdom_hearts_iii.importers import static_mesh as kingdom_hearts_iii_static_mesh
from ..games.kingdom_hearts_iii import profile as kingdom_hearts_iii_profile
from ..games.rebirth.importers import animations
from ..games.rebirth.importers import niagara as rebirth_niagara
from ..games.rebirth.importers import packages as game_packages
from ..games.rebirth import profile as rebirth_profile
from ..games.remake.importers import static_mesh as remake_static_mesh
from ..games.remake.importers import animations as remake_animations
from ..games.remake.importers import cutscenes as remake_cutscenes
from ..games.remake import profile as remake_profile
from . import operators
from ..formats.unreal_mesh import importer as generic_unreal_importer
from ..formats.unreal_mesh import animations as generic_unreal_animations
from ..formats.unreal_mesh import sequences as generic_sequences


def _game_install_path_is_configured(context, profile) -> bool:
    """Return whether the game install folder needed by a profile is set."""
    addon_name = addon_package_name(__package__)
    addon = context.preferences.addons.get(addon_name)
    if addon is None:
        return False
    return bool(getattr(addon.preferences, profile.install_root_property, "").strip())


class TOPBAR_MT_file_import_ue_talisman(Menu):
    bl_idname = "TOPBAR_MT_file_import_ue_talisman"
    bl_label = "Talisman (Unreal Engine)"

    def draw(self, _context):
        layout = self.layout
        layout.menu(TOPBAR_MT_file_import_ue_talisman_ff7r.bl_idname)
        layout.menu(TOPBAR_MT_file_import_ue_talisman_kingdom_hearts.bl_idname)
        layout.menu(TOPBAR_MT_file_import_ue_talisman_generic.bl_idname)


def _category_heading(layout, text):
    # Labels are non-clickable headings in Blender menus.
    layout.separator()
    layout.label(text=text)
    layout.separator()


class TOPBAR_MT_file_import_ue_talisman_ff7r(Menu):
    bl_idname = "TOPBAR_MT_file_import_ue_talisman_ff7r"
    bl_label = "FF7R"

    def draw(self, context):
        layout = self.layout
        layout.operator_context = "INVOKE_REGION_WIN"

        _category_heading(layout, "Remake")
        remake_importers = layout.column()
        remake_importers.enabled = _game_install_path_is_configured(
            context, remake_profile.PROFILE
        )
        remake_importers.operator(
            remake_static_mesh.FF7R_REMAKE_OT_import_skeletal_mesh_game_packages.bl_idname,
            text="Skeletal Mesh",
        )
        remake_importers.operator(
            remake_static_mesh.FF7R_REMAKE_OT_import_static_mesh_game_packages.bl_idname,
            text="Static Mesh",
        )
        remake_importers.operator(
            remake_static_mesh.FF7R_REMAKE_OT_import_umap_game_packages.bl_idname,
            text="UMAP",
        )
        remake_importers.operator(
            remake_cutscenes.FF7R_REMAKE_OT_import_cutscene_game_packages.bl_idname,
            text="Cutscene",
        )
        remake_importers.operator(
            remake_animations.FF7R_REMAKE_OT_apply_animation_game_packages.bl_idname,
            text="Animation",
        )
        remake_importers.operator(
            remake_static_mesh.FF7R_REMAKE_OT_import_kdi_game_packages.bl_idname,
            text="KineDriver",
        )

        _category_heading(layout, "Rebirth")
        rebirth_importers = layout.column()
        rebirth_importers.enabled = _game_install_path_is_configured(
            context, rebirth_profile.PROFILE
        )
        for operator, label in (
            (game_packages.FF7R_REBIRTH_OT_import_skeletal_mesh_game_packages, "Skeletal Mesh"),
            (game_packages.FF7R_REBIRTH_OT_import_static_mesh_game_packages, "Static Mesh"),
            (game_packages.FF7R_REBIRTH_OT_import_mec_game_packages, "UMAP"),
            (game_packages.FF7R_REBIRTH_OT_import_cutscene_game_packages, "Cutscene"),
            (game_packages.FF7R_REBIRTH_OT_import_skeleton_game_packages, "Skeleton only"),
            (animations.FF7R_REBIRTH_OT_apply_animation_game_packages, "Animation"),
            (game_packages.FF7R_REBIRTH_OT_import_kdi_game_packages, "KineDriver"),
            (rebirth_niagara.FF7R_REBIRTH_OT_import_niagara_game_packages, "Niagara (Mesh resources)"),
            (game_packages.FF7R_REBIRTH_OT_import_nearby_mec_terrain, "Nearby UMAP terrain (Experimental)"),
        ):
            rebirth_importers.operator(operator.bl_idname, text=label)

        op = layout.operator(
            mec_importer.FF7R_REBIRTH_OT_import_mec_umap.bl_idname,
            text="Massive Environment UMAP (Loose files)",
        )
        op.filepath = ""
        layout.operator(
            kdi_drivers.KDI_OT_step2_scalar_drivers.bl_idname,
            text="KineDriver JSON (Loose files)",
        )

        _category_heading(layout, "Crisis Core")
        crisis_core_importers = layout.column()
        crisis_core_importers.enabled = _game_install_path_is_configured(
            context, crisis_core_profile.PROFILE
        )
        crisis_core_importers.operator(
            crisis_core_static_mesh.FF7R_CRISIS_CORE_OT_import_skeletal_mesh_game_packages.bl_idname,
            text="Skeletal Mesh",
        )
        crisis_core_importers.operator(
            crisis_core_static_mesh.FF7R_CRISIS_CORE_OT_import_static_mesh_game_packages.bl_idname,
            text="Static Mesh",
        )
        crisis_core_importers.operator(
            crisis_core_static_mesh.FF7R_CRISIS_CORE_OT_import_umap_game_packages.bl_idname,
            text="UMAP",
        )
        crisis_core_importers.operator(
            crisis_core_cutscenes.FF7R_CRISIS_CORE_OT_import_cutscene_game_packages.bl_idname,
            text="Cutscene",
        )
        crisis_core_importers.operator(
            crisis_core_animations.FF7R_CRISIS_CORE_OT_import_animation_game_packages.bl_idname,
            text="Animation",
        )


class TOPBAR_MT_file_import_ue_talisman_kingdom_hearts(Menu):
    bl_idname = "TOPBAR_MT_file_import_ue_talisman_kingdom_hearts"
    bl_label = "Kingdom Hearts"

    def draw(self, context):
        layout = self.layout
        layout.operator_context = "INVOKE_REGION_WIN"

        _category_heading(layout, "Kingdom Hearts III")
        kingdom_hearts_iii_importers = layout.column()
        kingdom_hearts_iii_importers.enabled = _game_install_path_is_configured(
            context, kingdom_hearts_iii_profile.PROFILE
        )
        kingdom_hearts_iii_importers.operator(
            kingdom_hearts_iii_static_mesh.SQEX_KH3_OT_import_skeletal_mesh_game_packages.bl_idname,
            text="Skeletal Mesh",
        )
        kingdom_hearts_iii_importers.operator(
            kingdom_hearts_iii_static_mesh.SQEX_KH3_OT_import_static_mesh_game_packages.bl_idname,
            text="Static Mesh",
        )
        kingdom_hearts_iii_importers.operator(
            kingdom_hearts_iii_static_mesh.SQEX_KH3_OT_import_umap_game_packages.bl_idname,
            text="UMAP (Geometry)",
        )
        kingdom_hearts_iii_importers.operator(
            kingdom_hearts_iii_static_mesh.SQEX_KH3_OT_import_matinee_cutscene_game_packages.bl_idname,
            text="Cutscene (Matinee)",
        )
        kingdom_hearts_iii_importers.operator(
            kingdom_hearts_iii_static_mesh.SQEX_KH3_OT_import_animation_game_packages.bl_idname,
            text="Animation",
        )
        kingdom_hearts_iii_importers.operator(
            kingdom_hearts_iii_static_mesh.SQEX_KH3_OT_import_kdi_game_packages.bl_idname,
            text="KineDriver",
        )

        _category_heading(layout, "Kingdom Hearts 0.2")
        kingdom_hearts_0_2_importers = layout.column()
        kingdom_hearts_0_2_importers.enabled = _game_install_path_is_configured(
            context, kingdom_hearts_0_2_profile.PROFILE
        )
        kingdom_hearts_0_2_importers.operator(
            kingdom_hearts_0_2_static_mesh.SQEX_KH02_OT_import_skeletal_mesh_game_packages.bl_idname,
            text="Skeletal Mesh",
        )
        kingdom_hearts_0_2_importers.operator(
            kingdom_hearts_0_2_static_mesh.SQEX_KH02_OT_import_static_mesh_game_packages.bl_idname,
            text="Static Mesh",
        )
        kingdom_hearts_0_2_importers.operator(
            kingdom_hearts_0_2_static_mesh.SQEX_KH02_OT_import_umap_game_packages.bl_idname,
            text="UMAP (Geometry)",
        )
        kingdom_hearts_0_2_importers.operator(
            kingdom_hearts_0_2_static_mesh.SQEX_KH02_OT_import_matinee_cutscene_game_packages.bl_idname,
            text="Cutscene (Matinee)",
        )
        kingdom_hearts_0_2_importers.operator(
            kingdom_hearts_0_2_static_mesh.SQEX_KH02_OT_import_animation_game_packages.bl_idname,
            text="Animation",
        )
        kingdom_hearts_0_2_importers.operator(
            kingdom_hearts_0_2_static_mesh.SQEX_KH02_OT_import_kdi_game_packages.bl_idname,
            text="KineDriver",
        )


class TOPBAR_MT_file_import_ue_talisman_generic(Menu):
    bl_idname = "TOPBAR_MT_file_import_ue_talisman_generic"
    bl_label = "Generic UE4"

    def draw(self, _context):
        layout = self.layout
        layout.operator_context = "INVOKE_REGION_WIN"
        layout.operator(
            generic_unreal_importer.SQEX_OT_import_generic_unreal_skeletal_mesh.bl_idname,
            text="Skeletal Mesh",
        )
        layout.operator(
            generic_unreal_importer.SQEX_OT_import_generic_unreal_static_mesh.bl_idname,
            text="Static Mesh",
        )
        layout.operator(
            generic_unreal_importer.SQEX_OT_import_generic_unreal_umap.bl_idname,
            text="UMAP",
        )
        layout.operator(
            generic_sequences.SQEX_OT_import_generic_unreal_sequence.bl_idname,
            text="Cutscene (LevelSequence)",
        )
        layout.operator(
            generic_unreal_animations.SQEX_OT_import_generic_unreal_animation.bl_idname,
            text="Animation",
        )


class OBJECT_MT_sqex_ue4_tools(Menu):
    bl_idname = "OBJECT_MT_sqex_ue4_tools"
    bl_label = "Talisman"

    def draw(self, _context):
        from . import mouth_rig, ik_rig

        layout = self.layout
        layout.operator(operators.OBJECT_OT_add_rmi_surface_material.bl_idname)
        layout.separator()
        layout.operator(z_fighting.MESH_OT_find_opposite_faces.bl_idname)
        layout.separator()
        layout.operator(mouth_rig.OBJECT_OT_generate_mouth_controls.bl_idname)
        layout.operator(mouth_rig.OBJECT_OT_remove_mouth_controls.bl_idname)
        layout.operator(ik_rig.OBJECT_OT_repair_limb_ik.bl_idname)
        layout.separator()
        layout.operator(kdi_nodetree.SQEX_KDI_OT_visualize.bl_idname)
        layout.operator(kdi_drivers.KDI_OT_remove_scalar_drivers.bl_idname)


class ARMATURE_MT_sqex_ue4_tools(Menu):
    bl_idname = "ARMATURE_MT_sqex_ue4_tools"
    bl_label = "Talisman"

    def draw(self, _context):
        self.layout.operator(operators.ARMATURE_OT_connect_parent_tail_to_bone.bl_idname)


def menu_func_import(self, _context):
    self.layout.menu(TOPBAR_MT_file_import_ue_talisman.bl_idname)


def menu_func_object(self, _context):
    self.layout.menu(OBJECT_MT_sqex_ue4_tools.bl_idname)


def menu_func_pose_bone(self, context):
    if kdi_nodetree.selected_bone_has_kdi_driver(context):
        self.layout.separator()
        self.layout.operator(kdi_nodetree.SQEX_KDI_OT_focus_selected_bone.bl_idname)


def menu_func_edit_armature(self, _context):
    self.layout.menu(ARMATURE_MT_sqex_ue4_tools.bl_idname)


CLASSES = (
    TOPBAR_MT_file_import_ue_talisman_ff7r,
    TOPBAR_MT_file_import_ue_talisman_kingdom_hearts,
    TOPBAR_MT_file_import_ue_talisman_generic,
    TOPBAR_MT_file_import_ue_talisman,
    OBJECT_MT_sqex_ue4_tools,
    ARMATURE_MT_sqex_ue4_tools,
)
