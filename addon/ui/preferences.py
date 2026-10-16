"""Persistent Blender preferences for all supported game profiles."""

from __future__ import annotations

from ..language import tooltips

from pathlib import Path

import bpy

from bpy.props import BoolProperty, CollectionProperty, FloatProperty, StringProperty
from bpy.types import AddonPreferences, Operator, PropertyGroup
from bpy_extras.io_utils import ImportHelper

from ..core import profiles as game_profiles
from ..core.package_utils import addon_package_name
from ..games.crisis_core import profile as crisis_core_profile
from ..games.kingdom_hearts_0_2 import profile as kingdom_hearts_0_2_profile
from ..games.kingdom_hearts_iii import profile as kingdom_hearts_iii_profile
from ..games.rebirth import profile as rebirth_profile
from ..games.remake import profile as remake_profile


_detected_remake_usmap = Path.home() / "Downloads" / "Mappings.usmap"
_detected_crisis_core_usmap = Path.home() / "Downloads" / "Crisis Core.usmap"


_DEFAULT_GENERIC_UNREAL_PROFILES = (
    ("fnaf_security_breach", "Five Nights at Freddy's: Security Breach"),
    ("fnaf_secret_of_the_mimic", "Five Nights at Freddy's: Secret of the Mimic"),
)
_DEFAULT_FNAF_PBR_SLOT_MATCHES = (
    ("albedo", "Base_Color", "R"),
    ("albedo", "BaseColor01", "R"),
    ("albedo", "Diffuse", "R"),
    ("albedo", "Albedo_1", "R"),
    ("normal", "Normal", "R"),
    ("normal", "Normals", "R"),
    ("normal", "Normal01", "R"),
    ("normal", "Normal_1", "R"),
    ("metalness", "AO_Rough_Metal", "B"),
    ("metalness", "ORM01", "B"),
    ("metalness", "ORM", "B"),
    ("metalness", "ORM_1", "B"),
    ("roughness", "AO_Rough_Metal", "G"),
    ("roughness", "ORM01", "G"),
    ("roughness", "ORM", "G"),
    ("roughness", "ORM_1", "G"),
)
_LEGACY_OODLE_PROPERTIES = (
    "remake_oodle_dll",
    "rebirth_oodle_dll",
    "crisis_core_oodle_dll",
    "kingdom_hearts_iii_oodle_dll",
    "kingdom_hearts_0_2_oodle_dll",
)
_CHANNEL_ITEMS = (
    ("R", "Red", tooltips.PREFERENCES_CHANNEL_R),
    ("G", "Green", tooltips.PREFERENCES_CHANNEL_G),
    ("B", "Blue", tooltips.PREFERENCES_CHANNEL_B),
    ("A", "Alpha", tooltips.PREFERENCES_CHANNEL_A),
)
_PBR_SLOT_ITEMS = (
    ("albedo", "Albedo", tooltips.PREFERENCES_PBR_SLOT_ALBEDO),
    ("normal", "Normal", tooltips.PREFERENCES_PBR_SLOT_NORMAL),
    ("metalness", "Metalness", tooltips.PREFERENCES_PBR_SLOT_METALNESS),
    ("roughness", "Roughness", tooltips.PREFERENCES_PBR_SLOT_ROUGHNESS),
    ("alpha", "Alpha", tooltips.PREFERENCES_PBR_SLOT_ALPHA),
)
_PBR_SLOT_LABELS = {slot: label for slot, label, _description in _PBR_SLOT_ITEMS}
_PBR_SCALAR_SLOTS = frozenset(("metalness", "roughness", "alpha"))
_PBR_SLOT_LEGACY_PROPERTIES = (
    ("albedo", "pbr_albedo_parameter"),
    ("normal", "pbr_normal_parameter"),
    ("metalness", "pbr_metalness_parameter"),
    ("roughness", "pbr_roughness_parameter"),
    ("alpha", "pbr_alpha_parameter"),
)
_PBR_SLOT_LEGACY_CHANNEL_PROPERTIES = {
    "metalness": "pbr_metalness_channel",
    "roughness": "pbr_roughness_channel",
    "alpha": "pbr_alpha_channel",
}
_GENERIC_PROFILE_EDITOR_ITEMS = []


def _generic_profile_game_version_items(_profile, _context):
    """Expose the gargoyle's version list without duplicating it in preferences."""
    from ..formats.unreal_mesh import importer as generic_unreal_importer

    return generic_unreal_importer._version_items(None, None)


def _addon_preferences():
    addon_name = addon_package_name(__package__)
    addon = bpy.context.preferences.addons.get(addon_name)
    return addon.preferences if addon else None


class SQEX_OT_select_usmap(Operator, ImportHelper):
    bl_idname = "preferences.sqex_select_usmap"
    bl_label = "Select Mappings (.usmap)"
    bl_options = {"INTERNAL"}

    filename_ext = ".usmap"
    filter_glob: StringProperty(default="*.usmap", options={"HIDDEN"})
    property_name: StringProperty(options={"HIDDEN"})
    profile_id: StringProperty(options={"HIDDEN"})

    def _target(self):
        preferences = _addon_preferences()
        if preferences is None:
            return None
        if self.profile_id:
            if self.property_name == "usmap_path":
                return next(
                    (profile for profile in preferences.generic_unreal_profiles
                     if profile.profile_id == self.profile_id),
                    None,
                )
        elif self.property_name in {
            "remake_usmap_path", "rebirth_usmap_path", "crisis_core_usmap_path",
        }:
            return preferences
        return None

    def invoke(self, context, event):
        target = self._target()
        if target is None:
            return {"CANCELLED"}
        self.filepath = bpy.path.abspath(getattr(target, self.property_name))
        self.filter_glob = "*.usmap"
        return ImportHelper.invoke(self, context, event)

    def execute(self, _context):
        target = self._target()
        if target is None:
            return {"CANCELLED"}
        setattr(target, self.property_name, self.filepath)
        return {"FINISHED"}


def _draw_usmap_path(layout, target, property_name, *, profile_id=""):
    row = layout.row(align=True)
    row.prop(target, property_name)
    row.operator_context = "INVOKE_DEFAULT"
    picker = row.operator(SQEX_OT_select_usmap.bl_idname, text="", icon="FILE_FOLDER")
    picker.property_name = property_name
    picker.profile_id = profile_id


def _new_generic_profile_id(profiles) -> str:
    used_ids = {profile.profile_id for profile in profiles}
    number = 1
    while f"custom_{number}" in used_ids:
        number += 1
    return f"custom_{number}"


def _ensure_pbr_slot_matches(profile):
    """Move a pre-list PBR mapping into the ordered match collection once."""
    matches = profile.pbr_slot_matches
    if not profile.pbr_slot_matches_initialized:
        if not matches:
            for slot, property_name in _PBR_SLOT_LEGACY_PROPERTIES:
                parameter = getattr(profile, property_name).strip()
                if parameter:
                    match = matches.add()
                    match.slot = slot
                    match.parameter = parameter
                    match.priority = 0
        profile.pbr_slot_matches_initialized = True
    if not profile.pbr_slot_match_channels_initialized:
        for match in matches:
            channel_property = _PBR_SLOT_LEGACY_CHANNEL_PROPERTIES.get(match.slot)
            if channel_property:
                match.channel = getattr(profile, channel_property)
        profile.pbr_slot_match_channels_initialized = True


def _seed_default_fnaf_pbr_slot_matches(profile):
    """Add the verified FNaF mapping only to an otherwise unmapped preset."""
    if (
        profile.profile_id not in {profile_id for profile_id, _name in _DEFAULT_GENERIC_UNREAL_PROFILES}
        or profile.pbr_slot_matches
    ):
        return
    for priority, (slot, parameter, channel) in enumerate(_DEFAULT_FNAF_PBR_SLOT_MATCHES):
        match = profile.pbr_slot_matches.add()
        match.slot = slot
        match.parameter = parameter
        match.channel = channel
        # Priority is only compared within the same slot, so use a single
        # increasing sequence and preserve the order visible in the editor.
        match.priority = priority


def _slot_match_indexes(profile, slot):
    """Return one slot's matches in user-visible priority order."""
    return [
        index
        for index, _match in sorted(
            (
                (index, match)
                for index, match in enumerate(profile.pbr_slot_matches)
                if match.slot == slot
            ),
            key=lambda item: (item[1].priority, item[0]),
        )
    ]


def ensure_generic_unreal_profiles(preferences=None):
    """Create the shipped generic profiles once, without restoring deleted ones."""
    preferences = preferences or _addon_preferences()
    if preferences is None:
        return ()
    # Preserve an existing setup when upgrading from the former per-title
    # Oodle fields. The obsolete fields are not re-registered.
    if not preferences.oodle_dll:
        for property_name in _LEGACY_OODLE_PROPERTIES:
            try:
                legacy_value = preferences.get(property_name, "")
            except TypeError:
                legacy_value = getattr(preferences, property_name, "")
            if legacy_value:
                preferences.oodle_dll = legacy_value
                break
    profiles = preferences.generic_unreal_profiles
    used_ids = set()
    for number, profile in enumerate(profiles, start=1):
        if not profile.profile_id or profile.profile_id in used_ids:
            profile.profile_id = f"custom_{number}"
        used_ids.add(profile.profile_id)
    if not preferences.generic_unreal_profiles_initialized:
        for profile_id, name in _DEFAULT_GENERIC_UNREAL_PROFILES:
            if profile_id in used_ids:
                continue
            profile = profiles.add()
            profile.profile_id = profile_id
            profile.name = name
            profile.game_version = "GAME_UE4_27"
            used_ids.add(profile_id)
        preferences.generic_unreal_profiles_initialized = True
    for profile in profiles:
        _ensure_pbr_slot_matches(profile)
        _seed_default_fnaf_pbr_slot_matches(profile)
    return profiles


def _generic_profile_editor_items(_operator, _context):
    """Return profile labels without mutating preferences during a UI draw."""
    global _GENERIC_PROFILE_EDITOR_ITEMS
    preferences = _addon_preferences()
    if preferences is None:
        _GENERIC_PROFILE_EDITOR_ITEMS = [
            ("fnaf_security_breach", "Five Nights at Freddy's: Security Breach", "", 0),
        ]
        return _GENERIC_PROFILE_EDITOR_ITEMS
    # Blender can ask an EnumProperty for its items while it is drawing a
    # popup.  Do not run the migration/default-profile helper here: it writes
    # preferences, and Blender rejects writes from that context.  ``invoke``
    # prepares the profiles before this menu is shown.
    profiles = preferences.generic_unreal_profiles
    _GENERIC_PROFILE_EDITOR_ITEMS = [
        (profile.profile_id, profile.name or "Unnamed CUE4Parse Profile", "", index)
        for index, profile in enumerate(profiles)
    ] or [("", "No Profiles", tooltips.PREFERENCES_GENERIC_PROFILE_EDITOR_ITEMS, 0)]
    return _GENERIC_PROFILE_EDITOR_ITEMS


class SQEX_PG_generic_unreal_slot_match(PropertyGroup):
    """One potential Unreal texture parameter for a PBR slot."""

    slot: bpy.props.EnumProperty(items=_PBR_SLOT_ITEMS, options={"HIDDEN"})
    parameter: StringProperty(
        name="Texture Parameter",
        description=tooltips.PREFERENCES_SLOT_MATCH_PARAMETER,
        default="",
    )
    channel: bpy.props.EnumProperty(
        name="Channel",
        items=_CHANNEL_ITEMS,
        default="R",
    )
    priority: bpy.props.IntProperty(default=0, options={"HIDDEN"})


class SQEX_PG_generic_unreal_profile(PropertyGroup):
    """A reusable CUE4Parse mount configuration for generic UE4 importers."""

    profile_id: StringProperty(options={"HIDDEN"})
    name: StringProperty(
        name="Profile Name",
        description=tooltips.PREFERENCES_PROFILE_NAME,
        default="New CUE4Parse Profile",
    )
    game_path: StringProperty(
        name="Game / Package Folder",
        description=tooltips.PREFERENCES_PROFILE_GAME_PATH,
        subtype="DIR_PATH",
        default="",
    )
    game_version: bpy.props.EnumProperty(
        name="CUE4Parse Game Version",
        items=_generic_profile_game_version_items,
        default=0x041B0000,
        description=tooltips.PREFERENCES_PROFILE_GAME_VERSION,
    )
    usmap_path: StringProperty(
        name="Mappings (.usmap)",
        description=tooltips.PREFERENCES_PROFILE_USMAP_PATH,
        default="",
    )
    aes_key: StringProperty(
        name="AES Key",
        description=tooltips.PREFERENCES_PROFILE_AES_KEY,
        subtype="PASSWORD",
        default="",
    )
    pbr_albedo_parameter: StringProperty(
        name="Albedo",
        description=tooltips.PREFERENCES_PROFILE_PBR_ALBEDO_PARAMETER,
        default="",
    )
    pbr_normal_parameter: StringProperty(
        name="Normal",
        description=tooltips.PREFERENCES_PROFILE_PBR_NORMAL_PARAMETER,
        default="",
    )
    pbr_metalness_parameter: StringProperty(
        name="Metalness",
        description=tooltips.PREFERENCES_PROFILE_PBR_METALNESS_PARAMETER,
        default="",
    )
    pbr_metalness_channel: bpy.props.EnumProperty(
        name="Channel",
        items=_CHANNEL_ITEMS,
        default="R",
    )
    pbr_roughness_parameter: StringProperty(
        name="Roughness",
        description=tooltips.PREFERENCES_PROFILE_PBR_ROUGHNESS_PARAMETER,
        default="",
    )
    pbr_roughness_channel: bpy.props.EnumProperty(
        name="Channel",
        items=_CHANNEL_ITEMS,
        default="R",
    )
    pbr_alpha_parameter: StringProperty(
        name="Alpha",
        description=tooltips.PREFERENCES_PROFILE_PBR_ALPHA_PARAMETER,
        default="",
    )
    pbr_alpha_channel: bpy.props.EnumProperty(
        name="Channel",
        items=_CHANNEL_ITEMS,
        default="A",
    )
    pbr_slot_matches: CollectionProperty(type=SQEX_PG_generic_unreal_slot_match)
    pbr_slot_matches_initialized: BoolProperty(default=False, options={"HIDDEN"})
    pbr_slot_match_channels_initialized: BoolProperty(default=False, options={"HIDDEN"})


class SQEX_OT_add_generic_unreal_profile(Operator):
    bl_idname = "preferences.sqex_add_generic_unreal_profile"
    bl_label = "Add CUE4Parse Profile"
    bl_options = {"INTERNAL"}

    def execute(self, _context):
        preferences = _addon_preferences()
        if preferences is None:
            return {"CANCELLED"}
        profiles = ensure_generic_unreal_profiles(preferences)
        profile = profiles.add()
        profile.profile_id = _new_generic_profile_id(profiles)
        profile.name = "New CUE4Parse Profile"
        profile.game_version = "GAME_UE4_27"
        preferences.generic_unreal_active_profile = profile.profile_id
        return {"FINISHED"}


class SQEX_OT_remove_generic_unreal_profile(Operator):
    bl_idname = "preferences.sqex_remove_generic_unreal_profile"
    bl_label = "Remove CUE4Parse Profile"
    bl_options = {"INTERNAL"}

    profile_id: StringProperty(options={"HIDDEN"})

    def execute(self, _context):
        preferences = _addon_preferences()
        if preferences is None:
            return {"CANCELLED"}
        profiles = ensure_generic_unreal_profiles(preferences)
        for index, profile in enumerate(profiles):
            if profile.profile_id == self.profile_id:
                from ..formats.unreal_mesh import profile_test
                profile_test.cancel(self.profile_id)
                profiles.remove(index)
                preferences.generic_unreal_active_profile = (
                    profiles[min(index, len(profiles) - 1)].profile_id if profiles else ""
                )
                return {"FINISHED"}
        return {"CANCELLED"}


def _generic_profile_by_id(preferences, profile_id):
    profiles = ensure_generic_unreal_profiles(preferences)
    return next((profile for profile in profiles if profile.profile_id == profile_id), None)


class SQEX_OT_add_generic_unreal_pbr_slot_match(Operator):
    bl_idname = "preferences.sqex_add_generic_unreal_pbr_slot_match"
    bl_label = "Add PBR Slot Match"
    bl_options = {"INTERNAL"}

    profile_id: StringProperty(options={"HIDDEN"})
    slot: bpy.props.EnumProperty(items=_PBR_SLOT_ITEMS, options={"HIDDEN"})

    def execute(self, _context):
        preferences = _addon_preferences()
        if preferences is None:
            return {"CANCELLED"}
        profile = _generic_profile_by_id(preferences, self.profile_id)
        if profile is None:
            return {"CANCELLED"}
        priority = max(
            (match.priority for match in profile.pbr_slot_matches if match.slot == self.slot),
            default=-1,
        )
        match = profile.pbr_slot_matches.add()
        match.slot = self.slot
        match.channel = "A" if self.slot == "alpha" else "R"
        match.priority = priority + 1
        return {"FINISHED"}


class SQEX_OT_remove_generic_unreal_pbr_slot_match(Operator):
    bl_idname = "preferences.sqex_remove_generic_unreal_pbr_slot_match"
    bl_label = "Remove PBR Slot Match"
    bl_options = {"INTERNAL"}

    profile_id: StringProperty(options={"HIDDEN"})
    slot: bpy.props.EnumProperty(items=_PBR_SLOT_ITEMS, options={"HIDDEN"})
    match_index: bpy.props.IntProperty(options={"HIDDEN"})

    def execute(self, _context):
        preferences = _addon_preferences()
        if preferences is None:
            return {"CANCELLED"}
        profile = _generic_profile_by_id(preferences, self.profile_id)
        if (
            profile is None
            or not 0 <= self.match_index < len(profile.pbr_slot_matches)
            or profile.pbr_slot_matches[self.match_index].slot != self.slot
        ):
            return {"CANCELLED"}
        profile.pbr_slot_matches.remove(self.match_index)
        return {"FINISHED"}


class SQEX_OT_move_generic_unreal_pbr_slot_match(Operator):
    bl_idname = "preferences.sqex_move_generic_unreal_pbr_slot_match"
    bl_label = "Move PBR Slot Match"
    bl_options = {"INTERNAL"}

    profile_id: StringProperty(options={"HIDDEN"})
    slot: bpy.props.EnumProperty(items=_PBR_SLOT_ITEMS, options={"HIDDEN"})
    match_index: bpy.props.IntProperty(options={"HIDDEN"})
    direction: bpy.props.IntProperty(options={"HIDDEN"})

    def execute(self, _context):
        preferences = _addon_preferences()
        if preferences is None:
            return {"CANCELLED"}
        profile = _generic_profile_by_id(preferences, self.profile_id)
        if profile is None:
            return {"CANCELLED"}
        indexes = _slot_match_indexes(profile, self.slot)
        if self.match_index not in indexes:
            return {"CANCELLED"}
        position = indexes.index(self.match_index)
        destination = position + self.direction
        if not 0 <= destination < len(indexes):
            return {"CANCELLED"}
        current = profile.pbr_slot_matches[indexes[position]]
        other = profile.pbr_slot_matches[indexes[destination]]
        current.priority, other.priority = other.priority, current.priority
        return {"FINISHED"}


def _draw_pbr_channel_buttons(layout, match):
    """Draw compact, explicitly labelled R/G/B/A enum buttons."""
    row = layout.row(align=True)
    for channel in ("R", "G", "B", "A"):
        row.prop_enum(match, "channel", channel, text=channel)


def _draw_pbr_slot_matches(layout, profile, slot):
    """Draw an ordered, editable match list for one conventional PBR slot."""
    slot_box = layout.box()
    header = slot_box.row(align=True)
    header.label(text=f"{_PBR_SLOT_LABELS[slot]} Matches")
    add = header.operator(
        SQEX_OT_add_generic_unreal_pbr_slot_match.bl_idname,
        text="",
        icon="ADD",
    )
    add.profile_id = profile.profile_id
    add.slot = slot

    indexes = _slot_match_indexes(profile, slot)
    if not indexes:
        slot_box.label(text="No parameter names configured.", icon="INFO")
    for position, match_index in enumerate(indexes):
        match = profile.pbr_slot_matches[match_index]
        row = slot_box.row(align=True)
        row.label(text=f"{position + 1}.")
        row.prop(match, "parameter", text="")
        if slot in _PBR_SCALAR_SLOTS:
            _draw_pbr_channel_buttons(row, match)
        move_up_row = row.row(align=True)
        move_up_row.enabled = position > 0
        move_up = move_up_row.operator(
            SQEX_OT_move_generic_unreal_pbr_slot_match.bl_idname,
            text="",
            icon="TRIA_UP",
        )
        move_up.direction = -1
        move_up.profile_id = profile.profile_id
        move_up.slot = slot
        move_up.match_index = match_index
        move_down_row = row.row(align=True)
        move_down_row.enabled = position < len(indexes) - 1
        move_down = move_down_row.operator(
            SQEX_OT_move_generic_unreal_pbr_slot_match.bl_idname,
            text="",
            icon="TRIA_DOWN",
        )
        move_down.direction = 1
        move_down.profile_id = profile.profile_id
        move_down.slot = slot
        move_down.match_index = match_index
        remove = row.operator(
            SQEX_OT_remove_generic_unreal_pbr_slot_match.bl_idname,
            text="",
            icon="X",
        )
        remove.profile_id = profile.profile_id
        remove.slot = slot
        remove.match_index = match_index


class SQEX_OT_test_generic_unreal_profile(Operator):
    bl_idname = "preferences.sqex_test_generic_unreal_profile"
    bl_label = "Test Profile"
    bl_description = tooltips.PREFERENCES_TEST_GENERIC_PROFILE
    bl_options = {"INTERNAL"}

    profile_id: StringProperty(options={"HIDDEN"})

    def execute(self, _context):
        from ..formats.unreal_mesh import profile_test

        if profile_test.running(self.profile_id):
            profile_test.cancel(self.profile_id)
            return {"FINISHED"}
        preferences = _addon_preferences()
        profile = _generic_profile_by_id(preferences, self.profile_id) if preferences else None
        if profile is None:
            self.report({"ERROR"}, "The selected profile is no longer available.")
            return {"CANCELLED"}
        try:
            profile_test.start(preferences, profile)
        except (ValueError, OSError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        return {"FINISHED"}


class SQEX_OT_edit_generic_unreal_profiles(Operator):
    """Edit one reusable generic Unreal CUE4Parse profile at a time."""

    bl_idname = "preferences.sqex_edit_generic_unreal_profiles"
    bl_label = "Generic Unreal CUE4Parse Profiles"

    profile_id: bpy.props.EnumProperty(
        name="Profile",
        items=_generic_profile_editor_items,
        default=0,
    )

    def invoke(self, context, _event):
        preferences = _addon_preferences()
        profiles = ensure_generic_unreal_profiles(preferences)
        if not profiles:
            return {"CANCELLED"}
        active_profile = preferences.generic_unreal_active_profile
        self.profile_id = next(
            (profile.profile_id for profile in profiles if profile.profile_id == active_profile),
            profiles[0].profile_id,
        )
        return context.window_manager.invoke_props_dialog(self, width=760)

    def draw(self, _context):
        layout = self.layout
        preferences = _addon_preferences()
        # Keep this method read-only.  Blender suppresses the rest of a
        # dialog's layout if an operator mutates preference data while it is
        # drawing, which previously left this popup looking empty.
        profiles = preferences.generic_unreal_profiles if preferences else ()
        if not profiles:
            layout.label(text="Add a profile to begin.", icon="INFO")
            return
        profile = next(
            (item for item in profiles if item.profile_id == self.profile_id),
            profiles[0],
        )
        selector = layout.row(align=True)
        selector.prop(self, "profile_id", text="")
        selector.operator(SQEX_OT_add_generic_unreal_profile.bl_idname, text="", icon="ADD")
        remove = selector.operator(
            SQEX_OT_remove_generic_unreal_profile.bl_idname,
            text="",
            icon="REMOVE",
        )
        remove.profile_id = profile.profile_id

        layout.prop(profile, "name")
        layout.prop(profile, "game_path")
        layout.prop(profile, "game_version")
        _draw_usmap_path(layout, profile, "usmap_path", profile_id=profile.profile_id)
        layout.prop(profile, "aes_key")

        from ..formats.unreal_mesh import profile_test

        testing = profile_test.running(profile.profile_id)
        test = layout.operator(
            SQEX_OT_test_generic_unreal_profile.bl_idname,
            text="Cancel Profile Test" if testing else "Test Profile (Skeletal Mesh)",
            icon="CANCEL" if testing else "VIEWZOOM",
        )
        test.profile_id = profile.profile_id
        if testing:
            layout.label(text="Searching packages for a readable skeletal mesh...", icon="TIME")
        previous = profile_test.RESULTS.get(profile.profile_id)
        if previous:
            if previous[0] == profile_test.configuration(preferences, profile)[2]:
                profile_test.draw_result(layout, previous[1])
            else:
                layout.label(text="Profile settings changed. Run the test again.", icon="INFO")

        mapping_box = layout.box()
        mapping_box.label(text="PBR Slot Mapping")
        mapping_box.label(
            text="The first configured name found in a material wins. Use arrows to set its priority.",
            icon="INFO",
        )
        mapping_box.label(text="Use * for any characters, e.g. BaseColor* or *Normal* (case-insensitive).")
        _draw_pbr_slot_matches(mapping_box, profile, "albedo")
        _draw_pbr_slot_matches(mapping_box, profile, "normal")
        _draw_pbr_slot_matches(mapping_box, profile, "metalness")
        _draw_pbr_slot_matches(mapping_box, profile, "roughness")
        _draw_pbr_slot_matches(mapping_box, profile, "alpha")

    def execute(self, _context):
        """Remember the selected profile only after the dialog is confirmed."""
        preferences = _addon_preferences()
        if preferences is not None:
            preferences.generic_unreal_active_profile = self.profile_id
        return {"FINISHED"}


def _draw_game_path_settings(
    layout,
    preferences,
    profile: game_profiles.GameProfile,
    expanded_property: str,
):
    box = layout.box()
    header = box.row()
    expanded = getattr(preferences, expanded_property)
    header.prop(
        preferences,
        expanded_property,
        text=profile.label,
        icon="TRIA_DOWN" if expanded else "TRIA_RIGHT",
        emboss=False,
    )
    header.label(text=profile.engine_label, icon="PACKAGE")
    if not expanded:
        return box

    box.prop(preferences, profile.install_root_property)
    if profile.usmap_property:
        _draw_usmap_path(box, preferences, profile.usmap_property)
    else:
        box.label(
            text=f"Uses the built-in {profile.engine_label} profile; no .usmap is used.",
            icon="INFO",
        )
    if profile.aes_key_property:
        box.prop(preferences, profile.aes_key_property)
    return box


class SQEX_ImportPreferences(AddonPreferences):
    """Persistent settings shared by all Square Enix game importers."""

    bl_idname = addon_package_name(__package__)

    show_remake_settings: BoolProperty(
        name="Show Remake Intergrade Settings",
        description=tooltips.PREFERENCES_SHOW_REMAKE_SETTINGS,
        default=False,
    )
    show_rebirth_settings: BoolProperty(
        name="Show Rebirth Settings",
        description=tooltips.PREFERENCES_SHOW_REBIRTH_SETTINGS,
        default=False,
    )
    show_crisis_core_settings: BoolProperty(
        name="Show Crisis Core Reunion Settings",
        description=tooltips.PREFERENCES_SHOW_CRISIS_CORE_SETTINGS,
        default=False,
    )
    show_kingdom_hearts_iii_settings: BoolProperty(
        name="Show Kingdom Hearts III Settings",
        description=tooltips.PREFERENCES_SHOW_KINGDOM_HEARTS_III_SETTINGS,
        default=False,
    )
    show_kingdom_hearts_0_2_settings: BoolProperty(
        name="Show Kingdom Hearts 0.2 Settings",
        description=(
            tooltips.PREFERENCES_SHOW_KINGDOM_HEARTS_0_2_SETTINGS
        ),
        default=False,
    )
    oodle_dll: StringProperty(
        name="Oodle DLL",
        description=tooltips.PREFERENCES_OODLE_DLL,
        subtype="FILE_PATH",
        default="",
    )
    generic_unreal_profiles: CollectionProperty(type=SQEX_PG_generic_unreal_profile)
    generic_unreal_profiles_initialized: BoolProperty(default=False, options={"HIDDEN"})
    generic_unreal_active_profile: StringProperty(default="", options={"HIDDEN"})

    remake_install_root: StringProperty(
        name="Remake Intergrade Install Folder",
        description=tooltips.PREFERENCES_REMAKE_INSTALL_ROOT,
        subtype="DIR_PATH",
        default="",
    )
    remake_usmap_path: StringProperty(
        name="Remake Mapping File",
        description=(
            tooltips.PREFERENCES_REMAKE_USMAP_PATH
        ),
        default=str(_detected_remake_usmap) if _detected_remake_usmap.is_file() else "",
    )
    remake_aes_key: StringProperty(
        name="Remake AES Key",
        description=tooltips.PREFERENCES_REMAKE_AES_KEY,
        subtype="PASSWORD",
        default="0x23989837645C9D28BA58072B2076E895B853A7C9E1C5591B814C4FD2A2D7B782",
    )
    rebirth_install_root: StringProperty(
        name="Rebirth Install Folder",
        description=tooltips.PREFERENCES_REBIRTH_INSTALL_ROOT,
        subtype="DIR_PATH",
        default="",
    )
    rebirth_usmap_path: StringProperty(
        name="Rebirth Mapping File",
        description=tooltips.PREFERENCES_REBIRTH_USMAP_PATH,
        default="",
    )
    crisis_core_install_root: StringProperty(
        name="Crisis Core Reunion Install Folder",
        description=tooltips.PREFERENCES_CRISIS_CORE_INSTALL_ROOT,
        subtype="DIR_PATH",
        default="",
    )
    crisis_core_usmap_path: StringProperty(
        name="Crisis Core Mapping File",
        description=tooltips.PREFERENCES_CRISIS_CORE_USMAP_PATH,
        default=(
            str(_detected_crisis_core_usmap)
            if _detected_crisis_core_usmap.is_file()
            else ""
        ),
    )
    kingdom_hearts_iii_install_root: StringProperty(
        name="Kingdom Hearts III Game Folder",
        description=tooltips.PREFERENCES_KINGDOM_HEARTS_III_INSTALL_ROOT,
        subtype="DIR_PATH",
        default="",
    )
    kingdom_hearts_iii_aes_key: StringProperty(
        name="AES Key",
        description=tooltips.PREFERENCES_KINGDOM_HEARTS_III_AES_KEY,
        subtype="PASSWORD",
        default="",
    )
    kingdom_hearts_0_2_install_root: StringProperty(
        name="Kingdom Hearts 0.2 Game Folder",
        description=tooltips.PREFERENCES_KINGDOM_HEARTS_0_2_INSTALL_ROOT,
        subtype="DIR_PATH",
        default="",
    )
    kingdom_hearts_0_2_aes_key: StringProperty(
        name="AES Key",
        description=tooltips.PREFERENCES_KINGDOM_HEARTS_0_2_AES_KEY,
        subtype="PASSWORD",
        default="",
    )
    map_scale_factor: FloatProperty(
        name="Map Scale",
        description=tooltips.PREFERENCES_MAP_SCALE_FACTOR,
        default=0.01,
        min=0.0001,
        max=100.0,
        soft_min=0.001,
        soft_max=10.0,
    )
    offset_mec_opposite_faces: BoolProperty(
        name="Offset MEC Opposite Faces",
        description=(
            tooltips.PREFERENCES_OFFSET_MEC_OPPOSITE_FACES
        ),
        default=True,
    )
    game_texture_root: StringProperty(
        name="Texture Content Root",
        description=tooltips.PREFERENCES_GAME_TEXTURE_ROOT,
        default="",
        subtype="DIR_PATH",
    )
    texture_extension: StringProperty(
        name="Texture Extension",
        description=tooltips.PREFERENCES_TEXTURE_EXTENSION,
        default="dds",
    )
    texture_match_by_filename: BoolProperty(
        name="Match Textures by Filename Only",
        description=(
            tooltips.PREFERENCES_TEXTURE_MATCH_BY_FILENAME
        ),
        default=False,
    )
    last_import_settings_json: StringProperty(
        name="Last Import Settings",
        description=tooltips.PREFERENCES_LAST_IMPORT_SETTINGS_JSON,
        default="{}",
        options={"HIDDEN"},
    )

    def draw(self, _context):
        layout = self.layout
        # Default profiles and legacy settings are prepared when the add-on
        # registers.  Keep this draw method read-only so Blender can always
        # render its preference page and popup editor.
        layout.prop(self, "oodle_dll")

        _draw_game_path_settings(
            layout, self, remake_profile.PROFILE, "show_remake_settings"
        )
        rebirth_box = _draw_game_path_settings(
            layout, self, rebirth_profile.PROFILE, "show_rebirth_settings"
        )
        if self.show_rebirth_settings:
            rebirth_box.prop(self, "map_scale_factor")
            rebirth_box.prop(self, "offset_mec_opposite_faces")
        _draw_game_path_settings(
            layout, self, crisis_core_profile.PROFILE, "show_crisis_core_settings"
        )
        _draw_game_path_settings(
            layout,
            self,
            kingdom_hearts_iii_profile.PROFILE,
            "show_kingdom_hearts_iii_settings",
        )
        _draw_game_path_settings(
            layout,
            self,
            kingdom_hearts_0_2_profile.PROFILE,
            "show_kingdom_hearts_0_2_settings",
        )

        texture_box = layout.box()
        texture_box.label(text="Rebirth Massive Environment Textures (Loose files only. Ignore for package imports.)")
        texture_box.prop(self, "game_texture_root")
        row = texture_box.row()
        row.label(text="Extension:")
        row.prop(self, "texture_extension", text="")
        texture_box.prop(self, "texture_match_by_filename")

        layout.operator(
            SQEX_OT_edit_generic_unreal_profiles.bl_idname,
            text="Edit Generic Unreal CUE4Parse Profiles",
            icon="PREFERENCES",
        )


CLASSES = (
    SQEX_OT_select_usmap,
    SQEX_PG_generic_unreal_slot_match,
    SQEX_PG_generic_unreal_profile,
    SQEX_OT_add_generic_unreal_profile,
    SQEX_OT_remove_generic_unreal_profile,
    SQEX_OT_add_generic_unreal_pbr_slot_match,
    SQEX_OT_remove_generic_unreal_pbr_slot_match,
    SQEX_OT_move_generic_unreal_pbr_slot_match,
    SQEX_OT_test_generic_unreal_profile,
    SQEX_OT_edit_generic_unreal_profiles,
    SQEX_ImportPreferences,
)
