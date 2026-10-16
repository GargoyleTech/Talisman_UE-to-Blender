"""Eight handles with smooth, interpolated offsets for Rebirth lip bones.

Catmull-Rom interpolation is evaluated once to produce fixed weights. Ordinary
Blender drivers blend control translations; offset constraints preserve the
incoming animation. No handlers or custom driver functions run during playback.
"""

from __future__ import annotations

from ...language import tooltips

import json
import math

import bpy
from mathutils import Vector

from . import mouth_rig as jaw


RIG_PROPERTY = "sqex_lip_rig"
CONSTRAINT = "SQEX Lip Shape"
RIGHT = "SQEX_LipCorner_R_CTRL"
LEFT = "SQEX_LipCorner_L_CTRL"
UPPER = (RIGHT, "SQEX_UpperLip_R_CTRL", "SQEX_UpperLip_C_CTRL", "SQEX_UpperLip_L_CTRL", LEFT)
LOWER = (RIGHT, "SQEX_LowerLip_R_CTRL", "SQEX_LowerLip_C_CTRL", "SQEX_LowerLip_L_CTRL", LEFT)
CONTROLS = tuple(dict.fromkeys(UPPER + LOWER))
UPPER_LIPS = tuple(name.replace("Dlip", "Ulip") for name in jaw.LIPS)
UPPER_CORNERS = tuple(name.replace("Dcor", "Ucor") for name in jaw.CORNERS)
PROPERTIES = ("lip_controls_influence", "show_lip_guides")


def spline_weights(t):
    """Five interpolating knots; clamp endpoints and duplicate end tangents."""
    x = max(0.0, min(1.0, t)) * 4
    segment = min(3, int(x))
    u = x - segment
    weights = [0.0] * 5
    for index, weight in zip(range(segment - 1, segment + 3), (
        -0.5*u + u*u - 0.5*u*u*u,
        1 - 2.5*u*u + 1.5*u*u*u,
        0.5*u + 2*u*u - 1.5*u*u*u,
        -0.5*u*u + 0.5*u*u*u,
    )):
        weights[max(0, min(4, index))] += weight
    return weights


def _profile(armature):
    bones = armature.data.bones
    required = ("C_Ulip", "C_Dlip", "L_Ucor", "R_Ucor", "L_Dcor", "R_Dcor")
    if not all(name in bones for name in required):
        return None  # A sparse jaw-only rig remains useful.
    _, jaw_matrix, width = jaw._profile(armature)
    lateral = jaw_matrix.col[0].to_3d()
    forward = jaw_matrix.col[1].to_3d()
    up = -jaw_matrix.col[2].to_3d()
    points = {name: bones[name].head_local.copy() for name in required}
    corners = {
        RIGHT: (points["R_Ucor"] + points["R_Dcor"]) * 0.5,
        LEFT: (points["L_Ucor"] + points["L_Dcor"]) * 0.5,
    }
    left_x, right_x = (corners[n].dot(lateral) for n in (LEFT, RIGHT))
    if left_x - right_x < width * 0.1:
        raise ValueError("Lip corners are too close to estimate a lip curve.")
    anchors = dict(corners)
    targets = {}
    for family, controls, names in (("U", UPPER, UPPER_LIPS), ("D", LOWER, jaw.LIPS)):
        center = points[f"C_{family}lip"]
        center_x = center.dot(lateral)
        if not right_x < center_x < left_x:
            raise ValueError("Lip center is outside the mouth corners.")
        anchors[controls[2]] = center
        for side, index, corner in (("R", 1, RIGHT), ("L", 3, LEFT)):
            position = (center + corners[corner]) * 0.5
            # Place the halfway handle on the lip's original contour.
            samples = [center, corners[corner]] + [bones[name].head_local.copy()
                for name in (f"{side}_{family}lip_A", f"{side}_{family}lip_B") if name in bones]
            samples.sort(key=lambda p: p.dot(lateral))
            x = position.dot(lateral)
            for a, b in zip(samples, samples[1:]):
                if a.dot(lateral) <= x <= b.dot(lateral) and (b-a).dot(lateral) > 1e-8:
                    position = a.lerp(b, (x-a.dot(lateral)) / (b-a).dot(lateral))
                    break
            anchors[controls[index]] = position
        for name in names:
            if name not in bones:
                continue
            x = bones[name].head_local.dot(lateral)
            t = (0.5 + 0.5 * (x-center_x) / (left_x-center_x) if x >= center_x
                 else 0.5 * (x-right_x) / (center_x-right_x))
            targets[name] = list(zip(controls, spline_weights(t)))
    for name in jaw.CORNERS + UPPER_CORNERS:
        if name in bones:
            targets[name] = [(LEFT if name.startswith("L_") else RIGHT, 1.0)]
    for name in targets:
        if bones[name].parent != bones[jaw.FACE] or bones[name].use_connect:
            raise ValueError(f"Lip bone '{name}' is not an unconnected face-base child.")
    # Bring handles forward of the skin without changing their translation axes.
    anchors = {name: point + forward * width * 0.15 for name, point in anchors.items()}
    return anchors, targets, width, lateral, up


def _variable(driver, name, armature, path):
    var = driver.variables.new()
    var.name = name
    var.type = "SINGLE_PROP"
    var.targets[0].id = armature
    var.targets[0].data_path = path


def _record_driver(fcurve, manifest):
    manifest["drivers"].append([fcurve.data_path, fcurve.array_index])
    fcurve.driver.type = "SCRIPTED"
    return fcurve.driver


def _widget(context, armature, width, lateral, up, manifest):
    mesh = bpy.data.meshes.new(f"WGT_{armature.name}_LipHandle")
    manifest["widget_mesh"] = mesh.name
    basis = armature.data.bones[jaw.FACE].matrix_local.to_3x3().inverted()
    vertices = [basis @ (lateral * math.cos(i*math.tau/20) + up * math.sin(i*math.tau/20)) for i in range(20)]
    mesh.from_pydata(vertices, [(i, (i+1) % 20) for i in range(20)], [])
    obj = bpy.data.objects.new(mesh.name, mesh)
    manifest["widget"] = obj.name
    context.collection.objects.link(obj)
    obj.hide_render = True
    obj.hide_set(True)
    for name in CONTROLS:
        control = armature.pose.bones[name]
        control.custom_shape = obj
        control.use_custom_shape_bone_size = False
        control.custom_shape_scale_xyz = (width * (0.043 if name in (LEFT, RIGHT) else 0.035),) * 3
        control.lock_rotation = control.lock_scale = (True,) * 3
        control.bone.color.palette = "THEME09" if name in (LEFT, RIGHT) else (
            "THEME03" if name in UPPER else "THEME04")


def _guides(context, armature, manifest):
    for label, controls in (("Upper", UPPER), ("Lower", LOWER)):
        curve = bpy.data.curves.new(f"SQEX_{armature.name}_{label}LipGuide", "CURVE")
        manifest["curves"].append(curve.name)
        curve.dimensions = "3D"
        curve.resolution_u = 12
        spline = curve.splines.new("BEZIER")
        spline.bezier_points.add(4)
        for i, (point, name) in enumerate(zip(spline.bezier_points, controls)):
            # Explicit Catmull-Rom tangents follow driven points reliably.
            # AUTO handles are not recalculated consistently for RNA co drivers.
            point.handle_left_type = point.handle_right_type = "FREE"
            point.co = armature.pose.bones[name].matrix.translation
            for axis in range(3):
                driver = curve.driver_add(f"splines[0].bezier_points[{i}].co", axis).driver
                driver.type = "SCRIPTED"
                # RNA driver paths index matrices column-first, unlike mathutils.
                _variable(driver, "p", armature, f'pose.bones["{name}"].matrix[3][{axis}]')
                driver.expression = "p"
                for handle, sign in (("handle_left", "-"), ("handle_right", "+")):
                    driver = curve.driver_add(f"splines[0].bezier_points[{i}].{handle}", axis).driver
                    driver.type = "SCRIPTED"
                    for var, target in (("c", name), ("p", controls[max(0, i-1)]),
                                        ("n", controls[min(4, i+1)])):
                        _variable(driver, var, armature, f'pose.bones["{target}"].matrix[3][{axis}]')
                    driver.expression = f"c{sign}(n-p)/6"
        obj = bpy.data.objects.new(curve.name, curve)
        manifest["guides"].append(obj.name)
        context.collection.objects.link(obj)
        obj.parent = armature
        obj.hide_render = True
        obj.hide_select = True
        obj.show_in_front = True
        obj.color = (0.3, 0.8, 0.6, 1.0) if label == "Upper" else (0.3, 0.6, 1.0, 1.0)
        driver = obj.driver_add("hide_viewport").driver
        _variable(driver, "show", armature, f'pose.bones["{jaw.CONTROL}"]["show_lip_guides"]')
        driver.expression = "not show"


def _remove_owned(armature, manifest):
    for path, index in manifest["drivers"]:
        curve = armature.animation_data.drivers.find(path, index=index) if armature.animation_data else None
        if curve:
            armature.animation_data.drivers.remove(curve)
    for name, constraint_name in manifest["constraints"]:
        pose = armature.pose.bones.get(name)
        c = pose.constraints.get(constraint_name) if pose else None
        if (c and c.type in {"COPY_LOCATION", "COPY_TRANSFORMS"}
                and c.target == armature and c.subtarget in set(manifest["bones"]) | {jaw.DELTA}):
            c.driver_remove("influence")
            pose.constraints.remove(c)
    for name, hidden in manifest["hidden"]:
        if name in armature.data.bones:
            armature.data.bones[name].hide = hidden
    for name in manifest["guides"] + [manifest.get("widget", "")]:
        obj = bpy.data.objects.get(name)
        if obj:
            bpy.data.objects.remove(obj, do_unlink=True)
    for name in manifest["curves"]:
        curve = bpy.data.curves.get(name)
        if curve and curve.users == 0:
            bpy.data.curves.remove(curve)
    mesh = bpy.data.meshes.get(manifest.get("widget_mesh", ""))
    if mesh and mesh.users == 0:
        bpy.data.meshes.remove(mesh)
    bpy.ops.object.mode_set(mode="EDIT")
    for name in reversed(manifest["bones"]):
        bone = armature.data.edit_bones.get(name)
        if bone:
            armature.data.edit_bones.remove(bone)
    bpy.ops.object.mode_set(mode="OBJECT")
    for name in manifest["collections"]:
        collection = armature.data.collections.get(name)
        if collection and not collection.bones:
            armature.data.collections.remove(collection)
    control = armature.pose.bones.get(jaw.CONTROL)
    for name in manifest["properties"]:
        if control and name in control:
            del control[name]


def remove_lip_rig(context, armature):
    raw = armature.get(RIG_PROPERTY)
    if not raw:
        return False
    manifest = json.loads(raw)
    if manifest.get("version") != 1 or armature.data.users != 1:
        raise ValueError("Lip controls require a supported version and single-user armature data.")
    for name in manifest["bones"]:
        bone = armature.data.bones.get(name)
        if bone and any(child.name not in manifest["bones"] for child in bone.children):
            raise ValueError(f"'{name}' has additional children; detach them before removal.")
    with jaw._edit_context(context, armature):
        _remove_owned(armature, manifest)
        del armature[RIG_PROPERTY]
    return True


def generate_lip_rig(context, armature):
    raw = armature.get(RIG_PROPERTY)
    if raw:
        manifest = json.loads(raw)
        if (manifest.get("version") == 1 and all(n in armature.data.bones for n in manifest["bones"])
                and all(armature.pose.bones.get(n) and armature.pose.bones[n].constraints.get(c)
                        for n, c in manifest["constraints"])):
            return len(manifest["hidden"])
        raise ValueError("Existing lip controls are incomplete; remove mouth controls before rebuilding.")
    profile = _profile(armature)
    if profile is None:
        return 0
    anchors, targets, width, lateral, up = profile
    helpers = {name: f"SQEX_LipOffset_{name}" for name in targets}
    for name in CONTROLS + tuple(helpers.values()):
        if name in armature.data.bones:
            raise ValueError(f"Reserved lip bone '{name}' already exists.")
    for name in targets:
        if armature.pose.bones[name].constraints.get(CONSTRAINT):
            raise ValueError(f"Reserved lip constraint already exists on '{name}'.")
    for prop in PROPERTIES:
        if prop in armature.pose.bones[jaw.CONTROL]:
            raise ValueError(f"Reserved property '{prop}' already exists on the jaw control.")
    context.view_layer.update()
    incoming = {b.name: b.matrix.copy() for b in armature.pose.bones}
    manifest = {"version": 1, "bones": [], "constraints": [], "drivers": [],
                "collections": [], "hidden": [], "guides": [], "curves": [], "properties": []}
    with jaw._edit_context(context, armature):
        try:
            bpy.ops.object.mode_set(mode="EDIT")
            bones = armature.data.edit_bones
            for name in CONTROLS + tuple(helpers.values()):
                bone = bones.new(name)
                manifest["bones"].append(bone.name)
                bone.length = width * 0.08
                matrix = bones[jaw.FACE].matrix.copy()
                if name in anchors:
                    matrix.translation = anchors[name]
                bone.matrix = matrix
                bone.parent = bones[jaw.FACE]
                bone.use_deform = False
            bpy.ops.object.mode_set(mode="OBJECT")
            for label, names, visible in (("Lip Controls", CONTROLS, True), ("Lip Helpers", helpers.values(), False)):
                collection = armature.data.collections.new(label)
                manifest["collections"].append(collection.name)
                collection.is_visible = visible
                for name in names:
                    bone = armature.data.bones[name]
                    for previous in list(bone.collections):
                        previous.unassign(bone)
                    collection.assign(bone)
            control = armature.pose.bones[jaw.CONTROL]
            jaw._property(control, PROPERTIES[0], 1.0, tooltips.MOUTH_LIP_CONTROLS_INFLUENCE)
            manifest["properties"].append(PROPERTIES[0])
            control[PROPERTIES[1]] = True
            manifest["properties"].append(PROPERTIES[1])
            control.id_properties_ui(PROPERTIES[1]).update(description=tooltips.MOUTH_SHOW_LIP_GUIDES)
            _widget(context, armature, width, lateral, up, manifest)
            for name in LOWER:
                c = jaw._add_jaw_constraint(armature, name, "corner_follow" if name in (LEFT, RIGHT) else "lip_follow", manifest)
                fcurve = armature.animation_data.drivers.find(c.path_from_id("influence"))
                _record_driver(fcurve, manifest)
            for name, weights in targets.items():
                helper = armature.pose.bones[helpers[name]]
                for axis in range(3):
                    driver = _record_driver(helper.driver_add("location", axis), manifest)
                    terms = []
                    for i, (handle, weight) in enumerate(weights):
                        if abs(weight) < 1e-10:
                            continue
                        _variable(driver, f"p{i}", armature, f'pose.bones["{handle}"].location[{axis}]')
                        terms.append(f"({weight:.10g})*p{i}")
                    driver.expression = "+".join(terms)
                pose = armature.pose.bones[name]
                c = pose.constraints.new("COPY_LOCATION")
                c.name = CONSTRAINT
                c.target = armature
                c.subtarget = helper.name
                c.owner_space = c.target_space = "CUSTOM"
                c.space_object = armature
                c.space_subtarget = jaw.FACE
                c.use_offset = True
                manifest["constraints"].append([name, c.name])
                driver = _record_driver(c.driver_add("influence"), manifest)
                _variable(driver, "amount", armature, f'pose.bones["{jaw.CONTROL}"]["{PROPERTIES[0]}"]')
                driver.expression = "amount"
                # Shape offsets are applied before jaw motion, just like the
                # original pose channels. Opening the jaw carries the lip shape.
                jaw_constraint = pose.constraints.get(jaw.CONSTRAINT)
                if jaw_constraint:
                    pose.constraints.move(len(pose.constraints)-1, list(pose.constraints).index(jaw_constraint))
                manifest["hidden"].append([name, armature.data.bones[name].hide])
                armature.data.bones[name].hide = True
            armature.update_tag()
            context.view_layer.update()
            _guides(context, armature, manifest)
            context.view_layer.update()
            for name, matrix in incoming.items():
                result = armature.pose.bones[name].matrix
                if ((result.translation-matrix.translation).length > width*1e-4
                        or max(abs(result[r][c]-matrix[r][c]) for r in range(3) for c in range(3)) > 1e-4):
                    raise ValueError(f"Lip setup changed the incoming pose of '{name}'; setup was removed.")
            armature[RIG_PROPERTY] = json.dumps(manifest)
        except Exception:
            if armature.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            _remove_owned(armature, manifest)
            raise
    return len(targets)
