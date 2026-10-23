"""Cycles emission masks corresponding to UE4's deferred local-light shaders.

Blender still integrates the emitter and BSDF. These groups supply UE's radial
and angular masks, not another inverse-square falloff on top of Cycles.
"""

import bpy

SCHEMA = "ue427-local-light-masks-2026-10"


class Graph:
    def __init__(self, tree):
        self.tree = tree
        self.depths = {}
        self.rows = {}

    def node(self, kind, label, *values):
        node = self.tree.nodes.new(kind)
        node.label = node.name = label
        depth = 0
        for index, value in enumerate(values):
            if isinstance(value, bpy.types.NodeSocket):
                self.tree.links.new(value, node.inputs[index])
                depth = max(depth, self.depths.get(value.node.name, 0) + 1)
            elif value is not None:
                node.inputs[index].default_value = value
        row = self.rows.get(depth, 0)
        self.rows[depth] = row + 1
        node.location = (depth * 210, -row * 170)
        self.depths[node.name] = depth
        return node

    def math(self, op, a, b=None, label=None):
        node = self.node('ShaderNodeMath', label or op.title(), a, b)
        node.operation = op
        return node.outputs[0]

    def vector(self, op, a, b=None, label=None):
        node = self.node('ShaderNodeVectorMath', label or op.title(), a, b)
        node.operation = op
        return node.outputs['Value' if op in {'LENGTH', 'DOT_PRODUCT', 'DISTANCE'} else 'Vector']

    def scale(self, vector, amount, label):
        node = self.node('ShaderNodeVectorMath', label, vector)
        node.operation = 'SCALE'
        self.connect(amount, node.inputs['Scale'])
        return node.outputs['Vector']

    def connect(self, value, socket):
        if isinstance(value, bpy.types.NodeSocket):
            self.tree.links.new(value, socket)
        else:
            socket.default_value = value

    def clamp(self, value):
        return self.math('MINIMUM', self.math('MAXIMUM', value, 0), 1)

    def mix(self, a, b, factor, label):
        return self.math('ADD', self.math('MULTIPLY', a, self.math('SUBTRACT', 1, factor)),
                         self.math('MULTIPLY', b, factor), label)

    def attr(self, name, label):
        node = self.node('ShaderNodeAttribute', label)
        node.attribute_type = 'INSTANCER'
        node.attribute_name = name
        return node.outputs['Fac']

    def transform(self, value, vector_type, convert_from, convert_to, label):
        node = self.node('ShaderNodeVectorTransform', label, value)
        node.vector_type = vector_type
        node.convert_from, node.convert_to = convert_from, convert_to
        return node.outputs[0]

    def layout(self):
        """Lay out the completed graph, including late-connected group sockets."""
        depths, rows = {}, {}

        def depth(node):
            if node.name not in depths:
                parents = [link.from_node for socket in node.inputs for link in socket.links]
                depths[node.name] = 1 + max((depth(parent) for parent in parents), default=-1)
            return depths[node.name]

        for node in self.tree.nodes:
            column = depth(node)
            node.width = 210
            node.location = (column * 270, -rows.get(column, 0))
            rows[column] = rows.get(column, 0) + max(220, 100 + 28 * len(node.inputs))


def _group(name, inputs, outputs, build):
    tree = bpy.data.node_groups.get(name)
    if tree is not None and tree.get('ue_light_schema') == SCHEMA:
        return tree
    if tree is None:
        tree = bpy.data.node_groups.new(name, 'ShaderNodeTree')
    tree.nodes.clear()
    # Keep existing sockets/links when upgrading a saved group in place.
    existing = {(item.in_out, item.name) for item in tree.interface.items_tree if item.item_type == 'SOCKET'}
    for direction, sockets in (('INPUT', inputs), ('OUTPUT', outputs)):
        for socket_name, socket_type in sockets:
            if (direction, socket_name) not in existing:
                tree.interface.new_socket(name=socket_name, in_out=direction, socket_type=socket_type)
    graph = Graph(tree)
    incoming = graph.node('NodeGroupInput', 'Inputs')
    outgoing = graph.node('NodeGroupOutput', 'Output')
    build(graph, incoming.outputs, outgoing.inputs)
    graph.layout()
    tree['ue_light_schema'] = SCHEMA
    return tree


F = 'NodeSocketFloat'
V = 'NodeSocketVector'


def radial_group():
    def build(g, i, o):
        radius = g.math('MAXIMUM', i['Radius'], 1e-6, 'Safe radius')
        x = g.math('DIVIDE', i['Distance'], radius, 'Center distance / radius')
        x2 = g.math('MULTIPLY', x, x, '(d / R)^2')
        x4 = g.math('MULTIPLY', x2, x2, '(d / R)^4')
        mask = g.clamp(g.math('SUBTRACT', 1, x4))
        mask = g.math('MULTIPLY', mask, mask, 'UE inverse-square radius mask')
        d2 = g.math('MULTIPLY', i['Ray Distance'], i['Ray Distance'], 'Ray distance squared')
        # UE's 1 cm^2 bias is independent of emitter radius. Rect lights use
        # their native area integral and only receive the radius mask.
        center2 = g.math('MULTIPLY', i['Source Distance'], i['Source Distance'])
        bias_factor = g.math('DIVIDE', d2, g.math('MAXIMUM',
            g.math('ADD', center2, i['Bias Squared']), 1e-12), 'UE point distance correction')
        inverse = g.math('MULTIPLY', mask, g.mix(bias_factor, 1, i['Area Light'], 'Area / point falloff'))
        legacy = g.math('POWER', g.clamp(g.math('SUBTRACT', 1, x2)),
                        g.math('MAXIMUM', i['Exponent'], 0.0001), 'UE exponent radius mask')
        legacy = g.math('MULTIPLY', d2, legacy, 'Cancel native falloff for exponent lights')
        result = g.mix(legacy, inverse, g.clamp(i['Inverse Squared']), 'UE radial attenuation')
        result = g.math('MULTIPLY', result, g.math('GREATER_THAN', i['Radius'], 0), 'Zero radius emits nothing')
        g.connect(result, o['Strength'])
    return _group('UE4 Radial Falloff', [(name, F) for name in
        ('Distance', 'Source Distance', 'Ray Distance', 'Radius', 'Inverse Squared', 'Exponent', 'Bias Squared', 'Area Light')],
        [('Strength', F)], build)


def cone_group():
    def build(g, i, o):
        direction = g.vector('NORMALIZE', i['Receiver'], label='Direction from light center')
        cosine = g.vector('DOT_PRODUCT', direction, (0, 0, -1), 'Cosine to forward axis')
        inner_angle = g.math('MINIMUM', g.math('MAXIMUM', i['Inner Half Angle'], 0), 1.553343034)
        outer_angle = g.math('MINIMUM', g.math('MAXIMUM', i['Outer Half Angle'],
                                             g.math('ADD', inner_angle, 0.001)), 1.554343034)
        inner = g.math('COSINE', inner_angle)
        outer = g.math('COSINE', outer_angle)
        ramp = g.clamp(g.math('DIVIDE', g.math('SUBTRACT', cosine, outer),
                             g.math('MAXIMUM', g.math('SUBTRACT', inner, outer), 1e-7)))
        g.connect(g.math('MULTIPLY', ramp, ramp, 'UE squared cosine cone'), o['Mask'])
    return _group('UE4 Spot Cone', [('Receiver', V), ('Inner Half Angle', F), ('Outer Half Angle', F)],
                  [('Mask', F)], build)


def rect_group():
    def build(g, i, o):
        receiver = g.node('ShaderNodeSeparateXYZ', 'Receiver in light space', i['Receiver']).outputs
        emitter = g.node('ShaderNodeSeparateXYZ', 'Sample on rectangle', i['Emitter']).outputs
        angle = g.math('MINIMUM', g.math('MAXIMUM', i['Barn Angle'], 0), 1.535889742)
        cos_angle = g.math('COSINE', angle)
        sin_angle = g.math('SINE', angle)
        depth = g.math('MAXIMUM', g.math('MULTIPLY', cos_angle, i['Barn Length']), 1e-6)
        z = g.math('MULTIPLY', receiver['Z'], -1, 'Distance in front of light')
        # Intersect the sample-to-receiver ray with the end of the barn doors.
        # For receivers inside the doors, test at the receiver itself. This
        # samples the aperture that UE approximates with its visible rectangle.
        fraction = g.clamp(g.math('DIVIDE', depth, g.math('MAXIMUM', z, 1e-6)))
        flare = g.math('MULTIPLY', sin_angle, i['Barn Length'])
        fraction_depth = g.math('DIVIDE', g.math('MINIMUM', g.math('MAXIMUM', z, 0), depth), depth)
        flare = g.math('MULTIPLY', flare, fraction_depth)
        masks = []
        for axis, size in (('X', 'Width'), ('Y', 'Height')):
            cross = g.mix(emitter[axis], receiver[axis], fraction, 'Ray at barn aperture ' + axis)
            limit = g.math('ADD', g.math('MULTIPLY', i[size], 0.5), flare)
            masks.append(g.math('LESS_THAN', g.math('ABSOLUTE', cross), limit))
        barn = g.math('MULTIPLY', masks[0], masks[1], 'Rectangular aperture')
        enabled = g.math('MULTIPLY', g.math('GREATER_THAN', cos_angle, 0.035),
                         g.math('GREATER_THAN', i['Barn Length'], 0))
        result = g.math('MULTIPLY', g.mix(1, barn, enabled, 'Barn door enabled'),
                        g.math('GREATER_THAN', z, 0), 'Front hemisphere only')
        g.connect(result, o['Mask'])
    return _group('UE4 Rect Barn Doors', [('Receiver', V), ('Emitter', V), ('Width', F), ('Height', F),
                  ('Barn Angle', F), ('Barn Length', F)], [('Mask', F)], build)


def attenuation_group():
    from . import lights as L

    def build(g, _i, o):
        geometry = g.node('ShaderNodeNewGeometry', 'Light sample')
        ray = g.node('ShaderNodeLightPath', 'Distance to receiving surface').outputs['Ray Length']
        receiver_world = g.vector('ADD', geometry.outputs['Position'],
            g.scale(geometry.outputs['Incoming'], ray, 'Ray to receiving surface'), 'Receiving surface position')
        receiver = g.transform(receiver_world, 'POINT', 'WORLD', 'OBJECT', 'Receiver in light coordinates')
        sample_delta = g.transform(receiver, 'VECTOR', 'OBJECT', 'WORLD', 'World distance from source sample')
        sample_distance = g.vector('LENGTH', sample_delta, label='Source sample distance')
        emitter = g.transform(geometry.outputs['Position'], 'POINT', 'WORLD', 'OBJECT', 'Emitter in light coordinates')
        # Tube samples share the primary light's center for cutoff/cone masks.
        offset_node = g.node('ShaderNodeAttribute', 'Tube sample offset')
        offset_node.attribute_type = 'INSTANCER'
        offset_node.attribute_name = L.UE_SAMPLE_OFFSET_PROP
        receiver = g.vector('ADD', receiver, offset_node.outputs['Vector'], 'Receiver relative to primary light')
        world_delta = g.transform(receiver, 'VECTOR', 'OBJECT', 'WORLD', 'World distance from light center')
        distance = g.vector('LENGTH', world_delta, label='Center distance')
        kind = g.attr(L.UE_LIGHT_KIND_PROP, 'Light type: point 0, spot 1, rect 2')
        area = g.math('COMPARE', kind, 2, 'Is rect light')
        spot = g.math('COMPARE', kind, 1, 'Is spot light')
        radial = g.node('ShaderNodeGroup', 'UE radial falloff')
        radial.node_tree = radial_group()
        for name, value in {
            'Distance': distance, 'Source Distance': sample_distance, 'Ray Distance': ray, 'Area Light': area,
            'Radius': g.attr(L.UE_ATTENUATION_RADIUS_PROP, 'Attenuation radius'),
            'Inverse Squared': g.math('MAXIMUM', area, g.attr(L.UE_INVERSE_SQUARED_FALLOFF_PROP, 'Inverse squared')),
            'Exponent': g.attr(L.UE_LIGHT_FALLOFF_EXPONENT_PROP, 'Falloff exponent'),
            'Bias Squared': g.attr(L.UE_DISTANCE_BIAS_PROP, 'UE distance bias squared'),
        }.items():
            g.connect(value, radial.inputs[name])
        cone = g.node('ShaderNodeGroup', 'Spot cone mask')
        cone.node_tree = cone_group()
        # UE's cone is angular in world space, unaffected by nonuniform scale.
        axis_scale = g.node('ShaderNodeCombineXYZ', 'Light axis scales')
        for axis, unit in enumerate(((1, 0, 0), (0, 1, 0), (0, 0, 1))):
            basis = g.transform(unit, 'VECTOR', 'OBJECT', 'WORLD', 'World light axis')
            g.connect(g.vector('LENGTH', basis), axis_scale.inputs[axis])
        cone_receiver = g.vector('MULTIPLY', receiver, axis_scale.outputs[0], 'Receiver along unscaled light axes')
        g.connect(cone_receiver, cone.inputs['Receiver'])
        g.connect(g.attr(L.UE_INNER_CONE_PROP, 'Inner half angle'), cone.inputs['Inner Half Angle'])
        g.connect(g.attr(L.UE_OUTER_CONE_PROP, 'Outer half angle'), cone.inputs['Outer Half Angle'])
        rect = g.node('ShaderNodeGroup', 'Rect barn door mask')
        rect.node_tree = rect_group()
        for name, value in {
            'Receiver': receiver, 'Emitter': emitter,
            'Width': g.attr(L.UE_SOURCE_WIDTH_PROP, 'Source width'),
            'Height': g.attr(L.UE_SOURCE_HEIGHT_PROP, 'Source height'),
            'Barn Angle': g.attr(L.UE_BARN_ANGLE_PROP, 'Barn door angle'),
            'Barn Length': g.attr(L.UE_BARN_LENGTH_PROP, 'Barn door length'),
        }.items():
            g.connect(value, rect.inputs[name])
        shape = g.math('MULTIPLY', g.mix(1, cone.outputs['Mask'], spot, 'Spot selection'),
                       g.mix(1, rect.outputs['Mask'], area, 'Rect selection'))
        strength = g.math('MULTIPLY', radial.outputs['Strength'], shape)
        disabled = g.clamp(g.attr(L.UE_DISABLE_CUSTOM_ATTENUATION_PROP, 'Use native attenuation'))
        strength = g.mix(strength, 1, disabled, 'Native attenuation bypass')
        # Missing sample properties on older lights must preserve full energy.
        count = g.math('MAXIMUM', g.attr(L.UE_SAMPLE_COUNT_PROP, 'Tube sample count'), 1)
        g.connect(g.math('DIVIDE', strength, count, 'Emitter energy share'), o['Strength'])
    return _group(L.UE_LIGHT_ATTENUATION_GROUP_NAME, [], [('Strength', F)], build)
