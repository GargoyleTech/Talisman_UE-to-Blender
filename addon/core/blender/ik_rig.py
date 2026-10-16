"""Optional two-bone limb IK, without changing imported bone rest transforms."""

import math

import bpy
from mathutils import Vector, Quaternion


CONTROL_TAG = "sqex_ik_control"
CONSTRAINT_NAME = "SQEX Limb IK"
BEND_CONSTRAINT_NAME = "SQEX IK Preferred Bend"


def _add_preferred_bend(armature, middle_bone, root_name, seed):
    """Constant local offset, evaluated before IK and unaffected by pose reset."""
    preferred_bend = middle_bone.constraints.new("TRANSFORM")
    preferred_bend.name = BEND_CONSTRAINT_NAME
    preferred_bend.target = armature
    preferred_bend.subtarget = root_name
    preferred_bend.target_space = "LOCAL"
    preferred_bend.owner_space = "LOCAL"
    preferred_bend.map_from = "LOCATION"
    preferred_bend.map_to = "ROTATION"
    preferred_bend.to_euler_order = "XYZ"
    preferred_bend.mix_mode_rot = "AFTER"
    # Equal output endpoints make this independent of root motion.
    for axis_name, angle in zip("xyz", seed.to_euler("XYZ")):
        setattr(preferred_bend, f"to_min_{axis_name}_rot", angle)
        setattr(preferred_bend, f"to_max_{axis_name}_rot", angle)
    return preferred_bend


def repair_limb_ik(armature):
    """Upgrade our earlier generated rigs without clearing poses or animation."""
    count = 0
    for middle in armature.pose.bones:
        ik = middle.constraints.get(CONSTRAINT_NAME)
        if (ik is None or ik.type != "IK" or ik.target != armature
                or ik.pole_target != armature or ik.chain_count != 2 or not ik.use_tail
                or middle.constraints.get(BEND_CONSTRAINT_NAME) is not None):
            continue
        target = armature.data.bones.get(ik.subtarget)
        pole = armature.data.bones.get(ik.pole_subtarget)
        upper = middle.bone.parent
        if (target is None or pole is None or upper is None
                or not target.get(CONTROL_TAG) or not pole.get(CONTROL_TAG)):
            continue
        start, bend, tip = upper.head_local, middle.bone.head_local, middle.bone.tail_local
        first, second = bend - start, tip - bend
        if min(first.length, second.length) < 1e-6:
            continue
        if first.normalized().dot(second.normalized()) <= .9999:
            continue
        normal = first.cross(pole.head_local - bend)
        if normal.length < first.length * 1e-6:
            continue
        seed_axis = middle.bone.matrix_local.to_3x3().inverted() @ normal.normalized()
        root = upper
        while root.parent:
            root = root.parent
        preferred = _add_preferred_bend(armature, middle, root.name, Quaternion(seed_axis, .01))
        middle.constraints.move(middle.constraints.find(preferred.name), middle.constraints.find(ik.name))
        count += 1
    armature.update_tag()
    bpy.context.view_layer.update()
    return count


def _widget(pole):
    name = "WGT_SQEX_IK_" + ("Pole" if pole else "Target")
    obj = bpy.data.objects.get(name)
    if obj is None:
        if pole:
            vertices = [(1, 0, 0), (0, 1, 0), (-1, 0, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)]
            edges = [(a, b) for a in range(4) for b in (4, 5)]
            edges += [(a, (a + 1) % 4) for a in range(4)]
        else:
            vertices = [(x, y, z) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
            edges = [(a, b) for a in range(8) for b in range(a + 1, 8)
                     if sum(vertices[a][i] != vertices[b][i] for i in range(3)) == 1]
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata(vertices, edges, [])
        obj = bpy.data.objects.new(name, mesh)
        # Unlinked widget objects remain available to pose bones without scene clutter.
        obj.hide_render = True
    return obj


def _calibrate_pole(armature, constraint, originals):
    """Fit the imported roll, including mirrored limbs and either import basis.

    Use evaluated rotations instead of assuming a particular local hinge axis.
    The one-dimensional fit is performed only during generation, never at runtime.
    """
    def error(angle):
        constraint.pole_angle = (angle + math.pi) % math.tau - math.pi
        armature.update_tag()
        bpy.context.view_layer.update()
        return sum((armature.pose.bones[name].matrix[r][c] - matrix[r][c]) ** 2
                   for name, matrix in originals.items() for r in range(3) for c in range(3))

    step = math.tau / 32
    center = min((i * step for i in range(32)), key=error)
    left, right = center - step, center + step
    ratio = (math.sqrt(5) - 1) / 2
    a, b = right - ratio * (right - left), left + ratio * (right - left)
    ea, eb = error(a), error(b)
    for _ in range(26):
        if ea < eb:
            right, b, eb = b, a, ea
            a = right - ratio * (right - left)
            ea = error(a)
        else:
            left, a, ea = a, b, eb
            b = left + ratio * (right - left)
            eb = error(b)
    error((left + right) / 2)


def generate_limb_ik(armature):
    """Create targets and poles for recognized, complete arm/leg chains.

    Called by the existing import checkbox. Returns target and pole counts.
    Controls follow the skeleton root, independently of hips and shoulders.
    """
    context = bpy.context
    active = context.view_layer.objects.active
    selected = list(context.selected_objects)
    mode = active.mode if active else "OBJECT"
    if mode not in {"OBJECT", "POSE"}:
        raise ValueError("Leave Edit Mode before generating IK controls.")
    if active and mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for obj in selected:
        obj.select_set(False)
    armature.select_set(True)
    context.view_layer.objects.active = armature
    count = 0
    try:
        for side in ("L", "R"):
            for end, middle, upper, joint in (("Hand", "Forearm", "UpperArm", "Elbow"),
                                               ("Foot", "Foreleg", "UpperLeg", "Knee")):
                names = [f"{side}_{part}_a" for part in (upper, middle, end)]
                bones = [armature.data.bones.get(n) for n in names]
                if any(b is None for b in bones):
                    continue
                if bones[1].parent != bones[0] or bones[2].parent != bones[1]:
                    continue
                target_name = f"SQEX_{side}_{end}_IK"
                pole_name = f"SQEX_{side}_{joint}_Pole"
                # Never overwrite similarly named user bones or duplicate our controls.
                if target_name in armature.data.bones or pole_name in armature.data.bones:
                    continue
                context.view_layer.update()
                originals = {n: armature.pose.bones[n].matrix.copy() for n in names}
                start, bend, tip = [originals[n].translation.copy() for n in names]
                axis = tip - start
                length = (bend - start).length + (tip - bend).length
                if min((bend - start).length, (tip - bend).length, axis.length) < 1e-6:
                    continue
                # The solver ends at the lower bone's tail. Unusual rigs with a
                # different endpoint need their own profile, not a rest-pose edit.
                if (armature.pose.bones[names[1]].tail - tip).length > length * 1e-4:
                    continue
                axis.normalize()
                needs_seed = (bend - start).normalized().dot((tip - bend).normalized()) > .9999
                direction = bend - start - axis * (bend - start).dot(axis)
                if needs_seed:
                    # Tiny rest-pose bends are unreliable: aim straight elbows back
                    # and knees forward, respecting the chosen import facing axis.
                    forward = Vector((0, -1, 0) if armature.get("sqex_face_forward") == "BLENDER" else (1, 0, 0))
                    preferred = forward * (-1 if end == "Hand" else 1)
                    direction = preferred - axis * preferred.dot(axis)
                if direction.length < length * 1e-4:
                    candidates = [originals[names[0]].to_3x3().col[i] for i in (0, 2)]
                    direction = max((v - axis * v.dot(axis) for v in candidates), key=lambda v: v.length)
                pole_position = bend + direction.normalized() * length * .7
                normal = (bend - start).cross(direction).normalized()
                seed_axis = originals[names[1]].to_3x3().inverted() @ normal
                seed = Quaternion(seed_axis, .01)
                root = bones[0]
                while root.parent:
                    root = root.parent
                root_name = root.name
                bpy.ops.object.mode_set(mode="EDIT")
                for name, matrix in ((target_name, originals[names[2]]),
                                     (pole_name, originals[names[0]])):
                    bone = armature.data.edit_bones.new(name)
                    bone.length = length * .12
                    bone.matrix = matrix
                    if name == pole_name:
                        bone.head = pole_position
                        bone.tail = pole_position + Vector((0, length * .12, 0))
                    bone.parent = armature.data.edit_bones[root_name]
                    bone.use_deform = False
                    bone[CONTROL_TAG] = True
                bpy.ops.object.mode_set(mode="OBJECT")
                collection = armature.data.collections.get("IK Controls") or armature.data.collections.new("IK Controls")
                collection.is_visible = True
                for name in (target_name, pole_name):
                    bone = armature.data.bones[name]
                    for old in list(bone.collections):
                        old.unassign(bone)
                    collection.assign(bone)
                    pb = armature.pose.bones[name]
                    pb.custom_shape = _widget(name == pole_name)
                    pb.use_custom_shape_bone_size = False
                    size = length * (.035 if name == pole_name else .055)
                    pb.custom_shape_scale_xyz = (size,) * 3
                    pb.lock_scale = (True,) * 3
                    if name == pole_name:
                        pb.lock_rotation = (True,) * 3
                    if hasattr(bone, "color"):
                        bone.color.palette = "THEME04" if side == "L" else "THEME01"
                middle_bone = armature.pose.bones[names[1]]
                if needs_seed:
                    # An ordinary pose rotation disappears on Alt-R. Supply the
                    # preferred bend through a constant additive transform instead,
                    # so the solver receives it after every pose/animation reset.
                    _add_preferred_bend(armature, middle_bone, root_name, seed)
                end_bone = armature.pose.bones[names[2]]
                constraint = armature.pose.bones[names[1]].constraints.new("IK")
                constraint.name = CONSTRAINT_NAME
                constraint.target = armature
                constraint.subtarget = target_name
                constraint.pole_target = armature
                constraint.pole_subtarget = pole_name
                # Solve only the upper/lower limb, never the shoulder or hip.
                constraint.chain_count = 2
                constraint.iterations = 100
                constraint.use_tail = True
                constraint.use_stretch = False
                _calibrate_pole(armature, constraint, {n: originals[n] for n in names[:2]})
                rotation = end_bone.constraints.new("COPY_ROTATION")
                rotation.name = "SQEX IK End Rotation"
                rotation.target = armature
                rotation.subtarget = target_name
                rotation.target_space = "POSE"
                rotation.owner_space = "POSE"
                count += 1
    finally:
        if armature.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        armature.select_set(False)
        for obj in selected:
            obj.select_set(True)
        context.view_layer.objects.active = active
        if active and mode != "OBJECT":
            bpy.ops.object.mode_set(mode=mode)
    return count, count
