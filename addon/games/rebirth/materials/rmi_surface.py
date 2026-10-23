"""Package StaticMesh integration for the researched FF7R RMI_Surface port.

This module loads the bundled surface, eye and hair builders and their variant
trimmer. It is called by the direct package
StaticMesh and SkeletalMesh importers -- and, through PackageStaticMeshResolver,
by the package UMAP importer's StaticMesh actors, since they share the same
importer.  Both mesh types reach it the same way, because the gargoyle reports a
section's material the same way for either (SkeletalMaterials vs
StaticMaterials). Loose MEC UMAPs, JSON imports, and non-RMI material instances
use their own material builders.
"""

from __future__ import annotations

from ....language import strings

import importlib.util
import json
import re
from pathlib import Path
from typing import Any, Callable

import bpy

from ....core.blender.material_nodes import set_color_space as _set_image_color_space, refresh_material_textures
from ....core.blender.import_cache import get_import_cache, remember_datablock
from ....core.package_utils import addon_package_name


_MODULES: tuple[dict[str, Any], Any, dict[str, list[str]]] | None = None
_MATERIAL_CACHE: dict[str, bpy.types.Material] = {}
_GAZE_NORMAL_OVERRIDE_IMAGE: bpy.types.Image | None = None
_COMMON_EYE_PLAYER_NG = "/game/character/common/eye/texture/common_eye_player_ng"
_RENDERER_CONSTANT_TEXTURE = re.compile(
    r"(?:^|/)([0-9a-f]{8})_(srgb|bc4|bc5|hdr)(?:\.[^/]*)?$", re.IGNORECASE
)
_LIMBAL_BONE_NAME = "C_Limbal"
_EYE_PATH_LABEL = "eye path (SM 9)"
EXTERNAL_EMISSIVE_CONTEXT_PROP = "ExternalEmissiveContext"
_EXTERNAL_EMISSIVE_SWITCH = "ExternalEmissive_"
EMISSIVE_CAMERA_ONLY_PROP = "sw EmissiveCameraOnly"
_LEGACY_EMISSIVE_CAMERA_ONLY_PROP = "EmissiveCameraOnly"
_EMISSIVE_SWITCH = "Emissive_"
_EXTERNAL_EMISSIVE_STATUS_PROP = "sw ff7r_external_emissive"
_EMISSIVE_STATUS_PROP = "sw ff7r_emissive"
_LEGACY_EXTERNAL_EMISSIVE_STATUS_PROP = "ff7r_external_emissive"
_LEGACY_EMISSIVE_STATUS_PROP = "ff7r_emissive"


def _migrate_switch_status_properties(material: bpy.types.Material) -> None:
    """Move importer switch-status flags into the visible switch group."""
    for old_name, new_name in (
            (_LEGACY_EXTERNAL_EMISSIVE_STATUS_PROP,
             _EXTERNAL_EMISSIVE_STATUS_PROP),
            (_LEGACY_EMISSIVE_STATUS_PROP, _EMISSIVE_STATUS_PROP)):
        if new_name not in material and old_name in material:
            material[new_name] = bool(material[old_name])
        if old_name in material:
            del material[old_name]


def _migrate_camera_only_emission(material: bpy.types.Material) -> None:
    """Update the camera-only emission attribute on an existing material."""
    tree = getattr(material, "node_tree", None)
    if tree is None:
        return
    existing_attribute = tree.nodes.get("EmissiveCameraOnlyAttribute")
    if existing_attribute is not None:
        existing_attribute.attribute_name = EMISSIVE_CAMERA_ONLY_PROP
        existing_attribute.label = f'object["{EMISSIVE_CAMERA_ONLY_PROP}"]'


def _external_emissive_context(props: dict[str, Any]) -> tuple[float, float, float] | None:
    """Read the material's FLinearColor default without clamping HDR values."""
    for entry in props.get("VectorParameterValues") or []:
        entry = _unwrap_struct(entry)
        if _parameter_name(entry) != EXTERNAL_EMISSIVE_CONTEXT_PROP:
            continue
        value = _unwrap_struct(_first(entry, "ParameterValue", "Value"))
        if not isinstance(value, dict):
            continue
        try:
            return tuple(float(_first(value, channel)) for channel in ("R", "G", "B"))
        except (TypeError, ValueError):
            return None
    return None


def _material_uses_external_emissive(material: bpy.types.Material) -> bool:
    return material is not None and (
        material.get(_EXTERNAL_EMISSIVE_STATUS_PROP,
                     material.get(_LEGACY_EXTERNAL_EMISSIVE_STATUS_PROP, False))
        or _EXTERNAL_EMISSIVE_SWITCH in material.get("_RMI_Variant_Switches", ())
    )


def _material_uses_emissive(material: bpy.types.Material) -> bool:
    return material is not None and (
        material.get(_EMISSIVE_STATUS_PROP,
                     material.get(_LEGACY_EMISSIVE_STATUS_PROP, False))
        or _EMISSIVE_SWITCH in material.get("_RMI_Variant_Switches", ())
    )


def _is_neutral_external_emissive(color) -> bool:
    return color is not None and len(color) >= 3 and all(
        abs(float(channel) - 1.0) < 1e-6 for channel in color[:3]
    )


def initialize_external_emissive_context(obj: bpy.types.Object) -> bool:
    """Initialize a mesh's per-instance emissive RGB from its RMI materials.

    A value already on the object always wins. Otherwise, a non-white material
    declaration wins over a neutral one; ties use material-slot order. This
    permits multiple materials on one mesh without a later neutral default
    erasing an authored value.
    """
    if obj is None or obj.type != "MESH":
        return False
    changed = False
    if _LEGACY_EMISSIVE_CAMERA_ONLY_PROP in obj:
        if EMISSIVE_CAMERA_ONLY_PROP not in obj:
            obj[EMISSIVE_CAMERA_ONLY_PROP] = bool(
                obj[_LEGACY_EMISSIVE_CAMERA_ONLY_PROP])
        del obj[_LEGACY_EMISSIVE_CAMERA_ONLY_PROP]
        try:
            obj.id_properties_ui(EMISSIVE_CAMERA_ONLY_PROP).update(
                description=strings.MATERIALS_EMISSIVE_CAMERA_ONLY
            )
        except Exception:
            pass
        changed = True
    contexts = [
        material.get("ff7r_external_emissive_context", (1.0, 1.0, 1.0))
        for material in obj.data.materials
        if _material_uses_external_emissive(material)
    ]
    if contexts and EXTERNAL_EMISSIVE_CONTEXT_PROP not in obj:
        context = next((value for value in contexts if not _is_neutral_external_emissive(value)),
                       contexts[0])
        obj[EXTERNAL_EMISSIVE_CONTEXT_PROP] = tuple(context[:3])
        try:
            obj.id_properties_ui(EXTERNAL_EMISSIVE_CONTEXT_PROP).update(subtype="COLOR")
        except Exception:
            pass
        changed = True
    if (EMISSIVE_CAMERA_ONLY_PROP not in obj
            and any(_material_uses_emissive(material) for material in obj.data.materials)):
        obj[EMISSIVE_CAMERA_ONLY_PROP] = True
        try:
            obj.id_properties_ui(EMISSIVE_CAMERA_ONLY_PROP).update(
                description=strings.MATERIALS_EMISSIVE_CAMERA_ONLY
            )
        except Exception:
            pass
        changed = True
    return changed


def _eye_path_nodes(material: bpy.types.Material) -> list[bpy.types.Node]:
    """Return the material's top-level RMI eye-path group instances."""
    tree = material.node_tree
    if tree is None:
        return []
    return [
        node for node in tree.nodes
        if node.bl_idname == "ShaderNodeGroup"
        and node.label == _EYE_PATH_LABEL
        and node.inputs.get("Light Position") is not None
    ]


def _set_limbal_driver(socket: bpy.types.NodeSocket, armature: bpy.types.Object) -> None:
    """Drive a vector socket from ``C_Limbal`` in world space."""
    for component, transform_type in enumerate(("LOC_X", "LOC_Y", "LOC_Z")):
        try:
            socket.driver_remove("default_value", component)
        except (TypeError, ValueError, RuntimeError):
            pass
        fcurve = socket.driver_add("default_value", component)
        driver = fcurve.driver
        driver.type = "AVERAGE"
        variable = driver.variables.new()
        variable.name = "limbal"
        variable.type = "TRANSFORMS"
        target = variable.targets[0]
        target.id = armature
        target.bone_target = _LIMBAL_BONE_NAME
        target.transform_type = transform_type
        target.transform_space = "WORLD_SPACE"


def configure_limbal_eye_drivers(
        obj: bpy.types.Object,
        armature: bpy.types.Object,
) -> int:
    """Give this object's RMI eye materials world-space C_Limbal drivers.

    The RMI master graph carries an eye-path group even for non-eye variants,
    so the material's variant-selected Shading Model is the authoritative test
    here.  Materials are deliberately not copied or renamed for this setup.
    """
    if armature is None or armature.type != "ARMATURE":
        return 0
    if armature.pose is None or armature.pose.bones.get(_LIMBAL_BONE_NAME) is None:
        return 0

    configured = 0
    for slot in obj.material_slots:
        material = slot.material
        if material is None or material.get("Shading Model") != 5:
            continue
        eye_nodes = _eye_path_nodes(material)
        if not eye_nodes:
            continue
        for eye_node in eye_nodes:
            _set_limbal_driver(eye_node.inputs["Light Position"], armature)
            configured += 1
    return configured


def _source_files() -> tuple[dict[str, Path], Path, Path]:
    """Locate the three RMI builders and their shared variant data.

    An older external research checkout can still contain only the historical
    ubershader.  In that case it remains a safe development fallback for all
    profiles; installed add-ons always ship the dedicated eye and hair files.
    """
    addon_directory = Path(__file__).resolve().parent
    packaged = addon_directory / "rmi_sources"
    development = addon_directory.parents[4] / "material related" / "blender"
    candidates = (
        (packaged, packaged / "ff7r_rmi_surface_variant.py",
         packaged / "renderer_ground_truth.json"),
        (development, development / "ff7r_rmi_surface_variant.py",
         development.parent / "scripts" / "renderer_ground_truth.json"),
    )
    for directory, variant, ground_truth in candidates:
        surface = directory / "ff7r_rmi_surface.py"
        if surface.is_file() and variant.is_file() and ground_truth.is_file():
            return {
                "surface": surface,
                "eye": (directory / "ff7r_rmi_surface_eye.py"
                        if (directory / "ff7r_rmi_surface_eye.py").is_file() else surface),
                "hair": (directory / "ff7r_rmi_surface_hair.py"
                         if (directory / "ff7r_rmi_surface_hair.py").is_file() else surface),
            }, variant, ground_truth
    raise FileNotFoundError(
        "RMI_Surface runtime sources are missing. Expected packaged sources in "
        f"'{packaged}' or the sibling material-research checkout. See README_ADDON.md."
    )


def _load_module(name: str, path: Path) -> Any:
    # Keep file-loaded builders in the add-on namespace so their language
    # imports also work for extension installs with a different package name.
    spec = importlib.util.spec_from_file_location(
        f"{__package__}.rmi_sources.{name}", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load RMI_Surface source module '{path}'.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _module_set() -> tuple[dict[str, Any], Any, dict[str, list[str]]]:
    global _MODULES
    if _MODULES is not None:
        return _MODULES
    master_paths, variant_path, ground_truth_path = _source_files()
    masters: dict[str, Any] = {}
    for profile, path in master_paths.items():
        existing = next((module for other_profile, module in masters.items()
                         if master_paths[other_profile] == path), None)
        masters[profile] = (existing if existing is not None else _load_module(
            "talisman_rmi_" + profile, path))
    variant = _load_module("talisman_rmi_variant", variant_path)
    with ground_truth_path.open(encoding="utf-8") as stream:
        ground_truth = json.load(stream)
    _MODULES = masters, variant, ground_truth
    return _MODULES


def _modules() -> tuple[Any, Any, dict[str, list[str]]]:
    """Return the ordinary surface builder for legacy callers and variant data."""
    masters, variant, ground_truth = _module_set()
    return masters["surface"], variant, ground_truth


def _master_for_switches(switches: set[str] | list[str] | tuple[str, ...]) -> Any:
    """Choose the mutually exclusive Eye_/Hair_ or ordinary source profile."""
    switch_set = set(switches)
    if "Eye_" in switch_set and "Hair_" in switch_set:
        raise ValueError("An RMI_Surface variant cannot select both Eye_ and Hair_.")
    masters, _variant, _ground_truth = _module_set()
    if "Eye_" in switch_set:
        master = masters["eye"]
    elif "Hair_" in switch_set:
        master = masters["hair"]
    else:
        master = masters["surface"]
    unsupported = (switch_set - set(getattr(master, "ENGINE_ONLY_SWITCHES", ()))
                   - set(master.KNOWN_SWITCHES))
    if unsupported:
        raise RuntimeError(
            "RMI %s profile lacks switch(es): %s"
            % (getattr(master, "PROFILE_NAME", "surface"),
               ", ".join(sorted(unsupported))))
    return master


def _properties(material_data: dict[str, Any]) -> dict[str, Any]:
    """Turn the gargoyle's converted FPropertyTag sequence into a name map."""
    result: dict[str, Any] = {}
    for property_data in material_data.get("properties") or []:
        if not isinstance(property_data, dict):
            continue
        name = property_data.get("name")
        if name:
            result[str(name)] = _unwrap_struct(property_data.get("value"))
    return result


def _unwrap_struct(value: Any) -> Any:
    """Remove CUE4Parse's synthetic StructType layer from cooked array items."""
    while isinstance(value, dict) and set(value) == {"StructType"}:
        value = value["StructType"]
    return value


def _first(mapping: Any, *keys: str) -> Any:
    mapping = _unwrap_struct(mapping)
    if not isinstance(mapping, dict):
        return None
    folded = {str(key).casefold(): value for key, value in mapping.items()}
    for key in keys:
        value = folded.get(key.casefold())
        if value is not None:
            return value
    return None


def _parameter_name(entry: Any) -> str:
    entry = _unwrap_struct(entry)
    info = _first(entry, "ParameterInfo", "Parameter")
    info = _unwrap_struct(info)
    name = _first(info, "Name") if isinstance(info, dict) else None
    return str(name or "")


def _object_path(value: Any) -> str:
    value = _unwrap_struct(value)
    if not isinstance(value, dict):
        return ""
    return str(_first(value, "ObjectPath", "Path") or "")


def _colour(value: Any) -> tuple[float, float, float, float] | None:
    """Read CUE4Parse's FLinearColor/FColor forms without guessing strings."""
    value = _unwrap_struct(value)
    if isinstance(value, (list, tuple)) and 3 <= len(value) <= 4:
        channels = list(value) + [1.0]
    elif isinstance(value, dict):
        channels = [_first(value, "R", "X"), _first(value, "G", "Y"),
                    _first(value, "B", "Z"), _first(value, "A", "W")]
        if any(channel is None for channel in channels[:3]):
            nested = _first(value, "Color", "Value")
            if nested is not value:
                return _colour(nested)
        if channels[3] is None:
            channels[3] = 1.0
    else:
        return None
    try:
        result = tuple(float(channel) for channel in channels[:4])
    except (TypeError, ValueError):
        return None
    # FColor has integer bytes; FLinearColor can contain HDR floats above 1.
    if all(isinstance(channel, int) for channel in channels[:4]) and max(result) > 1.0:
        result = tuple(channel / 255.0 for channel in result)
    return result


def _srgb_to_linear(channel: int) -> float:
    """Decode one 8-bit sRGB component for a Blender shader colour socket."""
    value = channel / 255.0
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def _renderer_constant_texture(texture_path: str) -> tuple[float, float, float, float] | None:
    """Convert UE's named renderer constant textures (e.g. FFFFFFFF_sRGB,
    8080FFFF_BC5, FFFFFFFF_BC4, FFFFFFFF_HDR) to a plain RGBA colour.

    These are baked colour constants, not image assets that need exporting --
    the 8 hex digits are the four RGBA bytes of a solid-colour texture the
    renderer substitutes at that format. The gargoyle cannot create a DDS for
    their uncompressed payload. Store them on the texture Mix's B socket,
    or on an RGB node if the user enables image-node replacement.

    Only the ``_sRGB`` suffix is gamma-encoded. ``_BC4`` (single-channel masks)
    and ``_BC5`` (tangent-space normal maps) are UE UNORM formats that are
    never sRGB, and ``_HDR`` constants are already linear -- all three decode
    with a straight /255 normalize.
    """
    match = _RENDERER_CONSTANT_TEXTURE.search(texture_path.replace("\\", "/"))
    if match is None:
        return None
    encoded = bytes.fromhex(match.group(1))
    if match.group(2).casefold() == "srgb":
        return (*(_srgb_to_linear(channel) for channel in encoded[:3]), encoded[3] / 255.0)
    return tuple(channel / 255.0 for channel in encoded[:4])


def _normalized(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.casefold())


def _role_values(props: dict[str, Any]) -> tuple[dict[str, str], dict[str, tuple[float, float, float, float]], dict[str, float]]:
    textures: dict[str, str] = {}
    colours: dict[str, tuple[float, float, float, float]] = {}
    scalars: dict[str, float] = {}
    for entry in props.get("TextureParameterValues") or []:
        entry = _unwrap_struct(entry)
        name = _parameter_name(entry)
        value = _unwrap_struct(_first(entry, "ParameterValue", "Value"))
        path = _object_path(value)
        if name and path:
            textures[_normalized(name)] = path
    for entry in props.get("VectorParameterValues") or []:
        entry = _unwrap_struct(entry)
        name = _parameter_name(entry)
        colour = _colour(_unwrap_struct(_first(entry, "ParameterValue", "Value")))
        if name and colour is not None:
            colours[_normalized(name)] = colour
    for entry in props.get("ScalarParameterValues") or []:
        entry = _unwrap_struct(entry)
        name = _parameter_name(entry)
        value = _unwrap_struct(_first(entry, "ParameterValue", "Value"))
        try:
            if name:
                scalars[_normalized(name)] = float(value)
        except (TypeError, ValueError):
            pass
    return textures, colours, scalars


def _role_match(values: dict[str, Any], role: str) -> Any:
    candidates = [_normalized(role)]
    aliases = {"screlanormal": "scleranormal"}
    candidates.append(aliases.get(candidates[0], candidates[0]))
    for candidate in candidates:
        if candidate in values:
            return values[candidate]
    return None


def _role_default_colour(kind: str, default: Any) -> tuple[float, float, float, float]:
    """Expand a ROLES neutral default (master.ROLES' last column) to RGBA.

    'val' roles store a bare scalar (replicated across RGB); 'col'/'nrm'
    roles already store a 4-tuple.
    """
    if kind == "val":
        value = float(default)
        return (value, value, value, 1.0)
    if isinstance(default, tuple) and len(default) == 4:
        return default
    return (0.0, 0.0, 0.0, 1.0)


def _make_colour_node(tree: bpy.types.NodeTree, image_node: bpy.types.Node, colour: tuple[float, float, float, float]) -> None:
    """Replace an RMI image slot with a real RGB constant, preserving consumers."""
    outputs = [(link.to_node, link.to_socket) for link in image_node.outputs["Color"].links]
    name = image_node.name
    parent, location, label = image_node.parent, image_node.location.copy(), image_node.label
    tree.nodes.remove(image_node)
    constant = tree.nodes.new("ShaderNodeRGB")
    constant.name = name
    constant.label = f"{label}  [UE color constant]"
    constant.parent = parent
    constant.location = location
    constant.outputs["Color"].default_value = colour
    for node, socket in outputs:
        tree.links.new(constant.outputs["Color"], socket)


def _set_slot_colour(material, role, kind, colour):
    mix = material.node_tree.nodes.get("USE_" + role)
    if mix is None or mix.bl_idname != "ShaderNodeMix":
        raise RuntimeError(f"RMI texture slot {role!r} has no fallback Mix")
    # Resolve the enabled socket explicitly; Mix has several hidden A/B pairs.
    identifier = "B_Float" if kind == "val" else "B_Color"
    socket = next(socket for socket in mix.inputs if socket.identifier == identifier)
    socket.default_value = colour[0] if kind == "val" else colour


def _set_slot_fallback(material, node, kind, colour, *, replace_image):
    """A muted image has no bypass output: its consumer uses its own default."""
    if replace_image:
        # Scalar UE samplers read red; avoid RGB-to-float luminance conversion
        # changing that value when the optional RGB representation is selected.
        constant = (colour[0], colour[0], colour[0], 1.0) if kind == "val" else colour
        _make_colour_node(material.node_tree, node, constant)
    else:
        # Remember variant muting separately so a successful cache retry can
        # restore an active image without enabling an unused variant slot.
        node["sqex_rmi_fallback_previous_mute"] = node.mute
        node.mute = True


def _bundled_gaze_normal(texture_path: str) -> bpy.types.Image | None:
    """Use the lossless deblocked shared-eye normal for its exact game path."""
    normalized_path = texture_path.replace("\\", "/").split(".", 1)[0].casefold()
    if normalized_path != _COMMON_EYE_PLAYER_NG:
        return None

    global _GAZE_NORMAL_OVERRIDE_IMAGE
    try:
        cached = _GAZE_NORMAL_OVERRIDE_IMAGE
        if cached is not None and cached.name in bpy.data.images:
            return cached
    except ReferenceError:
        _GAZE_NORMAL_OVERRIDE_IMAGE = None

    asset_path = (
        Path(__file__).resolve().parents[3]
        / "assets"
        / "Common_Eye_Player_NG_filtered.png"
    )
    try:
        image = bpy.data.images.load(str(asset_path), check_existing=True)
        image.name = "Common_Eye_Player_NG [FF7R deblocked]"
        image.colorspace_settings.name = "Non-Color"
        image["ue_virtual_path"] = texture_path
        image["ff7r_override_source"] = "Common_Eye_Player_NG BC5"
        image["ff7r_override_filter"] = "lossless 16-bit, 5x5 binomial"
        image.pack()
        _GAZE_NORMAL_OVERRIDE_IMAGE = image
        return image
    except Exception as exc:
        print(f"  Warning: bundled GazeNormal override could not be loaded: {exc}")
        return None


def _variant_name(props: dict[str, Any]) -> str:
    parent = _first(props, "Parent")
    path = _object_path(parent)
    name = path.rsplit(".", 1)[-1].rsplit("/", 1)[-1]
    return name if name.startswith("RMI_Surface_") else ""


def refresh_hologram_material(material: bpy.types.Material) -> bool:
    """Upgrade only recognized surface output wiring; preserve artist edits."""
    if material.get("_RMI_Profile", "surface") != "surface":
        return False
    surface, _variant, _truth = _modules()
    refresh = getattr(surface, "refresh_hologram_alpha", None)
    return bool(refresh and refresh(material))


def _refresh_wide_occlusion_uv(material: bpy.types.Material) -> None:
    """Keep saved/import-cached WideOcclusion samplers on Coordinate1."""
    tree = material.node_tree
    if tree is None:
        return
    texture = tree.nodes.get("TEX_WideOcclusion")
    uv = tree.nodes.get("UV1")
    if (texture is None or texture.bl_idname != "ShaderNodeTexImage"
            or uv is None or uv.bl_idname != "ShaderNodeUVMap"):
        return  # Constant slots do not sample a UV map.
    if uv.uv_map != "Coordinate1":
        uv.uv_map = "Coordinate1"
    vector = texture.inputs["Vector"]
    if not any(link.from_node == uv for link in vector.links):
        tree.links.new(uv.outputs["UV"], vector)
    if not texture.mute and uv.mute:
        uv.mute = False


def _ensure_master(master: Any, *, import_cache=None) -> bpy.types.Material:
    material = bpy.data.materials.get(master.MAT_NAME)
    if material is not None:
        # Upgrade intact saved templates in place before structural validation,
        # preserving shared group interfaces and socket identities.
        refresh_hologram_material(material)
        _refresh_wide_occlusion_uv(material)
    profile_name = getattr(master, "PROFILE_NAME", "surface")
    profile_revision = getattr(master, "PROFILE_REVISION", 0)
    # Package meshes use these names regardless of the active object. Materials
    # are built before the imported mesh is selected (often with an armature
    # active), so the standalone builders' context-based discovery is unsafe.
    uv_names = tuple(f"Coordinate{index}" for index in range(4))
    uv_count = {"surface": 4, "hair": 3, "eye": 2}[profile_name]
    valid = (material is not None and material.node_tree is not None
             and material.node_tree.nodes.get("TEX_Color") is not None
             and material.get("_RMI_Profile") == profile_name
             and material.get("_RMI_Profile_Revision") == profile_revision
             # Invalidate incompatible templates. Existing material copies keep their
             # graphs and shared group interfaces.
             and all(material.node_tree.nodes.get(name) is not None
                     for name in getattr(master, "REQUIRED_MASTER_NODES", ()))
             and all(any(
                 link.from_node.name == source and link.from_socket.name == output
                 and link.to_node.name == target and link.to_socket.name == socket
                 for link in material.node_tree.links)
                 for source, output, target, socket in
                 getattr(master, "REQUIRED_MASTER_LINKS", ()))
             and all(
                 (node := material.node_tree.nodes.get(f"UV{index}")) is not None
                 and node.uv_map == uv_names[index]
                 for index in range(uv_count)))
    if valid and import_cache is not None:
        stamp = ("rmi-master", material.as_pointer(), profile_name, profile_revision)
        if import_cache.completed.get(stamp) == material:
            return material
    if not valid:
        material = master.build(uv_names=uv_names)
    else:
        # Keep saved masters live after a switch-key rename: this updates both
        # their visible ID properties and the Value-node driver targets.
        master._ensure_props(material)
    # The master is a template, never assigned to a mesh. Keep it across saves
    # so importing another package after reopening does not recreate it.
    material.use_fake_user = True
    if import_cache is None or not import_cache.completed.get("rmi-migrations"):
        for candidate in bpy.data.materials:
            _migrate_switch_status_properties(candidate)
            if candidate == material or "sqex_rmi_variant" in candidate:
                _migrate_camera_only_emission(candidate)
                refresh_hologram_material(candidate)
                _refresh_wide_occlusion_uv(candidate)
        if import_cache is not None:
            import_cache.completed["rmi-migrations"] = True
    else:
        _migrate_switch_status_properties(material)
        _migrate_camera_only_emission(material)
        refresh_hologram_material(material)
        _refresh_wide_occlusion_uv(material)
    if import_cache is not None:
        stamp = ("rmi-master", material.as_pointer(), profile_name, profile_revision)
        import_cache.completed[stamp] = material
    return material


def _import_all_material_switches() -> bool:
    addon = bpy.context.preferences.addons.get(addon_package_name(__package__))
    return bool(addon and getattr(addon.preferences, "rebirth_import_all_material_switches", False))


def _replace_empty_image_textures() -> bool:
    addon = bpy.context.preferences.addons.get(addon_package_name(__package__))
    return bool(addon and getattr(addon.preferences, "rebirth_replace_empty_image_textures", False))


def build_material(
        material_name: str,
        material_path: str,
        material_data: dict[str, Any],
        image_loader: Callable[[str], bpy.types.Image | None],
) -> bpy.types.Material | None:
    """Populate an RMI material using the preferred switch-retention policy.

    Returns ``None`` for non-RMI material instances, which lets the existing
    placeholder material behavior remain intact for unrelated game shaders.
    """
    props = _properties(material_data)
    variant_name = _variant_name(props)
    if not variant_name:
        return None
    master, variant_helper, ground_truth = _modules()
    switches = ground_truth.get(variant_name)
    if switches is None:
        print(f"  RMI material '{material_name}' skipped: unknown variant '{variant_name}'.")
        return None
    master = _master_for_switches(switches)
    keep_all_switches = _import_all_material_switches()
    replace_empty_images = _replace_empty_image_textures()
    texture_namespace = getattr(image_loader, "texture_namespace", "")
    cache_key = (f"{material_path.casefold()}::{variant_name}::{texture_namespace}"
                 f"::all-switches={int(keep_all_switches)}"
                 f"::replace-empty-images={int(replace_empty_images)}")
    cached = _MATERIAL_CACHE.get(cache_key)
    if cached is not None:
        try:
            still_valid = cached.name in bpy.data.materials
        except ReferenceError:
            # _MATERIAL_CACHE is module-level and outlives File > New (only an
            # addon reload/Blender restart clears it), so a cached entry can be
            # a Material from a file that no longer exists. Reading .name on
            # its freed RNA struct is itself what raises here.
            still_valid = False
        if still_valid:
            # Cached graphs can predate this output branch. Do not reapply
            # variants: live switch/texture/tint edits must survive reuse.
            refresh_hologram_material(cached)
            _refresh_wide_occlusion_uv(cached)
            return refresh_material_textures(cached, image_loader)
        del _MATERIAL_CACHE[cache_key]

    master_material = _ensure_master(master, import_cache=get_import_cache(image_loader))
    material = master_material.copy()
    material.use_fake_user = False
    material.name = material_name
    material["ue_virtual_path"] = material_path
    material["ue_texture_namespace"] = texture_namespace
    variant_helper.apply_variant(material, master, variant_name, set(switches),
                                 keep_all_switches=keep_all_switches)

    texture_values, colour_values, scalar_values = _role_values(props)
    assigned_images = assigned_colours = 0
    for _frame, role, kind, color_space, default in master.ROLES:
        node = material.node_tree.nodes.get("TEX_" + role)
        if node is None:
            continue
        texture_path = _role_match(texture_values, role)
        colour = _role_match(colour_values, role)
        texture_constant = _renderer_constant_texture(texture_path) if texture_path else None
        fallback = texture_constant if texture_constant is not None else colour
        if fallback is None:
            fallback = _role_default_colour(kind, default)
        _set_slot_colour(material, role, kind, fallback)
        if texture_path and texture_constant is None:
            node["ue_texture_path"] = texture_path
            node["sqex_rmi_color_space"] = color_space
            image = _bundled_gaze_normal(texture_path) if role == "GazeNormal" else None
            if image is None:
                image = image_loader(texture_path)
            if image is not None and hasattr(node, "image"):
                _set_image_color_space(image, color_space)
                node.image = image
                assigned_images += 1
                continue
        if node.bl_idname == "ShaderNodeTexImage":
            # Prefer the UE constant/colour. Some cooked parent defaults lose
            # their parameter names, so only those use the researched ROLES
            # neutral. The slot switch still selects neutral A versus this B.
            _set_slot_fallback(material, node, kind, fallback,
                               replace_image=replace_empty_images)
            assigned_colours += 1

    # Preserve named scalar overrides in the port's material custom properties.
    for name, _default, _min, _max, _description in master.FLOAT_PROPS:
        value = scalar_values.get(_normalized(name))
        if value is not None and name in material:
            material[name] = value
    external_emissive_context = _external_emissive_context(props)
    material["sqex_rmi_variant"] = variant_name
    material[_EXTERNAL_EMISSIVE_STATUS_PROP] = _EXTERNAL_EMISSIVE_SWITCH in switches
    material[_EMISSIVE_STATUS_PROP] = _EMISSIVE_SWITCH in switches
    _migrate_switch_status_properties(material)
    if external_emissive_context is not None:
        material["ff7r_external_emissive_context"] = external_emissive_context
    material["ff7r_rmi_texture_images"] = assigned_images
    material["ff7r_rmi_color_constants"] = assigned_colours
    _MATERIAL_CACHE[cache_key] = material
    remember_datablock("materials", material, image_loader)
    print(f"  RMI '{material.name}': {variant_name}; {assigned_images} image(s), {assigned_colours} color constant(s).")
    return material
