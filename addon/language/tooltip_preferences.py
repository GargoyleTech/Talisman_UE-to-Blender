"""English hover tooltips. Edit text here; keep variable names stable."""

# Edit > Preferences > Add-ons > Talisman.
# Game paths, generic CUE4Parse profiles, and PBR texture mappings.

# -----------------------------------------------------------------------------
# PBR texture channel dropdowns
# -----------------------------------------------------------------------------
# addon/ui/preferences.py (_CHANNEL_ITEMS_R)
PREFERENCES_CHANNEL_R = ('Use the red channel')
# addon/ui/preferences.py (_CHANNEL_ITEMS_G)
PREFERENCES_CHANNEL_G = ('Use the green channel')
# addon/ui/preferences.py (_CHANNEL_ITEMS_B)
PREFERENCES_CHANNEL_B = ('Use the blue channel')
# addon/ui/preferences.py (_CHANNEL_ITEMS_A)
PREFERENCES_CHANNEL_A = ('Use the alpha channel')

# -----------------------------------------------------------------------------
# PBR texture slot dropdowns
# -----------------------------------------------------------------------------
# addon/ui/preferences.py (_PBR_SLOT_ITEMS_albedo)
PREFERENCES_PBR_SLOT_ALBEDO = ('Connect to Principled BSDF Base Color')
# addon/ui/preferences.py (_PBR_SLOT_ITEMS_normal)
PREFERENCES_PBR_SLOT_NORMAL = ('Connect through a Normal Map node')
# addon/ui/preferences.py (_PBR_SLOT_ITEMS_metalness)
PREFERENCES_PBR_SLOT_METALNESS = ('Connect to Principled BSDF Metallic')
# addon/ui/preferences.py (_PBR_SLOT_ITEMS_roughness)
PREFERENCES_PBR_SLOT_ROUGHNESS = ('Connect to Principled BSDF Roughness')
# addon/ui/preferences.py (_PBR_SLOT_ITEMS_alpha)
PREFERENCES_PBR_SLOT_ALPHA = ('Connect to Principled BSDF Alpha')
# addon/ui/preferences.py (_PBR_SLOT_ITEMS_emission)
PREFERENCES_PBR_SLOT_EMISSION = ('Connect to Principled BSDF Emission Color and set Emission Strength to 1.0')

# -----------------------------------------------------------------------------
# Generic CUE4Parse profile editor
# -----------------------------------------------------------------------------
# addon/ui/preferences.py (_GENERIC_PROFILE_EDITOR_ITEMS_)
PREFERENCES_GENERIC_PROFILE_EDITOR_ITEMS = ('Add a profile with the + button')
# addon/ui/preferences.py (generic_unreal_slot_match_parameter)
PREFERENCES_SLOT_MATCH_PARAMETER = ('Unreal texture-parameter name, ignoring case; * matches zero or more characters (e.g. BaseColor* or *Normal*). The first matching parameter in material order is used')
# addon/ui/preferences.py (generic_unreal_profile_name)
PREFERENCES_PROFILE_NAME = ('Label shown by the generic Unreal mesh and UMAP importers')
# addon/ui/preferences.py (generic_unreal_profile_game_path)
PREFERENCES_PROFILE_GAME_PATH = ('Folder containing pak or IoStore packages; subfolders are searched recursively')
# addon/ui/preferences.py (generic_unreal_profile_game_version)
PREFERENCES_PROFILE_GAME_VERSION = ('Engine version or game profile supported by the bundled CUE4Parse runtime')
# addon/ui/preferences.py (generic_unreal_profile_usmap_path)
PREFERENCES_PROFILE_USMAP_PATH = ('Optional cooked property mappings; required for games using unversioned properties. n/a means this game does not need mappings and is treated as an empty field')
# addon/ui/preferences.py (generic_unreal_profile_aes_key)
PREFERENCES_PROFILE_AES_KEY = ("Optional hexadecimal AES key used to decrypt this game's packages. n/a means no key is needed and is treated as an empty field")
PREFERENCES_TEST_GENERIC_PROFILE = ('Search the selected folder for a readable skeletal mesh and check AES encryption and .usmap mappings; imports no objects. Click again to cancel a running test')
PREFERENCES_GENERATE_REBIRTH_TEXTURE_HASHES = ('Generate an optional texture hash lookup from your Rebirth game files for loose Massive Environment imports. Saves in Blender user data and survives add-on updates. Scans package headers without extracting textures; may take several minutes. Click again to cancel')
PREFERENCES_RESET_GENERIC_PROFILE = ('Restore this profile to the current shipped template, including its name, game version, mappings, AES key and material mappings. Clears the game folder and any entered key, and cancels the profile test')
# addon/ui/preferences.py (generic_unreal_profile_pbr_albedo_parameter)
PREFERENCES_PROFILE_PBR_ALBEDO_PARAMETER = ('Texture parameter name to connect to Principled BSDF Base Color')
# addon/ui/preferences.py (generic_unreal_profile_pbr_normal_parameter)
PREFERENCES_PROFILE_PBR_NORMAL_PARAMETER = ('Texture parameter name to connect through a Normal Map node')
# addon/ui/preferences.py (generic_unreal_profile_pbr_metalness_parameter)
PREFERENCES_PROFILE_PBR_METALNESS_PARAMETER = ('Texture parameter name to connect to Principled BSDF Metallic')
# addon/ui/preferences.py (generic_unreal_profile_pbr_roughness_parameter)
PREFERENCES_PROFILE_PBR_ROUGHNESS_PARAMETER = ('Texture parameter name to connect to Principled BSDF Roughness')
# addon/ui/preferences.py (generic_unreal_profile_pbr_alpha_parameter)
PREFERENCES_PROFILE_PBR_ALPHA_PARAMETER = ('Texture parameter name to connect to Principled BSDF Alpha')

# -----------------------------------------------------------------------------
# Game settings sections and paths
# -----------------------------------------------------------------------------
# addon/ui/preferences.py (SQEX_ImportPreferences_show_remake_settings)
PREFERENCES_SHOW_REMAKE_SETTINGS = ('Show paths and import settings for Final Fantasy VII Remake Intergrade')
# addon/ui/preferences.py (SQEX_ImportPreferences_show_rebirth_settings)
PREFERENCES_SHOW_REBIRTH_SETTINGS = ('Show paths and import settings for Final Fantasy VII Rebirth')
# addon/ui/preferences.py (SQEX_ImportPreferences_show_crisis_core_settings)
PREFERENCES_SHOW_CRISIS_CORE_SETTINGS = ('Show paths and import settings for Crisis Core Final Fantasy VII Reunion')
# addon/ui/preferences.py (SQEX_ImportPreferences_show_kingdom_hearts_iii_settings)
PREFERENCES_SHOW_KINGDOM_HEARTS_III_SETTINGS = ('Show paths and import settings for Kingdom Hearts III')
# addon/ui/preferences.py (SQEX_ImportPreferences_show_kingdom_hearts_0_2_settings)
PREFERENCES_SHOW_KINGDOM_HEARTS_0_2_SETTINGS = ('Show paths and import settings for Kingdom Hearts 0.2 Birth by Sleep -A fragmentary passage-')
# addon/ui/preferences.py (SQEX_ImportPreferences_oodle_dll)
PREFERENCES_OODLE_DLL = ('Compatible oo2core DLL shared by every CUE4Parse game importer')
# addon/ui/preferences.py (SQEX_ImportPreferences_remake_install_root)
PREFERENCES_REMAKE_INSTALL_ROOT = ('FINAL FANTASY VII REMAKE INTERGRADE installation containing End/Content/Paks')
# addon/ui/preferences.py (SQEX_ImportPreferences_remake_usmap_path)
PREFERENCES_REMAKE_USMAP_PATH = ("UE 4.18 mapping used to deserialize Remake's unversioned cooked properties")
# addon/ui/preferences.py (SQEX_ImportPreferences_remake_aes_key)
PREFERENCES_REMAKE_AES_KEY = ('AES key used to decrypt FINAL FANTASY VII REMAKE INTERGRADE packages')
# addon/ui/preferences.py (SQEX_ImportPreferences_rebirth_install_root)
PREFERENCES_REBIRTH_INSTALL_ROOT = ('FINAL FANTASY VII REBIRTH installation containing End/Content/Paks')
# addon/ui/preferences.py (SQEX_ImportPreferences_rebirth_usmap_path)
PREFERENCES_REBIRTH_USMAP_PATH = ('UE 4.26 .usmap used by CUE4Parse to deserialize Rebirth packages')
# addon/ui/preferences.py (SQEX_ImportPreferences_rebirth_import_all_material_switches)
PREFERENCES_REBIRTH_IMPORT_ALL_MATERIAL_SWITCHES = (
    'Keep every supported switch on imported Rebirth surface, eye and hair materials. '
    'Unused switches start disabled but remain editable, with their drivers, numeric '
    'controls and shader paths retained for enabling features after import'
)
# addon/ui/preferences.py (SQEX_ImportPreferences_rebirth_replace_empty_image_textures)
PREFERENCES_REBIRTH_REPLACE_EMPTY_IMAGE_TEXTURES = (
    'Replace empty Rebirth RMI image texture nodes with RGB constants. Disabled '
    'by default: keep the image nodes muted and store UE colors on the texture '
    "Mix's B input. Missing UE colors use the role's neutral default"
)
# addon/ui/preferences.py (SQEX_ImportPreferences_crisis_core_install_root)
PREFERENCES_CRISIS_CORE_INSTALL_ROOT = ('CRISIS CORE FINAL FANTASY VII REUNION installation containing CCFF7R/Content/Paks')
# addon/ui/preferences.py (SQEX_ImportPreferences_crisis_core_usmap_path)
PREFERENCES_CRISIS_CORE_USMAP_PATH = ('UE 4.27 .usmap used by CUE4Parse to deserialize Crisis Core packages')
# addon/ui/preferences.py (SQEX_ImportPreferences_kingdom_hearts_iii_install_root)
PREFERENCES_KINGDOM_HEARTS_III_INSTALL_ROOT = ('Steam folder containing KINGDOM HEARTS III/Content/Paks')
# addon/ui/preferences.py (SQEX_ImportPreferences_kingdom_hearts_iii_aes_key)
PREFERENCES_KINGDOM_HEARTS_III_AES_KEY = ('AES key required to decrypt Kingdom Hearts III package files')
# addon/ui/preferences.py (SQEX_ImportPreferences_kingdom_hearts_0_2_install_root)
PREFERENCES_KINGDOM_HEARTS_0_2_INSTALL_ROOT = ('KINGDOM HEARTS 0.2 Birth by Sleep folder containing Content/Paks')
# addon/ui/preferences.py (SQEX_ImportPreferences_kingdom_hearts_0_2_aes_key)
PREFERENCES_KINGDOM_HEARTS_0_2_AES_KEY = ('AES key required to decrypt Kingdom Hearts 0.2 package files')

# -----------------------------------------------------------------------------
# Default import options
# -----------------------------------------------------------------------------
# addon/ui/preferences.py (SQEX_ImportPreferences_map_scale_factor)
PREFERENCES_MAP_SCALE_FACTOR = ('Uniform coordinate scale applied to package map actors and Massive Environment geometry')
# addon/ui/preferences.py (SQEX_ImportPreferences_offset_mec_opposite_faces)
PREFERENCES_OFFSET_MEC_OPPOSITE_FACES = ('Directly offset overlapping opposite-facing Massive Environment faces by 0.0005 at 0.01 scale during import')
# addon/ui/preferences.py (SQEX_ImportPreferences_game_texture_root)
PREFERENCES_GAME_TEXTURE_ROOT = ('Local folder corresponding to Unreal /Game texture paths')
# addon/ui/preferences.py (SQEX_ImportPreferences_texture_extension)
PREFERENCES_TEXTURE_EXTENSION = ('File extension used when resolving /Game texture paths')
# addon/ui/preferences.py (SQEX_ImportPreferences_texture_match_by_filename)
PREFERENCES_TEXTURE_MATCH_BY_FILENAME = ('Ignore /Game/ path hierarchy and match indexed texture files by filename')
# addon/ui/preferences.py (SQEX_ImportPreferences_last_import_settings_json)
PREFERENCES_LAST_IMPORT_SETTINGS_JSON = ('Internal JSON store for remembered importer dialog settings')
