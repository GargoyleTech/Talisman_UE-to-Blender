"""Generic Unreal mesh operators and source hooks for the shared UMAP operator."""

from ...language import strings

import os

import bpy

from ...core.blender.reporting import SQEX_LoggedOperator, report
from ...core.package_utils import addon_package_name
from ...core.blender.skeletons import _bones_from_gargoyle, build_armature_from_bones
from ...core.profiles import GamePaths, normalize_optional_input
from ...games import package_browser
from .. import unreal_package as meshes
from . import maps, materials, session
from ...ui.textures import texture_options
from ...ui.nanite import NANITE_OPTION_NAMES, nanite_properties, nanite_options
from ..unreal_package.importer import (
    MESH_OPTION_NAMES, SKELETAL_OPTION_NAMES, MeshBrowserState, PackageMeshSource,
    PackageMeshOperator, mesh_properties, make_package_mesh_importer,
)
from ..unreal_package.indexing import validate_mesh_index, mesh_index_failure_count, UnreadableMeshPackagesError
from ..ue_map.package_importer import (
    MAP_OPTION_NAMES, map_properties, PackageMapOperator, MapBrowserState,
    PackageMapSource, make_package_map_importer,
)
from ..ue_map.streaming import StreamingMapQueue
from ..ue_map.landscapes import import_options as landscape_options


_VERSION_ITEMS = [("GAME_UE4_27", "UE4_27", "GAME_UE4_27", 0x041B0000)]
_VERSIONS_LOADED = False  # Keep dynamic RNA enum strings alive for Blender.
_PROFILE_ITEMS = []
_INDEX = {}
_BROWSERS = {
    "STATIC": package_browser.make_state("Unreal StaticMesh assets"),
    "SKELETAL": package_browser.make_state("Unreal SkeletalMesh assets", file_icon="ARMATURE_DATA"),
    "UMAP": package_browser.make_state("Unreal UMAP assets", file_icon="FILE"),
}
_CONFIG_PROPS = ("cue4parse_profile", "path_filter", "mesh_kind")


def _version_items(_operator, _context):
    return _VERSION_ITEMS


def _load_versions():
    global _VERSIONS_LOADED
    if not _VERSIONS_LOADED:
        _VERSION_ITEMS[:] = (
            (item["id"], item["label"], item["id"], item["value"])
            for item in session.game_versions()
        )
        _VERSIONS_LOADED = True


def _preferences(context):
    addon_name = addon_package_name(__package__)
    addon = context.preferences.addons.get(addon_name)
    return addon.preferences if addon else None


def _profiles(context):
    """Return generic importer profiles after installing the initial presets."""
    from ...ui.preferences import ensure_generic_unreal_profiles

    preferences = _preferences(context)
    if preferences is None:
        raise RuntimeError("The add-on preferences are unavailable.")
    return preferences, ensure_generic_unreal_profiles(preferences)


def _profile_items(_operator, context):
    global _PROFILE_ITEMS
    try:
        _preferences, profiles = _profiles(context)
    except (AttributeError, RuntimeError):
        # Blender can request dynamic enum items while it is constructing an
        # operator, before an add-on preference instance is available.
        _PROFILE_ITEMS = [("fnaf_security_breach", "Five Nights at Freddy's: Security Breach", "", 0)]
        return _PROFILE_ITEMS
    _PROFILE_ITEMS = [
        (
            profile.profile_id,
            profile.name or "Unnamed CUE4Parse Profile",
            strings.GENERIC_PROFILE_SETTINGS,
            index,
        )
        for index, profile in enumerate(profiles)
    ] or [("", "No CUE4Parse Profiles", strings.GENERIC_ADD_PROFILE, 0)]
    # Keep the original enum numbers so sorting cannot change saved selections.
    _PROFILE_ITEMS.sort(key=lambda item: (item[1].casefold(), item[0]))
    return _PROFILE_ITEMS


def _selected_profile(context, operator):
    _preferences, profiles = _profiles(context)
    for profile in profiles:
        if profile.profile_id == operator.cue4parse_profile:
            return profile
    if profiles:
        return profiles[0]
    raise ValueError("Add a CUE4Parse game profile in the add-on preferences.")


def _configuration_properties():
    return {
        "cue4parse_profile": bpy.props.EnumProperty(
            name="CUE4Parse Profile",
            items=_profile_items,
            default=0,
            description=strings.GENERIC_IMPORT_CUE4PARSE_PROFILE,
        ),
        "path_filter": bpy.props.StringProperty(
            name="Index Path Filter",
            description=strings.GENERIC_IMPORT_PATH_FILTER,
        ),
        "mesh_kind": bpy.props.EnumProperty(name="Asset Type", items=(
            ("STATIC", "StaticMesh", strings.GENERIC_IMPORT_MESH_KIND_STATIC),
            ("SKELETAL", "SkeletalMesh", strings.GENERIC_IMPORT_MESH_KIND_SKELETAL),
            ("UMAP", "UMAP", strings.GENERIC_IMPORT_MESH_KIND_UMAP),
        )),
    }


def _paths(context, operator, *, validate=True):
    preferences, generic_profiles = _profiles(context)
    profile = _selected_profile(context, operator)
    usmap_path = normalize_optional_input(profile.usmap_path)
    paths = GamePaths(
        bpy.path.abspath(profile.game_path) if profile.game_path else "",
        bpy.path.abspath(preferences.oodle_dll) if preferences.oodle_dll else "",
        bpy.path.abspath(usmap_path) if usmap_path else "",
        profile.aes_key,
    )
    if not validate:
        return paths
    if not paths.install_root or not os.path.isdir(paths.install_root):
        raise ValueError("Choose a valid game or package folder.")
    for label, path in (("Oodle library", paths.oodle_dll), ("Mappings file", paths.usmap_path)):
        if path and not os.path.isfile(path):
            raise ValueError(f"{label} does not exist: {path}")
    if paths.aes_key:
        key = paths.aes_key.removeprefix("0x").removeprefix("0X")
        if len(key) != 64 or any(char not in "0123456789abcdefABCDEF" for char in key):
            raise ValueError("The AES key must contain 64 hexadecimal digits (optionally prefixed with 0x).")
    return paths


def _game_version(context, operator):
    return _selected_profile(context, operator).game_version


def _hidden_object_patterns(context, operator):
    return tuple(item.pattern.strip() for item in _selected_profile(context, operator).hidden_object_patterns
                 if item.pattern.strip())


def _pbr_mapping(context, operator):
    """Snapshot a profile's ordered texture-parameter PBR match lists."""
    profile = _selected_profile(context, operator)
    mapping = {}
    for slot, parameter_property, channel_property in (
        ("albedo", "pbr_albedo_parameter", None),
        ("normal", "pbr_normal_parameter", None),
        ("metalness", "pbr_metalness_parameter", "pbr_metalness_channel"),
        ("roughness", "pbr_roughness_parameter", "pbr_roughness_channel"),
        ("alpha", "pbr_alpha_parameter", "pbr_alpha_channel"),
        ("emission", None, None),
    ):
        slot_matches = sorted(
            (match for match in profile.pbr_slot_matches if match.slot == slot),
            key=lambda match: match.priority,
        )
        if channel_property:
            matches = [
                {"parameter": match.parameter.strip(), "channel": match.channel}
                for match in slot_matches
                if match.parameter.strip()
            ]
        else:
            matches = [
                match.parameter.strip() for match in slot_matches if match.parameter.strip()
            ]
        # Keep old saved profiles usable if Blender has not yet run the
        # one-time migration that places their original value in the list.
        if not matches and parameter_property:
            parameter = getattr(profile, parameter_property).strip()
            if parameter:
                matches = [
                    {"parameter": parameter, "channel": getattr(profile, channel_property)}
                ] if channel_property else [parameter]
        if matches:
            mapping[slot] = matches
    return mapping


def _index_key(context, operator):
    return (
        session.source_id(_paths(context, operator, validate=False), _game_version(context, operator)),
        operator.path_filter.strip(),
    )


def _current_index(context, operator):
    try:
        index = _INDEX.get(_index_key(context, operator))
        if index is not None and ("umaps" if operator.mesh_kind == "UMAP" else "staticMeshes") in index:
            return index
        return None
    except ValueError:
        return None


def _mesh_paths(index, kind):
    return index.get({"STATIC": "staticMeshes", "SKELETAL": "skeletalMeshes", "UMAP": "umaps"}[kind]) or []


class SQEX_OT_index_generic_unreal(SQEX_LoggedOperator):
    bl_idname = "wm.sqex_index_generic_unreal"
    bl_label = "Load / Refresh Asset List"
    bl_description = strings.GENERIC_INDEX_DESCRIPTION
    bl_options = {"INTERNAL"}

    def execute(self, context):
        try:
            with session.GenericSession(_paths(context, self), _game_version(context, self)) as mounted:
                if self.mesh_kind == "UMAP":
                    response = mounted.request({"action": "umap_index"})
                    paths = [path for path in response.get("umaps") or [] if self.path_filter.casefold().strip() in path.casefold()]
                    response = {"meshIndex": {"umaps": paths}, "mount": mounted.mount_info}
                else:
                    response = mounted.request({"action": "generic_mesh_index", "pathFilter": self.path_filter.strip()})
            mesh_index = response.get("meshIndex") or {}
            key = _index_key(context, self)
            if self.mesh_kind != "UMAP":
                try:
                    validate_mesh_index(mesh_index)
                except UnreadableMeshPackagesError:
                    _INDEX.pop(key, None)
                    raise
            index = _INDEX.setdefault(key, {})
            index.update(mesh_index)
            for warning in index.get("warnings") or []:
                print(f"[Unreal index WARNING] {warning}")
            index["mount"] = response.get("mount") or {}
            _INDEX[_index_key(context, self)] = index
            package_browser.activate(
                context, _BROWSERS[self.mesh_kind], _mesh_paths(index, self.mesh_kind),
                dialog_operator=_importer_for_kind(self.mesh_kind).bl_idname,
            )
            failures = mesh_index_failure_count(index)
            note = (f"Indexed {len(index.get('umaps') or []):,} UMAP assets." if self.mesh_kind == "UMAP" else
                    f"Indexed {len(index.get('staticMeshes') or []):,} StaticMesh and "
                    f"{len(index.get('skeletalMeshes') or []):,} SkeletalMesh assets; {failures:,} packages unreadable.")
            report(self, {"WARNING"} if failures or index.get("warnings") else {"INFO"}, note)
        except Exception as exc:
            report(self, {"ERROR"}, f"Unreal package indexing failed: {exc}")
            return {"CANCELLED"}
        return {"FINISHED"}


SQEX_OT_index_generic_unreal.__annotations__ = _configuration_properties()


def _draw_generic_configuration(self, context, layout):
    config = layout.box()
    config.prop(self, "cue4parse_profile")
    config.label(
        text="Edit game paths, mappings, AES keys, and the shared Oodle DLL in Add-on Preferences.",
        icon="PREFERENCES",
    )
    config.prop(self, "path_filter")
    refresh = config.operator(SQEX_OT_index_generic_unreal.bl_idname, icon="FILE_REFRESH")
    for name in _CONFIG_PROPS:
        setattr(refresh, name, getattr(self, name))


def _execute_meshes(self, context):
    armature = (context.active_object if self.mesh_kind == "SKELETAL"
                and self.bind_active_armature and not self.build_skeleton else None)
    if self.mesh_kind == "SKELETAL" and self.bind_active_armature and not self.build_skeleton:
        if armature is None or armature.type != "ARMATURE":
            report(self, {"ERROR"}, "Select an armature to bind, or enable Build Armature.")
            return {"CANCELLED"}
    try:
        paths = _paths(context, self)
        game_version = _game_version(context, self)
        if self.virtual_path.strip():
            virtual_paths = [self.virtual_path.strip()]
        else:
            index = _current_index(context, self)
            if index is None:
                raise ValueError("Load the asset list using the current mount settings first.")
            virtual_paths = package_browser.selected_paths(context, _BROWSERS[self.mesh_kind])
        if not virtual_paths:
            raise ValueError("Select at least one asset in the package browser.")
        imported = 0
        failures = []
        with session.GenericSession(
            paths,
            game_version,
            pbr_mapping=_pbr_mapping(context, self),
            hidden_object_patterns=_hidden_object_patterns(context, self),
            **nanite_options(self),
        ) as mounted:
            mounted.profile_id = self.cue4parse_profile
            for virtual_path in virtual_paths:
                new_armature = None
                try:
                    options = dict(
                        scale_factor=self.scale_factor, material_session=mounted,
                        material_builder=materials.build_material, game_features=False,
                        face_y_forward=meshes._face_y_forward_enabled(self.face_y_forward),
                        offset_opposite_faces=self.offset_opposite_faces,
                    )
                    if self.mesh_kind == "STATIC":
                        obj = meshes.import_static_mesh_asset(context, mounted.static_mesh(virtual_path), virtual_path, **options)
                    else:
                        payload = mounted.skeletal_mesh(virtual_path)
                        binding = armature
                        if self.build_skeleton:
                            skeleton = payload.get("inlineSkeleton") or {}
                            if not skeleton.get("bones") and payload.get("skeletonPath"):
                                skeleton = mounted.skeleton_asset(payload["skeletonPath"])
                            if self.attachment_sockets != meshes.ATTACHMENT_SOCKETS_NONE:
                                socket_sources = [skeleton]
                                # UE sockets may live on the Skeleton or the mesh itself.
                                if payload.get("skeletonPath"):
                                    try:
                                        socket_sources.append(mounted.skeleton_asset(payload["skeletonPath"]))
                                    except Exception as exc:
                                        print(f"[Unreal sockets WARNING] Linked Skeleton: {exc}")
                                try:
                                    socket_sources.append(mounted.skeleton_asset(virtual_path))
                                except Exception as exc:
                                    print(f"[Unreal sockets WARNING] Mesh sockets: {exc}")
                                sockets = {}
                                for source in (*socket_sources, payload):
                                    for socket in source.get("sockets") or []:
                                        sockets[socket.get("name")] = socket
                                skeleton = dict(skeleton, sockets=list(sockets.values()))
                            if self.import_mesh_referenced_bones_only:
                                skeleton, _, _ = meshes._restrict_skeleton_to_referenced_bones(
                                    skeleton, set(payload.get("boneNames") or []))
                            bones = _bones_from_gargoyle(skeleton)
                            if not bones:
                                raise ValueError("The mesh contains no readable reference skeleton.")
                            new_armature = build_armature_from_bones(
                                context, payload.get("name") or "UnrealArmature", bones,
                                (skeleton.get("sockets") or []) if self.attachment_sockets != meshes.ATTACHMENT_SOCKETS_NONE else [],
                                create_socket_empties=self.attachment_sockets == meshes.ATTACHMENT_SOCKETS_EMPTIES,
                                create_socket_bones=self.attachment_sockets == meshes.ATTACHMENT_SOCKETS_BONES,
                                scale_factor=self.scale_factor, connect_bones=self.connect_bones,
                                face_y_forward=options["face_y_forward"],
                                preserve_ue_axis_order=self.preserve_ue_axis_order,
                                game_features=False,
                            )
                            session.tag_armature(new_armature, mounted, payload, virtual_path, self.scale_factor)
                            binding = new_armature
                        obj, _, _ = meshes.import_skeletal_mesh_asset(
                            context, payload, virtual_path, armature_obj=binding, **options,
                        )
                    obj["ue_source_id"] = mounted.cache_namespace
                    obj["ue_game_version"] = game_version
                    # Empty or unreadable material references still receive
                    # an unconnected output instead of Blender's default shader.
                    for slot in obj.material_slots:
                        if slot.material is not None and not slot.material.get("ue_texture_inventory_complete"):
                            slot.material = materials.build_material(
                                slot.material.name, slot.material.get("ue_virtual_path", ""), {}, mounted,
                            )
                    from .visibility import apply_default_visibility
                    apply_default_visibility(obj, mounted.hidden_object_patterns, virtual_path)
                    imported += 1
                except Exception as exc:
                    if new_armature is not None:
                        for child in list(new_armature.children):
                            if child.get("sqex_socket_bone"):
                                bpy.data.objects.remove(child, do_unlink=True)
                        data = new_armature.data
                        bpy.data.objects.remove(new_armature, do_unlink=True)
                        if data.users == 0:
                            bpy.data.armatures.remove(data)
                    failures.append(f"{virtual_path}: {exc}")
                    print(f"[Unreal import ERROR] {failures[-1]}")
            texture_failures = mounted.failed
            material_failures = mounted.failed_materials
            geometry_note = mounted.geometry_summary() if self.mesh_kind == "STATIC" else ""
            nanite_fallbacks = len(mounted.nanite_fallbacks)
        if not imported:
            raise RuntimeError(failures[0] if failures else "No assets were imported.")
    except Exception as exc:
        report(self, {"ERROR"}, f"Unreal import failed: {exc}")
        return {"CANCELLED"}
    report(self, {"WARNING"} if failures or texture_failures or material_failures or nanite_fallbacks else {"INFO"},
           f"Imported {imported:,} Unreal mesh(es); {len(failures):,} asset failures, "
           f"{texture_failures:,} unavailable textures, {material_failures:,} unreadable materials. {geometry_note} See console for details.")
    return {"FINISHED"}


def _generic_import_defaults(operator, context):
    _load_versions()
    _preferences, profiles = _profiles(context)
    if not profiles:
        raise ValueError("Add a CUE4Parse game profile in the add-on preferences.")


def _generic_browser_state(operator, context, *, refresh=False):
    if refresh:
        _preferences, profiles = _profiles(context)
        if not any(profile.profile_id == operator.cue4parse_profile for profile in profiles):
            operator.cue4parse_profile = profiles[0].profile_id
    index = _current_index(context, operator)
    paths = _mesh_paths(index or {}, operator.mesh_kind)
    messages = []
    if index is not None:
        info = index.get("mount") or {}
        messages.append((f"{info.get('mountedVfsCount', 0):,} containers mounted; "
                         f"{info.get('unloadedVfsCount', 0):,} unavailable; "
                         f"{index.get('failures', 0):,} packages unreadable.", "INFO"))
        if index.get("warnings"):
            messages.append(("Some asset registries were unreadable. See console for details.", "ERROR"))
    return MeshBrowserState(_BROWSERS[operator.mesh_kind], paths,
                           key=(_index_key(context, operator), id(index), len(paths)),
                           ready=index is not None, messages=tuple(messages))


def _execute_package_umaps(operator, context):
    paths = _paths(context, operator)
    index = _current_index(context, operator)
    if not operator.virtual_path.strip() and index is None:
        raise ValueError("Load the asset list using the current mount settings first.")
    virtual_paths = ([operator.virtual_path.strip()] if operator.virtual_path.strip() else
                     package_browser.selected_paths(context, _BROWSERS["UMAP"]))
    if not virtual_paths:
        raise ValueError("Select at least one UMAP in the package browser.")
    imported = created_total = 0
    failures = []
    missing_assets = set()
    with session.GenericSession(
        paths, _game_version(context, operator), pbr_mapping=_pbr_mapping(context, operator),
        hidden_object_patterns=_hidden_object_patterns(context, operator),
        import_textures=operator.import_textures, **texture_options(operator),
        **nanite_options(operator),
    ) as mounted:
        mounted.profile_id = operator.cue4parse_profile
        assets = maps.MapAssets(context, mounted, operator.scale_factor,
                                offset_opposite_faces=operator.offset_opposite_faces)
        indexed_paths = (index or {}).get("umaps") or []
        if operator.recursive_import and (not indexed_paths or operator.path_filter.strip()):
            indexed_paths = mounted.request({"action": "umap_index"}).get("umaps") or []
        content_root = (getattr(mounted, "mount_info", {}) or {}).get("contentRoot", "")
        queue = StreamingMapQueue(virtual_paths, indexed_paths, content_root=content_root.rstrip("/") or None)
        for virtual_path in queue.paths:
            try:
                actor_payload = mounted.umap_actors(virtual_path)
                if operator.recursive_import:
                    queue.extend(actor_payload.get("actors") or [])
                created, missing = maps.import_map(
                    context, mounted, assets, virtual_path, import_models=operator.import_models,
                    import_lights=operator.import_lights, import_light_probes=operator.import_light_probes,
                    exposure=operator.exposure, attenuation_radius_mult=operator.attenuation_radius_mult,
                    always_cast_shadows=operator.always_cast_shadows,
                    import_point_lights=operator.import_point_lights,
                    import_spot_lights=operator.import_spot_lights, actor_payload=actor_payload,
                    import_rect_lights=operator.import_rect_lights,
                    import_directional_lights=operator.import_directional_lights,
                    bake_light_parameters=operator.bake_light_parameters,
                    import_splines=operator.import_splines,
                    **landscape_options(operator),
                )
                created_total += created
                missing_assets.update(missing)
                imported += 1
            except Exception as exc:
                failures.append(f"{virtual_path}: {exc}")
                print(f"[Unreal UMAP import ERROR] {failures[-1]}")
        texture_failures, material_failures = mounted.failed, mounted.failed_materials
        geometry_note = mounted.geometry_summary()
        nanite_fallbacks = len(mounted.nanite_fallbacks)
    if not imported:
        raise RuntimeError(failures[0] if failures else "No maps were imported.")
    report(operator, {"WARNING"} if failures or texture_failures or material_failures or missing_assets or nanite_fallbacks else {"INFO"},
           f"Imported {imported:,} Unreal UMAP(s), {created_total:,} placements, "
           f"{len(missing_assets):,} missing mesh assets; {len(failures):,} asset failures, "
           f"{texture_failures:,} unavailable textures, {material_failures:,} unreadable materials. {geometry_note} See console for details.")
    return {"FINISHED"}


_GENERIC_MESH_DEFAULTS = {
    "bind_active_armature": False, "preserve_ue_axis_order": True,
    "attachment_sockets": meshes.ATTACHMENT_SOCKETS_NONE,
}
_GENERIC_STATIC_SOURCE = PackageMeshSource(
    "Generic Unreal", _generic_browser_state, _execute_meshes,
    defaults=_generic_import_defaults, configure=_draw_generic_configuration,
    material_summary="Materials use the selected profile's texture mappings.",
)
_GENERIC_SKELETAL_SOURCE = PackageMeshSource(
    "Generic Unreal", _generic_browser_state, _execute_meshes,
    defaults=_generic_import_defaults, configure=_draw_generic_configuration,
    property_defaults=_GENERIC_MESH_DEFAULTS,
    material_summary="Materials use the selected profile's texture mappings.",
)
_generic_mesh_configuration = _configuration_properties()
_generic_mesh_configuration.pop("mesh_kind")
_generic_mesh_configuration.update(nanite_properties())
SQEX_OT_import_generic_unreal_static_mesh = make_package_mesh_importer(
    class_name="SQEX_OT_import_generic_unreal_static_mesh",
    bl_idname="import_scene.sqex_generic_unreal_static_mesh", module_name=__name__, mesh_kind="STATIC",
    source=_GENERIC_STATIC_SOURCE, configuration_properties=_generic_mesh_configuration,
    persisted_configuration=("cue4parse_profile", "path_filter", *NANITE_OPTION_NAMES),
)
_generic_skeletal_configuration = _configuration_properties()
_generic_skeletal_configuration.pop("mesh_kind")
SQEX_OT_import_generic_unreal_skeletal_mesh = make_package_mesh_importer(
    class_name="SQEX_OT_import_generic_unreal_skeletal_mesh",
    bl_idname="import_scene.sqex_generic_unreal_skeletal_mesh", module_name=__name__, mesh_kind="SKELETAL",
    source=_GENERIC_SKELETAL_SOURCE, configuration_properties=_generic_skeletal_configuration,
    persisted_configuration=("cue4parse_profile", "path_filter"),
)


_GENERIC_UMAP_SOURCE = PackageMapSource(
    "Generic Unreal", _generic_browser_state, _execute_package_umaps,
    defaults=_generic_import_defaults, configure=_draw_generic_configuration,
    show_nanite=lambda operator, context: not _game_version(context, operator).removeprefix("GAME_").startswith("UE4"),
)
_generic_map_configuration = _configuration_properties()
_generic_map_configuration.pop("mesh_kind")
_generic_map_configuration.update(nanite_properties(default_mode="FALLBACK"))
SQEX_OT_import_generic_unreal_umap = make_package_map_importer(
    class_name="SQEX_OT_import_generic_unreal_umap",
    bl_idname="import_scene.sqex_generic_unreal_umap", module_name=__name__,
    source=_GENERIC_UMAP_SOURCE, configuration_properties=_generic_map_configuration,
    persisted_configuration=("cue4parse_profile", "path_filter", *NANITE_OPTION_NAMES),
)


def _importer_for_kind(kind):
    return {
        "STATIC": SQEX_OT_import_generic_unreal_static_mesh,
        "SKELETAL": SQEX_OT_import_generic_unreal_skeletal_mesh,
        "UMAP": SQEX_OT_import_generic_unreal_umap,
    }[kind]


class SQEX_OT_import_generic_unreal_mesh(SQEX_LoggedOperator):
    """Keep the former operator ID working through the shared operators."""
    bl_idname = "import_scene.sqex_generic_unreal_mesh"
    bl_label = "Generic Unreal Import (Legacy)"
    _map_source = _GENERIC_UMAP_SOURCE
    _massive_environment = False
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}
    _persisted_props = tuple(dict.fromkeys((
        "cue4parse_profile", "path_filter", *MAP_OPTION_NAMES, "import_lights",
        *MESH_OPTION_NAMES, *SKELETAL_OPTION_NAMES,
        *NANITE_OPTION_NAMES, "import_splines",
    )))

    @property
    def _mesh_source(self):
        return _GENERIC_SKELETAL_SOURCE if self.mesh_kind == "SKELETAL" else _GENERIC_STATIC_SOURCE

    def invoke(self, context, event):
        cls = PackageMapOperator if self.mesh_kind == "UMAP" else PackageMeshOperator
        return cls.invoke(self, context, event)

    def check(self, context):
        cls = PackageMapOperator if self.mesh_kind == "UMAP" else PackageMeshOperator
        return cls.check(self, context)

    def draw(self, context):
        cls = PackageMapOperator if self.mesh_kind == "UMAP" else PackageMeshOperator
        return cls.draw(self, context)

    def cancel(self, context):
        self._save_last_import_settings(context)

    def execute(self, context):
        cls = PackageMapOperator if self.mesh_kind == "UMAP" else PackageMeshOperator
        return cls.execute(self, context)


SQEX_OT_import_generic_unreal_mesh.__annotations__ = {
    **mesh_properties("SKELETAL", defaults=_GENERIC_MESH_DEFAULTS),
    **_configuration_properties(), **map_properties(), **nanite_properties(),
    "import_splines": bpy.props.BoolProperty(
        name="Import splines", default=True, description=strings.MAP_IMPORT_SPLINES),
    "import_lights": bpy.props.BoolProperty(name="Import Lights", default=True, options={"HIDDEN"}),
}


CLASSES = (
    SQEX_OT_index_generic_unreal,
    SQEX_OT_import_generic_unreal_static_mesh,
    SQEX_OT_import_generic_unreal_skeletal_mesh,
    SQEX_OT_import_generic_unreal_umap,
    SQEX_OT_import_generic_unreal_mesh,
)
