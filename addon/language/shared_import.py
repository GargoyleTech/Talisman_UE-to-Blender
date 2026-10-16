"""English hover tooltips. Edit text here; keep variable names stable."""

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
SHARED_SKELETAL_PRESERVE_UE_AXIS_ORDER = ('Preserve Unreal bone axes instead of Blender-oriented display rolls.')
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
SHARED_MAX_TEXTURE_RESOLUTION = ('Maximum width or height for newly imported textures; 0 keeps the original resolution. Existing higher-resolution images are retained')
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
