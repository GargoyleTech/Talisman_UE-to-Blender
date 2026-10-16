"""Persist parsed Bonamik assets beside imported Blender armatures.

Physics is intentionally not applied.  The embedded JSON only keeps the
package gargoyle result available to a later simulator, much like KDI keeps its
audited graph in Blender Text blocks.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

try:
    import bpy
except ModuleNotFoundError:  # Keeps the parser usable in normal Python tests.
    bpy = None

from .parser import BonamikAsset, parse_bnm


BNM_TEXT_BLOCK_PREFIX = "SQEX_BNM_"
BNM_TEXTS_PROPERTY = "sqex_bnm_texts"
BNM_STORAGE_SCHEMA = "sqex-bnm-asset-v1"


def _path_key(path: str) -> str:
    return path.replace("\\", "/").lstrip("/").casefold()


def _text_name(virtual_path: str) -> str:
    stem = virtual_path.replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0]
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem) or "Asset"
    digest = hashlib.sha1(_path_key(virtual_path).encode("utf-8")).hexdigest()[:10]
    return f"{BNM_TEXT_BLOCK_PREFIX}{stem}_{digest}"


def _stored_records(owner: Any) -> list[dict[str, str]]:
    try:
        value = owner.get(BNM_TEXTS_PROPERTY, "[]")
        decoded = json.loads(value)
    except (AttributeError, TypeError, ValueError):
        return []
    if not isinstance(decoded, Sequence) or isinstance(decoded, (str, bytes, bytearray)):
        return []
    records: list[dict[str, str]] = []
    for item in decoded:
        if isinstance(item, Mapping):
            path = item.get("path")
            text = item.get("text")
            if isinstance(path, str) and isinstance(text, str):
                records.append({"path": path, "text": text})
        elif isinstance(item, str):
            # Accept an early/simple list-of-text-names form if one was saved
            # during development before the richer source manifest existed.
            records.append({"path": "", "text": item})
    return records


def store_bnm_assets(
    owner: Any,
    assets: Sequence[tuple[str, BonamikAsset | Mapping[str, Any]]],
    *,
    source_mesh_path: str = "",
) -> tuple[str, ...]:
    """Embed BNM gargoyle payloads in Blender Text blocks and link them to owner.

    ``owner`` is normally the newly built armature; an unbound mesh can be used
    as the fallback owner.  Re-importing the same virtual BNM path replaces its
    matching text payload rather than duplicating it.  This function creates no
    objects, modifiers, constraints, or animation data.
    """
    if bpy is None:
        raise RuntimeError("BNM persistence requires Blender's bpy module")

    records_by_path = {
        _path_key(record["path"]): record
        for record in _stored_records(owner)
        if record["path"]
    }
    for virtual_path, source in assets:
        path = virtual_path.strip().replace("\\", "/").lstrip("/")
        if not path:
            continue
        parsed = source if isinstance(source, BonamikAsset) else parse_bnm(source)
        text_name = _text_name(path)
        text = bpy.data.texts.get(text_name)
        if text is None:
            text = bpy.data.texts.new(text_name)
        payload = {
            "schema": BNM_STORAGE_SCHEMA,
            "source": {
                "virtual_path": path,
                "source_mesh_path": source_mesh_path,
            },
            "asset": dict(parsed.source),
        }
        text.clear()
        text.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        records_by_path[_path_key(path)] = {"path": path, "text": text.name}

    records = sorted(records_by_path.values(), key=lambda record: _path_key(record["path"]))
    owner[BNM_TEXTS_PROPERTY] = json.dumps(records, ensure_ascii=False)
    return tuple(record["text"] for record in records)


def stored_bnm_assets(owner: Any) -> tuple[BonamikAsset, ...]:
    """Load parsed BNM assets previously embedded on an armature or mesh."""
    if bpy is None:
        raise RuntimeError("BNM persistence requires Blender's bpy module")
    assets: list[BonamikAsset] = []
    for record in _stored_records(owner):
        text = bpy.data.texts.get(record["text"])
        if text is None:
            continue
        try:
            payload = json.loads(text.as_string())
            asset = payload.get("asset") if isinstance(payload, Mapping) else None
            assets.append(parse_bnm(asset))
        except (TypeError, ValueError):
            continue
    return tuple(assets)
