"""Top-bar, object, pose, and armature menus."""

from bpy.types import Menu

from ..core.blender import z_fighting
from ..formats.kdi import drivers as kdi_drivers
from ..formats.kdi import nodetree as kdi_nodetree
from ..formats.mec import importer as mec_importer
from ..games.crisis_core.importers import static_mesh as crisis_core_static_mesh
from ..games.rebirth.importers import animations
from ..games.rebirth.importers import packages as game_packages
from ..games.remake.importers import static_mesh as remake_static_mesh
from . import operators


class TOPBAR_MT_file_import_ff7r_rebirth(Menu):
    bl_idname = "TOPBAR_MT_file_import_ff7r_rebirth"
    bl_label = "FF7R Retrilogy"

    def draw(self, _context):
        layout = self.layout
        # Labels are intentionally used for headings instead of disabled
        # operators: Blender renders them as non-clickable menu text.
        def category_heading(text):
            layout.separator()
            layout.label(text=text)
            layout.separator()

        category_heading("Remake")
        layout.operator(
            remake_static_mesh.FF7R_REMAKE_OT_import_umap_game_packages.bl_idname,
            text="UMAP",
        )
        layout.operator(
            remake_static_mesh.FF7R_REMAKE_OT_import_skeletal_mesh_game_packages.bl_idname,
            text="Skeletal mesh",
        )
        layout.operator(
            remake_static_mesh.FF7R_REMAKE_OT_import_static_mesh_game_packages.bl_idname,
            text="Static mesh",
        )
        layout.operator(
            remake_static_mesh.FF7R_REMAKE_OT_import_kdi_game_packages.bl_idname,
            text="KineDriver",
        )
        
        category_heading("Rebirth")
        for operator, label in (
            (game_packages.FF7R_REBIRTH_OT_import_skeletal_mesh_game_packages, "Skeletal mesh"),
            (game_packages.FF7R_REBIRTH_OT_import_static_mesh_game_packages, "Static mesh"),
            (game_packages.FF7R_REBIRTH_OT_import_skeleton_game_packages, "Skeleton only"),
            (game_packages.FF7R_REBIRTH_OT_import_mec_game_packages, "UMAP"),
            (game_packages.FF7R_REBIRTH_OT_import_nearby_mec_terrain, "Nearby UMAP terrain (Experimental)"),
            (game_packages.FF7R_REBIRTH_OT_import_cutscene_game_packages, "Cutscene"),
            (game_packages.FF7R_REBIRTH_OT_import_kdi_game_packages, "KineDriver"),
        ):
            layout.operator(operator.bl_idname, text=label)

        op = layout.operator(
            mec_importer.FF7R_REBIRTH_OT_import_mec_umap.bl_idname,
            text="Massive Environment UMAP (Loose files)",
        )
        op.filepath = ""
        layout.operator(
            kdi_drivers.KDI_OT_step2_scalar_drivers.bl_idname,
            text="KineDriver JSON (Loose files)",
        )

        category_heading("Crisis Core")
        layout.operator(
            crisis_core_static_mesh.FF7R_CRISIS_CORE_OT_import_umap_game_packages.bl_idname,
            text="UMAP",
        )
        layout.operator(
            crisis_core_static_mesh.FF7R_CRISIS_CORE_OT_import_skeletal_mesh_game_packages.bl_idname,
            text="Skeletal mesh",
        )
        layout.operator(
            crisis_core_static_mesh.FF7R_CRISIS_CORE_OT_import_static_mesh_game_packages.bl_idname,
            text="Static mesh",
        )


class OBJECT_MT_ff7r_rebirth_tools(Menu):
    bl_idname = "OBJECT_MT_ff7r_rebirth_tools"
    bl_label = "Retrilogy tools"

    def draw(self, _context):
        layout = self.layout
        layout.operator(operators.OBJECT_OT_add_rmi_surface_material.bl_idname)
        layout.separator()
        layout.operator(z_fighting.MESH_OT_find_opposite_faces.bl_idname)
        layout.separator()
        layout.operator(animations.FF7R_REBIRTH_OT_apply_animation_game_packages.bl_idname)
        layout.separator()
        layout.operator(kdi_nodetree.FF7R_KDI_OT_visualize.bl_idname)
        layout.operator(kdi_drivers.KDI_OT_remove_scalar_drivers.bl_idname)


class ARMATURE_MT_ff7r_rebirth_tools(Menu):
    bl_idname = "ARMATURE_MT_ff7r_rebirth_tools"
    bl_label = "Retrilogy tools"

    def draw(self, _context):
        self.layout.operator(operators.ARMATURE_OT_connect_parent_tail_to_bone.bl_idname)


def menu_func_import(self, _context):
    self.layout.menu(TOPBAR_MT_file_import_ff7r_rebirth.bl_idname)


def menu_func_object(self, _context):
    self.layout.menu(OBJECT_MT_ff7r_rebirth_tools.bl_idname)


def menu_func_pose_bone(self, context):
    if kdi_nodetree.selected_bone_has_kdi_driver(context):
        self.layout.separator()
        self.layout.operator(kdi_nodetree.FF7R_KDI_OT_focus_selected_bone.bl_idname)


def menu_func_edit_armature(self, _context):
    self.layout.menu(ARMATURE_MT_ff7r_rebirth_tools.bl_idname)


CLASSES = (
    TOPBAR_MT_file_import_ff7r_rebirth,
    OBJECT_MT_ff7r_rebirth_tools,
    ARMATURE_MT_ff7r_rebirth_tools,
)
