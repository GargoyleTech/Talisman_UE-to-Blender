"""Resolve Sequencer bindings and instantiate serialized actor/component templates."""

from dataclasses import dataclass, field
import math

import bpy
from mathutils import Euler, Matrix, Quaternion, Vector

from ...formats.ue_map import lights, map_import
from . import maps
from .sequence_data import asset_path, guid, number


# Blender cameras/lights look along -Z. UE camera/light components look +X;
# keep this display correction on a visual child, not the animated UE frame.
FORWARD_FIX = Matrix(((0, 0, -1, 0), (-1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 0, 1)))


def transform(values, factor):
    translation = values.get("RelativeLocation", values.get("Translation")) or {}
    rotation = values.get("RelativeRotation", values.get("Rotation")) or {}
    scale = values.get("RelativeScale3D", values.get("Scale3D")) or {}
    location = Vector((number(translation.get("X")) * factor, -number(translation.get("Y")) * factor, number(translation.get("Z")) * factor))
    if "W" in rotation:
        orientation = Quaternion((number(rotation.get("W"), 1), -number(rotation.get("X")), number(rotation.get("Y")), -number(rotation.get("Z"))))
        orientation.normalize()
    else:
        orientation = Euler(tuple(math.radians(number(rotation.get(key)) * sign)
                                  for key, sign in (("Roll", 1), ("Pitch", -1), ("Yaw", -1))), "XYZ").to_quaternion()
    return Matrix.LocRotScale(location, orientation, Vector(tuple(number(scale.get(axis), 1) for axis in "XYZ")))


def children(obj):
    return [obj, *obj.children_recursive]


def armature_for(obj):
    if obj.type == "ARMATURE":
        return obj
    rigs = [child for child in obj.children_recursive if child.type == "ARMATURE"]
    return rigs[0] if len(rigs) == 1 else None


def visual_for(obj, kind):
    if obj.type == kind:
        return obj
    matches = [child for child in obj.children_recursive if child.type == kind and not child.get('ue_light_helper')]
    return matches[0] if len(matches) == 1 else None


@dataclass
class Actor:
    root: object
    components: dict = field(default_factory=dict)
    created: bool = False

    def component(self, path):
        name = str(path or "").rsplit(".", 1)[-1].casefold()
        if not name:
            return self.root
        if name in self.components:
            return self.components[name]
        matches = [obj for obj in children(self.root)
                   if name in {obj.name.casefold(), str(obj.get("ue_component_name", "")).casefold()}]
        return matches[0] if len(matches) == 1 else None


class Resolver:
    def __init__(self, context, mounted, graph, collection, *, factor=0.01, load_missing=True,
                 import_models=True, import_cameras=True, import_lights=True, overrides=None):
        self.context, self.mounted, self.graph, self.collection = context, mounted, graph, collection
        self.factor, self.load_missing = factor, load_missing
        self.import_models, self.import_cameras, self.import_lights = import_models, import_cameras, import_lights
        self.overrides = overrides or {}
        self.assets = maps.MapAssets(context, mounted, factor)
        self.resolved, self.actors, self.template_cache = {}, {}, {}
        self.resolving = set()
        self.unresolved = []
        self.original_objects = [obj for obj in context.scene.objects
                                 if obj.get("ue_source_id") in (None, mounted.cache_namespace)]

    def canonical(self, path):
        path = str(path or "").replace("\\", "/")
        if path.startswith("/Game/"):
            path = (self.mounted.mount_info.get("contentRoot") or "/Game/") + path[6:]
        return path.casefold()

    def existing(self, path, name=""):
        path_key = self.canonical(path)
        matches = []
        for obj in self.original_objects:
            if path_key and self.canonical(obj.get("ue_component_path")) == path_key:
                matches.append(obj)
            elif path_key and self.canonical(obj.get("ue_actor_path")) == path_key:
                matches.append(obj)
        if matches:
            roots = [obj for obj in matches if obj.parent not in matches]
            return roots[0] if len(roots) == 1 else None
        # Legacy map imports only retained actor names. Require a unique match
        # in the exact source map collection, never just a matching basename.
        package = self.canonical(asset_path(path))
        actor_name = path.split("PersistentLevel.", 1)[-1].split(".", 1)[0] if "PersistentLevel." in path else name
        matches = [obj for obj in self.original_objects
                   if (obj.name == actor_name or obj.get("source_name") == actor_name)
                   and any(self.canonical(asset_path(col.get("ue_map_path"))) == package for col in obj.users_collection)]
        return matches[0] if len(matches) == 1 else None

    def _empty(self, name):
        obj = bpy.data.objects.new(name, None)
        self.collection.objects.link(obj)
        obj.empty_display_size = 0.15
        return obj

    def _component(self, record, actor_name):
        kind, props = record.get("Type", ""), record.get("Properties") or {}
        name = record.get("Alias") or record.get("Name") or kind
        path = props.get("SkeletalMesh") or props.get("SkinnedAsset")
        if path and self.import_models:
            asset = self.assets.skeletal(path.get("ObjectPath") or "")
            return map_import.create_package_skeletal_mesh_instance(asset, actor_name + "." + name,
                Vector((0, 0, 0)), Euler((0, 0, 0)), self.collection, Vector((1, 1, 1)), game_features=False)
        path = props.get("StaticMesh")
        if path and self.import_models:
            obj = bpy.data.objects.new(path["ObjectPath"].rsplit("/", 1)[-1].split(".", 1)[0], self.assets.static(path["ObjectPath"]))
            self.collection.objects.link(obj)
            return obj
        anchor = self._empty(actor_name + "." + name)
        camera = "CameraComponent" in kind
        light_type = lights.blender_light_type_from_name(kind)
        if camera and self.import_cameras:
            data = bpy.data.cameras.new(anchor.name)
            data.lens = number(props.get("CurrentFocalLength"), 35)
            data.dof.focus_distance = number((props.get("FocusSettings") or {}).get("ManualFocusDistance"), 1000) * self.factor
            data.sensor_width = number((props.get("Filmback") or props.get("FilmbackSettings") or {}).get("SensorWidth"), 36)
            data.sensor_height = number((props.get("Filmback") or props.get("FilmbackSettings") or {}).get("SensorHeight"), 24)
            data.lens = max(0.1, data.lens)
            aperture = number(props.get("CurrentAperture"), 2.8)
            data.dof.aperture_fstop = max(0.1, aperture)
            data.clip_end = 10000
        elif light_type and self.import_lights:
            data = lights.create_static_light_data(anchor.name, light_type, props, location_scale=self.factor)
        else:
            data = None
            if any(token in kind for token in ("Niagara", "Particle", "Audio", "Decal", "SceneCapture", "DirectionalLight", "RectLight")):
                self.graph.warn(f"Unsupported visual/audio component kept as a transform placeholder: {kind} / {actor_name}.{name}")
        if data is not None:
            visual = bpy.data.objects.new(anchor.name + ".Visual", data)
            self.collection.objects.link(visual)
            visual.parent = anchor
            visual.matrix_local = FORWARD_FIX if camera or light_type in {'SPOT', 'AREA'} else Matrix.Identity(4)
            if light_type:
                lights.apply_ue_light_object_properties(visual)
                lights.apply_source_texture(visual, self.mounted)
                lights.apply_component_visibility(visual, props)
        return anchor

    def template(self, path, object_path):
        key = self.canonical(object_path)
        if key not in self.template_cache:
            self.template_cache[key] = self.mounted.request({"action": "generic_actor_template", "assetPath": path, "objectPath": object_path})["template"]
        return self.template_cache[key]

    def create_actor(self, path, object_path, name, spawn_transform=None):
        payload = self.template(path, object_path)
        for warning in payload.get("warnings") or []:
            self.graph.warn(f"{name}: {warning}")
        root = self._empty(name)
        root["ue_actor_path"] = payload["actor"]["ObjectPath"]
        root["ue_source_id"] = self.mounted.cache_namespace
        actor = Actor(root, created=True)
        records = sorted(payload.get("components") or [], key=lambda record: not record.get("ObjectPath", "").startswith(payload["actor"]["ObjectPath"]))
        created, records_by_obj = {}, {}
        root_ref = (payload["actor"].get("Properties") or {}).get("RootComponent") or {}
        root_path = root_ref.get("ObjectPath") or ""
        if not root_path:
            root_path = next((record.get("ObjectPath") for record in records if not record.get("ParentPath") and
                              "SceneComponent" in record.get("Type", "")), "")
        for record in records:
            alias = record.get("Alias") or record.get("Name") or "Component"
            alias = alias.removesuffix("_GEN_VARIABLE")
            if alias.casefold() in actor.components:
                continue
            try:
                obj = self._component(record, name)
            except Exception as exc:
                self.graph.warn(f"Component unavailable ({name}.{alias}): {exc}")
                obj = self._empty(name + "." + alias)
            obj.parent = root
            obj.matrix_local = transform(record.get("Properties") or {}, self.factor)
            obj["ue_component_name"] = alias
            obj["ue_component_path"] = record.get("ObjectPath") or ""
            obj["ue_source_id"] = self.mounted.cache_namespace
            from .visibility import apply_default_visibility
            apply_default_visibility(obj, getattr(self.mounted, "hidden_object_patterns", ()), name,
                                     path, object_path, alias)
            created[record.get("ObjectPath")] = obj
            if record.get("SourceTemplatePath"):
                created[record["SourceTemplatePath"]] = obj
            records_by_obj[obj] = record
            for component_name in (alias, record.get("Name", ""), record.get("Alias", "")):
                if component_name:
                    actor.components[component_name.casefold()] = obj
        for obj, record in records_by_obj.items():
            props = record.get("Properties") or {}
            parent = created.get((props.get("AttachParent") or {}).get("ObjectPath") or record.get("ParentPath"))
            if parent is not None and parent != obj:
                obj.parent = parent
        root_component = created.get(root_path)
        if root_component is not None:
            root.matrix_local = root_component.matrix_local.copy()
            root_component.matrix_local = Matrix.Identity(4)
            for alias, target in list(actor.components.items()):
                if target == root_component:
                    actor.components[alias] = root
            # Root component curves animate the same UE frame as actor curves.
        if spawn_transform:
            initial = transform(spawn_transform, self.factor)
            if any(abs(initial[row][column] - float(row == column)) > 1e-6 for row in range(4) for column in range(4)):
                root.matrix_local = initial
        if not created:
            self.graph.warn(f"No serialized scene components for {name}; created a transform placeholder.")
        from .visibility import apply_default_visibility
        apply_default_visibility(root, getattr(self.mounted, "hidden_object_patterns", ()), name, path, object_path)
        return actor

    def resolve(self, instance, binding_id):
        key = instance.binding_key(binding_id)
        if key in self.resolved:
            return self.resolved[key]
        if key in self.resolving:
            self.graph.warn(f"Cyclic object binding: {key}")
            return None
        self.resolving.add(key)
        binding = instance.sequence.bindings.get(guid(binding_id)) or {}
        name = binding.get("Name") or binding_id
        try:
            override = self.overrides.get(key) or self.overrides.get(guid(binding_id))
            if override:
                obj = override if isinstance(override, bpy.types.Object) else self.context.scene.objects.get(override)
                if obj is None:
                    raise ValueError(f"Override object does not exist: {override}")
                actor = Actor(obj)
            elif binding.get("spawned"):
                reference = binding.get("ObjectTemplate") or {}
                actor = self.create_actor(instance.sequence.path, reference.get("ObjectPath", ""), name, binding.get("SpawnTransform"))
            else:
                actor = None
                parent_id = guid(binding.get("ParentGuid"))
                references = instance.sequence.binding_refs.get(guid(binding_id)) or []
                for reference in references:
                    relative = reference.get("ObjectPath") or ""
                    if parent_id and relative:
                        parent = self.resolve(instance, parent_id)
                        obj = parent.component(relative) if parent else None
                        if obj:
                            actor = Actor(obj, parent.components, parent.created)
                            break
                    external = reference.get("ExternalObjectPath") or {}
                    package = external.get("AssetPathName") or ""
                    subpath = external.get("SubPathString") or ""
                    if not subpath or package in ("", "None"):
                        continue
                    object_path = self.canonical(package) + ":" + subpath
                    actor = self.actors.get(self.canonical(object_path))
                    if actor:
                        break
                    obj = self.existing(object_path, name)
                    if obj:
                        actor = Actor(obj)
                    elif self.load_missing:
                        actor = self.create_actor(asset_path(package), object_path, name)
                    if actor:
                        self.actors[self.canonical(object_path)] = actor
                        break
                if actor is None and parent_id:
                    parent = self.resolve(instance, parent_id)
                    obj = parent.component(name) if parent else None
                    if obj:
                        actor = Actor(obj, parent.components, parent.created)
                if actor is None:
                    self.unresolved.append({"key": key, "sequence": instance.sequence.path, "guid": binding_id, "name": name})
                    self.graph.warn(f"Unresolved binding: {instance.sequence.path} / {name} ({binding_id})")
            self.resolved[key] = actor
            return actor
        except Exception as exc:
            self.unresolved.append({"key": key, "sequence": instance.sequence.path, "guid": binding_id, "name": name, "error": str(exc)})
            self.graph.warn(f"Binding unavailable ({name}): {exc}")
            self.resolved[key] = None
            return None
        finally:
            self.resolving.remove(key)
