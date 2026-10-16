"""Shared Kingdom Hearts legacy-Matinee cutscene importer.

KH 0.2 and KH3 store authored cinematics as ``*_camera_ms*.umap`` packages.
Unlike Rebirth's Sequencer-based EndCinemaSequence assets, their timelines are
ordinary UE4 Matinee objects: MatineeActor -> InterpData -> InterpGroup ->
InterpTrack.  This module deliberately keeps that data model separate from the
Rebirth importer while sharing the package session, browser, and animation
decoder infrastructure.
"""

from __future__ import annotations

from ....language import tooltips

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import bpy

from ....core.blender.reporting import SQEX_LoggedOperator, report
from ....formats.ue_map import map_import
from ....formats.ue_map.map_import import location_from_relative, rotation_from_relative
from ... import package_browser
from .. import materials as kh_materials
from ....formats import unreal_package as shared_packages
from ...rebirth.importers import animations as shared_animations
from . import static_mesh as kh_mesh


_CAMERA_MAP_PATTERN = re.compile(r"_camera_ms[0-9a-z_]*\.umap$", re.IGNORECASE)


@dataclass
class _MatineeGroup:
    """One Matinee group plus the level actor(s) it explicitly controls."""

    group: dict
    tracks: list[dict]
    actor_names: list[str]


@dataclass
class _MatineeTimeline:
    """Objects and authored group data needed for the post-map import pass."""

    created: int
    end_frame: float
    groups: list[_MatineeGroup]
    placeholders_by_actor: dict[str, list[bpy.types.Object]]


def _reference_index(value: Any) -> int | None:
    """Return a gargoyle-stable export index from a serialized object reference."""
    if not isinstance(value, dict):
        return None
    index = value.get("ExportIndex")
    if isinstance(index, int):
        return index
    path = value.get("ObjectPath")
    if isinstance(path, str) and path.startswith("Package."):
        try:
            return int(path.rsplit(".", 1)[1])
        except ValueError:
            return None
    return None


def _reference_asset_path(value: Any, profile) -> str | None:
    """Translate a Matinee external ObjectPath into a mounted package path."""
    if not isinstance(value, dict):
        return None
    object_path = value.get("ObjectPath")
    if not isinstance(object_path, str):
        return None
    return shared_packages._game_asset_path_to_virtual_uasset(object_path, profile=profile)


def _reference_object_name(value: Any) -> str | None:
    """Return the terminal Unreal object name from a gargoyle reference."""
    if not isinstance(value, dict):
        return None
    object_name = value.get("ObjectName")
    if isinstance(object_name, str) and object_name:
        if "'" in object_name:
            parts = object_name.split("'")
            if len(parts) >= 2 and parts[-2]:
                return parts[-2]
        return object_name.rsplit(".", 1)[-1].rstrip("'") or None
    object_path = value.get("ObjectPath")
    if isinstance(object_path, str) and object_path:
        return object_path.rsplit(".", 1)[-1].rstrip("'") or None
    return None


def _group_actor_info_by_name(matinee_props: dict) -> dict[str, list[dict]]:
    """Index Matinee GroupActorInfos by their local InterpGroup object name."""
    indexed: dict[str, list[dict]] = {}
    for info in matinee_props.get("GroupActorInfos") or []:
        if not isinstance(info, dict):
            continue
        name = _reference_object_name(info)
        if name:
            indexed.setdefault(name.casefold(), []).append(info)
    return indexed


def _actors_from_group_info(info: dict | None) -> list[str]:
    if not isinstance(info, dict):
        return []
    names: list[str] = []
    for actor_ref in info.get("Actors") or []:
        name = _reference_object_name(actor_ref)
        if name and name.casefold() not in {item.casefold() for item in names}:
            names.append(name)
    return names


def _collection(scene: bpy.types.Scene, source_path: str) -> bpy.types.Collection:
    name = Path(source_path).stem + "_Cutscene"
    collection = bpy.data.collections.get(name)
    if collection is None:
        collection = bpy.data.collections.new(name)
    if scene.collection.children.get(collection.name) is None:
        scene.collection.children.link(collection)
    return collection


def _new_empty(collection: bpy.types.Collection, name: str) -> bpy.types.Object:
    obj = bpy.data.objects.new(name, None)
    obj.empty_display_type = "SINGLE_ARROW"
    obj.empty_display_size = 0.4
    collection.objects.link(obj)
    return obj


def _new_camera(collection: bpy.types.Collection, name: str) -> bpy.types.Object:
    camera_data = bpy.data.cameras.new(name)
    obj = bpy.data.objects.new(name, camera_data)
    collection.objects.link(obj)
    return obj


def _frame(scene: bpy.types.Scene, time_seconds: Any, start_frame: float) -> float:
    try:
        return start_frame + float(time_seconds) * scene.render.fps / scene.render.fps_base
    except (TypeError, ValueError, ZeroDivisionError):
        return start_frame


def _point_vector(point: dict, key: str) -> dict:
    value = point.get(key) if isinstance(point, dict) else None
    return value if isinstance(value, dict) else {}


def _key_object_motion(
    scene: bpy.types.Scene,
    obj: bpy.types.Object,
    track: dict,
    start_frame: float,
    scale_factor: float,
) -> float:
    """Import Matinee's position and Euler curves into a Blender object."""
    props = track.get("Properties") or {}
    pos_points = ((props.get("PosTrack") or {}).get("Points") or [])
    rot_points = ((props.get("EulerTrack") or {}).get("Points") or [])
    end_frame = start_frame
    for point in pos_points:
        if not isinstance(point, dict):
            continue
        frame = _frame(scene, point.get("InVal"), start_frame)
        obj.location = location_from_relative(_point_vector(point, "OutVal"), scale_factor)
        obj.keyframe_insert(data_path="location", frame=frame)
        end_frame = max(end_frame, frame)
    for point in rot_points:
        if not isinstance(point, dict):
            continue
        frame = _frame(scene, point.get("InVal"), start_frame)
        # Matinee stores FRotator channels as X=Pitch, Y=Yaw, Z=Roll.
        value = _point_vector(point, "OutVal")
        obj.rotation_mode = "XYZ"
        obj.rotation_euler = rotation_from_relative({
            "Pitch": value.get("X", 0.0),
            "Yaw": value.get("Y", 0.0),
            "Roll": value.get("Z", 0.0),
        })
        obj.keyframe_insert(data_path="rotation_euler", frame=frame)
        end_frame = max(end_frame, frame)
    return end_frame


def _key_camera_fov(
    scene: bpy.types.Scene,
    camera: bpy.types.Object,
    track: dict,
    start_frame: float,
) -> float:
    props = track.get("Properties") or {}
    if not str(props.get("PropertyName") or "").endswith("FieldOfView"):
        return start_frame
    points = ((props.get("FloatTrack") or {}).get("Points") or [])
    end_frame = start_frame
    for point in points:
        if not isinstance(point, dict):
            continue
        try:
            angle = math.radians(float(point.get("OutVal")))
        except (TypeError, ValueError):
            continue
        frame = _frame(scene, point.get("InVal"), start_frame)
        # Camera.angle is derived and therefore not keyframeable.  Matinee's
        # FieldOfView is horizontal, which maps directly to Blender's lens
        # through the camera sensor width.
        camera.data.lens = camera.data.sensor_width / (2.0 * math.tan(angle / 2.0))
        camera.data.keyframe_insert(data_path="lens", frame=frame)
        end_frame = max(end_frame, frame)
    return end_frame


def _key_visibility(
    scene: bpy.types.Scene,
    obj: bpy.types.Object,
    track: dict,
    start_frame: float,
) -> float:
    """Translate Tres visibility events to Blender's render-visibility keys."""
    keys = (track.get("Properties") or {}).get("VisibilityTrack") or []
    end_frame = start_frame
    for key in keys:
        if not isinstance(key, dict):
            continue
        action = str(key.get("Action") or "").casefold()
        if action not in {"evta_show", "evta_hide"}:
            continue
        frame = _frame(scene, key.get("Time"), start_frame)
        obj.hide_render = action == "evta_hide"
        obj.keyframe_insert(data_path="hide_render", frame=frame)
        end_frame = max(end_frame, frame)
    return end_frame


def _find_camera_for_group(
    camera_exports: list[dict],
    group_name: str,
    matinee_name: str,
    used_camera_indices: set[int],
) -> dict | None:
    suffix = "_" + group_name.casefold()
    candidates = [
        item for item in camera_exports
        if item.get("Index") not in used_camera_indices
        and str(item.get("Name") or "").casefold().endswith(suffix)
    ]
    if not candidates and group_name.casefold().startswith("cut"):
        digits = re.search(r"(\d+)$", group_name)
        if digits is not None:
            expected = int(digits.group(1))
            candidates = [
                item for item in camera_exports
                if item.get("Index") not in used_camera_indices
                and (match := re.search(r"(\d+)$", str(item.get("Name") or ""))) is not None
                and int(match.group(1)) == expected
            ]
    if not candidates:
        return None
    # Group names such as ``cut01`` repeat across the map.  Their owning
    # Matinee actor carries the identifying mission/prop token, for example
    # ``ms030_GEAR_A`` -> ``ms030_10_GearA_cut01``. Prefer that relationship
    # while retaining a deterministic fallback for maps with opaque names.
    owner_token = re.sub(r"[^a-z0-9]", "", matinee_name.casefold())
    return max(
        candidates,
        key=lambda item: (
            owner_token in re.sub(r"[^a-z0-9]", "", str(item.get("Name") or "").casefold()),
            -int(item.get("Index") or 0),
        ),
    )


def _find_matching_armature(character_id: str) -> bpy.types.Object | None:
    token = character_id.casefold()
    if not token:
        return None
    for obj in bpy.data.objects:
        if obj.type != "ARMATURE":
            continue
        sources = (
            obj.name,
            str(obj.get("sqex_skeletal_mesh_asset_path") or ""),
            str(obj.get(shared_packages.SKELETON_ASSET_PATH_PROPERTY) or ""),
        )
        if any(token in source.casefold() for source in sources):
            return obj
    return None


def _armature_from_object(obj: bpy.types.Object | None) -> bpy.types.Object | None:
    """Return an actor root's armature without depending on helper names."""
    if obj is None:
        return None
    if obj.type == "ARMATURE":
        return obj
    for candidate in obj.children_recursive:
        if candidate.type == "ARMATURE":
            return candidate
    return None


def _import_existing_rig_animations(
    scene: bpy.types.Scene,
    session: shared_packages.PackageAssetSession,
    profile,
    group: dict,
    tracks: list[dict],
    *,
    start_frame: float,
    armature: bpy.types.Object | None = None,
) -> int:
    """Create actions for full-body Matinee keys when its character rig exists.

    A cutscene map references event-pawn blueprints rather than a conventional
    SkeletalMesh asset.  Importing those blueprints recursively is a separate
    concern, so this first pass applies clips to an already imported matching
    Kingdom Hearts armature and leaves a clearly named Empty otherwise.
    """
    character_id = str((group.get("Properties") or {}).get("m_CharacterMesh") or "")
    armature = armature or _find_matching_armature(character_id)
    if armature is None:
        return 0
    imported = 0
    seen: set[tuple[str, float]] = set()
    for track in tracks:
        if track.get("Type") != "TresInterpTrackFullBodyAnimation":
            continue
        for key in (track.get("Properties") or {}).get("Keys") or []:
            if not isinstance(key, dict):
                continue
            virtual_path = _reference_asset_path(key.get("AnimAsset"), profile)
            if not virtual_path:
                continue
            frame = _frame(scene, key.get("Time"), start_frame)
            dedupe = (virtual_path.casefold(), frame)
            if dedupe in seen:
                continue
            seen.add(dedupe)
            try:
                asset = session.animation_asset(virtual_path, report_errors=False)
                shared_animations.import_animation_asset(
                    armature, virtual_path, asset,
                    start_frame=frame,
                    replace_current_action=False,
                    use_fake_user=True,
                    scene=scene,
                )
                imported += 1
            except Exception as exc:
                print(f"[KH Matinee] Animation skipped {virtual_path}: {exc}")
    return imported


def _import_timeline_animations(
    scene: bpy.types.Scene,
    session: shared_packages.PackageAssetSession,
    profile,
    timeline: _MatineeTimeline,
    actor_roots: dict[str, bpy.types.Object],
    *,
    start_frame: float,
) -> int:
    """Load full-body clips onto the exact event-pawn rig when one is bound.

    Matinee tracks can animate a generic ``GEAR_A`` group without a
    ``m_CharacterMesh`` identifier.  GroupActorInfos is authoritative in that
    case, so prefer its imported level actor before falling back to the
    character-id lookup used for manually imported player rigs.
    """
    imported = 0
    for group_data in timeline.groups:
        armatures: list[bpy.types.Object] = []
        for actor_name in group_data.actor_names:
            armature = _armature_from_object(actor_roots.get(actor_name.casefold()))
            if armature is not None and armature not in armatures:
                armatures.append(armature)
        if armatures:
            for armature in armatures:
                imported += _import_existing_rig_animations(
                    scene, session, profile, group_data.group, group_data.tracks,
                    start_frame=start_frame, armature=armature,
                )
        else:
            imported += _import_existing_rig_animations(
                scene, session, profile, group_data.group, group_data.tracks,
                start_frame=start_frame,
            )
    return imported


def _import_event_pawn_components(
    context,
    collection: bpy.types.Collection,
    source_path: str,
    actor_data: list[dict],
    timeline: _MatineeTimeline,
    session: shared_packages.PackageAssetSession,
    *,
    scale_factor: float,
) -> tuple[int, int, dict[str, bpy.types.Object]]:
    """Materialize a cutscene map's event-pawn skeletal components.

    The shared UMAP placement path already understands inherited component
    properties, skeleton construction, and skin binding.  This thin adapter
    filters it to skeletal event-pawn components, places them under the
    cutscene collection, then parents each explicit GroupActorInfos binding to
    its corresponding Matinee control Empty.
    """
    skeletal_entries = [
        entry for entry in actor_data
        if isinstance(entry, dict)
        and entry.get("Type") in {
            "EndSkeletalMeshComponent",
            "SkeletalMeshComponent",
            "TresSkeletalMeshComponent",
            "TresRootComponent",
        }
    ]
    if not skeletal_entries:
        return 0, 0, {}

    before = {obj.as_pointer() for obj in bpy.data.objects}
    resolver = shared_packages.PackageSkeletalMeshResolver(
        context, session, scale_factor, material_builder=kh_materials.build_material,
    )
    created, _missing = map_import.import_map_entries(
        skeletal_entries,
        source_path,
        exposure_mult=1.0,
        attenuation_radius_mult=1.0,
        location_scale=scale_factor,
        static_mesh_resolver=None,
        skeletal_mesh_resolver=resolver,
        import_models=True,
        import_lights=False,
        import_reflection_probes=False,
        target_collection=collection,
    )

    actor_roots: dict[str, bpy.types.Object] = {}
    for obj in bpy.data.objects:
        if obj.as_pointer() in before:
            continue
        source_name = obj.get("source_name")
        is_tres_root = obj.get("source_type") == "TresRootComponent"
        is_mesh_root = obj.type in {"ARMATURE", "MESH"} and not (
            obj.type == "MESH" and obj.parent is not None
        )
        # The Tres root owns the whole event actor. Armatures (or unskinned
        # meshes) are a fallback for maps that omit such a component.
        if not isinstance(source_name, str) or not (is_tres_root or is_mesh_root):
            continue
        if is_tres_root:
            actor_roots[source_name.casefold()] = obj
        else:
            actor_roots.setdefault(source_name.casefold(), obj)
        obj["sqex_matinee_source"] = source_path
        obj["sqex_matinee_event_pawn"] = source_name

    bound_count = 0
    for actor_key, root in actor_roots.items():
        placeholders = timeline.placeholders_by_actor.get(actor_key) or []
        if not placeholders:
            continue
        placeholder = placeholders[0]
        world_matrix = root.matrix_world.copy()
        root.parent = placeholder
        root.matrix_parent_inverse = placeholder.matrix_world.inverted()
        root.matrix_world = world_matrix
        root["sqex_matinee_bound_actor"] = root.get("source_name", root.name)
        root["sqex_matinee_group"] = placeholder.get("sqex_matinee_group", "")
        bound_count += 1
    return created, bound_count, actor_roots


def _import_matinee_data(
    scene: bpy.types.Scene,
    collection: bpy.types.Collection,
    source_path: str,
    payload: dict,
    *,
    start_frame: float,
    scale_factor: float,
) -> _MatineeTimeline:
    exports = [item for item in payload.get("exports") or [] if isinstance(item, dict)]
    by_index = {item.get("Index"): item for item in exports if isinstance(item.get("Index"), int)}
    camera_exports = [item for item in exports if item.get("Type") == "CameraActor"]
    used_camera_indices: set[int] = set()
    objects_by_group: dict[tuple[int, int], bpy.types.Object] = {}
    groups: list[_MatineeGroup] = []
    placeholders_by_actor: dict[str, list[bpy.types.Object]] = {}
    created = 0
    end_frame = start_frame

    for matinee in (item for item in exports if item.get("Type") == "MatineeActor"):
        matinee_props = matinee.get("Properties") or {}
        data = by_index.get(_reference_index(matinee_props.get("MatineeData")))
        if data is None:
            continue
        matinee_label = str(matinee.get("Name") or "Matinee")
        actor_infos_by_name = _group_actor_info_by_name(matinee_props)
        for group_ref in (data.get("Properties") or {}).get("InterpGroups") or []:
            group_index = _reference_index(group_ref)
            group = by_index.get(group_index)
            if group is None:
                continue
            group_props = group.get("Properties") or {}
            group_name = str(group_props.get("GroupName") or group.get("Name") or "Group")
            group_info_candidates = actor_infos_by_name.get(
                str(group.get("Name") or "").casefold(), []
            )
            group_info = group_info_candidates.pop(0) if group_info_candidates else None
            actor_names = _actors_from_group_info(group_info)
            tracks = [
                by_index[index] for index in (
                    _reference_index(reference)
                    for reference in group_props.get("InterpTracks") or []
                ) if index in by_index
            ]
            camera_export = _find_camera_for_group(
                camera_exports, group_name, matinee_label, used_camera_indices
            )
            if camera_export is not None:
                used_camera_indices.add(camera_export["Index"])
                obj = _new_camera(collection, f"{matinee_label} | {camera_export['Name']}")
                obj["sqex_matinee_kind"] = "camera"
            else:
                character_id = str(group_props.get("m_CharacterMesh") or "")
                label = character_id or group_name
                obj = _new_empty(collection, f"{matinee_label} | {label}")
                obj["sqex_matinee_kind"] = "actor"
                if character_id:
                    obj["sqex_kh_character_id"] = character_id
            obj["sqex_matinee_source"] = source_path
            obj["sqex_matinee_group"] = group_name
            for actor_name in actor_names:
                placeholders_by_actor.setdefault(actor_name.casefold(), []).append(obj)
            if actor_names:
                obj["sqex_matinee_actor"] = actor_names[0]
            objects_by_group[(matinee.get("Index"), group_index)] = obj
            groups.append(_MatineeGroup(group, tracks, actor_names))
            created += 1
            for track in tracks:
                track_type = str(track.get("Type") or "")
                if track_type == "InterpTrackMove":
                    end_frame = max(end_frame, _key_object_motion(
                        scene, obj, track, start_frame, scale_factor
                    ))
                elif track_type == "InterpTrackFloatProp" and obj.type == "CAMERA":
                    end_frame = max(end_frame, _key_camera_fov(scene, obj, track, start_frame))
                elif track_type == "TresInterpTrackVisibility":
                    end_frame = max(end_frame, _key_visibility(scene, obj, track, start_frame))

    # Some KH3 maps use anonymous CameraActor_0 / CameraActor_1 exports whose
    # authored binding lives in a level script rather than the Matinee group.
    # Preserve them as editable cameras even when the association is opaque.
    for camera_export in camera_exports:
        if camera_export.get("Index") in used_camera_indices:
            continue
        obj = _new_camera(collection, f"Camera | {camera_export.get('Name') or 'Camera'}")
        obj["sqex_matinee_kind"] = "unbound_camera"
        obj["sqex_matinee_source"] = source_path
        created += 1

    # Keep a readable fallback for maps whose groups cannot be associated with
    # a MatineeActor (usually disabled ambient/FX data).
    if not objects_by_group:
        raise ValueError("The cutscene map contains no Matinee actor timeline groups.")
    return _MatineeTimeline(created, end_frame, groups, placeholders_by_actor)


def make_matinee_importer(
    *,
    class_name: str,
    bl_idname: str,
    game_label: str,
    definition: kh_mesh.MeshImporterDefinition,
) -> type[SQEX_LoggedOperator]:
    """Create one branded KH0.2/KH3 cutscene operator backed by common code."""
    browser = package_browser.make_state(
        f"{game_label} Cutscene Maps", initial_directory=definition.initial_directory,
        file_icon="SEQUENCE",
    )
    state: dict[str, Any] = {"paths": [], "cache_key": None, "source": ""}

    def refresh(context, *, force=False) -> list[str]:
        paths = kh_mesh._configured_paths(context, definition)
        cache_key = (*kh_mesh._cache_key(paths), "matinee-camera-maps")
        if force or cache_key != state["cache_key"]:
            result = shared_packages._run_gargoyle_asset_request(
                paths.install_root, paths.oodle_dll, paths.usmap_path,
                {"action": "umap_index"}, profile=definition.profile, aes_key=paths.aes_key,
            )
            state["paths"] = sorted(
                (str(path).replace("\\", "/") for path in result.get("umaps") or []
                 if _CAMERA_MAP_PATTERN.search(str(path).replace("\\", "/"))),
                key=shared_packages._natural_path_key,
            )
            state["cache_key"] = cache_key
            state["source"] = "mounted packages"
        return state["paths"]

    def search(_self, _context, edit_text):
        return shared_packages._search_virtual_paths(
            state["paths"], edit_text, sort_key=shared_packages._natural_path_key,
        )

    def invoke(self, context, _event):
        try:
            indexed = refresh(context)
        except Exception as exc:
            report(self, {"ERROR"}, f"{game_label} cutscene index failed: {exc}")
            return {"CANCELLED"}
        if not indexed:
            report(self, {"WARNING"}, f"No {game_label} Matinee cutscene maps were found.")
            return {"CANCELLED"}
        self.start_frame = context.scene.frame_current
        package_browser.activate(context, browser, indexed, dialog_operator=self.bl_idname)
        return context.window_manager.invoke_props_dialog(self, width=1000)

    def draw(self, context):
        layout = self.layout
        package_browser.draw(layout, context, browser)
        layout.separator()
        layout.prop(self, "start_frame")
        layout.prop(self, "scale_factor")
        layout.prop(self, "import_existing_rig_animations")
        layout.label(
            text=f"{len(state['paths']):,} {game_label} camera cutscene maps indexed ({state['source'] or 'memory'})",
            icon="SEQUENCE",
        )
        layout.label(text="Imports Matinee camera/actor transforms and field-of-view curves.", icon="INFO")

    def execute(self, context):
        try:
            paths = kh_mesh._configured_paths(context, definition)
            indexed = refresh(context)
            browser["paths"] = list(indexed)
            selected = package_browser.resolve_paths(context, browser, self.virtual_path)
            if not selected:
                raise ValueError("Highlight or select at least one cutscene map.")
            collection = None
            created = actions = event_pawns = bound_event_pawns = 0
            end_frame = float(self.start_frame)
            with shared_packages.PackageAssetSession(
                paths.install_root, paths.oodle_dll, paths.usmap_path,
                profile=definition.profile, aes_key=paths.aes_key,
            ) as session:
                for virtual_path in selected:
                    collection = _collection(context.scene, virtual_path)
                    payload = session.kh_matinee_asset(virtual_path)
                    timeline = _import_matinee_data(
                        context.scene, collection, virtual_path, payload,
                        start_frame=self.start_frame, scale_factor=self.scale_factor,
                    )
                    actor_payload = session.umap_actors(virtual_path)
                    pawn_count, bound_count, actor_roots = _import_event_pawn_components(
                        context, collection, virtual_path,
                        actor_payload.get("actors") or [], timeline, session,
                        scale_factor=self.scale_factor,
                    )
                    if self.import_existing_rig_animations:
                        actions += _import_timeline_animations(
                            context.scene, session, definition.profile,
                            timeline, actor_roots, start_frame=self.start_frame,
                        )
                    created += timeline.created
                    event_pawns += pawn_count
                    bound_event_pawns += bound_count
                    end_frame = max(end_frame, timeline.end_frame)
            context.scene.frame_end = max(context.scene.frame_end, math.ceil(end_frame))
        except Exception as exc:
            report(self, {"ERROR"}, f"{game_label} cutscene import failed: {exc}")
            return {"CANCELLED"}
        pawn_note = (
            f"; {event_pawns} event-pawn component(s), {bound_event_pawns} bound to Matinee"
            if event_pawns else ""
        )
        action_note = f"; {actions} full-body action(s) created" if actions else ""
        report(self, {"INFO"}, f"Imported {len(selected)} {game_label} Matinee cutscene(s): {created} actor/camera object(s){pawn_note}{action_note}")
        return {"FINISHED"}

    attributes = {
        "bl_idname": bl_idname,
        "bl_label": f"Cutscene from {game_label} Packages",
        "bl_description": tooltips.KINGDOM_HEARTS_MATINEE_IMPORT.format(game_label=game_label),
        "bl_options": {"REGISTER", "UNDO"},
        "__annotations__": {
            "virtual_path": bpy.props.StringProperty(
                name="Cutscene Map", search=search, search_options={"SUGGESTION"},
            ),
            "start_frame": bpy.props.IntProperty(name="Start Frame", default=1),
            "scale_factor": bpy.props.FloatProperty(
                name="Scale", default=0.01, min=0.0001, max=100.0,
                description=tooltips.SHARED_SCALE_FACTOR,
            ),
            "import_existing_rig_animations": bpy.props.BoolProperty(
                name="Load Full-Body Matinee Actions", default=True,
                description=tooltips.KINGDOM_HEARTS_MATINEE_EXISTING_RIG_ANIMATIONS,
            ),
        },
        "invoke": invoke,
        "draw": draw,
        "execute": execute,
    }
    return type(class_name, (SQEX_LoggedOperator,), attributes)

