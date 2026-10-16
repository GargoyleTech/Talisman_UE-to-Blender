"""Shared conventional UE4 mesh importers for Kingdom Hearts games."""

from __future__ import annotations

from ....language import tooltips

import hashlib
import json
import os
import re
import tempfile
from typing import Any

import bpy

from ....core.blender.reporting import SQEX_LoggedOperator, report
from ....core.package_utils import addon_package_name
from ....core.profiles import GamePaths
from ....formats.kdi.drivers import (
    AXIS_ORDER_ITEMS,
    COORDINATE_PROFILE_PACKAGE_SKELETON_ROLL_90,
    COORDINATE_PROFILE_REFERENCE,
)
from ... import package_browser
from .. import materials as kh_materials
from ....formats import unreal_package as shared_packages
from ...rebirth.importers import animations as shared_animations
from ... import conventional_mesh as shared_mesh
from ... import conventional_animation as shared_animation
from ...conventional_mesh import MeshImporterDefinition


_SUPPORTED_SKELETAL_OPTIONS = {
    "import_kdi",
    "preserve_ue_axis_order",
    "import_mesh_referenced_bones_only",
}


# Square Enix's UE4 KineDriver assets for Kingdom Hearts refer to skeleton
# objects numerically (``TargetObject``, ``BaseSpace`` and ``SourceArray``)
# instead of by bone name. Keep the reference-skeleton slot on the actual
# Blender Bone so a later KDI import can resolve those fields without relying
# on names or on Blender's bone ordering.
KDI_OBJECT_INDEX_PROPERTY = "sqex_kdi_object_index"
_KDI_ASSET_PATTERN = re.compile(r"_kdi(?:_[a-z0-9_]+)?\.uasset$", re.IGNORECASE)


def make_definition(*args, **kwargs):
    return shared_mesh.make_definition(
        *args, **kwargs, material_builder=kh_materials.build_material,
        supported_skeletal_options=frozenset(_SUPPORTED_SKELETAL_OPTIONS),
        post_skeleton=_post_skeleton,
    )


def _configured_paths(context, definition):
    return shared_mesh._configured_paths(context, definition)


def refresh_mesh_indices(context, definition, *, force=False):
    return shared_mesh.refresh_mesh_indices(context, definition, force=force)


def refresh_static_mesh_index(context, definition, *, force=False):
    return shared_mesh.refresh_static_mesh_index(context, definition, force=force)


def refresh_skeletal_mesh_index(context, definition, *, force=False):
    return shared_mesh.refresh_skeletal_mesh_index(context, definition, force=force)


make_static_mesh_importer = shared_mesh.make_static_mesh_importer
make_skeletal_mesh_importer = shared_mesh.make_skeletal_mesh_importer


def _post_skeleton(context, operator, definition, session, skeletal_mesh, virtual_path,
                   armature_obj, skeleton_path, source_skeleton, batch):
    reference_bones = list(source_skeleton.get("bones") or [])
    kdi_count = 0
    # Animation clips are selected against this exact
    # Skeleton source. Retain the mesh path too: KH clips
    # omit Skeleton on many AnimSequence exports, so their
    # character-family folder is the reliable narrow index.
    # Some KH SkeletalMesh packages carry the complete
    # reference skeleton inline instead of referencing a
    # standalone USkeleton asset. Use the mesh package as
    # the stable source identity in that case.
    armature_obj[shared_packages.SKELETON_ASSET_PATH_PROPERTY] = (
        skeleton_path or virtual_path
    )
    armature_obj["sqex_skeletal_mesh_asset_path"] = virtual_path
    tagged_bones = _tag_kdi_bone_object_indices(
        armature_obj, reference_bones
    )
    if tagged_bones != len(armature_obj.data.bones):
        print(
            f"{definition.game_name}: tagged {tagged_bones:,} of "
            f"{len(armature_obj.data.bones):,} imported bones with KineDriver object indices."
        )
    if operator.import_kdi:
        kdi_paths = _skeletal_mesh_kdi_paths(
            skeletal_mesh, virtual_path
        )
        # A mesh can nominate more than one KDI pass. Match
        # Rebirth's ordinary skeletal import and apply the
        # first pre-physics driver asset; additional KDI
        # passes remain available through the explicit menu.
        kdi_path = kdi_paths[0] if kdi_paths else ""
        if kdi_path:
            try:
                kdi_asset = session.kdi_asset(kdi_path)
                if kdi_asset.get("Properties"):
                    _import_kh_kdi_asset_drivers(
                        context,
                        armature_obj,
                        kdi_asset,
                        kdi_path,
                    )
                    kdi_count += 1
            except Exception as exc:
                # A mesh import is still useful without its
                # procedural layer, and the explicit KDI
                # importer gives users a focused retry path.
                print(
                    f"{definition.game_name}: associated KineDriver "
                    f"'{kdi_path}' could not be imported: {exc}"
                )

    return kdi_count


def _preferences(context):
    addon_name = addon_package_name(__package__)
    addon = context.preferences.addons.get(addon_name)
    return addon.preferences if addon else None


def _cache_key(paths: GamePaths) -> tuple[str, str, str, str]:
    """Keep encrypted-game listings separate without persisting their AES key."""
    return (
        *shared_packages._package_config_key(
            paths.install_root, paths.oodle_dll, paths.usmap_path
        ),
        hashlib.sha256(paths.aes_key.encode("utf-8")).hexdigest(),
    )


def _tag_kdi_bone_object_indices(
    armature_obj: bpy.types.Object,
    reference_bones: list[dict[str, Any]],
) -> int:
    """Store original Kingdom Hearts reference-skeleton indices on Blender bones.

    ``_restrict_skeleton_to_referenced_bones`` can discard bones before an
    armature is built. Its compacted order must never replace the source index:
    KineDriver's numeric references are always slots in the complete UE
    reference skeleton. Callers therefore pass the unfiltered gargoyle bone list
    captured before any optional restriction.
    """
    tagged = 0
    for object_index, source_bone in enumerate(reference_bones):
        bone_name = str(source_bone.get("name") or "")
        if not bone_name:
            continue
        blender_bone = armature_obj.data.bones.get(bone_name)
        if blender_bone is None:
            continue
        blender_bone[KDI_OBJECT_INDEX_PROPERTY] = object_index
        tagged += 1
    return tagged


def refresh_kdi_index(
    context,
    definition: MeshImporterDefinition,
    *,
    force: bool = False,
) -> list[str]:
    """Build a title-scoped list of legacy and current KineDriver packages."""
    paths = _configured_paths(context, definition)
    cache_key = _cache_key(paths)
    if force or cache_key != definition.kdi_cache_key:
        result = shared_packages._run_gargoyle(
            paths.install_root,
            paths.oodle_dll,
            paths.usmap_path,
            path_filter="_kdi",
            profile=definition.profile,
            aes_key=paths.aes_key,
        )
        definition.virtual_kdis = sorted(
            (
                path.replace("\\", "/")
                for path in result.get("files", [])
                if path.lower().endswith(".uasset")
                and _KDI_ASSET_PATTERN.search(os.path.basename(path)) is not None
                and "/autogencollision/" not in path.replace("\\", "/").casefold()
            ),
            key=shared_packages._natural_path_key,
        )
        definition.kdi_cache_key = cache_key
    return definition.virtual_kdis


def _animation_family_token(armature: bpy.types.Object) -> str:
    """Return the Kingdom Hearts character ID used by its clip directories."""
    source_paths = (
        armature.get("sqex_skeletal_mesh_asset_path"),
        armature.get(shared_packages.SKELETON_ASSET_PATH_PROPERTY),
    )
    for source_path in source_paths:
        if not isinstance(source_path, str):
            continue
        # Character families such as p_ex002, c_bx200, and e_dw401 occur both
        # in the model source and in every matching anm/rt or anm/event clip.
        matches = re.findall(r"(?:^|/)([a-z]+_[a-z0-9]+)(?=/|$)", source_path.casefold())
        if matches:
            return matches[-1]
    return ""


def refresh_animation_index(
    context,
    definition: MeshImporterDefinition,
    armature: bpy.types.Object,
    *,
    force: bool = False,
) -> list[str]:
    """Index a selected Kingdom Hearts rig's conventional AnimSequence clips."""
    skeleton_path = armature.get(shared_packages.SKELETON_ASSET_PATH_PROPERTY)
    if not isinstance(skeleton_path, str) or not skeleton_path.strip():
        raise ValueError(
            "The selected armature has no package Skeleton source. Reimport the "
            "SkeletalMesh with Build Linked Skeleton enabled."
        )
    family_token = _animation_family_token(armature)
    if not family_token:
        raise ValueError(
            "Could not determine the character family from the selected package armature."
        )
    paths = _configured_paths(context, definition)
    definition.virtual_animations = definition.animation_index.refresh(
        paths, definition.profile, skeleton_path,
        search_token=family_token, include_unlinked=True, force=force,
    )
    definition.animation_cache_key = definition.animation_index.cache_key
    return definition.virtual_animations


def make_animation_importer(*, class_name, module_name, bl_idname, definition):
    return shared_animation.make_animation_importer(
        class_name=class_name, module_name=module_name, bl_idname=bl_idname,
        game_name=definition.game_name, profile=definition.profile,
        configured_paths=lambda context: _configured_paths(context, definition),
        compatible_paths=lambda context, armature: refresh_animation_index(context, definition, armature),
        import_animation=shared_animations.import_animation_asset,
        browser=definition.animation_browser,
    )


def _kdi_bones_by_object_index(armature_obj: bpy.types.Object) -> dict[int, str]:
    """Return the KH KineDriver object table recorded during skeletal import."""
    result: dict[int, str] = {}
    duplicates: set[int] = set()
    for bone in armature_obj.data.bones:
        value = bone.get(KDI_OBJECT_INDEX_PROPERTY)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            continue
        if value in result:
            duplicates.add(value)
            continue
        result[value] = bone.name
    if duplicates:
        preview = ", ".join(str(index) for index in sorted(duplicates)[:5])
        raise ValueError(f"Active armature has duplicate KineDriver bone indices: {preview}")
    if not result:
        raise ValueError(
            "Active armature has no Kingdom Hearts KineDriver bone indices. "
            "Re-import its SkeletalMesh with Build Linked Skeleton enabled."
        )
    return result


def _normalise_kh_kdi_bone_references(
    kdi_asset: dict[str, Any], armature_obj: bpy.types.Object
) -> int:
    """Replace KH's serialized skeleton-object slots with conventional bone names.

    KH 0.2 and KH3 use the same legacy KineDriver graph as Remake, but their
    bodies address bones through integer object slots. The common KDI audit and
    driver generator intentionally operate on named bones; translating only the
    bone-reference fields here lets both game families share that well-tested
    graph and driver code. ``SourceQuat`` is deliberately excluded because it
    is an operator index, not a skeleton object index.
    """
    properties = kdi_asset.get("Properties")
    if not isinstance(properties, dict):
        raise ValueError("KineDriver asset has no Properties object.")
    bone_by_index = _kdi_bones_by_object_index(armature_obj)
    unresolved: set[int] = set()
    converted = 0

    def name_for(value: Any) -> str | None:
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        if value < 0:
            return None
        name = bone_by_index.get(value)
        if name is None:
            unresolved.add(value)
        return name

    def unset_name(value: Any) -> bool:
        return not isinstance(value, str) or not value or value == "None"

    for array_name, bodies in properties.items():
        if not array_name.endswith("Body") or not isinstance(bodies, list):
            continue
        for body in bodies:
            if not isinstance(body, dict):
                continue
            # Target, base, aim, and up object fields each identify one bone.
            for index_key, name_key in (
                ("TargetObject", "TargetObjectBoneName"),
                ("BaseSpace", "BaseSpaceBoneName"),
                ("AimObject", "AimObjectBoneName"),
                ("UpObject", "UpObjectBoneName"),
            ):
                if index_key not in body or not unset_name(body.get(name_key)):
                    continue
                bone_name = name_for(body[index_key])
                if bone_name is not None:
                    body[name_key] = bone_name
                    converted += 1

            # SourceArray is KH's integer equivalent of the conventional
            # SourceBoneNameArray. Preserve an authored name array if one ever
            # appears in a later title/update.
            source_indices = body.get("SourceArray")
            if (
                isinstance(source_indices, list)
                and not body.get("SourceBoneNameArray")
            ):
                source_names = []
                for source_index in source_indices:
                    bone_name = name_for(source_index)
                    if bone_name is not None:
                        source_names.append(bone_name)
                if len(source_names) == len(source_indices):
                    body["SourceBoneNameArray"] = source_names
                    converted += len(source_names)

    if unresolved:
        preview = ", ".join(str(index) for index in sorted(unresolved)[:8])
        raise ValueError(
            "KineDriver references bone index/indices not present on the active "
            f"armature: {preview}. Import the matching full Kingdom Hearts skeleton."
        )
    return converted


def _import_kh_kdi_asset_drivers(
    context,
    armature_obj: bpy.types.Object,
    kdi_asset: dict[str, Any],
    virtual_path: str,
    *,
    replace_previous_generated: bool = True,
    translation_axis_order: str | None = None,
    scale_axis_order: str | None = None,
) -> int:
    """Generate KineDriver drivers from one already-fetched KH KDI asset."""
    converted_references = _normalise_kh_kdi_bone_references(kdi_asset, armature_obj)
    for selected in context.selected_objects:
        selected.select_set(False)
    armature_obj.select_set(True)
    context.view_layer.objects.active = armature_obj
    coordinate_profile = armature_obj.get(
        shared_packages.KDI_COORDINATE_PROFILE_PROPERTY,
        COORDINATE_PROFILE_REFERENCE,
    )
    default_axis_order = (
        "YZX"
        if coordinate_profile == COORDINATE_PROFILE_PACKAGE_SKELETON_ROLL_90
        else "XZY"
    )
    with tempfile.TemporaryDirectory(prefix="sqex_kh_kdi_") as temp_dir:
        kdi_path = os.path.join(temp_dir, os.path.basename(virtual_path) + ".json")
        with open(kdi_path, "w", encoding="utf-8") as stream:
            json.dump([kdi_asset], stream, ensure_ascii=False, indent=2)
        result = bpy.ops.import_scene.sqex_kinedriver_json(
            filepath=kdi_path,
            replace_previous_generated=replace_previous_generated,
            translation_axis_order=translation_axis_order or default_axis_order,
            scale_axis_order=scale_axis_order or default_axis_order,
            coordinate_profile=coordinate_profile,
        )
    if result != {"FINISHED"}:
        raise RuntimeError("The KineDriver driver generator could not complete.")
    return converted_references


def _skeletal_mesh_kdi_paths(skeletal_mesh: dict[str, Any], virtual_path: str) -> list[str]:
    """Return an authored KH KDI reference, or its predictable sibling path."""
    paths = []
    for value in skeletal_mesh.get("kdiPaths") or []:
        if not isinstance(value, str):
            continue
        normalized = value.strip().replace("\\", "/").lstrip("/")
        if normalized and normalized not in paths:
            paths.append(normalized)
    if paths:
        return paths
    if virtual_path.casefold().endswith(".uasset"):
        return [virtual_path[:-len(".uasset")] + "_kdi.uasset"]
    return [virtual_path + "_kdi.uasset"]


def make_kdi_importer(
    *,
    class_name: str,
    module_name: str,
    bl_idname: str,
    definition: MeshImporterDefinition,
) -> type[SQEX_LoggedOperator]:
    """Create a title-branded KineDriver package importer for Kingdom Hearts."""

    def search_virtual_kdis(_self, _context, edit_text):
        return shared_packages._search_virtual_paths(
            definition.virtual_kdis,
            edit_text,
            sort_key=shared_packages._natural_path_key,
        )

    def active_armature(context):
        armature = context.active_object
        if armature is None or armature.type != "ARMATURE":
            raise ValueError(
                "Select the matching Kingdom Hearts armature and make it active."
            )
        return armature

    def invoke(self, context, _event):
        try:
            armature = active_armature(context)
            paths = refresh_kdi_index(context, definition)
        except Exception as exc:
            report(self, {"ERROR"}, f"{definition.game_name} KineDriver index failed: {exc}")
            return {"CANCELLED"}
        if not paths:
            report(
                self,
                {"WARNING"},
                f"No {definition.game_name} KineDriver assets were found in the packages.",
            )
            return {"CANCELLED"}
        self._load_last_import_settings(context)
        if armature.get(shared_packages.KDI_COORDINATE_PROFILE_PROPERTY) == (
            COORDINATE_PROFILE_PACKAGE_SKELETON_ROLL_90
        ):
            self.translation_axis_order = "YZX"
            self.scale_axis_order = "YZX"
        else:
            self.translation_axis_order = "XZY"
            self.scale_axis_order = "XZY"
        package_browser.activate(
            context, definition.kdi_browser, paths, dialog_operator=self.bl_idname
        )
        return context.window_manager.invoke_props_dialog(self, width=1000)

    def draw(self, context):
        layout = self.layout
        package_browser.draw(layout, context, definition.kdi_browser)
        layout.prop(self, "replace_previous_generated")
        layout.separator()
        layout.label(text="Experimental target-axis mapping")
        layout.prop(self, "translation_axis_order")
        layout.prop(self, "scale_axis_order")
        layout.label(
            text=f"{len(definition.virtual_kdis):,} {definition.game_name} KineDriver assets indexed",
            icon="PACKAGE",
        )
        layout.label(
            text="Uses sqex_kdi_object_index properties from a Kingdom Hearts skeletal import."
        )

    def execute(self, context):
        try:
            armature = active_armature(context)
            paths = _configured_paths(context, definition)
            indexed_paths = refresh_kdi_index(context, definition)
            definition.kdi_browser["paths"] = list(indexed_paths)
            virtual_paths = package_browser.resolve_paths(
                context, definition.kdi_browser, self.virtual_path
            )
            if len(virtual_paths) != 1:
                raise ValueError("Select exactly one KineDriver asset in the package browser.")
            virtual_path = virtual_paths[0]
            with shared_packages.PackageAssetSession(
                paths.install_root,
                paths.oodle_dll,
                paths.usmap_path,
                profile=definition.profile,
                aes_key=paths.aes_key,
            ) as session:
                kdi_asset = session.kdi_asset(virtual_path)
            converted_references = _import_kh_kdi_asset_drivers(
                context,
                armature,
                kdi_asset,
                virtual_path,
                replace_previous_generated=self.replace_previous_generated,
                translation_axis_order=self.translation_axis_order,
                scale_axis_order=self.scale_axis_order,
            )
        except Exception as exc:
            report(self, {"ERROR"}, f"{definition.game_name} KineDriver import failed: {exc}")
            return {"CANCELLED"}
        self._save_last_import_settings(context)
        report(
            self,
            {"INFO"},
            f"Imported KineDriver drivers from {virtual_path} "
            f"({converted_references:,} numeric bone references resolved).",
        )
        return {"FINISHED"}

    return type(
        class_name,
        (SQEX_LoggedOperator,),
        {
            "__module__": module_name,
            "__annotations__": {
                "virtual_path": bpy.props.StringProperty(
                    name="Package KineDriver",
                    description=(
                        tooltips.KINGDOM_HEARTS_KDI_SEARCH_PATH.format(definition_game_name=definition.game_name)
                    ),
                    search=search_virtual_kdis,
                    search_options={"SORT"},
                ),
                "replace_previous_generated": bpy.props.BoolProperty(
                    name="Replace previous generated KDI layer",
                    default=True,
                ),
                "translation_axis_order": bpy.props.EnumProperty(
                    name="Translation axis mapping",
                    description=tooltips.KDI_TRANSLATION_AXIS_ORDER,
                    items=AXIS_ORDER_ITEMS,
                    default="XZY",
                ),
                "scale_axis_order": bpy.props.EnumProperty(
                    name="Scale axis mapping",
                    description=tooltips.KDI_SCALE_AXIS_ORDER,
                    items=AXIS_ORDER_ITEMS,
                    default="XZY",
                ),
            },
            "bl_idname": bl_idname,
            "bl_label": f"KineDriver from {definition.game_name} Packages",
            "bl_description": (
                tooltips.KINGDOM_HEARTS_KDI_IMPORT.format(definition_game_name=definition.game_name)
            ),
            "bl_options": {"REGISTER", "UNDO"},
            "_persisted_props": (
                "replace_previous_generated",
                "translation_axis_order",
                "scale_axis_order",
            ),
            "invoke": invoke,
            "draw": draw,
            "execute": execute,
        },
    )
