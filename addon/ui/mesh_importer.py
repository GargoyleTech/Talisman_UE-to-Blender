"""Shared UE4-first layout for StaticMesh and SkeletalMesh package dialogs."""

from ..language import strings


SKELETAL_OPTION_LABELS = {
    "import_kdi": "Also import KDI",
    "preserve_ue_axis_order": "Keep original UE axis ordering",
    "connect_bones": "Connect bones to parent",
    "import_mesh_referenced_bones_only": "Only import bones used by this SkeletalMesh",
    "create_variant_bone_collections": "Create variant bone collections",
    "attachment_sockets": "Attachment Sockets",
    "setup_naive_ik": "Create limb IK controls",
    "create_limbal_bone": "Create C_Limbal eye controller",
    "generate_mouth_controls": "Generate Mouth Controls",
}

SKELETAL_OPTION_DESCRIPTIONS = {
    "import_kdi": strings.SHARED_SKELETAL_IMPORT_KDI,
    "preserve_ue_axis_order": strings.SHARED_SKELETAL_PRESERVE_UE_AXIS_ORDER,
    "connect_bones": strings.SHARED_SKELETAL_CONNECT_BONES,
    "import_mesh_referenced_bones_only": (
        strings.SHARED_SKELETAL_IMPORT_MESH_REFERENCED_BONES_ONLY
    ),
    "create_variant_bone_collections": (
        strings.SHARED_SKELETAL_CREATE_VARIANT_BONE_COLLECTIONS
    ),
    "attachment_sockets": strings.SHARED_SKELETAL_ATTACHMENT_SOCKETS,
    "setup_naive_ik": strings.SHARED_SKELETAL_SETUP_NAIVE_IK,
    "create_limbal_bone": strings.SHARED_SKELETAL_CREATE_LIMBAL_BONE,
    "generate_mouth_controls": strings.SHARED_SKELETAL_GENERATE_MOUTH_CONTROLS,
}

SKELETAL_OPTION_NAMES = frozenset(SKELETAL_OPTION_LABELS)


# These are Blender representations of ordinary UE4 skeletal data.
CORE_SKELETAL_OPTIONS = (
    "preserve_ue_axis_order", "connect_bones", "import_mesh_referenced_bones_only", "attachment_sockets",
)
GAME_SKELETAL_OPTIONS = (
    "import_kdi", "create_variant_bone_collections", "setup_naive_ik",
    "create_limbal_bone", "generate_mouth_controls",
)


def draw_package_mesh_options(layout, operator, *, mesh_kind, game_label, game_options=()):
    """Keep ordinary Unreal controls above the applicable title-specific extras."""
    common = layout.box()
    common.label(text="UE4 options")
    row = common.row(align=True)
    row.prop(operator, "scale_factor")
    row.prop(operator, "face_y_forward")
    common.prop(operator, "offset_opposite_faces")
    if mesh_kind == "STATIC" and hasattr(operator, "nanite_mode"):
        from .nanite import draw_nanite_options
        draw_nanite_options(layout, operator)
    if mesh_kind == "SKELETAL":
        row = common.row(align=True)
        row.prop(operator, "build_skeleton")
        binding = row.column(align=True)
        binding.enabled = not operator.build_skeleton
        binding.prop(operator, "bind_active_armature")
        skeleton = common.column(align=True)
        skeleton.enabled = operator.build_skeleton
        for name in CORE_SKELETAL_OPTIONS:
            skeleton.prop(operator, name, text=SKELETAL_OPTION_LABELS[name])

        applicable = [name for name in GAME_SKELETAL_OPTIONS if name in game_options]
        if applicable:
            specific = layout.box()
            specific.label(text=f"{game_label} options")
            controls = specific.column(align=True)
            controls.enabled = operator.build_skeleton
            for name in applicable:
                controls.prop(operator, name, text=SKELETAL_OPTION_LABELS[name])


def draw_package_mesh_importer(layout, context, *, operator, browser_state, mesh_kind,
                               asset_count, cache_source, game_label, material_summary,
                               supported_skeletal_options=frozenset()):
    """Compatibility wrapper for scripts using the former layout helper."""
    from ..games import package_browser
    package_browser.draw(layout, context, browser_state)
    draw_package_mesh_options(layout, operator, mesh_kind=mesh_kind,
                              game_label=game_label, game_options=supported_skeletal_options)
    layout.label(text=f"{asset_count:,} {game_label} {mesh_kind.title()}Mesh assets indexed ({cache_source or 'memory'})")
    layout.label(text=material_summary)
