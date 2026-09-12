"""Generic Unreal map actor conversion and Blender placement."""

import bpy
import os
import math
import re
import importlib
from dataclasses import dataclass
from mathutils import Vector, Euler, Matrix, Quaternion

from . import lights, particles, worlds


TextureIndexCache = dict[tuple[str, str], dict[str, str]]
_SETPOS_MARKER = "_setpos_"

# Blender spot lights emit along local -Z, while UE components use +X forward.
_LIGHT_FWD_FIX = (
    Matrix.Rotation(math.radians(90.0), 4, "X") @
    Matrix.Rotation(math.radians(-90.0), 4, "Y")
)
_EXTERNAL_EMISSIVE_CONTEXT_PROP = "ExternalEmissiveContext"
_package_skeletal_mesh_binder = None
_external_emissive_initializer = None


def configure_package_adapters(
    *,
    bind_skeletal_mesh_object,
    initialize_external_emissive_context,
) -> None:
    """Inject title-specific package/material behavior into generic map placement."""
    global _package_skeletal_mesh_binder, _external_emissive_initializer
    _package_skeletal_mesh_binder = bind_skeletal_mesh_object
    _external_emissive_initializer = initialize_external_emissive_context


def _bind_package_skeletal_mesh_object(*args, **kwargs):
    if _package_skeletal_mesh_binder is None:
        raise RuntimeError("No game adapter configured package SkeletalMesh binding.")
    return _package_skeletal_mesh_binder(*args, **kwargs)


def _initialize_external_emissive_context(obj: bpy.types.Object) -> None:
    if _external_emissive_initializer is not None:
        _external_emissive_initializer(obj)


@dataclass(frozen=True)
class SkeletalMeshDatablocks:
    """Shared data needed to place one package SkeletalMesh actor.

    Each map placement gets ordinary mesh and armature objects, while their
    Mesh and Armature datablocks are shared.
    """
    mesh: bpy.types.Mesh
    armature: bpy.types.Armature | None
    skeletal_mesh: dict
    virtual_path: str

def extract_static_mesh_name(object_name_str: str) -> str | None:
    if not object_name_str:
        return None
    if "'" in object_name_str:
        parts = object_name_str.split("'")
        if len(parts) >= 2:
            return parts[1]
    return object_name_str


def extract_static_mesh_game_path(static_mesh: dict) -> str | None:
    """Return the full UE object path emitted by the package bridge, when present."""
    if not isinstance(static_mesh, dict):
        return None
    object_path = static_mesh.get("ObjectPath")
    return extract_static_mesh_name(object_path) if isinstance(object_path, str) else None


def ensure_parent_collection_for_source(source_name: str) -> bpy.types.Collection:
    base_name = os.path.splitext(os.path.basename(source_name))[0]
    col = bpy.data.collections.get(base_name)
    if col is None:
        col = bpy.data.collections.new(base_name)

    scene = bpy.context.scene
    if col.name not in scene.collection.children:
        scene.collection.children.link(col)

    return col


def ensure_map_import_root(
    parent_collection: bpy.types.Collection,
    source_name: str,
    *,
    display_size: float = 1.0,
) -> bpy.types.Object:
    """Return this map's shared, initially hidden hierarchy Empty.

    MEC terrain and package-decoded actors use the same source collection, so
    this deliberately lives in the general map-import module rather than in
    either individual importer.
    """
    base_name = os.path.splitext(os.path.basename(source_name))[0]
    root_name = f"{base_name}_Origin"
    root = parent_collection.objects.get(root_name)
    if root is None:
        root = bpy.data.objects.new(root_name, None)
        root.empty_display_type = "PLAIN_AXES"
        root.empty_display_size = display_size
        root["ff7r_map_import_root"] = True
        parent_collection.objects.link(root)
        # Keep the organizing control out of the viewport by default without
        # changing any child object's own visibility.
        root.hide_set(True)
    return root


def parent_map_objects_to_root(
    root: bpy.types.Object,
    objects: list[bpy.types.Object],
) -> None:
    """Parent map objects that have no actor parent, preserving their pose.

    MEC imports move ``root`` immediately before calling this helper.  Blender
    does not necessarily refresh ``matrix_world`` until the next dependency
    graph update, particularly while a multi-file file-browser import is still
    running.  Refresh it here so every map in a batch receives the transform
    of *its own* origin Empty rather than the previous identity matrix.
    """
    view_layer = getattr(bpy.context, "view_layer", None)
    if view_layer is not None:
        view_layer.update()

    root_inverse = root.matrix_world.inverted()
    for obj in objects:
        if obj.parent is None:
            # Direct RNA parenting keeps the object's local transform.  Save
            # and restore the world transform so parent assignment is stable
            # even if Blender defers another dependency-graph evaluation.
            world_matrix = obj.matrix_world.copy()
            obj.parent = root
            obj.matrix_parent_inverse = root_inverse
            obj.matrix_world = world_matrix


def ensure_child_collection(
    parent_collection: bpy.types.Collection,
    child_name: str,
) -> bpy.types.Collection:
    col = bpy.data.collections.get(child_name)
    if col is None:
        col = bpy.data.collections.new(child_name)

    if parent_collection.children.get(col.name) is None:
        parent_collection.children.link(col)

    return col


def ensure_typed_import_collection(
    root_collection: bpy.types.Collection,
    suffix: str,
) -> bpy.types.Collection:
    return ensure_child_collection(root_collection, f"{root_collection.name}{suffix}")


def collection_is_child(
    parent_collection: bpy.types.Collection,
    child_collection: bpy.types.Collection,
) -> bool:
    return any(child == child_collection for child in parent_collection.children)


def scene_collection_parents(collection: bpy.types.Collection) -> list[bpy.types.Collection]:
    if collection is None:
        return []

    scene_root = bpy.context.scene.collection
    parents: list[bpy.types.Collection] = []
    visited: set[int] = set()

    def visit(parent: bpy.types.Collection) -> None:
        pointer = parent.as_pointer()
        if pointer in visited:
            return
        visited.add(pointer)

        for child in list(parent.children):
            if child == collection:
                parents.append(parent)
            else:
                visit(child)

    visit(scene_root)
    return parents


def unlink_collection_from_scene(collection: bpy.types.Collection) -> int:
    parents = scene_collection_parents(collection)

    unlinked_count = 0
    for parent in parents:
        try:
            parent.children.unlink(collection)
            unlinked_count += 1
        except RuntimeError as exc:
            print(
                f"[Rebirth Map Import]   Could not unlink collection "
                f"'{collection.name}' from '{parent.name}': {exc}"
            )

    return unlinked_count


def collapse_outliner_collections() -> None:
    screen = getattr(bpy.context, "screen", None)
    if screen is None:
        return

    for area in screen.areas:
        if area.type != "OUTLINER":
            continue

        region = next((r for r in area.regions if r.type == "WINDOW"), None)
        space = next((s for s in area.spaces if s.type == "OUTLINER"), None)
        if region is None or space is None:
            continue

        try:
            with bpy.context.temp_override(area=area, region=region, space_data=space):
                for _ in range(8):
                    result = bpy.ops.outliner.show_one_level(open=False)
                    if result == {"CANCELLED"}:
                        break
        except Exception as exc:
            print(f"[Rebirth Map Import]   Could not collapse Outliner collections: {exc}")


def rotation_from_relative(rot_dict: dict) -> Euler:
    """UE RelativeRotation (Pitch/Yaw/Roll degrees) -> Blender XYZ Euler. Mapping: X=Roll, Y=-Pitch, Z=-Yaw."""
    pitch_deg = float(rot_dict.get("Pitch", 0.0))
    yaw_deg = float(rot_dict.get("Yaw", 0.0))
    roll_deg = float(rot_dict.get("Roll", 0.0))

    pitch = math.radians(pitch_deg)
    yaw = math.radians(yaw_deg)
    roll = math.radians(roll_deg)

    return Euler((roll, -pitch, -yaw), "XYZ")


def light_rotation_from_relative(rot_dict: dict) -> Euler:
    """rotation_from_relative plus the Blender spot -Z -> UE +X forward correction."""
    if not _has_rotation_values(rot_dict):
        return Euler((0.0, 0.0, 0.0), "XYZ")
    mesh_rot = rotation_from_relative(rot_dict)
    return (mesh_rot.to_matrix().to_4x4() @ _LIGHT_FWD_FIX).to_euler("XYZ")


def _has_rotation_values(rot_dict: dict) -> bool:
    """Return True when the export supplied at least one UE rotation channel."""
    if not isinstance(rot_dict, dict):
        return False
    return any(axis in rot_dict for axis in ("Pitch", "Yaw", "Roll"))


def location_from_relative(loc_dict: dict, scale_factor: float = 0.01) -> Vector:
    if not isinstance(loc_dict, dict):
        loc_dict = {}
    x = _float_or_default(loc_dict.get("X", 0.0)) * scale_factor
    y = -_float_or_default(loc_dict.get("Y", 0.0)) * scale_factor
    z = _float_or_default(loc_dict.get("Z", 0.0)) * scale_factor
    return Vector((x, y, z))


def scale_from_relative(scale_dict: dict) -> Vector:
    if not isinstance(scale_dict, dict):
        scale_dict = {}
    return Vector((
        _float_or_default(scale_dict.get("X", 1.0), 1.0),
        _float_or_default(scale_dict.get("Y", 1.0), 1.0),
        _float_or_default(scale_dict.get("Z", 1.0), 1.0),
    ))


def scale_from_entry(props: dict, entry: dict | None = None) -> Vector:
    if not isinstance(props, dict):
        props = {}
    entry_scale = entry.get("RelativeScale3D", {}) if isinstance(entry, dict) else {}
    return scale_from_relative(props.get("RelativeScale3D", entry_scale))


def rotation_from_quaternion(rot_dict: dict) -> Euler:
    if not isinstance(rot_dict, dict):
        rot_dict = {}
    quat = Quaternion((
        _float_or_default(rot_dict.get("W", 1.0), 1.0),
        _float_or_default(rot_dict.get("X", 0.0)),
        -_float_or_default(rot_dict.get("Y", 0.0)),
        -_float_or_default(rot_dict.get("Z", 0.0)),
    ))
    quat.normalize()
    return quat.to_euler("XYZ")


def transform_location_rotation_scale(transform: dict, scale_factor: float = 0.01) -> tuple[Vector, Euler, Vector]:
    if not isinstance(transform, dict):
        transform = {}
    loc = location_from_relative(transform.get("Translation", {}), scale_factor=scale_factor)
    rot = rotation_from_quaternion(transform.get("Rotation", {}))
    scale = scale_from_relative(transform.get("Scale3D", {}))
    return loc, rot, scale


def _multiply_vectors(lhs, rhs) -> Vector:
    return Vector((
        _float_or_default(lhs[0], 1.0) * _float_or_default(rhs[0], 1.0),
        _float_or_default(lhs[1], 1.0) * _float_or_default(rhs[1], 1.0),
        _float_or_default(lhs[2], 1.0) * _float_or_default(rhs[2], 1.0),
    ))


def _float_or_default(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _set_custom_property(
    obj: bpy.types.ID,
    name: str,
    value,
    *,
    subtype: str | None = None,
) -> None:
    obj[name] = value
    if subtype is None:
        return
    try:
        obj.id_properties_ui(name).update(subtype=subtype)
    except Exception:
        pass


def _bool_or_default(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    return bool(value)


def _get_light_temperature(props: dict) -> float | None:
    if "Temperature" in props:
        return _float_or_default(props.get("Temperature"), 6500.0)
    if "ColorTemperature" in props:
        return _float_or_default(props.get("ColorTemperature"), 6500.0)
    return None


def _resolve_light_name(entry: dict, default_name: str) -> str:
    """Use the owning actor name for light objects when the JSON provides it."""
    outer_name = _resolve_outer_name(entry)
    entry_name = entry.get("Name", default_name)
    entry_name = entry_name if isinstance(entry_name, str) and entry_name else default_name
    if outer_name:
        return f"{outer_name}.{entry_name}"
    return entry_name


def create_point_light_from_entry(
    entry: dict,
    parent_collection: bpy.types.Collection,
    location_scale: float,
    exposure_mult: float,
    attenuation_radius_mult: float,
    always_cast_shadows: bool = False,
    attach_parent_obj: bpy.types.Object | None = None,
):
    props = entry.get("Properties", {})
    light_name = _resolve_light_name(entry, "PointLight")
    light_data = lights.create_static_light_data(
        light_name, "POINT", {**entry, **props},
        location_scale=location_scale,
        exposure_mult=exposure_mult,
        attenuation_radius_mult=attenuation_radius_mult,
        always_cast_shadows=always_cast_shadows,
    )
    loc_dict = props.get("RelativeLocation", entry.get("RelativeLocation", {}))
    rot_dict = props.get("RelativeRotation", entry.get("RelativeRotation", {}))
    loc = location_from_relative(loc_dict, scale_factor=location_scale)
    rot = rotation_from_relative(rot_dict)
    scale = scale_from_entry(props, entry)
    light_obj = bpy.data.objects.new(light_name, light_data)
    if attach_parent_obj is not None:
        light_obj.parent = attach_parent_obj
    light_obj.location = loc
    light_obj.rotation_euler = rot
    light_obj.scale = scale
    lights.apply_ue_light_object_properties(light_obj)
    parent_collection.objects.link(light_obj)
    return light_obj


def create_spot_light_from_entry(
    entry: dict,
    parent_collection: bpy.types.Collection,
    location_scale: float,
    exposure_mult: float,
    attenuation_radius_mult: float,
    always_cast_shadows: bool = False,
    attach_parent_obj: bpy.types.Object | None = None,
):
    props = entry.get("Properties", {})
    light_name = _resolve_light_name(entry, "SpotLight")
    light_data = lights.create_static_light_data(
        light_name, "SPOT", {**entry, **props},
        location_scale=location_scale,
        exposure_mult=exposure_mult,
        attenuation_radius_mult=attenuation_radius_mult,
        always_cast_shadows=always_cast_shadows,
    )
    loc_dict = props.get("RelativeLocation", entry.get("RelativeLocation", {}))
    rot_dict = props.get("RelativeRotation", entry.get("RelativeRotation", {}))
    loc = location_from_relative(loc_dict, scale_factor=location_scale)
    rot = light_rotation_from_relative(rot_dict)
    scale = scale_from_entry(props, entry)
    light_obj = bpy.data.objects.new(light_name, light_data)
    if attach_parent_obj is not None:
        light_obj.parent = attach_parent_obj
    light_obj.location = loc
    light_obj.rotation_euler = rot
    light_obj.scale = scale
    lights.apply_ue_light_object_properties(light_obj)
    parent_collection.objects.link(light_obj)
    return light_obj


def extract_skeletal_mesh_name(entry: dict) -> tuple[str | None, str | None]:
    """Return (asset_name, object_path) from a SkeletalMeshComponent entry.

    Package UMAP imports expose the resolved SkeletalMesh reference in the
    component properties. Legacy exported JSON instead stores a compatible
    object path on the component template, so retain that fallback.
    """
    props = entry.get("Properties", {})
    if isinstance(props, dict):
        for property_name in ("SkeletalMesh", "SkinnedAsset"):
            mesh_ref = props.get(property_name)
            if not isinstance(mesh_ref, dict):
                continue
            obj_path = mesh_ref.get("ObjectPath", "")
            if not isinstance(obj_path, str) or not obj_path:
                continue
            object_path = extract_static_mesh_name(obj_path)
            last_segment = object_path.rstrip("/").rsplit("/", 1)[-1]
            asset_name = last_segment.split(".")[0] or None
            if asset_name:
                return asset_name, object_path

    template = entry.get("Template", {})
    if not isinstance(template, dict):
        return None, None

    obj_path = template.get("ObjectPath", "")
    if not obj_path:
        return None, None

    last_segment = obj_path.rstrip("/").rsplit("/", 1)[-1]
    asset_name = last_segment.split(".")[0] or None

    return asset_name or None, obj_path


def _resolve_outer_name(entry: dict) -> str:
    outer_raw = entry.get("Outer", "")
    if isinstance(outer_raw, dict):
        obj_name = outer_raw.get("ObjectName", "")
        name = obj_name.rsplit(".", 1)[-1].rstrip("'").strip()
        return name
    return outer_raw.strip()


def extract_setpos_lookup_name(name: str) -> str | None:
    """Return the suffix after _setpos_ from a UE actor/component name."""
    if not isinstance(name, str) or not name:
        return None

    marker_index = name.casefold().find(_SETPOS_MARKER)
    if marker_index < 0:
        return None

    lookup_name = name[marker_index + len(_SETPOS_MARKER):].strip()
    return lookup_name or None


def extract_setpos_lookup_name_from_entry(entry: dict) -> str | None:
    """Extract a setpos lookup token, preferring the owning actor name."""
    outer_lookup_name = extract_setpos_lookup_name(_resolve_outer_name(entry))
    if outer_lookup_name:
        return outer_lookup_name

    entry_name = entry.get("Name", "")
    return extract_setpos_lookup_name(entry_name)


def iter_layout_object_pack_objects(entry: dict):
    props = entry.get("Properties", {})
    if not isinstance(props, dict):
        return

    objects = props.get("Objects", [])
    if not isinstance(objects, list):
        return

    for obj_entry in objects:
        if not isinstance(obj_entry, dict):
            continue
        key = obj_entry.get("Key", "")
        value = obj_entry.get("Value", {})
        if not isinstance(key, str) or not key or not isinstance(value, dict):
            continue
        yield key, value


def _object_reference_keys(ref: dict) -> set[str]:
    keys: set[str] = set()
    if not isinstance(ref, dict):
        return keys

    obj_name = ref.get("ObjectName", "")
    if isinstance(obj_name, str) and obj_name:
        cleaned = obj_name.strip()
        _add_reference_key_with_aliases(keys, cleaned)
        if "PersistentLevel." in cleaned:
            after = cleaned.split("PersistentLevel.", 1)[1].rstrip("'")
            _add_reference_key_with_aliases(keys, after)

    obj_path = ref.get("ObjectPath", "")
    if isinstance(obj_path, str) and obj_path:
        _add_reference_key_with_aliases(keys, obj_path.strip())

    return {key for key in keys if key}


def _object_reference_lookup_keys(ref: dict) -> list[str]:
    """Return AttachParent lookup keys with exact UE refs first, XENGINE__ aliases as fallback."""
    exact_keys: list[str] = []
    alias_keys: list[str] = []

    def _append_unique(target: list[str], key: str):
        if key and key not in exact_keys and key not in alias_keys:
            target.append(key)

    def _add_exact(key: str):
        if not key:
            return
        _append_unique(exact_keys, key)
        for alias in _xengine_reference_aliases(key):
            _append_unique(alias_keys, alias)

    if not isinstance(ref, dict):
        return []

    obj_name = ref.get("ObjectName", "")
    if isinstance(obj_name, str) and obj_name:
        cleaned = obj_name.strip()
        _add_exact(cleaned)
        if "PersistentLevel." in cleaned:
            _add_exact(cleaned.split("PersistentLevel.", 1)[1].rstrip("'"))

    obj_path = ref.get("ObjectPath", "")
    if isinstance(obj_path, str) and obj_path:
        cleaned = obj_path.strip()
        _add_exact(cleaned)
        if "PersistentLevel." in cleaned:
            _add_exact(cleaned.split("PersistentLevel.", 1)[1].rstrip("'"))

    return exact_keys + alias_keys


def _xengine_reference_aliases(key: str) -> set[str]:
    """Return lookup aliases with the XENGINE__ actor prefix stripped."""
    aliases: set[str] = set()
    if not isinstance(key, str) or "XENGINE__" not in key:
        return aliases

    def _strip_actor_prefix(path: str) -> str | None:
        actor, sep, rest = path.partition(".")
        if not actor.startswith("XENGINE__"):
            return None
        actor = actor[len("XENGINE__"):]
        return f"{actor}{sep}{rest}" if sep else actor

    if "PersistentLevel." in key:
        prefix, rest = key.split("PersistentLevel.", 1)
        normalized = _strip_actor_prefix(rest.rstrip("'"))
        if normalized:
            suffix = "'" if key.endswith("'") else ""
            aliases.add(f"{prefix}PersistentLevel.{normalized}{suffix}")
            aliases.add(normalized)
    else:
        normalized = _strip_actor_prefix(key.rstrip("'"))
        if normalized:
            suffix = "'" if key.endswith("'") else ""
            aliases.add(f"{normalized}{suffix}")

    return aliases


def _add_reference_key_with_aliases(keys: set[str], key: str):
    if not key:
        return
    keys.add(key)
    keys.update(_xengine_reference_aliases(key))


def _entry_component_reference_keys(entry: dict) -> set[str]:
    keys: set[str] = set()
    component_name = entry.get("Name")
    outer = entry.get("Outer", {})

    if not isinstance(component_name, str) or not component_name:
        return keys

    outer_obj_name = outer.get("ObjectName", "") if isinstance(outer, dict) else ""
    if isinstance(outer_obj_name, str) and outer_obj_name:
        if "'" in outer_obj_name:
            outer_path = outer_obj_name.split("'", 1)[1].rstrip("'")
            full_component_path = f"{outer_path}.{component_name}"
            _add_reference_key_with_aliases(keys, f"{entry.get('Type')}'{full_component_path}'")
            if "PersistentLevel." in full_component_path:
                _add_reference_key_with_aliases(
                    keys,
                    full_component_path.split("PersistentLevel.", 1)[1],
                )

    if isinstance(outer, str) and outer:
        _add_reference_key_with_aliases(keys, f"{outer}.{component_name}")

    return keys


def register_component_object(
    component_objects: dict[str, bpy.types.Object],
    entry: dict,
    obj: bpy.types.Object,
):
    """Register *obj* under the Unreal component-reference keys for *entry*."""
    if obj is None:
        return
    for key in _entry_component_reference_keys(entry):
        component_objects[key] = obj


def _register_actor_object(
    actor_objects: dict[str, bpy.types.Object],
    actor_name: str,
    obj: bpy.types.Object,
):
    """Register an object by actor/Outer name plus XENGINE__ aliases."""
    if not actor_name or obj is None:
        return
    actor_objects[actor_name] = obj
    for alias in _xengine_reference_aliases(actor_name):
        actor_objects.setdefault(alias, obj)


def intact_physics_asset_name_from_part_name(part_name: str) -> str | None:
    """Map break-part names like Sofa_Multi_01A_1_Physics to Sofa_Multi_01A_0_Physics."""
    if not isinstance(part_name, str):
        return None
    match = re.match(r"^(.+)_(\d+)_Physics$", part_name)
    if not match:
        return None
    return f"{match.group(1)}_0_Physics"


def collect_physics_root_fallback_asset_names(data: list) -> dict[str, str]:
    """Map physics root component reference keys to their intact _0_Physics asset name."""
    fallback_asset_names: dict[str, str] = {}

    for entry in data:
        if not isinstance(entry, dict) or entry.get("Type") != "EndStaticMeshPhysicsPartsComponent":
            continue

        asset_name = intact_physics_asset_name_from_part_name(entry.get("Name", ""))
        if not asset_name:
            continue

        props = entry.get("Properties", {})
        if not isinstance(props, dict):
            continue

        for key in _object_reference_lookup_keys(props.get("AttachParent", {})):
            fallback_asset_names.setdefault(key, asset_name)

    return fallback_asset_names


def physics_root_fallback_asset_name_for_entry(
    entry: dict,
    physics_root_fallback_asset_names: dict[str, str],
) -> str | None:
    if not physics_root_fallback_asset_names:
        return None
    for key in _entry_component_reference_keys(entry):
        asset_name = physics_root_fallback_asset_names.get(key)
        if asset_name:
            return asset_name
    return None


def _reference_export_index(ref: dict) -> int | None:
    """Return the numeric export index at the end of an ObjectPath, if present."""
    if not isinstance(ref, dict):
        return None
    obj_path = ref.get("ObjectPath", "")
    if not isinstance(obj_path, str) or "." not in obj_path:
        return None
    suffix = obj_path.rsplit(".", 1)[-1]
    try:
        return int(suffix)
    except ValueError:
        return None


def register_override_material_targets(
    material_targets: dict[int, bpy.types.Object],
    props: dict,
    obj: bpy.types.Object,
):
    """Map MaterialInstanceDynamic export indices from OverrideMaterials to *obj*."""
    for ref in props.get("OverrideMaterials", []) or []:
        export_index = _reference_export_index(ref)
        if export_index is not None:
            material_targets[export_index] = obj


def _color_prop_values(color: dict) -> tuple[list[float] | None, str | None]:
    if not isinstance(color, dict):
        return None, None
    channels = []
    for channel in ("R", "G", "B", "A"):
        if channel in color:
            channels.append(_float_or_default(color.get(channel)))
    hex_value = color.get("Hex")
    return (channels or None), hex_value if isinstance(hex_value, str) else None


def _apply_material_parameter_light_props(
    obj: bpy.types.Object,
    props: dict,
    exposure_mult: float = 1.0,
):
    mpl = props.get("MaterialParameterLight", {})
    if obj is None or not isinstance(mpl, dict):
        return
    if "Intensity" in mpl:
        intensity = _float_or_default(mpl.get("Intensity"))
        obj["material_parameter_light_intensity"] = intensity
        light_data = getattr(obj, "data", None)
        if light_data is not None and hasattr(light_data, "energy"):
            lights.set_light_energy(light_data, intensity * exposure_mult)
    if "ColorTemperature" in mpl:
        temperature = _float_or_default(mpl.get("ColorTemperature"))
        obj["material_parameter_light_color_temperature"] = temperature
        light_data = getattr(obj, "data", None)
        if light_data is not None:
            if hasattr(light_data, "use_temperature"):
                light_data.use_temperature = True
            if hasattr(light_data, "temperature"):
                light_data.temperature = temperature
    color_value, hex_value = _color_prop_values(mpl.get("Color", {}))
    if color_value is not None:
        obj["material_parameter_light_color"] = color_value
        light_data = getattr(obj, "data", None)
        if light_data is not None and hasattr(light_data, "color") and len(color_value) >= 3:
            lights.set_light_color(
                light_data,
                (
                    max(0.0, min(1.0, color_value[0] / 255.0)),
                    max(0.0, min(1.0, color_value[1] / 255.0)),
                    max(0.0, min(1.0, color_value[2] / 255.0)),
                ),
            )
            # MaterialParameterLight's FColor is the authored light colour.
            # Do not let Blender apply ColorTemperature a second time to it.
            if hasattr(light_data, "use_temperature"):
                light_data.use_temperature = False
    if hex_value is not None:
        obj["material_parameter_light_color_hex"] = hex_value


def _apply_vector_parameter_props(obj: bpy.types.Object, props: dict):
    if obj is None:
        return
    for param in props.get("VectorParameterValues", []) or []:
        if not isinstance(param, dict):
            continue
        info = param.get("ParameterInfo", {})
        name = info.get("Name", "VectorParameter")
        value = param.get("ParameterValue", {})
        if not isinstance(name, str) or not isinstance(value, dict):
            continue
        color_value, hex_value = _color_prop_values(value)
        prop_prefix = (
            _EXTERNAL_EMISSIVE_CONTEXT_PROP
            if name == _EXTERNAL_EMISSIVE_CONTEXT_PROP
            else f"material_vector_{name}"
        )
        if color_value is not None:
            subtype = "COLOR" if name == _EXTERNAL_EMISSIVE_CONTEXT_PROP else None
            _set_custom_property(obj, prop_prefix, color_value, subtype=subtype)
        if hex_value is not None:
            obj[f"{prop_prefix}_hex"] = hex_value


def resolve_attach_parent_object(
    props: dict,
    component_objects: dict[str, bpy.types.Object],
    child_name: str = "object",
    report_missing: bool = True,
) -> bpy.types.Object | None:
    """Resolve Properties.AttachParent to a previously imported Blender object."""
    attach_parent = props.get("AttachParent", {})
    if not attach_parent:
        return None

    lookup_keys = _object_reference_lookup_keys(attach_parent)
    for key in lookup_keys:
        obj = component_objects.get(key)
        if obj is not None:
            return obj

    actor_name = _resolve_attach_parent_name(props)
    if actor_name:
        obj = bpy.data.objects.get(actor_name)
        if obj is not None:
            return obj

    if report_missing:
        object_name = attach_parent.get("ObjectName", "<missing ObjectName>")
        print(
            f"[Rebirth Map Import]   AttachParent for '{child_name}' could not be resolved: "
            f"{object_name!r} (tried {len(lookup_keys)} key(s))."
        )
    return None


def apply_deferred_light_parent(
    light_obj: bpy.types.Object,
    props: dict,
    parent_obj: bpy.types.Object,
    location_scale: float,
):
    """Parent a previously-created light while keeping JSON local transform semantics."""
    light_obj.parent = parent_obj
    loc_dict = props.get("RelativeLocation", {})
    rot_dict = props.get("RelativeRotation", {})
    light_obj.location = location_from_relative(loc_dict, scale_factor=location_scale)
    if getattr(light_obj.data, "type", None) == "SPOT":
        light_obj.rotation_euler = light_rotation_from_relative(rot_dict)
    else:
        light_obj.rotation_euler = rotation_from_relative(rot_dict)
    light_obj.scale = scale_from_entry(props)


def apply_deferred_object_parent(
    child_obj: bpy.types.Object,
    props: dict,
    parent_obj: bpy.types.Object,
    location_scale: float,
):
    """Parent a mesh/helper object while keeping JSON local transform semantics."""
    child_obj.parent = parent_obj
    loc_dict = props.get("RelativeLocation", {})
    rot_dict = props.get("RelativeRotation", {})
    child_obj.location = location_from_relative(loc_dict, scale_factor=location_scale)
    child_obj.rotation_euler = rotation_from_relative(rot_dict)
    child_obj.scale = scale_from_entry(props)


def outer_to_instance_name(outer_name: str, asset_name: str) -> str:
    """Convert UE duplicate-suffix ``_N`` to Blender dot-suffix ``.N`` (e.g. ``Mesh_2`` -> ``Mesh.2``)."""
    if asset_name and outer_name.startswith(asset_name):
        remainder = outer_name[len(asset_name):]
        m = re.match(r"^_(\d+)$", remainder)
        if m:
            return f"{asset_name}.{m.group(1)}"
    return outer_name


def create_mesh_empty(
    name: str,
    loc: "Vector",
    rot: "Euler",
    parent_collection: "bpy.types.Collection",
    scale: Vector | None = None,
):
    obj = bpy.data.objects.new(name, None)
    obj.empty_display_type = "PLAIN_AXES"
    obj.empty_display_size = 1.0
    obj.location = loc
    obj.rotation_euler = rot
    if scale is not None:
        obj.scale = scale
    parent_collection.objects.link(obj)
    return obj


def resolve_game_asset_file_path(asset_path_name: str, game_root: str, extension: str) -> str | None:
    """Map a /Game/... asset path to a local file path under game_root."""
    if not game_root or not asset_path_name:
        return None

    prefix = "/Game/"
    if asset_path_name.startswith(prefix):
        rel = asset_path_name[len(prefix):]
    else:
        rel = asset_path_name.lstrip("/")

    rel_no_suffix = rel.split(".", 1)[0]
    rel_path = rel_no_suffix + extension
    rel_path_parts = rel_path.split("/")
    return os.path.join(game_root, *rel_path_parts)


def collect_level_streaming_asset_paths(data: list) -> list[str]:
    """Return asset paths from LevelStreamingAlwaysLoaded/Dynamic entries (preferred over EndStreamingVolume)."""
    asset_paths: list[str] = []
    seen: set[str] = set()

    for entry in data:
        if not isinstance(entry, dict):
            continue
        if entry.get("Type") not in {"LevelStreamingAlwaysLoaded", "LevelStreamingDynamic"}:
            continue

        props = entry.get("Properties", {})
        if not isinstance(props, dict):
            continue
        world_asset = props.get("WorldAsset")
        if not isinstance(world_asset, dict):
            continue

        asset_path_name = world_asset.get("AssetPathName")
        if not asset_path_name or asset_path_name in seen:
            continue
        seen.add(asset_path_name)
        asset_paths.append(asset_path_name)

    return asset_paths


def collect_volume_streaming_asset_paths(data: list) -> list[str]:
    asset_paths: list[str] = []
    seen: set[str] = set()

    for entry in data:
        if not isinstance(entry, dict) or entry.get("Type") != "EndStreamingVolume":
            continue

        props = entry.get("Properties", {})
        if not isinstance(props, dict):
            continue
        levels = props.get("StreamingLevels", [])
        if not isinstance(levels, list):
            continue

        for lvl in levels:
            if not isinstance(lvl, dict):
                continue
            asset_path_name = lvl.get("AssetPathName")
            if not asset_path_name or asset_path_name in seen:
                continue
            seen.add(asset_path_name)
            asset_paths.append(asset_path_name)

    return asset_paths


def resolve_massive_environment_umap_path(entry: dict, game_root: str) -> str | None:
    """Resolve a MassiveEnvironmentComponent StreamingProxy ObjectPath to a local .umap path."""
    props = entry.get("Properties", {})
    if not isinstance(props, dict):
        return None

    streaming_proxy = props.get("StreamingProxy")
    if not isinstance(streaming_proxy, dict):
        return None

    asset_path_name = streaming_proxy.get("ObjectPath")
    return resolve_game_asset_file_path(asset_path_name, game_root, ".umap")


def get_umap_import_function():
    try:
        importer_module = importlib.import_module(f"{__package__.rsplit('.', 1)[0]}.mec.importer")
    except Exception as exc:
        print(f"[Rebirth Map Import]   Bundled FF7R .umap importer is not available: {exc}")
        return None
    return getattr(importer_module, "import_umap_paths", None)


def is_umap_addon_available() -> bool:
    """Return True when the bundled Massive Environment .umap importer can be called."""
    try:
        importer_module = importlib.import_module(f"{__package__.rsplit('.', 1)[0]}.mec.importer")
    except Exception:
        return False
    return callable(getattr(importer_module, "import_umap_paths", None))


def import_massive_environment_umap(
    entry: dict,
    game_root: str,
    imported_umap_paths: set[str],
    texture_index_cache: TextureIndexCache | None = None,
    offset_opposite_faces: bool = False,
    scale_factor: float = 0.01,
) -> tuple[int, int, set[str]]:
    if not game_root:
        print("[Rebirth Map Import]   MassiveEnvironmentComponent found but Game Root is not set - skipping .umap import.")
        return 0, 1, set()

    umap_path = resolve_massive_environment_umap_path(entry, game_root)
    if not umap_path:
        print("[Rebirth Map Import]   MassiveEnvironmentComponent path could not be resolved - skipping .umap import.")
        return 0, 1, set()

    umap_path = os.path.realpath(umap_path)
    if umap_path in imported_umap_paths:
        print(f"[Rebirth Map Import]   MassiveEnvironment .umap already imported: {umap_path}")
        return 0, 0, set()

    if not os.path.exists(umap_path):
        print(f"[Rebirth Map Import]   MassiveEnvironment .umap not found: {umap_path}")
        imported_umap_paths.add(umap_path)
        return 0, 1, set()

    import_umap_paths = get_umap_import_function()
    if import_umap_paths is None:
        imported_umap_paths.add(umap_path)
        return 0, 1, set()

    print(f"[Rebirth Map Import]   Importing MassiveEnvironment .umap: {umap_path}")
    imported_umap_paths.add(umap_path)
    try:
        processed, skipped, _unresolved_count = import_umap_paths(
            bpy.context,
            [umap_path],
            lod_mode="LEVEL",
            lod_level=0,
            scale_factor=scale_factor,
            texture_index_cache=texture_index_cache,
            offset_opposite_faces=offset_opposite_faces,
        )
        return processed, skipped, set()
    except Exception as exc:
        print(f"[Rebirth Map Import]   MassiveEnvironment .umap import failed for {umap_path}: {exc}")
        return 0, 1, set()


def find_bone_by_socket_name(armature_obj: bpy.types.Object, socket_name: str):
    if armature_obj is None or armature_obj.type != "ARMATURE":
        return None
    return socket_name if armature_obj.data.bones.get(socket_name) is not None else None


def _resolve_attach_parent_name(props: dict) -> str | None:
    attach_parent = props.get("AttachParent", {})
    if not isinstance(attach_parent, dict):
        return None
    obj_name = attach_parent.get("ObjectName", "")
    if not obj_name:
        return None
    if "PersistentLevel." in obj_name:
        after = obj_name.split("PersistentLevel.", 1)[1]
        return after.split(".")[0].rstrip("'") or None
    return obj_name.rsplit(".", 1)[-1].strip("'") or None


def parent_to_bone(
    child_obj: bpy.types.Object,
    armature_obj: bpy.types.Object,
    bone_name: str,
    props: dict,
    location_scale: float,
):
    """Bone-parent an attachment using its UE socket-local transform.

    Blender's bone-parent frame is at a bone's tail.  Rebase the UE component
    transform from the socket bone's head onto that frame so the package
    socket-local transform is preserved.
    """
    bone = armature_obj.data.bones.get(bone_name)
    if bone is None:
        return
    loc = location_from_relative(
        props.get("RelativeLocation", {}), scale_factor=location_scale
    )
    if getattr(child_obj.data, "type", None) == "SPOT":
        rot = light_rotation_from_relative(props.get("RelativeRotation", {}))
    else:
        rot = rotation_from_relative(props.get("RelativeRotation", {}))
    relative_matrix = Matrix.LocRotScale(loc, rot, scale_from_entry(props))
    socket_head_matrix = bone.matrix_local @ relative_matrix
    bone_parent_frame = bone.matrix_local @ Matrix.Translation((0.0, bone.length, 0.0))
    child_obj.parent = armature_obj
    child_obj.parent_type = "BONE"
    child_obj.parent_bone = bone_name
    child_obj.matrix_parent_inverse = Matrix.Identity(4)
    child_obj.matrix_basis = bone_parent_frame.inverted() @ socket_head_matrix


def _apply_deferred_parent_transform(
    child_obj: bpy.types.Object,
    props: dict,
    parent_obj: bpy.types.Object,
    location_scale: float,
) -> None:
    if getattr(child_obj.data, "type", None) in {"POINT", "SPOT"}:
        apply_deferred_light_parent(child_obj, props, parent_obj, location_scale)
    else:
        apply_deferred_object_parent(child_obj, props, parent_obj, location_scale)


def process_deferred_attach(
    child_obj: bpy.types.Object,
    props: dict,
    attach_socket: str,
    location_scale: float,
    component_objects: dict[str, bpy.types.Object],
):
    target_instance = resolve_attach_parent_object(
        props, component_objects, child_obj.name, report_missing=False
    )
    if target_instance is None:
        attach_actor_name = _resolve_attach_parent_name(props)
        target_instance = bpy.data.objects.get(attach_actor_name) if attach_actor_name else None
    if target_instance is None:
        print(f"[Rebirth Map Import]   AttachSocketName '{attach_socket}': parent not found for '{child_obj.name}'.")
        return

    armature_obj = None
    if target_instance.type == "ARMATURE":
        armature_obj = target_instance
    else:
        for child in target_instance.children_recursive:
            if child.type == "ARMATURE":
                armature_obj = child
                break

    if armature_obj is None:
        _apply_deferred_parent_transform(child_obj, props, target_instance, location_scale)
        return

    bone_name = find_bone_by_socket_name(armature_obj, attach_socket)
    if bone_name:
        parent_to_bone(child_obj, armature_obj, bone_name, props, location_scale)
    else:
        _apply_deferred_parent_transform(child_obj, props, target_instance, location_scale)


def create_static_mesh_instance_from_datablock(
    mesh: bpy.types.Mesh,
    name: str,
    loc: Vector,
    rot: Euler,
    static_collection: bpy.types.Collection,
    rel_scale: Vector,
) -> bpy.types.Object:
    """Instance an already-imported package mesh without duplicating its data."""
    obj = bpy.data.objects.new(name, mesh)
    obj.location = loc
    obj.rotation_euler = rot
    obj.scale = rel_scale
    if mesh.get("ff7r_virtual_path"):
        obj["ff7r_virtual_path"] = mesh["ff7r_virtual_path"]
    static_collection.objects.link(obj)
    _initialize_external_emissive_context(obj)
    return obj


def create_package_skeletal_mesh_instance(
    asset: SkeletalMeshDatablocks,
    name: str,
    loc: Vector,
    rot: Euler,
    skeletal_collection: bpy.types.Collection,
    rel_scale: Vector,
) -> bpy.types.Object:
    """Place a package SkeletalMesh using shared Mesh/Armature datablocks.

    The armature is the component root when available.  Its child mesh has
    per-object vertex groups and an Armature modifier, but both objects reuse
    the cached game asset's datablocks.  This mirrors static-mesh placement and
    leaves no helper empty or collection-instance source behind.
    """
    armature_obj = None
    mesh_obj = None
    try:
        if asset.armature is not None:
            armature_obj = bpy.data.objects.new(name, asset.armature)
            armature_obj.location = loc
            armature_obj.rotation_mode = "XYZ"
            armature_obj.rotation_euler = rot
            armature_obj.scale = rel_scale
            skeletal_collection.objects.link(armature_obj)
            mesh_obj = bpy.data.objects.new(f"{name}_Mesh", asset.mesh)
            skeletal_collection.objects.link(mesh_obj)
            _bind_package_skeletal_mesh_object(
                mesh_obj,
                asset.skeletal_mesh,
                armature_obj,
                preserve_world_transform=False,
            )
            root_obj = armature_obj
        else:
            mesh_obj = bpy.data.objects.new(name, asset.mesh)
            mesh_obj.location = loc
            mesh_obj.rotation_mode = "XYZ"
            mesh_obj.rotation_euler = rot
            mesh_obj.scale = rel_scale
            skeletal_collection.objects.link(mesh_obj)
            # Preserve the skin groups even if the asset has no usable skeleton.
            _bind_package_skeletal_mesh_object(mesh_obj, asset.skeletal_mesh)
            root_obj = mesh_obj

        for obj in (root_obj, mesh_obj):
            obj["source_name"] = name
            obj["template_object_path"] = asset.virtual_path
        if armature_obj is not None:
            armature_obj["ff7r_skeleton_asset_path"] = (
                asset.skeletal_mesh.get("skeletonPath") or ""
            )
        mesh_obj["ff7r_skeletal_mesh_lod"] = int(asset.skeletal_mesh.get("lodIndex", 0))
        mesh_obj["ff7r_normal_format"] = asset.skeletal_mesh.get("normalFormat") or ""
        mesh_obj["ff7r_linked_skeleton_path"] = asset.skeletal_mesh.get("skeletonPath") or ""
        _initialize_external_emissive_context(mesh_obj)
        return root_obj
    except Exception:
        if mesh_obj is not None:
            bpy.data.objects.remove(mesh_obj, do_unlink=True)
        if armature_obj is not None:
            bpy.data.objects.remove(armature_obj, do_unlink=True)
        raise


def collect_asset_names_for_import(data: list) -> tuple[set[str], set[str]]:
    static_asset_names: set[str] = set()
    skeletal_asset_names: set[str] = set()

    static_asset_names.update(collect_physics_root_fallback_asset_names(data).values())

    for entry in data:
        if not isinstance(entry, dict):
            continue

        t = entry.get("Type")
        if t in {"EndEnvironmentStaticMeshComponent", "StaticMeshComponent"}:
            props = entry.get("Properties", {})
            static_mesh = props.get("StaticMesh", {})
            if isinstance(static_mesh, dict):
                asset_name = extract_static_mesh_name(static_mesh.get("ObjectName"))
                if asset_name:
                    static_asset_names.add(asset_name)
        elif t in {"EndSkeletalMeshComponent", "SkeletalMeshComponent"}:
            asset_name, _template_object_path = extract_skeletal_mesh_name(entry)
            if asset_name:
                skeletal_asset_names.add(asset_name)

    return static_asset_names, skeletal_asset_names


def collect_package_static_mesh_paths_for_import(data: list) -> set[str]:
    """Collect full StaticMesh object paths supplied by a package UMAP payload."""
    paths: set[str] = set()
    for entry in data:
        if not isinstance(entry, dict) or entry.get("Type") not in {
            "EndEnvironmentStaticMeshComponent", "StaticMeshComponent",
        }:
            continue
        props = entry.get("Properties", {})
        static_mesh = props.get("StaticMesh", {}) if isinstance(props, dict) else {}
        game_path = extract_static_mesh_game_path(static_mesh)
        if game_path:
            paths.add(game_path)
    return paths


def collect_package_skeletal_mesh_paths_for_import(data: list) -> set[str]:
    """Collect full SkeletalMesh object paths supplied by a package UMAP payload."""
    paths: set[str] = set()
    for entry in data:
        if not isinstance(entry, dict) or entry.get("Type") not in {
            "EndSkeletalMeshComponent", "SkeletalMeshComponent",
        }:
            continue
        _asset_name, template_object_path = extract_skeletal_mesh_name(entry)
        if template_object_path:
            paths.add(template_object_path)
    return paths


def create_setpos_object_from_entry(
    entry: dict,
    lookup_name: str,
    parent_collection: bpy.types.Collection,
    location_scale: float,
) -> bpy.types.Object:
    props = entry.get("Properties", {})
    if not isinstance(props, dict):
        props = {}

    loc_dict = props.get("RelativeLocation", entry.get("RelativeLocation", {}))
    rot_dict = props.get("RelativeRotation", entry.get("RelativeRotation", {}))
    loc = location_from_relative(loc_dict, scale_factor=location_scale)
    rot = rotation_from_relative(rot_dict)
    rel_scale = scale_from_entry(props, entry)

    instance_name = _resolve_outer_name(entry)
    if not instance_name:
        component_name = entry.get("Name", "SceneComponent")
        instance_name = component_name if isinstance(component_name, str) and component_name else "SceneComponent"

    obj = create_mesh_empty(instance_name, loc, rot, parent_collection, scale=rel_scale)

    obj["source_name"] = instance_name
    obj["source_type"] = entry.get("Type", "")
    obj["setpos_lookup_name"] = lookup_name
    return obj


def create_layout_object_pack_object(
    key: str,
    value: dict,
    parent_collection: bpy.types.Collection,
    location_scale: float,
) -> bpy.types.Object:
    transform = value.get("Transform", {}) if isinstance(value, dict) else {}
    loc, rot, rel_scale = transform_location_rotation_scale(transform, scale_factor=location_scale)

    lookup_name = extract_setpos_lookup_name(key)
    obj = create_mesh_empty(key, loc, rot, parent_collection, scale=rel_scale)

    obj["source_name"] = key
    obj["source_type"] = "EndLayoutObjectPack"
    if isinstance(value, dict):
        if "TypeHash" in value:
            obj["layout_object_type_hash"] = value["TypeHash"]
        if "IndexToAppendParam" in value:
            obj["layout_object_index_to_append_param"] = value["IndexToAppendParam"]
    if lookup_name:
        obj["setpos_lookup_name"] = lookup_name
    return obj


def import_map_entries(
    data: list[dict],
    source_name: str,
    exposure_mult: float,
    attenuation_radius_mult: float,
    import_finite_fog: bool = False,
    location_scale: float = 0.01,
    always_cast_shadows: bool = False,
    static_mesh_resolver=None,
    skeletal_mesh_resolver=None,
    import_models: bool = True,
    import_lights: bool = True,
    import_reflection_probes: bool | None = None,
) -> tuple[int, set[str]]:
    """Create requested Blender models and lights from package-decoded UMAP entries."""
    location_scale = _float_or_default(location_scale, 0.01)

    if not isinstance(data, list):
        raise ValueError("Package map entries must be a list of objects")

    print(f"[Rebirth Map Import] Decoded {len(data)} top-level entries from {source_name}.")

    physics_root_fallback_asset_names = (
        collect_physics_root_fallback_asset_names(data) if import_models else set()
    )

    static_asset_names = (
        collect_package_static_mesh_paths_for_import(data) if import_models else set()
    )
    static_asset_cache = {}
    if static_mesh_resolver is not None:
        for asset_name in sorted(static_asset_names, key=str.casefold):
            try:
                static_asset_cache[asset_name] = static_mesh_resolver(asset_name)
            except Exception as exc:
                static_asset_cache[asset_name] = None
                print(
                    f"[Rebirth Map Import] ERROR: Game StaticMesh '{asset_name}' "
                    f"could not be imported: {exc}"
                )
    # Skeletal packages are substantially heavier than static component assets.
    # Build them on first placement below rather than all at once: maps such as
    # 2350-GOLDS_Gimmick reference dozens of unique rigs, and eager construction
    # delays all lights until the entire skeletal batch has completed.
    skeletal_asset_cache = {}
    non_renderable_skeletal_assets = set()

    parent_collection = None

    def ensure_root_collection() -> bpy.types.Collection:
        nonlocal parent_collection
        if parent_collection is None:
            parent_collection = ensure_parent_collection_for_source(source_name)
        return parent_collection

    def ensure_static_collection() -> bpy.types.Collection:
        return ensure_typed_import_collection(ensure_root_collection(), "_Static")

    def ensure_skeletal_collection() -> bpy.types.Collection:
        return ensure_typed_import_collection(ensure_root_collection(), "_Skeletal")

    def ensure_lights_collection() -> bpy.types.Collection:
        return ensure_typed_import_collection(ensure_root_collection(), "_Lights")

    def ensure_setpos_collection() -> bpy.types.Collection:
        return ensure_typed_import_collection(ensure_root_collection(), "_SetPos")

    def ensure_layout_objects_collection() -> bpy.types.Collection:
        return ensure_typed_import_collection(ensure_root_collection(), "_LayoutObjects")

    created_count = 0
    missing_assets: set[str] = set()
    pending_parent_attaches: list[tuple[bpy.types.Object, dict, str]] = []
    pending_attaches: list[tuple[bpy.types.Object, dict, str]] = []
    pending_light_attaches: list[tuple[bpy.types.Object, dict, str]] = []
    component_objects: dict[str, bpy.types.Object] = {}
    actor_objects: dict[str, bpy.types.Object] = {}
    light_objects_by_outer: dict[str, list[bpy.types.Object]] = {}
    material_targets: dict[int, bpy.types.Object] = {}
    pending_material_parameter_lights: list[dict] = []
    pending_vector_parameters: list[tuple[int, dict]] = []
    map_mesh_objects: list[bpy.types.Object] = []
    if import_models:
        created_count += particles.create_niagara_empties_from_effect_json(
            data,
            source_name,
            location_scale=location_scale,
        )
        if worlds.create_world_from_level_data(data, source_name):
            created_count += 1
        if import_finite_fog:
            created_count += worlds.create_finite_fog_volume_from_level_data(
                data,
                source_name,
                location_scale=location_scale,
            )
    if import_reflection_probes is None:
        import_reflection_probes = import_models
    if import_reflection_probes:
        created_count += worlds.create_reflection_capture_probes(
            data,
            source_name,
            location_scale=location_scale,
            include_box_reflection_captures=True,
        )

    # Create non-skeletal components first.  Deferred attachment resolution below
    # preserves parent/socket relationships even when a light targets a rig that
    # is materialized in the following skeletal pass.
    ordered_entries = [
        (index, entry) for index, entry in enumerate(data)
        if not isinstance(entry, dict) or entry.get("Type") not in {
            "EndSkeletalMeshComponent", "SkeletalMeshComponent",
        }
    ] + [
        (index, entry) for index, entry in enumerate(data)
        if isinstance(entry, dict) and entry.get("Type") in {
            "EndSkeletalMeshComponent", "SkeletalMeshComponent",
        }
    ]
    for entry_index, entry in ordered_entries:
        if not isinstance(entry, dict):
            continue

        t = entry.get("Type")

        if import_models and t in {"EndEnvironmentStaticMeshComponent", "StaticMeshComponent"}:
            props = entry.get("Properties", {})
            if not isinstance(props, dict):
                props = {}
            static_mesh = props.get("StaticMesh", {})
            object_name_str = static_mesh.get("ObjectName") if isinstance(static_mesh, dict) else None

            asset_name = extract_static_mesh_name(object_name_str)
            game_asset_path = extract_static_mesh_game_path(static_mesh)
            asset_key = game_asset_path
            rel_loc = props.get("RelativeLocation", {})
            rel_rot = props.get("RelativeRotation", {})
            rel_scale = scale_from_entry(props, entry)
            loc = location_from_relative(rel_loc, scale_factor=location_scale)
            rot = rotation_from_relative(rel_rot)

            static_collection = ensure_static_collection()

            attach_socket = props.get("AttachSocketName")
            has_attach_socket = bool(attach_socket)
            component_name = entry.get("Name", "StaticMeshComponent")
            component_name = (
                component_name
                if isinstance(component_name, str) and component_name
                else "StaticMeshComponent"
            )
            attach_name = _resolve_outer_name(entry) or asset_name or component_name
            asset = static_asset_cache.get(asset_key) if asset_key else None
            if not asset_name:
                fallback_asset_name = physics_root_fallback_asset_name_for_entry(
                    entry,
                    physics_root_fallback_asset_names,
                )
                if not fallback_asset_name:
                    print(
                        f"[Rebirth Map Import]   Warning: StaticMesh entry has no parseable ObjectName "
                        f"for '{attach_name}' and no physics fallback - "
                        "using transform empty."
                    )
                    new_obj = create_mesh_empty(attach_name, loc, rot, static_collection, scale=rel_scale)
                    new_obj["source_name"] = attach_name
                    new_obj["source_type"] = t
                    new_obj["component_empty_reason"] = "no_static_mesh_attach_parent"
                else:
                    asset = static_asset_cache.get(fallback_asset_name)
                    if static_mesh_resolver is not None and asset is None:
                        try:
                            asset = static_mesh_resolver(fallback_asset_name)
                            static_asset_cache[fallback_asset_name] = asset
                        except Exception as exc:
                            static_asset_cache[fallback_asset_name] = None
                            print(
                                f"[Rebirth Map Import] ERROR: Game StaticMesh "
                                f"'{fallback_asset_name}' could not be imported: {exc}"
                            )
                    if asset is not None:
                        new_obj = create_static_mesh_instance_from_datablock(
                            mesh=asset, name=attach_name, loc=loc, rot=rot,
                            static_collection=static_collection, rel_scale=rel_scale,
                        )
                        new_obj["source_name"] = attach_name
                        new_obj["source_type"] = t
                        new_obj["physics_root_fallback_asset_name"] = fallback_asset_name
                        print(
                            f"[Rebirth Map Import]   Warning: StaticMesh entry has no parseable ObjectName "
                            f"for '{attach_name}' - using physics fallback asset "
                            f"'{fallback_asset_name}' | "
                            f"loc=({loc.x:.3f},{loc.y:.3f},{loc.z:.3f})"
                        )
                    else:
                        missing_assets.add(fallback_asset_name)
                        new_obj = create_mesh_empty(attach_name, loc, rot, static_collection, scale=rel_scale)
                        new_obj["source_name"] = attach_name
                        new_obj["source_type"] = t
                        new_obj["component_empty_reason"] = "missing_physics_root_fallback_asset"
                        new_obj["physics_root_fallback_asset_name"] = fallback_asset_name
                        print(
                            f"[Rebirth Map Import]   Warning: StaticMesh entry has no parseable ObjectName "
                            f"and physics fallback asset is missing "
                            f"for '{attach_name}': '{fallback_asset_name}' - using transform empty."
                        )
            elif asset is not None:
                new_obj = create_static_mesh_instance_from_datablock(
                    mesh=asset, name=attach_name, loc=loc, rot=rot,
                    static_collection=static_collection, rel_scale=rel_scale,
                )
            else:
                missing_assets.add(asset_key or asset_name)
                placeholder_name = attach_name
                new_obj = create_mesh_empty(placeholder_name, loc, rot, static_collection, scale=rel_scale)
                print(
                    f"[Rebirth Map Import]   StaticMesh fallback empty '{placeholder_name}' | "
                    f"loc=({loc.x:.3f},{loc.y:.3f},{loc.z:.3f})"
                )

            if attach_socket:
                pending_attaches.append((new_obj, props, attach_socket))
                attach_socket = None

            register_component_object(component_objects, entry, new_obj)
            _register_actor_object(actor_objects, attach_name, new_obj)
            register_override_material_targets(material_targets, props, new_obj)
            map_mesh_objects.append(new_obj)

            if props.get("AttachParent") and not has_attach_socket:
                parent_obj = resolve_attach_parent_object(
                    props,
                    component_objects,
                    attach_name,
                    report_missing=False,
                )
                if parent_obj is not None:
                    apply_deferred_object_parent(
                        new_obj,
                        props,
                        parent_obj,
                        location_scale,
                    )
                else:
                    pending_parent_attaches.append((new_obj, props, attach_name))

            # -------------------------------------------------------------- #
            # AttachSocketName is resolved after all components exist.  Package
            # skeletal actors expose their sockets as identically named bones.
            # -------------------------------------------------------------- #
            created_count += 1

        elif import_models and t in {"EndSkeletalMeshComponent", "SkeletalMeshComponent"}:
            skeletal_collection = ensure_skeletal_collection()

            props = entry.get("Properties", {})
            loc_dict = props.get("RelativeLocation", entry.get("RelativeLocation", {}))
            rot_dict = props.get("RelativeRotation", entry.get("RelativeRotation", {}))
            rel_scale = scale_from_entry(props, entry)
            loc = location_from_relative(loc_dict, scale_factor=location_scale)
            rot = rotation_from_relative(rot_dict)

            asset_name, template_object_path = extract_skeletal_mesh_name(entry)

            outer_name = _resolve_outer_name(entry)
            if not outer_name:
                comp_name = entry.get("Name", "SkeletalMeshComponent")
                outer_name = comp_name if isinstance(comp_name, str) else "SkeletalMeshComponent"
            instance_name = outer_name

            asset_key = template_object_path
            asset = skeletal_asset_cache.get(asset_key) if asset_key else None
            if asset_key and asset_key not in skeletal_asset_cache and skeletal_mesh_resolver is not None:
                try:
                    asset = skeletal_mesh_resolver(asset_key)
                    skeletal_asset_cache[asset_key] = asset
                except Exception as exc:
                    skeletal_asset_cache[asset_key] = None
                    if "has no importable" in str(exc).casefold() and "lod" in str(exc).casefold():
                        non_renderable_skeletal_assets.add(asset_key)
                        print(
                            f"[Rebirth Map Import] Skipping renderless SkeletalMesh "
                            f"'{asset_key}' (the package has no renderable LOD)."
                        )
                    else:
                        print(
                            f"[Rebirth Map Import] ERROR: Game SkeletalMesh '{asset_key}' "
                            f"could not be imported: {exc}"
                        )

            if isinstance(asset, SkeletalMeshDatablocks):
                obj = create_package_skeletal_mesh_instance(
                    asset=asset,
                    name=instance_name,
                    loc=loc,
                    rot=rot,
                    skeletal_collection=skeletal_collection,
                    rel_scale=rel_scale,
                )
                print(
                    f"[Rebirth Map Import]   SkeletalMesh '{instance_name}' "
                    f"(asset lookup: '{asset_name}', "
                    f"template: '{template_object_path}') | "
                    f"loc=({loc.x:.3f},{loc.y:.3f},{loc.z:.3f})"
                )
            else:
                if asset_key and asset_key not in non_renderable_skeletal_assets:
                    missing_assets.add(asset_key)
                obj = create_mesh_empty(instance_name, loc, rot, skeletal_collection, scale=rel_scale)
                obj["source_name"] = instance_name
                if template_object_path:
                    obj["template_object_path"] = template_object_path
                print(
                    f"[Rebirth Map Import]   SkeletalMesh empty '{instance_name}' | "
                    f"loc=({loc.x:.3f},{loc.y:.3f},{loc.z:.3f})  "
                    f"rot=({math.degrees(rot.x):.2f},{math.degrees(rot.y):.2f},{math.degrees(rot.z):.2f}) deg"
                )

            register_component_object(component_objects, entry, obj)
            _register_actor_object(actor_objects, instance_name, obj)
            map_mesh_objects.append(obj)

            attach_socket = props.get("AttachSocketName")
            if attach_socket:
                pending_attaches.append((obj, props, attach_socket))
            elif props.get("AttachParent"):
                parent_obj = resolve_attach_parent_object(
                    props,
                    component_objects,
                    instance_name,
                    report_missing=False,
                )
                if parent_obj is not None:
                    apply_deferred_object_parent(
                        obj,
                        props,
                        parent_obj,
                        location_scale,
                    )
                else:
                    pending_parent_attaches.append((obj, props, instance_name))

            created_count += 1

        elif import_models and t == "SceneComponent" and extract_setpos_lookup_name_from_entry(entry):
            lookup_name = extract_setpos_lookup_name_from_entry(entry)
            setpos_collection = ensure_setpos_collection()
            obj = create_setpos_object_from_entry(
                entry=entry,
                lookup_name=lookup_name or "",
                parent_collection=setpos_collection,
                location_scale=location_scale,
            )

            register_component_object(component_objects, entry, obj)
            _register_actor_object(actor_objects, _resolve_outer_name(entry) or obj.name, obj)

            props = entry.get("Properties", {})
            if not isinstance(props, dict):
                props = {}
            if props.get("AttachParent"):
                parent_obj = resolve_attach_parent_object(
                    props,
                    component_objects,
                    obj.name,
                    report_missing=False,
                )
                if parent_obj is not None:
                    apply_deferred_object_parent(
                        obj,
                        props,
                        parent_obj,
                        location_scale,
                    )
                else:
                    pending_parent_attaches.append((obj, props, obj.name))

            created_count += 1

        elif import_models and t == "EndLayoutObjectPack":
            layout_collection = ensure_layout_objects_collection()
            pack_created_count = 0
            for key, value in iter_layout_object_pack_objects(entry):
                lookup_name = extract_setpos_lookup_name(key)
                obj = create_layout_object_pack_object(
                    key=key,
                    value=value,
                    parent_collection=layout_collection,
                    location_scale=location_scale,
                )
                _register_actor_object(actor_objects, key, obj)
                pack_created_count += 1

            created_count += pack_created_count

        elif import_lights and t == "PointLightComponent":
            lights_collection = ensure_lights_collection()

            props = entry.get("Properties", {})
            light_name = _resolve_light_name(entry, "PointLight")
            attach_socket = props.get("AttachSocketName")
            attach_parent_obj = None if attach_socket else resolve_attach_parent_object(
                props, component_objects, light_name, report_missing=False,
            )
            light_obj = create_point_light_from_entry(
                entry=entry,
                parent_collection=lights_collection,
                location_scale=location_scale,
                exposure_mult=exposure_mult,
                attenuation_radius_mult=attenuation_radius_mult,
                always_cast_shadows=always_cast_shadows,
                attach_parent_obj=attach_parent_obj,
            )
            outer_name = _resolve_outer_name(entry)
            if outer_name:
                light_objects_by_outer.setdefault(outer_name, []).append(light_obj)
            if attach_socket:
                pending_attaches.append((light_obj, props, attach_socket))
            elif attach_parent_obj is None and props.get("AttachParent"):
                pending_light_attaches.append((light_obj, props, light_name))
            created_count += 1

        elif import_lights and t == "SpotLightComponent":
            lights_collection = ensure_lights_collection()

            props = entry.get("Properties", {})
            light_name = _resolve_light_name(entry, "SpotLight")
            attach_socket = props.get("AttachSocketName")
            attach_parent_obj = None if attach_socket else resolve_attach_parent_object(
                props, component_objects, light_name, report_missing=False,
            )
            light_obj = create_spot_light_from_entry(
                entry=entry,
                parent_collection=lights_collection,
                location_scale=location_scale,
                exposure_mult=exposure_mult,
                attenuation_radius_mult=attenuation_radius_mult,
                always_cast_shadows=always_cast_shadows,
                attach_parent_obj=attach_parent_obj,
            )
            outer_name = _resolve_outer_name(entry)
            if outer_name:
                light_objects_by_outer.setdefault(outer_name, []).append(light_obj)
            if attach_socket:
                pending_attaches.append((light_obj, props, attach_socket))
            elif attach_parent_obj is None and props.get("AttachParent"):
                pending_light_attaches.append((light_obj, props, light_name))
            created_count += 1

        elif import_lights and t == "MaterialParameterLightPlacedComponent":
            pending_material_parameter_lights.append(entry)

        elif import_models and t == "MaterialInstanceDynamic":
            pending_vector_parameters.append((entry_index, entry))

        elif t in {"EndStreamingVolume", "MassiveEnvironmentComponent"}:
            # Package streaming recursion and MEC geometry are handled by the
            # package importer, which has direct access to mounted assets.
            continue

        # Other types ignored

    if pending_parent_attaches:
        for child_obj, props, child_name in pending_parent_attaches:
            parent_obj = resolve_attach_parent_object(
                props,
                component_objects,
                child_name,
                report_missing=True,
            )
            if parent_obj is not None:
                apply_deferred_object_parent(
                    child_obj,
                    props,
                    parent_obj,
                    location_scale,
                )

    if pending_attaches:
        print(
            f"[Rebirth Map Import] Processing {len(pending_attaches)} deferred attach request(s) "
            f"for '{os.path.basename(source_name)}'."
        )
        for child_obj, props, attach_socket in pending_attaches:
            process_deferred_attach(
                child_obj, props, attach_socket, location_scale, component_objects
            )

    if pending_light_attaches:
        for light_obj, props, light_name in pending_light_attaches:
            parent_obj = resolve_attach_parent_object(
                props,
                component_objects,
                light_name,
                report_missing=True,
            )
            if parent_obj is not None:
                apply_deferred_light_parent(
                    light_obj,
                    props,
                    parent_obj,
                    location_scale,
                )

    for entry in pending_material_parameter_lights:
        props = entry.get("Properties", {})
        outer_name = _resolve_outer_name(entry)
        targets: list[bpy.types.Object] = []
        actor_obj = actor_objects.get(outer_name)
        if actor_obj is not None:
            targets.append(actor_obj)
        targets.extend(light_objects_by_outer.get(outer_name, []))
        for target in targets:
            _apply_material_parameter_light_props(target, props, exposure_mult=exposure_mult)

    for export_index, entry in pending_vector_parameters:
        # Bridge actor lists are filtered, so their list offsets are not UE
        # export indices. Resolve the MID's owning component first.
        owner_keys = _object_reference_lookup_keys(entry.get("Outer", {}))
        target = next((component_objects[key] for key in owner_keys
                       if key in component_objects), None)
        if target is None:
            target = material_targets.get(export_index)
        if target is not None:
            _apply_vector_parameter_props(target, entry.get("Properties", {}))

    if map_mesh_objects:
        root = ensure_map_import_root(
            ensure_root_collection(), source_name, display_size=location_scale * 100.0,
        )
        parent_map_objects_to_root(root, map_mesh_objects)

    print(
        f"[Rebirth Map Import] Finished '{os.path.basename(source_name)}' - "
        f"{created_count} item(s) created, {len(missing_assets)} missing asset(s)."
    )
    return created_count, missing_assets
