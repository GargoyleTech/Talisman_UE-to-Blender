"""Shared animation picker, package session and per-clip reporting workflow."""

from ..language import strings

import traceback

import bpy

from ..core.blender.reporting import SQEX_LoggedOperator, report
from ..formats import unreal_package
from . import package_browser


def make_animation_importer(
    *,
    class_name,
    module_name,
    bl_idname,
    game_name,
    profile,
    configured_paths,
    compatible_paths,
    import_animation,
    browser,
    rest_tolerance=None,
):
    """Keep title decoding and compatibility policy outside Blender UI code."""

    def selected_armature(context):
        armature = context.active_object
        if armature is None or armature.type != "ARMATURE":
            raise ValueError("Select the armature that should receive the animation.")
        return armature

    def search(_self, _context, edit_text):
        return unreal_package._search_virtual_paths(
            browser["paths"],
            edit_text,
            sort_key=unreal_package._natural_path_key,
        )

    @classmethod
    def poll(cls, context):
        return (
            context.active_object is not None
            and context.active_object.type == "ARMATURE"
        )

    def invoke(self, context, _event):
        try:
            paths = compatible_paths(context, selected_armature(context))
            if not paths:
                report(
                    self,
                    {"WARNING"},
                    f"No {game_name} AnimSequence assets were found for this rig.",
                )
                return {"CANCELLED"}
            self.start_frame = context.scene.frame_current
            self._load_last_import_settings(context)
            package_browser.activate(
                context, browser, paths, dialog_operator=self.bl_idname
            )
            return context.window_manager.invoke_props_dialog(self, width=1000)
        except Exception as exc:
            report(self, {"ERROR"}, f"{game_name} animation index failed: {exc}")
            return {"CANCELLED"}

    def draw(self, context):
        package_browser.draw(self.layout, context, browser)
        self.layout.prop(self, "start_frame")
        self.layout.prop(self, "replace_current_action")
        self.layout.prop(self, "use_fake_user")
        self.layout.label(
            text="Uses the scene frame rate and the rig's recorded bone convention.",
            icon="INFO",
        )

    def execute(self, context):
        try:
            armature = selected_armature(context)
            paths = configured_paths(context)
            browser["paths"] = list(compatible_paths(context, armature))
            selected = package_browser.resolve_paths(
                context, browser, self.virtual_path
            )
            if not selected:
                raise ValueError(
                    "Select at least one animation in the package browser."
                )
            imported, failures = [], []
            with unreal_package.PackageAssetSession(
                paths.install_root,
                paths.oodle_dll,
                paths.usmap_path,
                profile=profile,
                aes_key=paths.aes_key,
            ) as session:
                for virtual_path in selected:
                    try:
                        payload = session.animation_asset(virtual_path)
                        imported.append(
                            import_animation(
                                armature,
                                virtual_path,
                                payload,
                                start_frame=self.start_frame,
                                replace_current_action=self.replace_current_action,
                                use_fake_user=self.use_fake_user,
                                scene=context.scene,
                            )
                        )
                    except Exception as exc:
                        print(f"[{game_name} animation ERROR] {virtual_path}: {exc}")
                        traceback.print_exc()
                        failures.append(virtual_path)
        except Exception as exc:
            report(self, {"ERROR"}, f"{game_name} animation import failed: {exc}")
            return {"CANCELLED"}
        if not imported:
            report(
                self,
                {"ERROR"},
                "No animation actions were imported; see the console for details.",
            )
            return {"CANCELLED"}
        bones = sum(result[1] for result in imported)
        keys = sum(result[2] for result in imported)
        skipped = sum(result[3] for result in imported)
        if rest_tolerance is not None:
            error = max(result[4] for result in imported)
            if error > rest_tolerance:
                report(
                    self,
                    {"WARNING"},
                    f"'{armature.name}' rest pose differs from the animation bind pose by {error:.3f}. Import the package Skeleton for the expected bone frame.",
                )
        report(
            self,
            {"INFO"},
            f"Imported {len(imported)} {game_name} action(s) to '{armature.name}': "
            f"{bones} bone(s), {keys:,} channel key(s)"
            + (f"; skipped {skipped} unavailable bone(s)" if skipped else ""),
        )
        if failures:
            report(
                self,
                {"WARNING"},
                f"{len(failures)} selected animation(s) failed; see the console for details.",
            )
        self._save_last_import_settings(context)
        return {"FINISHED"}

    return type(
        class_name,
        (SQEX_LoggedOperator,),
        {
            "__module__": module_name,
            "__annotations__": {
                "virtual_path": bpy.props.StringProperty(
                    name="Animation Path", search=search, search_options={"SUGGESTION"}
                ),
                "start_frame": bpy.props.IntProperty(name="Start Frame", default=1),
                "replace_current_action": bpy.props.BoolProperty(
                    name="Set as Active Action", default=True
                ),
                "use_fake_user": bpy.props.BoolProperty(name="Fake User", default=True),
            },
            "bl_idname": bl_idname,
            "bl_label": f"Import {game_name} Animations",
            "bl_description": strings.ANIMATION_IMPORT.format(game_name=game_name),
            "bl_options": {"REGISTER", "UNDO"},
            "_persisted_props": ("replace_current_action", "use_fake_user"),
            "poll": poll,
            "invoke": invoke,
            "draw": draw,
            "execute": execute,
        },
    )
