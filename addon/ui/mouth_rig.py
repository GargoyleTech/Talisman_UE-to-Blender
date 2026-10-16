"""Artist controls for the optional generated Rebirth jaw layer."""

from ..language import tooltips

from ..core.blender import mouth_rig
from ..core.blender.reporting import SQEX_LoggedOperator, report


def _armature(context):
    obj = context.object
    if obj is None:
        return None
    return obj if obj.type == "ARMATURE" else obj.find_armature()


class OBJECT_OT_generate_mouth_controls(SQEX_LoggedOperator):
    bl_idname = "object.sqex_generate_mouth_controls"
    bl_label = "Generate Mouth Controls (experimental)"
    bl_description = tooltips.SCENE_TOOLS_GENERATE_MOUTH_CONTROLS_DESCRIPTION
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode in {"OBJECT", "POSE"} and _armature(context) is not None

    def execute(self, context):
        try:
            count = mouth_rig.generate_mouth_rig(context, _armature(context))
        except Exception as exc:
            report(self, {"ERROR"}, str(exc))
            return {"CANCELLED"}
        report(self, {"INFO"}, f"Mouth controls ready: jaw drives {count} bones; settings are on the control bones")
        return {"FINISHED"}


class OBJECT_OT_remove_mouth_controls(SQEX_LoggedOperator):
    bl_idname = "object.sqex_remove_mouth_controls"
    bl_label = "Remove Generated Mouth Controls"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        armature = _armature(context)
        return (context.mode in {"OBJECT", "POSE"} and armature is not None
                and bool(armature.get(mouth_rig.RIG_PROPERTY)))

    def execute(self, context):
        try:
            mouth_rig.remove_mouth_rig(context, _armature(context))
        except Exception as exc:
            report(self, {"ERROR"}, str(exc))
            return {"CANCELLED"}
        report(self, {"INFO"}, "Removed generated mouth controls")
        return {"FINISHED"}


CLASSES = (
    OBJECT_OT_generate_mouth_controls,
    OBJECT_OT_remove_mouth_controls,
)
