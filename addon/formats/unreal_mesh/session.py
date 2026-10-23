"""Generic gargoyle sessions with source-scoped packed images and diagnostics."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

import bpy

from ...core.blender.import_cache import find_datablock, live_datablock, remember_datablock

from ...core.blender.material_nodes import (
    load_packed_image, image_meets_texture_request, set_channel_packed_alpha,
)

from ...core.bridge import gargoyle_command, gargoyle_executable_path
from ...core.profiles import GamePaths, GameProfile
from .binary_geometry import load_binary_geometry
from ..unreal_package.session import PackageAssetSession


_CAPABILITIES = None


def game_versions():
    global _CAPABILITIES
    if _CAPABILITIES is None:
        executable = gargoyle_executable_path(Path(__file__).resolve().parents[2])
        result = subprocess.run(
            [str(executable), "--capabilities"], capture_output=True, text=True,
            encoding="utf-8", errors="replace", check=False,
        )
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or "The bundled bridge needs to be rebuilt for generic imports.")
        _CAPABILITIES = json.loads(result.stdout)["gameVersions"]
    return _CAPABILITIES


def make_profile(version):
    return GameProfile(
        key="generic_unreal", label="Generic Unreal", gargoyle_profile="generic:" + version,
        engine_label=version, package_relative_path=(), install_root_property="",
    )


def source_id(paths, version, pbr_mapping=None):
    values = [os.path.normcase(os.path.abspath(value)) if value else "" for value in (
        paths.install_root, paths.oodle_dll, paths.usmap_path,
    )]
    values.extend((version, paths.aes_key))
    if pbr_mapping:
        values.append({key: str(value) for key, value in sorted(pbr_mapping.items())})
    return hashlib.sha256(json.dumps(values).encode("utf-8")).hexdigest()


def tag_armature(armature, mounted, payload, virtual_path, scale_factor):
    """Keep animation source settings on the data too, for placed map instances."""
    values = {
        "ue_source_id": mounted.cache_namespace,
        "ue_game_version": getattr(mounted, "game_version", ""),
        "ue_profile_id": getattr(mounted, "profile_id", ""),
        "ue_import_scale": scale_factor,
        "ue_skeleton_path": payload.get("linkedSkeletonPath") or payload.get("skeletonPath") or "",
        "ue_skeletal_mesh_path": virtual_path,
        "ue_reference_skeleton": json.dumps(payload.get("inlineSkeleton") or {}),
        "sqex_face_forward": armature.get("sqex_face_forward", "UNREAL"),
        "sqex_axis_order": armature.get("sqex_axis_order", "UNREAL"),
    }
    for target in (armature, armature.data):
        for key, value in values.items():
            target[key] = value


class GenericSession(PackageAssetSession):
    def __init__(self, paths: GamePaths, version: str, *, pbr_mapping=None, hidden_object_patterns=(),
                 max_texture_resolution=0, texture_mip_offset=0, import_textures=True,
                 nanite_mode="AUTO", max_nanite_triangles=2_000_000, nanite_cache_mb=256):
        super().__init__(paths.install_root, paths.oodle_dll, paths.usmap_path,
                         profile=make_profile(version), aes_key=paths.aes_key,
                         max_texture_resolution=max_texture_resolution, texture_mip_offset=texture_mip_offset,
                         import_textures=import_textures)
        self.paths = paths
        self.game_version = version
        self.pbr_mapping = dict(pbr_mapping or {})
        self.hidden_object_patterns = tuple(hidden_object_patterns)
        self.cache_namespace = source_id(paths, version, self.pbr_mapping)
        self.texture_namespace = self.cache_namespace
        if not import_textures:
            self.texture_namespace += ":no-textures"
        self._stderr_file = None
        self.failed_materials = 0
        self.texture_info = {}
        self.nanite_mode = nanite_mode.upper()
        self.max_nanite_triangles = max(0, int(max_nanite_triangles))
        self.nanite_cache_mb = max(0, min(16384, int(nanite_cache_mb)))
        if self.nanite_mode not in {"AUTO", "NATIVE", "FALLBACK"}:
            raise ValueError("Unknown Nanite geometry mode.")
        self.geometry_namespace = hashlib.sha256(json.dumps([
            self.cache_namespace, self.nanite_mode, self.max_nanite_triangles,
        ]).encode()).hexdigest()
        self.nanite_fallbacks = {}
        self.geometry_counts = {}

    def static_mesh(self, asset_path):
        # Temporary files are removed after the typed arrays have been loaded;
        # callers can retain the arrays independently of the bridge/session.
        with tempfile.TemporaryDirectory(prefix="talisman_geometry_") as directory:
            payload = self.request({
                "action": "static_mesh", "assetPath": asset_path,
                "naniteMode": self.nanite_mode, "maxNaniteTriangles": self.max_nanite_triangles,
                "naniteCacheMiB": self.nanite_cache_mb, "geometryOutput": directory,
            }).get("staticMesh") or {}
            if self.nanite_mode != "FALLBACK" and payload.get("geometryMode") != self.nanite_mode:
                raise RuntimeError("The bundled bridge does not support the requested Nanite mode. Rebuild or reinstall the matching add-on and bridge.")
            payload = load_binary_geometry(payload, directory)
        if reason := payload.get("naniteFallbackReason"):
            self.nanite_fallbacks[asset_path] = reason
            print(f"[Nanite fallback] {asset_path}: {reason}")
        source = payload.get("geometrySource", "CONVENTIONAL")
        self.geometry_counts[source] = self.geometry_counts.get(source, 0) + 1
        return payload

    def geometry_summary(self):
        return (f"{self.geometry_counts.get('NANITE', 0):,} native Nanite meshes; "
                f"{len(self.nanite_fallbacks):,} automatic Nanite fallbacks.")

    def _start_process(self):
        self._stderr_file = tempfile.TemporaryFile(mode="w+b")
        command = gargoyle_command(
            Path(__file__).resolve().parents[2], self.profile, self.paths, "-", operation="asset-server",
        )
        try:
            self.process = subprocess.Popen(
                command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._stderr_file,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
            )
            self.mount_info = self.request({"action": "generic_mount"}).get("mount") or {}
            if not self.mount_info.get("fileCount") or not self.mount_info.get("mountedVfsCount"):
                self._stderr_file.seek(0)
                detail = self._stderr_file.read().decode("utf-8", errors="replace").strip()
                raise RuntimeError("No package containers were mounted. Check the folder, CUE4Parse profile, AES key, and compression library."
                                   + ("\n" + detail if detail else ""))
        except Exception:
            self._stop_process()
            raise

    def request(self, payload, *, report_errors=True):
        try:
            return super().request(payload, report_errors=report_errors)
        except RuntimeError as exc:
            if self.process is not None and self.process.poll() is not None and self._stderr_file is not None:
                self._stderr_file.seek(0)
                detail = self._stderr_file.read().decode("utf-8", errors="replace").strip()
                if detail:
                    raise RuntimeError(detail) from exc
            raise

    def _stop_process(self):
        process = self.process
        try:
            super()._stop_process()
        finally:
            if process is not None:
                for stream in (process.stdin, process.stdout):
                    if stream is not None:
                        stream.close()
            if self._stderr_file is not None:
                self._stderr_file.close()
                self._stderr_file = None

    @staticmethod
    def material_asset_path(path):
        return path if path and path.casefold() != "none" else None

    def material_instance(self, asset_path):
        key = asset_path.casefold()
        if key not in self.material_cache:
            try:
                self.material_cache[key] = self.request({
                    "action": "generic_material", "assetPath": asset_path, "objectPath": asset_path,
                }).get("material") or {}
            except Exception as exc:
                warning = f"Material references could not be read: {asset_path}: {exc}"
                print(f"[Unreal material WARNING] {warning}")
                self.failed_materials += 1
                self.material_cache[key] = {"textures": [], "warnings": [warning]}
        return self.material_cache[key]

    def __call__(self, game_path):
        if not self.import_textures:
            return None
        key = game_path.casefold()
        if key in self.cache:
            image = self.cache[key]
            if image is None or (live_datablock("images", image) and image_meets_texture_request(
                    image, self.max_texture_resolution, self.texture_mip_offset)):
                return image
            del self.cache[key]
        existing = find_datablock("images", "generic-texture", (self.cache_namespace, self.texture_namespace, key),
                                  lambda item: (item.get("ue_source_id"), item.get("ue_texture_namespace"),
                                                item.get("ue_virtual_path", "").casefold()), self)
        if existing is not None and image_meets_texture_request(
                existing, self.max_texture_resolution, self.texture_mip_offset):
            set_channel_packed_alpha(existing)
            self.cache[key] = existing
            return existing
        image = None
        try:
            with tempfile.TemporaryDirectory(prefix="unreal_texture_") as directory:
                name = game_path.rsplit("/", 1)[-1].split(".")[0]
                output = os.path.join(directory, name + ".dds")
                response = self.request({
                    "action": "generic_texture", "assetPath": game_path,
                    "objectPath": game_path, "ddsOutput": output,
                    **self.texture_request_options,
                })
                info = response.get("dds") or {}
                self.texture_info[key] = info
                if info.get("status") == "unavailable":
                    raise RuntimeError(info.get("reason") or "This texture has no stored image pixels.")
                image = load_packed_image(info.get("output") or output, name, metadata={
                    "ue_source_id": self.cache_namespace,
                    "ue_virtual_path": game_path,
                    "ue_pixel_format": info.get("pixelFormat", ""),
                    "ue_image_format": info.get("fileExtension", "dds"),
                    "ue_texture_type": info.get("textureType", "Texture2D"),
                    "ue_texture_layout": info.get("textureLayout", "2D"),
                    "ue_texture_namespace": self.texture_namespace,
                    "ue_texture_mip_index": info.get("mipIndex", -1),
                    "ue_max_texture_resolution": self.max_texture_resolution,
                    "ue_texture_mip_offset": self.texture_mip_offset,
                    "ue_texture_source_width": info.get("sourceWidth", info.get("width", 1)),
                    "ue_texture_source_height": info.get("sourceHeight", info.get("height", 1)),
                }, color_space="sRGB" if info.get("srgb") else "Non-Color",
                    max_resolution=self.max_texture_resolution, existing=existing)
                # Unreal commonly stores a material mask in the color texture's
                # alpha. Keep RGB independent instead of treating that mask as
                # image coverage (which turns zero-alpha skin regions black).
                set_channel_packed_alpha(image)
            self.cache[key] = image
            remember_datablock("images", image, self)
            self.loaded += 1
            return image
        except Exception as exc:
            if image is not None and image.users == 0:
                bpy.data.images.remove(image)
            print(f"[Unreal texture WARNING] {game_path}: {exc}")
            self.cache[key] = None
            self.failed += 1
            return None
