"""English import tooltips. Edit text here; keep variable names stable."""

# -----------------------------------------------------------------------------
# Shared Import
# -----------------------------------------------------------------------------

# Shared mesh / skeleton import dialogs, package browser, and texture options.
# Used by File > Import > Talisman across all supported games.
# Shared dropdown choices and identical controls reuse these variables.

# -----------------------------------------------------------------------------
# Mesh import > Offset Faces dropdown
# -----------------------------------------------------------------------------
# addon/formats/unreal_package/options.py (OFFSET_FACES_ITEMS_OFFSET_FACES_NONE)
SHARED_OFFSET_FACES_NONE = ('Do not offset overlapping opposite-facing faces')
# addon/formats/unreal_package/options.py (OFFSET_FACES_ITEMS_OFFSET_FACES_BAKED)
SHARED_OFFSET_FACES_BAKED = ('Offset opposite-facing vertices during mesh import')
# addon/formats/unreal_package/options.py (OFFSET_FACES_ITEMS_OFFSET_FACES_MODIFIER)
SHARED_OFFSET_FACES_MODIFIER = ('Add the Retrilogy Alpha Displace modifier and vertex-group mask')

# -----------------------------------------------------------------------------
# Skeleton / Skeletal mesh > Attachment Sockets dropdown
# -----------------------------------------------------------------------------
# addon/formats/unreal_package/options.py (ATTACHMENT_SOCKETS_ITEMS_ATTACHMENT_SOCKETS_NONE)
SHARED_ATTACHMENT_SOCKETS_NONE = ('Do not create attachment socket objects or bones')
# addon/formats/unreal_package/options.py (ATTACHMENT_SOCKETS_ITEMS_ATTACHMENT_SOCKETS_EMPTIES)
SHARED_ATTACHMENT_SOCKETS_EMPTIES = ('Create bone-parented Empty objects for attachment sockets')
# addon/formats/unreal_package/options.py (ATTACHMENT_SOCKETS_ITEMS_ATTACHMENT_SOCKETS_BONES)
SHARED_ATTACHMENT_SOCKETS_BONES = ('Create hidden non-deforming bones for attachment sockets')

# -----------------------------------------------------------------------------
# Mesh / Skeleton import > Face Forward dropdown
# -----------------------------------------------------------------------------
# addon/formats/unreal_package/options.py (FACE_FORWARD_ITEMS_FACE_FORWARD_UNREAL)
SHARED_FACE_FORWARD_UNREAL = ("Keep the imported asset facing Unreal's +X axis. Incompatible with Blender tools related to armature symmetry.")
# addon/formats/unreal_package/options.py (FACE_FORWARD_ITEMS_FACE_FORWARD_BLENDER)
SHARED_FACE_FORWARD_BLENDER = ("Rotate the imported asset to face Blender's -Y axis, benefitting from Blender tools related to armature symmetry.")

# -----------------------------------------------------------------------------
# Skeletal mesh options (common UE4 controls and supported game-specific extras)
# -----------------------------------------------------------------------------
# addon/ui/mesh_importer.py (skeletal_import_kdi)
SHARED_SKELETAL_IMPORT_KDI = ("Import the SkeletalMesh's associated Square Enix KineDriver rig onto the new armature to automatically set up corrective bones.")
# addon/ui/mesh_importer.py (skeletal_preserve_ue_axis_order)
SHARED_SKELETAL_PRESERVE_UE_AXIS_ORDER = ('Keep the source bone rotations, with local X pointing down Unreal bone chains. Disable to reorient bones so Blender local Y points down the chains. Bone heads and mesh geometry are unchanged.')
# addon/ui/mesh_importer.py (skeletal_connect_bones)
SHARED_SKELETAL_CONNECT_BONES = ("Connect imported bones that are close to their parent's tail. Enables the use of Blender's Auto-IK function.")
# addon/ui/mesh_importer.py (skeletal_import_mesh_referenced_bones_only)
SHARED_SKELETAL_IMPORT_MESH_REFERENCED_BONES_ONLY = ("Build from this mesh's reference skeleton and required parents instead of its linked master Skeleton.")
# addon/ui/mesh_importer.py (skeletal_create_variant_bone_collections)
SHARED_SKELETAL_CREATE_VARIANT_BONE_COLLECTIONS = ('Create a bone collection for each SkeletalMesh variant with uniquely weighted bones.')
# addon/ui/mesh_importer.py (skeletal_attachment_sockets)
SHARED_SKELETAL_ATTACHMENT_SOCKETS = ('Import native Unreal attachment sockets as bone-parented empties, hidden non-deforming bones, or neither.')
SHARED_SKELETAL_BUILD_SKELETON = ('Build an armature from the mesh reference skeleton or its linked Unreal Skeleton asset.')
SHARED_SKELETAL_BIND_ACTIVE_ARMATURE = ('Bind the imported mesh to the active armature when building a new skeleton is disabled.')
# addon/ui/mesh_importer.py (skeletal_setup_naive_ik)
SHARED_SKELETAL_SETUP_NAIVE_IK = ('Create hand/foot targets and elbow/knee pole controls.')
# addon/ui/mesh_importer.py (skeletal_create_limbal_bone)
SHARED_SKELETAL_CREATE_LIMBAL_BONE = ('Create a centered eye shadow ring controller for compatible eye materials.')
# addon/ui/mesh_importer.py (skeletal_generate_mouth_controls)
SHARED_SKELETAL_GENERATE_MOUTH_CONTROLS = ('Add jaw and smooth lip controls for recognized human faces.')
# addon/ui/mesh_importer.py (mesh_importer_description)
SHARED_UNAVAILABLE_SKELETAL_OPTION = ('Not available for {game_label}. {option_description}')

# -----------------------------------------------------------------------------
# Map import dialogs > Texture Memory
# -----------------------------------------------------------------------------
# addon/ui/textures.py (max_texture_resolution)
SHARED_MAX_TEXTURE_RESOLUTION = ('Maximum width or height for newly imported textures, in powers of two; 0 keeps the original resolution. Existing higher-resolution images are retained. Older arbitrary limits round down to a power of two')
# addon/ui/textures.py (texture_mip_offset)
SHARED_TEXTURE_MIP_OFFSET = ('Reduce every texture by available mip levels: -1 halves each dimension, -2 quarters it. The resolution cap and offset both apply; the smaller result wins')

# -----------------------------------------------------------------------------
# Mesh import dialogs > Common controls
# -----------------------------------------------------------------------------
# addon/games/conventional_mesh.py (virtual_path)
SHARED_STATIC_MESH_SEARCH_PATH = ('Type any part of an indexed {definition_game_name} StaticMesh package path')
# addon/games/conventional_mesh.py (offset_opposite_faces)
# addon/games/rebirth/importers/packages.py (import_static_mesh_game_packages_offset_opposite_faces)
# addon/games/rebirth/importers/packages.py (import_skeletal_mesh_game_packages_offset_opposite_faces)
SHARED_OFFSET_OPPOSITE_FACES = ('Choose how overlapping faces with opposite-facing normals are handled')
# addon/games/conventional_mesh.py (face_y_forward)
# addon/games/rebirth/importers/packages.py (import_static_mesh_game_packages_face_y_forward)
SHARED_FACE_Y_FORWARD = ("Choose the imported mesh's forward axis to either preserve UE convention or adapt to Blender convention")
# addon/games/conventional_mesh.py (conventional_mesh_description)
SHARED_STATIC_MESH_IMPORT = ('Import a {definition_profile_engine_label} StaticMesh from {definition_game_name} packages')
# addon/games/conventional_mesh.py (conventional_mesh_description)
SHARED_SKELETAL_MESH_IMPORT = ('Import a {definition_game_name} SkeletalMesh and its linked Skeleton')

# -----------------------------------------------------------------------------
# All package browsers > Search and selection controls
# -----------------------------------------------------------------------------
# addon/games/package_browser.py (package_asset_browser_filter_text)
SHARED_PACKAGE_ASSET_BROWSER_FILTER_TEXT = ('Filter assets by space-separated terms anywhere in their package path')
# addon/games/package_browser.py (package_asset_selection_mode_SELECT)
SHARED_PACKAGE_ASSET_SELECTION_MODE_SELECT = ('Select every visible asset')
# addon/games/package_browser.py (package_asset_selection_mode_CLEAR)
SHARED_PACKAGE_ASSET_SELECTION_MODE_CLEAR = ('Clear the complete batch selection')
# addon/games/package_browser.py (package_asset_selection_mode_INVERT)
SHARED_PACKAGE_ASSET_SELECTION_MODE_INVERT = ('Invert visible asset selections')

# Shared coordinate scale in mesh, map, and cutscene dialogs.
# addon/games/conventional_map.py (attributes_scale_factor)
# addon/games/conventional_mesh.py (scale_factor)
# addon/games/kingdom_hearts/importers/matinee.py (attributes_scale_factor)
# addon/games/rebirth/importers/packages.py (import_static_mesh_game_packages_scale_factor)
# addon/games/rebirth/importers/packages.py (import_skeletal_mesh_game_packages_scale_factor)
SHARED_SCALE_FACTOR = ('Convert Unreal centimeters to Blender units')

# -----------------------------------------------------------------------------
# Animation Import
# -----------------------------------------------------------------------------

# File > Import > Talisman > each game > Animation.
# Shared animation importer used by the supported game menus.
# addon/games/conventional_animation.py (conventional_animation_description)
ANIMATION_IMPORT = ('Import compatible {game_name} AnimSequence assets as Blender Actions')

# -----------------------------------------------------------------------------
# Generic Import
# -----------------------------------------------------------------------------

# File > Import > Talisman > Generic UE4.
# Mesh / UMAP, animation, sequence binding, and LevelSequence dialogs.
# addon/formats/unreal_mesh/animations.py (import_generic_unreal_animation_description)
GENERIC_ANIMATION_DESCRIPTION = ('Import AnimSequence clips for a selected generic package armature as separate Actions')
# addon/formats/unreal_mesh/animations.py (import_generic_unreal_animation_virtual_path)
# addon/formats/unreal_mesh/sequences.py (import_generic_unreal_sequence_virtual_path)
GENERIC_PACKAGE_PATH = ('Optional exact package path instead of browser selection')
# addon/formats/unreal_mesh/animations.py (import_generic_unreal_animation_scale_factor)
GENERIC_ANIMATION_SCALE_FACTOR = ('Must match the scale used when importing this armature; older imports default to 0.01')
# addon/formats/unreal_mesh/importer.py (_PROFILE_ITEMS_profile.profile_id)
GENERIC_PROFILE_SETTINGS = ('Reusable game, CUE4Parse version, mappings, and AES key settings')
# addon/formats/unreal_mesh/importer.py (_PROFILE_ITEMS_)
GENERIC_ADD_PROFILE = ('Add a profile in the add-on preferences')
# addon/formats/unreal_mesh/importer.py (cue4parse_profile)
GENERIC_IMPORT_CUE4PARSE_PROFILE = ('Shared game configuration from the add-on preferences')
# addon/formats/unreal_mesh/importer.py (path_filter)
GENERIC_IMPORT_PATH_FILTER = ('Optional package-path substring to limit indexing on large games')
# addon/formats/unreal_mesh/importer.py (mesh_kind_STATIC)
GENERIC_IMPORT_MESH_KIND_STATIC = ('Import Unreal static meshes, including native Nanite geometry')
# addon/formats/unreal_mesh/importer.py (mesh_kind_SKELETAL)
GENERIC_IMPORT_MESH_KIND_SKELETAL = ('Import conventional Unreal skinned meshes and reference skeletons')
# addon/formats/unreal_mesh/importer.py (mesh_kind_UMAP)
GENERIC_IMPORT_MESH_KIND_UMAP = ('Import placed mesh components and lights from selected maps')
# addon/formats/unreal_mesh/importer.py (index_generic_unreal_description)
GENERIC_INDEX_DESCRIPTION = ('Mount packages using the dialog settings and index the selected asset type')
# addon/formats/unreal_mesh/importer.py (import_generic_unreal_mesh_description)
GENERIC_MESH_DESCRIPTION = ('Import Unreal meshes or maps with unlinked material texture nodes')
# addon/formats/unreal_mesh/importer.py (import_generic_unreal_mesh_virtual_path)
GENERIC_MESH_VIRTUAL_PATH = ('Optional mounted or /Game asset path for direct/scripted imports')
# addon/formats/unreal_mesh/importer.py (import_generic_unreal_mesh_build_skeleton)
GENERIC_MESH_BUILD_SKELETON = ("Build the mesh's own reference skeleton and bind its weights")
# addon/formats/unreal_mesh/sequences.py (generic_sequence_binding_target)
GENERIC_SEQUENCE_BINDING_TARGET = ('Optional explicit object binding; leave empty for automatic template/level resolution')
# addon/formats/unreal_mesh/sequences.py (inspect_generic_sequence_bindings_description)
GENERIC_SEQUENCE_BINDINGS_DESCRIPTION = ('Read the selected sequence and nested shots so existing scene objects can be bound explicitly')
# addon/formats/unreal_mesh/sequences.py (import_generic_unreal_sequence_description)
GENERIC_SEQUENCE_DESCRIPTION = ('Import stock LevelSequences with nested shots, actors, cameras and skeletal animation; multiple selections create separate Blender scenes')
# addon/formats/unreal_mesh/sequences.py (import_generic_unreal_sequence_load_missing)
GENERIC_SEQUENCE_LOAD_MISSING = ('Read referenced level actors and Blueprint component defaults, without executing Blueprint scripts or importing entire maps')
# addon/formats/unreal_mesh/sequences.py (import_generic_unreal_sequence_replace_existing)
GENERIC_SEQUENCE_REPLACE_EXISTING = ('Mute existing NLA tracks and retain the old active Action as unused data; otherwise occupied animation targets are skipped')
# addon/formats/unreal_mesh/sequences.py (import_generic_unreal_sequence_binding_overrides)
GENERIC_SEQUENCE_BINDING_OVERRIDES = ('Scripted JSON mapping from instance:GUID (or GUID) to existing scene object names')

GENERIC_NANITE_MODE = ('Choose native Nanite detail or the conventional fallback mesh; ordinary non-Nanite meshes use their conventional geometry')
GENERIC_NANITE_AUTO = ('Import the finest stored Nanite triangles when available; use the fallback mesh if a limit or decoding error prevents native import, and report the reason')
GENERIC_NANITE_NATIVE = ('Require complete native geometry for Nanite assets; exceeding a limit or encountering unsupported data fails that mesh instead of substituting its fallback')
GENERIC_NANITE_FALLBACK = ('Import the conventional fallback LOD, which can be much less detailed than native Nanite geometry')
GENERIC_NANITE_TRIANGLES = ('Maximum native triangles per unique source mesh, before map instancing. 0 allows full stored detail. Auto uses the fallback if exceeded; Native fails that mesh. This does not decimate or truncate geometry')
GENERIC_NANITE_CACHE = ('Target decoded-page cache size per mesh in MiB; 0 removes the cache target. Evicted vertex references use temporary disk storage. Dependencies may temporarily exceed the target. This controls decoding cache only, not total Blender or import memory')

# -----------------------------------------------------------------------------
# Map Import
# -----------------------------------------------------------------------------

# File > Import > Talisman > Remake / Crisis Core / Kingdom Hearts > UMAP.
# Shared conventional map import dialogs.
# addon/formats/ue_map/package_importer.py (description)
MAP_DESCRIPTION = ('Import placed meshes and lights from a {game_label} UMAP')
# addon/formats/ue_map/package_importer.py (virtual_path)
MAP_VIRTUAL_PATH = ('Mounted UMAP path for scripted or redo-panel imports')
# addon/formats/ue_map/package_importer.py (import_models)
MAP_IMPORT_MODELS = ('Create placed static and skeletal meshes, editable text, flat textured decal planes, and cameras')
MAP_IMPORT_LANDSCAPES = ('Reconstruct Landscape terrain from cooked height and XY-offset textures, including holes and editable paint weights. Separate from Rebirth Massive Environment')
MAP_LANDSCAPE_LOD = ('Terrain detail level: zero uses the full cooked grid. Higher levels reduce geometry while preserving component endpoints. The vertex budget can raise this level for a large map')
MAP_LANDSCAPE_BUDGET = ('Maximum terrain vertices per map. The importer raises terrain LOD uniformly to fit this budget and reports the selected level. Zero keeps the requested LOD without a budget. Separate streaming maps may choose different levels')
MAP_LANDSCAPE_PREVIEW = ('Display paint layers with stable diagnostic colors. All layer weights are preserved with this option off. This is a layer preview, not the original Unreal landscape material')
# addon/formats/ue_map/package_importer.py and legacy generic operator (import_splines)
MAP_IMPORT_SPLINES = ('Create editable curves from authored spline paths and spline-mesh centerlines, including native game subclasses. Retains control points, tangents, loop state, and source deformation settings for later use')
# addon/formats/ue_map/package_importer.py (import_lights)
MAP_IMPORT_LIGHTS = ('Create placed point, spot, rectangular area, and sun lights')
# addon/formats/ue_map/package_importer.py (exposure)
# addon/games/rebirth/importers/packages.py (import_mec_game_packages_exposure)
MAP_EXPOSURE = ('Light exposure in stops; +1 doubles brightness. Uses the native light Exposure field when available, otherwise scales power')
# addon/formats/ue_map/package_importer.py (attenuation_radius_mult)
# addon/games/rebirth/importers/packages.py (import_mec_game_packages_attenuation_radius_mult)
MAP_ATTENUATION_RADIUS_MULT = ('Multiplier applied to imported Unreal light attenuation radii')
# addon/formats/ue_map/package_importer.py (import_light_probes)
MAP_IMPORT_LIGHT_PROBES = ('Create editable Eevee light probes for sphere and box reflection captures. Box capture offsets are stored but left unapplied for manual adjustment')
# addon/formats/ue_map/package_importer.py (always_cast_shadows)
MAP_ALWAYS_CAST_SHADOWS = ('Force imported lights to cast shadows')
MAP_BAKE_LIGHT_PARAMETERS = ('Make non-animated lights directly editable by replacing their parameter drivers with evaluated static values. Keeps UE attenuation nodes and skips animated lights')
MAP_RECURSIVE_IMPORT = ('Also import referenced streaming sublevels recursively, visiting each map once')
MAP_IMPORT_TEXTURES = ('Load and pack textures referenced by imported models. Supported DDS textures retain their compressed format')
MAP_IMPORT_POINT_LIGHTS = ('Create placed point lights')
MAP_IMPORT_SPOT_LIGHTS = ('Create placed spot lights')
MAP_IMPORT_RECT_LIGHTS = ('Create rectangular Blender area lights from Unreal RectLight components')
MAP_IMPORT_DIRECTIONAL_LIGHTS = ('Create Blender sun lights from Unreal DirectionalLight components')

# -----------------------------------------------------------------------------
# Loose Map Import
# -----------------------------------------------------------------------------

# File > Import > Talisman > FF7R > Massive Environment UMAP (Loose files).
# File picker settings, texture paths, lights, and level of detail.
# addon/formats/mec/importer.py (import_mec_umap_description)
LOOSE_MAP_DESCRIPTION = ('Import MassiveEnvironmentComponent0 geometry from Unreal Engine .umap files')
# addon/formats/mec/importer.py (import_mec_umap_fallback_tex_root)
LOOSE_MAP_FALLBACK_TEX_ROOT = ('Local folder corresponding to /Game/ in asset paths.\nUsed only when Addon Preferences cannot be read.')
# addon/formats/mec/importer.py (import_mec_umap_fallback_tex_ext)
LOOSE_MAP_FALLBACK_TEX_EXT = ('File extension for texture files (dds, png, tga, etc.). Used only when Addon Preferences cannot be read.')
# addon/formats/mec/importer.py (import_mec_umap_import_originals)
LOOSE_MAP_IMPORT_ORIGINALS = ("Create hidden 'Original' objects at the world origin for each mesh type")
# addon/formats/mec/importer.py (import_mec_umap_create_map_origin)
LOOSE_MAP_CREATE_MAP_ORIGIN = ("Create an Empty at the average center of the imported groups' bounding boxes and parent this map's meshes to it")
# addon/formats/mec/importer.py (import_mec_umap_offset_opposite_faces)
LOOSE_MAP_OFFSET_OPPOSITE_FACES = ('Directly offset vertices on overlapping opposite-facing faces by 0.0005 at 0.01 scale to reduce z-fighting; no modifiers or material changes')
# addon/formats/mec/importer.py (import_mec_umap_import_sway)
LOOSE_MAP_IMPORT_SWAY = ('Bake the DeformContext wind animation into one shape key per frame. Only affects groups that carry sway data (roughly a third of them)')
# addon/formats/mec/importer.py (import_mec_umap_lod_mode)
LOOSE_MAP_LOD_MODE = ('Choose how LoD meshes are selected')
# addon/formats/mec/importer.py (import_mec_umap_lod_mode_QUALITY)
LOOSE_MAP_LOD_MODE_QUALITY = ('Select LoD by normalized quality: 1 is highest detail, 0 is lowest')
# addon/formats/mec/importer.py (import_mec_umap_lod_mode_LEVEL)
LOOSE_MAP_LOD_MODE_LEVEL = ('Select LoD by explicit level offset from highest detail')
# addon/formats/mec/importer.py (import_mec_umap_lod_mode_ALL)
LOOSE_MAP_LOD_MODE_ALL = ('Import every available LoD level')
# addon/formats/mec/importer.py (import_mec_umap_lod_quality)
LOOSE_MAP_LOD_QUALITY = ('Normalized LoD quality: 1 is highest detail, 0 is lowest available LoD')
# addon/formats/mec/importer.py (import_mec_umap_lod_level)
LOOSE_MAP_LOD_LEVEL = ('Explicit LoD level offset: 0 is highest detail, negative values step toward lower detail')
# addon/formats/mec/importer.py (import_mec_umap_scale_factor)
LOOSE_MAP_SCALE_FACTOR = ('Uniform scale factor applied to all positions (e.g. 0.01 for cm to m)')

# -----------------------------------------------------------------------------
# Rebirth Import
# -----------------------------------------------------------------------------

# Niagara resource importer (games/rebirth/importers/niagara.py).
REBIRTH_NIAGARA_DESCRIPTION = ('Import one of each Niagara mesh/material variant, using generic UE materials')
REBIRTH_NIAGARA_VIRTUAL_PATH = ('Mounted Niagara system .uasset path or /Game object path for scripted imports')
REBIRTH_NIAGARA_FOLDER = ('Limit the package-header scan to this folder or path text, then click Refresh Assets')
REBIRTH_NIAGARA_REFRESH = ('Read Niagara system classes from package headers in the selected asset folder')

# File > Import > Talisman > FF7R > Rebirth.
# Skeletal mesh, static mesh, skeleton only, UMAP, nearby terrain,
# cutscene, and KineDriver dialogs. Identical shared help lives in shared_import.py.

# -----------------------------------------------------------------------------
# Cutscene dialog
# -----------------------------------------------------------------------------
# addon/games/rebirth/importers/packages.py (import_cutscene_game_packages_description)
REBIRTH_CUTSCENE_DESCRIPTION = ('Import an EndCinemaSequence directly from mounted Rebirth packages')
# addon/games/rebirth/importers/packages.py (import_cutscene_game_packages_virtual_path)
REBIRTH_CUTSCENE_VIRTUAL_PATH = ('Selected package Camera sequence')
# addon/games/rebirth/importers/packages.py (import_cutscene_game_packages_cutscene_search_text)
REBIRTH_CUTSCENE_CUTSCENE_SEARCH_TEXT = ('Space-separated terms may occur anywhere in the cutscene path')
# addon/games/rebirth/importers/packages.py (import_cutscene_game_packages_always_cast_shadows)
REBIRTH_CUTSCENE_ALWAYS_CAST_SHADOWS = ('Force imported point and spot lights to cast shadows')

# -----------------------------------------------------------------------------
# Static mesh dialog
# -----------------------------------------------------------------------------
# addon/games/rebirth/importers/packages.py (import_static_mesh_game_packages_description)
REBIRTH_STATIC_MESH_DESCRIPTION = ('Import a Rebirth StaticMesh directly from its mounted virtual package path')
# addon/games/rebirth/importers/packages.py (import_static_mesh_game_packages_virtual_path)
REBIRTH_STATIC_MESH_VIRTUAL_PATH = ('Mounted Unreal virtual path to an indexed StaticMesh .uasset')
# addon/games/rebirth/importers/packages.py (import_static_mesh_game_packages_mesh_search_text)
REBIRTH_STATIC_MESH_MESH_SEARCH_TEXT = ('Filter indexed StaticMesh paths while preserving numeric order')

# -----------------------------------------------------------------------------
# Skeletal mesh dialog (shared entries also serve Skeleton only)
# -----------------------------------------------------------------------------
# addon/games/rebirth/importers/packages.py (import_skeletal_mesh_game_packages_description)
REBIRTH_SKELETAL_MESH_DESCRIPTION = ('Import a Rebirth SkeletalMesh and bind it to the selected armature')
# addon/games/rebirth/importers/packages.py (import_skeletal_mesh_game_packages_virtual_path)
REBIRTH_SKELETAL_MESH_VIRTUAL_PATH = ('Mounted Unreal virtual path to an indexed SkeletalMesh .uasset')
# addon/games/rebirth/importers/packages.py (import_skeletal_mesh_game_packages_mesh_search_text)
REBIRTH_SKELETAL_MESH_MESH_SEARCH_TEXT = ('Filter indexed SkeletalMesh paths while preserving numeric order')
# addon/games/rebirth/importers/packages.py (import_skeletal_mesh_game_packages_bind_active_armature)
REBIRTH_SKELETAL_MESH_BIND_ACTIVE_ARMATURE = ('Add matching vertex groups and an Armature modifier for the active armature')
# addon/games/rebirth/importers/packages.py (import_skeletal_mesh_game_packages_build_skeleton)
REBIRTH_SKELETAL_MESH_BUILD_SKELETON = ("Ignore Bind Active Armature and build a new armature from this mesh's associated Skeleton asset before importing, exactly as the Skeleton importer would")
# addon/games/rebirth/importers/packages.py (import_skeletal_mesh_game_packages_attachment_sockets)
# addon/games/rebirth/importers/packages.py (import_skeleton_game_packages_attachment_sockets)
REBIRTH_SKELETAL_MESH_ATTACHMENT_SOCKETS = ('Choose how attachment sockets are materialized on the generated armature')
# addon/games/rebirth/importers/packages.py (import_skeletal_mesh_game_packages_import_kdi)
REBIRTH_SKELETAL_MESH_IMPORT_KDI = ('After building the skeleton, also import its KineDriver rig (and any secondary passes)')
# addon/games/rebirth/importers/packages.py (import_skeletal_mesh_game_packages_connect_bones)
# addon/games/rebirth/importers/packages.py (import_skeleton_game_packages_connect_bones)
REBIRTH_SKELETAL_MESH_CONNECT_BONES = ("Move the parent's tail to the imported child head, then enable Blender's connected-bone display, preserving the child's original head position")
# addon/games/rebirth/importers/packages.py (import_skeletal_mesh_game_packages_setup_naive_ik)
# addon/games/rebirth/importers/packages.py (import_skeleton_game_packages_setup_naive_ik)
REBIRTH_SKELETAL_MESH_SETUP_NAIVE_IK = ('Create hand/foot targets and elbow/knee poles for matching limb chains, without changing the original bone hierarchy. Move targets to pose limbs; rotate targets to orient hands and feet')
# addon/games/rebirth/importers/packages.py (import_skeletal_mesh_game_packages_create_limbal_bone)
REBIRTH_SKELETAL_MESH_CREATE_LIMBAL_BONE = ('When L_Eye or R_Eye exists, create a centered non-deforming controller one foot in front of the character and use it for imported eye materials')
# addon/games/rebirth/importers/packages.py (import_skeletal_mesh_game_packages_generate_mouth_controls)
# addon/games/rebirth/importers/packages.py (import_skeleton_game_packages_generate_mouth_controls)
REBIRTH_SKELETAL_MESH_GENERATE_MOUTH_CONTROLS = ('Add jaw and smooth lip controls for recognized human faces using constraints, preserving the original bone hierarchy')
# addon/games/rebirth/importers/packages.py (import_skeletal_mesh_game_packages_create_variant_bone_collections)
# addon/games/rebirth/importers/packages.py (import_skeleton_game_packages_create_variant_bone_collections)
REBIRTH_SKELETAL_MESH_CREATE_VARIANT_BONE_COLLECTIONS = ('For player skeletons, scan meshes sharing this skeleton and create a collection named after each variant that has uniquely weighted bones')
# addon/games/rebirth/importers/packages.py (import_skeletal_mesh_game_packages_import_mesh_referenced_bones_only)
REBIRTH_SKELETAL_MESH_IMPORT_MESH_REFERENCED_BONES_ONLY = ("Build the armature from this mesh's complete ReferenceSkeleton and required parent bones, instead of the master Skeleton")
# addon/games/rebirth/importers/packages.py (import_skeletal_mesh_game_packages_face_y_forward)
REBIRTH_SKELETAL_MESH_FACE_Y_FORWARD = ("Choose the imported mesh and armature's forward axis")
# addon/games/rebirth/importers/packages.py (import_skeletal_mesh_game_packages_preserve_ue_axis_order)
REBIRTH_SKELETAL_MESH_PRESERVE_UE_AXIS_ORDER = ('Preserve the Unreal bone and KDI coordinate-axis convention')

# -----------------------------------------------------------------------------
# Nearby UMAP terrain (Experimental) dialog
# -----------------------------------------------------------------------------
# addon/games/rebirth/importers/packages.py (import_nearby_mec_terrain_description)
REBIRTH_NEARBY_MEC_TERRAIN_DESCRIPTION = ('Import untextured lowest-detail Massive Environment terrain near a Blender location')
# addon/games/rebirth/importers/packages.py (import_nearby_mec_terrain_continent)
REBIRTH_NEARBY_MEC_TERRAIN_CONTINENT = ('The continent whose streaming volumes are queried')
# addon/games/rebirth/importers/packages.py (import_nearby_mec_terrain_location)
REBIRTH_NEARBY_MEC_TERRAIN_LOCATION = ('Blender position within the selected continent around which to load terrain')
# addon/games/rebirth/importers/packages.py (import_nearby_mec_terrain_place_in_world_space)
REBIRTH_NEARBY_MEC_TERRAIN_PLACE_IN_WORLD_SPACE = ("Add the selected continent's MassiveEnvironmentOrigin when placing terrain")
# addon/games/rebirth/importers/packages.py (import_nearby_mec_terrain_view_distance)
REBIRTH_NEARBY_MEC_TERRAIN_VIEW_DISTANCE = ("Blender-space radius used to select the game's EndStreamingVolume brushes")

# -----------------------------------------------------------------------------
# UMAP dialog
# -----------------------------------------------------------------------------
# addon/games/rebirth/importers/packages.py (import_mec_game_packages_description)
REBIRTH_MEC_DESCRIPTION = ("Browse UMAPs inside Rebirth's mounted package files and import geometry, actors, and lights")
# addon/games/rebirth/importers/packages.py (import_mec_game_packages_virtual_path)
REBIRTH_MEC_VIRTUAL_PATH = ('Single Unreal virtual path for scripted/non-interactive imports')
# addon/games/rebirth/importers/packages.py (import_mec_game_packages_import_textures)
REBIRTH_MEC_IMPORT_TEXTURES = ('Read original DDS texture data from the game packages and pack it into the Blend file')
# addon/games/rebirth/importers/packages.py (import_mec_game_packages_import_models)
REBIRTH_MEC_IMPORT_MODELS = ('Create StaticMesh and SkeletalMesh UMAP actors directly from the mounted game packages. Repeated actors share one Blender datablock and missing game assets are reported. Skeletal actors import in bind pose; no in-level animation/pose data is available from the package.')
# addon/games/rebirth/importers/packages.py (import_mec_game_packages_import_lights)
REBIRTH_MEC_IMPORT_LIGHTS = ('Create point and spot lights from the UMAP actor data')
# addon/games/rebirth/importers/packages.py (import_mec_game_packages_always_cast_shadows)
REBIRTH_MEC_ALWAYS_CAST_SHADOWS = ('Force imported point and spot lights to cast shadows, overriding their Unreal CastShadows setting')
# addon/games/rebirth/importers/packages.py (import_mec_game_packages_recursive_import)
REBIRTH_MEC_RECURSIVE_IMPORT = ('Also import UMAPs referenced by Level Streaming actors')
# addon/games/rebirth/importers/packages.py (import_mec_game_packages_lod_mode_QUALITY)
REBIRTH_MEC_LOD_MODE_QUALITY = ('Select LoD by normalized quality')
# addon/games/rebirth/importers/packages.py (import_mec_game_packages_lod_mode_LEVEL)
REBIRTH_MEC_LOD_MODE_LEVEL = ('Select an explicit LoD level')
# addon/games/rebirth/importers/packages.py (import_mec_game_packages_lod_mode_ALL)
REBIRTH_MEC_LOD_MODE_ALL = ('Import every available LoD')

# -----------------------------------------------------------------------------
# KineDriver dialog
# -----------------------------------------------------------------------------
# addon/games/rebirth/importers/packages.py (import_kdi_game_packages_description)
REBIRTH_KDI_DESCRIPTION = ('Search the mounted game packages for a _KDI asset and build its drivers on the active armature')
# addon/games/rebirth/importers/packages.py (import_kdi_game_packages_virtual_path)
# addon/games/rebirth/importers/packages.py (import_skeleton_game_packages_virtual_path)
REBIRTH_KDI_VIRTUAL_PATH = ('Unreal virtual path. Type any part of a folder or filename to search')

# -----------------------------------------------------------------------------
# Skeleton only dialog
# -----------------------------------------------------------------------------
# addon/games/rebirth/importers/packages.py (import_skeleton_game_packages_description)
REBIRTH_SKELETON_DESCRIPTION = ('Search the mounted game packages for a _Skeleton asset and build its armature')
# addon/games/rebirth/importers/packages.py (import_skeleton_game_packages_armature_name)
REBIRTH_SKELETON_ARMATURE_NAME = ('Leave blank to name the armature after the skeleton asset')
# addon/games/rebirth/importers/packages.py (import_skeleton_game_packages_create_limbal_bone)
REBIRTH_SKELETON_CREATE_LIMBAL_BONE = ('When L_Eye or R_Eye exists, create a centered non-deforming controller one foot in front of the character for imported eye materials')
# addon/games/rebirth/importers/packages.py (import_skeleton_game_packages_import_secondary_kdi)
REBIRTH_SKELETON_IMPORT_SECONDARY_KDI = ('Stack any sibling _KDI_Extra1/_Head/_Hood/_StBody/_StHair passes onto the main KDI layer. In-game _Extra1 runs after Bonamik physics, which this add-on does not simulate, so it is an approximation; channels the main layer already drives are left alone')
# addon/games/rebirth/importers/packages.py (import_skeleton_game_packages_import_kdi)
REBIRTH_SKELETON_IMPORT_KDI = ('After building the armature, also search the mounted packages for a matching _KDI asset (e.g. PC0000_00_KDI beside PC0000_00_Skeleton) and import its drivers onto it. Skipped silently if none exists')
# addon/games/rebirth/importers/packages.py (import_skeleton_game_packages_kdi_virtual_path_override)
REBIRTH_SKELETON_KDI_VIRTUAL_PATH_OVERRIDE = ('Internal SkeletalMesh-provided KineDriver path; blank keeps the Skeleton-name fallback')
# addon/games/rebirth/importers/packages.py (import_skeleton_game_packages_referenced_bone_names_json)
REBIRTH_SKELETON_REFERENCED_BONE_NAMES_JSON = ('Internal SkeletalMesh-provided ReferenceSkeleton bone names')
# addon/games/rebirth/importers/packages.py (import_skeleton_game_packages_import_mesh_referenced_bones_only)
REBIRTH_SKELETON_IMPORT_MESH_REFERENCED_BONES_ONLY = ("Keep this folder's complete mesh ReferenceSkeleton, including unweighted KDI/helper bones, rather than every bone in the master Skeleton. This matches FModel/umodel; variant-collection creation is skipped")
# addon/games/rebirth/importers/packages.py (import_skeleton_game_packages_face_y_forward)
REBIRTH_SKELETON_FACE_Y_FORWARD = ("Choose the generated armature's forward axis")
# addon/games/rebirth/importers/packages.py (import_skeleton_game_packages_preserve_ue_axis_order)
REBIRTH_SKELETON_PRESERVE_UE_AXIS_ORDER = ('Do not apply the Blender-oriented bone display roll; preserve Unreal bone axes')

# -----------------------------------------------------------------------------
# Remake Import
# -----------------------------------------------------------------------------

# File > Import > Talisman > FF7R > Remake.
# Package KineDriver and LevelSequence cutscene dialogs.
# addon/games/remake/importers/cutscenes.py (import_cutscene_game_packages_description)
REMAKE_CUTSCENE_DESCRIPTION = ('Import a Remake UE4 LevelSequence camera, light, and character sequencing data')
# addon/games/remake/importers/cutscenes.py (import_cutscene_game_packages_virtual_path)
REMAKE_CUTSCENE_VIRTUAL_PATH = ('Select a Remake _Camera LevelSequence package')
# addon/games/remake/importers/cutscenes.py (import_cutscene_game_packages_import_characters)
REMAKE_CUTSCENE_IMPORT_CHARACTERS = ('Apply sections to already-imported Remake actors and actions with matching source names')
# addon/games/remake/importers/static_mesh.py (import_kdi_game_packages_description)
REMAKE_KDI_DESCRIPTION = ('Search mounted Remake packages for a _KDI asset and build its drivers on the active armature')
# addon/games/remake/importers/static_mesh.py (import_kdi_game_packages_virtual_path)
REMAKE_KDI_VIRTUAL_PATH = ('Type any part of a Remake KDI package path to search')

# -----------------------------------------------------------------------------
# Kingdom Hearts Import
# -----------------------------------------------------------------------------

# File > Import > Talisman > Kingdom Hearts.
# Package KineDriver and Matinee cutscene import dialogs.
# addon/games/kingdom_hearts/importers/matinee.py (attributes_description)
KINGDOM_HEARTS_MATINEE_IMPORT = ('Import a legacy Matinee cutscene map from {game_label}')
# addon/games/kingdom_hearts/importers/matinee.py (attributes_import_existing_rig_animations)
KINGDOM_HEARTS_MATINEE_EXISTING_RIG_ANIMATIONS = ('Load full-body clips onto imported event-pawn rigs and matching Kingdom Hearts armatures')
# addon/games/kingdom_hearts/importers/static_mesh.py (virtual_path)
KINGDOM_HEARTS_KDI_SEARCH_PATH = ('Type any part of an indexed {definition_game_name} KineDriver package path')
# addon/games/kingdom_hearts/importers/static_mesh.py (static_mesh_description)
KINGDOM_HEARTS_KDI_IMPORT = ('Import a {definition_game_name} KineDriver package onto the active armature')
