"""Small shared operators exposed by the add-on menus."""

from __future__ import annotations

from ..language import strings

import bpy
from bpy.props import StringProperty

from ..core.blender.reporting import SQEX_LoggedOperator, report
from ..games.rebirth.materials import rmi_surface


def _search_rmi_variants(_self, _context, edit_text):
    try:
        _master, _variant, ground_truth = rmi_surface._modules()
    except Exception:
        return []
    needle = (edit_text or "").casefold()
    return [
        name for name in sorted(ground_truth, key=str.casefold)
        if needle in name.casefold()
    ]


class OBJECT_OT_add_rmi_surface_material(SQEX_LoggedOperator):
    """Put a fresh RMI_Surface master or trimmed variant in the active slot."""

    bl_idname = "object.sqex_add_rmi_surface_material"
    bl_label = "Add Square Enix RMI Surface Material"
    bl_description = (
        strings.SCENE_TOOLS_ADD_RMI_SURFACE_MATERIAL_DESCRIPTION
    )
    bl_options = {"REGISTER", "UNDO"}

    variant: StringProperty(
        name="Variant",
        description=strings.SCENE_TOOLS_ADD_RMI_SURFACE_MATERIAL_VARIANT,
        default="",
        search=_search_rmi_variants,
        search_options={"SUGGESTION", "SORT"},
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and hasattr(getattr(obj, "data", None), "materials")

    def draw(self, _context):
        self.layout.prop(self, "variant")

    def execute(self, context):
        obj = context.active_object
        try:
            master, variant_helper, ground_truth = rmi_surface._modules()
            requested = self.variant.strip()
            if requested:
                variant_name = requested if requested.startswith("RMI_Surface_") else (
                    "RMI_Surface_" + requested
                )
                switches = ground_truth.get(variant_name)
                if switches is None:
                    report(self, {"ERROR"}, "Choose a variant from the search list.")
                    return {"CANCELLED"}
                master = rmi_surface._master_for_switches(switches)
            master_material = rmi_surface._ensure_master(master)
            material = master_material.copy()
            if requested:
                material.name = variant_name
                variant_helper.apply_variant(material, master, variant_name, set(switches))
                material["sqex_rmi_variant"] = variant_name
            else:
                material.name = "Rebirth RMI Surface"
                material["sqex_rmi_variant"] = ""

            slots = obj.data.materials
            if slots:
                slot_index = min(max(0, obj.active_material_index), len(slots) - 1)
                slots[slot_index] = material
                obj.active_material_index = slot_index
            else:
                slots.append(material)
                obj.active_material_index = 0
            report(self, {"INFO"}, "Added " + material.name)
            return {"FINISHED"}
        except Exception as exc:
            report(self, {"ERROR"}, "Could not create RMI surface: " + str(exc))
            return {"CANCELLED"}


class ARMATURE_OT_connect_parent_tail_to_bone(SQEX_LoggedOperator):
    bl_idname = "armature.connect_parent_tail_to_bone"
    bl_label = "Move Parent Tail Here and Connect"
    bl_description = (
        strings.SCENE_TOOLS_CONNECT_PARENT_TAIL_TO_BONE_DESCRIPTION
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        armature = context.object
        bone = context.active_bone
        return (
            armature is not None
            and armature.type == "ARMATURE"
            and armature.mode == "EDIT"
            and bone is not None
            and bone.parent is not None
        )

    def execute(self, context):
        bone = context.active_bone
        parent = bone.parent
        parent.tail = bone.head
        bone.use_connect = True
        report(self, {"INFO"}, f"Connected '{bone.name}' to '{parent.name}' without moving its head")
        return {"FINISHED"}


CLASSES = (
    OBJECT_OT_add_rmi_surface_material,
    ARMATURE_OT_connect_parent_tail_to_bone,
)

