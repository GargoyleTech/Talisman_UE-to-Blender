"""Insert the captured FF7 Rebirth Phantom colour/alpha function into a material.

Run this file in Blender's Text Editor with the destination material active.
Existing shader links are preserved. Connect Color to an Emission shader (or a
shader's emission colour), and Alpha separately if the destination uses alpha.

Source: C:/temp/GiNattak/rd_graphics_shaders/
09147_ps736266_Shader_8b8409ac_MainPS__DXBC_DXIL.txt, EID 9187, BodyA.
The default group has 27 nodes, including Group Input and Group Output.
The optional general two-map occlusion path adds 8 nodes.

Noise is an INPUT, defaulting to the blue-noise mean, 0.5. Supply the original
volume sample upstream to reproduce its grain. Scene fog, engine pre-exposure,
and primitive visibility discard are renderer operations, outside this group.
Blender shader colour sockets have no independently writable alpha component;
Color + Alpha together are the RGBA result. Alpha is depth fade, NOT colour luma.
See ff7r_phantom.md alongside this file for the equations and input contract.
"""

from array import array
from pathlib import Path

import bpy


# Optional image datablocks or absolute filenames. Empty means sockets only.
# Scalar textures are sampled from RED, never from Blender's colour-to-value
# luminance conversion. Normal is BC5 RG; its blue channel is reconstructed.
IMAGES = {
    # "Normal": r"C:\path\NP0132_00_BodyA_N.png",
    # "Roughness": r"C:\path\NP0132_00_BodyA_Mg.png",
    # "Wide Occlusion": r"C:\path\NP0132_00_BodyA_O.png",
    # "Tone Gradient": r"C:\path\Common_EmissiveTone_Ancient_EH.exr",
}
UV_MAP = ""                       # Empty = active render UV map.
WIDE_UV_MAP = "Coordinate1"       # Set to the imported mesh's UV1 name.
DIRECTX_NORMAL = True
INCLUDE_LOCAL_OCCLUSION = False   # BodyA's local Occlusion is exactly white.

SOURCE_HASH = "ac09848bb2fd60b7d752433cd0496724"
GROUP_NAME = "FF7R Phantom — BodyA"


def _node(tree, kind, name, xy, **properties):
    node = tree.nodes.new(kind)
    node.name = node.label = name
    node.location = xy
    node.width = 160
    for key, value in properties.items():
        setattr(node, key, value)
    return node


def _wire(tree, source, target):
    if isinstance(source, bpy.types.NodeSocket):
        tree.links.new(source, target)
    else:
        target.default_value = source


def _math(tree, operation, name, xy, *values, clamp=False):
    node = _node(tree, "ShaderNodeMath", name, xy,
                 operation=operation, use_clamp=clamp, hide=True)
    for socket, value in zip(node.inputs, values):
        _wire(tree, value, socket)
    return node.outputs[0]


def _vector(tree, operation, name, xy, *values):
    node = _node(tree, "ShaderNodeVectorMath", name, xy,
                 operation=operation, hide=True)
    for socket, value in zip(node.inputs, values):
        _wire(tree, value, socket)
    return node.outputs['Value' if operation == 'DOT_PRODUCT' else 'Vector']


def _socket(tree, name, kind, default=None, description="", limits=None,
            direction='INPUT'):
    socket = tree.interface.new_socket(name=name, in_out=direction,
                                       socket_type=kind)
    socket.description = description
    if default is not None:
        socket.default_value = default
    if limits:
        socket.min_value, socket.max_value = limits
    return socket


def build_phantom_group(include_local_occlusion=False):
    """Build once; reuse existing groups without overwriting artist edits."""
    name = GROUP_NAME + (" + local occlusion" if include_local_occlusion else "")
    existing = bpy.data.node_groups.get(name)
    if (existing and existing.get('phantom_source') == SOURCE_HASH
            and existing.get('local_occlusion') == include_local_occlusion):
        return existing
    tree = bpy.data.node_groups.new(name, 'ShaderNodeTree')
    tree['source_event'] = "GiNattak EID 9187; archive 23354_3F1D1C73"
    tree.description = "Captured Phantom camera response; Color + Alpha = RGBA"
    normal = _socket(tree, 'Normal', 'NodeSocketVector', (0, 0, 1),
                     "Unit world-space mapped normal. The insertion script connects surface normal.")
    normal.hide_value = True
    _socket(tree, 'Roughness', 'NodeSocketFloat', 0.5,
            "Material_Texture2D_3 RED at UV0; used directly, without PBR remapping.", (0, 1))
    _socket(tree, 'Wide Occlusion', 'NodeSocketFloat', 1.0,
            "Material_Texture2D_11 RED at UV1. BodyA's local occlusion is white.", (0, 1))
    if include_local_occlusion:
        _socket(tree, 'Occlusion', 'NodeSocketFloat', 1.0,
                "Material_Texture2D_4 RED at UV0; exact general two-map blend.", (0, 1))
    _socket(tree, 'Blue Noise', 'NodeSocketFloat', 0.5,
            "RED of original position-indexed View_BlueNoiseVolumeTexture; 0.5 = mean.", (0, 1))
    _socket(tree, 'Tone 0', 'NodeSocketColor', (0, 0, 0, 1),
            "Linear RGB of ToneGradient texel (0, 0), not the image's filtered edge.")
    _socket(tree, 'Tone 1', 'NodeSocketColor', (1, 1, 1, 1),
            "Linear HDR RGB of ToneGradient texel (1, 0).")
    _socket(tree, 'External Emissive', 'NodeSocketColor', (1, 1, 1, 1),
            "Material_VectorExpressions[19].rgb, with any engine exposure compensation applied.")
    _socket(tree, 'Depth Gap', 'NodeSocketFloat', 1000000.0,
            "Linear scene depth minus surface view depth, in Blender distance units. Large = no fade.")
    _socket(tree, 'Fade Distance', 'NodeSocketFloat', 0.5,
            "Depth-fade span in the SAME units as Depth Gap. Default 0.5 m = game's 50 cm.",
            (0.000001, 1000000.0))
    _socket(tree, 'Color', 'NodeSocketColor', direction='OUTPUT',
            description="Linear HDR RGB, before scene fog and Blender colour management.")
    _socket(tree, 'Alpha', 'NodeSocketFloat', direction='OUTPUT',
            description="Smooth depth fade. Independent of the tone colour's luminance.")

    group_in = _node(tree, 'NodeGroupInput', 'Inputs', (-1200, 180))
    group_in.width = 210
    group_out = _node(tree, 'NodeGroupOutput', 'Color + Alpha', (1740, 180))
    p = group_in.outputs

    # Camera Data points CAMERA -> SURFACE. Transform its normalized vector to
    # world space and negate the dot. Unlike Geometry Incoming, this remains
    # tied to the actual camera when Cycles evaluates secondary rays.
    camera = _node(tree, 'ShaderNodeCameraData', 'Actual camera', (-1200, 540))
    to_world = _node(tree, 'ShaderNodeVectorTransform', 'View vector to world',
                     (-1000, 540), vector_type='VECTOR', convert_from='CAMERA',
                     convert_to='WORLD', hide=True)
    tree.links.new(camera.outputs['View Vector'], to_world.inputs[0])
    dot = _vector(tree, 'DOT_PRODUCT', 'N dot camera-to-surface', (-800, 540),
                  p['Normal'], to_world.outputs[0])
    d = _math(tree, 'MULTIPLY', 'd = saturate(N dot V)', (-600, 540), dot, -1.0,
              clamp=True)
    inv_d = _math(tree, 'SUBTRACT', '1 - d', (-400, 620), 1.0, d)
    rim = _math(tree, 'POWER', '(1 - d)^5', (-200, 620), inv_d, 5.0)
    front = _math(tree, 'POWER', 'd^5', (-200, 540), d, 5.0)
    symmetric = _math(tree, 'ADD', 'd^5 + (1 - d)^5', (0, 580), rim, front)
    separate = _node(tree, 'ShaderNodeSeparateXYZ', 'World normal Z',
                     (-800, 380), hide=True)
    tree.links.new(p['Normal'], separate.inputs[0])
    up = _math(tree, 'MULTIPLY_ADD', '0.5 * N.z + 0.5', (-600, 380),
               separate.outputs['Z'], 0.5, 0.5)

    o = p['Wide Occlusion']
    if include_local_occlusion:
        # m + (a*b - m) * [1 - (1 + a*b - m)^5]^5, exactly as DXIL.
        product = _math(tree, 'MULTIPLY', 'a * b', (-1000, -460), p['Occlusion'], o)
        minimum = _math(tree, 'MINIMUM', 'm = min(a, b)', (-1000, -540), p['Occlusion'], o)
        delta = _math(tree, 'SUBTRACT', 'a*b - m', (-800, -460), product, minimum)
        k = _math(tree, 'ADD', '1 + a*b - m', (-600, -460), 1.0, delta)
        k5 = _math(tree, 'POWER', '(1 + a*b - m)^5', (-400, -460), k, 5.0)
        t = _math(tree, 'SUBTRACT', '1 - k^5', (-200, -460), 1.0, k5)
        t5 = _math(tree, 'POWER', '(1 - k^5)^5', (0, -460), t, 5.0)
        o = _math(tree, 'MULTIPLY_ADD', 'Combined occlusion', (200, -460), t5, delta, minimum)

    exponent_log2 = _math(tree, 'MULTIPLY_ADD', '-1 - 16 * roughness', (-600, 120),
                         p['Roughness'], -16.0, -1.0)
    exponent = _math(tree, 'POWER', 'e = 2^(-1 - 16r)', (-400, 120), 2.0, exponent_log2)
    base = _math(tree, 'ADD', 'occlusion + d', (-200, 180), o, d)
    power = _math(tree, 'POWER', '(occlusion + d)^e', (0, 180), base, exponent)
    offset = _math(tree, 'SUBTRACT', 'occlusion - 1', (-200, 20), o, 1.0)
    mask = _math(tree, 'ADD', 'saturate(o - 1 + (o + d)^e)', (200, 140),
                 power, offset, clamp=True)
    factor = _math(tree, 'MULTIPLY', 'Angle * world-up', (200, 500), symmetric, up)
    factor = _math(tree, 'MULTIPLY', 'Angle * up * blue noise', (400, 500),
                   factor, p['Blue Noise'])
    factor = _math(tree, 'MULTIPLY', 'Tone factor (saturated)', (600, 340),
                   factor, mask, clamp=True)
    mix = _node(tree, 'ShaderNodeMix', 'Two texels, linear HDR mix', (800, 340),
                data_type='RGBA', blend_type='MIX', clamp_factor=True,
                clamp_result=False, hide=True)
    tree.links.new(factor, mix.inputs[0])
    tree.links.new(p['Tone 0'], mix.inputs[6])
    tree.links.new(p['Tone 1'], mix.inputs[7])
    tinted = _vector(tree, 'MULTIPLY', 'External emissive tint', (1000, 340),
                     mix.outputs[2], p['External Emissive'])
    positive = _vector(tree, 'MAXIMUM', 'max(0, colour), preserve HDR', (1200, 340),
                       tinted, (0.0, 0.0, 0.0))

    fade = _node(tree, 'ShaderNodeMapRange', 'Alpha = smooth depth fade',
                 (800, -40), interpolation_type='SMOOTHSTEP', clamp=True)
    tree.links.new(p['Depth Gap'], fade.inputs['Value'])
    tree.links.new(p['Fade Distance'], fade.inputs['From Max'])
    fade.inputs['From Min'].default_value = 0.0
    fade.inputs['To Min'].default_value = 0.0
    fade.inputs['To Max'].default_value = 1.0
    fade8 = _math(tree, 'POWER', 'RGB depth fade = alpha^8', (1200, -40),
                  fade.outputs['Result'], 8.0)
    scaled = _node(tree, 'ShaderNodeVectorMath', 'Final linear RGB', (1480, 240),
                   operation='SCALE', hide=True)
    tree.links.new(positive, scaled.inputs[0])
    tree.links.new(fade8, scaled.inputs['Scale'])
    tree.links.new(scaled.outputs['Vector'], group_out.inputs['Color'])
    tree.links.new(fade.outputs['Result'], group_out.inputs['Alpha'])
    tree['phantom_source'] = SOURCE_HASH
    tree['local_occlusion'] = include_local_occlusion
    tree['node_count'] = len(tree.nodes)
    return tree


def _image(value, data=False):
    image = (value if isinstance(value, bpy.types.Image)
             else bpy.data.images.load(str(value), check_existing=True))
    if data and not image.colorspace_settings.is_data:
        # Do not reinterpret another material's shared colour image.
        pixels = None
        if image.source == 'GENERATED' or image.is_dirty:
            pixels = array('f', [0.0]) * len(image.pixels)
            image.pixels.foreach_get(pixels)
        image = image.copy()
        image.colorspace_settings.name = 'Non-Color'
        if pixels is not None:
            image.pixels.foreach_set(pixels)
            image.update()
    return image


def set_tone_gradient(node, image):
    """Read the original two unfiltered linear texels; adds ZERO shader nodes.

    A Blender shader group cannot have an Image datablock input socket. This
    sets its two colour parameters from an image, so re-run after image edits.
    Supply a correctly decoded 2x1 linear HDR/EXR image, not an sRGB screenshot.
    """
    image = _image(image)
    if tuple(image.size) != (2, 1):
        raise ValueError('Tone Gradient must be the original 2x1 image.')
    pixels = image.pixels[:8]
    # The reference CUE4Parse export emits scanline RLE even at width 2.
    # Radiance readers expect flat RGBE below width 8 and otherwise load these
    # particular files as denormals. Decode that narrowly identified export.
    path = Path(bpy.path.abspath(image.filepath)) if image.filepath else None
    if path and path.suffix.lower() == '.hdr' and path.is_file():
        data = path.read_bytes()
        marker = b'-Y 1 +X 2\n'
        if b'# Written by CUE4Parse' in data and marker in data:
            body = data.split(marker, 1)[1]
            if body[:4] == bytes((2, 2, 0, 2)):
                channels, offset = [], 4
                for _ in range(4):
                    values = []
                    while len(values) < 2:
                        count = body[offset]
                        offset += 1
                        if count > 128:
                            values.extend([body[offset]] * (count - 128))
                            offset += 1
                        elif count:
                            values.extend(body[offset:offset + count])
                            offset += count
                        else:
                            raise ValueError('Invalid CUE4Parse tone-gradient RLE.')
                    if len(values) != 2:
                        raise ValueError('Invalid CUE4Parse tone-gradient scanline length.')
                    channels.append(values)
                pixels = []
                for i in range(2):
                    scale = 2.0 ** (channels[3][i] - 136) if channels[3][i] else 0.0
                    pixels.extend([channels[c][i] * scale for c in range(3)] + [1.0])
    node.inputs['Tone 0'].default_value = (*pixels[0:3], 1.0)
    node.inputs['Tone 1'].default_value = (*pixels[4:7], 1.0)


def _bc5_world_normal(tree, color, uv_map, directx, origin):
    """Decode RG, reconstruct positive Z, normalize via Blender's tangent map."""
    x, y = origin
    xy = _vector(tree, 'MULTIPLY_ADD', 'BC5 signed XY', (x, y), color,
                 (2.0, 2.0, 0.0), (-1.0, -1.0, 0.0))
    length2 = _vector(tree, 'DOT_PRODUCT', 'BC5 x*x + y*y', (x + 180, y), xy, xy)
    z2 = _math(tree, 'SUBTRACT', 'BC5 max(0, 1 - x*x - y*y)', (x + 360, y),
               1.0, length2, clamp=True)
    z = _math(tree, 'SQRT', 'BC5 positive Z', (x + 540, y), z2)
    z_vector = _node(tree, 'ShaderNodeCombineXYZ', 'BC5 Z vector', (x + 720, y), hide=True)
    tree.links.new(z, z_vector.inputs['Z'])
    normal = _vector(tree, 'ADD', 'BC5 XYZ', (x + 900, y), xy, z_vector.outputs[0])
    # Fuse DirectX's Y inversion into re-encoding: no extra flip node, including
    # on Blender versions that predate the Normal Map convention property.
    encode = _vector(tree, 'MULTIPLY_ADD', 'BC5 to Blender tangent RGB',
                     (x + 1080, y), normal,
                     (0.5, -0.5 if directx else 0.5, 0.5), (0.5, 0.5, 0.5))
    mapped = _node(tree, 'ShaderNodeNormalMap', 'BC5 world normal',
                   (x + 1260, y), space='TANGENT', uv_map=uv_map)
    if hasattr(mapped, 'convention'):
        mapped.convention = 'OPENGL'  # Conversion already performed exactly once.
    mapped.inputs['Strength'].default_value = 1.0
    tree.links.new(encode, mapped.inputs['Color'])
    return mapped.outputs['Normal']


def connect_images(node, images, uv_map=UV_MAP, wide_uv_map=WIDE_UV_MAP,
                   directx_normal=DIRECTX_NORMAL):
    """Optionally create only the samplers requested; leave the shader untouched."""
    allowed = {'Normal', 'Roughness', 'Occlusion', 'Wide Occlusion', 'Tone Gradient'}
    unknown = set(images) - allowed
    if unknown:
        raise ValueError('Unknown Phantom image roles: ' + ', '.join(sorted(unknown)))
    if 'Occlusion' in images and 'Occlusion' not in node.inputs:
        raise ValueError('Build with include_local_occlusion=True for a local Occlusion image.')
    tree = node.id_data
    x, y = node.location
    uv_nodes = {}
    for index, (role, value) in enumerate(images.items()):
        if value is None:
            continue
        if role == 'Tone Gradient':
            set_tone_gradient(node, value)
            continue
        uv_name = wide_uv_map if role == 'Wide Occlusion' else uv_map
        if uv_name not in uv_nodes:
            uv_nodes[uv_name] = _node(tree, 'ShaderNodeUVMap',
                                      'Phantom UV: ' + (uv_name or 'active'),
                                      (x - 1880, y - 300 * len(uv_nodes)), uv_map=uv_name)
        image_node = _node(tree, 'ShaderNodeTexImage', 'Phantom ' + role,
                           (x - 1640, y - index * 320), image=_image(value, data=True),
                           interpolation='Linear', extension='REPEAT')
        tree.links.new(uv_nodes[uv_name].outputs['UV'], image_node.inputs['Vector'])
        if role == 'Normal':
            output = _bc5_world_normal(tree, image_node.outputs['Color'], uv_map,
                                       directx_normal, (x - 1400, y + 250))
        else:
            red = _node(tree, 'ShaderNodeSeparateColor', role + ' RED',
                        (x - 1350, y - index * 320), mode='RGB', hide=True)
            tree.links.new(image_node.outputs['Color'], red.inputs['Color'])
            output = red.outputs['Red']
        tree.links.new(output, node.inputs[role])


def insert_phantom(images=None, include_local_occlusion=False, tree=None):
    """Insert one group into the current shader graph, including an edited subgroup."""
    if tree is None:
        space = bpy.context.space_data
        if (space and space.type == 'NODE_EDITOR' and space.tree_type == 'ShaderNodeTree'
                and isinstance(space.id, bpy.types.Material)):
            tree = space.edit_tree
        else:
            obj = bpy.context.object
            material = obj.active_material if obj else None
            if material is None:
                raise RuntimeError('Select an object with an active material, then run the script.')
            if not material.use_nodes:
                material.use_nodes = True
            tree = material.node_tree
    if tree is None or tree.bl_idname != 'ShaderNodeTree' or not tree.is_editable:
        raise RuntimeError('The current material graph must be an editable shader node tree.')
    group = build_phantom_group(include_local_occlusion)
    if tree == group:
        raise RuntimeError('Leave the Phantom group before inserting another instance of it.')
    right = max((n.location.x + n.width for n in tree.nodes), default=0)
    top = max((n.location.y for n in tree.nodes), default=0)
    # With optional samplers, put the new cluster beyond existing nodes too.
    node = _node(tree, 'ShaderNodeGroup', 'FF7R Phantom',
                  (right + (2050 if images else 100), top), node_tree=group)
    node.width = 285
    # Convert the source's default 50 centimetres into this scene's units.
    scale_length = bpy.context.scene.unit_settings.scale_length
    node.inputs['Fade Distance'].default_value = 0.5 / max(scale_length, 0.000001)
    if not (images and images.get('Normal') is not None):
        geometry = _node(tree, 'ShaderNodeNewGeometry', 'Phantom surface normal',
                         (node.location.x - 200, top - 100), hide=True)
        tree.links.new(geometry.outputs['Normal'], node.inputs['Normal'])
    if images:
        connect_images(node, images)
    for other in tree.nodes:
        other.select = other == node
    tree.nodes.active = node
    print(f'Inserted {node.name}: {len(group.nodes)} internal nodes; Color + Alpha outputs.')
    return node


if __name__ == '__main__':
    insert_phantom(images=IMAGES, include_local_occlusion=INCLUDE_LOCAL_OCCLUSION)
