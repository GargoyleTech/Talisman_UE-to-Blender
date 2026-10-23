"""Live UE light controls and finite-source approximations using Blender lights."""

import math
import json
import bpy

from . import lights as L
from . import light_photometry


DRIVER_REGISTRY = '_ue_light_parameter_drivers'
BAKED_PROP = 'ue_light_parameters_baked'


def _driver_key(curve):
    return f'{curve.array_index}:{curve.data_path}'


def driver(owner, path, expression, variables, index=None):
    """Only built-in expressions: saved files work without an enabled add-on."""
    curve = owner.driver_add(path) if index is None else owner.driver_add(path, index)
    d = curve.driver
    d.type = 'SCRIPTED'
    while d.variables:
        d.variables.remove(d.variables[0])
    for name, (target, data_path) in variables.items():
        variable = d.variables.new()
        variable.name = name
        variable.type = 'SINGLE_PROP'
        variable.targets[0].id_type = target.id_type
        variable.targets[0].id = target
        variable.targets[0].data_path = data_path
    d.expression = expression
    # Record ownership so baking cannot remove unrelated user drivers.
    registry_owner = owner.id_data
    if DRIVER_REGISTRY not in registry_owner:
        registry_owner[DRIVER_REGISTRY] = {}
    registry_owner[DRIVER_REGISTRY][_driver_key(curve)] = d.expression
    return curve


def _variables(obj, **names):
    return {name: (obj, f'["{prop}"]') for name, prop in names.items()}


def bind_light_controls(obj):
    data = obj.data
    if L.UE_ATTENUATION_RADIUS_PROP not in obj:
        return
    obj[BAKED_PROP] = False
    # Older imported lights can still use the corrected radial group. Only
    # newly resolved authoring values enable physical-power conversion.
    if L.UE_INTENSITY_PROP in obj:
        variables = _variables(obj, i=L.UE_INTENSITY_PROP, u=L.UE_UNIT_CODE_PROP,
            q=L.UE_INVERSE_SQUARED_FALLOFF_PROP, s=L.UE_SCALE_PROP, e=L.UE_EXPOSURE_PROP,
            k=L.UE_EFFICACY_PROP, r=L.UE_SOURCE_RADIUS_PROP, l=L.UE_SOURCE_LENGTH_PROP,
            w=L.UE_SOURCE_WIDTH_PROP, h=L.UE_SOURCE_HEIGHT_PROP)
        if data.type == 'SPOT':
            # Match UE's clamping when animated inner/outer angles cross.
            obj['ue_effective_outer_cone'] = obj[L.UE_OUTER_CONE_PROP]
            driver(obj, '["ue_effective_outer_cone"]',
                   'min(89*pi/180+0.001,max(a,min(89*pi/180,max(i,0))+0.001))',
                   _variables(obj, a=L.UE_OUTER_CONE_PROP, i=L.UE_INNER_CONE_PROP))
            variables.update(_variables(obj, a='ue_effective_outer_cone'))
        native_exposure = hasattr(data, 'exposure')
        driver(data, 'energy', light_photometry.energy_expression(data.type, native_exposure=native_exposure), variables)
        if native_exposure:
            driver(data, 'exposure', 'log(max(e,2**-32))/log(2) if e>0 else 0',
                   _variables(obj, e=L.UE_EXPOSURE_PROP))
    if hasattr(data, 'shadow_soft_size'):
        driver(data, 'shadow_soft_size', 'max(r,0)', _variables(obj, r=L.UE_SOURCE_RADIUS_PROP))
    if hasattr(data, 'cutoff_distance'):
        driver(data, 'cutoff_distance', 'max(r,0)', _variables(obj, r=L.UE_ATTENUATION_RADIUS_PROP))
        driver(data, 'use_custom_distance', 'not b', _variables(obj, b=L.UE_DISABLE_CUSTOM_ATTENUATION_PROP))
    if data.type == 'SPOT':
        variables = _variables(obj, a=L.UE_OUTER_CONE_PROP, i=L.UE_INNER_CONE_PROP,
            b=L.UE_DISABLE_CUSTOM_ATTENUATION_PROP, r=L.UE_SOURCE_RADIUS_PROP, l=L.UE_SOURCE_LENGTH_PROP)
        cone_driver = driver(data, 'spot_size',
            '2*min(89*pi/180+0.001,max(a,min(89*pi/180,max(i,0))+0.001)) if b or (r==0 and l==0 and abs(x-z)+abs(y-z)<0.000001) else pi', variables)
        # A scaled native cone can reject rays before the world-angle shader
        # runs. Open that sampling cone for nonuniform (including parent) scale.
        for name, axis in zip('xyz', 'XYZ'):
            variable = cone_driver.driver.variables.new()
            variable.name, variable.type = name, 'TRANSFORMS'
            variable.targets[0].id = obj
            variable.targets[0].transform_type = 'SCALE_' + axis
            variable.targets[0].transform_space = 'WORLD_SPACE'
        driver(data, 'spot_blend', 'max(0,min(1,1-i/max(a,0.001))) if b else 0', variables)
    if data.type == 'AREA':
        driver(data, 'size', 'max(v,0.000001)', _variables(obj, v=L.UE_SOURCE_WIDTH_PROP))
        driver(data, 'size_y', 'max(v,0.000001)', _variables(obj, v=L.UE_SOURCE_HEIGHT_PROP))
    if L.UE_TEMPERATURE_PROP in obj and hasattr(data, 'temperature'):
        driver(data, 'temperature', 'max(800,min(t,12000))', _variables(obj, t=L.UE_TEMPERATURE_PROP))
        driver(data, 'use_temperature', 'b', _variables(obj, b=L.UE_USE_TEMPERATURE_PROP))
    # UI values are canonical shader/driver inputs, including during animation.
    for prop in L.UE_LIGHT_OBJECT_PROPS:
        if prop in obj and isinstance(obj[prop], float):
            options = dict(min=0.0)
            if prop in {L.UE_INNER_CONE_PROP, L.UE_OUTER_CONE_PROP, L.UE_BARN_ANGLE_PROP}:
                options.update(subtype='ANGLE', max=math.radians(89) + 0.001)
                if prop == L.UE_BARN_ANGLE_PROP:
                    options['max'] = math.radians(88)
            obj.id_properties_ui(prop).update(**options)


def bind_temperature_nodes(data, emission):
    """Temperature fallback for Blender versions before native temperature."""
    tree = data.node_tree
    blackbody = tree.nodes.new('ShaderNodeBlackbody')
    blackbody.location = (-300, -380)
    temperature = tree.nodes.new('ShaderNodeAttribute')
    temperature.attribute_type = 'INSTANCER'
    temperature.attribute_name = L.UE_TEMPERATURE_PROP
    temperature.location = (-550, -380)
    enabled = tree.nodes.new('ShaderNodeAttribute')
    enabled.attribute_type = 'INSTANCER'
    enabled.attribute_name = L.UE_USE_TEMPERATURE_PROP
    enabled.location = (-550, -600)
    mix = tree.nodes.new('ShaderNodeMixRGB')
    mix.name = 'UE4 Temperature Tint'
    mix.inputs[1].default_value = (1, 1, 1, 1)
    mix.location = (-60, -380)
    tree.links.new(temperature.outputs['Fac'], blackbody.inputs[0])
    tree.links.new(enabled.outputs['Fac'], mix.inputs[0])
    tree.links.new(blackbody.outputs[0], mix.inputs[2])
    tree.links.new(mix.outputs[0], emission.inputs['Color'])


def bind_temperature_texture(data, texture, emission):
    tree = data.node_tree
    color = tree.nodes['UE4 Temperature Tint']
    multiply = tree.nodes.get('UE4 Textured Tint') or tree.nodes.new('ShaderNodeMixRGB')
    multiply.name = 'UE4 Textured Tint'
    multiply.blend_type = 'MULTIPLY'
    multiply.inputs[0].default_value = 1
    tree.links.new(color.outputs[0], multiply.inputs[1])
    tree.links.new(texture.outputs['Color'], multiply.inputs[2])
    tree.links.new(multiply.outputs[0], emission.inputs['Color'])


def ensure_source_helpers(obj, *, animated_length=False, animated_soft_radius=False):
    """Approximate UE tube/soft-highlight sources with sampled Blender emitters.

    Five midpoint samples approximate the capsule's line integral. A separate
    glossy-only source uses sqrt(radius^2 + soft_radius^2) while diffuse and
    volume lighting retain the authored radius. This is deliberately a Cycles
    approximation of UE's BRDF treatment, not a port of its analytic integral.
    """
    if obj.data.type not in {'POINT', 'SPOT'} or not obj.users_collection or obj.get('ue_light_helper'):
        return
    length = obj.get(L.UE_SOURCE_LENGTH_PROP, 0)
    soft = obj.get(L.UE_SOFT_SOURCE_RADIUS_PROP, 0)
    if animated_length:
        obj['ue_animated_source_length'] = True
    if animated_soft_radius:
        obj['ue_animated_soft_radius'] = True
    count = 5 if length > 0 or obj.get('ue_animated_source_length') else 1
    need_soft = soft > 0 or obj.get('ue_animated_soft_radius')
    obj[L.UE_SAMPLE_COUNT_PROP] = float(count)
    obj['ue_source_shape_approximation'] = '5 tube samples; separate glossy soft radius'
    # Reuse helpers so refreshing controls does not discard a user's parenting
    # or create duplicate emitters. Retired helpers are removed explicitly.
    existing = {child.get('ue_source_sample_key'): child for child in obj.children if child.get('ue_light_helper')}
    keep = set()
    soft_data = None
    bound_soft_data = set()
    axis = 1 if obj.data.type == 'SPOT' else 2  # UE source tangent is local +Z.
    for glossy in (False, True) if need_soft else (False,):
        for index in range(count):
            offset = (index + 0.5) / count - 0.5
            if not glossy and index == count // 2:
                continue
            key = f'{int(glossy)}:{index}:{count}'
            keep.add(key)
            helper = existing.get(key)
            if helper is None:
                if glossy and soft_data is None:
                    soft_data = obj.data.copy()
                    soft_data.name = obj.data.name + ' Soft Highlights'
                helper = bpy.data.objects.new(obj.name + (' Soft Highlight' if glossy else ' Tube Sample'),
                                               soft_data if glossy else obj.data)
                obj.users_collection[0].objects.link(helper)
                helper.parent = obj
                helper['ue_light_helper'] = True
                helper['ue_source_sample_key'] = key
                helper.hide_select = True
            if glossy and helper.data not in bound_soft_data:
                # Refresh also works after a static bake removed the copied
                # data drivers. Follow the primary's native settings again.
                bound_soft_data.add(helper.data)
                driver(helper.data, 'shadow_soft_size', 'sqrt(r*r+s*s)',
                       _variables(obj, r=L.UE_SOURCE_RADIUS_PROP, s=L.UE_SOFT_SOURCE_RADIUS_PROP))
                for path in ('energy', 'exposure', 'use_shadow', 'temperature', 'use_temperature', 'spot_size', 'spot_blend'):
                    if hasattr(helper.data, path):
                        driver(helper.data, path, 'v', {'v': (obj.data, path)})
                for channel in range(3):
                    driver(helper.data, 'color', 'c', {'c': (obj.data, f'color[{channel}]')}, channel)
            for prop in L.UE_LIGHT_OBJECT_PROPS:
                if prop not in obj:
                    continue
                helper[prop] = obj[prop]
                if prop not in {L.UE_SAMPLE_OFFSET_PROP, L.UE_ATTENUATION_RADIUS_UNITS_PROP}:
                    driver(helper, f'["{prop}"]', 'v', {'v': (obj, f'["{prop}"]')})
            for channel in range(3):
                expression = f'{offset!r}*l' if channel == axis else '0'
                variables = _variables(obj, l=L.UE_SOURCE_LENGTH_PROP)
                driver(helper, 'location', expression, variables, channel)
                driver(helper, f'["{L.UE_SAMPLE_OFFSET_PROP}"]', expression, variables, channel)
            driver(helper, 'hide_render', 'h', {'h': (obj, 'hide_render')})
            driver(helper, 'hide_viewport', 'h', {'h': (obj, 'hide_viewport')})
            if glossy:
                helper.visible_diffuse = False
                helper.visible_transmission = False
                helper.visible_volume_scatter = False
                helper.visible_camera = False
                driver(helper, 'visible_glossy', 's>0', _variables(obj, s=L.UE_SOFT_SOURCE_RADIUS_PROP))
            else:
                driver(helper, 'visible_glossy', 's<=0' if need_soft else '1',
                       _variables(obj, s=L.UE_SOFT_SOURCE_RADIUS_PROP))
    if need_soft:
        driver(obj, 'visible_glossy', 's<=0', _variables(obj, s=L.UE_SOFT_SOURCE_RADIUS_PROP))
    elif obj.animation_data and any(curve.data_path == 'visible_glossy' for curve in obj.animation_data.drivers):
        obj.driver_remove('visible_glossy')
        obj.visible_glossy = True
    for key, helper in existing.items():
        if key not in keep:
            data = helper.data
            bpy.data.objects.remove(helper, do_unlink=True)
            if data.users == 0:
                bpy.data.lights.remove(data)


def _has_animation(owner):
    animation = getattr(owner, 'animation_data', None)
    return bool(animation and (animation.action or any(track.strips for track in animation.nla_tracks)))


def _unowned_driver(owner):
    animation = getattr(owner, 'animation_data', None)
    registry = owner.get(DRIVER_REGISTRY, {})
    return bool(animation and any(registry.get(_driver_key(curve)) != curve.driver.expression
                                  for curve in animation.drivers))


def _rig_objects(obj):
    return [obj, *(child for child in obj.children if child.get('ue_light_helper'))]


def _rig_owners(objects):
    # Tube samples share data. Read and remove each datablock's drivers once.
    return list(dict.fromkeys(owner for obj in objects for owner in (obj, obj.data)))


def _can_bake_light(obj, objects, data_users):
    if obj.get('ue_animated_source_length') or obj.get('ue_animated_soft_radius'):
        return False
    owned_objects = set(objects)
    if any(data_users.get(item.data, set()) - owned_objects for item in objects):
        return False
    owners = _rig_owners(objects)
    owners.extend(item.data.node_tree for item in objects if item.data.node_tree)
    ancestor = obj.parent
    while ancestor is not None:
        owners.append(ancestor)
        if ancestor.data is not None:
            owners.append(ancestor.data)
        ancestor = ancestor.parent
    return not any(_has_animation(owner) or _unowned_driver(owner) for owner in owners)


def _write_baked_value(owner, path, axis, value, array):
    if array:
        owner.path_resolve(path)[axis] = value
    elif path.startswith('["'):
        owner[json.loads(path[1:-1])] = value
    else:
        parent_path, separator, name = path.rpartition('.')
        parent = owner.path_resolve(parent_path) if separator else owner
        setattr(parent, name, value)


def bake_static_light_parameters(light_objects):
    """Freeze evaluated importer drivers, preserving shader nodes and animation.

    All values are captured before any driver is removed, including helper
    offsets, visibility and shared data. Unrelated drivers or animation cause
    the whole light rig to be skipped. Returns the number of baked lights.
    """
    candidates = [obj for obj in light_objects if obj.type == 'LIGHT' and not obj.get('ue_light_helper')]
    data_users = {}
    for obj in bpy.data.objects:
        if obj.type == 'LIGHT':
            data_users.setdefault(obj.data, set()).add(obj)
    rigs = [_rig_objects(obj) for obj in candidates]
    rigs = [objects for obj, objects in zip(candidates, rigs) if _can_bake_light(obj, objects, data_users)]
    if not rigs:
        return 0
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    snapshots = []
    for owner in dict.fromkeys(owner for objects in rigs for owner in _rig_owners(objects)):
        animation = owner.animation_data
        if animation is None:
            continue
        evaluated = owner.evaluated_get(depsgraph)
        registry = owner.get(DRIVER_REGISTRY, {})
        for curve in animation.drivers:
            if _driver_key(curve) not in registry:
                continue
            if not curve.driver.is_valid:
                raise ValueError(f"Cannot bake invalid light driver: {owner.name} / {curve.data_path}")
            value = evaluated.path_resolve(curve.data_path)
            array = hasattr(value, '__len__') and not isinstance(value, str)
            snapshots.append((owner, curve.data_path, curve.array_index,
                              value[curve.array_index] if array else value, array))
    for owner, path, axis, value, array in snapshots:
        if array:
            owner.driver_remove(path, axis)
        else:
            owner.driver_remove(path)
    for owner, path, axis, value, array in snapshots:
        _write_baked_value(owner, path, axis, value, array)
    for objects in rigs:
        for owner in _rig_owners(objects):
            if DRIVER_REGISTRY in owner:
                del owner[DRIVER_REGISTRY]
        for obj in objects:
            obj[BAKED_PROP] = True
            obj.update_tag()
    return len(rigs)
