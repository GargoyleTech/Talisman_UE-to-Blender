"""Run with Blender --background --factory-startup --python this_file."""
import json
from pathlib import Path
import sys
import tempfile

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from addon.games.rebirth.materials import rmi_surface


def snapshot(material):
    trees = {}

    def visit(tree):
        if tree.name in trees:
            return
        defaults = []
        for node in tree.nodes:
            for socket in node.inputs:
                if hasattr(socket, "default_value"):
                    value = socket.default_value
                    if not isinstance(value, (str, int, float, bool)):
                        try:
                            value = list(value)
                        except TypeError:
                            value = getattr(value, "name", None)
                    defaults.append((node.name, socket.identifier, value))
        trees[tree.name] = {
            "links": sorted((link.from_node.name, link.from_socket.identifier,
                             link.to_node.name, link.to_socket.identifier)
                            for link in tree.links),
            "defaults": defaults,
        }
        for node in tree.nodes:
            if node.type == 'GROUP' and node.node_tree:
                visit(node.node_tree)

    visit(material.node_tree)
    return json.dumps(trees, sort_keys=True)


master, _, _ = rmi_surface._modules()
template = rmi_surface._ensure_master(master)
existing = template.copy()
existing.name = 'Existing prop material'
existing.use_fake_user = True
before = snapshot(existing)

# Reproduce old files: the unassigned template had no fake user and vanished.
template.use_fake_user = False
with tempfile.TemporaryDirectory(prefix='ff7r_rmi_reload_') as directory:
    filepath = str(Path(directory) / 'reload.blend')
    bpy.ops.wm.save_as_mainfile(filepath=filepath)
    bpy.ops.wm.open_mainfile(filepath=filepath)
    assert bpy.data.materials.get(master.MAT_NAME) is None
    existing = bpy.data.materials['Existing prop material']
    assert snapshot(existing) == before, 'Save/reload itself changed the graph'
    template = rmi_surface._ensure_master(master)
    assert snapshot(existing) == before, 'Recreating master damaged existing material'
    assert template.use_fake_user
    emission = existing.node_tree.nodes['EmissionStrength']
    assert all(socket.is_linked for socket in list(emission.inputs)[:2])
    bpy.ops.wm.save_as_mainfile(filepath=filepath)
    bpy.ops.wm.open_mainfile(filepath=filepath)
    assert bpy.data.materials.get(master.MAT_NAME) is not None
    assert snapshot(bpy.data.materials['Existing prop material']) == before
    print('RMI_RELOAD_PASS: existing links/defaults preserved; master survives reload')
