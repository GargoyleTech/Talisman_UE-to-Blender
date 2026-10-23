"""Check preset upgrades and n/a handling in factory Blender preferences."""

from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

import bpy


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
bpy.ops.preferences.addon_enable(module="addon")
import addon
from addon.core.bridge import gargoyle_command
from addon.core.profiles import GamePaths, GameProfile
from addon.formats.unreal_mesh import importer, profile_test
from addon.ui import preferences as ui


preferences = bpy.context.preferences.addons["addon"].preferences
expected = {
    "fnaf_security_breach": ("GAME_UE4_27", ""),
    "fnaf_secret_of_the_mimic": ("GAME_UE4_27", ""),
    "amid_evil": ("GAME_UE4_27", "n/a"),
    "anomalous": ("GAME_UE4_27", "n/a"),
    "hi_fi_rush": ("GAME_UE4_27", ""),
    "hogwarts_legacy": ("GAME_HogwartsLegacy", "n/a"),
    "moss": ("GAME_UE4_27", "n/a"),
    "cosmic_shake": ("GAME_UE4_27", "n/a"),
    "ghostrunner": ("GAME_UE4_26", ""),
    "last_flag": ("GAME_UE5_5", "n/a"),
    "marvel_rivals": ("GAME_MarvelRivals", ""),
}


def profiles_by_id():
    return {p.profile_id: p for p in ui.ensure_generic_unreal_profiles(preferences)}


profiles = profiles_by_id()
assert profiles.keys() == expected.keys(), profiles.keys()
for profile_id, (version, key) in expected.items():
    profile = profiles[profile_id]
    mappings = "" if profile_id in {"last_flag", "marvel_rivals"} else "n/a"
    assert (profile.game_version, profile.aes_key, profile.usmap_path, profile.game_path) == (version, key, mappings, ""), profile_id
    assert bool(profile.pbr_slot_matches) == (profile_id.startswith("fnaf_") or profile_id == "last_flag"), profile_id
# Hide-pattern rows remain per profile, and import snapshots ignore blank rows.
profile = profiles["last_flag"]
assert not profile.hidden_object_patterns
assert bpy.ops.preferences.sqex_edit_generic_unreal_hide_pattern(profile_id=profile.profile_id) == {"FINISHED"}
profile.hidden_object_patterns[0].pattern = "  *Collision*  "
assert bpy.ops.preferences.sqex_edit_generic_unreal_hide_pattern(profile_id=profile.profile_id) == {"FINISHED"}
operator = SimpleNamespace(cue4parse_profile=profile.profile_id)
assert importer._hidden_object_patterns(bpy.context, operator) == ("*Collision*",)
assert not profiles["ghostrunner"].hidden_object_patterns
assert bpy.ops.preferences.sqex_edit_generic_unreal_hide_pattern(profile_id=profile.profile_id, pattern_index=0) == {"FINISHED"}
assert len(profile.hidden_object_patterns) == 1
profile.hidden_object_patterns.clear()

history = preferences.generic_unreal_profile_templates_seen
pointers = {key: p.as_pointer() for key, p in profiles.items()}
assert {key: p.as_pointer() for key, p in profiles_by_id().items()} == pointers
assert preferences.generic_unreal_profile_templates_seen == history

# Both selectors sort visible labels while retaining the numeric enum values
# that identify existing selections, including after a profile is renamed.
original_order = [p.profile_id for p in preferences.generic_unreal_profiles]
enum_values = {profile_id: index for index, profile_id in enumerate(original_order)}
selectors = (importer._profile_items, ui._generic_profile_editor_items)
for selector in selectors:
    items = selector(None, bpy.context)
    assert [item[1].casefold() for item in items] == sorted(item[1].casefold() for item in items)
    assert {item[0]: item[3] for item in items} == enum_values
last_flag_name = profiles["last_flag"].name
try:
    profiles["last_flag"].name = "aaa Last Flag"
    for selector in selectors:
        items = selector(None, bpy.context)
        assert items[0][0] == "last_flag"
        assert {item[0]: item[3] for item in items} == enum_values
    assert [p.profile_id for p in preferences.generic_unreal_profiles] == original_order
finally:
    profiles["last_flag"].name = last_flag_name

# Add newly shipped templates without replacing existing objects or edits.
# Snapshot after removal: Blender may move collection items following it.
for new_id in ("last_flag", "marvel_rivals"):
    new_index = next(i for i, p in enumerate(preferences.generic_unreal_profiles) if p.profile_id == new_id)
    preferences.generic_unreal_profiles.remove(new_index)
    existing_pointers = {p.profile_id: p.as_pointer() for p in preferences.generic_unreal_profiles}
    preferences.generic_unreal_profile_templates_seen = ",".join(sorted(set(expected) - {new_id}))
    profiles = profiles_by_id()
    assert {key: p.as_pointer() for key, p in profiles.items() if key != new_id} == existing_pointers
    assert profiles[new_id].game_version == expected[new_id][0] and profiles[new_id].usmap_path == ""

# Upgrade an old installation with an edited FNaF profile, a deleted FNaF
# preset, and a pre-existing user configuration for one of the new games.
preferences.generic_unreal_profiles.clear()
preferences.generic_unreal_profiles_initialized = True
preferences.generic_unreal_profile_templates_seen = ""
profiles = preferences.generic_unreal_profiles
security = profiles.add()
security.profile_id = "fnaf_security_breach"
security.name = "My Security Breach"
security.game_version = "GAME_UE4_26"
security.game_path = "my-security-breach"
security.aes_key = "0x" + "01" * 32
security.usmap_path = "my-mappings.usmap"
amid = profiles.add()
amid.profile_id = "amid_evil"
amid.name = "My AMID EVIL"
amid.game_version = "GAME_UE4_25"
amid.game_path = "my-amid-evil"
amid.aes_key = "my-own-key"
custom = profiles.add()
custom.profile_id = "custom_1"
custom.name = "Unrelated game"
custom.game_version = "GAME_UE5_0"
preferences.generic_unreal_active_profile = security.profile_id
profiles = profiles_by_id()
assert "fnaf_secret_of_the_mimic" not in profiles, "Deleted legacy preset was restored"
assert set(profiles) == (set(expected) - {"fnaf_secret_of_the_mimic"}) | {"custom_1"}
assert (security.name, security.game_version, security.game_path, security.usmap_path, security.aes_key) == (
    "My Security Breach", "GAME_UE4_26", "my-security-breach", "my-mappings.usmap", "0x" + "01" * 32)
assert (amid.name, amid.game_version, amid.game_path, amid.aes_key) == (
    "My AMID EVIL", "GAME_UE4_25", "my-amid-evil", "my-own-key")
assert amid.usmap_path == "n/a"
assert custom.name == "Unrelated game" and custom.usmap_path == custom.aes_key == ""
assert preferences.generic_unreal_active_profile == security.profile_id
assert bpy.ops.preferences.sqex_remove_generic_unreal_profile(profile_id="ghostrunner") == {"FINISHED"}
assert "ghostrunner" not in profiles_by_id()

# Template history survives reload, so intentional deletion stays effective.
addon.unregister()
addon.register()
preferences = bpy.context.preferences.addons["addon"].preferences
profiles = profiles_by_id()
assert "ghostrunner" not in profiles and "fnaf_secret_of_the_mimic" not in profiles
assert profiles["amid_evil"].game_version == "GAME_UE4_25"
assert profiles["hogwarts_legacy"].game_version == "GAME_HogwartsLegacy"


class Layout:
    def __init__(self):
        self.properties = []
        self.operators = []
    def row(self, **kwargs): return self
    def column(self, **kwargs): return self
    def box(self): return self
    def prop(self, target, name, **kwargs): self.properties.append(name)
    def label(self, **kwargs): pass
    def operator(self, name, **kwargs):
        self.operators.append(name)
        return SimpleNamespace()


def drawn_layout(profile):
    layout = Layout()
    count = len(preferences.generic_unreal_profiles)
    ui.SQEX_OT_edit_generic_unreal_profiles.draw(
        SimpleNamespace(layout=layout, profile_id=profile.profile_id), bpy.context)
    assert len(preferences.generic_unreal_profiles) == count
    return layout


def drawn_properties(profile):
    return drawn_layout(profile).properties


profile = profiles["hogwarts_legacy"]
assert "aes_key_unmasked" in drawn_properties(profile)
assert profile.aes_key_unmasked == "n/a"
profile.aes_key_unmasked = "0x" + "02" * 32
assert profile.aes_key == "0x" + "02" * 32
assert "aes_key" in drawn_properties(profile) and "aes_key_unmasked" not in drawn_properties(profile)
assert ui.SQEX_PG_generic_unreal_profile.bl_rna.properties["aes_key"].subtype == "PASSWORD"

# Reset is scoped to the selected shipped profile and restores current
# defaults, including clearing old credentials and user material mappings.
reset = bpy.ops.preferences.sqex_reset_generic_unreal_profile
reset_name = ui.SQEX_OT_reset_generic_unreal_profile.bl_idname
assert reset_name in drawn_layout(profile).operators
assert reset_name not in drawn_layout(profiles["custom_1"]).operators
assert reset(profile_id="custom_1") == {"CANCELLED"}
assert reset(profile_id="ghostrunner") == {"CANCELLED"}
assert "ghostrunner" not in profiles_by_id()
profile.name = "Edited title"
profile.game_path = "edited-folder"
profile.game_version = "GAME_UE5_0"
profile.usmap_path = "edited.usmap"
profile.pbr_albedo_parameter = "EditedColor"
profile.pbr_alpha_channel = "B"
match = profile.pbr_slot_matches.add()
match.slot, match.parameter = "normal", "EditedNormal"
profile_test.RESULTS[profile.profile_id] = ("old", {"success": True})
with patch.object(profile_test, "cancel", wraps=profile_test.cancel) as cancel:
    assert reset(profile_id=profile.profile_id) == {"FINISHED"}
    cancel.assert_called_once_with(profile.profile_id)
assert profile.profile_id not in profile_test.RESULTS
assert (profile.name, profile.game_path, profile.game_version, profile.usmap_path, profile.aes_key) == (
    "Hogwarts Legacy", "", "GAME_HogwartsLegacy", "n/a", "n/a")
assert not profile.pbr_slot_matches and not profile.pbr_albedo_parameter and profile.pbr_alpha_channel == "A"
assert profiles["amid_evil"].name == "My AMID EVIL", "Reset modified a different profile"

# A later template change must be applied by reset, without replacing the
# existing profile object or relying on a one-time upgrade flag.
updated = tuple((item[0], "Updated template", "GAME_UE5_1", "updated.usmap", "")
                if item[0] == profile.profile_id else item for item in ui._DEFAULT_GENERIC_UNREAL_PROFILES)
pointer = profile.as_pointer()
with patch.object(ui, "_DEFAULT_GENERIC_UNREAL_PROFILES", updated):
    assert reset(profile_id=profile.profile_id) == {"FINISHED"}
assert profile.as_pointer() == pointer
assert (profile.name, profile.game_version, profile.usmap_path, profile.aes_key) == (
    "Updated template", "GAME_UE5_1", "updated.usmap", "")
assert reset(profile_id=profile.profile_id) == {"FINISHED"}

security = profiles["fnaf_security_breach"]
security.pbr_slot_matches.clear()
security.pbr_normal_parameter = "EditedNormal"
assert reset(profile_id=security.profile_id) == {"FINISHED"}
assert (security.name, security.game_version, security.game_path, security.usmap_path, security.aes_key) == (
    "Five Nights at Freddy's: Security Breach", "GAME_UE4_27", "", "n/a", "")
assert not security.pbr_normal_parameter
assert any(m.slot == "metalness" and m.parameter == "AO_Rough_Metal" and m.channel == "B"
           for m in security.pbr_slot_matches)
assert any(m.slot == "roughness" and m.parameter == "AO_Rough_Metal" and m.channel == "G"
           for m in security.pbr_slot_matches)

# Last Flag requires user-supplied mappings, needs no AES key, and has distinct
# character/environment parameter names. Refresh preserves custom settings;
# explicit reset restores the shipped mappings and clears machine-local paths.
last_flag = profiles["last_flag"]
expected_last_flag_mapping = {
    "albedo": ["Base Color Texture", "Base Color"],
    "normal": ["Normal Texture", "Normal"],
    "metalness": [{"parameter": "ORM Texture", "channel": "B"}],
    "roughness": [{"parameter": "ORM Texture", "channel": "G"}],
}
last_flag_operator = SimpleNamespace(cue4parse_profile="last_flag")
assert importer._pbr_mapping(bpy.context, last_flag_operator) == expected_last_flag_mapping
# Emission uses the same ordered match editor, without scalar channel controls.
assert bpy.ops.preferences.sqex_add_generic_unreal_pbr_slot_match(
    profile_id="last_flag", slot="emission") == {"FINISHED"}
emission_match = next(m for m in last_flag.pbr_slot_matches if m.slot == "emission")
emission_match.parameter = "  Emissive*  "
assert importer._pbr_mapping(bpy.context, last_flag_operator) == {
    **expected_last_flag_mapping, "emission": ["Emissive*"]}
emission_layout = Layout()
ui._draw_pbr_slot_matches(emission_layout, last_flag, "emission")
assert "parameter" in emission_layout.properties and "channel" not in emission_layout.properties
last_flag.game_path = "my-last-flag"
last_flag.usmap_path = "my-last-flag.usmap"
last_flag.game_version = "GAME_UE5_4"
last_flag.pbr_slot_matches[0].parameter = "CustomColor"
assert profiles_by_id()["last_flag"].pbr_slot_matches[0].parameter == "CustomColor"
assert (last_flag.game_path, last_flag.usmap_path, last_flag.game_version) == (
    "my-last-flag", "my-last-flag.usmap", "GAME_UE5_4")
assert reset(profile_id="last_flag") == {"FINISHED"}
assert (last_flag.name, last_flag.game_path, last_flag.usmap_path, last_flag.game_version, last_flag.aes_key) == (
    "Last Flag", "", "", "GAME_UE5_5", "n/a")
assert importer._pbr_mapping(bpy.context, last_flag_operator) == expected_last_flag_mapping

# Marvel Rivals needs both external inputs. Refresh preserves configured
# paths/keys; reset clears them and restores the dedicated CUE4Parse profile.
marvel = profiles["marvel_rivals"]
marvel.game_path = "my-marvel-rivals"
marvel.usmap_path = "my-marvel-rivals.usmap"
marvel.aes_key = "0x" + "04" * 32
marvel.game_version = "GAME_UE5_3"
assert profiles_by_id()["marvel_rivals"].as_pointer() == marvel.as_pointer()
assert (marvel.game_path, marvel.usmap_path, marvel.aes_key, marvel.game_version) == (
    "my-marvel-rivals", "my-marvel-rivals.usmap", "0x" + "04" * 32, "GAME_UE5_3")
assert reset(profile_id="marvel_rivals") == {"FINISHED"}
assert (marvel.name, marvel.game_path, marvel.usmap_path, marvel.aes_key, marvel.game_version) == (
    "Marvel Rivals", "", "", "", "GAME_MarvelRivals")
assert not marvel.pbr_slot_matches

with tempfile.TemporaryDirectory(prefix="profile-templates-") as directory:
    profile.game_path = directory
    preferences.oodle_dll = ""
    operator = SimpleNamespace(cue4parse_profile=profile.profile_id)
    profile.usmap_path = profile.aes_key = ""
    empty_paths = importer._paths(bpy.context, operator)
    empty_signature = profile_test.configuration(preferences, profile)[2]
    for marker in ("n/a", "N/A", " \tN/a  "):
        profile.usmap_path = profile.aes_key = marker
        paths = importer._paths(bpy.context, operator)
        assert paths == empty_paths and not paths.usmap_path and not paths.aes_key
        tested_paths, version, signature = profile_test.configuration(preferences, profile)
        assert tested_paths == paths and signature == empty_signature
        direct = GamePaths(directory, usmap_path=marker, aes_key=marker)
        assert direct.usmap_path == direct.aes_key == ""
        command = gargoyle_command(ROOT / "addon", importer.session.make_profile(version), direct, "-")
        assert command[6] == command[12] == "", command
        assert profile.usmap_path == profile.aes_key == marker, "Visible markers were overwritten"

    # The profile test must receive empty inputs too, not report a bogus key
    # format or try to open a file called n/a. No package containers are needed.
    assert bpy.ops.preferences.sqex_test_generic_unreal_profile(profile_id=profile.profile_id) == {"FINISHED"}
    result = profile_test.RESULTS[profile.profile_id][1]
    assert result["aesStatus"] == "not_needed" and result["mappingsStatus"] == "not_supplied", result

    picker = SimpleNamespace(_target=lambda: profile, property_name="usmap_path", filepath="old")
    with patch.object(ui.ImportHelper, "invoke", return_value={"RUNNING_MODAL"}):
        assert ui.SQEX_OT_select_usmap.invoke(picker, bpy.context, None) == {"RUNNING_MODAL"}
    assert picker.filepath == "", "File picker tried to browse to n/a"

    # Actual inputs still pass through, while invalid non-marker text is rejected.
    mapping = Path(directory) / "real.usmap"
    mapping.touch()
    profile.usmap_path = str(mapping)
    profile.aes_key = "  0x" + "03" * 32 + "  "
    paths = importer._paths(bpy.context, operator)
    assert paths.usmap_path == str(mapping) and paths.aes_key == "0x" + "03" * 32
    profile.aes_key = "not-a-key"
    try:
        importer._paths(bpy.context, operator)
    except ValueError as error:
        assert "64 hexadecimal digits" in str(error)
    else:
        raise AssertionError("Invalid AES text was silently ignored")
    profile.aes_key = "n/a"
    profile.usmap_path = str(Path(directory) / "absent.usmap")
    try:
        importer._paths(bpy.context, operator)
    except ValueError as error:
        assert "Mappings file does not exist" in str(error)
    else:
        raise AssertionError("Missing mappings were silently ignored")

    resolved = []
    definition = GameProfile("fixture", "Fixture", "generic:GAME_UE4_27", "UE4.27", (), "root",
                             usmap_property="mapping", aes_key_property="key")
    paths = definition.paths_from_preferences(
        SimpleNamespace(root=directory, oodle_dll="", mapping=" N/A ", key="n/a"),
        lambda path: resolved.append(path) or path)
    assert paths.usmap_path == paths.aes_key == "" and resolved == [directory]

assert bpy.ops.preferences.sqex_remove_generic_unreal_profile(profile_id="last_flag") == {"FINISHED"}
assert "last_flag" not in profiles_by_id()
addon.unregister()
addon.register()
preferences = bpy.context.preferences.addons["addon"].preferences
assert "last_flag" not in profiles_by_id(), "Deleted Last Flag preset was restored on reload"
addon.unregister()
print("GENERIC_PROFILE_TEMPLATES_OK: defaults, upgrade, deletion, reload, reset, n/a inputs, masking, profile test")
