"""Remake preserves unused textures without duplicating connected images."""
from pathlib import Path
import sys

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from addon.games.remake.materials import build_material
from addon.formats.unreal_package.mesh_import import _static_mesh_material


class Images:
    def __init__(self):
        self.images = {}

    def __call__(self, path):
        if path.endswith('Missing'):
            return None
        key = path.rsplit('.', 1)[0].casefold()
        if key not in self.images:
            self.images[key] = bpy.data.images.new(key, width=2, height=2)
        return self.images[key]


# Mesh import creates placeholders before reconstructing their shaders. Reuse
# those IDs (including renamed placeholders) instead of creating .001 copies.
loader = Images()
loader.texture_namespace = "remake-naming-fixture"
for index in range(2):
    name = f"RemakeNaming{index}"
    path = f"/Game/{name}.{name}"
    placeholder = _static_mesh_material(name, path, loader.texture_namespace, loader)
    if index:
        placeholder.name = "RenamedRemakePlaceholder"
    original_name = placeholder.name
    count = len(bpy.data.materials)
    material = build_material(name, path, {}, loader)
    assert material == placeholder
    assert material.name == original_name
    assert len(bpy.data.materials) == count
    assert build_material(name, path, {}, loader) == material

other_loader = Images()
other_loader.texture_namespace = "other-remake-source"
assert build_material(name, path, {}, other_loader) != material


def build(name, parameters, streaming=None):
    loader = Images()
    data = {'properties': [{'name': 'TextureParameterValues', 'value': [
        {'ParameterName': key, 'ParameterValue': {'ObjectPath': value}}
        for key, value in parameters
    ]}]}
    if streaming is not None:
        data['properties'].append({'name': 'TextureStreamingData', 'value': streaming})
    material = build_material(name, '/Game/' + name, data, loader)
    nodes = [node for node in material.node_tree.nodes if node.type == 'TEX_IMAGE']
    return material, nodes, loader


material, nodes, loader = build('Inventory', [
    ('0:0:Color', '/Game/Color.Color'),
    ('0:1:MetallicRoughnessVariant', '/Game/MRV.MRV'),
    ('0:2:Coverage', '/Game/Alpha.Alpha'),
    ('0:6:Opacity', '/Game/Alpha.Alpha'),
    ('0:7:UnusedColor', '/Game/Color.0'),
    ('0:8:Detail', '/Game/Detail.Detail'),
    ('0:9:UnusedDetail', '/Game/Detail.0'),
    ('0:10:MissingDetail', '/Game/Missing'),
])
assert len(nodes) == 5, [node.label for node in nodes]
bsdf = next(node for node in material.node_tree.nodes if node.type == 'BSDF_PRINCIPLED')
assert bsdf.inputs['Alpha'].links[0].from_node.label == 'Opacity (Alpha)'
assert len([node for node in nodes if node.image == loader('/Game/Alpha.0')]) == 1
detail = next(node for node in nodes if node.image == loader('/Game/Detail.0'))
assert detail.label == '0:8:Detail'
assert not any(socket.is_linked for socket in detail.outputs)
missing = next(node for node in nodes if node.image is None)
assert missing['ue_texture_unavailable'] and missing['ue_texture_path'] == '/Game/Missing'
assert loader('/Game/Color.0').colorspace_settings.name == 'sRGB'

# Distinct layer parameters survive role normalization, but inherited values
# replaced by the same parameter's instance override do not become orphans.
material, nodes, loader = build('Layers', [
    ('0:0:Color', '/Game/Inherited.Inherited'),
    ('0:1:Color', '/Game/OtherLayer.OtherLayer'),
    ('0:0:Color', '/Game/Override.Override'),
    ('0:2:Coverage', '/Game/Coverage.Coverage'),
    ('0:3:Opacity', '/Game/Opacity.Opacity'),
])
assert len(nodes) == 4, [node.label for node in nodes]
assert all(node.image != loader('/Game/Inherited.0') for node in nodes)
bsdf = next(node for node in material.node_tree.nodes if node.type == 'BSDF_PRINCIPLED')
assert bsdf.inputs['Base Color'].links[0].from_node.image == loader('/Game/Override.0')
coverage = next(node for node in nodes if node.image == loader('/Game/Coverage.0'))
assert not any(socket.is_linked for socket in coverage.outputs)
print('REMAKE_MATERIAL_INVENTORY_OK', flush=True)

material, nodes, loader = build('StreamingUVs', [
    ('0:0:Color', '/Game/T_FacilityInMachine_02_5thMako_C.0'),
    ('0:1:MetallicRoughnessVariant', '/Game/T_FacilityInMachine_02_5thMako_MRV.0'),
    ('0:2:Normal', '/Game/T_FacilityInMachine_02_5thMako_N.0'),
    ('0:3:Occlusion', '/Game/T_FacilityInMachine_02_5thMako_O.0'),
    ('0:4:Unused', '/Game/Unused.0'),
    ('0:5:Unspecified', '/Game/Unspecified.0'),
    ('0:6:Invalid', '/Game/Invalid.0'),
], [
    {'StructType': {'TextureName': 'T_FacilityInMachine_02_5thMako_' + suffix,
                    'UVChannelIndex': channel, 'SamplingScale': 1.0}}
    for suffix, channel in [('C', 0), ('MRV', 0), ('N', 0), ('O', 1)]
] + [
    {'TextureName': 'Unused', 'UVChannelIndex': 1, 'SamplingScale': 3.5},
    {'TextureName': 'Invalid', 'UVChannelIndex': -1},
    {'TextureName': 'Invalid', 'UVChannelIndex': 'bad'},
])
uv_nodes = [node for node in material.node_tree.nodes if node.type == 'UVMAP']
assert len(uv_nodes) == 2
for node in nodes:
    path = node['ue_texture_path']
    if 'Unspecified' in path or 'Invalid' in path:
        assert not node.inputs['Vector'].is_linked
        continue
    expected = 1 if '_O.' in path or '/Unused.' in path else 0
    uv_link = node.inputs['Vector'].links[0]
    assert uv_link.from_node.uv_map == f'Coordinate{expected}', (node.label, expected)
    assert node['ue_uv_channel_index'] == expected
assert not any(node.type == 'MAPPING' for node in material.node_tree.nodes)
assert len(nodes) == 7
print('REMAKE_TEXTURE_STREAMING_UVS_OK', flush=True)

renderer = 'End/Content/GameContents/Renderer/Texture/'
material, nodes, loader = build('ConstantsAndEmission', [
    ('0:0:Color', renderer + '767676FF_sRGB.0'),
    ('0:1:MetallicRoughnessVariant', renderer + '008000FF_HDR.0'),
    ('0:2:Normal', renderer + '8080FFFF_BC5.0'),
    ('0:3:Opacity', renderer + 'FFFFFFFF_BC4.0'),
    ('0:4:Emissive', '/Game/T_Stationary_Emissive.0'),
    ('0:5:UnusedColor', renderer + '767676FF_sRGB.767676FF_sRGB'),
    ('0:6:UnusedConstant', renderer + '11223344_HDR.0'),
    ('0:7:UnusedConstantDuplicate', renderer + '11223344_HDR.11223344_HDR'),
])
bsdf = next(node for node in material.node_tree.nodes if node.type == 'BSDF_PRINCIPLED')
constants = [node for node in material.node_tree.nodes if node.type == 'RGB']
assert len(constants) == 4, [node.label for node in constants]
assert len(nodes) == 1 and nodes[0].label == 'Emissive'
assert all('/Renderer/' not in path for path in loader.images)
color = bsdf.inputs['Base Color'].links[0].from_node
assert color.type == 'RGB'
expected_gray = ((118 / 255 + 0.055) / 1.055) ** 2.4
assert all(abs(value - expected_gray) < 1e-6 for value in color.outputs['Color'].default_value[:3])
assert color.outputs['Color'].default_value[3] == 1
alpha = bsdf.inputs['Alpha'].links[0].from_node
assert alpha.type == 'VALUE' and alpha.outputs[0].default_value == 1.0
assert bsdf.inputs['Normal'].is_linked
assert bsdf.inputs['Metallic'].is_linked and bsdf.inputs['Roughness'].is_linked
emission_mask = bsdf.inputs['Emission Color'].links[0].from_node
assert emission_mask.blend_type == 'MULTIPLY'
assert emission_mask.inputs['Fac'].default_value == 1
assert emission_mask.inputs[1].links[0].from_node == nodes[0]
assert emission_mask.inputs[2].links[0].from_socket.name == 'Blue'
assert emission_mask.inputs[2].links[0].from_node == bsdf.inputs['Metallic'].links[0].from_node
strength = bsdf.inputs['Emission Strength']
assert strength.default_value == 1
assert strength.links[0].from_node.type == 'LIGHT_PATH'
assert strength.links[0].from_socket.name == 'Is Camera Ray'
unused_constant = next(node for node in constants if node.name == '0:6:UnusedConstant')
assert not unused_constant.outputs['Color'].is_linked
assert all(abs(value - byte / 255) < 1e-6 for value, byte in zip(
    unused_constant.outputs['Color'].default_value, (0x11, 0x22, 0x33, 0x44)))

for name, parameters, expected in [
    ('NoEmission', [('Color', '/Game/Color.0')], None),
    ('LDREmission', [('LDREmissive', '/Game/LDR.0')], 'LDR Emissive'),
    ('PreferredEmission', [('LDREmissive', '/Game/LDR.0'), ('Emissive', '/Game/Emission.0')], 'Emissive'),
    ('ConstantEmission', [('Emissive', renderer + '767676FF_sRGB.0')], 'Emissive [UE color constant]'),
    ('MaskedEmission', [('Emissive', '/Game/Emission.0'), ('MetallicRoughnessVariant', '/Game/MRV.0')], 'Emissive'),
    ('MaskedLDREmission', [('LDREmissive', '/Game/LDR.0'), ('MetallicRoughnessVariant', '/Game/MRV.0')], 'LDR Emissive'),
]:
    material, nodes, loader = build(name, parameters)
    bsdf = next(node for node in material.node_tree.nodes if node.type == 'BSDF_PRINCIPLED')
    if expected is None:
        assert bsdf.inputs['Emission Strength'].default_value == 0
        assert not bsdf.inputs['Emission Strength'].is_linked
    else:
        emission_source = bsdf.inputs['Emission Color'].links[0].from_node
        if name.startswith('Masked'):
            assert emission_source.blend_type == 'MULTIPLY'
            assert emission_source.inputs['Fac'].default_value == 1
            blue_link = emission_source.inputs[2].links[0]
            assert blue_link.from_socket.name == 'Blue'
            assert blue_link.from_node.inputs['Color'].links[0].from_node.label == 'Metallic / Roughness / Variant'
            emission_source = emission_source.inputs[1].links[0].from_node
        assert emission_source.label == expected
        assert bsdf.inputs['Emission Strength'].links[0].from_socket.name == 'Is Camera Ray'
print('REMAKE_CONSTANTS_AND_CAMERA_EMISSION_OK', flush=True)

# M_Light_cmn_NoLit_1stAvenue uses unsuffixed linear renderer constants.
material, nodes, loader = build('BareRendererConstants', [
    ('0:0:Color', renderer + '767676FF_sRGB.0'),
    ('0:2:Metallic/Roughness/Variant', renderer + '00FFFFFF.00FFFFFF'),
    ('0:3:Normal', renderer + '8080FF00.0'),
    ('0:4:Emissive', '/Game/T_Stationary_Emissive.0'),
    ('0:5:UnusedMRV', renderer + '00FFFFFF.0'),
    ('0:6:NotRendererConstant', '/Game/Environment/12345678.0'),
])
bsdf = next(node for node in material.node_tree.nodes if node.type == 'BSDF_PRINCIPLED')
assert bsdf.inputs['Metallic'].is_linked and bsdf.inputs['Roughness'].is_linked
mrv = bsdf.inputs['Metallic'].links[0].from_node.inputs['Color'].links[0].from_node
assert mrv.type == 'RGB'
assert tuple(mrv.outputs['Color'].default_value) == (0, 1, 1, 1)
assert bsdf.inputs['Normal'].is_linked
normal = next(node for node in material.node_tree.nodes if node.name == 'Normal')
assert normal.type == 'RGB'
assert all(abs(value - byte / 255) < 1e-6 for value, byte in zip(
    normal.outputs['Color'].default_value, (128, 128, 255, 0)))
assert sum(node.type == 'RGB' for node in material.node_tree.nodes) == 3
assert all('/Renderer/' not in path for path in loader.images)
assert len(nodes) == 2
print('REMAKE_BARE_RENDERER_CONSTANTS_OK', flush=True)

material, nodes, loader = build('ScalarAO', [
    ('Color', '/Game/Albedo.0'),
    ('Occlusion', renderer + 'FF000000_BC4.0'),
    ('Opacity', renderer + '80000000_BC4.0'),
    ('UnusedMask', renderer + 'FF000000_BC4.FF000000_BC4'),
])
bsdf = next(node for node in material.node_tree.nodes if node.type == 'BSDF_PRINCIPLED')
multiply = bsdf.inputs['Base Color'].links[0].from_node
occlusion = multiply.inputs[2].links[0].from_node
assert occlusion.type == 'VALUE' and occlusion.outputs[0].default_value == 1.0
alpha = bsdf.inputs['Alpha'].links[0].from_node
assert alpha.type == 'VALUE' and abs(alpha.outputs[0].default_value - 128 / 255) < 1e-6
assert sum(node.type == 'VALUE' for node in material.node_tree.nodes) == 2
assert not any(node.type == 'RGB' for node in material.node_tree.nodes)
assert all('/Renderer/' not in path for path in loader.images)
print('REMAKE_BC4_SCALAR_CONSTANTS_OK', flush=True)
