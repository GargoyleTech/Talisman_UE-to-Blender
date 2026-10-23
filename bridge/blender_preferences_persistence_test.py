"""Disable/re-enable and restart checks; run with an isolated BLENDER_USER_CONFIG."""

import importlib
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

import addon_utils
import bpy


assert os.environ.get("BLENDER_USER_CONFIG"), "Use an isolated test configuration"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
assert bpy.ops.preferences.addon_enable(module="addon") == {"FINISHED"}
import addon
from addon.core.blender import preferences_storage as storage


def preferences():
    return bpy.context.preferences.addons["addon"].preferences


def check_settings():
    prefs = preferences()
    assert prefs.oodle_dll == "fixture-oodle.dll"
    assert prefs.remake_install_root == "fixture-remake"
    assert prefs.rebirth_usmap_path == "fixture-rebirth.usmap"
    assert prefs.remake_aes_key == "user-supplied-test-key"
    assert prefs.show_rebirth_settings
    assert abs(prefs.map_scale_factor - 0.025) < 1e-6
    assert json.loads(prefs.last_import_settings_json) == {
        "import_scene.fixture": {"import_textures": False}}
    profiles = {p.profile_id: p for p in prefs.generic_unreal_profiles}
    assert "ghostrunner" not in profiles  # Intentionally deleted preset stays deleted.
    custom = profiles["custom_persistence"]
    assert custom.name == "Persistence fixture" and custom.game_path == "fixture-game"
    assert custom.game_version == "GAME_UE4_26" and custom.aes_key == "fixture-custom-key"
    assert prefs.generic_unreal_active_profile == custom.profile_id
    assert [m.slot for m in custom.pbr_slot_matches] == ["emission", "roughness"]
    assert custom.pbr_slot_matches[0].parameter == "Emissive*"
    assert custom.pbr_slot_matches[1].channel == "G"
    assert custom.hidden_object_patterns[0].pattern == "*Collision*"


if "--verify-restart" in sys.argv:
    check_settings()
    print("PREFERENCES_RESTART_OK", flush=True)
    sys.exit(0)

prefs = preferences()
prefs.oodle_dll = "fixture-oodle.dll"
prefs.remake_install_root = "fixture-remake"
prefs.rebirth_usmap_path = "fixture-rebirth.usmap"
prefs.remake_aes_key = "user-supplied-test-key"
prefs.show_rebirth_settings = True
prefs.map_scale_factor = 0.025
prefs.last_import_settings_json = json.dumps({"import_scene.fixture": {"import_textures": False}})
profiles = prefs.generic_unreal_profiles
profiles.remove(next(i for i, p in enumerate(profiles) if p.profile_id == "ghostrunner"))
custom = profiles.add()
custom.profile_id = "custom_persistence"
custom.name = "Persistence fixture"
custom.game_path = "fixture-game"
custom.game_version = "GAME_UE4_26"
custom.aes_key = "fixture-custom-key"
custom.pbr_slot_matches_initialized = custom.pbr_slot_match_channels_initialized = True
for slot, parameter, channel in (("emission", "Emissive*", "R"), ("roughness", "ORM", "G")):
    match = custom.pbr_slot_matches.add()
    match.slot, match.parameter, match.channel = slot, parameter, channel
custom.hidden_object_patterns.add().pattern = "*Collision*"
prefs.generic_unreal_active_profile = custom.profile_id
check_settings()
expected = storage._snapshot(prefs)

# Use Blender's actual toggle path, which removes the Addon entry after unregister().
addon_utils.disable("addon", default_set=True)
assert "addon" not in bpy.context.preferences.addons
backup = storage._backup_path()
assert backup.is_file()
assert bpy.ops.preferences.addon_enable(module="addon") == {"FINISHED"}
check_settings()
assert storage._snapshot(preferences()) == expected

# An interrupted backup write must leave the previous backup intact.
previous_backup = backup.read_bytes()
with patch.object(storage.os, "replace", side_effect=OSError("fixture write failure")):
    storage.save_preferences()
assert backup.read_bytes() == previous_backup
assert not list(backup.parent.glob("*.tmp"))

# Ordinary source reloads must still preserve all settings.
importlib.reload(addon)
addon.register()
check_settings()
assert storage._snapshot(preferences()) == expected

# Never replace existing preferences with a stale backup.
preferences().oodle_dll = "newer-value"
assert not storage.restore_preferences()
assert preferences().oodle_dll == "newer-value"
preferences().oodle_dll = "fixture-oodle.dll"

# A removed enum item and an unknown property do not discard other settings.
addon_utils.disable("addon", default_set=True)
payload = json.loads(backup.read_text(encoding="utf-8"))
damaged = json.loads(json.dumps(payload))
damaged["settings"]["removed_property"] = "ignored"
damaged["settings"]["generic_unreal_profiles"][-1]["game_version"] = "REMOVED_ENUM"
backup.write_text(json.dumps(damaged), encoding="utf-8")
assert bpy.ops.preferences.addon_enable(module="addon") == {"FINISHED"}
assert preferences().oodle_dll == "fixture-oodle.dll"
assert preferences().generic_unreal_profiles[-1].game_path == "fixture-game"
preferences().generic_unreal_profiles[-1].game_version = "GAME_UE4_26"
check_settings()

# Preserve an intentionally emptied profile collection, too.
preferences().generic_unreal_profiles.clear()
addon_utils.disable("addon", default_set=True)
assert bpy.ops.preferences.addon_enable(module="addon") == {"FINISHED"}
assert not preferences().generic_unreal_profiles
addon_utils.disable("addon", default_set=True)

# Invalid or unrelated backups must not prevent registration.
for invalid in ("not JSON", '[]', json.dumps({**payload, "module": "other_addon"})):
    backup.write_text(invalid, encoding="utf-8")
    assert bpy.ops.preferences.addon_enable(module="addon") == {"FINISHED"}
    assert preferences().oodle_dll == ""
    addon_utils.disable("addon", default_set=True)

# A failed registration must not replace a good backup with partial defaults.
backup.write_text(json.dumps(payload), encoding="utf-8")
with patch.object(addon.ui_preferences, "ensure_generic_unreal_profiles", side_effect=RuntimeError("fixture registration failure")):
    assert addon_utils.enable("addon", default_set=True, handle_error=lambda _error: None) is None
assert json.loads(backup.read_text(encoding="utf-8")) == payload
assert bpy.ops.preferences.addon_enable(module="addon") == {"FINISHED"}
check_settings()
addon_utils.disable("addon", default_set=True)

# Leave only the backup on disk: the next Blender process must recover it.
backup.write_text(json.dumps(payload), encoding="utf-8")
print("PREFERENCES_DISABLE_ENABLE_OK", flush=True)
