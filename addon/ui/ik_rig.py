"""Repair earlier generated limb controls, without an additional sidebar."""

from ..language import tooltips

from ..core.blender import ik_rig
from ..core.blender.reporting import SQEX_LoggedOperator, report


def _armature(context):
    obj = context.object
    return (obj if obj.type == "ARMATURE" else obj.find_armature()) if obj else None


class OBJECT_OT_repair_limb_ik(SQEX_LoggedOperator):
    bl_idname = "object.sqex_repair_limb_ik"
    bl_label = "Repair Generated Limb IK"
    bl_description = tooltips.SCENE_TOOLS_REPAIR_LIMB_IK_DESCRIPTION
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode in {"OBJECT", "POSE"} and _armature(context) is not None

    def execute(self, context):
        count = ik_rig.repair_limb_ik(_armature(context))
        report(self, {"INFO"}, f"Updated {count} straight limb(s) with persistent IK bend hints")
        return {"FINISHED"}


CLASSES = (OBJECT_OT_repair_limb_ik,)
