"""English hover tooltips. Edit text here; keep variable names stable."""

# Object / Pose / Armature > Talisman menus and the viewport KDI toggle.
# Also includes generated mouth-control custom properties in Bone Properties.

# -----------------------------------------------------------------------------
# Bone Properties > Generated mouth controls
# -----------------------------------------------------------------------------
# addon/core/blender/lip_rig.py (PROPERTIES[0])
MOUTH_LIP_CONTROLS_INFLUENCE = ('Blend the eight lip handles with the incoming lip pose')
# addon/core/blender/lip_rig.py (lip_rig)
MOUTH_SHOW_LIP_GUIDES = ('Show the curved guides joining the lip handles')
# addon/core/blender/mouth_rig.py ('influence')
SCENE_TOOLS_INFLUENCE = ('Blend the generated jaw motion with the incoming facial pose')
# addon/core/blender/mouth_rig.py ('lip_follow')
SCENE_TOOLS_LIP_FOLLOW = ('How strongly the lower lips follow the jaw')
# addon/core/blender/mouth_rig.py ('corner_follow')
SCENE_TOOLS_CORNER_FOLLOW = ('How strongly the lower mouth corners follow the jaw')
# addon/core/blender/mouth_rig.py ('jaw_side_follow')
SCENE_TOOLS_JAW_SIDE_FOLLOW = ('How strongly the jaw-angle skin follows the jaw')

# -----------------------------------------------------------------------------
# Object > Talisman > Fix Z-Fighting
# -----------------------------------------------------------------------------
# addon/core/blender/z_fighting.py (MESH_OT_find_opposite_faces_description)
SCENE_TOOLS_MESH_OT_FIND_OPPOSITE_FACES_DESCRIPTION = ('Mark opposite duplicate faces and add the UE4 alpha displacement fix')
# addon/core/blender/z_fighting.py (MESH_OT_find_opposite_faces_subsurface_weight)
SCENE_TOOLS_MESH_OT_FIND_OPPOSITE_FACES_SUBSURFACE_WEIGHT = ('Subsurface weight for opposite faces')

# -----------------------------------------------------------------------------
# Pose / Object > Talisman > Repair limb IK
# -----------------------------------------------------------------------------
# addon/ui/ik_rig.py (repair_limb_ik_description)
SCENE_TOOLS_REPAIR_LIMB_IK_DESCRIPTION = ('Make earlier Square Enix IK rigs resistant to straight-limb stalls after clearing pose rotations')

# -----------------------------------------------------------------------------
# Pose / Object > Talisman > Generate Mouth Controls
# -----------------------------------------------------------------------------
# addon/ui/mouth_rig.py (generate_mouth_controls_description)
SCENE_TOOLS_GENERATE_MOUTH_CONTROLS_DESCRIPTION = ('Add or upgrade jaw and smooth lip controls without changing original bone parents')

# -----------------------------------------------------------------------------
# Object > Talisman > Add RMI Surface Material
# -----------------------------------------------------------------------------
# addon/ui/operators.py (add_rmi_surface_material_description)
SCENE_TOOLS_ADD_RMI_SURFACE_MATERIAL_DESCRIPTION = ('Create a new Square Enix RMI Surface material in the active material slot; leave Variant blank for the full master')
# addon/ui/operators.py (add_rmi_surface_material_variant)
SCENE_TOOLS_ADD_RMI_SURFACE_MATERIAL_VARIANT = ('Choose an RMI_Surface variant or leave blank for the complete master')

# -----------------------------------------------------------------------------
# Armature Edit Mode > Talisman > Move Parent Tail Here and Connect
# -----------------------------------------------------------------------------
# addon/ui/operators.py (connect_parent_tail_to_bone_description)
SCENE_TOOLS_CONNECT_PARENT_TAIL_TO_BONE_DESCRIPTION = ("Move the active bone's parent's tail to this bone's head, then connect the active bone without moving its head")
