"""Neutral AnimSequence loading, with no title-specific root or bone rules."""

from ...language import strings

import math

import bpy
from mathutils import Matrix, Vector

from ...core.blender import skeletons
from ...core.blender.reporting import SQEX_LoggedOperator, report
from ...games import package_browser
from ...core.blender import animation as curves
from . import importer, session


_BROWSER = package_browser.make_state("compatible Unreal AnimSequence assets", file_icon="ARMATURE_DATA")
_INDEX = {}


def source_property(armature, name, default=None):
    return armature.get(name, armature.data.get(name, default))


def skeleton_path(armature):
    return (source_property(armature, "ue_skeleton_path")
            or curves._selected_armature_skeleton_path(armature))


def _identity(path):
    path = str(path or "").replace("\\", "/").strip()
    if "'" in path:
        path = path.split("'", 1)[1].rstrip("'")
    path = path.split(":", 1)[0]
    return path.rsplit(".", 1)[0].casefold() if "." in path.rsplit("/", 1)[-1] else path.casefold()


def _transform(translation, rotation, scale, factor):
    return skeletons.ue_bone_transform_to_blender(tuple(translation), tuple(rotation), factor, tuple(scale))


def import_animation_asset(armature, virtual_path, animation, *, start_frame=1.0,
                           replace_current_action=True, use_fake_user=True, scene=None,
                           scale_factor=None):
    """Bake an ordinary local-bone clip to an Action on a generic package rig.

    Carry animated/bind global deltas onto the actual edit-bone rest matrices.
    This removes the display-axis convention without assuming a special root
    track, and cancels reference scales already baked into imported geometry.
    No cross-skeleton retargeting or animation-blueprint evaluation is done.
    """
    if armature is None or armature.type != "ARMATURE":
        raise ValueError("Select a generic imported armature first.")
    target_path = skeleton_path(armature)
    if not target_path or _identity(target_path) not in {
            _identity(animation.get("skeletonPath")), _identity(animation.get("linkedSkeletonPath"))}:
        raise ValueError("This animation is not linked to the armature's source Skeleton.")
    factor = float(scale_factor if scale_factor is not None else source_property(armature, "ue_import_scale", 0.01))
    if not math.isfinite(factor) or factor <= 0:
        raise ValueError("The model's import scale must be positive.")
    bones = (animation.get("referenceSkeleton") or {}).get("bones") or []
    tracks = {track["boneName"]: track for track in animation.get("tracks") or []}
    if not bones or not any(name in armature.data.bones for name in tracks):
        raise ValueError("No decoded animation tracks match this armature.")
    count = max(1, int(animation.get("numFrames") or 1))
    fps = float(animation.get("framesPerSecond") or 30.0)
    if not math.isfinite(fps) or fps <= 0:
        raise ValueError("The clip has an invalid sample rate.")
    scene = scene or bpy.context.scene
    frame_scale = scene.render.fps / scene.render.fps_base / fps
    forward = (skeletons.Y_FORWARD_ROTATION if source_property(armature, skeletons.FACE_FORWARD_PROPERTY)
               == skeletons.FACE_FORWARD_BLENDER else Matrix.Identity(4))
    bind_globals, samplers, targets = [], [], {}
    for index, source in enumerate(bones):
        parent = int(source.get("parentIndex", -1))
        if parent < -1 or parent >= index:
            raise ValueError("The animation Skeleton is not in parent-first order.")
        translation = source.get("translation") or (0, 0, 0)
        rotation = source.get("rotation") or (0, 0, 0, 1)
        scale = source.get("scale") or (1, 1, 1)
        local = _transform(translation, rotation, scale, factor)
        bind = (bind_globals[parent] if parent >= 0 else forward) @ local
        bind_globals.append(bind)
        track = tracks.get(source["name"], {})
        translations, rotations, scales = (list(track.get(key) or []) for key in ("translations", "rotations", "scales"))
        # Generic bridge output is uniformly sampled. Explicit channel times
        # remain supported for fixtures and future sparse-track exporters.
        times = lambda values, key: curves._key_times(values, list(track.get(key) or range(len(values))), count)
        samplers.append((parent,
            curves._vector_sampler(translations, times(translations, "translationFrames"), Vector(translation)),
            curves._ue_quaternion_sampler(rotations, times(rotations, "rotationFrames"), tuple(rotation)),
            curves._vector_sampler(scales, times(scales, "scaleFrames"), Vector(scale))))
        bone = armature.data.bones.get(source["name"])
        if bone is not None:
            targets[index] = (bone, bind.inverted_safe() @ bone.matrix_local, [], [], [])
    target_indices = {bone.name: index for index, (bone, *_) in targets.items()}
    for bone, *_ in targets.values():
        if bone.parent and bone.parent.name not in target_indices:
            raise ValueError(f"Bone '{bone.name}' has a parent absent from the source Skeleton.")

    for frame in range(count):
        globals_ = []
        for parent, translation, rotation, scale in samplers:
            local = _transform(translation(frame), rotation(frame), scale(frame), factor)
            globals_.append((globals_[parent] if parent >= 0 else forward) @ local)
        poses = {index: globals_[index] @ target[1] for index, target in targets.items()}
        for index, (bone, _offset, translations, rotations, scales) in targets.items():
            parent_args = ({"parent_matrix": poses[target_indices[bone.parent.name]],
                            "parent_matrix_local": bone.parent.matrix_local} if bone.parent else {})
            basis = bone.convert_local_to_pose(poses[index], bone.matrix_local, invert=True, **parent_args)
            location, rotation, scale = basis.decompose()
            if rotations and rotation.dot(rotations[-1]) < 0:
                rotation.negate()
            translations.append(tuple(location))
            rotations.append(rotation)
            scales.append(tuple(scale))
    action = bpy.data.actions.new(f"{armature.name} | {animation.get('name') or virtual_path.rsplit('/', 1)[-1]}")
    try:
        action.use_fake_user = use_fake_user
        new_curve, slot = curves._action_curves(action, armature)
        key_count = 0
        frames = list(range(count))
        for bone, _offset, translations, rotations, scales in targets.values():
            path = 'pose.bones["' + bpy.utils.escape_identifier(bone.name) + '"]'
            for channel, values in (("location", translations), ("rotation_quaternion", rotations), ("scale", scales)):
                key_count += curves._insert_keys(new_curve, bone.name, path + "." + channel,
                                                  values, frames, frame_scale, start_frame)
        action["ue_animation_path"] = virtual_path
        action["sqex_animation_virtual_path"] = virtual_path
        action["ue_skeleton_path"] = target_path
        action["ue_source_fps"] = fps
        action["ue_source_duration"] = float(animation.get("duration") or 0)
        action["ue_import_scale"] = factor
        action["ue_additive_baked"] = bool(animation.get("additiveBaked"))
        action.frame_start = start_frame
        action.frame_end = start_frame + max((count - 1) * frame_scale,
                                             action["ue_source_duration"] * scene.render.fps / scene.render.fps_base)
        for bone, *_ in targets.values():
            armature.pose.bones[bone.name].rotation_mode = "QUATERNION"
        if replace_current_action:
            data = armature.animation_data_create()
            data.action = action
            if slot is not None:
                data.action_slot = slot
        return action, len(targets), key_count, len(set(tracks) - set(target_indices))
    except Exception:
        bpy.data.actions.remove(action)
        raise


def _key(context, operator):
    armature = context.active_object
    if armature is None or armature.type != "ARMATURE" or not skeleton_path(armature):
        raise ValueError("Select an armature imported from a generic SkeletalMesh first.")
    return (session.source_id(importer._paths(context, operator, validate=False), importer._game_version(context, operator)),
            _identity(skeleton_path(armature)), operator.path_filter.strip())


def _activate(context, paths):
    package_browser.activate(context, _BROWSER, paths, dialog_operator=SQEX_OT_import_generic_unreal_animation.bl_idname)


def _config_properties():
    properties = importer._configuration_properties()
    return {key: properties[key] for key in ("cue4parse_profile", "path_filter")}


class SQEX_OT_index_generic_unreal_animation(SQEX_LoggedOperator):
    bl_idname = "wm.sqex_index_generic_unreal_animation"
    bl_label = "Load / Refresh Compatible Animations"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        try:
            key = _key(context, self)
            with session.GenericSession(importer._paths(context, self), importer._game_version(context, self)) as mounted:
                index = mounted.request({"action": "generic_animation_index", "skeletonAssetPath": skeleton_path(context.active_object),
                                         "pathFilter": self.path_filter.strip()})["index"]
            _INDEX[key] = index
            _activate(context, index.get("paths") or [])
            for warning in index.get("warnings") or []:
                print(f"[Unreal animation WARNING] {warning}")
            report(self, {"WARNING"} if index.get("warnings") else {"INFO"},
                   f"Found {len(index.get('paths') or []):,} compatible AnimSequence assets.")
            return {"FINISHED"}
        except Exception as exc:
            report(self, {"ERROR"}, f"Animation indexing failed: {exc}")
            return {"CANCELLED"}


SQEX_OT_index_generic_unreal_animation.__annotations__ = _config_properties()


class SQEX_OT_import_generic_unreal_animation(SQEX_LoggedOperator):
    bl_idname = "object.sqex_import_generic_unreal_animation"
    bl_label = "Import Generic Unreal Animations"
    bl_description = strings.GENERIC_ANIMATION_DESCRIPTION
    bl_options = {"REGISTER", "UNDO"}

    virtual_path: bpy.props.StringProperty(name="Animation Package", description=strings.GENERIC_PACKAGE_PATH)
    start_frame: bpy.props.IntProperty(name="Start Frame", default=1)
    replace_current_action: bpy.props.BoolProperty(name="Set as Active Action", default=True)
    use_fake_user: bpy.props.BoolProperty(name="Keep Unused Actions", default=True)
    scale_factor: bpy.props.FloatProperty(name="Model Import Scale", default=0.01, min=0.000001,
        description=strings.GENERIC_ANIMATION_SCALE_FACTOR)

    @classmethod
    def poll(cls, context):
        return context.active_object is not None and context.active_object.type == "ARMATURE"

    def invoke(self, context, _event):
        self._load_last_import_settings(context)
        try:
            _prefs, profiles = importer._profiles(context)
            profile_id = source_property(context.active_object, "ue_profile_id")
            if any(profile.profile_id == profile_id for profile in profiles):
                self.cue4parse_profile = profile_id
            self.scale_factor = source_property(context.active_object, "ue_import_scale", 0.01)
            self.start_frame = context.scene.frame_current
            self._browser_key = _key(context, self)
            _activate(context, (_INDEX.get(self._browser_key) or {}).get("paths") or [])
        except Exception as exc:
            report(self, {"ERROR"}, str(exc))
            return {"CANCELLED"}
        return context.window_manager.invoke_props_dialog(self, width=1000)

    def check(self, context):
        key = _key(context, self)
        if key != getattr(self, "_browser_key", None):
            _activate(context, (_INDEX.get(key) or {}).get("paths") or [])
            self._browser_key = key
        return True

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "cue4parse_profile")
        layout.label(text="Game paths, mappings and keys are shared with the generic model importer.", icon="PREFERENCES")
        layout.prop(self, "path_filter")
        refresh = layout.operator(SQEX_OT_index_generic_unreal_animation.bl_idname, icon="FILE_REFRESH")
        refresh.cue4parse_profile, refresh.path_filter = self.cue4parse_profile, self.path_filter
        package_browser.draw(layout, context, _BROWSER, rows=9)
        layout.prop(self, "virtual_path")
        for name in ("start_frame", "scale_factor", "replace_current_action", "use_fake_user"):
            layout.prop(self, name)
        layout.label(text="Bone animation only; no montages, morph curves, notifies or Blueprint logic.", icon="INFO")

    def execute(self, context):
        imported, failures = [], []
        try:
            armature = context.active_object
            index = _INDEX.get(_key(context, self))
            if not self.virtual_path.strip() and index is None:
                raise ValueError("Load the compatible animation list first.")
            virtual_paths = ([self.virtual_path.strip()] if self.virtual_path.strip() else
                             package_browser.selected_paths(context, _BROWSER))
            if not virtual_paths:
                raise ValueError("Select at least one animation.")
            if index is not None and not self.virtual_path.strip() and not set(virtual_paths) <= set(index.get("paths") or []):
                raise ValueError("The browser selection no longer matches the selected game and Skeleton. Refresh the list.")
            with session.GenericSession(importer._paths(context, self), importer._game_version(context, self)) as mounted:
                for path in virtual_paths:
                    try:
                        animation = mounted.animation_asset(path)
                        imported.append(import_animation_asset(armature, path, animation, scene=context.scene,
                            start_frame=self.start_frame, scale_factor=self.scale_factor,
                            replace_current_action=self.replace_current_action, use_fake_user=self.use_fake_user))
                    except Exception as exc:
                        failures.append(f"{path}: {exc}")
                        print(f"[Unreal animation ERROR] {failures[-1]}")
            if not imported:
                raise ValueError(failures[0] if failures else "No animations imported.")
            context.scene.frame_set(context.scene.frame_current)
            report(self, {"WARNING"} if failures else {"INFO"},
                   f"Imported {len(imported):,} Actions, {sum(result[2] for result in imported):,} keys; {len(failures):,} failures.")
            self._save_last_import_settings(context)
            return {"FINISHED"}
        except Exception as exc:
            report(self, {"ERROR"}, f"Unreal animation import failed: {exc}")
            return {"CANCELLED"}


SQEX_OT_import_generic_unreal_animation.__annotations__.update(_config_properties())
SQEX_OT_import_generic_unreal_animation._persisted_props = ("path_filter", "replace_current_action", "use_fake_user")
CLASSES = (SQEX_OT_index_generic_unreal_animation, SQEX_OT_import_generic_unreal_animation)
