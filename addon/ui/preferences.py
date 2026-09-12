"""Persistent Blender preferences for all supported game profiles."""

from __future__ import annotations

from pathlib import Path

from bpy.props import BoolProperty, FloatProperty, StringProperty
from bpy.types import AddonPreferences

from ..core import profiles as game_profiles
from ..games.crisis_core import profile as crisis_core_profile
from ..games.rebirth import profile as rebirth_profile
from ..games.remake import profile as remake_profile


_detected_remake_usmap = Path.home() / "Downloads" / "Mappings.usmap"
_detected_crisis_core_usmap = Path.home() / "Downloads" / "Crisis Core.usmap"


def _draw_game_path_settings(layout, preferences, profile: game_profiles.GameProfile):
    box = layout.box()
    header = box.row()
    header.label(text=profile.label)
    header.label(text=profile.engine_label, icon="PACKAGE")
    box.prop(preferences, profile.install_root_property)
    if profile.usmap_property:
        box.prop(preferences, profile.usmap_property)
    else:
        box.label(text="Uses the built-in UE 4.18 profile; no .usmap is used.", icon="INFO")
    if profile.oodle_property:
        box.prop(preferences, profile.oodle_property)
    if profile.bundled_oodle_relative_path:
        box.label(
            text="Leave the Oodle override blank to detect the DLL from this installation.",
            icon="INFO",
        )
    return box


class FF7R_ImportPreferences(AddonPreferences):
    """Persistent settings shared by all FF7R importers."""

    bl_idname = __package__.split(".", 1)[0]

    remake_install_root: StringProperty(
        name="Remake Intergrade Install Folder",
        description="FINAL FANTASY VII REMAKE INTERGRADE installation containing End/Content/Paks",
        subtype="DIR_PATH",
        default="",
    )
    remake_oodle_dll: StringProperty(
        name="Oodle DLL Override",
        description=(
            "Optional compatible oo2core DLL. Leave blank to use the copy under "
            "the configured Remake installation"
        ),
        subtype="FILE_PATH",
        default="",
    )
    remake_usmap_path: StringProperty(
        name="Remake Mapping File",
        description=(
            "UE 4.18 mapping used to deserialize Remake's unversioned cooked properties"
        ),
        subtype="FILE_PATH",
        default=str(_detected_remake_usmap) if _detected_remake_usmap.is_file() else "",
    )
    rebirth_install_root: StringProperty(
        name="Rebirth Install Folder",
        description="FINAL FANTASY VII REBIRTH installation containing End/Content/Paks",
        subtype="DIR_PATH",
        default="",
    )
    rebirth_usmap_path: StringProperty(
        name="Rebirth Mapping File",
        description="UE 4.26 .usmap used by CUE4Parse to deserialize Rebirth packages",
        subtype="FILE_PATH",
        default="",
    )
    rebirth_oodle_dll: StringProperty(
        name="Oodle DLL",
        description=(
            "Compatible oo2core DLL used to decompress package content "
            "(FF7 Remake Intergrade ships a compatible copy)"
        ),
        subtype="FILE_PATH",
        default="",
    )
    crisis_core_install_root: StringProperty(
        name="Crisis Core Reunion Install Folder",
        description="CRISIS CORE FINAL FANTASY VII REUNION installation containing CCFF7R/Content/Paks",
        subtype="DIR_PATH",
        default="",
    )
    crisis_core_usmap_path: StringProperty(
        name="Crisis Core Mapping File",
        description="UE 4.27 .usmap used by CUE4Parse to deserialize Crisis Core packages",
        subtype="FILE_PATH",
        default=(
            str(_detected_crisis_core_usmap)
            if _detected_crisis_core_usmap.is_file()
            else ""
        ),
    )
    crisis_core_oodle_dll: StringProperty(
        name="Oodle DLL",
        description="Compatible oo2core DLL used to decompress Crisis Core package content",
        subtype="FILE_PATH",
        default="",
    )
    map_scale_factor: FloatProperty(
        name="Map Scale",
        description="Uniform coordinate scale applied to package map actors and Massive Environment geometry",
        default=0.01,
        min=0.0001,
        max=100.0,
        soft_min=0.001,
        soft_max=10.0,
    )
    offset_mec_opposite_faces: BoolProperty(
        name="Offset MEC Opposite Faces",
        description=(
            "Directly offset overlapping opposite-facing Massive Environment faces "
            "by 0.0005 at 0.01 scale during import"
        ),
        default=True,
    )
    game_texture_root: StringProperty(
        name="Texture Content Root",
        description="Local folder corresponding to Unreal /Game texture paths",
        default="",
        subtype="DIR_PATH",
    )
    texture_extension: StringProperty(
        name="Texture Extension",
        description="File extension used when resolving /Game texture paths",
        default="dds",
    )
    texture_match_by_filename: BoolProperty(
        name="Match Textures by Filename Only",
        description=(
            "Ignore /Game/ path hierarchy and match indexed texture files by filename"
        ),
        default=False,
    )
    last_import_settings_json: StringProperty(
        name="Last Import Settings",
        description="Internal JSON store for remembered importer dialog settings",
        default="{}",
        options={"HIDDEN"},
    )

    def draw(self, _context):
        layout = self.layout
        _draw_game_path_settings(layout, self, remake_profile.PROFILE)
        rebirth_box = _draw_game_path_settings(layout, self, rebirth_profile.PROFILE)
        rebirth_box.prop(self, "map_scale_factor")
        rebirth_box.prop(self, "offset_mec_opposite_faces")
        _draw_game_path_settings(layout, self, crisis_core_profile.PROFILE)

        texture_box = layout.box()
        texture_box.label(text="Rebirth Massive Environment Textures")
        texture_box.prop(self, "game_texture_root")
        row = texture_box.row()
        row.label(text="Extension:")
        row.prop(self, "texture_extension", text="")
        texture_box.prop(self, "texture_match_by_filename")


CLASSES = (FF7R_ImportPreferences,)
