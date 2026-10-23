"""Shared reporting for Square Enix Blender operators.

Blender's status-bar reports are intentionally short-lived; mirror them to the
system console so import diagnostics, warnings, and success summaries live in
one searchable log as well.
"""

from __future__ import annotations

import json

import bpy

from ..package_utils import addon_package_name


def _json_setting_value(value):
    """Convert Blender RNA vector values into data JSON can persist.

    FloatVectorProperty values are returned as ``mathutils.Vector`` in Blender
    5.x.  They behave like a sequence but are not directly JSON serializable.
    Keep this conversion generic so Color/array properties work as well.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_setting_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_setting_value(item) for item in value]
    try:
        return [_json_setting_value(item) for item in value]
    except TypeError:
        return value


def _addon_package_name() -> str:
    return addon_package_name(__package__)


def _last_settings_preferences(context):
    addon = context.preferences.addons.get(_addon_package_name())
    return addon.preferences if addon else None


class SQEX_LoggedOperator(bpy.types.Operator):
    """Operator base which sends every Blender report to stdout too, and lets
    an importer remember its dialog settings across Blender sessions.
    """

    # Property names an importer subclass wants remembered as "last used" --
    # deliberately excludes transient per-asset state like a typed search
    # path, search results, or a file browser's filepath. Persisted as JSON
    # on the add-on preferences, keyed by bl_idname, so unrelated operators
    # never collide.
    _persisted_props: tuple[str, ...] = ()

    def _load_last_import_settings(self, context) -> None:
        """Apply this operator's remembered settings, and mark this run as
        interactive so `_save_last_import_settings` is allowed to update them.

        Call once from `invoke()`, never from `execute()` alone -- an operator
        invoked headlessly by another operator's `execute()` (e.g. the
        SkeletalMesh importer driving the Skeleton importer with its own
        caller-supplied/context-derived arguments) must not feed those
        arguments back into what the user chose the last time they used the
        dialog directly.
        """
        self._interactive_invoke = True
        prefs = _last_settings_preferences(context)
        if prefs is None or not self._persisted_props:
            return
        try:
            all_settings = json.loads(prefs.last_import_settings_json or "{}")
        except (ValueError, TypeError):
            return
        if not isinstance(all_settings, dict):
            return
        stored = all_settings.get(self.bl_idname)
        if not isinstance(stored, dict):
            return
        for prop_name in self._persisted_props:
            if prop_name not in stored:
                continue
            try:
                setattr(self, prop_name, stored[prop_name])
            except (AttributeError, TypeError, ValueError):
                # Removed enum items and old property types must not prevent
                # the remaining options from being restored.
                continue

    def _save_last_import_settings(self, context) -> None:
        """Remember this run's settings, if it was reached via `invoke()`."""
        if not getattr(self, "_interactive_invoke", False):
            return
        prefs = _last_settings_preferences(context)
        if prefs is None or not self._persisted_props:
            return
        try:
            all_settings = json.loads(prefs.last_import_settings_json or "{}")
        except (ValueError, TypeError):
            all_settings = {}
        if not isinstance(all_settings, dict):
            all_settings = {}
        all_settings[self.bl_idname] = {
            prop_name: _json_setting_value(getattr(self, prop_name))
            for prop_name in self._persisted_props
        }
        serialized = json.dumps(all_settings)
        if prefs.last_import_settings_json != serialized:
            prefs.last_import_settings_json = serialized
            # Python assignments to AddonPreferences do not mark preferences
            # dirty. Let Blender's normal preference saving retain the change.
            context.preferences.is_dirty = True

    def cancel(self, context) -> None:
        """Retain dialog choices when an importer or file selector is closed."""
        self._save_last_import_settings(context)

    # Blender invokes its RNA ``Operator.report`` implementation directly,
    # bypassing a Python override on this base class.  Operator code must use
    # the module-level ``report()`` helper below so the same message reaches
    # both Blender's Info log and the system console.


def report(operator: bpy.types.Operator, levels, message: str) -> None:
    """Emit a Blender report and mirror it to the system console.

    ``Operator.report`` is implemented by Blender's RNA layer and bypasses a
    Python subclass override, so every operator calls this helper explicitly.
    """
    level_text = "/".join(sorted(str(level) for level in levels))
    print(f"[Talisman {level_text}] {message}")
    operator.report(levels, message)
