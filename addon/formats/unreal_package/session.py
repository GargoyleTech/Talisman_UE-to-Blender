"""Mounted CUE4Parse sessions and package request transport.

Callers provide a game profile; the runtime does not select a title.
"""

from __future__ import annotations

import json
import hashlib
import os
import subprocess
import tempfile
from pathlib import Path

import bpy

from ...core.blender.material_nodes import load_packed_image, image_meets_texture_request

from ...core.bridge import gargoyle_command
from ...core.profiles import GamePaths
from .paths import _texture_package_path


def _gargoyle_command(
    game_root: str,
    oodle_dll: str,
    usmap_path: str,
    output_json: str,
    profile,
    aes_key: str = "",
    **options,
) -> list[str]:
    return gargoyle_command(
        Path(__file__).resolve().parents[2],
        profile,
        GamePaths(game_root, oodle_dll, usmap_path, aes_key),
        output_json,
        **options,
    )


def _run_gargoyle(
    game_root: str,
    oodle_dll: str,
    usmap_path: str,
    *,
    path_filter: str = "",
    asset_path: str = "",
    raw_output: str = "",
    summary: bool = False,
    profile,
    aes_key: str = "",
) -> dict:
    output_handle = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    output_path = output_handle.name
    output_handle.close()
    command = _gargoyle_command(
        game_root,
        oodle_dll,
        usmap_path,
        output_path,
        path_filter=path_filter,
        asset_path=asset_path,
        raw_output=raw_output,
        summary=summary,
        profile=profile,
        aes_key=aes_key,
    )
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if completed.returncode:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(
                detail or f"Bridge exited with code {completed.returncode}"
            )
        with open(output_path, encoding="utf-8-sig") as stream:
            return json.load(stream)
    finally:
        try:
            os.remove(output_path)
        except OSError:
            pass


def _run_gargoyle_asset_request(
    game_root: str,
    oodle_dll: str,
    usmap_path: str,
    payload: dict,
    *,
    profile,
    aes_key: str = "",
) -> dict:
    """Run one short-lived asset-server request (used by package pickers)."""
    command = _gargoyle_command(
        game_root,
        oodle_dll,
        usmap_path,
        "-",
        profile=profile,
        aes_key=aes_key,
        operation="asset-server",
    )
    completed = subprocess.run(
        command,
        input=json.dumps(payload) + "\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(detail or f"Bridge exited with code {completed.returncode}")
    response_line = next(
        (line for line in completed.stdout.splitlines() if line.strip()), ""
    )
    if not response_line:
        raise RuntimeError(
            "The package bridge returned no response while indexing meshes."
        )
    response = json.loads(response_line)
    if not response.get("ok"):
        details = response.get("errorDetails")
        if details:
            print(
                "[Talisman bridge ERROR] Asset-server request failed:\n" + str(details)
            )
        raise RuntimeError(response.get("error") or "Package mesh indexing failed")
    return response


class PackageAssetSession:
    """Keep CUE4Parse mounted for a complete multi-asset import batch."""

    UMAP_RESTART_WORKING_SET_MB = 2048

    def __init__(
        self,
        game_root: str,
        oodle_dll: str,
        usmap_path: str,
        *,
        profile,
        aes_key: str = "",
        max_texture_resolution: int = 0,
        texture_mip_offset: int = 0,
        import_textures: bool = True,
    ):
        self.game_root = game_root
        self.oodle_dll = oodle_dll
        self.usmap_path = usmap_path
        self.profile = profile
        self.aes_key = aes_key
        self.max_texture_resolution = max(0, int(max_texture_resolution))
        self.texture_mip_offset = max(-16, min(0, int(texture_mip_offset)))
        source = [os.path.normcase(os.path.abspath(game_root)), profile.key,
                  os.path.normcase(os.path.abspath(usmap_path)) if usmap_path else ""]
        self.cache_namespace = hashlib.sha256(json.dumps(source).encode()).hexdigest()
        self.texture_namespace = self.cache_namespace
        self.import_textures = import_textures
        if not import_textures:
            self.texture_namespace += ":no-textures"
        self.process = None
        self.cache: dict[str, bpy.types.Image | None] = {}
        self.material_cache: dict[str, dict] = {}
        self.bnm_asset_cache: dict[str, dict] = {}
        self.loaded = 0
        self.failed = 0

    def __enter__(self):
        self._start_process()
        return self

    def _start_process(self):
        command = _gargoyle_command(
            self.game_root,
            self.oodle_dll,
            self.usmap_path,
            "-",
            profile=self.profile,
            aes_key=self.aes_key,
            operation="asset-server",
        )
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

    def _stop_process(self):
        if self.process is not None:
            try:
                self.process.stdin.close()
                self.process.wait(timeout=10)
            except Exception:
                self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except Exception:
                    self.process.kill()
            finally:
                self.process = None

    def __exit__(self, _exc_type, _exc, _traceback):
        self._stop_process()
        if self.loaded or self.failed:
            print(
                f"Package textures: {self.loaded} packed image(s), {self.failed} failed"
            )

    def release_batch_memory(self) -> dict:
        """Release transient package data and recycle a gargoyle that remains large."""
        threshold_bytes = self.UMAP_RESTART_WORKING_SET_MB * 1024 * 1024
        response = self.request(
            {
                "action": "release_batch_memory",
                "restartThresholdBytes": threshold_bytes,
            }
        )
        memory = response.get("memory") or {}
        if memory.get("restartRecommended"):
            working_set_mb = int(memory.get("workingSetBytes") or 0) / (1024 * 1024)
            print(
                f"Package bridge retained {working_set_mb:,.0f} MiB after cleanup; "
                "recycling it before the next map."
            )
            self._stop_process()
            self._start_process()
        return memory

    def request(self, payload: dict, *, report_errors: bool = True) -> dict:
        if self.process is None or self.process.poll() is not None:
            raise RuntimeError("The package bridge is not running.")
        self.process.stdin.write(json.dumps(payload) + "\n")
        self.process.stdin.flush()
        response_line = self.process.stdout.readline()
        if not response_line:
            raise RuntimeError("The package bridge stopped unexpectedly.")
        response = json.loads(response_line)
        if not response.get("ok"):
            details = response.get("errorDetails")
            if details and report_errors:
                print("[Talisman bridge ERROR] " + str(details))
            raise RuntimeError(response.get("error") or "Unknown package bridge error")
        return response

    def extract_raw(
        self,
        asset_path: str,
        output_path: str,
        *,
        report_errors: bool = True,
    ) -> None:
        self.request(
            {"action": "raw", "assetPath": asset_path, "output": output_path},
            report_errors=report_errors,
        )

    def import_names(self, asset_path: str) -> list[str | None]:
        response = self.request({"action": "metadata", "assetPath": asset_path})
        return response.get("importNames") or []

    def kdi_asset(self, asset_path: str) -> dict:
        return self.request({"action": "kdi", "assetPath": asset_path}).get("kdi") or {}

    def bnm_asset(self, asset_path: str, *, report_errors: bool = True) -> dict:
        """Return one raw Bonamik asset, cached for the current import session."""
        cache_key = asset_path.casefold()
        if cache_key not in self.bnm_asset_cache:
            self.bnm_asset_cache[cache_key] = (
                self.request(
                    {"action": "bnm", "assetPath": asset_path},
                    report_errors=report_errors,
                ).get("bnm")
                or {}
            )
        return self.bnm_asset_cache[cache_key]

    def skeleton_asset(self, asset_path: str) -> dict:
        return (
            self.request({"action": "skeleton", "assetPath": asset_path}).get(
                "skeleton"
            )
            or {}
        )

    def animation_asset(self, asset_path: str, *, report_errors: bool = True) -> dict:
        return (
            self.request(
                {"action": "animation", "assetPath": asset_path},
                report_errors=report_errors,
            ).get("animation")
            or {}
        )

    def static_mesh(self, asset_path: str) -> dict:
        return (
            self.request({"action": "static_mesh", "assetPath": asset_path}).get(
                "staticMesh"
            )
            or {}
        )

    def material_instance(self, asset_path: str) -> dict:
        cache_key = asset_path.casefold()
        if cache_key not in self.material_cache:
            self.material_cache[cache_key] = (
                self.request({"action": "material", "assetPath": asset_path}).get(
                    "material"
                )
                or {}
            )
        return self.material_cache[cache_key]

    def niagara_asset(self, asset_path: str) -> dict:
        """Return the gargoyle's partial Niagara report for one system package."""
        return (
            self.request({"action": "niagara", "assetPath": asset_path}).get("niagara")
            or {}
        )

    def skeletal_mesh(self, asset_path: str, *, report_errors: bool = True) -> dict:
        return (
            self.request(
                {"action": "skeletal_mesh", "assetPath": asset_path},
                report_errors=report_errors,
            ).get("skeletalMesh")
            or {}
        )

    def skeleton_bone_usage(self, asset_path: str, search_path: str) -> dict:
        return (
            self.request(
                {
                    "action": "skeleton_bone_usage",
                    "assetPath": asset_path,
                    "searchPath": search_path,
                }
            ).get("skeletonBoneUsage")
            or {}
        )

    def skeleton_users(self, asset_path: str, search_path: str) -> list[dict]:
        """Return package SkeletalMeshes that use one Skeleton in its model family."""
        return (
            self.request(
                {
                    "action": "skeleton_users",
                    "assetPath": asset_path,
                    "searchPath": search_path,
                }
            ).get("users")
            or []
        )

    def umap_actors(self, asset_path: str) -> dict:
        return (
            self.request({"action": "umap_actors", "assetPath": asset_path}).get(
                "umapActors"
            )
            or {}
        )

    def umap_data(self, asset_path: str) -> tuple[list[str | None], dict]:
        response = self.request({"action": "umap_data", "assetPath": asset_path})
        return response.get("importNames") or [], response.get("umapActors") or {}

    def streaming_probe(self, asset_path: str) -> dict:
        return (
            self.request({"action": "streaming_probe", "assetPath": asset_path}).get(
                "streamingProbe"
            )
            or {}
        )

    def cutscene_asset(self, asset_path: str) -> dict:
        """Decode an EndCinemaSequence package into FModel-compatible exports."""
        return (
            self.request({"action": "cutscene", "assetPath": asset_path}).get(
                "cutscene"
            )
            or {}
        )

    def kh_matinee_asset(self, asset_path: str) -> dict:
        """Decode a Kingdom Hearts legacy Matinee cutscene-map package."""
        return (
            self.request({"action": "kh_matinee", "assetPath": asset_path}).get(
                "matinee"
            )
            or {}
        )

    @property
    def texture_request_options(self):
        return {"maxTextureResolution": self.max_texture_resolution,
                "textureMipOffset": self.texture_mip_offset}

    def __call__(self, game_path: str):
        if not self.import_textures:
            return None
        cache_key = game_path.casefold()
        if cache_key in self.cache:
            return self.cache[cache_key]

        for image in bpy.data.images:
            if (image.get("sqex_virtual_path", "").casefold() == cache_key
                    and image.get("ue_texture_namespace") == self.texture_namespace):
                existing = image
                break
        else:
            existing = None

        if existing is not None and image_meets_texture_request(
                existing, self.max_texture_resolution, self.texture_mip_offset):
            self.cache[cache_key] = existing
            return existing

        temp_path = ""
        temp_dir = None
        try:
            asset_path, image_name = _texture_package_path(
                game_path, profile=self.profile
            )
            # Blender records the source file's basename when packing an image,
            # then uses that recorded name when the Blend file is unpacked. Give
            # the gargoyle a disposable directory but retain the DDS's game name
            # instead of NamedTemporaryFile's random ``tmp...`` basename.
            temp_dir = tempfile.TemporaryDirectory(prefix="ff7r_texture_")
            temp_path = os.path.join(temp_dir.name, f"{image_name}.dds")
            response = self.request(
                {
                    "action": "texture",
                    "assetPath": asset_path,
                    "ddsOutput": temp_path,
                    **self.texture_request_options,
                }
            )
            dds_info = response.get("dds") or {}
            if int(dds_info.get("byteLength") or 0) <= 128:
                raise RuntimeError(
                    f"CUE4Parse returned no usable DDS payload for {dds_info.get('pixelFormat', 'unknown format')}"
                )
            image = load_packed_image(
                temp_path,
                image_name,
                metadata={
                    "sqex_virtual_path": game_path,
                    "ff7r_pixel_format": dds_info.get("pixelFormat", ""),
                    "ue_texture_namespace": self.texture_namespace,
                    "ue_texture_mip_index": dds_info.get("mipIndex", -1),
                    "ue_max_texture_resolution": self.max_texture_resolution,
                    "ue_texture_mip_offset": self.texture_mip_offset,
                    "ue_texture_source_width": dds_info.get("sourceWidth", dds_info.get("width", 1)),
                    "ue_texture_source_height": dds_info.get("sourceHeight", dds_info.get("height", 1)),
                },
                max_resolution=self.max_texture_resolution,
                existing=existing,
            )
            self.cache[cache_key] = image
            self.loaded += 1
            return image
        except Exception as exc:
            print(
                f"  Warning: package texture '{game_path}' could not be loaded: {exc}"
            )
            self.cache[cache_key] = None
            self.failed += 1
            return None
        finally:
            if temp_dir is not None:
                temp_dir.cleanup()
