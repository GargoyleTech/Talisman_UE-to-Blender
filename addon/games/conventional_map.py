"""Package browser and import backend for conventional UE4 title profiles.

The game-neutral operator definition lives in formats/ue_map/package_importer.py.
"""

from __future__ import annotations

import hashlib

import bpy

from ..core.blender.reporting import report
from ..formats.ue_map import map_import
from ..formats import unreal_package as shared_packages
from . import package_browser
from ..ui.textures import texture_options
from ..formats.ue_map.package_importer import MapBrowserState, PackageMapSource, make_package_map_importer
from ..formats.ue_map.streaming import StreamingMapQueue
from ..formats.ue_map.landscapes import import_options as landscape_options


CLASSES: tuple = ()


def register_runtime_properties() -> None:
    """The shared package browser owns the only runtime browser property."""


def unregister_runtime_properties() -> None:
    """Remove the legacy property when reloading over an older add-on build."""
    if hasattr(bpy.types.WindowManager, "sqex_conventional_umap_browser"):
        del bpy.types.WindowManager.sqex_conventional_umap_browser


def make_umap_importer(
        *,
        class_name: str,
        bl_idname: str,
        game_label: str,
        profile,
        configured_paths,
        material_builder=None,
        initial_directory="",
        umap_path_filter=None,
):
    """Create a title-specific conventional UMAP operator.

    Remake and Crisis Core store ordinary UE map components, so this deliberately
    shares the package actor path rather than invoking Rebirth's MEC decoder.
    Each generated operator keeps a small independent UMAP index because its
    mounted game and preference paths are distinct. ``umap_path_filter`` lets
    titles with non-world UMAPs (for example cutscenes) keep the picker focused
    on their playable map hierarchy.
    """
    browser = package_browser.make_state(
        "UMAP assets",
        initial_directory=initial_directory,
        file_icon="FILE",
    )
    state = {"paths": [], "cache_key": None, "source": ""}

    def refresh_index(context, *, force=False) -> list[str]:
        paths = configured_paths(context)
        cache_key = (
            *shared_packages._package_config_key(
                paths.install_root, paths.oodle_dll, paths.usmap_path
            ),
            # Encrypted titles need a fresh mounted-provider request after a
            # key change, but cache only a one-way digest rather than the key.
            hashlib.sha256(paths.aes_key.encode("utf-8")).hexdigest(),
        )
        if force or cache_key != state["cache_key"]:
            result = shared_packages._run_gargoyle_asset_request(
                paths.install_root,
                paths.oodle_dll,
                paths.usmap_path,
                {"action": "umap_index"},
                profile=profile,
                aes_key=paths.aes_key,
            )
            indexed_paths = (str(path) for path in result.get("umaps") or [])
            if umap_path_filter is not None:
                indexed_paths = (
                    path for path in indexed_paths if umap_path_filter(path)
                )
            state["paths"] = sorted(
                indexed_paths,
                key=shared_packages._natural_path_key,
            )
            state["cache_key"] = cache_key
            state["source"] = "mounted packages"
        return state["paths"]

    def browser_state(operator, context, *, refresh=False):
        if refresh:
            refresh_index(context)
        return MapBrowserState(browser, state["paths"], key=state["cache_key"],
                               source=state["source"] or "memory")

    def execute(self, context):
        try:
            exposure_mult = 2.0 ** self.exposure
            paths = configured_paths(context)
            indexed_paths = refresh_index(context)
            browser["paths"] = list(indexed_paths)
            virtual_paths = package_browser.resolve_paths(
                context, browser, self.virtual_path
            )
            if not virtual_paths:
                raise ValueError("Highlight or select at least one UMAP from the package browser.")
            queue = StreamingMapQueue(virtual_paths, indexed_paths, content_root=profile.mounted_content_root)
            virtual_paths = queue.paths
            created = 0
            missing_assets = set()
            with shared_packages.PackageAssetSession(
                paths.install_root,
                paths.oodle_dll,
                paths.usmap_path,
                profile=profile,
                aes_key=paths.aes_key,
                import_textures=self.import_textures,
                **texture_options(self),
            ) as session:
                static_mesh_resolver = (
                    shared_packages.PackageStaticMeshResolver(
                        context,
                        session,
                        self.scale_factor,
                        offset_opposite_faces=self.offset_opposite_faces,
                        build_materials=material_builder is not None,
                        material_builder=material_builder,
                    )
                    if self.import_models else None
                )
                skeletal_mesh_resolver = (
                    shared_packages.PackageSkeletalMeshResolver(
                        context,
                        session,
                        self.scale_factor,
                        offset_opposite_faces=self.offset_opposite_faces,
                        build_materials=material_builder is not None,
                        material_builder=material_builder,
                    )
                    if self.import_models else None
                )
                for virtual_path in virtual_paths:
                    actor_payload = session.umap_actors(virtual_path)
                    actor_data = actor_payload.get("actors") or []
                    if self.recursive_import:
                        queue.extend(actor_data)
                    if not actor_data:
                        continue
                    map_created, map_missing = map_import.import_map_entries(
                        actor_data, virtual_path, exposure_mult=exposure_mult,
                        attenuation_radius_mult=self.attenuation_radius_mult,
                        location_scale=self.scale_factor,
                        always_cast_shadows=self.always_cast_shadows,
                        static_mesh_resolver=static_mesh_resolver,
                        skeletal_mesh_resolver=skeletal_mesh_resolver,
                        import_models=self.import_models, import_lights=self.import_lights,
                        import_splines=self.import_splines,
                        import_point_lights=self.import_point_lights,
                        import_spot_lights=self.import_spot_lights,
                        import_rect_lights=self.import_rect_lights,
                        import_directional_lights=self.import_directional_lights,
                        bake_light_parameters=self.bake_light_parameters,
                        import_reflection_probes=self.import_light_probes,
                        color_lut_loader=session.color_lut,
                        light_texture_loader=session,
                        light_profile="UE4",
                        **landscape_options(self),
                    )
                    created += map_created
                    missing_assets.update(map_missing)
            if not created:
                raise ValueError("The selected UMAPs have no supported mesh or light components.")
        except Exception as exc:
            report(self, {"ERROR"}, f"{game_label} UMAP import failed: {exc}")
            return {"CANCELLED"}
        missing_note = f"; {len(missing_assets)} mesh asset(s) missing" if missing_assets else ""
        report(self, {"INFO"}, f"Imported {len(virtual_paths)} {game_label} UMAP(s): {created:,} placement(s){missing_note}")
        return {"FINISHED"}

    return make_package_map_importer(
        class_name=class_name, bl_idname=bl_idname, module_name=__name__,
        source=PackageMapSource(game_label, browser_state, execute),
    )
