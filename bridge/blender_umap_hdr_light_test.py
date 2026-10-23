"""Blender regression for sparse package lists and HDR fixture lights."""
import json
from pathlib import Path
import sys
import math
import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from addon.games.rebirth.materials import rmi_surface
from addon.formats.ue_map import lights, map_import, light_photometry

dump = Path(r'O:\Games\Rebirth Tools\FModel\Output\Exports\End\Content\Level\Game\Field\2350-GOLDS\Layout\2350-GOLDS_SQGhost_Light.json')
data = json.loads(dump.read_text(encoding='utf-8'))
# Retain original export offsets, as a full FModel list does.
fixture = [entry if 'PersistentLevel.Light_17B12' in
           entry.get('Outer', {}).get('ObjectName', '') else {} for entry in data]

for sparse in (False, True):
    for obj in list(bpy.data.objects):
        if obj.name.startswith('Light_17B12'):
            bpy.data.objects.remove(obj, do_unlink=True)
    entries = fixture
    if sparse:
        entries = [json.loads(json.dumps(e)) for e in fixture if e]
        # Gargoyle ownership references use full object paths, not list offsets.
        for entry in entries:
            outer = entry['Outer']
            outer['ObjectPath'] = outer['ObjectName'].split("'")[1]
            parent = entry.get('Properties', {}).get('AttachParent')
            if parent:
                parent['ObjectPath'] = parent['ObjectName'].split("'")[1]
    map_import.import_map_entries(entries, 'hdr_test.json', 1.0, 1.0)
    bpy.context.view_layer.update()
    obj = bpy.data.objects['Light_17B12.SpotLight']
    light = obj.data
    print('HDR_LIGHT_AUTHORING', obj[lights.UE_INTENSITY_PROP], light['ue_intensity_source'], light.energy, flush=True)
    expected_power = light_photometry.radiant_power('SPOT', obj[lights.UE_INTENSITY_PROP],
        light['ue_intensity_units'], outer=math.radians(40), radius=0.05)
    assert math.isclose(light.energy, expected_power, rel_tol=1e-6)
    expected = (light_photometry.srgb_to_linear(124.0 / 255.0), 0.0, 1.0)
    assert all(math.isclose(a, b, rel_tol=1e-6) for a, b in zip(light.color, expected))
    assert not light.use_temperature
    assert any(node.type == 'GROUP' and node.node_tree.name == lights.UE_LIGHT_ATTENUATION_GROUP_NAME
               for node in light.node_tree.nodes)
    mesh = bpy.data.objects['Light_17B12']
    expected_emissive = (1538.6997, 0.0, 15470.784)
    assert all(math.isclose(a, b, rel_tol=1e-6)
               for a, b in zip(mesh['ExternalEmissiveContext'], expected_emissive))
    print('HDR_LIGHT_PASS', 'bridge-shaped' if sparse else 'full-dump',
          light.energy, tuple(light.color), tuple(mesh['ExternalEmissiveContext']))

# Light_17B6 serializes only InnerFullConeAngle=60.  Its missing outer value
# is the FF7 default 90-degree cone; the node mask provides edge falloff.
cone_test = bpy.data.lights.new('MissingOuterConeTest', 'SPOT')
lights.apply_spot_cone_properties(cone_test, {'InnerFullConeAngle': 60.0})
assert math.isclose(cone_test.spot_size, math.radians(90.0), abs_tol=1e-6)
assert math.isclose(cone_test.spot_blend, 0.0, abs_tol=1e-6)
print('SPOT_CONE_FALLBACK_PASS', math.degrees(cone_test.spot_size), cone_test.spot_blend)

# Mesh import selects a declared non-neutral context before neutral material
# defaults, and never overwrites a value the object already owns.
context_mesh = bpy.data.meshes.new('ExternalContextMesh')
context_obj = bpy.data.objects.new('ExternalContextObject', context_mesh)
bpy.context.scene.collection.objects.link(context_obj)
neutral = bpy.data.materials.new('ExternalContextNeutral')
neutral['sw ff7r_external_emissive'] = True
neutral['ff7r_external_emissive_context'] = (1.0, 1.0, 1.0)
authored = bpy.data.materials.new('ExternalContextAuthored')
authored['sw ff7r_external_emissive'] = True
authored['ff7r_external_emissive_context'] = (2.0, 0.5, 4.0)
context_mesh.materials.append(neutral)
context_mesh.materials.append(authored)
assert rmi_surface.initialize_external_emissive_context(context_obj)
assert tuple(context_obj['ExternalEmissiveContext']) == (2.0, 0.5, 4.0)
context_obj['ExternalEmissiveContext'] = (7.0, 8.0, 9.0)
assert not rmi_surface.initialize_external_emissive_context(context_obj)
assert tuple(context_obj['ExternalEmissiveContext']) == (7.0, 8.0, 9.0)
camera_only = bpy.data.materials.new('EmissiveCameraOnly')
camera_only['sw ff7r_emissive'] = True
context_mesh.materials.append(camera_only)
assert rmi_surface.initialize_external_emissive_context(context_obj)
assert context_obj['sw EmissiveCameraOnly'] is True
print('EXTERNAL_EMISSIVE_CONTEXT_PASS', tuple(context_obj['ExternalEmissiveContext']))
