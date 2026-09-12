"""Small shared operators exposed by the add-on menus."""

from __future__ import annotations

import bpy
from bpy.props import StringProperty

from ..core.blender.reporting import FF7R_LoggedOperator
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


class OBJECT_OT_add_rmi_surface_material(FF7R_LoggedOperator):
    """Put a fresh RMI_Surface master or trimmed variant in the active slot."""

    bl_idname = "object.ff7r_add_rmi_surface_material"
    bl_label = "Add FF7R RMI Surface Material"
    bl_description = (
        "Create a new FF7R RMI Surface material in the active material slot; "
        "leave Variant blank for the full master"
    )
    bl_options = {"REGISTER", "UNDO"}

    variant: StringProperty(
        name="Variant",
        description="Choose an RMI_Surface variant or leave blank for the complete master",
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
            master_material = rmi_surface._ensure_master(master)
            material = master_material.copy()
            requested = self.variant.strip()
            if requested:
                variant_name = requested if requested.startswith("RMI_Surface_") else (
                    "RMI_Surface_" + requested
                )
                switches = ground_truth.get(variant_name)
                if switches is None:
                    bpy.data.materials.remove(material)
                    self.report({"ERROR"}, "Choose a variant from the search list.")
                    return {"CANCELLED"}
                material.name = variant_name
                variant_helper.apply_variant(material, master, variant_name, set(switches))
                material["ff7r_rmi_variant"] = variant_name
            else:
                material.name = "FF7R RMI Surface"
                material["ff7r_rmi_variant"] = ""

            slots = obj.data.materials
            if slots:
                slot_index = min(max(0, obj.active_material_index), len(slots) - 1)
                slots[slot_index] = material
                obj.active_material_index = slot_index
            else:
                slots.append(material)
                obj.active_material_index = 0
            self.report({"INFO"}, "Added " + material.name)
            return {"FINISHED"}
        except Exception as exc:
            self.report({"ERROR"}, "Could not create RMI surface: " + str(exc))
            return {"CANCELLED"}


class ARMATURE_OT_connect_parent_tail_to_bone(FF7R_LoggedOperator):
    bl_idname = "armature.connect_parent_tail_to_bone"
    bl_label = "Move Parent Tail Here and Connect"
    bl_description = (
        "Move the active bone's parent's tail to this bone's head, then connect "
        "the active bone without moving its head"
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
        self.report({"INFO"}, f"Connected '{bone.name}' to '{parent.name}' without moving its head")
        return {"FINISHED"}


CLASSES = (
    OBJECT_OT_add_rmi_surface_material,
    ARMATURE_OT_connect_parent_tail_to_bone,
)

