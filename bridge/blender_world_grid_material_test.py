"""Engine WorldGridMaterial uses black diffuse without reading an instance."""
from pathlib import Path
import sys
import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from addon.core.blender.material_nodes import is_world_grid_material
from addon.formats.unreal_package.mesh_import import _static_mesh_material
from addon.games.remake.materials import build_material


def no_images(path):
    raise AssertionError('WorldGridMaterial requested a texture: ' + path)


def check(material):
    nodes = material.node_tree.nodes
    assert len(nodes) == 2
    diffuse = next(node for node in nodes if node.type == 'BSDF_DIFFUSE')
    output = next(node for node in nodes if node.type == 'OUTPUT_MATERIAL')
    assert tuple(diffuse.inputs['Color'].default_value) == (0, 0, 0, 1)
    assert output.inputs['Surface'].links[0].from_node == diffuse


base = 'Engine/Content/EngineMaterials/WorldGridMaterial'
for index, path in enumerate((base, base + '.uasset', base + '.WorldGridMaterial',
                              '/' + base.lower() + '.0', base.replace('/', '\\'))):
    assert is_world_grid_material(path)
    check(build_material('WorldGrid' + str(index), path, {}, no_images))
    placeholder = _static_mesh_material('GridPlaceholder' + str(index), path, 'world-grid-test')
    check(placeholder)
    assert _static_mesh_material('GridPlaceholder' + str(index), path, 'world-grid-test') == placeholder
    check(placeholder)
assert not is_world_grid_material('/Game/Environment/WorldGridMaterial')
assert not is_world_grid_material(base + 'Extra')
print('WORLD_GRID_BLACK_DIFFUSE_OK', flush=True)
