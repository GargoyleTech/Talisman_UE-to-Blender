"""FF7 Rebirth RMI_Surface Eye_ material generator.

This profile is selected only for the three current-build variants carrying
``Eye_``.  It builds the SM9 iris, cornea, limbal, and supported emissive
paths, retaining only switches that occur on those variants.  No hair or
ordinary-surface detail/layer graph is created.

Run with Blender's ``--python ff7r_rmi_surface_eye.py`` option, or let the
RMI integration select it from a material parent's ground-truth switch set.
"""

if __package__:
    from .....language import strings
else:
    # Preserve running the packaged builder directly in Blender's Text Editor.
    import sys as _sys
    from pathlib import Path as _Path

    _sys.path.insert(0, str(_Path(__file__).resolve().parents[4]))
    try:
        from language import strings
    finally:
        _sys.path.pop(0)

import bpy


def _detect_menu_switch():
    """Find a usable shader-tree Menu Switch bl_idname, and separately whether
    its selector can actually be controlled from outside the node -- these
    turn out to be two different questions with two different answers, found
    by testing on a real Blender 5.2.0 LTS build (`GeometryNodeMenuSwitch`
    placed in a `ShaderNodeTree`, confirmed via a Tree Clipper export of a
    material the user built by hand in the Shader Editor), not guessed:

    1. **Existence / placeability is not a straightforward version check.**
       `hasattr(bpy.types, "ShaderNodeMenuSwitch")` is a literal string check
       (not a fuzzy version comparison), and it is False on 5.2.0 LTS: no
       `ShaderNode`-prefixed class exists.  The real, only class is
       `GeometryNodeMenuSwitch` -- confirmed present since at least 5.0.1 too.
       `nodes.new(idname)` does not enforce tree-type compatibility (that is
       `poll()`'s job, which the direct data-API does not call), so a naive
       "did it instantiate" test is a false positive: on 5.0.1 it happily
       creates a GeometryNode inside a ShaderNodeTree that cannot compile.
       `GeometryNodeMenuSwitch.poll(shader_tree)` reports False even on 5.2.0
       LTS -- yet the Shader Editor's own Add menu lets a user place one
       anyway (per the Tree Clipper dump). So neither "did nodes.new()
       succeed" nor "does poll() agree" is fully trustworthy on its own; both
       are recorded so the build log shows what was actually found rather
       than a version guess.

    2. **Selectability is the fact that actually matters here, and it is
       negative.** The Menu socket's `default_value` -- and the companion
       `FunctionNodeInputMenu.value` -- both raise
       `TypeError: property "default_value" not animatable` from
       `driver_add()`, confirmed directly against 5.2.0 LTS.  Menu selection
       is evidently resolved as a compile-time/specialization choice, not a
       per-shading-point value, so it cannot be driven live from a numeric
       material custom property without a scripted driver (which this file
       deliberately avoids -- see the module docstring on "Auto Run Python
       Scripts").  A plain Float *links* into a Menu socket without Blender
       raising -- but `links.new()` is permissive about socket-type mismatches
       and that success is not evidence the link means anything at shading
       time, so it is not treated as a substitute for the driver test.

    Net effect: **the comparison-ladder fallback in `_menu()` is not a
    compatibility shim for "Menu Switch doesn't exist yet" -- it is the only
    mechanism, on any Blender version tested so far, that satisfies this
    project's actual requirement of live custom-property control without a
    scripted driver.** `HAS_MENU_SWITCH` is therefore gated on both existence
    AND drivability, not existence alone; today that means it is False
    regardless of which candidate name matches."""
    candidates = ["ShaderNodeMenuSwitch", "FunctionNodeMenuSwitch",
                  "NodeMenuSwitch", "GeometryNodeMenuSwitch"]
    scratch = bpy.data.node_groups.new("_ff7r_menu_probe", "ShaderNodeTree")
    try:
        for idn in candidates:
            try:
                node = scratch.nodes.new(idn)
            except RuntimeError:
                continue
            cls = getattr(bpy.types, idn, None)
            polls = cls.poll(scratch) if cls is not None and hasattr(cls, "poll") else None
            drivable = False
            try:
                fc = node.inputs[0].driver_add("default_value")
                drivable = True
                node.inputs[0].driver_remove("default_value")
            except TypeError:
                pass
            except Exception:
                pass
            print("Menu Switch: %r instantiates in a ShaderNodeTree "
                  "(poll=%s, selector drivable=%s)" % (idn, polls, drivable))
            if drivable:
                return idn, True
            if MENU_SWITCH_BEST[0] is None:
                MENU_SWITCH_BEST[0] = idn
        if MENU_SWITCH_BEST[0] is not None:
            print("Menu Switch: %r exists but its selector is not drivable "
                  "from a custom property on this build (Blender %s) -- "
                  "using the comparison-ladder fallback, which is not a "
                  "version shim here, see _detect_menu_switch()'s docstring."
                  % (MENU_SWITCH_BEST[0], bpy.app.version_string))
            return MENU_SWITCH_BEST[0], False
        print("Menu Switch: no candidate instantiates in a ShaderNodeTree on "
              "this build (Blender %s) -- using the fallback ladder."
              % bpy.app.version_string)
        return None, False
    finally:
        bpy.data.node_groups.remove(scratch)


MENU_SWITCH_BEST = [None]   # mutable cell _detect_menu_switch() writes into
MENU_SWITCH_IDNAME, MENU_SWITCH_DRIVABLE = _detect_menu_switch()


def _detect_menu_input():
    """Return a Constant Menu idname for capability diagnostics.

    The generator deliberately keeps the portable numeric selector (see
    ``HAS_MANUAL_MENU_SWITCH`` below), because a standalone Constant Menu
    cannot author its enum definition in a ShaderNodeTree.  Retaining this
    probe makes the console explain precisely which menu nodes a Blender build
    exposes without mistaking their existence for a usable material path.
    """
    candidates = ["FunctionNodeInputMenu", "ShaderNodeInputMenu",
                  "NodeInputMenu", "FunctionNodeMenuInput"]
    scratch = bpy.data.node_groups.new("_ff7r_menu_input_probe", "ShaderNodeTree")
    try:
        for idn in candidates:
            try:
                scratch.nodes.new(idn)
            except RuntimeError:
                continue
            print("Constant Menu: %r instantiates in a ShaderNodeTree." % idn)
            return idn
        return None
    finally:
        bpy.data.node_groups.remove(scratch)


MENU_INPUT_IDNAME = _detect_menu_input()
# ``FunctionNodeInputMenu`` exposes a selected value but no writable enum
# definition.  In a ShaderNodeTree the new node therefore has an empty enum;
# assigning ``Standard (SM1)`` raises ``enum ... not found in ()``.  The enum
# definition of a Menu Switch cannot safely cross the material/group boundary
# used by this generator either.  Keep the capability probes for diagnostics,
# but use the established numeric comparison ladder until Blender exposes a
# constructible, shader-tree-safe menu definition.
HAS_MANUAL_MENU_SWITCH = False
if MENU_SWITCH_IDNAME is not None and MENU_INPUT_IDNAME is not None:
    print("Constant Menu: %r has no authorable enum definition in this "
          "ShaderNodeTree path (Blender %s) -- using the comparison ladder."
          % (MENU_INPUT_IDNAME, bpy.app.version_string))
elif MENU_SWITCH_IDNAME is not None:
    print("Constant Menu: %r exists but this build (Blender %s) has no "
          "constant-menu node to select with -- using the same comparison "
          "ladder as 4.x." % (MENU_SWITCH_IDNAME, bpy.app.version_string))
HAS_MENU_SWITCH = MENU_SWITCH_IDNAME is not None and MENU_SWITCH_DRIVABLE


def _detect_bundles():
    """True when a bundle in a ShaderNodeTree can carry what this file bundles.

    Existence of the nodes is not the question.  Blender 5.0 ships
    NodeCombineBundle / NodeSeparateBundle and lists BOOLEAN in the socket-type
    enum, yet a bundle inside a ShaderNodeTree refuses to hold one --
    `RuntimeError: Error: Unable to create item with this socket type`,
    measured on 5.0.1, which accepts FLOAT / INT / VECTOR / RGBA and rejects
    BOOLEAN and MENU.  5.2.0 LTS accepts all of them (measured).  The 5.1
    release notes do not say which side of that line 5.1 falls on, so ask the
    running build instead of hard-coding a version: every switch is bundled as
    BOOLEAN and every parameter as FLOAT, so create one of each and let the
    answer decide.  Where it fails, the material keeps the direct property
    links -- exactly what 4.x does, and no feature is lost, only the tidier
    single-wire routing."""
    if not (hasattr(bpy.types, "NodeCombineBundle") and
            hasattr(bpy.types, "NodeSeparateBundle")):
        return False
    scratch = bpy.data.node_groups.new("_ff7r_bundle_probe", "ShaderNodeTree")
    try:
        node = scratch.nodes.new("NodeCombineBundle")
        try:
            node.define_signature = True
        except Exception:
            pass
        for socket_type in ("BOOLEAN", "FLOAT"):
            try:
                node.bundle_items.new(socket_type, "probe_" + socket_type)
            except Exception:
                print("Bundles: this build (Blender %s) cannot put a %s into a "
                      "shader bundle -- material properties stay on direct "
                      "links." % (bpy.app.version_string, socket_type))
                return False
        print("Bundles: shader bundles carry BOOLEAN and FLOAT -- routing the "
              "material properties through one.")
        return True
    except Exception:
        print("Bundles: no usable Combine Bundle on this build (Blender %s) -- "
              "material properties stay on direct links."
              % bpy.app.version_string)
        return False
    finally:
        bpy.data.node_groups.remove(scratch)


HAS_BUNDLES = _detect_bundles()
HAS_CONVENTION = "convention" in bpy.types.ShaderNodeNormalMap.bl_rna.properties


def _detect_thin_wall():
    """Return Principled's thin-wall input name, or None on builds without it.

    Cloth (SM8) is a thin translucent sheet, which Principled can only express
    from Blender 5.2 on.  Probe for the socket rather than testing the version
    number -- same reasoning as HAS_CONVENTION -- so this stays correct if the
    input arrives under a different spelling.  Absence is not an error: it
    means Cloth keeps exactly the parameters it had on 5.1 and earlier."""
    scratch = bpy.data.node_groups.new("_ff7r_thinwall_probe", "ShaderNodeTree")
    try:
        node = scratch.nodes.new("ShaderNodeBsdfPrincipled")
        for nm_ in ("Thin Wall", "Thin wall", "Thin Walled", "Thinwall"):
            if node.inputs.get(nm_) is not None:
                print("Thin Wall: Principled exposes %r -- Cloth gets "
                      "subsurface 1.0 and thin wall." % nm_)
                return nm_
        print("Thin Wall: Principled has no thin-wall input on this build "
              "(Blender %s) -- Cloth left unchanged."
              % bpy.app.version_string)
        return None
    finally:
        bpy.data.node_groups.remove(scratch)


THIN_WALL_SOCKET = _detect_thin_wall()


def _detect_panel_states():
    """Return the Node attribute holding per-panel collapse state, or None.

    Principled draws Subsurface / Specular / Transmission / Coat / Sheen /
    Emission / Thin Film as collapsed sections, and this material drives most
    of them, so they are worth arriving open.  Blender 4.5 and 5.0 keep that
    state in DNA without exposing it to RNA (measured on 4.5.3 and 5.0.1:
    neither `panel_states` nor `panels` exists on a node), so probe for it the
    same way as the other capabilities rather than testing a version: expand
    the sections on builds that allow it, leave them alone on builds that do
    not.  Absence is not an error -- it costs the user one click per panel."""
    scratch = bpy.data.node_groups.new("_ff7r_panel_probe", "ShaderNodeTree")
    try:
        node = scratch.nodes.new("ShaderNodeBsdfPrincipled")
        for attr in ("panel_states", "panels"):
            states = getattr(node, attr, None)
            if not states:
                continue
            try:
                states[0].is_collapsed = False
            except Exception:
                continue
            print("Node panels: %r is writable -- Principled ships with its "
                  "sections expanded." % attr)
            return attr
        print("Node panels: this build (Blender %s) does not expose node panel "
              "state to Python -- Principled keeps Blender's own default."
              % bpy.app.version_string)
        return None
    finally:
        bpy.data.node_groups.remove(scratch)


PANEL_STATE_ATTR = _detect_panel_states()


def _expand_panels(node):
    """Open every collapsed section on `node`, where the build allows it."""
    if PANEL_STATE_ATTR is None:
        return
    for state in getattr(node, PANEL_STATE_ATTR, ()):
        try:
            state.is_collapsed = False
        except Exception:
            log("panel expand failed on %s" % getattr(node, "name", "?"))
            return

MAT_NAME = "FF7R_RMI_Surface_Eye_Master"
PROFILE_NAME = "eye"
PROFILE_REVISION = 2

# ---------------------------------------------------------------------------
# Literals hoisted out of the compiled shaders.  PLAN 0.2: the material JSONs
# carry no per-instance numerics worth reading, so these constants ARE the
# parameters.  Everything here is also exposed as a material custom property.
# ---------------------------------------------------------------------------

# base pass / GBuffer
F0_KNEE = 0.666667                  # GBufferA.a piecewise remap knee
F0_LO, F0_HI = 0.06, 0.36
F0_HI_BIAS = 0.2
F0_CLAMP = 0.16
SPEC_LEVEL_SCALE = 0.08             # Blender: Specular IOR Level = F0 / 0.08
OPACITY_CLIP = 0.3333               # BasePropertyOverrides.OpacityMaskClipValue

# eye  (from ff7r_eye_material_v2.py)
CORNEA_SLOPE = 0.911537             # cornea dome xy scale
ETA = 0.671141                      # 1 / 1.49, the cornea IOR
DEPTH_CONST = 0.373500              # iris depth = max(0, C - F*r^2) * S
DEPTH_FALLOFF = 0.279500
DEPTH_SCALE = 0.407664
MASK_INNER = 0.900000               # sclera mask = smoothstep(IN, OUT, |uvC|)
MASK_OUTER = 1.100000
LIMBAL_OFFSET = 0.780000
LIMBAL_SOFTNESS = 0.550000
LIMBAL_APERTURE = 2.700000
EYE_UV_CENTER = (0.5, 0.5)
EYE_UV_RADIUS = 0.25
_INV = 1.0 / EYE_UV_RADIUS
UV_MAP = ""                         # "" = the object's ACTIVE uv layer
# Shared strength for texture-derived Normal Map nodes.  The synthetic map in
# util_tbn() stays at 1.0 because it recovers tangent handedness, not detail.
NORMAL_MAP_STRENGTH = 0.7

# hair  (from ff7r_hair_material.py -- measured values, not guesses)
MIN_VDOTT = 0.05                    # shader clamps |dot(V, strand)| off zero
HAIR_SPECULAR_F0 = 0.046520         # GBufferA.a 0.684779 through the remap
ROUGHNESS_CURVATURE = 1          # specular-AA curvature term, saturated
HAIR_ANISOTROPIC = 1.0
FLOW_INFLUENCE = 0.5                # 0 = capture-exact

# blood
BLOOD_R = (0.0802, 0.8328)          # channel = a + b*s
BLOOD_G = (0.00368, -0.00368)
BLOOD_B = (0.00802, -0.0065)

_LOG = []
_UV_NOTES = []


def log(msg):
    _LOG.append(msg)


# ---------------------------------------------------------------- helpers ---

def _new(tree, idname, name, loc, label="", parent=None):
    n = tree.nodes.new(idname)
    n.name = name
    if label:
        n.label = label
    if parent is not None:
        n.parent = parent
    n.location = loc
    return n


def _prop(node, attr, value):
    try:
        setattr(node, attr, value)
    except Exception:
        log("prop failed: %s.%s" % (getattr(node, "name", "?"), attr))


def _in(node, key):
    """Socket by NAME, falling back to index.  Principled's socket ORDER moves
    between Blender versions; its names do not (PLAN 3.3)."""
    try:
        return node.inputs[key]
    except (KeyError, IndexError, TypeError):
        return None


def _sv(node, key, value):
    s = _in(node, key)
    if s is None:
        log("no socket %r on %s" % (key, node.name))
        return
    try:
        dv = s.default_value
        if hasattr(dv, "__len__") and not isinstance(dv, str):
            n = len(dv)
            v = list(value) if hasattr(value, "__len__") else [value] * n
            s.default_value = (v + [1.0] * n)[:n]
        else:
            s.default_value = value
    except Exception:
        log("set failed %s[%s]" % (node.name, key))


def _sov(node, value):
    """ShaderNodeValue keeps its value on outputs[0], not inputs[0]."""
    try:
        node.outputs[0].default_value = value
    except Exception:
        log("value set failed on %s" % getattr(node, "name", "?"))


def _link(tree, a, ao, b, bi):
    try:
        fs = a.outputs[ao]
        ts = b.inputs[bi]
    except (KeyError, IndexError, AttributeError, TypeError):
        log("broken link %s[%s] -> %s[%s]"
            % (getattr(a, "name", "?"), ao, getattr(b, "name", "?"), bi))
        return None
    try:
        return tree.links.new(fs, ts)
    except Exception:
        log("link refused %s -> %s" % (a.name, b.name))
        return None


def _frame(tree, name, label, parent=None):
    f = tree.nodes.new("NodeFrame")
    f.name = name
    f.label = label
    f.shrink = True
    f.label_size = 22
    if parent is not None:
        f.parent = parent
    return f


def _sock(g, name, in_out, stype, default=None, mn=None, mx=None):
    it = g.interface.new_socket(name, in_out=in_out, socket_type=stype)
    if default is not None:
        try:
            it.default_value = default
        except Exception:
            pass
    for attr, val in (("min_value", mn), ("max_value", mx)):
        if val is not None:
            try:
                setattr(it, attr, val)
            except Exception:
                pass
    return it


def _rebuild_group(name, builder):
    g = bpy.data.node_groups.get(name)
    # These groups are shared by every generated material, including materials
    # restored from a Blend file whose unused master was discarded on save.
    # Removing interface sockets severs links in all those material instances.
    # A populated group is already built: reuse its socket identities and values.
    if g is not None and g.nodes:
        return g
    if g is None:
        g = bpy.data.node_groups.new(name, "ShaderNodeTree")
    else:
        g.nodes.clear()
        try:
            for it in list(g.interface.items_tree):
                g.interface.remove(it)
        except Exception:
            pass
    builder(g)
    _hide_unused_system_outputs(g)
    return g


def _grp(tree, gname, node_name, loc, label="", parent=None):
    n = _new(tree, "ShaderNodeGroup", node_name, loc, label or gname, parent)
    n.node_tree = bpy.data.node_groups.get(gname)
    if n.node_tree is None:
        log("missing group %r for %s" % (gname, node_name))
    return n


def _hide_unused_system_outputs(tree):
    """Apply Ctrl+H-style output hiding to high-fanout system nodes.

    Geometry and Light Path otherwise display a large wall of irrelevant
    sockets.  This is intentionally limited to those nodes: ordinary shader
    nodes often use unlinked inputs as authored constants and should stay
    visible for editing.
    """
    for node in tree.nodes:
        if node.bl_idname not in {"ShaderNodeNewGeometry", "ShaderNodeLightPath"}:
            continue
        for socket in node.outputs:
            socket.hide = not socket.is_linked


# ------------------------------------------------ DirectX normal convention --

_MISSING_CONVENTION = []
_CONVENTION_FIXED = []


def _convention(node, value):
    """Normal Map 'convention' is Blender 5.2+.  On 5.0/5.1 the property does
    not exist, so a DIRECTX map would silently lose its green flip.  Record it
    and splice explicit maths in after linking."""
    if HAS_CONVENTION:
        _prop(node, "convention", value)
    elif value == "DIRECTX":
        _MISSING_CONVENTION.append(node)


def _fix_conventions(tree):
    """5.0/5.1 fallback: insert (r, 1-g, b) before each DIRECTX Normal Map --
    exactly what convention='DIRECTX' does natively on 5.2+."""
    for node in list(_MISSING_CONVENTION):
        if node.id_data is not tree:
            continue
        col = _in(node, "Color")
        if col is None or not col.is_linked:
            _MISSING_CONVENTION.remove(node)
            continue
        link = col.links[0]
        src = link.from_socket
        tree.links.remove(link)
        flip = tree.nodes.new("ShaderNodeVectorMath")
        flip.operation = "MULTIPLY_ADD"
        flip.name = node.name + " green flip"
        flip.label = "green flip (DirectX -> OpenGL)"
        flip.parent = node.parent
        flip.location = (node.location[0] - 190, node.location[1] - 120)
        flip.inputs[1].default_value = (1.0, -1.0, 1.0)
        flip.inputs[2].default_value = (0.0, 1.0, 0.0)
        tree.links.new(src, flip.inputs[0])
        tree.links.new(flip.outputs[0], col)
        _CONVENTION_FIXED.append(node.name)
        _MISSING_CONVENTION.remove(node)


def _decode_tangent_normal(tree, name, loc, label="", parent=None):
    """Create the non-destructive part of a normal-map decode in *tree*.

    The returned pair is ``(signed, normal)``: connect a texture colour to
    ``signed`` and use ``normal`` downstream.  The vector deliberately stays
    in the authored DirectX convention.  On Blender 5.2+, the one final
    Normal Map node performs the Y inversion through ``convention='DIRECTX'``;
    this avoids mutating the texture colours merely to satisfy Blender's
    default convention.
    """
    signed = _new(tree, "ShaderNodeVectorMath", name, loc,
                  label or "normal rgb * 2 - 1", parent)
    _prop(signed, "operation", "MULTIPLY_ADD")
    _sv(signed, 1, (2.0, 2.0, 2.0))
    _sv(signed, 2, (-1.0, -1.0, -1.0))
    normal = _new(tree, "ShaderNodeVectorMath", name + " Normalize",
                  (loc[0] + 190, loc[1]), "normalise tangent vector", parent)
    _prop(normal, "operation", "NORMALIZE")
    _link(tree, signed, 0, normal, 0)
    return signed, normal


# ------------------------------------------------------- custom properties ---

# Parent materials establish a 126-flag universe. Every flag is exposed
# below, but flags with identical presence vectors across all 104 ground-truth
# variants share ONE checkbox (the complete "A_ + B_" list). This prevents the
# UI from claiming separability no carrier or decompilation proves.
_SWITCH_DEFAULTS = dict([
    ("Color_", 1.0), ("Normal_", 1.0), ("Roughness_", 1.0), ("Occlusion_", 1.0),
    ("WideOcclusion_", 1.0), ("Metallic_", 0.0), ("Standard_", 1.0),
    ("Coverage_", 0.0), ("Detail_", 0.0), ("DetailNormal_", 0.0),
    ("DetailRoughness_", 0.0), ("DetailColor_", 0.0), ("DetailOcclusion_", 0.0),
    ("Skin_", 0.0), ("Pores_", 0.0), ("Subsurface_", 0.0),
    ("Fabric_", 0.0), ("Diffusion_", 0.0),
    ("Hair_", 0.0), ("CylindricalNormal_", 0.0), ("WideBentNormal_", 0.0),
    ("Eye_", 0.0), ("ScleraNormal_", 0.0), ("GazeNormal_", 0.0),
    ("IrisColor_", 0.0), ("IrisNormal_", 0.0), ("IrisOcclusion_", 0.0),
    ("IrisEmissive_", 0.0), ("EyeMigration_", 0.0),
    ("Segmented_", 0.0), ("SegmentLayer0_", 0.0), ("SegmentLayer1_", 0.0),
    ("Layered_", 0.0), ("ShadingLayer_", 0.0),
    ("Emissive_", 0.0), ("ExtraEmissive_", 0.0), ("ExternalEmissive_", 0.0),
    ("Blood_", 0.0), ("OxygenSaturation_", 0.0),
    ("PositiveTransitionNormal_", 0.0), ("VertexExpressionBone_", 0.0),
    ("Film_", 0.0), ("FilmThickness_", 0.0),
    ("Materia_", 0.0), ("MateriaContext_", 0.0),
    ("Gradient_", 0.0), ("Isotropy_", 0.0),
])

# Coordinate switches only tell UE which of its vertex UV slots a permutation
# reads. Blender resolves the corresponding UV-map names directly on the mesh,
# so they have no artist-facing material purpose and must not become custom
# properties. They remain present in renderer_ground_truth.json for provenance.
ENGINE_ONLY_SWITCHES = (
    "Coordinate0_", "Coordinate1_", "Coordinate2_", "Coordinate3_",
)

# Static switches exposed as material controls. This is the exact ground-truth
# union minus ENGINE_ONLY_SWITCHES.
KNOWN_SWITCHES = [
    "AnimateTime_", "Blood_", "BrokenFlowEmissive0_", "BrokenFlowEmissive1_",
    "BrokenFlow_", "Color_", "Convex_", "CoverageIdentifierCoordinate2_",
    "CoverageIdentifierCoordinate3_", "CoverageIdentifier_", "Coverage_",
    "CylindricalNormal_", "Deform_", "DetailColor_", "DetailCoverage_",
    "DetailFoam_", "DetailMetallic_", "DetailNormal_", "DetailOcclusion_",
    "DetailRoughness_", "Detail_", "Diffusion_", "Distribution_", "Emissive_",
    "ExternalEmissive_", "ExtraColor_", "ExtraEmissive_",
    "ExtraNormalizedCoordinate_", "ExtraPixelCoordinate_", "EyeMigration_",
    "Eye_", "Fabric_", "FilmStructure_", "FilmThickness_", "Film_",
    "FlowDetailFoam_", "FlowDetailNormal_", "FlowDetailRoughness_",
    "FlowDirection_", "FlowFoam_", "FlowNormal_", "FlowRoughness_", "Flow_",
    "Foam_", "Froth_", "GazeNormal_", "GenericVector_", "Ghost_",
    "GradientNormal_", "GradientOcclusion_", "GradientPhase_",
    "GradientRoughness_", "Gradient_", "Hair_", "HologramEye_", "Hologram_",
    "IrisColor_", "IrisEmissive_", "IrisNormal_", "IrisOcclusion_",
    "Isotropy_", "LayeredColor_", "Layered_", "MateriaContext_",
    "MateriaIndexed_", "Materia_", "Metallic_", "Muddiness_", "Normal_",
    "Occlusion_", "OceanGeometry_", "OceanMagnitude_", "Ocean_", "Opacity_",
    "OxygenSaturation_", "Phantom_", "PhaseGCrystal_", "PhaseGGlass_",
    "PhaseGWater_", "Pool_", "Pores_", "PositiveTransitionNormal_",
    "ReflectanceCrystal_", "ReflectanceGlass_", "ReflectanceWater_",
    "RenderPassWater_", "RigidBody_", "Roughness_", "ScleraNormal_",
    "SegmentLayer0_", "SegmentLayer1_", "Segmented_", "ShadingLayer_", "Skin_",
    "SkinnedBody_", "SoftBody_", "Standard_", "Subsurface_", "Thick_",
    "Thickness_", "Thin_", "Thinness_", "ToneGradient_",
    "TransmittanceCoefficient_", "Transmittance_", "TransparencyCoefficient_",
    "Transparency_", "Unlit_", "VertexExpressionBone_",
    "VertexExpressionNormal_", "VertexExpressionOcean_",
    "VertexExpressionPosition_", "VertexExpression_", "ViewCoordinate_",
    "WetnessTrickle_", "Wetness_", "WideBentNormal_", "WideFlowDirection_",
    "WideFlowDirectivity_", "WideFlowPhase_", "WideFoamThreshold_",
    "WideOcclusion_",
]

# Exact union of the three current-build RMI_Surface variants carrying Eye_.
# Do not retain a generic ubershader checkbox merely because it exists in a
# different surface family: it cannot select a path in an eye material.
_PROFILE_SWITCHES = {
    "Color_", "Emissive_", "ExternalEmissive_", "Eye_", "EyeMigration_",
    "GazeNormal_", "IrisColor_", "IrisEmissive_", "IrisNormal_",
    "IrisOcclusion_", "Normal_", "Occlusion_", "ScleraNormal_",
    "WideOcclusion_",
}
KNOWN_SWITCHES = [flag for flag in KNOWN_SWITCHES if flag in _PROFILE_SWITCHES]

# Exact identical-presence classes across the 104 current-build variants.
# Keep this table synchronized with scripts/renderer_ground_truth.json. A future
# breaker variant should split its class here as soon as it is observed.
COOCCURRENCE_GROUPS = [
    ("Blood_", "OxygenSaturation_"),
    ("BrokenFlowEmissive0_", "BrokenFlowEmissive1_", "BrokenFlow_",
     "WideFlowDirection_"),
    ("DetailColor_", "DetailMetallic_", "LayeredColor_"),
    ("DetailFoam_", "FlowDetailFoam_", "FlowDetailNormal_",
     "FlowDetailRoughness_", "FlowDirection_", "FlowFoam_", "FlowNormal_",
     "FlowRoughness_", "Flow_", "Foam_", "WideFoamThreshold_"),
    ("DetailNormal_", "DetailRoughness_"),
    ("Diffusion_", "Fabric_"),
    ("ExtraNormalizedCoordinate_", "ExtraPixelCoordinate_"),
    ("Eye_", "IrisColor_", "IrisNormal_", "ScleraNormal_"),
    ("FilmStructure_", "FilmThickness_", "Film_"),
    ("Froth_", "Pool_", "RenderPassWater_"),
    ("GradientNormal_", "GradientOcclusion_", "GradientPhase_",
     "GradientRoughness_", "Gradient_"),
    ("Hair_", "WideBentNormal_"),
    ("Layered_", "ShadingLayer_"),
    ("MateriaContext_", "MateriaIndexed_"),
    ("Materia_", "VertexExpressionNormal_"),
    ("Muddiness_", "TransmittanceCoefficient_", "Transmittance_",
     "TransparencyCoefficient_", "Transparency_"),
    ("OceanGeometry_", "OceanMagnitude_", "Ocean_", "VertexExpressionOcean_"),
    ("PhaseGCrystal_", "ReflectanceCrystal_"),
    ("PhaseGGlass_", "Thin_", "Thinness_"),
    ("PhaseGWater_", "ReflectanceWater_"),
    ("Pores_", "Skin_"),
    ("PositiveTransitionNormal_", "VertexExpressionBone_"),
    ("SegmentLayer0_", "SegmentLayer1_", "Segmented_"),
    ("WideFlowDirectivity_", "WideFlowPhase_"),
]

COOCCURRENCE_GROUPS = [
    tuple(member for member in members if member in KNOWN_SWITCHES)
    for members in COOCCURRENCE_GROUPS
]
COOCCURRENCE_GROUPS = [members for members in COOCCURRENCE_GROUPS if members]

_GROUP_FOR_SWITCH = {member: group for group in COOCCURRENCE_GROUPS
                     for member in group}
SWITCH_PROPERTY_PREFIX = "sw "
_MAX_ID_PROPERTY_NAME_LENGTH = 63


def _legacy_switch_control_name(members):
    """Return the property key emitted by pre-``sw `` master builds."""
    full = " + ".join(members)
    return (full if len(full) <= _MAX_ID_PROPERTY_NAME_LENGTH else
            "%s + ... + %s (%d flags)" %
            (members[0], members[-1], len(members)))


def _switch_control_name(members):
    """Return a short, alphabetically-grouped switch property key."""
    full = " + ".join(members)
    max_control_length = (_MAX_ID_PROPERTY_NAME_LENGTH -
                          len(SWITCH_PROPERTY_PREFIX))
    if len(full) <= max_control_length:
        return SWITCH_PROPERTY_PREFIX + full
    # The complete member list remains in the UI description and node label.
    # Keep the key below Blender's ID-property limit, including its switch prefix.
    short = "%s + ... (%d flags)" % (members[0], len(members))
    return SWITCH_PROPERTY_PREFIX + short[:max_control_length]


SWITCH_CONTROLS = []
for _flag in KNOWN_SWITCHES:
    _members = _GROUP_FOR_SWITCH.get(_flag, (_flag,))
    if _flag != _members[0]:
        continue
    _control = _switch_control_name(_members)
    _default = any(bool(_SWITCH_DEFAULTS.get(m, 0.0)) for m in _members)
    SWITCH_CONTROLS.append((_control, _members, _default))
CONTROL_FOR_SWITCH = {member: control for control, members, _default
                      in SWITCH_CONTROLS for member in members}

# Discrete selectors: integers, not floats -- a "Shading Model" of 2.5 is as
# meaningless as a switch of 0.37.  Drivers read ints fine.
ENUM_PROPS = [
    ("Shading Model", 0, 0, 6,
     strings.MATERIALS_SHADING_MODEL),
    ("Coverage Mode", 0, 0, 2,
     strings.MATERIALS_COVERAGE_MODE),
    ("Detail Blend", 0, 0, 2,
     strings.MATERIALS_DETAIL_BLEND),
    ("Vertex Expression Source", 0, 0, 2,
     strings.MATERIALS_VERTEX_EXPRESSION_SOURCE),
]
ENUM_PROPS = [prop for prop in ENUM_PROPS if prop[0] == "Shading Model"]

FLOAT_PROPS = [
    # name,                     default,             min,  max,  description
    ("Object Fade", 1.0, 0.0, 1.0, strings.MATERIALS_OBJECT_FADE),
    ("Opacity Clip", OPACITY_CLIP, 0.0, 1.0,
     strings.MATERIALS_OPACITY_CLIP),
    ("GBufferA.a", 0.645420, 0.0, 1.0,
     strings.MATERIALS_GBUFFERA_A),
    # --- eye (ff7r_eye_material_v2.py) ---
    ("Eye Cornea Slope", CORNEA_SLOPE, 0.0, 4.0, strings.MATERIALS_EYE_CORNEA_SLOPE),
    ("Eye Eta", ETA, 0.0, 2.0, strings.MATERIALS_EYE_ETA),
    ("Eye Depth Const", DEPTH_CONST, 0.0, 2.0, strings.MATERIALS_EYE_DEPTH_CONST),
    ("Eye Depth Falloff", DEPTH_FALLOFF, 0.0, 2.0, strings.MATERIALS_EYE_DEPTH_FALLOFF),
    ("Eye Depth Scale", DEPTH_SCALE, 0.0, 2.0, strings.MATERIALS_EYE_DEPTH_SCALE),
    ("Eye Mask Inner", MASK_INNER, 0.0, 2.0, strings.MATERIALS_EYE_MASK_INNER),
    ("Eye Mask Outer", MASK_OUTER, 0.0, 2.0, strings.MATERIALS_EYE_MASK_OUTER),
    ("Eye Limbal Offset", LIMBAL_OFFSET, 0.0, 2.0, strings.MATERIALS_EYE_LIMBAL_OFFSET),
    ("Eye Limbal Softness", LIMBAL_SOFTNESS, 0.0, 2.0, strings.MATERIALS_EYE_LIMBAL_SOFTNESS),
    ("Eye Limbal Aperture", LIMBAL_APERTURE, 0.0, 8.0, strings.MATERIALS_EYE_LIMBAL_APERTURE),
    ("Eye Limbal Amount", 1.0, 0.0, 1.0, strings.MATERIALS_EYE_LIMBAL_AMOUNT),
    ("Eye Iris AO Factor", 1, 0.0, 1.0,
     strings.MATERIALS_EYE_IRIS_AO_FACTOR),
    ("Pupil Dilation", 1.0, 0.05, 4.0, strings.MATERIALS_PUPIL_DILATION),
    # --- hair (ff7r_hair_material.py -- measured) ---
    ("Hair Min VdotT", MIN_VDOTT, 0.001, 0.5,
     strings.MATERIALS_HAIR_MIN_VDOTT),
    ("Hair Dither Sign", 1.0, 0.0, 1.0,
     strings.MATERIALS_HAIR_DITHER_SIGN),
    ("Hair Roughness Curvature", ROUGHNESS_CURVATURE, 0.0, 1.0,
     strings.MATERIALS_HAIR_ROUGHNESS_CURVATURE),
    ("Hair Anisotropic", HAIR_ANISOTROPIC, -1.0, 1.0,
     strings.MATERIALS_HAIR_ANISOTROPIC),
    ("Hair Flow Influence", FLOW_INFLUENCE, 0.0, 1.0,
     strings.MATERIALS_HAIR_FLOW_INFLUENCE),
    ("Hair Specular F0", HAIR_SPECULAR_F0, 0.0, 0.16,
     strings.MATERIALS_HAIR_SPECULAR_F0),
    # --- shared normal-map calibration ---
    ("Normal Map Strength", NORMAL_MAP_STRENGTH, 0.0, 2.0,
     strings.MATERIALS_NORMAL_MAP_STRENGTH),
    # --- detail layer ---
    ("Detail Normal Strength", 0.5, 0.0, 1.0,
     strings.MATERIALS_DETAIL_NORMAL_STRENGTH),
    # --- shading model parameters ---
    ("Subsurface Scale", 0.05, 0.0, 1.0, strings.MATERIALS_SUBSURFACE_SCALE),
    ("Sheen Roughness", 0.3, 0.0, 1.0, strings.MATERIALS_SHEEN_ROUGHNESS),
    # --- constant roles (PLAN 0.4: never a texture anywhere in the game) ---
    ("Isotropy", 0.0, 0.0, 1.0, strings.MATERIALS_ISOTROPY),
    ("Sheen", 1.0, 0.0, 1.0, strings.MATERIALS_SHEEN),
    ("Wetness", 0.0, 0.0, 1.0, strings.MATERIALS_WETNESS),
    ("DetailWetness", 0.0, 0.0, 1.0, strings.MATERIALS_DETAIL_WETNESS),
    ("Visibility", 1.0, 0.0, 1.0, strings.MATERIALS_VISIBILITY),
    ("FilmStructure", 0.4, 0.0, 1.0, strings.MATERIALS_FILM_STRUCTURE),
    ("ExtraColor", 0.0, 0.0, 1.0, strings.MATERIALS_EXTRA_COLOR),
    ("OxygenSaturation", 0.078, 0.0, 1.0,
     strings.MATERIALS_OXYGENSATURATION),
    ("DetailMetallic", 0.0, 0.0, 1.0, strings.MATERIALS_DETAILMETALLIC),
    ("Thickness", 0.2, 0.0, 1.0, strings.MATERIALS_THICKNESS),
    ("FilmThickness", 0.5, 0.0, 1.0, strings.MATERIALS_FILMTHICKNESS),
]

_PROFILE_FLOAT_PROPS = {
    "GBufferA.a", "Eye Cornea Slope", "Eye Eta", "Eye Depth Const",
    "Eye Depth Falloff", "Eye Depth Scale", "Eye Mask Inner", "Eye Mask Outer",
    "Eye Limbal Offset", "Eye Limbal Softness", "Eye Limbal Aperture",
    "Eye Limbal Amount", "Eye Iris AO Factor", "Pupil Dilation",
    "Normal Map Strength",
}
FLOAT_PROPS = [prop for prop in FLOAT_PROPS if prop[0] in _PROFILE_FLOAT_PROPS]


def _ensure_props(mat):
    """Initialize boolean switches, integer selectors, and float parameters."""
    renamed_switch_properties = {}
    for name, members, default in SWITCH_CONTROLS:
        # Upgrade the old one-property-per-flag and unprefixed grouped layouts
        # without losing an enabled member.  The visible ``sw `` prefix keeps
        # every boolean switch together in Blender's alphabetical list.
        legacy_names = set(members)
        legacy_names.add(_legacy_switch_control_name(members))
        legacy = [bool(mat[old_name]) for old_name in legacy_names
                  if old_name in mat]
        if name not in mat:
            mat[name] = any(legacy) if legacy else bool(default)
        try:
            mat.id_properties_ui(name).update(
                default=bool(default),
                description=(strings.MATERIALS_STATIC_SWITCH if len(members) == 1
                             else strings.MATERIALS_GROUPED_STATIC_SWITCH_PREFIX +
                             " + ".join(members)))
        except Exception:
            pass
        for old_name in legacy_names:
            if old_name in mat:
                renamed_switch_properties[old_name] = name
                del mat[old_name]
    # Existing masters keep their node tree when this script is upgraded.
    # Move each driver target along with its property so a renamed switch does
    # not silently become a permanently-zero node value.
    animation = getattr(getattr(mat, "node_tree", None), "animation_data", None)
    for curve in getattr(animation, "drivers", ()):
        for variable in curve.driver.variables:
            for target in variable.targets:
                old_name = next((old for old in renamed_switch_properties
                                 if target.id == mat and
                                 target.data_path == '["%s"]' % old), None)
                if old_name is not None:
                    target.data_path = '["%s"]' % renamed_switch_properties[old_name]
    for name, default, mn, mx, desc in ENUM_PROPS:
        if name not in mat:
            mat[name] = int(default)
        try:
            mat.id_properties_ui(name).update(
                min=mn, max=mx, soft_min=mn, soft_max=mx,
                default=int(default), description=desc)
        except Exception:
            pass
    for name, default, mn, mx, desc in FLOAT_PROPS:
        if name not in mat:
            mat[name] = float(default)
        try:
            mat.id_properties_ui(name).update(
                min=mn, max=mx, soft_min=mn, soft_max=mx,
                default=float(default), description=desc)
        except Exception:
            pass


def _drive(socket, mat, prop):
    """Bind a float socket to mat["prop"] with an AVERAGE driver over a single
    SINGLE_PROP variable -- a pass-through that needs no scripted expression, so
    it works without 'Auto Run Python Scripts'."""
    if socket is None:
        log("drive: no socket for %r" % prop)
        return None
    try:
        fc = socket.driver_add("default_value")
    except Exception:
        log("drive: driver_add failed for %r" % prop)
        return None
    if isinstance(fc, list):          # vector socket -- not supported here
        for f in fc:
            f.id_data.animation_data.drivers.remove(f)
        return None
    d = fc.driver
    d.type = "AVERAGE"
    v = d.variables.new()
    v.name = "p"
    v.type = "SINGLE_PROP"
    t = v.targets[0]
    t.id_type = "MATERIAL"
    t.id = mat
    t.data_path = '["%s"]' % prop
    return fc


def _bundle_material_properties(tree, property_sources, property_types,
                                props_frame):
    """Route driven material values through one bundle and one separator/frame.

    Blender's Ctrl+H on a node hides unused sockets.  The data-API equivalent
    is ``socket.hide = True``; after rewiring, every Separate Bundle therefore
    exposes only the outputs actually consumed inside its parent frame.

    Shading Model is intentionally absent: in Blender 5.2 it is a Constant Menu,
    not a driven material-property value, and Menu enum definitions do not
    survive independently declared bundle signatures.
    """
    if not HAS_BUNDLES:
        return {}

    # Capture the existing direct property links before the Combine Bundle is
    # added, otherwise its own inputs would be mistaken for destinations.
    routes = []
    for prop_name, source in property_sources.items():
        if prop_name == "Shading Model" or not source.outputs:
            continue
        for link in list(source.outputs[0].links):
            frame = getattr(link.to_node, "parent", None)
            if frame is not None and frame != props_frame:
                routes.append((prop_name, link, frame))

    bundled_names = [name for name in property_sources if name != "Shading Model"]
    # Blender 5.x only: no 4.5 dump position exists for these, so the bundle
    # sits one column right of the float parameters, and each Separate Bundle
    # just above the frame that consumes it.
    combine = _new(tree, "NodeCombineBundle", "MaterialPropertiesBundle",
                   (FLOAT_COLUMN[0] + 400, FLOAT_COLUMN[1]),
                   "All material custom properties", props_frame)
    combine.define_signature = True
    combine_socket_names = {}
    for prop_name in bundled_names:
        item = combine.bundle_items.new(property_types[prop_name], prop_name)
        # Bundle paths sanitise punctuation (`+`/`.` become `_`). Retain the
        # actual socket name returned by Blender instead of assuming the label.
        combine_socket_names[prop_name] = item.name
        _link(tree, property_sources[prop_name], 0, combine, item.name)

    separators = {}
    separator_socket_names = {}
    used = {}
    for prop_name, old_link, frame in routes:
        frame_key = frame.name
        sep = separators.get(frame_key)
        if sep is None:
            key = frame_key.replace("FRAME_", "")
            origin = FRAME_ORIGIN.get(key, (-600, 400))
            sep = _new(tree, "NodeSeparateBundle", "PROPS_" + frame_key,
                       BUNDLE_SEPARATOR_POS.get(
                           key, (origin[0] + FRAME_PAD[0],
                                 origin[1] + BUNDLE_SEPARATOR_DY)),
                       "Material properties used here", frame)
            sep.define_signature = True
            names = {}
            for bundled_name in bundled_names:
                item = sep.bundle_items.new(property_types[bundled_name], bundled_name)
                names[bundled_name] = item.name
            _link(tree, combine, "Bundle", sep, "Bundle")
            separators[frame_key] = sep
            separator_socket_names[frame_key] = names
            used[frame_key] = set()
        destination = old_link.to_socket
        tree.links.remove(old_link)
        try:
            socket_name = separator_socket_names[frame_key][prop_name]
            tree.links.new(sep.outputs[socket_name], destination)
            used[frame_key].add(socket_name)
        except Exception:
            log("bundle link refused: %s -> %s" %
                (prop_name, getattr(destination.node, "name", "?")))

    # Python equivalent of selecting every Separate Bundle and pressing Ctrl+H.
    for frame_key, sep in separators.items():
        visible = used[frame_key]
        for socket in sep.outputs:
            if socket.bl_idname != "NodeSocketVirtual":
                socket.hide = socket.name not in visible
    return separators


# ------------------------------------------------------------- node layout --
# Every position below is an ABSOLUTE canvas coordinate, transcribed from the
# arranged graph in Blender 4.5 -- 4.x draws the widest nodes, so a layout that
# reads cleanly there reads cleanly on 5.x too.  Absolute is what build() can
# use directly: while it runs, every frame is still at the origin, and Blender
# rebases each frame around its children on the first redraw, leaving them at
# FRAME_PAD from the frame's own corner.
FRAME_ORIGIN = {
    "Props": (-2182, 2965), "Coords": (-757, 3434),
    "Base": (-138, 2630), "Coverage": (-141, 270), "Detail": (-137, -450),
    "SkinCloth": (808, -93), "Segment": (813, -757), "Emissive": (-133, -2240),
    "Hair": (797, 2502), "Transition": (814, -2266), "Eye": (802, 2173),
    "Shade": (1767, 1177), "EyePath": (1952, 2484), "HairPath": (1903, 1554),
    "Out": (4375, 2301),
}
FRAME_PAD = (30, -39)       # offset a shrunk frame leaves its first child at

# The OUTPUT frame holds a different node set per build -- three seven-rung
# comparison ladders below 5.2, four compact Menu-Switch-fed mixes on 5.2 --
# so the two are arranged separately, each transcribed from its own version.
OUT_POS = {                 # <5.2 ladder build, arranged in 4.5
    "BloodOverride": (4513, 2261), "Principled BSDF": (5173, 1261),
    "Material Output": (5573, 1261), "EmissionSum": (4545, -342),
    "EmissionStrength": (4628, 43), "MetallicGate": (4405, 115),
    "MetallicModelGate": (4615, 221),
}
OUT_POS_MENU = {            # 5.2 Menu Switch build, arranged in 5.2
    "SM_BaseColor": (4425, 1925), "SM_Normal_Hair": (4559, 1455),
    "SM_Normal": (4758, 1447), "SM_Roughness": (4596, 1671),
    "SM_Roughness_Eye": (4770, 1671),
    "BloodOverride": (4591, 1925), "Principled BSDF": (5173, 1261),
    "Material Output": (5573, 1261), "EmissionSum": (4649, 559),
    "EmissionStrength": (4819, 416), "MetallicGate": (4558, 1226),
    "MetallicModelGate": (4771, 1231),
}

# Separate Bundle nodes (5.x only) sit above the frame that consumes them;
# the OUTPUT one is hand-placed inside its own busier frame.
BUNDLE_SEPARATOR_DY = 300
BUNDLE_SEPARATOR_POS = {"Out": (4364, 1234)}

# Driven property columns, in the Props frame.
PROP_ROW_PITCH = 150
SWITCH_COLUMNS = ((-2151, 2925), (-1759, 2324))   # x, first y, per column
SWITCH_COLUMN_LEN = 40      # switches per column; a longer list runs the last
                            # column past its neighbour rather than losing rows
ENUM_COLUMN = (-1751, 2925)
FLOAT_COLUMN = (-1351, 2925)

# Coordinate frame, and the texture slots inside each TEXTURES frame.
UV_COLUMN = (-727, 3394)
UV_ROW_PITCH = 200
SLOT_ROW_PITCH = 380
SLOT_USE_DX = 292           # neutral/texture Mix, x offset from its image node


def _out_pos(name):
    """Where `name` goes in the OUTPUT frame, for the build being run."""
    return (OUT_POS_MENU if HAS_MANUAL_MENU_SWITCH else OUT_POS)[name]


# --------------------------------------------------------- menu abstraction --

# A Mix node draws its data-type and blend-mode dropdowns even when the
# ladder does not use them, so each rung measures roughly 140 x 220.
# Keep MENU_ROW_PITCH above ~230 and column offsets more than ~180 apart
# to prevent rungs from overlapping each other or the next menu.
MENU_ROW_PITCH = 280
MENU_COL_VAL = 320
MENU_COL_EQ = 620
MENU_COL_MIX = 920
# Where each <5.2 fallback ladder starts; it grows right and down from there.
# The 5.2 Menu Switch build has no ladders at all, and lays its selectors out
# inside the OUTPUT frame instead -- see OUT_POS_MENU.
MENU_ANCHOR = {"SM_BaseColor": (7406, 4290),
               "SM_Normal": (7408, 2068),
               "SM_Roughness": (7411, 6237)}


def _menu(tree, name, loc, items, data_type="FLOAT", label="", parent=None,
          selector_src=None, manual=False):
    """One N-way selector.  Returns (out_node, selector_socket, value_sockets).

    With ``manual=True``, use a real Blender 5.2 Menu Switch whenever one is
    available.  Its default may be set through Python, but cannot have a
    live driver.  Other selectors use a real Menu Switch only once Blender
    makes that socket drivable; until then they retain the property-driven
    comparison ladder."""
    if HAS_MENU_SWITCH or (manual and HAS_MANUAL_MENU_SWITCH):
        n = _new(tree, MENU_SWITCH_IDNAME, name, loc, label or "Menu", parent)
        _prop(n, "data_type", data_type)
        try:
            n.enum_items.clear()
            for it in items:
                n.enum_items.new(it)
            # Replacing the default A/B labels clears Menu's selection.
            # Initialise manual menus to option zero; variant application
            # overwrites this with the imported shading model.
            n.inputs[0].default_value = items[0]
        except Exception:
            log("menu items failed on %s" % name)
        if selector_src is not None:
            selector_node, selector_output = selector_src
            _link(tree, selector_node, selector_output, n, 0)
        return n, n.inputs[0], list(n.inputs)[1:]

    holder = _frame(tree, name + "_frame",
                    (label or "Menu") + "   [<5.2 fallback ladder]", parent)
    caption = "Selector  " + " / ".join("%d=%s" % (i, s)
                                        for i, s in enumerate(items))
    if selector_src is not None:
        sel_node, sel_out = selector_src
        sel_socket = sel_node.outputs[sel_out]
        sel = None
    else:
        sel = _new(tree, "ShaderNodeValue", name + "_selector", loc, caption, holder)
        sel_socket = sel.outputs[0]
    values, prev = [], None
    for i, it in enumerate(items):
        v = _new(tree, "ShaderNodeMix", "%s_val%d" % (name, i),
                 (loc[0] + MENU_COL_VAL, loc[1] - i * MENU_ROW_PITCH),
                 "%d: %s" % (i, it), holder)
        _prop(v, "data_type", data_type)
        # v is used purely as a value HOLDER -- _menu_feed()/_menu_set() only
        # ever write to its "A" input, and every caller (e.g. the per-model
        # loops in build()) expects v's Result to equal whatever was put into
        # A. That only holds if Factor is pinned to 0 (same reasoning as the
        # identical `_sv(byp, "Factor", 0.0)` in _tex_slot()); left at the new
        # -node default of 0.5 -- with B also left at its default -- v's
        # Result silently blends toward B and option 0 in particular (which
        # skips the compare/select ladder below entirely and is returned
        # as-is when i == 0) comes out wrong for EVERY caller of this menu.
        _sv(v, "Factor", 0.0)
        values.append(v)
        if i == 0:
            prev = v
            continue
        c = _new(tree, "ShaderNodeMath", "%s_eq%d" % (name, i),
                 (loc[0] + MENU_COL_EQ, loc[1] - i * MENU_ROW_PITCH + 110),
                 "selector == %d" % i, holder)
        _prop(c, "operation", "COMPARE")
        _sv(c, 1, float(i))
        _sv(c, 2, 0.5)
        try:
            tree.links.new(sel_socket, c.inputs[0])
        except Exception:
            log('menu selector link failed')
        m = _new(tree, "ShaderNodeMix", "%s_mix%d" % (name, i),
                 (loc[0] + MENU_COL_MIX, loc[1] - i * MENU_ROW_PITCH),
                 "select: %s" % it, holder)
        _prop(m, "data_type", data_type)
        _link(tree, c, 0, m, "Factor")
        _link(tree, prev, "Result", m, "A")
        _link(tree, v, "Result", m, "B")
        prev = m
    return prev, sel_socket, [_in(v, "A") for v in values]


def _menu_out(node):
    # Manual Blender 5.2 menus intentionally exist even though HAS_MENU_SWITCH
    # is False (that flag means *drivable*).  Inspect the actual node rather
    # than the global capability flag, otherwise their Output socket is never
    # connected to the shader.
    return 0 if getattr(node, "bl_idname", "") == MENU_SWITCH_IDNAME else "Result"


def _menu_feed(tree, vals, index, source, out=0):
    if index >= len(vals) or vals[index] is None:
        log("menu option %d missing" % index)
        return
    try:
        tree.links.new(source.outputs[out], vals[index])
    except Exception:
        log("menu feed failed at option %d" % index)


def _menu_set(vals, index, value):
    if index >= len(vals) or vals[index] is None:
        return
    tgt = vals[index]
    try:
        dv = tgt.default_value
        if hasattr(dv, "__len__") and not isinstance(dv, str):
            n = len(dv)
            v = list(value) if hasattr(value, "__len__") else [value] * n
            tgt.default_value = (v + [1.0] * n)[:n]
        else:
            tgt.default_value = value
    except Exception:
        pass


# ============================================================ UTILITY GROUPS ==

def util_tbn():
    """Explicit tangent frame.  Blender's Tangent node gives T but no bitangent
    sign, so w = sign(dot(B_signed, cross(N,T))) recovers handedness."""
    def _b(g):
        _sock(g, "T", "OUTPUT", "NodeSocketVector")
        _sock(g, "B", "OUTPUT", "NodeSocketVector")
        _sock(g, "N", "OUTPUT", "NodeSocketVector")
        _sock(g, "w", "OUTPUT", "NodeSocketFloat")
        go = _new(g, "NodeGroupOutput", "Group Output", (620, 0))
        tan = _new(g, "ShaderNodeTangent", "Tangent", (-620, 140), "UV tangent")
        _prop(tan, "direction_type", "UV_MAP")
        geo = _new(g, "ShaderNodeNewGeometry", "Geometry", (-620, -80))
        nmap = _new(g, "ShaderNodeNormalMap", "Signed B", (-620, -320),
                    "flat green map -> signed bitangent")
        # Synthetic handedness probe, not a sampled normal map.
        _sv(nmap, "Strength", 1.0)
        _sv(nmap, "Color", (0.5, 1.0, 0.5, 1.0))
        cr = _new(g, "ShaderNodeVectorMath", "cross", (-380, -20), "cross(N, T)")
        _prop(cr, "operation", "CROSS_PRODUCT")
        dt = _new(g, "ShaderNodeVectorMath", "dot", (-180, -180),
                  "dot(B_signed, cross(N,T))")
        _prop(dt, "operation", "DOT_PRODUCT")
        sg = _new(g, "ShaderNodeMath", "sign", (20, -180), "w = +/-1")
        _prop(sg, "operation", "SIGN")
        bsc = _new(g, "ShaderNodeVectorMath", "B", (240, -20), "B = w*cross(N,T)")
        _prop(bsc, "operation", "SCALE")
        _link(g, geo, "Normal", cr, 0)
        _link(g, tan, 0, cr, 1)
        _link(g, nmap, 0, dt, 0)
        _link(g, cr, 0, dt, 1)
        _link(g, dt, "Value", sg, 0)
        _link(g, cr, 0, bsc, 0)
        _link(g, sg, 0, bsc, "Scale")
        _link(g, tan, 0, go, "T")
        _link(g, bsc, 0, go, "B")
        _link(g, geo, "Normal", go, "N")
        _link(g, sg, 0, go, "w")
    return _rebuild_group("FF7R Util/TBN", _b)


def util_tangent_to_world(uv_map=UV_MAP):
    """Tangent-space vector -> world, through a mikktspace Normal Map node.

    From ff7r_hair_material.py.  UE generates ONE vertex tangent frame (from
    UV0) and uses it for every tangent-space vector regardless of which UV the
    texture was sampled on -- so UV0 is the shader-exact basis for slot 14 too,
    even though slot 14 is sampled on UV1. Named-UV variants are separate node
    groups so importing a mesh with another UV0 name cannot rewrite the basis
    underneath materials that already use this transform.

    ``Vector`` stays in the source map's DirectX convention through all
    tangent-space layer maths.  Blender 5.2+'s Normal Map node converts it to
    Blender's convention exactly once here; older builds receive the same
    conversion through ``_fix_conventions`` after the group is built."""
    group_name = ("UE Tangent To World (mikktspace)" if not uv_map else
                  "UE Tangent To World (mikktspace, %s)" % uv_map)
    def _b(g):
        _sock(g, "Vector", "OUTPUT", "NodeSocketVector")
        _sock(g, "Vector", "INPUT", "NodeSocketVector", (0.0, 0.0, 1.0))
        _sock(g, "Normal Map Strength", "INPUT", "NodeSocketFloat",
              NORMAL_MAP_STRENGTH, 0.0, 2.0)
        gi = _new(g, "NodeGroupInput", "Group Input", (-520, 0))
        go = _new(g, "NodeGroupOutput", "Group Output", (320, 0))
        enc = _new(g, "ShaderNodeVectorMath", "encode", (-300, 0),
                   "encode to 0..1")
        _prop(enc, "operation", "MULTIPLY_ADD")
        _sv(enc, 1, (0.5, 0.5, 0.5))
        _sv(enc, 2, (0.5, 0.5, 0.5))
        nm = _new(g, "ShaderNodeNormalMap", "TBN", (-80, 0),
                  "mikktspace TBN (%s basis)" % (uv_map or "active UV"))
        _prop(nm, "uv_map", uv_map)
        _convention(nm, "DIRECTX")
        _link(g, gi, "Vector", enc, 0)
        _link(g, enc, 0, nm, "Color")
        _link(g, gi, "Normal Map Strength", nm, "Strength")
        _link(g, nm, "Normal", go, "Vector")
        _fix_conventions(g)
    return _rebuild_group(group_name, _b)


def util_frame_to_world():
    """Explicit TBN transform: v -> T*v.x + B*v.y + N*v.z, normalised.
    Verbatim from ff7r_eye_material_v2.py -- the eye groups index its sockets
    positionally, so the socket ORDER here must not change."""
    def _b(g):
        _sock(g, "Vector", "OUTPUT", "NodeSocketVector")
        _sock(g, "T", "INPUT", "NodeSocketVector")
        _sock(g, "B", "INPUT", "NodeSocketVector")
        _sock(g, "N", "INPUT", "NodeSocketVector")
        _sock(g, "Vector", "INPUT", "NodeSocketVector")
        gi = _new(g, "NodeGroupInput", "Group Input", (-900, 0))
        go = _new(g, "NodeGroupOutput", "Group Output", (900, 0))
        sep = _new(g, "ShaderNodeSeparateXYZ", "Separate XYZ", (-500, -220))
        a = _new(g, "ShaderNodeVectorMath", "Vector Math", (-280, 220), "T * v.x")
        _prop(a, "operation", "SCALE")
        b = _new(g, "ShaderNodeVectorMath", "Vector Math.001", (-280, 40), "B * v.y")
        _prop(b, "operation", "SCALE")
        c = _new(g, "ShaderNodeVectorMath", "Vector Math.002", (-280, -140), "N * v.z")
        _prop(c, "operation", "SCALE")
        d = _new(g, "ShaderNodeVectorMath", "Vector Math.003", (-60, 140))
        _prop(d, "operation", "ADD")
        e = _new(g, "ShaderNodeVectorMath", "Vector Math.004", (130, 60))
        _prop(e, "operation", "ADD")
        f = _new(g, "ShaderNodeVectorMath", "Vector Math.005", (330, 0))
        _prop(f, "operation", "NORMALIZE")
        _link(g, gi, 3, sep, 0)
        _link(g, gi, 0, a, 0)
        _link(g, sep, 0, a, 3)
        _link(g, gi, 1, b, 0)
        _link(g, sep, 1, b, 3)
        _link(g, gi, 2, c, 0)
        _link(g, sep, 2, c, 3)
        _link(g, a, 0, d, 0)
        _link(g, b, 0, d, 1)
        _link(g, d, 0, e, 0)
        _link(g, c, 0, e, 1)
        _link(g, e, 0, f, 0)
        _link(g, f, 0, go, 0)
        _fix_conventions(g)
    return _rebuild_group("UE Frame To World (explicit TBN)", _b)


def util_slerp():
    """Spherical normal blend -- what Detail_ AND PositiveTransitionNormal_ both
    do (PLAN tier 1, two independent shaders).  theta is clamped away from 0
    because the shader relied on GPU flush behaviour Blender does not
    reproduce; without the guard this NaNs in the common case (PLAN 2.8)."""
    def _b(g):
        _sock(g, "Normal", "OUTPUT", "NodeSocketVector")
        _sock(g, "A", "INPUT", "NodeSocketVector", (0.0, 0.0, 1.0))
        _sock(g, "B", "INPUT", "NodeSocketVector", (0.0, 0.0, 1.0))
        _sock(g, "t", "INPUT", "NodeSocketFloat", 0.0, 0.0, 1.0)
        _sock(g, "Fast (lerp)", "INPUT", "NodeSocketFloat", 0.0, 0.0, 1.0)
        gi = _new(g, "NodeGroupInput", "Group Input", (-980, 0))
        go = _new(g, "NodeGroupOutput", "Group Output", (980, 0))
        d = _new(g, "ShaderNodeVectorMath", "dot", (-760, 260), "dot(A,B)")
        _prop(d, "operation", "DOT_PRODUCT")
        cl = _new(g, "ShaderNodeMath", "clampdot", (-580, 260), "min(dot, 0.9999)")
        _prop(cl, "operation", "MINIMUM")
        _sv(cl, 1, 0.9999)
        th = _new(g, "ShaderNodeMath", "theta", (-400, 260), "theta = acos(dot)")
        _prop(th, "operation", "ARCCOSINE")
        thg = _new(g, "ShaderNodeMath", "theta_guard", (-220, 260),
                   "max(theta, 1e-3)   <- PLAN 2.8 singularity guard")
        _prop(thg, "operation", "MAXIMUM")
        _sv(thg, 1, 0.001)
        omt = _new(g, "ShaderNodeMath", "one_minus_t", (-400, 60), "1 - t")
        _prop(omt, "operation", "SUBTRACT")
        _sv(omt, 0, 1.0)
        sa = _new(g, "ShaderNodeMath", "mulA", (-20, 160), "theta*(1-t)")
        _prop(sa, "operation", "MULTIPLY")
        sb = _new(g, "ShaderNodeMath", "mulB", (-20, -20), "theta*t")
        _prop(sb, "operation", "MULTIPLY")
        sna = _new(g, "ShaderNodeMath", "sinA", (160, 160), "sin")
        _prop(sna, "operation", "SINE")
        snb = _new(g, "ShaderNodeMath", "sinB", (160, -20), "sin")
        _prop(snb, "operation", "SINE")
        pa = _new(g, "ShaderNodeVectorMath", "scaleA", (360, 200),
                  "A * sin(theta(1-t))")
        _prop(pa, "operation", "SCALE")
        pb = _new(g, "ShaderNodeVectorMath", "scaleB", (360, 20),
                  "B * sin(theta t)")
        _prop(pb, "operation", "SCALE")
        ad = _new(g, "ShaderNodeVectorMath", "add", (560, 120))
        _prop(ad, "operation", "ADD")
        nz = _new(g, "ShaderNodeVectorMath", "normalize", (720, 120))
        _prop(nz, "operation", "NORMALIZE")
        lp = _new(g, "ShaderNodeMix", "lerp", (560, -260), "fast path: plain mix")
        _prop(lp, "data_type", "VECTOR")
        lpn = _new(g, "ShaderNodeVectorMath", "lerp_norm", (720, -260))
        _prop(lpn, "operation", "NORMALIZE")
        sel = _new(g, "ShaderNodeMix", "select", (860, -60), "slerp / fast")
        _prop(sel, "data_type", "VECTOR")
        _link(g, gi, "A", d, 0)
        _link(g, gi, "B", d, 1)
        _link(g, d, "Value", cl, 0)
        _link(g, cl, 0, th, 0)
        _link(g, th, 0, thg, 0)
        _link(g, gi, "t", omt, 1)
        _link(g, thg, 0, sa, 0)
        _link(g, omt, 0, sa, 1)
        _link(g, thg, 0, sb, 0)
        _link(g, gi, "t", sb, 1)
        _link(g, sa, 0, sna, 0)
        _link(g, sb, 0, snb, 0)
        _link(g, gi, "A", pa, 0)
        _link(g, sna, 0, pa, "Scale")
        _link(g, gi, "B", pb, 0)
        _link(g, snb, 0, pb, "Scale")
        _link(g, pa, 0, ad, 0)
        _link(g, pb, 0, ad, 1)
        _link(g, ad, 0, nz, 0)
        _link(g, gi, "t", lp, "Factor")
        _link(g, gi, "A", lp, "A")
        _link(g, gi, "B", lp, "B")
        _link(g, lp, "Result", lpn, 0)
        _link(g, gi, "Fast (lerp)", sel, "Factor")
        _link(g, nz, 0, sel, "A")
        _link(g, lpn, 0, sel, "B")
        _link(g, sel, "Result", go, "Normal")
    return _rebuild_group("FF7R Util/Normal Slerp", _b)


def util_detail_normal_additive():
    """Apply a detail normal as a tangent-space perturbation of ``Base``.

    A detail normal is *not* a second complete surface normal to interpolate
    toward.  In particular, the neutral texel (0, 0, 1) means "no detail",
    so it must leave Base unchanged at every mask value.  The character shader
    uses a spherical ramp for the detail amount; retain that ramp by slerping
    from the flat tangent normal to Detail, then compose that delta over Base
    with RNM.  Slerping Base directly to Detail instead biases every base map
    toward flat whenever a detail layer is enabled.
    """
    def _b(g):
        _sock(g, "Normal", "OUTPUT", "NodeSocketVector")
        _sock(g, "Base", "INPUT", "NodeSocketVector", (0.0, 0.0, 1.0))
        _sock(g, "Detail", "INPUT", "NodeSocketVector", (0.0, 0.0, 1.0))
        _sock(g, "t", "INPUT", "NodeSocketFloat", 0.0, 0.0, 1.0)
        gi = _new(g, "NodeGroupInput", "Group Input", (-720, 0))
        go = _new(g, "NodeGroupOutput", "Group Output", (560, 0))
        amount = _grp(g, "FF7R Util/Normal Slerp", "detail_amount", (-480, -120),
                      "flat -> detail (spherical amount)")
        _sv(amount, "A", (0.0, 0.0, 1.0))
        compose = _grp(g, "FF7R Util/RNM", "compose", (120, 40),
                       "Base + detail perturbation")
        _sv(compose, "Strength", 1.0)
        _link(g, gi, "Detail", amount, "B")
        _link(g, gi, "t", amount, "t")
        _link(g, gi, "Base", compose, "Base")
        _link(g, amount, "Normal", compose, "Detail")
        _link(g, compose, "Normal", go, "Normal")
    return _rebuild_group("FF7R Util/Detail Normal Additive", _b)


def util_rnm():
    """Reoriented normal mapping used by the MEC/environment detail path.

    This is the algebra in M_Tile_Rock_Granite_06A_MainPS_19457e58.txt,
    decompiler lines 493-511, after its screen-derivative basis alignment:

        t = base + (0, 0, 1)
        u = (-detail.x, -detail.y, detail.z)
        r = normalize(t * dot(t, u) - u * t.z)

    The shader's derivative work maps independently sampled normals into one
    tangent frame. Blender's Normal Map/TBN stage provides that common frame,
    so the portable node group starts at the actual RNM operation. Strength
    scales the detail away by blending it toward the flat tangent normal first.
    """
    def _b(g):
        _sock(g, "Normal", "OUTPUT", "NodeSocketVector")
        _sock(g, "Base", "INPUT", "NodeSocketVector", (0.0, 0.0, 1.0))
        _sock(g, "Detail", "INPUT", "NodeSocketVector", (0.0, 0.0, 1.0))
        _sock(g, "Strength", "INPUT", "NodeSocketFloat", 1.0, 0.0, 1.0)
        gi = _new(g, "NodeGroupInput", "Group Input", (-1100, 0))
        go = _new(g, "NodeGroupOutput", "Group Output", (1050, 0))
        dmix = _new(g, "ShaderNodeMix", "detail_strength", (-880, -220),
                    "flat -> detail")
        _prop(dmix, "data_type", "VECTOR")
        _sv(dmix, "A", (0.0, 0.0, 1.0))
        t = _new(g, "ShaderNodeVectorMath", "t", (-660, 220),
                 "t = base + (0,0,1)")
        _prop(t, "operation", "ADD")
        _sv(t, 1, (0.0, 0.0, 1.0))
        dsep = _new(g, "ShaderNodeSeparateXYZ", "detail_xyz", (-460, -220))
        nx = _new(g, "ShaderNodeMath", "neg_x", (-260, -100))
        _prop(nx, "operation", "MULTIPLY")
        _sv(nx, 1, -1.0)
        ny = _new(g, "ShaderNodeMath", "neg_y", (-260, -260))
        _prop(ny, "operation", "MULTIPLY")
        _sv(ny, 1, -1.0)
        u = _new(g, "ShaderNodeCombineXYZ", "u", (-40, -180),
                 "u = (-detail.x,-detail.y,detail.z)")
        dot = _new(g, "ShaderNodeVectorMath", "dot_tu", (180, 180), "dot(t,u)")
        _prop(dot, "operation", "DOT_PRODUCT")
        tdot = _new(g, "ShaderNodeVectorMath", "t_dot", (400, 180),
                    "t * dot(t,u)")
        _prop(tdot, "operation", "SCALE")
        tsep = _new(g, "ShaderNodeSeparateXYZ", "t_xyz", (180, -100))
        utz = _new(g, "ShaderNodeVectorMath", "u_tz", (400, -100), "u * t.z")
        _prop(utz, "operation", "SCALE")
        sub = _new(g, "ShaderNodeVectorMath", "r", (640, 80),
                   "t*dot(t,u) - u*t.z")
        _prop(sub, "operation", "SUBTRACT")
        norm = _new(g, "ShaderNodeVectorMath", "normalize", (840, 80))
        _prop(norm, "operation", "NORMALIZE")
        _link(g, gi, "Strength", dmix, "Factor")
        _link(g, gi, "Detail", dmix, "B")
        _link(g, gi, "Base", t, 0)
        _link(g, dmix, "Result", dsep, 0)
        _link(g, dsep, "X", nx, 0)
        _link(g, dsep, "Y", ny, 0)
        _link(g, nx, 0, u, "X")
        _link(g, ny, 0, u, "Y")
        _link(g, dsep, "Z", u, "Z")
        _link(g, t, 0, dot, 0)
        _link(g, u, 0, dot, 1)
        _link(g, t, 0, tdot, 0)
        _link(g, dot, "Value", tdot, "Scale")
        _link(g, t, 0, tsep, 0)
        _link(g, u, 0, utz, 0)
        _link(g, tsep, "Z", utz, "Scale")
        _link(g, tdot, 0, sub, 0)
        _link(g, utz, 0, sub, 1)
        _link(g, sub, 0, norm, 0)
        _link(g, norm, 0, go, "Normal")
    return _rebuild_group("FF7R Util/RNM", _b)


def util_ao_combine():
    """m=l1*l2; n=min(l1,l2); t=m+1-n; AO=(1-t^5)^5*(m-n)+n   (PLAN tier 1).

    Identical to the hair script's "UE SoftMin Occlusion" -- expanding both
    forms gives the same expression, an independent confirmation of the decode.
    Kept as one group rather than two doing the same thing."""
    def _b(g):
        _sock(g, "AO", "OUTPUT", "NodeSocketFloat")
        _sock(g, "L1", "INPUT", "NodeSocketFloat", 1.0, 0.0, 1.0)
        _sock(g, "L2", "INPUT", "NodeSocketFloat", 1.0, 0.0, 1.0)
        gi = _new(g, "NodeGroupInput", "Group Input", (-760, 0))
        go = _new(g, "NodeGroupOutput", "Group Output", (800, 0))
        m = _new(g, "ShaderNodeMath", "m", (-540, 140), "m = l1*l2")
        _prop(m, "operation", "MULTIPLY")
        n = _new(g, "ShaderNodeMath", "n", (-540, -80), "n = min(l1,l2)")
        _prop(n, "operation", "MINIMUM")
        t1 = _new(g, "ShaderNodeMath", "t1", (-360, 80), "m + 1")
        _prop(t1, "operation", "ADD")
        _sv(t1, 1, 1.0)
        t = _new(g, "ShaderNodeMath", "t", (-200, 80), "t = m+1-n")
        _prop(t, "operation", "SUBTRACT")
        p5 = _new(g, "ShaderNodeMath", "t5", (-40, 80), "t^5")
        _prop(p5, "operation", "POWER")
        _sv(p5, 1, 5.0)
        om = _new(g, "ShaderNodeMath", "om", (120, 80), "1 - t^5")
        _prop(om, "operation", "SUBTRACT")
        _sv(om, 0, 1.0)
        q5 = _new(g, "ShaderNodeMath", "q5", (280, 80), "(1-t^5)^5")
        _prop(q5, "operation", "POWER")
        _sv(q5, 1, 5.0)
        df = _new(g, "ShaderNodeMath", "diff", (280, -160), "m - n")
        _prop(df, "operation", "SUBTRACT")
        mu = _new(g, "ShaderNodeMath", "mul", (460, -40))
        _prop(mu, "operation", "MULTIPLY")
        adn = _new(g, "ShaderNodeMath", "add_n", (620, -40), "+ n")
        _prop(adn, "operation", "ADD")
        _prop(adn, "use_clamp", True)
        _link(g, gi, "L1", m, 0)
        _link(g, gi, "L2", m, 1)
        _link(g, gi, "L1", n, 0)
        _link(g, gi, "L2", n, 1)
        _link(g, m, 0, t1, 0)
        _link(g, t1, 0, t, 0)
        _link(g, n, 0, t, 1)
        _link(g, t, 0, p5, 0)
        _link(g, p5, 0, om, 1)
        _link(g, om, 0, q5, 0)
        _link(g, m, 0, df, 0)
        _link(g, n, 0, df, 1)
        _link(g, q5, 0, mu, 0)
        _link(g, df, 0, mu, 1)
        _link(g, mu, 0, adn, 0)
        _link(g, n, 0, adn, 1)
        _link(g, adn, 0, go, "AO")
    return _rebuild_group("FF7R Util/AO Combine", _b)


def util_rough_combine():
    """sqrt(saturate(r1^2 + r2^2))   (PLAN tier 1)"""
    def _b(g):
        _sock(g, "Roughness", "OUTPUT", "NodeSocketFloat")
        _sock(g, "R1", "INPUT", "NodeSocketFloat", 0.5, 0.0, 1.0)
        _sock(g, "R2", "INPUT", "NodeSocketFloat", 0.0, 0.0, 1.0)
        gi = _new(g, "NodeGroupInput", "Group Input", (-560, 0))
        go = _new(g, "NodeGroupOutput", "Group Output", (560, 0))
        a = _new(g, "ShaderNodeMath", "r1sq", (-340, 100), "r1^2")
        _prop(a, "operation", "MULTIPLY")
        b = _new(g, "ShaderNodeMath", "r2sq", (-340, -100), "r2^2")
        _prop(b, "operation", "MULTIPLY")
        s = _new(g, "ShaderNodeMath", "sum", (-120, 0), "saturate(sum)")
        _prop(s, "operation", "ADD")
        _prop(s, "use_clamp", True)
        q = _new(g, "ShaderNodeMath", "sqrt", (80, 0), "sqrt")
        _prop(q, "operation", "SQRT")
        _link(g, gi, "R1", a, 0)
        _link(g, gi, "R1", a, 1)
        _link(g, gi, "R2", b, 0)
        _link(g, gi, "R2", b, 1)
        _link(g, a, 0, s, 0)
        _link(g, b, 0, s, 1)
        _link(g, s, 0, q, 0)
        _link(g, q, 0, go, "Roughness")
    return _rebuild_group("FF7R Util/Roughness Combine", _b)


def util_f0():
    """GBufferA.a -> dielectric F0 -> Blender 'Specular IOR Level' (PLAN 2.11).

        F0 = clamp(x < 0.666667 ? x*0.06 : x*0.36 - 0.2, 0, 0.16)
        level = F0 / 0.08              (Blender: level 0.5 <-> F0 0.04)

    The /0.08 divisor matches the hair script's measured calibration:
    0.046520 -> 0.5815."""
    def _b(g):
        _sock(g, "Specular IOR Level", "OUTPUT", "NodeSocketFloat")
        _sock(g, "F0", "OUTPUT", "NodeSocketFloat")
        _sock(g, "GBufferA.a", "INPUT", "NodeSocketFloat", 0.5, 0.0, 1.0)
        gi = _new(g, "NodeGroupInput", "Group Input", (-660, 0))
        go = _new(g, "NodeGroupOutput", "Group Output", (620, 0))
        lo = _new(g, "ShaderNodeMath", "lo", (-440, 160), "x * 0.06")
        _prop(lo, "operation", "MULTIPLY")
        _sv(lo, 1, F0_LO)
        hi = _new(g, "ShaderNodeMath", "hi", (-440, -20), "x * 0.36 - 0.2")
        _prop(hi, "operation", "MULTIPLY_ADD")
        _sv(hi, 1, F0_HI)
        _sv(hi, 2, -F0_HI_BIAS)
        cm = _new(g, "ShaderNodeMath", "knee", (-440, -220), "x >= 0.666667")
        _prop(cm, "operation", "GREATER_THAN")
        _sv(cm, 1, F0_KNEE)
        mx = _new(g, "ShaderNodeMix", "pick", (-220, 0), "piecewise")
        _prop(mx, "data_type", "FLOAT")
        cl = _new(g, "ShaderNodeMath", "clamp", (-20, 0), "clamp to 0.16")
        _prop(cl, "operation", "MINIMUM")
        _sv(cl, 1, F0_CLAMP)
        _prop(cl, "use_clamp", True)
        nz = _new(g, "ShaderNodeMath", "level", (200, 80), "F0 / 0.08 -> level")
        _prop(nz, "operation", "DIVIDE")
        _sv(nz, 1, SPEC_LEVEL_SCALE)
        _link(g, gi, "GBufferA.a", lo, 0)
        _link(g, gi, "GBufferA.a", hi, 0)
        _link(g, gi, "GBufferA.a", cm, 0)
        _link(g, cm, 0, mx, "Factor")
        _link(g, lo, 0, mx, "A")
        _link(g, hi, 0, mx, "B")
        _link(g, mx, "Result", cl, 0)
        _link(g, cl, 0, nz, 0)
        _link(g, nz, 0, go, "Specular IOR Level")
        _link(g, cl, 0, go, "F0")
    return _rebuild_group("FF7R Util/F0 Remap", _b)


# ================================================================ EYE PATH ===
# Ported from ff7r_eye_material_v2.py.  These four groups are self-contained:
# further eye tweaks should only need edits inside them.

def eye_disc():
    """uvC = (UV - centre)/radius; sclera mask = smoothstep(0.9, 1.1, |uvC|)."""
    def _b(g):
        _sock(g, "UV", "OUTPUT", "NodeSocketVector")
        _sock(g, "uvC", "OUTPUT", "NodeSocketVector")
        _sock(g, "Sclera Mask", "OUTPUT", "NodeSocketFloat")
        _sock(g, "UV0", "INPUT", "NodeSocketVector")
        _sock(g, "Mask Inner", "INPUT", "NodeSocketFloat", MASK_INNER, 0.0, 2.0)
        _sock(g, "Mask Outer", "INPUT", "NodeSocketFloat", MASK_OUTER, 0.0, 2.0)
        gi = _new(g, "NodeGroupInput", "Group Input", (-900, -220))
        go = _new(g, "NodeGroupOutput", "Group Output", (700, 0))
        vc = _new(g, "ShaderNodeVectorMath", "uvC", (-460, 0),
                  "uvC = (UV - centre) / radius")
        _prop(vc, "operation", "MULTIPLY_ADD")
        _sv(vc, 1, (_INV, _INV, 0.0))
        _sv(vc, 2, (-EYE_UV_CENTER[0] * _INV, -EYE_UV_CENTER[1] * _INV, 0.0))
        ln = _new(g, "ShaderNodeVectorMath", "r", (-220, 120), "r = |uvC|")
        _prop(ln, "operation", "LENGTH")
        mr = _new(g, "ShaderNodeMapRange", "mask", (20, 180),
                  "sclera mask = smoothstep(inner, outer, r)")
        _prop(mr, "interpolation_type", "SMOOTHSTEP")
        _sv(mr, 3, 0.0)
        _sv(mr, 4, 1.0)
        _link(g, gi, "UV0", vc, 0)
        _link(g, vc, 0, ln, 0)
        _link(g, ln, 1, mr, 0)
        _link(g, gi, "Mask Inner", mr, 1)
        _link(g, gi, "Mask Outer", mr, 2)
        _link(g, gi, "UV0", go, "UV")
        _link(g, vc, 0, go, "uvC")
        _link(g, mr, 0, go, "Sclera Mask")
    return _rebuild_group("FF7R Eye Disc", _b)


def eye_limbal_directional():
    """UE Limbal Occlusion (directional) -- verbatim shader maths from the eye
    capture.  Do not hand-edit; socket order is indexed positionally."""
    def _b(g):
        _sock(g, "Occlusion", "OUTPUT", "NodeSocketFloat")
        _sock(g, "uvC2", "INPUT", "NodeSocketVector")
        _sock(g, "Light Dir", "INPUT", "NodeSocketVector")
        _sock(g, "T2", "INPUT", "NodeSocketVector")
        _sock(g, "B2", "INPUT", "NodeSocketVector")
        _sock(g, "r", "INPUT", "NodeSocketFloat")
        _sock(g, "Offset", "INPUT", "NodeSocketFloat", LIMBAL_OFFSET)
        _sock(g, "Softness", "INPUT", "NodeSocketFloat", LIMBAL_SOFTNESS)
        _sock(g, "Aperture", "INPUT", "NodeSocketFloat", LIMBAL_APERTURE)
        _sock(g, "Normalize", "INPUT", "NodeSocketFloat", 0.5)
        gi = _new(g, "NodeGroupInput", "Group Input", (-1900, 0))
        go = _new(g, "NodeGroupOutput", "Group Output", (1900, 0))

        def vm(nm, loc, op, label=""):
            n = _new(g, "ShaderNodeVectorMath", nm, loc, label)
            _prop(n, "operation", op)
            return n

        def fm(nm, loc, op, label="", clamp=False):
            n = _new(g, "ShaderNodeMath", nm, loc, label)
            _prop(n, "operation", op)
            _prop(n, "use_clamp", clamp)
            return n

        v0 = vm("Vector Math", (-1000, 380), "DOT_PRODUCT", "Lu = dot(L, T2)")
        v1 = vm("Vector Math.001", (-1000, 240), "DOT_PRODUCT", "Lv = dot(L, B2)")
        m0 = fm("Math", (-820, 420), "MULTIPLY")
        m1 = fm("Math.001", (-820, 300), "MULTIPLY")
        m2 = fm("Math.002", (-640, 360), "ADD", "|Lproj|^2")
        sp = _new(g, "ShaderNodeSeparateXYZ", "Separate XYZ", (-1000, 60))
        m3 = fm("Math.003", (-820, 120), "MULTIPLY")
        m4 = fm("Math.004", (-820, 0), "MULTIPLY")
        m5 = fm("Math.005", (-640, 60), "ADD")
        m6 = fm("Math.006", (-460, 60), "DIVIDE", "Lx = radial component")
        m7 = fm("Math.007", (-640, -120), "MULTIPLY", "d2 = r*0.5")
        m8 = fm("Math.008", (-640, -240), "SQRT", "|Lproj|")
        m9 = fm("Math.009", (-460, -160), "MULTIPLY")
        m10 = fm("Math.010", (-280, -160), "MULTIPLY")
        m11 = fm("Math.011", (-100, -160), "SUBTRACT", "1 - sat(...)", True)
        _sv(m11, 0, 1.0)
        m12 = fm("Math.012", (80, -160), "MAXIMUM", "aperture")
        _sv(m12, 1, 0.01)
        m13 = fm("Math.013", (-460, 240), "MULTIPLY")
        m14 = fm("Math.014", (-280, 300), "MULTIPLY")
        m15 = fm("Math.015", (-280, 160), "MULTIPLY")
        m16 = fm("Math.016", (-100, 160), "MULTIPLY")
        m17 = fm("Math.017", (80, 160), "MULTIPLY")
        _sv(m17, 1, 2.0)
        m18 = fm("Math.018", (-280, 20), "MULTIPLY")
        m19 = fm("Math.019", (260, 240), "ADD")
        m20 = fm("Math.020", (440, 240), "ADD")
        m21 = fm("Math.021", (600, 240), "MAXIMUM")
        _sv(m21, 1, 0.0)
        m22 = fm("Math.022", (760, 240), "SQRT", "|offvec|")
        m23 = fm("Math.023", (260, 60), "MULTIPLY")
        m24 = fm("Math.024", (440, 60), "SUBTRACT",
                 "sat(aperture - softness*|offvec|)", True)
        m25 = fm("Math.025", (260, -160), "DIVIDE")
        _sv(m25, 0, 1.0)
        m26 = fm("Math.026", (440, -160), "MAXIMUM")
        _sv(m26, 0, 1.0)
        m27 = fm("Math.027", (440, -60), "DIVIDE")
        m28 = fm("Math.028", (600, -60), "MINIMUM")
        _sv(m28, 1, 1.0)
        m29 = fm("Math.029", (760, -100), "MULTIPLY", "normalised form")
        mix = _new(g, "ShaderNodeMix", "Mix", (760, 60), "raw <-> normalised")
        _prop(mix, "data_type", "FLOAT")
        m30 = fm("Math.030", (900, -100), "MULTIPLY", "f^2, clamped", True)

        _link(g, gi, 1, v0, 0)
        _link(g, gi, 2, v0, 1)
        _link(g, gi, 1, v1, 0)
        _link(g, gi, 3, v1, 1)
        _link(g, v0, 1, m0, 0)
        _link(g, v0, 1, m0, 1)
        _link(g, v1, 1, m1, 0)
        _link(g, v1, 1, m1, 1)
        _link(g, m0, 0, m2, 0)
        _link(g, m1, 0, m2, 1)
        _link(g, gi, 0, sp, 0)
        _link(g, v0, 1, m3, 0)
        _link(g, sp, 0, m3, 1)
        _link(g, v1, 1, m4, 0)
        _link(g, sp, 1, m4, 1)
        _link(g, m3, 0, m5, 0)
        _link(g, m4, 0, m5, 1)
        _link(g, m5, 0, m6, 0)
        _link(g, gi, 4, m6, 1)
        _link(g, gi, 4, m7, 0)
        _link(g, m2, 0, m8, 0)
        _link(g, m7, 0, m9, 0)
        _link(g, gi, 7, m9, 1)
        _link(g, m9, 0, m10, 0)
        _link(g, m8, 0, m10, 1)
        _link(g, m10, 0, m11, 1)
        _link(g, m11, 0, m12, 0)
        _link(g, gi, 5, m13, 0)
        _link(g, gi, 5, m13, 1)
        _link(g, m13, 0, m14, 0)
        _link(g, m2, 0, m14, 1)
        _link(g, m6, 0, m15, 0)
        _link(g, gi, 4, m15, 1)
        _link(g, m15, 0, m16, 0)
        _link(g, gi, 5, m16, 1)
        _link(g, m16, 0, m17, 0)
        _link(g, gi, 4, m18, 0)
        _link(g, gi, 4, m18, 1)
        _link(g, m14, 0, m19, 0)
        _link(g, m17, 0, m19, 1)
        _link(g, m19, 0, m20, 0)
        _link(g, m18, 0, m20, 1)
        _link(g, m20, 0, m21, 0)
        _link(g, m21, 0, m22, 0)
        _link(g, m22, 0, m23, 0)
        _link(g, gi, 6, m23, 1)
        _link(g, m12, 0, m24, 0)
        _link(g, m23, 0, m24, 1)
        _link(g, m12, 0, m25, 1)
        _link(g, m25, 0, m26, 1)
        _link(g, m24, 0, m27, 0)
        _link(g, m12, 0, m27, 1)
        _link(g, m27, 0, m28, 0)
        _link(g, m26, 0, m29, 0)
        _link(g, m28, 0, m29, 1)
        _link(g, gi, 8, mix, 0)
        _link(g, m24, 0, mix, 2)
        _link(g, m29, 0, mix, 3)
        _link(g, mix, 0, m30, 0)
        _link(g, mix, 0, m30, 1)
        _link(g, m30, 0, go, 0)
        _fix_conventions(g)
    return _rebuild_group("UE Limbal Occlusion (directional)", _b)


def eye_cornea():
    """Cornea dome + view-side refraction parallax + iris UV.
    Cornea IOR 1.49 is triangulated three independent ways (PLAN tier 1)."""
    def _b(g):
        _sock(g, "Cornea Normal", "OUTPUT", "NodeSocketVector")
        _sock(g, "uvC2", "OUTPUT", "NodeSocketVector")
        _sock(g, "r", "OUTPUT", "NodeSocketFloat")
        _sock(g, "Iris UV", "OUTPUT", "NodeSocketVector")
        _sock(g, "N8", "INPUT", "NodeSocketVector")
        _sock(g, "Incoming", "INPUT", "NodeSocketVector")
        _sock(g, "T2", "INPUT", "NodeSocketVector")
        _sock(g, "B2", "INPUT", "NodeSocketVector")
        _sock(g, "UV", "INPUT", "NodeSocketVector")
        _sock(g, "uvC", "INPUT", "NodeSocketVector")
        _sock(g, "Slope", "INPUT", "NodeSocketFloat", CORNEA_SLOPE, 0.0, 4.0)
        _sock(g, "Eta", "INPUT", "NodeSocketFloat", ETA, 0.0, 2.0)
        _sock(g, "Depth Const", "INPUT", "NodeSocketFloat", DEPTH_CONST, 0.0, 2.0)
        _sock(g, "Depth Falloff", "INPUT", "NodeSocketFloat", DEPTH_FALLOFF, 0.0, 2.0)
        _sock(g, "Depth Scale", "INPUT", "NodeSocketFloat", DEPTH_SCALE, 0.0, 2.0)
        _sock(g, "Pupil Dilation", "INPUT", "NodeSocketFloat", 1.0, 0.05, 4.0)
        gi = _new(g, "NodeGroupInput", "Group Input", (-1900, 0))
        go = _new(g, "NodeGroupOutput", "Group Output", (1900, 0))

        dome = _new(g, "ShaderNodeVectorMath", "dome", (-634, 228),
                    "dome = (uvC.xy * slope, 1)")
        _prop(dome, "operation", "MULTIPLY_ADD")
        _sv(dome, 2, (0.0, 0.0, 1.0))
        slope3 = _new(g, "ShaderNodeCombineXYZ", "slope3", (-820, 100),
                      "(slope, slope, 0)")
        r2 = _new(g, "ShaderNodeVectorMath", "r2", (-624, 407), "r^2")
        _prop(r2, "operation", "DOT_PRODUCT")
        f2w = _grp(g, "UE Frame To World (explicit TBN)", "Group.003", (38, -89),
                   "cornea normal -> world")
        neg = _new(g, "ShaderNodeVectorMath", "I", (8, 262), "I = -Incoming")
        _prop(neg, "operation", "SCALE")
        _sv(neg, 3, -1.0)
        refr = _new(g, "ShaderNodeVectorMath", "refract", (213, 43),
                    "refract(I, cornea, eta)")
        _prop(refr, "operation", "REFRACT")
        dT = _new(g, "ShaderNodeVectorMath", "dotT", (415, 146), "dot(refr, T2)")
        _prop(dT, "operation", "DOT_PRODUCT")
        dB = _new(g, "ShaderNodeVectorMath", "dotB", (415, 6), "dot(refr, B2)")
        _prop(dB, "operation", "DOT_PRODUCT")
        dN = _new(g, "ShaderNodeVectorMath", "dotN", (415, -162), "dot(refr, N8)")
        _prop(dN, "operation", "DOT_PRODUCT")
        dep = _new(g, "ShaderNodeMath", "depth", (245, 231),
                   "const - falloff*r^2")
        _prop(dep, "operation", "MULTIPLY_ADD")
        negf = _new(g, "ShaderNodeMath", "negfalloff", (60, 231), "-falloff")
        _prop(negf, "operation", "MULTIPLY")
        _sv(negf, 1, -1.0)
        dmax = _new(g, "ShaderNodeMath", "dmax", (422, 318), "max(0, ...)")
        _prop(dmax, "operation", "MAXIMUM")
        _sv(dmax, 1, 0.0)
        dsc = _new(g, "ShaderNodeMath", "dscale", (592, 317), "iris depth")
        _prop(dsc, "operation", "MULTIPLY")
        px = _new(g, "ShaderNodeMath", "px", (599, 108), "refr.x / refr.z")
        _prop(px, "operation", "DIVIDE")
        py = _new(g, "ShaderNodeMath", "py", (611, -123), "refr.y / refr.z")
        _prop(py, "operation", "DIVIDE")
        ox = _new(g, "ShaderNodeMath", "ox", (799, 108))
        _prop(ox, "operation", "MULTIPLY")
        oy = _new(g, "ShaderNodeMath", "oy", (799, -52))
        _prop(oy, "operation", "MULTIPLY")
        off = _new(g, "ShaderNodeCombineXYZ", "offset", (977, 21),
                   "parallax offset")
        uvr = _new(g, "ShaderNodeVectorMath", "uv_refr", (46, -501),
                   "uv_refr = UV0 - offset")
        _prop(uvr, "operation", "SUBTRACT")
        uvc2 = _new(g, "ShaderNodeVectorMath", "uvC2", (198, -501),
                    "uvC2 = (uv_refr - centre) / radius")
        _prop(uvc2, "operation", "MULTIPLY_ADD")
        _sv(uvc2, 1, (_INV, _INV, 0.0))
        _sv(uvc2, 2, (-EYE_UV_CENTER[0] * _INV, -EYE_UV_CENTER[1] * _INV, 0.0))
        ln2 = _new(g, "ShaderNodeVectorMath", "len2", (357, -553), "|uvC2|")
        _prop(ln2, "operation", "LENGTH")
        cl2 = _new(g, "ShaderNodeMath", "clamp2", (537, -553), "min(|uvC2|, 1)")
        _prop(cl2, "operation", "MINIMUM")
        _sv(cl2, 1, 1.0)
        pw = _new(g, "ShaderNodeMath", "pow", (897, -353), "r' = pow(r, k)")
        _prop(pw, "operation", "POWER")
        nz2 = _new(g, "ShaderNodeVectorMath", "dir", (357, -681),
                   "normalize(uvC2)")
        _prop(nz2, "operation", "NORMALIZE")
        sc2 = _new(g, "ShaderNodeVectorMath", "scaled", (1046, -635))
        _prop(sc2, "operation", "SCALE")
        iuv = _new(g, "ShaderNodeVectorMath", "iris_uv", (1226, -635),
                   "iris UV = dir*len*0.5 + 0.5")
        _prop(iuv, "operation", "MULTIPLY_ADD")
        _sv(iuv, 1, (0.5, 0.5, 0.0))
        _sv(iuv, 2, (0.5, 0.5, 0.0))

        _link(g, gi, "Slope", slope3, 0)
        _link(g, gi, "Slope", slope3, 1)
        _link(g, slope3, 0, dome, 1)
        _link(g, gi, "uvC", dome, 0)
        _link(g, gi, "uvC", r2, 0)
        _link(g, gi, "uvC", r2, 1)
        _link(g, gi, "T2", f2w, 0)
        _link(g, gi, "B2", f2w, 1)
        _link(g, gi, "N8", f2w, 2)
        _link(g, dome, 0, f2w, 3)
        _link(g, gi, "Incoming", neg, 0)
        _link(g, neg, 0, refr, 0)
        _link(g, f2w, 0, refr, 1)
        _link(g, gi, "Eta", refr, 3)
        _link(g, refr, 0, dT, 0)
        _link(g, gi, "T2", dT, 1)
        _link(g, refr, 0, dB, 0)
        _link(g, gi, "B2", dB, 1)
        _link(g, refr, 0, dN, 0)
        _link(g, gi, "N8", dN, 1)
        _link(g, gi, "Depth Falloff", negf, 0)
        _link(g, r2, 1, dep, 0)
        _link(g, negf, 0, dep, 1)
        _link(g, gi, "Depth Const", dep, 2)
        _link(g, dep, 0, dmax, 0)
        _link(g, dmax, 0, dsc, 0)
        _link(g, gi, "Depth Scale", dsc, 1)
        _link(g, dT, 1, px, 0)
        _link(g, dN, 1, px, 1)
        _link(g, dB, 1, py, 0)
        _link(g, dN, 1, py, 1)
        _link(g, px, 0, ox, 0)
        _link(g, dsc, 0, ox, 1)
        _link(g, py, 0, oy, 0)
        _link(g, dsc, 0, oy, 1)
        _link(g, ox, 0, off, 0)
        _link(g, oy, 0, off, 1)
        _link(g, gi, "UV", uvr, 0)
        _link(g, off, 0, uvr, 1)
        _link(g, uvr, 0, uvc2, 0)
        _link(g, uvc2, 0, ln2, 0)
        _link(g, ln2, 1, cl2, 0)
        _link(g, cl2, 0, pw, 0)
        _link(g, gi, "Pupil Dilation", pw, 1)
        _link(g, uvc2, 0, nz2, 0)
        _link(g, nz2, 0, sc2, 0)
        _link(g, pw, 0, sc2, 3)
        _link(g, sc2, 0, iuv, 0)
        _link(g, f2w, 0, go, "Cornea Normal")
        _link(g, uvc2, 0, go, "uvC2")
        _link(g, ln2, 1, go, "r")
        _link(g, iuv, 0, go, "Iris UV")
        _fix_conventions(g)
    return _rebuild_group("FF7R Cornea", _b)


def eye_limbal():
    """Limbal occlusion: radial term blended with the directional term, applied
    to the iris only (the sclera stays at 1.0)."""
    def _b(g):
        _sock(g, "Occlusion", "OUTPUT", "NodeSocketFloat")
        _sock(g, "r", "INPUT", "NodeSocketFloat")
        _sock(g, "Sclera Mask", "INPUT", "NodeSocketFloat")
        _sock(g, "N8", "INPUT", "NodeSocketVector")
        _sock(g, "uvC2", "INPUT", "NodeSocketVector")
        _sock(g, "T2", "INPUT", "NodeSocketVector")
        _sock(g, "B2", "INPUT", "NodeSocketVector")
        _sock(g, "Light Position", "INPUT", "NodeSocketVector")
        _sock(g, "Shading Point", "INPUT", "NodeSocketVector")
        _sock(g, "Eta", "INPUT", "NodeSocketFloat", ETA, 0.0, 2.0)
        _sock(g, "Offset", "INPUT", "NodeSocketFloat", LIMBAL_OFFSET, 0.0, 2.0)
        _sock(g, "Softness", "INPUT", "NodeSocketFloat", LIMBAL_SOFTNESS, 0.0, 2.0)
        _sock(g, "Aperture", "INPUT", "NodeSocketFloat", LIMBAL_APERTURE, 0.0, 8.0)
        _sock(g, "Amount", "INPUT", "NodeSocketFloat", 1.0, 0.0, 1.0)
        _sock(g, "Directional", "INPUT", "NodeSocketFloat", 1.0, 0.0, 1.0)
        gi = _new(g, "NodeGroupInput", "Group Input", (-1900, 0))
        go = _new(g, "NodeGroupOutput", "Group Output", (1900, 0))
        rad = _new(g, "ShaderNodeMath", "radial", (111, 284),
                   "1 - 0.55*|uvC2|")
        _prop(rad, "operation", "MULTIPLY_ADD")
        _prop(rad, "use_clamp", True)
        _sv(rad, 2, 1.0)
        negs = _new(g, "ShaderNodeMath", "negsoft", (-70, 284), "-softness")
        _prop(negs, "operation", "MULTIPLY")
        _sv(negs, 1, -1.0)
        sq = _new(g, "ShaderNodeMath", "squared", (269, 274), "squared")
        _prop(sq, "operation", "MULTIPLY")
        iris_only = _new(g, "ShaderNodeMix", "iris_only", (628, 396),
                         "iris only -- sclera stays 1.0")
        _prop(iris_only, "data_type", "FLOAT")
        _sv(iris_only, 3, 1.0)
        amt = _new(g, "ShaderNodeMix", "amount", (793, 396),
                   "limbal occlusion amount")
        _prop(amt, "data_type", "FLOAT")
        _sv(amt, 2, 1.0)
        lsub = _new(g, "ShaderNodeVectorMath", "L", (-675, -139),
                    "L = light position - shading point")
        _prop(lsub, "operation", "SUBTRACT")
        lnz = _new(g, "ShaderNodeVectorMath", "Lhat", (-519, -157),
                   "unit light dir")
        _prop(lnz, "operation", "NORMALIZE")
        lref = _new(g, "ShaderNodeMix", "refract_L", (-363, -130),
                    "lerp(N, L, eta) -- light-side refraction")
        _prop(lref, "data_type", "VECTOR")
        lrn = _new(g, "ShaderNodeVectorMath", "Lrefr", (-214, -130),
                   "refracted light dir")
        _prop(lrn, "operation", "NORMALIZE")
        lsc = _new(g, "ShaderNodeVectorMath", "Lscaled", (-67, -132),
                   "* directional")
        _prop(lsc, "operation", "SCALE")
        dirg = _grp(g, "UE Limbal Occlusion (directional)", "directional",
                    (254, 88), "shader maths -- do not hand-edit")
        blend = _new(g, "ShaderNodeMix", "blend", (448, 262),
                     "radial <-> directional")
        _prop(blend, "data_type", "FLOAT")
        _link(g, gi, "Softness", negs, 0)
        _link(g, gi, "r", rad, 0)
        _link(g, negs, 0, rad, 1)
        _link(g, rad, 0, sq, 0)
        _link(g, rad, 0, sq, 1)
        _link(g, gi, "Light Position", lsub, 0)
        _link(g, gi, "Shading Point", lsub, 1)
        _link(g, lsub, 0, lnz, 0)
        _link(g, gi, "Eta", lref, "Factor")
        _link(g, gi, "N8", lref, "A")
        _link(g, lnz, 0, lref, "B")
        _link(g, lref, "Result", lrn, 0)
        _link(g, lrn, 0, lsc, 0)
        _link(g, gi, "Directional", lsc, "Scale")
        _link(g, gi, "uvC2", dirg, 0)
        _link(g, lsc, 0, dirg, 1)
        _link(g, gi, "T2", dirg, 2)
        _link(g, gi, "B2", dirg, 3)
        _link(g, gi, "r", dirg, 4)
        _link(g, gi, "Offset", dirg, 5)
        _link(g, gi, "Softness", dirg, 6)
        _link(g, gi, "Aperture", dirg, 7)
        _link(g, gi, "Directional", blend, "Factor")
        _link(g, sq, 0, blend, "A")
        _link(g, dirg, 0, blend, "B")
        _link(g, blend, "Result", iris_only, "A")
        _link(g, gi, "Sclera Mask", iris_only, "Factor")
        _link(g, gi, "Amount", amt, "Factor")
        _link(g, iris_only, "Result", amt, "B")
        _link(g, amt, "Result", go, "Occlusion")
        _fix_conventions(g)
    return _rebuild_group("FF7R Limbal Occlusion", _b)


def eye_uv():
    """Geometry-only half of the eye path: disc -> cornea, producing Iris UV and
    the cornea-local frame.  Deliberately has NO input derived from an iris
    texture colour.

    This split exists to avoid a node-graph cycle.  In the material tree the
    iris textures (IrisColor/IrisNormal/IrisOcclusion/IrisEmissive) must be
    sampled at the Iris UV this group computes -- but Blender treats a Group
    node as opaque for cycle detection, so if ONE group both consumed those
    textures' colours AND produced the UV they are sampled at, Blender refuses
    the graph outright ("This link forms a cycle which is not supported"),
    even though internally Iris UV never actually depends on iris colour.
    Keeping UV production in its own node sidesteps that: eye_uv has no path
    back into the textures that read its own output, so the two can wire to
    each other safely.  See `grp_eye()`, which consumes these outputs, and
    `build()` for the wiring."""
    def _b(g):
        _sock(g, "Iris UV", "OUTPUT", "NodeSocketVector")
        _sock(g, "Cornea Normal", "OUTPUT", "NodeSocketVector")
        _sock(g, "uvC2", "OUTPUT", "NodeSocketVector")
        _sock(g, "r", "OUTPUT", "NodeSocketFloat")
        _sock(g, "Sclera Mask", "OUTPUT", "NodeSocketFloat")
        _sock(g, "T2", "OUTPUT", "NodeSocketVector")
        _sock(g, "B2", "OUTPUT", "NodeSocketVector")
        _sock(g, "UV0", "INPUT", "NodeSocketVector")
        _sock(g, "Gaze Normal", "INPUT", "NodeSocketVector", (0.0, 0.0, 1.0))
        _sock(g, "Pupil Dilation", "INPUT", "NodeSocketFloat", 1.0, 0.05, 4.0)
        gi = _new(g, "NodeGroupInput", "Group Input", (-1400, 0))
        go = _new(g, "NodeGroupOutput", "Group Output", (700, 0))

        geo = _new(g, "ShaderNodeNewGeometry", "Geometry", (-1400, 300))
        tbn = _grp(g, "FF7R Util/TBN", "TBN", (-1400, 0), "tangent frame")
        disc = _grp(g, "FF7R Eye Disc", "Disc", (-1100, 300), "eye disc / limbus")
        # cornea frame: B2 = normalize(cross(N8,T)), T2 = cross(B2,N8)
        b2 = _new(g, "ShaderNodeVectorMath", "B2", (-900, 100), "cross(N8, T)")
        _prop(b2, "operation", "CROSS_PRODUCT")
        b2n = _new(g, "ShaderNodeVectorMath", "B2n", (-740, 100))
        _prop(b2n, "operation", "NORMALIZE")
        b2w = _new(g, "ShaderNodeVectorMath", "B2w", (-580, 100), "* w")
        _prop(b2w, "operation", "SCALE")
        t2 = _new(g, "ShaderNodeVectorMath", "T2", (-900, -100), "cross(B2, N8)")
        _prop(t2, "operation", "CROSS_PRODUCT")
        t2n = _new(g, "ShaderNodeVectorMath", "T2n", (-740, -100))
        _prop(t2n, "operation", "NORMALIZE")
        t2w = _new(g, "ShaderNodeVectorMath", "T2w", (-580, -100), "* w")
        _prop(t2w, "operation", "SCALE")

        cornea = _grp(g, "FF7R Cornea", "Cornea", (-300, 100), "cornea / parallax")

        _link(g, gi, "UV0", disc, "UV0")
        _link(g, tbn, "T", b2, 1)
        _link(g, gi, "Gaze Normal", b2, 0)
        _link(g, b2, 0, b2n, 0)
        _link(g, b2n, 0, b2w, 0)
        _link(g, tbn, "w", b2w, "Scale")
        _link(g, b2w, 0, t2, 0)
        _link(g, gi, "Gaze Normal", t2, 1)
        _link(g, t2, 0, t2n, 0)
        _link(g, t2n, 0, t2w, 0)
        _link(g, tbn, "w", t2w, "Scale")

        _link(g, gi, "Gaze Normal", cornea, "N8")
        _link(g, geo, "Incoming", cornea, "Incoming")
        _link(g, t2w, 0, cornea, "T2")
        _link(g, b2w, 0, cornea, "B2")
        _link(g, disc, "UV", cornea, "UV")
        _link(g, disc, "uvC", cornea, "uvC")
        _link(g, gi, "Pupil Dilation", cornea, "Pupil Dilation")

        _link(g, cornea, "Iris UV", go, "Iris UV")
        _link(g, cornea, "Cornea Normal", go, "Cornea Normal")
        _link(g, cornea, "uvC2", go, "uvC2")
        _link(g, cornea, "r", go, "r")
        _link(g, disc, "Sclera Mask", go, "Sclera Mask")
        _link(g, t2w, 0, go, "T2")
        _link(g, b2w, 0, go, "B2")
        _fix_conventions(g)
    return _rebuild_group("FF7R Eye UV", _b)


def grp_eye():
    """Colour half of the eye path: limbal occlusion + iris/sclera composition.
    Outputs everything the Principled needs for SM 9.  Takes the cornea-local
    frame and Iris UV as INPUTS from `eye_uv()` rather than computing them --
    see that function's docstring for why the two are split.

    PLAN 0.3: slot 11 is `IrisOcclusion`, not a specular mask -- it multiplies
    base colour (AO), it does not drive specular."""
    def _b(g):
        _sock(g, "Base Color", "OUTPUT", "NodeSocketColor")
        _sock(g, "Normal", "OUTPUT", "NodeSocketVector")
        _sock(g, "Coat Normal", "OUTPUT", "NodeSocketVector")
        _sock(g, "Emission", "OUTPUT", "NodeSocketColor")
        _sock(g, "Sclera Color", "INPUT", "NodeSocketColor", (0.6, 0.6, 0.6, 1.0))
        _sock(g, "Iris Color", "INPUT", "NodeSocketColor", (0.3, 0.2, 0.1, 1.0))
        _sock(g, "Iris Occlusion", "INPUT", "NodeSocketFloat", 1.0, 0.0, 1.0)
        _sock(g, "Iris AO Factor", "INPUT", "NodeSocketFloat", 0.5, 0.0, 1.0)
        _sock(g, "Iris Emissive", "INPUT", "NodeSocketColor", (0.0, 0.0, 0.0, 1.0))
        _sock(g, "Sclera Base Normal", "INPUT", "NodeSocketVector", (0.0, 0.0, 1.0))
        _sock(g, "Sclera Secondary Normal", "INPUT", "NodeSocketVector", (0.0, 0.0, 1.0))
        _sock(g, "Gaze Normal", "INPUT", "NodeSocketVector", (0.0, 0.0, 1.0))
        _sock(g, "Iris Detail Normal", "INPUT", "NodeSocketVector", (0.0, 0.0, 1.0))
        _sock(g, "Cornea Normal", "INPUT", "NodeSocketVector", (0.0, 0.0, 1.0))
        _sock(g, "uvC2", "INPUT", "NodeSocketVector", (0.0, 0.0, 0.0))
        _sock(g, "r", "INPUT", "NodeSocketFloat", 0.0, 0.0, 2.0)
        _sock(g, "Sclera Mask", "INPUT", "NodeSocketFloat", 0.0, 0.0, 1.0)
        _sock(g, "T2", "INPUT", "NodeSocketVector", (1.0, 0.0, 0.0))
        _sock(g, "B2", "INPUT", "NodeSocketVector", (0.0, 1.0, 0.0))
        _sock(g, "Light Position", "INPUT", "NodeSocketVector", (17.0, 0.0, 17.0))
        _sock(g, "IrisEmissive_", "INPUT", "NodeSocketFloat", 0.0, 0.0, 1.0)
        _sock(g, "Limbal Amount", "INPUT", "NodeSocketFloat", 1.0, 0.0, 1.0)
        gi = _new(g, "NodeGroupInput", "Group Input", (-1200, -200))
        go = _new(g, "NodeGroupOutput", "Group Output", (900, 0))

        geo = _new(g, "ShaderNodeNewGeometry", "Geometry", (-1200, 400),
                   "only used for Position (limbal shading point)")
        limbal = _grp(g, "FF7R Limbal Occlusion", "Limbal", (-700, 0),
                      "limbal occlusion")

        albedo = _new(g, "ShaderNodeMix", "iris_sclera", (200, 400),
                      "lerp(iris, sclera, mask)")
        _prop(albedo, "data_type", "RGBA")
        irisao = _new(g, "ShaderNodeMix", "iris_ao", (20, 560),
                      "iris colour * IrisOcclusion  [PLAN 0.3]")
        _prop(irisao, "data_type", "RGBA")
        _prop(irisao, "blend_type", "MULTIPLY")
        _sv(irisao, "Factor", 0.5)
        limbmul = _new(g, "ShaderNodeMix", "limbal_mul", (400, 400),
                       "base colour * limbal occlusion")
        _prop(limbmul, "data_type", "RGBA")
        _prop(limbmul, "blend_type", "MULTIPLY")
        _sv(limbmul, "Factor", 1.0)
        nrm = _new(g, "ShaderNodeMix", "normal_mix", (200, 100),
                   "lerp(cornea, sclera N, mask)")
        _prop(nrm, "data_type", "VECTOR")
        iris_normal = _new(g, "ShaderNodeMix", "iris_normal_mix", (420, 100),
                            "lerp(iris detail normal, regular normal, sclera mask)")
        _prop(iris_normal, "data_type", "VECTOR")
        n2nd = _new(g, "ShaderNodeMix", "second_normal", (200, -200),
                    "lerp(cornea map, gaze, mask)")
        _prop(n2nd, "data_type", "VECTOR")
        em = _new(g, "ShaderNodeMix", "emissive", (400, -420),
                  "IrisEmissive_ gate (additive, unshadowed)")
        _prop(em, "data_type", "RGBA")
        _sv(em, "A", (0.0, 0.0, 0.0, 1.0))
        eminv = _new(g, "ShaderNodeMath", "iris_side", (200, -420),
                     "1 - sclera mask")
        _prop(eminv, "operation", "SUBTRACT")
        _sv(eminv, 0, 1.0)
        emg = _new(g, "ShaderNodeMath", "em_gate", (360, -560), "* IrisEmissive_")
        _prop(emg, "operation", "MULTIPLY")

        _link(g, gi, "r", limbal, "r")
        _link(g, gi, "Sclera Mask", limbal, "Sclera Mask")
        _link(g, gi, "Gaze Normal", limbal, "N8")
        _link(g, gi, "uvC2", limbal, "uvC2")
        _link(g, gi, "T2", limbal, "T2")
        _link(g, gi, "B2", limbal, "B2")
        _link(g, gi, "Light Position", limbal, "Light Position")
        _link(g, geo, "Position", limbal, "Shading Point")
        _link(g, gi, "Limbal Amount", limbal, "Amount")

        _link(g, gi, "Iris Color", irisao, "A")
        _link(g, gi, "Iris Occlusion", irisao, "B")
        _link(g, gi, "Iris AO Factor", irisao, "Factor")
        _link(g, irisao, "Result", albedo, "A")
        _link(g, gi, "Sclera Color", albedo, "B")
        _link(g, gi, "Sclera Mask", albedo, "Factor")
        _link(g, albedo, "Result", limbmul, "A")
        _link(g, limbal, "Occlusion", limbmul, "B")

        _link(g, gi, "Sclera Mask", nrm, "Factor")
        _link(g, gi, "Cornea Normal", nrm, "A")
        _link(g, gi, "Sclera Base Normal", nrm, "B")
        _link(g, gi, "Sclera Mask", iris_normal, "Factor")
        _link(g, gi, "Iris Detail Normal", iris_normal, "A")
        _link(g, nrm, "Result", iris_normal, "B")
        _link(g, gi, "Sclera Mask", n2nd, "Factor")
        _link(g, gi, "Gaze Normal", n2nd, "A")
        _link(g, gi, "Sclera Secondary Normal", n2nd, "B")

        _link(g, gi, "Sclera Mask", eminv, 1)
        _link(g, eminv, 0, emg, 0)
        _link(g, gi, "IrisEmissive_", emg, 1)
        _link(g, emg, 0, em, "Factor")
        _link(g, gi, "Iris Emissive", em, "B")

        _link(g, limbmul, "Result", go, "Base Color")
        _link(g, iris_normal, "Result", go, "Normal")
        _link(g, n2nd, "Result", go, "Coat Normal")
        _link(g, em, "Result", go, "Emission")
        _fix_conventions(g)
    return _rebuild_group("FF7R Eye", _b)


# ============================================================ OTHER FEATURES ==

def grp_coverage():
    """PLAN 2.6 -- three modes.  Native Alpha is the default; the blue-noise
    dither only reads as soft coverage because UE's TAA resolves it, which
    Blender has no equivalent of, so it is present for reference only."""
    def _b(g):
        _sock(g, "Alpha", "OUTPUT", "NodeSocketFloat")
        _sock(g, "Coverage", "INPUT", "NodeSocketFloat", 1.0, 0.0, 1.0)
        _sock(g, "Object Fade", "INPUT", "NodeSocketFloat", 1.0, 0.0, 1.0)
        _sock(g, "Clip", "INPUT", "NodeSocketFloat", OPACITY_CLIP, 0.0, 1.0)
        _sock(g, "Enable", "INPUT", "NodeSocketFloat", 0.0, 0.0, 1.0)
        _sock(g, "Mode", "INPUT", "NodeSocketFloat", 0.0, 0.0, 2.0)
        gi = _new(g, "NodeGroupInput", "Group Input", (-1100, 0))
        go = _new(g, "NodeGroupOutput", "Group Output", (1400, 0))
        fade = _new(g, "ShaderNodeMath", "fade", (-880, 200),
                    "coverage * object fade")
        _prop(fade, "operation", "MULTIPLY")
        cut = _new(g, "ShaderNodeMath", "cutout", (-880, 20),
                   "hard cutout: > clip  (authored 0.3333)")
        _prop(cut, "operation", "GREATER_THAN")
        noise = _new(g, "ShaderNodeTexWhiteNoise", "dither_noise", (-880, -220),
                     "stand-in for View_SpatiotemporalBlueNoise [not portable]")
        _prop(noise, "noise_dimensions", "2D")
        dth = _new(g, "ShaderNodeMath", "dither", (-660, -220),
                   "n*(255/256) + 1/512")
        _prop(dth, "operation", "MULTIPLY_ADD")
        _sv(dth, 1, 255.0 / 256.0)
        _sv(dth, 2, 1.0 / 512.0)
        cmp_ = _new(g, "ShaderNodeMath", "dither_test", (-460, -220),
                    "coverage > dither(n)")
        _prop(cmp_, "operation", "GREATER_THAN")
        mode, sel, vals = _menu(g, "CoverageMode", (-200, 60),
                                ["Alpha (native)", "Hard cutout",
                                 "Dithered (faithful)"], "FLOAT", "Coverage Mode",
                                selector_src=(gi, "Mode"))
        _menu_feed(g, vals, 0, fade)
        _menu_feed(g, vals, 1, cut)
        _menu_feed(g, vals, 2, cmp_)
        onoff = _new(g, "ShaderNodeMix", "enable", (1200, 0),
                     "Coverage_ off -> alpha 1")
        _prop(onoff, "data_type", "FLOAT")
        _sv(onoff, "A", 1.0)
        _link(g, gi, "Coverage", fade, 0)
        _link(g, gi, "Object Fade", fade, 1)
        _link(g, gi, "Coverage", cut, 0)
        _link(g, gi, "Clip", cut, 1)
        _link(g, gi, "Coverage", cmp_, 0)
        _link(g, noise, "Value", dth, 0)
        _link(g, dth, 0, cmp_, 1)
        _link(g, gi, "Enable", onoff, "Factor")
        _link(g, mode, _menu_out(mode), onoff, "B")
        _link(g, onoff, "Result", go, "Alpha")
    return _rebuild_group("FF7R Coverage", _b)


def grp_detail_layer():
    """Character detail (slerp) and MEC/environment detail (exact RNM core).

    The RNM option is transcribed from the retained Granite shader and is no
    longer a stub. `build()` forces this option when Isotropy_ is enabled and
    enables the layer from the actual detail-role switches, because current
    RMI_Surface_Standard_Overlay_Isotropy_Detail variants do not carry Detail_.
    Chained remains an artist-friendly preview option, not game shader math."""
    def _b(g):
        _sock(g, "Base Color", "OUTPUT", "NodeSocketColor")
        _sock(g, "Normal", "OUTPUT", "NodeSocketVector")
        _sock(g, "Roughness", "OUTPUT", "NodeSocketFloat")
        _sock(g, "AO", "OUTPUT", "NodeSocketFloat")
        for nm_, ty, dv in (("Base Color", "NodeSocketColor", (0.5, 0.5, 0.5, 1.0)),
                            ("Base Normal", "NodeSocketVector", (0.0, 0.0, 1.0)),
                            ("Base Roughness", "NodeSocketFloat", 0.5),
                            ("Base AO", "NodeSocketFloat", 1.0),
                            ("Detail Color", "NodeSocketColor", (0.5, 0.5, 0.5, 1.0)),
                            ("Detail Normal", "NodeSocketVector", (0.0, 0.0, 1.0)),
                            ("Detail Roughness", "NodeSocketFloat", 0.0),
                            ("Detail AO", "NodeSocketFloat", 1.0),
                            ("Detail Mask", "NodeSocketFloat", 0.0),
                            ("Enable", "NodeSocketFloat", 0.0),
                            ("Detail Blend", "NodeSocketFloat", 0.0)):
            _sock(g, nm_, "INPUT", ty, dv)
        _sock(g, "Normal Strength", "INPUT", "NodeSocketFloat", 0.5, 0.0, 1.0)
        gi = _new(g, "NodeGroupInput", "Group Input", (-1100, 0))
        go = _new(g, "NodeGroupOutput", "Group Output", (1400, 0))
        gate = _new(g, "ShaderNodeMath", "gate", (-860, -520),
                    "mask * Detail_ enable")
        _prop(gate, "operation", "MULTIPLY")
        # Detail-normal intensity: scale the tangent xy and renormalize, the
        # same shaping a Normal Map node's Strength applies.  Separate from the
        # gate, which is the mask; this is the artist-facing amount.
        dsep = _new(g, "ShaderNodeSeparateXYZ", "detail_normal_xyz", (-1000, 300))
        dsx = _new(g, "ShaderNodeMath", "detail_normal_x", (-860, 380),
                   "detail.x * strength")
        _prop(dsx, "operation", "MULTIPLY")
        dsy = _new(g, "ShaderNodeMath", "detail_normal_y", (-860, 220),
                   "detail.y * strength")
        _prop(dsy, "operation", "MULTIPLY")
        dcomb = _new(g, "ShaderNodeCombineXYZ", "detail_normal_scaled", (-720, 300))
        dnorm = _new(g, "ShaderNodeVectorMath", "detail_normal_renormalize",
                     (-720, 140), "scaled detail normal")
        _prop(dnorm, "operation", "NORMALIZE")
        _link(g, gi, "Detail Normal", dsep, 0)
        _link(g, dsep, "X", dsx, 0)
        _link(g, gi, "Normal Strength", dsx, 1)
        _link(g, dsep, "Y", dsy, 0)
        _link(g, gi, "Normal Strength", dsy, 1)
        _link(g, dsx, 0, dcomb, "X")
        _link(g, dsy, 0, dcomb, "Y")
        _link(g, dsep, "Z", dcomb, "Z")
        _link(g, dcomb, 0, dnorm, 0)
        ov = _new(g, "ShaderNodeMix", "overlay", (-560, 460),
                  "albedo overlay (native Blender mix)")
        _prop(ov, "data_type", "RGBA")
        _prop(ov, "blend_type", "OVERLAY")
        slerp = _grp(g, "FF7R Util/Detail Normal Additive", "slerp", (-560, 140),
                     "additive detail slerp [tier 1]")
        rnm = _grp(g, "FF7R Util/RNM", "rnm", (-560, -20),
                   "reoriented normal mapping [tier 1]")
        rc = _grp(g, "FF7R Util/Roughness Combine", "rough", (-560, -180))
        ao = _grp(g, "FF7R Util/AO Combine", "ao", (-560, -360))
        chain = _new(g, "ShaderNodeMix", "chained", (-560, -60),
                     "chained: detail over base (Blender-idiomatic)")
        _prop(chain, "data_type", "VECTOR")
        chn = _new(g, "ShaderNodeVectorMath", "chain_n", (-380, -60))
        _prop(chn, "operation", "NORMALIZE")
        blend, sel, bvals = _menu(g, "DetailBlend", (-160, 140),
                                  ["Additive slerp (character)", "Chained Normal Map",
                                   "RNM (MEC, decompiled)"], "VECTOR",
                                  "Detail Normal Blend",
                                  selector_src=(gi, "Detail Blend"))
        _menu_feed(g, bvals, 0, slerp)
        _menu_feed(g, bvals, 1, chn)
        _menu_feed(g, bvals, 2, rnm)
        _link(g, gi, "Detail Mask", gate, 0)
        _link(g, gi, "Enable", gate, 1)
        _link(g, gi, "Base Color", ov, "A")
        _link(g, gi, "Detail Color", ov, "B")
        _link(g, gate, 0, ov, "Factor")
        _link(g, gi, "Base Normal", slerp, "Base")
        _link(g, dnorm, 0, slerp, "Detail")
        _link(g, gate, 0, slerp, "t")
        _link(g, gi, "Base Normal", rnm, "Base")
        _link(g, dnorm, 0, rnm, "Detail")
        _link(g, gate, 0, rnm, "Strength")
        _link(g, gate, 0, chain, "Factor")
        _link(g, gi, "Base Normal", chain, "A")
        _link(g, dnorm, 0, chain, "B")
        _link(g, chain, "Result", chn, 0)
        _link(g, gi, "Base Roughness", rc, "R1")
        _link(g, gi, "Detail Roughness", rc, "R2")
        _link(g, gi, "Base AO", ao, "L1")
        _link(g, gi, "Detail AO", ao, "L2")
        _link(g, ov, "Result", go, "Base Color")
        _link(g, blend, _menu_out(blend), go, "Normal")
        _link(g, rc, "Roughness", go, "Roughness")
        _link(g, ao, "AO", go, "AO")
    return _rebuild_group("FF7R Detail Layer", _b)


def grp_segment_layers():
    """Segmented_ / SegmentLayer0_ / 1_  -- two independently tinted, masked
    overlays (PLAN tier 2):  color += clamp(tint.w,0,1) * mask.x"""
    def _b(g):
        _sock(g, "Base Color", "OUTPUT", "NodeSocketColor")
        _sock(g, "Base Color", "INPUT", "NodeSocketColor", (0.5, 0.5, 0.5, 1.0))
        _sock(g, "Mask 0", "INPUT", "NodeSocketFloat", 0.0, 0.0, 1.0)
        _sock(g, "Tint 0", "INPUT", "NodeSocketColor", (1.0, 0.0, 0.0, 1.0))
        _sock(g, "Opacity 0", "INPUT", "NodeSocketFloat", 1.0, 0.0, 1.0)
        _sock(g, "Mask 1", "INPUT", "NodeSocketFloat", 0.0, 0.0, 1.0)
        _sock(g, "Tint 1", "INPUT", "NodeSocketColor", (0.0, 0.0, 1.0, 1.0))
        _sock(g, "Opacity 1", "INPUT", "NodeSocketFloat", 1.0, 0.0, 1.0)
        _sock(g, "Enable", "INPUT", "NodeSocketFloat", 0.0, 0.0, 1.0)
        gi = _new(g, "NodeGroupInput", "Group Input", (-820, 0))
        go = _new(g, "NodeGroupOutput", "Group Output", (820, 0))
        f0 = _new(g, "ShaderNodeMath", "f0", (-580, 200), "clamp(op0) * mask0")
        _prop(f0, "operation", "MULTIPLY")
        _prop(f0, "use_clamp", True)
        f1 = _new(g, "ShaderNodeMath", "f1", (-580, -200), "clamp(op1) * mask1")
        _prop(f1, "operation", "MULTIPLY")
        _prop(f1, "use_clamp", True)
        g0 = _new(g, "ShaderNodeMath", "g0", (-380, 200), "* Segmented_")
        _prop(g0, "operation", "MULTIPLY")
        g1 = _new(g, "ShaderNodeMath", "g1", (-380, -200), "* Segmented_")
        _prop(g1, "operation", "MULTIPLY")
        m0 = _new(g, "ShaderNodeMix", "layer0", (-120, 80), "paint layer 0")
        _prop(m0, "data_type", "RGBA")
        m1 = _new(g, "ShaderNodeMix", "layer1", (160, 0), "paint layer 1")
        _prop(m1, "data_type", "RGBA")
        _link(g, gi, "Opacity 0", f0, 0)
        _link(g, gi, "Mask 0", f0, 1)
        _link(g, gi, "Opacity 1", f1, 0)
        _link(g, gi, "Mask 1", f1, 1)
        _link(g, f0, 0, g0, 0)
        _link(g, gi, "Enable", g0, 1)
        _link(g, f1, 0, g1, 0)
        _link(g, gi, "Enable", g1, 1)
        _link(g, g0, 0, m0, "Factor")
        _link(g, gi, "Base Color", m0, "A")
        _link(g, gi, "Tint 0", m0, "B")
        _link(g, g1, 0, m1, "Factor")
        _link(g, m0, "Result", m1, "A")
        _link(g, gi, "Tint 1", m1, "B")
        _link(g, m1, "Result", go, "Base Color")
    return _rebuild_group("FF7R Segment Layers", _b)


def grp_layer_blend():
    """Layered_ / ShadingLayer_ -- Overlay the layer colour through its mask,
    while roughness and metallic retain scalar mixes (PLAN tier 2).
    Fabric_ and Standard_ are not mutually exclusive; Chocobo Body carries both.
    """
    def _b(g):
        _sock(g, "Base Color", "OUTPUT", "NodeSocketColor")
        _sock(g, "Roughness", "OUTPUT", "NodeSocketFloat")
        _sock(g, "Metallic", "OUTPUT", "NodeSocketFloat")
        _sock(g, "Base Color", "INPUT", "NodeSocketColor", (0.5, 0.5, 0.5, 1.0))
        _sock(g, "Layer Color", "INPUT", "NodeSocketColor", (0.5, 0.5, 0.5, 1.0))
        _sock(g, "Base Roughness", "INPUT", "NodeSocketFloat", 0.5, 0.0, 1.0)
        _sock(g, "Layer Roughness", "INPUT", "NodeSocketFloat", 0.5, 0.0, 1.0)
        _sock(g, "Base Metallic", "INPUT", "NodeSocketFloat", 0.0, 0.0, 1.0)
        _sock(g, "Layer Metallic", "INPUT", "NodeSocketFloat", 0.0, 0.0, 1.0)
        _sock(g, "Mask", "INPUT", "NodeSocketFloat", 0.0, 0.0, 1.0)
        _sock(g, "Enable", "INPUT", "NodeSocketFloat", 0.0, 0.0, 1.0)
        gi = _new(g, "NodeGroupInput", "Group Input", (-700, 0))
        go = _new(g, "NodeGroupOutput", "Group Output", (700, 0))
        gate = _new(g, "ShaderNodeMath", "gate", (-460, -300), "mask * Layered_")
        _prop(gate, "operation", "MULTIPLY")
        c = _new(g, "ShaderNodeMix", "color", (-160, 220))
        _prop(c, "data_type", "RGBA")
        _prop(c, "blend_type", "OVERLAY")
        r = _new(g, "ShaderNodeMix", "rough", (-160, 0))
        _prop(r, "data_type", "FLOAT")
        m = _new(g, "ShaderNodeMix", "metal", (-160, -200))
        _prop(m, "data_type", "FLOAT")
        _link(g, gi, "Mask", gate, 0)
        _link(g, gi, "Enable", gate, 1)
        for node, a, b in ((c, "Base Color", "Layer Color"),
                           (r, "Base Roughness", "Layer Roughness"),
                           (m, "Base Metallic", "Layer Metallic")):
            _link(g, gate, 0, node, "Factor")
            _link(g, gi, a, node, "A")
            _link(g, gi, b, node, "B")
        _link(g, c, "Result", go, "Base Color")
        _link(g, r, "Result", go, "Roughness")
        _link(g, m, "Result", go, "Metallic")
    return _rebuild_group("FF7R Layer Blend", _b)


def grp_transition_normal():
    """PositiveTransitionNormal_ / VertexExpressionBone_ -- the tier-1 slerp with
    a blend factor that comes from BONE ANIMATION STATE rather than a texture.

    Blender has no skeleton-driven shader input, so the source is a menu:
    Constant / Attribute (a named vertex layer) / Object property.  Only 2
    materials in the game use it and the driving bone is unknown."""
    def _b(g):
        _sock(g, "Normal", "OUTPUT", "NodeSocketVector")
        _sock(g, "t", "OUTPUT", "NodeSocketFloat")
        _sock(g, "Base Normal", "INPUT", "NodeSocketVector", (0.0, 0.0, 1.0))
        _sock(g, "Transition Normal", "INPUT", "NodeSocketVector", (0.0, 0.0, 1.0))
        _sock(g, "Constant", "INPUT", "NodeSocketFloat", 0.0, 0.0, 1.0)
        _sock(g, "Enable", "INPUT", "NodeSocketFloat", 0.0, 0.0, 1.0)
        _sock(g, "Source", "INPUT", "NodeSocketFloat", 0.0, 0.0, 2.0)
        gi = _new(g, "NodeGroupInput", "Group Input", (-900, 0))
        go = _new(g, "NodeGroupOutput", "Group Output", (900, 0))
        attr = _new(g, "ShaderNodeAttribute", "vertex_expression", (-700, -240),
                    'geometry attribute "VertexExpression"')
        _prop(attr, "attribute_type", "GEOMETRY")
        _prop(attr, "attribute_name", "VertexExpression")
        obj = _new(g, "ShaderNodeAttribute", "object_prop", (-700, -460),
                   'object["VertexExpressionBone"] -- keyframe this')
        _prop(obj, "attribute_type", "OBJECT")
        _prop(obj, "attribute_name", "VertexExpressionBone")
        src, sel, svals = _menu(g, "VExprSource", (-440, -140),
                                ["Constant", "Attribute", "Object property"],
                                "FLOAT", "Vertex Expression Source",
                                selector_src=(gi, "Source"))
        _menu_feed(g, svals, 1, attr, "Fac")
        _menu_feed(g, svals, 2, obj, "Fac")
        gate = _new(g, "ShaderNodeMath", "gate", (400, -140),
                    "t * PositiveTransitionNormal_")
        _prop(gate, "operation", "MULTIPLY")
        _prop(gate, "use_clamp", True)
        slerp = _grp(g, "FF7R Util/Normal Slerp", "slerp", (620, 140),
                     "same slerp as Detail_ [tier 1]")
        _menu_feed(g, svals, 0, gi, "Constant")
        _link(g, src, _menu_out(src), gate, 0)
        _link(g, gi, "Enable", gate, 1)
        _link(g, gi, "Base Normal", slerp, "A")
        _link(g, gi, "Transition Normal", slerp, "B")
        _link(g, gate, 0, slerp, "t")
        _link(g, slerp, "Normal", go, "Normal")
        _link(g, gate, 0, go, "t")
    return _rebuild_group("FF7R Transition Normal", _b)


def grp_emissive():
    """Emissive_ / ExtraEmissive_ / ExternalEmissive_.

    ExternalEmissive_, confirmed by the user (2026-08-24) from their own use of
    the identical pattern on light-up props that need different colours in
    different areas of the same map: multiplies the emissive sum by an
    UNCLAMPED RGB value set per OBJECT INSTANCE, not a material parameter --
    UE Custom Primitive Data or equivalent, set by the actor/Blueprint. This is
    why `ExternalEmissiveContext` reads (1,1,1,0) in every material in the game
    with zero exceptions: that is the material-level no-op default, not
    evidence the multiplier is always neutral -- the real value lives entirely
    outside what a material JSON can show. Unclamped matters: it is what lets
    this drive HDR/bloom intensity per-instance without a separate material per
    state or per colour. Still PLAN tier 3 for the exact formula (plain
    multiply is the working model, not shader-confirmed byte-for-byte).

    Blender mechanism, and why it is NOT a driver: every other control in this
    file is a MATERIAL custom property read through an AVERAGE driver (see
    `_drive()`), which works because there is exactly one shared master
    material. A driver can't do the same job here -- a driver's target is a
    static reference to ONE specific object, chosen at authoring time, so it
    cannot represent "whichever object this shared material happens to be on."
    The correct primitive is a `ShaderNodeAttribute` with
    `attribute_type='OBJECT'`, which reads a named custom property off
    whichever object is actually being shaded, entirely inside the node graph,
    varying correctly per instance with no driver at all -- the same pattern
    `grp_transition_normal()` already uses for `VertexExpressionBone_`. Reads
    `object["ExternalEmissiveContext"]`; mesh import initializes that property
    from the material's declared RGB default, so a newly imported object is
    neutral rather than going black."""
    def _b(g):
        _sock(g, "Emission", "OUTPUT", "NodeSocketColor")
        _sock(g, "Strength", "OUTPUT", "NodeSocketFloat")
        _sock(g, "Emissive", "INPUT", "NodeSocketColor", (0.0, 0.0, 0.0, 1.0))
        _sock(g, "Extra Emissive", "INPUT", "NodeSocketColor", (0.0, 0.0, 0.0, 1.0))
        _sock(g, "Emissive_", "INPUT", "NodeSocketFloat", 0.0, 0.0, 1.0)
        _sock(g, "ExtraEmissive_", "INPUT", "NodeSocketFloat", 0.0, 0.0, 1.0)
        _sock(g, "ExternalEmissive_", "INPUT", "NodeSocketFloat", 0.0, 0.0, 1.0)
        _sock(g, "ExternalEmissiveContext", "INPUT", "NodeSocketColor", (0.5, 0.5, 0.5, 1.0))
        gi = _new(g, "NodeGroupInput", "Group Input", (-800, 0))
        go = _new(g, "NodeGroupOutput", "Group Output", (800, 0))
        e0 = _new(g, "ShaderNodeMix", "gate0", (-560, 200), "Emissive_ gate")
        _prop(e0, "data_type", "RGBA")
        _sv(e0, "A", (0.0, 0.0, 0.0, 1.0))
        e1 = _new(g, "ShaderNodeMix", "gate1", (-560, -80), "ExtraEmissive_ gate")
        _prop(e1, "data_type", "RGBA")
        _sv(e1, "A", (0.0, 0.0, 0.0, 1.0))
        add = _new(g, "ShaderNodeMix", "sum", (-300, 60), "additive")
        _prop(add, "data_type", "RGBA")
        _prop(add, "blend_type", "ADD")
        _sv(add, "Factor", 1.0)
        objtint = _new(g, "ShaderNodeAttribute", "external_tint", (-560, -260),
                       'object["ExternalEmissiveContext"] -- per-instance, UNCLAMPED')
        _prop(objtint, "attribute_type", "OBJECT")
        _prop(objtint, "attribute_name", "ExternalEmissiveContext")
        tint = _new(g, "ShaderNodeMix", "external", (-60, 60),
                    "* per-instance tint, UNCLAMPED -- see docstring")
        _prop(tint, "data_type", "RGBA")
        _prop(tint, "blend_type", "MULTIPLY")
        _prop(tint, "clamp_result", False)
        st = _new(g, "ShaderNodeMath", "strength", (-60, -260),
                  "max(Emissive_, ExtraEmissive_)")
        _prop(st, "operation", "MAXIMUM")
        _link(g, gi, "Emissive_", e0, "Factor")
        _link(g, gi, "Emissive", e0, "B")
        _link(g, gi, "ExtraEmissive_", e1, "Factor")
        _link(g, gi, "Extra Emissive", e1, "B")
        _link(g, e0, "Result", add, "A")
        _link(g, e1, "Result", add, "B")
        _link(g, gi, "ExternalEmissive_", tint, "Factor")
        _link(g, add, "Result", tint, "A")
        _link(g, gi, "ExternalEmissiveContext", tint, "B")
        _link(g, gi, "Emissive_", st, 0)
        _link(g, gi, "ExtraEmissive_", st, 1)
        _link(g, tint, "Result", go, "Emission")
        _link(g, st, 0, go, "Strength")
    return _rebuild_group("FF7R Emissive", _b)


def grp_blood():
    """Blood_ / OxygenSaturation_ -- procedural haemoglobin colour (PLAN tier 2).
    PLAN 0.4: s is a per-material CONSTANT (3 assets game-wide, all solid), not a
    sampled map, so the whole ramp is three Math nodes."""
    def _b(g):
        _sock(g, "Base Color", "OUTPUT", "NodeSocketColor")
        _sock(g, "Oxygen Saturation", "INPUT", "NodeSocketFloat", 0.078, 0.0, 1.0)
        gi = _new(g, "NodeGroupInput", "Group Input", (-660, 0))
        go = _new(g, "NodeGroupOutput", "Group Output", (620, 0))
        outs = []
        for i, (nm_, (a, b)) in enumerate((("R", BLOOD_R), ("G", BLOOD_G),
                                           ("B", BLOOD_B))):
            n = _new(g, "ShaderNodeMath", nm_, (-400, 220 - i * 200),
                     "%s = %.5f + %.5f*s" % (nm_, a, b))
            _prop(n, "operation", "MULTIPLY_ADD")
            _sv(n, 1, b)
            _sv(n, 2, a)
            _link(g, gi, "Oxygen Saturation", n, 0)
            outs.append(n)
        c = _new(g, "ShaderNodeCombineColor", "combine", (-80, 0),
                 "dark venous -> bright arterial")
        for i, n in enumerate(outs):
            _link(g, n, 0, c, i)
        _link(g, c, 0, go, "Base Color")
    return _rebuild_group("FF7R Blood", _b)


def grp_film():
    """Film_ / FilmThickness_ / FilmStructure_ -- thin-film iridescence.
    PLAN 2.12: Principled has this natively, and since the branch is tier 3 (one
    material in the game, never diffed) a native mapping at the right magnitude
    beats reproducing unknown maths."""
    def _b(g):
        _sock(g, "Thin Film Thickness", "OUTPUT", "NodeSocketFloat")
        _sock(g, "Thin Film IOR", "OUTPUT", "NodeSocketFloat")
        _sock(g, "Thickness", "INPUT", "NodeSocketFloat", 0.5, 0.0, 1.0)
        _sock(g, "Structure", "INPUT", "NodeSocketFloat", 0.4, 0.0, 1.0)
        _sock(g, "Enable", "INPUT", "NodeSocketFloat", 0.0, 0.0, 1.0)
        gi = _new(g, "NodeGroupInput", "Group Input", (-620, 0))
        go = _new(g, "NodeGroupOutput", "Group Output", (620, 0))
        nm = _new(g, "ShaderNodeMath", "nm", (-380, 120),
                  "0..1 -> 0..800 nm  [ROUGH: magnitude only]")
        _prop(nm, "operation", "MULTIPLY")
        _sv(nm, 1, 800.0)
        gate = _new(g, "ShaderNodeMath", "gate", (-160, 120), "* Film_")
        _prop(gate, "operation", "MULTIPLY")
        ior = _new(g, "ShaderNodeMath", "ior", (-160, -140),
                   "structure -> film IOR 1.0..2.0")
        _prop(ior, "operation", "MULTIPLY_ADD")
        _sv(ior, 1, 1.0)
        _sv(ior, 2, 1.0)
        _link(g, gi, "Thickness", nm, 0)
        _link(g, nm, 0, gate, 0)
        _link(g, gi, "Enable", gate, 1)
        _link(g, gi, "Structure", ior, 0)
        _link(g, gate, 0, go, "Thin Film Thickness")
        _link(g, ior, 0, go, "Thin Film IOR")
    return _rebuild_group("FF7R Film", _b)


SHADING_MODELS = ["Standard (SM1)", "Skin (SM3)", "Subsurface Profile (SM5)",
                  "Hair (SM7)", "Cloth (SM8)", "Eye (SM9)", "Unlit (SM0)"]


# ================================================================= MATERIAL ==

# frame, role, kind, colourspace, neutral default        (PLAN 0.1 / 0.4)
#   kind: 'col' colour | 'val' scalar | 'nrm' loaded tangent-space normal RGB
ROLES = [
    ("Base",       "Color",                    "col", "sRGB",      (0.18, 0.18, 0.18, 1.0)),
    ("Base",       "Normal",                   "nrm", "Non-Color", (0.5, 0.5, 1.0, 1.0)),
    ("Base",       "Roughness",                "val", "Non-Color", 0.5),
    ("Base",       "Metallic",                 "val", "Non-Color", 0.0),
    ("Base",       "Occlusion",                "val", "Non-Color", 1.0),
    ("Base",       "WideOcclusion",            "val", "Non-Color", 1.0),
    ("Coverage",   "Coverage",                 "val", "Non-Color", 1.0),
    # Fur/card coverage. EID 10082 samples this separately in the alpha-test
    # path; neutral 1 keeps ordinary Coverage-only materials unchanged.
    ("Coverage",   "DetailCoverage",           "val", "Non-Color", 1.0),
    ("Detail",     "Detail",                   "val", "Non-Color", 1.0),
    ("Detail",     "DetailNormal",             "nrm", "Non-Color", (0.5, 0.5, 1.0, 1.0)),
    ("Detail",     "DetailRoughness",          "val", "Non-Color", 0.0),
    # DetailColor is an Overlay input; middle grey is its neutral element.
    ("Detail",     "DetailColor",              "col", "sRGB",      (0.5, 0.5, 0.5, 1.0)),
    ("Detail",     "DetailOcclusion",          "val", "Non-Color", 1.0),
    ("SkinCloth",  "Pores",                    "val", "Non-Color", 1.0),
    ("SkinCloth",  "Diffusion",                "val", "Non-Color", 1.0),
    ("Segment",    "SegmentLayer0",            "val", "Non-Color", 0.0),
    ("Segment",    "SegmentLayer1",            "val", "Non-Color", 0.0),
    ("Segment",    "ShadingLayer",             "val", "Non-Color", 0.0),
    ("Segment",    "LayeredColor",             "col", "sRGB",      (0.5, 0.5, 0.5, 1.0)),
    ("Emissive",   "Emissive",                 "col", "sRGB",      (0.0, 0.0, 0.0, 1.0)),
    ("Emissive",   "ExtraEmissive",            "col", "sRGB",      (0.0, 0.0, 0.0, 1.0)),
    # BC1 full-RGB direction: all three channels are authored, Z included.
    ("Hair",       "WideBentNormal",           "nrm", "Non-Color", (0.5, 0.5, 1.0, 1.0)),
    ("Transition", "PositiveTransitionNormal", "nrm", "Non-Color", (0.5, 0.5, 1.0, 1.0)),
    # eye  (PLAN 0.3 -- roles named from the JSON, not the shader slot numbers)
    ("Eye",        "IrisColor",                "col", "sRGB",      (0.3, 0.2, 0.1, 1.0)),
    ("Eye",        "IrisNormal",               "nrm", "Non-Color", (0.5, 0.5, 1.0, 1.0)),
    ("Eye",        "IrisOcclusion",            "val", "Non-Color", 1.0),
    ("Eye",        "IrisEmissive",             "col", "sRGB",      (0.0, 0.0, 0.0, 1.0)),
    ("Eye",        "ScrelaNormal",             "nrm", "Non-Color", (0.5, 0.5, 1.0, 1.0)),
    ("Eye",        "GazeNormal",               "nrm", "Non-Color", (0.5, 0.5, 1.0, 1.0)),
]

# Which UV set each role samples on.  Hair's flow map is the one that must be on
# UV1; getting this wrong looks like "the flow map does nothing" rather than an
# error (see the UV note in ff7r_hair_material.py).
# EID 10082's baked detail textures (coverage, colour, normal, roughness, and
# occlusion) use TEXCOORD_1.xy, the third packed coordinate. Detail itself is
# the placement mask, sampled on the second UV set; the hair flow map is also
# on UV1.
ROLE_UV = {"WideBentNormal": 1, "WideOcclusion": 1,
           "DetailCoverage": 2, "DetailColor": 2, "DetailNormal": 2,
           "DetailRoughness": 2, "Detail": 1, "DetailOcclusion": 2}

SWITCH_FOR_ROLE = {
    "Color": "Color_", "Normal": "Normal_", "Roughness": "Roughness_",
    "Metallic": "Metallic_", "Occlusion": "Occlusion_",
    "WideOcclusion": "WideOcclusion_", "Coverage": "Coverage_",
    "DetailCoverage": "DetailCoverage_",
    "Detail": "Detail_", "DetailNormal": "DetailNormal_",
    "DetailRoughness": "DetailRoughness_", "DetailColor": "DetailColor_",
    "DetailOcclusion": "DetailOcclusion_", "Pores": "Pores_",
    "Diffusion": "Diffusion_", "SegmentLayer0": "SegmentLayer0_",
    "SegmentLayer1": "SegmentLayer1_", "ShadingLayer": "ShadingLayer_",
    "LayeredColor": "LayeredColor_", "Emissive": "Emissive_",
    "ExtraEmissive": "ExtraEmissive_", "WideBentNormal": "WideBentNormal_",
    "PositiveTransitionNormal": "PositiveTransitionNormal_",
    "IrisColor": "IrisColor_", "IrisNormal": "IrisNormal_",
    "IrisOcclusion": "IrisOcclusion_", "IrisEmissive": "IrisEmissive_",
    "ScrelaNormal": "ScleraNormal_", "GazeNormal": "GazeNormal_",
}

_PROFILE_ROLES = {
    "Color", "Normal", "Emissive", "IrisColor", "IrisNormal",
    "IrisOcclusion", "IrisEmissive", "ScrelaNormal", "GazeNormal",
}
ROLES = [spec for spec in ROLES if spec[1] in _PROFILE_ROLES]
SWITCH_FOR_ROLE = {
    role: flag for role, flag in SWITCH_FOR_ROLE.items()
    if role in _PROFILE_ROLES
}

# PLAN 2.13 / 2.15 -- deliberately absent, reported at the end so the omission
# reads as intentional rather than an oversight.
OUT_OF_SCOPE = {
    "vertex domain (needs modifiers/geometry nodes, not a shader tree)":
        ["Deform_", "SoftBody_", "RigidBody_", "Convex_",
         "VertexExpressionPosition_", "ViewCoordinate_"],
    "separate shader family (forward-shaded, one shader per material instance)":
        ["Transparency_", "Transmittance_", "Opacity_", "Thin_", "Thick_",
         "ReflectanceGlass_", "ReflectanceWater_", "ReflectanceCrystal_",
         "PhaseGGlass_", "PhaseGWater_", "PhaseGCrystal_", "Muddiness_"],
    "late compositing pass (reads resolved SceneColor/Depth)":
        ["Hologram_", "Unlit_", "Phantom_", "Ghost_", "HologramEye_"],
    "captured permutation/base pass exists, but its feature math is not traced":
        ["Gradient*_", "BrokenFlow*_", "WideFlow*_", "CoverageIdentifier*_",
         "EyeMigration_", "HologramEye_", "Materia*_",
         "Wetness*_", "Ocean*_", "Flow*_", "Foam_", "Froth_", "Pool_"],
    "no captured carrier shader yet":
        ["Distribution_", "ExtraColor_", "Ghost_", "RigidBody_",
         "ViewCoordinate_"],
    "deferred-light behavior replaced by Blender-native Principled approximation":
        ["SM1 default", "SM3 skin", "SM5 subsurface profile", "SM7 hair",
         "SM8 cloth", "SM9 eye -- see DEFERRED_LIGHTING_HANDOFF.md"],
}


def _tex_slot(t, mat, role, kind, cs, default, frame, x, y, uvnodes,
              switch_source=None):
    """Image node + neutral-constant bypass, built in the MATERIAL tree.

    Groups share their node tree between instances, so an Image Texture inside a
    group would be the same image for every user of it -- texture slots have to
    live out here (see module docstring)."""
    img = _new(t, "ShaderNodeTexImage", "TEX_" + role, (x, y), role, frame)
    # Cubic softens Blender's harsh close-range normal-map filtering.
    _prop(img, "interpolation", "Cubic" if kind == "nrm" else "Linear")
    _prop(img, "extension", "REPEAT")
    dt = "RGBA" if kind in ("col", "nrm") else "FLOAT"
    sw = SWITCH_FOR_ROLE.get(role)
    byp = _new(t, "ShaderNodeMix", "USE_" + role, (x + SLOT_USE_DX, y),
               "%s   neutral / texture   [%s]" % (role, sw or "always"), frame)
    _prop(byp, "data_type", dt)
    _sv(byp, "A", default)
    _sv(byp, "B", default)
    _sv(byp, "Factor", 0.0)
    _link(t, img, "Color", byp, "B")
    if sw:
        if switch_source is not None:
            _link(t, switch_source, 0, byp, "Factor")
        else:
            _drive(_in(byp, "Factor"), mat, CONTROL_FOR_SWITCH.get(sw, sw))
    uv = uvnodes[ROLE_UV.get(role, 0)]
    _link(t, uv, 0, img, "Vector")
    return img, byp


def _resolve_uv_names(n=4):
    """Auto-populate UV-map names from `bpy.context.active_object`'s layers.

    The map order follows the mesh: layer 0 -> UV Map 0, layer 1 -> UV Map 1,
    and so on. UE's CoordinateN_ permutation declarations are deliberately
    not represented here or as material properties.

    Same convention as `resolve_uv_names()` in ff7r_hair_material.py, extended
    from 2 slots to N: a slot beyond the object's layer count is left blank
    ("") rather than aliased onto another layer.  A blank `uv_map` on a
    ShaderNodeUVMap means "the object's ACTIVE layer" (see the module
    docstring's UV_MAP note), which is the correct graceful degradation --
    pointing it at a named layer that does not exist would not fall back
    gracefully, it would just read zeros. Returns (names, notes); names[i] is
    "" for any slot with no corresponding layer."""
    notes = []
    obj = getattr(bpy.context, "active_object", None)
    layers = []
    if obj is not None and obj.type == "MESH":
        layers = [uvl.name for uvl in obj.data.uv_layers]
    elif obj is not None:
        notes.append("active object %r is not a mesh -- UV maps "
                     "left blank (active layer at render time)" % obj.name)
    else:
        notes.append("no active object -- UV maps left blank "
                     "(active layer at render time); select the target mesh "
                     "and re-run to auto-populate them")
    names = []
    for i in range(n):
        if i < len(layers):
            names.append(layers[i])
            notes.append("UV Map %d auto-resolved to %r (layer %d of %s)"
                         % (i, layers[i], i, obj.name))
        else:
            names.append("")
            if layers:
                notes.append("UV Map %d left blank -- %s has only %d UV "
                             "layer%s" % (i, obj.name, len(layers),
                                         "" if len(layers) == 1 else "s"))
    return names, notes


# ============================================================ EYE PROFILE ===

def build(*, uv_names=None):
    """Build the dedicated SM9 eye material profile.

    Only node paths reachable by one of the three Eye_ variants are created.
    The full generic base/detail, coverage, hair, and model-routing ladders are
    intentionally absent rather than hidden behind zero-valued switches.
    """
    if uv_names is None:
        uv_names, uv_notes = _resolve_uv_names(2)
    else:
        uv_names, uv_notes = list(uv_names[:2]), []
    _UV_NOTES.extend(uv_notes)
    util_tbn()
    util_frame_to_world()
    util_f0()
    eye_disc()
    eye_limbal_directional()
    eye_cornea()
    eye_limbal()
    eye_uv()
    grp_eye()
    grp_emissive()

    mat = bpy.data.materials.get(MAT_NAME) or bpy.data.materials.new(MAT_NAME)
    if mat.node_tree is None and bpy.app.version < (5, 0, 0):
        mat.use_nodes = True
    _ensure_props(mat)
    tree = mat.node_tree
    preserved = {node.name: node.image for node in tree.nodes
                 if node.bl_idname == "ShaderNodeTexImage" and node.image
                 and node.name.startswith("TEX_")}
    tree.nodes.clear()

    frames = {}
    for key, label in [
            ("Props", "MATERIAL CONTROLS  ->  EYE PROFILE"),
            ("Coords", "UV MAP SETS"), ("Base", "TEXTURES   Sclera"),
            ("Emissive", "TEXTURES   Emissive"), ("Eye", "TEXTURES   Iris / cornea"),
            ("EyePath", "SHADING   Eye  (SM 9)"), ("Out", "OUTPUT")]:
        frames[key] = _frame(tree, "FRAME_" + key, label)

    props, property_sources, property_types = {}, {}, {}
    for index, (name, members, _default) in enumerate(SWITCH_CONTROLS):
        column = min(index // SWITCH_COLUMN_LEN, len(SWITCH_COLUMNS) - 1)
        x, y = SWITCH_COLUMNS[column]
        node = _new(tree, "ShaderNodeValue", "SW_" + members[0],
                    (x, y - (index - column * SWITCH_COLUMN_LEN) * PROP_ROW_PITCH),
                    " + ".join(members), frames["Props"])
        _drive(node.outputs[0], mat, name)
        property_sources[name] = node
        property_types[name] = "BOOLEAN"
        for member in members:
            props[member] = node
    for index, (name, _default, _min, _max, _description) in enumerate(ENUM_PROPS):
        if name == "Shading Model" and HAS_MANUAL_MENU_SWITCH:
            node = _new(tree, MENU_INPUT_IDNAME, "E_Shading_Model",
                        (ENUM_COLUMN[0], ENUM_COLUMN[1] - index * PROP_ROW_PITCH),
                        name, frames["Props"])
        else:
            node = _new(tree, "ShaderNodeValue", "E_" + name.replace(" ", "_"),
                        (ENUM_COLUMN[0], ENUM_COLUMN[1] - index * PROP_ROW_PITCH),
                        name, frames["Props"])
            _drive(node.outputs[0], mat, name)
        props[name] = node
        property_sources[name] = node
        property_types[name] = ("MENU" if name == "Shading Model" and
                                HAS_MANUAL_MENU_SWITCH else "FLOAT")
    for index, (name, _default, _min, _max, _description) in enumerate(FLOAT_PROPS):
        node = _new(tree, "ShaderNodeValue", "P_" + name.replace(" ", "_"),
                    (FLOAT_COLUMN[0], FLOAT_COLUMN[1] - index * PROP_ROW_PITCH),
                    name, frames["Props"])
        _drive(node.outputs[0], mat, name)
        props[name] = node
        property_sources[name] = node
        property_types[name] = "FLOAT"

    uv = {}
    for index, uv_name in enumerate(uv_names):
        uv[index] = _new(tree, "ShaderNodeUVMap", "UV%d" % index,
                         (UV_COLUMN[0], UV_COLUMN[1] - index * UV_ROW_PITCH),
                         "UV Map %d" % index, frames["Coords"])
        if uv_name:
            _prop(uv[index], "uv_map", uv_name)
    slots, cursor = {}, {}
    for frame_key, role, kind, colourspace, default in ROLES:
        x, y = FRAME_ORIGIN[frame_key]
        y = cursor.get(frame_key, y + FRAME_PAD[1])
        cursor[frame_key] = y - SLOT_ROW_PITCH
        slots[role] = _tex_slot(tree, mat, role, kind, colourspace, default,
                                frames[frame_key], x + FRAME_PAD[0], y, uv,
                                props.get(SWITCH_FOR_ROLE.get(role)))

    def slot(role):
        return slots[role][1]

    sclera = _new(tree, "ShaderNodeNormalMap", "N_Sclera_Base_World", (2318, 2324),
                  "Normal / slot 2 -> sclera base world normal", frames["EyePath"])
    secondary = _new(tree, "ShaderNodeNormalMap", "N_Sclera_Secondary_World", (2146, 2202),
                    "ScleraNormal / slot 7 -> sclera secondary world normal", frames["EyePath"])
    gaze = _new(tree, "ShaderNodeNormalMap", "N_Gaze_World", (2147, 2048),
                "GazeNormal / slot 8 -> gaze world normal", frames["EyePath"])
    for node in (sclera, secondary, gaze):
        _prop(node, "space", "TANGENT")
        if uv_names[0]:
            _prop(node, "uv_map", uv_names[0])
        _convention(node, "DIRECTX")
        _link(tree, props["Normal Map Strength"], 0, node, "Strength")
    eye_uv_group = _grp(tree, "FF7R Eye UV", "EyeUV", (2319, 1887),
                        "eye disc + cornea (Iris UV)", frames["EyePath"])
    iris_unpack = _new(tree, "ShaderNodeVectorMath", "N_Iris_Detail", (2500, 1845),
                       "IrisNormal: DirectX vector", frames["EyePath"])
    _prop(iris_unpack, "operation", "MULTIPLY_ADD")
    _sv(iris_unpack, 1, (2.0, -2.0, 2.0))
    _sv(iris_unpack, 2, (-1.0, 1.0, -1.0))
    iris_world = _grp(tree, "UE Frame To World (explicit TBN)", "N_Iris_World",
                      (2690, 1810), "iris detail normal -> cornea frame", frames["EyePath"])
    eye = _grp(tree, "FF7R Eye", "Eye", (2502, 2300), "eye path (SM 9)",
               frames["EyePath"])
    _link(tree, slot("Normal"), "Result", sclera, "Color")
    _link(tree, slot("ScrelaNormal"), "Result", secondary, "Color")
    _link(tree, slot("GazeNormal"), "Result", gaze, "Color")
    _link(tree, slot("IrisNormal"), "Result", iris_unpack, 0)
    _link(tree, uv[0], "UV", eye_uv_group, "UV0")
    _link(tree, gaze, "Normal", eye_uv_group, "Gaze Normal")
    _link(tree, props["Pupil Dilation"], 0, eye_uv_group, "Pupil Dilation")
    _link(tree, eye_uv_group, "T2", iris_world, "T")
    _link(tree, eye_uv_group, "B2", iris_world, "B")
    _link(tree, gaze, "Normal", iris_world, "N")
    _link(tree, iris_unpack, 0, iris_world, "Vector")
    _link(tree, slot("Color"), "Result", eye, "Sclera Color")
    _link(tree, slot("IrisColor"), "Result", eye, "Iris Color")
    _link(tree, slot("IrisOcclusion"), "Result", eye, "Iris Occlusion")
    _link(tree, props["Eye Iris AO Factor"], 0, eye, "Iris AO Factor")
    _link(tree, slot("IrisEmissive"), "Result", eye, "Iris Emissive")
    _link(tree, sclera, "Normal", eye, "Sclera Base Normal")
    _link(tree, secondary, "Normal", eye, "Sclera Secondary Normal")
    _link(tree, gaze, "Normal", eye, "Gaze Normal")
    _link(tree, iris_world, "Vector", eye, "Iris Detail Normal")
    _link(tree, eye_uv_group, "Cornea Normal", eye, "Cornea Normal")
    _link(tree, eye_uv_group, "uvC2", eye, "uvC2")
    _link(tree, eye_uv_group, "r", eye, "r")
    _link(tree, eye_uv_group, "Sclera Mask", eye, "Sclera Mask")
    _link(tree, eye_uv_group, "T2", eye, "T2")
    _link(tree, eye_uv_group, "B2", eye, "B2")
    _link(tree, props["IrisEmissive_"], 0, eye, "IrisEmissive_")
    _link(tree, props["Eye Limbal Amount"], 0, eye, "Limbal Amount")
    for role in ("IrisColor", "IrisNormal", "IrisOcclusion", "IrisEmissive"):
        _link(tree, eye_uv_group, "Iris UV", slots[role][0], "Vector")

    f0 = _grp(tree, "FF7R Util/F0 Remap", "F0", (4300, 1050), "", frames["Out"])
    emissive = _grp(tree, "FF7R Emissive", "Emissive", (4300, 780), "", frames["Out"])
    if emissive.inputs.get("ExternalEmissiveContext") is not None:
        context = _new(tree, "ShaderNodeAttribute", "external_tint", (4060, 440),
                       'object["ExternalEmissiveContext"] -- per-instance, UNCLAMPED', frames["Out"])
        _prop(context, "attribute_type", "OBJECT")
        _prop(context, "attribute_name", "ExternalEmissiveContext")
        _link(tree, context, "Color", emissive, "ExternalEmissiveContext")
    _link(tree, props["GBufferA.a"], 0, f0, "GBufferA.a")
    _link(tree, slot("Emissive"), "Result", emissive, "Emissive")
    _link(tree, props["Emissive_"], 0, emissive, "Emissive_")
    # Eye variants never carry ExtraEmissive_; retain the group input at its neutral default.
    _link(tree, props["ExternalEmissive_"], 0, emissive, "ExternalEmissive_")
    base_roughness = _new(tree, "ShaderNodeValue", "EyeBaseRoughness", (4300, 520),
                          "neutral roughness (no Roughness_ eye variant)", frames["Out"])
    _sov(base_roughness, 0.5)
    roughness = _new(tree, "ShaderNodeMath", "EyeRoughness", (4500, 520),
                   "eye roughness ^ 0.4", frames["Out"])
    _prop(roughness, "operation", "POWER")
    _sv(roughness, 1, 0.4)
    _link(tree, base_roughness, 0, roughness, 0)
    emission_sum = _new(tree, "ShaderNodeMix", "EmissionSum", (4700, 800),
                        "emissive + iris glow", frames["Out"])
    _prop(emission_sum, "data_type", "RGBA")
    _prop(emission_sum, "blend_type", "ADD")
    _sv(emission_sum, "Factor", 1.0)
    _link(tree, emissive, "Emission", emission_sum, "A")
    _link(tree, eye, "Emission", emission_sum, "B")

    bsdf = _new(tree, "ShaderNodeBsdfPrincipled", "Principled BSDF", (5300, 850),
                "RMI_Surface Eye", frames["Out"])
    _expand_panels(bsdf)
    _sv(bsdf, "IOR", 1.3)
    _sv(bsdf, "Coat IOR", 1.15)
    _sv(bsdf, "Coat Weight", 1.0)
    _sv(bsdf, "Metallic", 0.0)
    _sv(bsdf, "Alpha", 1.0)
    out = _new(tree, "ShaderNodeOutputMaterial", "Material Output", (5700, 850), "", frames["Out"])
    _link(tree, eye, "Base Color", bsdf, "Base Color")
    _link(tree, eye, "Normal", bsdf, "Normal")
    _link(tree, eye, "Coat Normal", bsdf, "Coat Normal")
    _link(tree, roughness, 0, bsdf, "Roughness")
    _link(tree, f0, "Specular IOR Level", bsdf, "Specular IOR Level")
    _link(tree, emission_sum, "Result", bsdf, "Emission Color")
    emission_strength = _new(tree, "ShaderNodeMath", "EmissionStrength", (4900, 600),
                             "eye emissive strength", frames["Out"])
    _prop(emission_strength, "operation", "MAXIMUM")
    _link(tree, emissive, "Strength", emission_strength, 0)
    _sv(emission_strength, 1, 0.0)
    emissive_camera_only = _new(tree, "ShaderNodeAttribute", "EmissiveCameraOnlyAttribute",
                                 (5080, 510), 'object["sw EmissiveCameraOnly"]', frames["Out"])
    _prop(emissive_camera_only, "attribute_type", "OBJECT")
    _prop(emissive_camera_only, "attribute_name", "sw EmissiveCameraOnly")
    camera_ray = _new(tree, "ShaderNodeLightPath", "EmissiveCameraRay", (5080, 360),
                      "Is Camera Ray", frames["Out"])
    restricted = _new(tree, "ShaderNodeMath", "EmissionCameraRayStrength", (5260, 510),
                      "emission strength × camera ray", frames["Out"])
    _prop(restricted, "operation", "MULTIPLY")
    selector = _new(tree, "ShaderNodeMix", "EmissionCameraOnly", (5440, 600),
                    "camera-only emission", frames["Out"])
    _prop(selector, "data_type", "FLOAT")
    _prop(selector, "clamp_factor", True)
    _link(tree, emission_strength, 0, restricted, 0)
    _link(tree, camera_ray, "Is Camera Ray", restricted, 1)
    _link(tree, emissive_camera_only, "Fac", selector, "Factor")
    _link(tree, emission_strength, 0, selector, "A")
    _link(tree, restricted, 0, selector, "B")
    _link(tree, selector, "Result", bsdf, "Emission Strength")
    _link(tree, bsdf, 0, out, "Surface")

    _bundle_material_properties(tree, property_sources, property_types, frames["Props"])
    _fix_conventions(tree)
    _hide_unused_system_outputs(tree)
    for name, image in preserved.items():
        node = tree.nodes.get(name)
        if node is not None:
            node.image = image
    mat["_RMI_Profile"] = PROFILE_NAME
    mat["_RMI_Profile_Revision"] = PROFILE_REVISION
    return mat


# Guarded so that OTHER scripts can `importlib` this file to reuse its tables
# (SWITCH_CONTROLS, ROLES, SWITCH_FOR_ROLE, ...) without triggering build().
# Importing must not regenerate the master material. Shared node groups are
# additionally reused by _rebuild_group(), preserving their interface socket
# identities and all links in existing materials if the master is recreated.
if __name__ == "__main__":
    mat = build()
    _ng = [g for g in bpy.data.node_groups
           if g.name.startswith("FF7R") or g.name.startswith("UE ")]
    print("=" * 72)
    print("Built  %r" % mat.name)
    print("  Blender %s   MenuSwitch=%s   NormalMap.convention=%s"
          % (bpy.app.version_string, HAS_MENU_SWITCH, HAS_CONVENTION))
    print("  material nodes: %-5d node groups: %-4d texture slots: %d"
          % (len(mat.node_tree.nodes), len(_ng), len(ROLES)))
    print("  custom properties: %d bool controls for %d known flags + "
          "%d int selectors + %d floats"
          % (len(SWITCH_CONTROLS), len(KNOWN_SWITCHES),
             len(ENUM_PROPS), len(FLOAT_PROPS)))
    print("     (Material Properties > Custom Properties)")
    if _UV_NOTES:
        print("  UV Map Sets:")
        for m_ in _UV_NOTES:
            print("     " + m_)
    if not HAS_MENU_SWITCH:
        print("  NOTE: menus built as property-driven compare+mix ladders -- not "
              "a version gate, see _detect_menu_switch()'s docstring for why.")
    if _CONVENTION_FIXED:
        print("  NOTE: Blender < 5.2 -- spliced explicit green-flip maths before %s"
              % ", ".join(sorted(set(_CONVENTION_FIXED))))
    print("  Not reconstructed / deliberately delegated:")
    for why, items in OUT_OF_SCOPE.items():
        print("     %s\n        %s" % (why, ", ".join(items)))
    if _LOG:
        print("  %d issue(s):" % len(_LOG))
        for m in _LOG[:60]:
            print("     " + m)
    else:
        print("  no issues.")
print("=" * 72)
