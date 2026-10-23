"""Import a stock LevelSequence graph as ordinary Blender animation data."""

from collections import defaultdict
import json
import math

import bpy
from mathutils import Euler, Matrix, Vector

from ...core.blender import animation as action_curves
from ...core.blender import skeletons
from ..ue_map import lights
from . import animations
from .sequence_bindings import Resolver, armature_for, children, transform, visual_for
from .sequence_data import Channel, Graph, asset_path, bounds, guid, number, value


new_curves = action_curves._action_curves

def channel(data, graph, label, default=0):
    result = Channel(data, default)
    if result.weighted:
        graph.warn(f"Weighted tangents approximated by unweighted cubic samples: {label}")
    return result


def easing_weight(instance, section, tick):
    properties = section.get("Properties") or {}
    lower, upper = bounds(properties, instance.sequence.playback)
    easing = properties.get("Easing") or {}
    weight = 1.0
    for side, distance in (("In", tick-lower), ("Out", upper-tick)):
        duration = number(easing.get(("Manual" if easing.get("bManualEase"+side) else "Auto") + "Ease" + side + "Duration"))
        if duration > 0:
            fraction = min(1.0, max(0.0, distance / duration))
            # Built-in easing's default is Linear. Report non-default functions
            # at planning time; do not claim exact arbitrary easing evaluation.
            weight *= fraction
    return weight


def _blend_type(properties):
    result = str(value(properties.get("BlendType"), "Absolute"))
    return "Additive" if "Additive" in result and "FromBase" not in result else "Absolute" if result in ("Absolute", "0") or "Absolute" in result or result.startswith("{") else result


class Importer:
    def __init__(self, context, mounted, path, *, start_frame=1, factor=0.01, load_missing=True,
                 import_models=True, import_cameras=True, import_lights=True, import_animation=True,
                 replace_existing=False, overrides=None, max_samples=100000):
        self.context, self.scene, self.mounted = context, context.scene, mounted
        self.graph = Graph(lambda path: mounted.request({"action": "generic_sequence", "assetPath": path})["sequence"], path)
        self.start_frame, self.factor = start_frame, factor
        self.fps = self.scene.render.fps / self.scene.render.fps_base
        self.end_frame = start_frame + self.graph.duration * self.fps
        if self.end_frame - start_frame > max_samples:
            raise ValueError(f"Sequence exceeds the {max_samples:,}-sample safety limit.")
        self.initial_objects = {obj.as_pointer() for obj in bpy.data.objects}
        self.initial_actions = {action.as_pointer() for action in bpy.data.actions}
        self.initial_markers = {marker.as_pointer() for marker in self.scene.timeline_markers}
        self.original_camera = self.scene.camera
        self.original_range = self.scene.frame_start, self.scene.frame_end
        self.original_frame = self.scene.frame_current, self.scene.frame_subframe
        self.snapshots, self.added_tracks, self.added_constraints = {}, [], []
        self.data_copies = []
        self.report_text = None
        self.collection = bpy.data.collections.new(asset_path(path).rsplit("/", 1)[-1])
        self.scene.collection.children.link(self.collection)
        self.collection["ue_sequence_path"] = path
        self.collection["ue_source_id"] = mounted.cache_namespace
        self.resolver = Resolver(context, mounted, self.graph, self.collection, factor=factor, load_missing=load_missing,
            import_models=import_models, import_cameras=import_cameras, import_lights=import_lights, overrides=overrides)
        self.import_cameras, self.import_lights, self.import_animation = import_cameras, import_lights, import_animation
        self.replace_existing = replace_existing
        self.prepared = {}
        self.object_tracks, self.data_tracks = defaultdict(list), defaultdict(list)
        self.visibility, self.clip_specs, self.attach_specs, self.cuts = defaultdict(list), defaultdict(list), [], []
        self.actions = []
        self.stats = {"sequenceInstances": len(self.graph.instances), "bindings": 0, "resolvedBindings": 0,
                      "actions": 0, "animationStrips": 0, "cameraCuts": 0, "attachments": 0, "unsupportedTracks": 0}
        self.stats["authoredAnimationSections"] = sum(len(instance.sequence.sections(track)) for instance in self.graph.instances
            for tracks in instance.sequence.tracks.values() for track in tracks if track.get("Type") == "MovieSceneSkeletalAnimationTrack")

    def frame(self, seconds):
        return self.start_frame + seconds * self.fps

    def samples(self, extra=()):
        # Sample both sides of section boundaries so linear baked curves do
        # not fade or jump a whole scene frame before a discrete section edge.
        boundaries = [self.frame(time) for time in extra]
        return sorted({float(self.start_frame), float(self.end_frame),
                       *map(float, range(math.ceil(self.start_frame), math.ceil(self.end_frame))),
                       *(max(self.start_frame, min(self.end_frame, frame + offset))
                         for frame in boundaries for offset in (-0.0001, 0))})

    def available(self, target):
        if target in self.prepared:
            return self.prepared[target]
        data = target.animation_data
        self.snapshots[target] = {
            "action": data.action if data else None,
            "slot": getattr(data, "action_slot", None) if data else None,
            "fake_user": data.action.use_fake_user if data and data.action else False,
            "tracks": [(track, track.mute) for track in data.nla_tracks] if data else [],
        }
        if isinstance(target, bpy.types.Object):
            self.snapshots[target].update(matrix=target.matrix_basis.copy(), rotation_mode=target.rotation_mode,
                hidden=(target.hide_viewport, target.hide_render),
                bone_modes={bone.name: bone.rotation_mode for bone in target.pose.bones} if target.pose else {})
        else:
            self.snapshots[target]["values"] = {path: tuple(sample) if hasattr(sample, "__len__") else sample
                for path in ("lens", "sensor_width", "sensor_height", "dof.focus_distance", "dof.aperture_fstop", "energy", "color")
                if (sample := self._read_property(target, path)) is not None}
        occupied = data is not None and (data.action is not None or any(not track.mute for track in data.nla_tracks))
        if occupied and not self.replace_existing:
            self.graph.warn(f"Existing animation preserved; skipped animation on {target.name}. Enable Replace Existing Animation to apply it.")
            self.prepared[target] = False
        else:
            if occupied:
                if data.action:
                    data.action.use_fake_user = True
                    data.action = None
                for track in data.nla_tracks:
                    track.mute = True
            self.prepared[target] = True
        return self.prepared[target]

    @staticmethod
    def _read_property(target, path):
        try:
            return target.path_resolve(path)
        except (ValueError, AttributeError):
            return None

    def rollback(self):
        """Remove only this import and restore occupied targets on fatal failure."""
        for owner, constraint in reversed(self.added_constraints):
            owner.constraints.remove(constraint)
        for owner, track in reversed(self.added_tracks):
            owner.animation_data.nla_tracks.remove(track)
        for target, snapshot in self.snapshots.items():
            data = target.animation_data
            if data:
                data.action = snapshot["action"]
                if snapshot["action"]:
                    snapshot["action"].use_fake_user = snapshot["fake_user"]
                    if snapshot["slot"] is not None:
                        data.action_slot = snapshot["slot"]
                for track, mute in snapshot["tracks"]:
                    track.mute = mute
            if "matrix" in snapshot:
                target.rotation_mode = snapshot["rotation_mode"]
                target.matrix_basis = snapshot["matrix"]
                target.hide_viewport, target.hide_render = snapshot["hidden"]
                for name, mode in snapshot["bone_modes"].items():
                    target.pose.bones[name].rotation_mode = mode
            for path, value in snapshot.get("values", {}).items():
                parts = path.rsplit(".", 1)
                parent, key = (target.path_resolve(parts[0]), parts[1]) if len(parts) > 1 else (target, path)
                setattr(parent, key, value)
            if 'light_controls' in snapshot:
                for name, value in snapshot['light_controls'].items():
                    target[name] = value
                for name, value in snapshot['light_animation_flags'].items():
                    if value is None:
                        if name in target:
                            del target[name]
                    else:
                        target[name] = value
                from ..ue_map.light_rig import ensure_source_helpers
                ensure_source_helpers(target)
        self.scene.camera = self.original_camera
        self.scene.frame_start, self.scene.frame_end = self.original_range
        for marker in list(self.scene.timeline_markers):
            if marker.as_pointer() not in self.initial_markers:
                self.scene.timeline_markers.remove(marker)
        for visual, original, copied in self.data_copies:
            visual.data = original
        for obj in list(self.collection.all_objects):
            if obj.as_pointer() not in self.initial_objects:
                bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.collections.remove(self.collection)
        for action in list(bpy.data.actions):
            if action.as_pointer() not in self.initial_actions and action.users <= int(action.use_fake_user):
                bpy.data.actions.remove(action)
        for visual, original, copied in self.data_copies:
            if copied.users == 0:
                (bpy.data.cameras if isinstance(copied, bpy.types.Camera) else bpy.data.lights).remove(copied)
        if self.report_text:
            bpy.data.texts.remove(self.report_text)
        self.scene.frame_set(self.original_frame[0], subframe=self.original_frame[1])

    def add_action(self, target, channels, frames, *, constant=False):
        if not channels or not self.available(target):
            return None
        action = bpy.data.actions.new(self.collection.name + " | " + target.name)
        action.use_fake_user = True
        action["ue_sequence_path"] = self.collection["ue_sequence_path"]
        new_curve, slot = new_curves(action, target)
        for path, samples in channels.items():
            action_curves._insert_keys(new_curve, target.name, path, samples, frames, 1, 0)
        if constant:
            curves = getattr(action, "fcurves", None)
            if curves is None:
                curves = action.layers[0].strips[0].channelbag(slot).fcurves
            for curve in curves:
                for point in curve.keyframe_points:
                    point.interpolation = "CONSTANT"
        action.frame_start, action.frame_end = self.start_frame, self.end_frame
        track = target.animation_data_create().nla_tracks.new()
        self.added_tracks.append((target, track))
        track.name = "UE " + self.collection.name
        strip = track.strips.new(action.name, math.floor(self.start_frame), action)
        # strips.new selects the single compatible slot. Reassigning the same
        # slot with no active Action can crash Blender 5.1's NLA RNA setter.
        strip.frame_start = self.start_frame
        strip.frame_end = max(self.start_frame + 0.0001, self.end_frame)
        strip.extrapolation = "NOTHING"
        strip.blend_type = "REPLACE"
        self.actions.append(action)
        self.stats["actions"] += 1
        return action

    def binding_reference(self, instance, reference):
        if not isinstance(reference, dict):
            return None
        parents = int(number(reference.get("ResolveParentIndex")))
        current = instance
        for _ in range(parents):
            current = current.parent if current else None
        sequence_id = value(reference.get("SequenceID"), 0)
        if sequence_id not in (0, "0", None):
            # A cooked SequenceID is hierarchy-local. A GUID is safe as a
            # fallback only when every matching instance resolves to the same
            # concrete actor; never guess among repeated spawned instances.
            matches = [self.resolver.resolve(candidate, reference.get("Guid")) for candidate in self.graph.instances
                       if guid(reference.get("Guid")) in candidate.sequence.bindings]
            matches = {match.root.as_pointer(): match for match in matches if match is not None}
            if len(matches) == 1:
                return next(iter(matches.values()))
            self.graph.warn(f"Non-local sequence binding ID is not resolved: {reference}")
            return None
        return self.resolver.resolve(current, reference.get("Guid")) if current else None

    def _sections(self, instance, track):
        for section in instance.sequence.sections(track):
            lower, upper = instance.section_range(section)
            if upper <= lower:
                continue
            easing = section.get("Properties", {}).get("Easing") or {}
            for side in ("EaseIn", "EaseOut"):
                function = instance.sequence.resolve((easing.get(side) or {}).get("Object"))
                if function and (function.get("Properties") or {}).get("Type") not in (None, "Linear", "EMovieSceneBuiltInEasing::Linear"):
                    self.graph.warn(f"Non-linear section easing approximated as linear: {section.get('Name')}")
            yield section, lower, upper

    def plan(self):
        for instance, binding_id, binding in self.graph.bindings():
            self.stats["bindings"] += 1
            actor = self.resolver.resolve(instance, binding_id)
            if actor:
                self.stats["resolvedBindings"] += 1
            tracks = instance.sequence.tracks.get(binding_id) or []
            if actor and binding.get("spawned") and not any(track.get("Type") == "MovieSceneSpawnTrack" for track in tracks):
                self.visibility[actor.root].append((instance, Channel({"DefaultValue": True, "bHasDefaultValue": True}),
                                                    instance.clip[0], instance.clip[1], True))
            for track in tracks:
                kind = track.get("Type") or ""
                if kind == "MovieScene3DTransformTrack":
                    if actor:
                        self.object_tracks[actor.root].extend((instance, section, lo, hi) for section, lo, hi in self._sections(instance, track))
                elif kind == "MovieSceneSkeletalAnimationTrack":
                    if actor and self.import_animation:
                        rig = armature_for(actor.root)
                        if rig:
                            self.clip_specs[rig].extend((instance, section, lo, hi) for section, lo, hi in self._sections(instance, track))
                        else:
                            self.graph.warn(f"No unique armature for animation binding {binding.get('Name')}")
                elif kind in {"MovieSceneSpawnTrack", "MovieSceneVisibilityTrack"}:
                    if actor:
                        for section, lo, hi in self._sections(instance, track):
                            curve = channel(section.get("Properties", {}).get("BoolCurve"), self.graph, section.get("Name"), 1)
                            self.visibility[actor.root].append((instance, curve, lo, hi, kind == "MovieSceneSpawnTrack"))
                elif kind == "MovieScene3DAttachTrack":
                    if actor:
                        self.attach_specs.extend((actor.root, instance, section, lo, hi) for section, lo, hi in self._sections(instance, track))
                elif kind in {"MovieSceneFloatTrack", "MovieSceneBoolTrack", "MovieSceneColorTrack"}:
                    if actor:
                        self.plan_property(actor.root, instance, track)
                else:
                    self.unsupported(instance, track)
        for instance in self.graph.instances:
            for track in instance.sequence.master_tracks:
                kind = track.get("Type") or ""
                if kind in {"MovieSceneSubTrack", "MovieSceneCinematicShotTrack"}:
                    continue
                if kind == "MovieSceneCameraCutTrack" and self.import_cameras:
                    for section, lo, hi in self._sections(instance, track):
                        actor = self.binding_reference(instance, section.get("Properties", {}).get("CameraBindingID"))
                        camera = visual_for(actor.root, "CAMERA") if actor else None
                        if camera:
                            self.cuts.append((lo, hi, camera, instance.key.count("/")))
                        else:
                            self.graph.warn(f"Unresolved camera cut: {instance.sequence.path} / {section.get('Name')}")
                else:
                    self.unsupported(instance, track)

    def unsupported(self, instance, track):
        self.stats["unsupportedTracks"] += 1
        self.graph.warn(f"Unsupported track: {track.get('Type')} / {track.get('Name')} in {instance.sequence.path}")
        # Keep authored trigger times as labelled timeline markers, but never
        # execute Blueprint functions, Wwise events, or other gameplay logic.
        for section, lo, hi in self._sections(instance, track):
            props = section.get("Properties") or {}
            times = (props.get("EventChannel") or props.get("EventData") or {}).get("Times") or []
            times = [instance.root_time(number(tick)) for tick in times] or [lo]
            for time in times:
                if lo <= time < hi:
                    marker = self.scene.timeline_markers.new("UE unsupported: " + track.get("Type", "Track"), frame=round(self.frame(time)))

    def plan_property(self, obj, instance, track):
        props = track.get("Properties") or {}
        binding = props.get("PropertyBinding") or {}
        name = binding.get("PropertyPath") or binding.get("PropertyName") or ""
        kind = track.get("Type")
        camera, light = visual_for(obj, "CAMERA"), visual_for(obj, "LIGHT")
        owner, path, convert = None, None, lambda x: x
        if camera and self.import_cameras:
            owner = camera.data
            mapping = {"CurrentFocalLength": "lens", "CurrentAperture": "dof.aperture_fstop", "Filmback.SensorWidth": "sensor_width",
                       "FilmbackSettings.SensorWidth": "sensor_width", "Filmback.SensorHeight": "sensor_height", "FilmbackSettings.SensorHeight": "sensor_height",
                       "FocusSettings.ManualFocusDistance": "dof.focus_distance"}
            path = mapping.get(name)
            if name.endswith("ManualFocusDistance"):
                path, convert = "dof.focus_distance", lambda x: max(0, x * self.factor)
            if name == "FieldOfView":
                path, convert = "lens", lambda x: camera.data.sensor_width / (2 * math.tan(math.radians(max(0.1, min(179.9, x))) / 2))
        if light and self.import_lights:
            resolved = lights.animation_property(light, name.rsplit('.', 1)[-1])
            if resolved is not None:
                owner, path, factor = resolved
                convert = lambda x, factor=factor: x * factor
        if name in {"bHidden", "bHiddenInGame", "bVisible"} and kind == "MovieSceneBoolTrack":
            for section, lo, hi in self._sections(instance, track):
                curve = channel(section.get("Properties", {}).get("BoolCurve"), self.graph, section.get("Name"), 0)
                # Internally visibility channels always represent visibility.
                if name != "bVisible":
                    source_sample = curve.sample
                    curve.sample = lambda tick, sample=source_sample: 1 - sample(tick)
                self.visibility[obj].append((instance, curve, lo, hi, False))
            return
        if owner is None or path is None:
            self.unsupported(instance, track)
            return
        if isinstance(owner, (bpy.types.Camera, bpy.types.Light)) and any(
                candidate.data == owner and candidate not in {camera, light} and not candidate.get('ue_light_helper')
                for candidate in bpy.data.objects):
            # A binding animates one component, not every object sharing its
            # Camera/Light datablock. Keep unrelated scene instances intact.
            visual = camera if isinstance(owner, bpy.types.Camera) else light
            copied = owner.copy()
            visual.data = copied
            self.data_copies.append((visual, owner, copied))
            owner = copied
        for section, lo, hi in self._sections(instance, track):
            properties = section.get("Properties") or {}
            data = ([channel(properties.get(key), self.graph, section.get("Name")) for key in ("RedCurve", "GreenCurve", "BlueCurve")]
                    if kind == "MovieSceneColorTrack" else [channel(properties.get("BoolCurve" if kind == "MovieSceneBoolTrack" else "FloatCurve"), self.graph, section.get("Name"))])
            self.data_tracks[owner].append((path, instance, data, lo, hi, convert))

    def bake_transforms(self):
        for obj, specifications in self.object_tracks.items():
            if not self.available(obj):
                continue
            base_matrix = obj.matrix_parent_inverse @ obj.matrix_basis
            location, rotation, scale = base_matrix.decompose()
            euler = rotation.to_euler("XYZ")
            base = [location.x / self.factor, -location.y / self.factor, location.z / self.factor,
                    math.degrees(euler.x), -math.degrees(euler.y), -math.degrees(euler.z), *scale]
            sections = []
            for instance, section, lo, hi in specifications:
                properties = section.get("Properties") or {}
                blend = _blend_type(properties)
                if blend not in {"Absolute", "Additive"}:
                    self.graph.warn(f"Unsupported transform blend {blend}: {section.get('Name')}")
                    continue
                channels = []
                mask = int(number((properties.get("TransformMask") or {}).get("Mask"), 511))
                for axis, (prefix, index) in enumerate((prefix, index) for prefix in ("Translation", "Rotation", "Scale") for index in range(3)):
                    data = properties.get(prefix + (f"[{index}]" if index else ""))
                    channels.append(channel(data, self.graph, section.get("Name"), base[axis]) if data is not None and mask & (1 << axis) else None)
                sections.append((instance, section, lo, hi, blend, channels))
            frames = self.samples(time for _, _, lo, hi in specifications for time in (lo, hi))
            output = {"location": [], "rotation_quaternion": [], "scale": []}
            previous = None
            for frame in frames:
                seconds = (frame - self.start_frame) / self.fps
                absolute, additive = [[] for _ in base], [0.0] * len(base)
                for instance, section, lo, hi, blend, channels in sections:
                    if not lo <= seconds < hi:
                        continue
                    tick = instance.local_time(seconds)
                    weight = easing_weight(instance, section, tick)
                    for axis, curve in enumerate(channels):
                        if curve is not None:
                            sample = curve.sample(tick)
                            if blend == "Absolute":
                                absolute[axis].append((sample, weight))
                            else:
                                additive[axis] += (sample - (1 if axis >= 6 else 0)) * weight
                values = []
                for axis, samples in enumerate(absolute):
                    total = sum(weight for _, weight in samples)
                    values.append((sum(sample * weight for sample, weight in samples) + base[axis] * max(0, 1-total)) / max(1, total) + additive[axis])
                matrix = transform({"Translation": dict(zip("XYZ", values[:3])), "RelativeRotation": dict(zip(("Roll", "Pitch", "Yaw"), values[3:6])),
                                    "Scale3D": dict(zip("XYZ", values[6:]))}, self.factor)
                local = obj.matrix_parent_inverse.inverted_safe() @ matrix
                location, rotation, scale = local.decompose()
                if previous is not None and rotation.dot(previous) < 0:
                    rotation.negate()
                previous = rotation
                for path, sample in (("location", location), ("rotation_quaternion", rotation), ("scale", scale)):
                    output[path].append(tuple(sample))
            obj.rotation_mode = "QUATERNION"
            self.add_action(obj, output, frames)

    def bake_properties(self):
        for owner, specifications in self.data_tracks.items():
            if not self.available(owner):
                continue
            if isinstance(owner, bpy.types.Object) and owner.type == 'LIGHT':
                # Resolve channels without changing an occupied binding. Make
                # helper emitters only once the animation target is available.
                self.snapshots[owner]['light_controls'] = {
                    name: owner[name] for name in lights.UE_LIGHT_OBJECT_PROPS
                    if name in owner and isinstance(owner[name], (bool, int, float))}
                self.snapshots[owner]['light_animation_flags'] = {
                    name: owner.get(name) for name in ('ue_animated_source_length', 'ue_animated_soft_radius')}
                paths = {spec[0] for spec in specifications}
                from ..ue_map.light_rig import ensure_source_helpers
                ensure_source_helpers(owner,
                    animated_length=f'["{lights.UE_SOURCE_LENGTH_PROP}"]' in paths,
                    animated_soft_radius=f'["{lights.UE_SOFT_SOURCE_RADIUS_PROP}"]' in paths)
            frames = self.samples(time for _, _, _, lo, hi, _ in specifications for time in (lo, hi))
            output = {}
            for path in {spec[0] for spec in specifications}:
                default = owner.path_resolve(path)
                default = tuple(default) if hasattr(default, "__len__") else (float(default),)
                values = []
                for frame in frames:
                    seconds = (frame-self.start_frame)/self.fps
                    sample = default
                    for spec_path, instance, curves, lo, hi, convert in specifications:
                        if path == spec_path and lo <= seconds < hi:
                            sample = tuple(convert(curve.sample(instance.local_time(seconds))) for curve in curves)
                    values.append(sample)
                output[path] = values
            self.add_action(owner, output, frames)

    def bake_visibility(self):
        for root, specifications in self.visibility.items():
            boundaries = [time for _, _, lo, hi, _ in specifications for time in (lo, hi)]
            for instance, curve, _, _, _ in specifications:
                boundaries.extend(instance.root_time(tick) for tick in curve.times)
            frames = self.samples(boundaries)
            flags = []
            for frame in frames:
                seconds = (frame-self.start_frame)/self.fps
                spawned = not any(is_spawn for _, _, _, _, is_spawn in specifications)
                visible = True
                for instance, curve, lo, hi, is_spawn in specifications:
                    if lo <= seconds < hi:
                        state = bool(curve.sample(instance.local_time(seconds)))
                        if is_spawn:
                            spawned = spawned or state
                        else:
                            visible = state
                flags.append((float(not (spawned and visible)),))
            for obj in children(root):
                if obj.get('ue_hidden_by_profile'):
                    continue  # Profile filters take priority over authored visibility.
                if obj.get('ue_light_helper'):
                    continue  # Visibility is driven by the primary emitter.
                self.add_action(obj, {"hide_render": flags, "hide_viewport": flags}, frames, constant=True)

    def import_clips(self):
        cache = {}
        for rig, specifications in self.clip_specs.items():
            if not self.available(rig):
                continue
            clips = []
            for instance, section, lo, hi in specifications:
                params = section.get("Properties", {}).get("Params") or {}
                path = asset_path(params.get("Animation"))
                if not path:
                    continue
                try:
                    key = (rig.as_pointer(), path.casefold())
                    if key not in cache:
                        animation = self.mounted.animation_asset(path)
                        result = animations.import_animation_asset(rig, path, animation, start_frame=0, replace_current_action=False,
                            use_fake_user=True, scene=self.scene, scale_factor=animations.source_property(rig, "ue_import_scale", self.factor))
                        cache[key] = result[0]
                        self.actions.append(result[0])
                        self.stats["actions"] += 1
                        if animation.get("additiveBaked"):
                            self.graph.warn(f"Additive section is imported as an absolute baked pose, not a runtime additive layer: {path}")
                    action = cache[key]
                    speed = number(params.get("PlayRate"), 1)
                    if speed <= 0:
                        raise ValueError("Nonpositive animation PlayRate is not supported; use bReverse for reverse playback.")
                    tick_rate = float(instance.sequence.tick_rate)
                    trim_start = number(params.get("StartFrameOffset")) / tick_rate + number(params.get("StartOffset"))
                    trim_end = number(params.get("EndFrameOffset")) / tick_rate + number(params.get("EndOffset"))
                    crop_start, crop_end = trim_start*self.fps, action.frame_end-trim_end*self.fps
                    if crop_end <= crop_start:
                        raise ValueError("Animation section trims away the whole clip.")
                    parent_speed = 1 / float(instance.scale * instance.sequence.tick_rate)
                    section_start, _ = bounds(section.get("Properties") or {}, instance.sequence.playback)
                    elapsed = (lo - instance.root_time(section_start)) * parent_speed * speed * self.fps
                    first = number(params.get("FirstLoopStartFrameOffset")) / tick_rate * self.fps + elapsed
                    length = crop_end-crop_start
                    first %= length
                    # Animated strip time handles partial loops, trim offsets,
                    # clipping by parent shots and reverse without changing Actions.
                    track = rig.animation_data_create().nla_tracks.new()
                    self.added_tracks.append((rig, track))
                    track.name = "UE " + self.collection.name + " | " + section.get("Name", "Animation")
                    strip = track.strips.new(action.name, math.floor(self.frame(lo)), action)
                    strip.action_frame_start, strip.action_frame_end = crop_start, crop_end
                    strip.frame_start, strip.frame_end = self.frame(lo), self.frame(hi)
                    strip.extrapolation, strip.blend_type = "NOTHING", "REPLACE"
                    strip.use_animated_time = True
                    strip.use_animated_influence = True
                    weight = channel(params.get("Weight"), self.graph, section.get("Name"), 1)
                    clips.append((strip, instance, section, lo, hi, weight))
                    frames = self.samples((lo, hi))
                    for frame in frames:
                        if not self.frame(lo) <= frame <= self.frame(hi):
                            continue
                        phase = first + (frame - self.frame(lo)) * parent_speed * speed
                        sample = crop_start + phase % length
                        if params.get("bReverse"):
                            sample = crop_end - phase % length
                        strip.strip_time = sample
                        strip.keyframe_insert("strip_time", frame=frame)
                    # Avoid interpolating backwards through a loop discontinuity.
                    cycle_length = length / (parent_speed * speed)
                    seam = self.frame(lo) + (length-first) / (parent_speed*speed)
                    if (self.frame(hi)-self.frame(lo)) / cycle_length > 10000:
                        self.graph.warn(f"Fast animation loops resampled at scene FPS (seam limit reached): {path}")
                        seam = self.frame(hi)
                    while seam < self.frame(hi) - 1e-6:
                        for frame, sample in ((seam-0.0001, crop_start if params.get("bReverse") else crop_end),
                                              (seam, crop_end if params.get("bReverse") else crop_start)):
                            strip.strip_time = sample
                            strip.keyframe_insert("strip_time", frame=frame)
                        seam += cycle_length
                    for curve in strip.fcurves:
                        for point in curve.keyframe_points:
                            point.interpolation = "LINEAR"
                    self.stats["animationStrips"] += 1
                except Exception as exc:
                    self.graph.warn(f"Animation section unavailable ({path}) on {rig.name} [{animations.skeleton_path(rig)}]: {exc}")
            frames = self.samples(time for _, _, _, lo, hi, _ in clips for time in (lo, hi))
            for frame in frames:
                seconds = (frame-self.start_frame)/self.fps
                weights = [max(0, curve.sample(instance.local_time(seconds)) * easing_weight(instance, section, instance.local_time(seconds)))
                           if lo <= seconds < hi else 0 for _, instance, section, lo, hi, curve in clips]
                denominator = max(0, 1-sum(weights))
                # Compensate sequential NLA mixing so overlapping absolute
                # weights sum like Sequencer, rather than attenuating twice.
                for (strip, *_), weight in zip(clips, weights):
                    denominator += weight
                    strip.influence = weight/denominator if denominator else 0
                    strip.keyframe_insert("influence", frame=frame)
            for strip, *_ in clips:
                for curve in strip.fcurves:
                    for point in curve.keyframe_points:
                        point.interpolation = "LINEAR"

    def import_attachments(self):
        for owner, instance, section, lo, hi in self.attach_specs:
            properties = section.get("Properties") or {}
            actor = self.binding_reference(instance, properties.get("ConstraintBindingID"))
            if actor is None:
                self.graph.warn(f"Unresolved attachment target: {section.get('Name')}")
                continue
            target = actor.component(properties.get("AttachComponentName")) or actor.root
            socket = properties.get("AttachSocketName") or ""
            if socket and socket != "None":
                target = self.socket_target(target, socket)
                if target is None:
                    self.graph.warn(f"Attachment socket or bone unavailable: {section.get('Name')} / {socket}")
                    continue
            dependencies, visited = [target], set()
            cyclic = False
            while dependencies:
                dependency = dependencies.pop()
                if dependency == owner:
                    cyclic = True
                    break
                if dependency.as_pointer() in visited:
                    continue
                visited.add(dependency.as_pointer())
                if dependency.parent:
                    dependencies.append(dependency.parent)
                dependencies.extend(constraint.target for constraint in dependency.constraints
                                    if hasattr(constraint, "target") and constraint.target is not None)
            if cyclic or target in children(owner):
                self.graph.warn(f"Cyclic attachment skipped: {section.get('Name')}")
                continue
            rules = [str(properties.get(key, "KeepRelative")) for key in
                     ("AttachmentLocationRule", "AttachmentRotationRule", "AttachmentScaleRule")]
            if any("KeepRelative" not in rule for rule in rules):
                self.graph.warn(f"Non-relative attachment rules not imported: {section.get('Name')}")
                continue
            if not self.available(owner):
                continue
            constraint = owner.constraints.new("CHILD_OF")
            self.added_constraints.append((owner, constraint))
            constraint.name = "UE " + self.collection.name + " | " + section.get("Name", "Attach")
            constraint.target = target
            constraint.inverse_matrix = Matrix.Identity(4)
            frames = self.samples((lo, hi))
            flags = [(float(self.frame(lo) <= frame < self.frame(hi)),) for frame in frames]
            self.add_action(owner, {constraint.path_from_id("influence"): flags}, frames, constant=True)
            self.stats["attachments"] += 1

    def socket_target(self, target, name):
        rig = armature_for(target)
        if rig is None:
            return None
        reference = json.loads(animations.source_property(rig, "ue_reference_skeleton", "{}"))
        bones = reference.get("bones") or []
        socket = None
        bone_name = name
        if name not in rig.data.bones:
            try:
                payload = self.mounted.skeleton_asset(animations.skeleton_path(rig))
                socket = next((item for item in payload.get("sockets") or [] if item.get("name") == name), None)
            except Exception as exc:
                self.graph.warn(f"Socket metadata unavailable ({name}): {exc}")
            if not socket:
                return None
            bone_name = socket.get("boneName") or ""
        bone = rig.data.bones.get(bone_name)
        if bone is None or not bones:
            return None
        factor = animations.source_property(rig, "ue_import_scale", self.factor)
        forward = (skeletons.Y_FORWARD_ROTATION if animations.source_property(rig, skeletons.FACE_FORWARD_PROPERTY) == skeletons.FACE_FORWARD_BLENDER else Matrix.Identity(4))
        matrices = []
        for source in bones:
            parent = int(source.get("parentIndex", -1))
            matrix = skeletons.ue_bone_transform_to_blender(tuple(source.get("translation") or (0, 0, 0)),
                tuple(source.get("rotation") or (0, 0, 0, 1)), factor, tuple(source.get("scale") or (1, 1, 1)))
            matrices.append((matrices[parent] if parent >= 0 else forward) @ matrix)
            if source.get("name") == bone_name:
                if socket:
                    matrix = skeletons.ue_bone_transform_to_blender(tuple(socket.get("translation") or (0, 0, 0)),
                        tuple(socket.get("rotation") or (0, 0, 0, 1)), factor, tuple(socket.get("scale") or (1, 1, 1)))
                    matrices[-1] = matrices[-1] @ matrix
                anchor = bpy.data.objects.new(rig.name + ".Socket." + name, None)
                self.collection.objects.link(anchor)
                anchor.parent, anchor.parent_type, anchor.parent_bone = rig, "BONE", bone_name
                # Blender bone parents use the displayed bone's tail frame.
                parent_rest = bone.matrix_local @ Matrix.Translation((0, bone.length, 0))
                anchor.matrix_parent_inverse = Matrix.Identity(4)
                anchor.matrix_basis = parent_rest.inverted_safe() @ matrices[-1]
                return anchor
        return None

    def import_cuts(self):
        old_camera = self.scene.camera
        previous = None
        times = {bound for lo, hi, _, _ in self.cuts for bound in (lo, hi)}
        if self.cuts:
            times.add(0)
        for time in sorted(times):
            active = [cut for cut in self.cuts if cut[0] <= time < cut[1]]
            camera = max(active, key=lambda cut: cut[3])[2] if active else old_camera
            if camera != previous and camera is not None:
                marker = self.scene.timeline_markers.new("UE " + self.collection.name + " | " + camera.name, frame=round(self.frame(time)))
                marker.camera = camera
                self.stats["cameraCuts"] += 1
                if previous is None:
                    self.scene.camera = camera
            previous = camera

    def run(self):
        self.plan()
        self.context.view_layer.update()
        self.bake_transforms()
        self.bake_properties()
        self.bake_visibility()
        self.import_clips()
        self.import_attachments()
        self.import_cuts()
        self.stats["objects"] = len(self.collection.all_objects)
        self.stats["textureFailures"] = getattr(self.mounted, "failed", 0)
        self.stats["materialFailures"] = getattr(self.mounted, "failed_materials", 0)
        if self.stats["textureFailures"] or self.stats["materialFailures"]:
            self.graph.warn(f"Unavailable textures: {self.stats['textureFailures']}; unreadable materials: {self.stats['materialFailures']}. Empty labelled nodes are retained; see console for asset paths.")
        self.stats["unresolvedBindings"] = self.resolver.unresolved
        self.stats["warnings"] = self.graph.warnings
        report_text = bpy.data.texts.new("UE Sequence Report | " + self.collection.name)
        self.report_text = report_text
        report_text.write(json.dumps(self.stats, indent=2, ensure_ascii=False))
        self.collection["ue_import_report"] = report_text.name
        self.collection["ue_sequence_duration"] = self.graph.duration
        for warning in self.graph.warnings:
            print(f"[Unreal sequence WARNING] {warning}")
        self.context.scene.frame_set(self.context.scene.frame_current)
        return self.stats
