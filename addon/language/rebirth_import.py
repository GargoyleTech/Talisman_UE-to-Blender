"""English hover tooltips. Edit text here; keep variable names stable."""

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
