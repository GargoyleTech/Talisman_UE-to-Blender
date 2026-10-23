"""Keep preferences when Blender removes an add-on's entry on disable."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

import bpy

from ..package_utils import addon_package_name


_VALUE_TYPES = {"BOOLEAN", "INT", "FLOAT", "STRING", "ENUM"}
# This editable UI alias shares storage with aes_key; persist the canonical field.
_ALIASES = {"aes_key_unmasked"}


def _preferences():
    entry = bpy.context.preferences.addons.get(addon_package_name(__package__))
    return entry.preferences if entry else None


def _properties(settings):
    declared = getattr(type(settings), "__annotations__", {})
    for prop in settings.bl_rna.properties:
        if prop.identifier in declared and prop.identifier not in _ALIASES and (
            prop.type == "COLLECTION" or (prop.type in _VALUE_TYPES and not prop.is_readonly)
        ):
            yield prop


def _snapshot(settings):
    values = {}
    for prop in _properties(settings):
        name = prop.identifier
        value = getattr(settings, name)
        if prop.type == "COLLECTION":
            if value or settings.is_property_set(name):
                values[name] = [_snapshot(item) for item in value]
        elif settings.is_property_set(name):
            values[name] = list(value) if getattr(prop, "is_array", False) else value
    return values


def _restore(settings, values):
    for prop in _properties(settings):
        name = prop.identifier
        if name not in values:
            continue
        value = values[name]
        try:
            if prop.type == "COLLECTION":
                if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
                    continue
                collection = getattr(settings, name)
                collection.clear()
                for item in value:
                    _restore(collection.add(), item)
            else:
                setattr(settings, name, value)
        except (AttributeError, TypeError, ValueError):
            # A removed enum item or changed property must not lose other settings.
            continue


def _backup_path(*, create=False):
    directory = bpy.utils.user_resource("CONFIG", path="talisman", create=create)
    if not directory:
        return None
    # Keep separate installations/repositories independent, like Blender does.
    return Path(directory) / f"preferences-{addon_package_name(__package__)}.json"


def save_preferences():
    """Run before unregistering RNA classes and Blender deletes the entry."""
    settings = _preferences()
    if settings is None:
        return
    temporary = None
    try:
        values = _snapshot(settings)
        if not values:
            return
        path = _backup_path(create=True)
        if path is None:
            return
        payload = {"schema": 1, "module": addon_package_name(__package__), "settings": values}
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=path.name, suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(payload, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    except (OSError, TypeError, ValueError):
        # Do not log private paths, keys, or serialized preference values.
        print("[Talisman preferences WARNING] Could not preserve add-on settings before disable.")
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def restore_preferences():
    """Restore only a fresh entry; existing Blender preferences take priority."""
    settings = _preferences()
    if settings is None or _snapshot(settings):
        return False
    path = _backup_path()
    if path is None or not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema") != 1:
            return False
        if payload.get("module") != addon_package_name(__package__):
            return False
        values = payload.get("settings")
        if not isinstance(values, dict) or not values:
            return False
        _restore(settings, values)
    except (OSError, TypeError, ValueError):
        print("[Talisman preferences WARNING] Could not restore preserved add-on settings.")
        return False
    bpy.context.preferences.is_dirty = True
    return True
