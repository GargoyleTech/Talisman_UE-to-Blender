"""Run with Blender --background --factory-startup --python this_file."""
from pathlib import Path
import sys

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from addon.games.rebirth.materials import rmi_surface


masters, variant_helper, ground_truth = rmi_surface._module_set()
master = masters["surface"]
material = rmi_surface._ensure_master(master)
tree = material.node_tree


def upstream(node, socket):
    links = node.inputs[socket].links
    assert len(links) == 1, (node.name, socket)
    link = links[0]
    while link.from_node.bl_idname == "NodeReroute":
        link = link.from_node.inputs[0].links[0]
    return link.from_node, link.from_socket


def links_snapshot(tree):
    return sorted((l.from_node.name, l.from_socket.identifier,
                   l.to_node.name, l.to_socket.identifier) for l in tree.links)


# One alphabetical switch stack and one alphabetical numeric stack, with the
# persisted integer selector properties and their existing driver paths intact.
switches = [(tree.nodes["SW_" + members[0]], name)
            for name, members, _default in master.SWITCH_CONTROLS]
numeric = [(tree.nodes[prefix + prop[0].replace(" ", "_")], prop[0])
           for prefix, properties in (("E_", master.ENUM_PROPS), ("P_", master.FLOAT_PROPS))
           for prop in properties]
for column in (switches, numeric):
    assert len({round(n.location_absolute.x, 3) for n, _name in column}) == 1
    ordered = [name for node, name in sorted(column, key=lambda pair: -pair[0].location_absolute.y)]
    assert ordered == sorted(ordered, key=str.casefold), ordered
assert switches[0][0].location_absolute.x < numeric[0][0].location_absolute.x
assert all(type(material[prop[0]]) is int for prop in master.ENUM_PROPS)
assert len(tree.animation_data.drivers) == len(switches) + len(numeric)
signature = [item.name for item in tree.nodes["MaterialPropertiesBundle"].bundle_items]
assert signature[31] == "sw Hologram_"
assert signature[75] == "Detail Normal Strength"
assert all([item.name for item in n.bundle_items] == signature
           for n in tree.nodes if n.bl_idname == "NodeSeparateBundle")

reroutes = [n for n in tree.nodes if n.bl_idname == "NodeReroute"]
assert len(reroutes) == 10
assert all(n.label for n in reroutes)
assert len({n.label for n in reroutes}) == len(reroutes)
for _frame, role, _kind, _space, _default in master.ROLES:
    if role == "ToneGradient":
        assert upstream(tree.nodes["TEX_ToneGradient"], "Vector")[0].name == "ToneGradient UV"
        continue
    source, socket = upstream(tree.nodes["TEX_" + role], "Vector")
    assert source == tree.nodes["UV%d" % master.ROLE_UV.get(role, 0)]
    assert socket.name == "UV"

assert not any(n.name.startswith("DetailEnable") for n in tree.nodes)
source, socket = upstream(tree.nodes["DetailLayer"], "Enable")
assert socket.name == "sw Detail_", (source.name, socket.name)
assert upstream(tree.nodes["Principled BSDF"], "Base Color")[0].name == "PhantomOverride"
assert upstream(tree.nodes["HologramOverride"], "Factor")[0].name == "PROPS_FRAME_AlphaCompositeColored"
assert upstream(tree.nodes["Material Output"], "Surface")[0].name == "Mix Shader"
assert upstream(tree.nodes["Mix Shader"], 1)[0].name == "Principled BSDF"
assert upstream(tree.nodes["Mix Shader"], 2)[0].name == "HologramCompositeOverride"
assert upstream(tree.nodes["HologramCompositeOverride"], 1)[0].name == "Add Shader"
assert upstream(tree.nodes["HologramCompositeOverride"], 2)[0].name == "HologramCutout"
assert upstream(tree.nodes["HologramCutout"], 0)[0].name == "HologramVisibility"
assert upstream(tree.nodes["HologramCutout"], 1)[0].name == "Transparent BSDF"
assert upstream(tree.nodes["HologramCutout"], 2)[0].name == "Emission"
assert upstream(tree.nodes["HologramCompositeOverride"], 0)[1].name == "sw Hologram_"
assert upstream(tree.nodes["HologramVisibility"], 0)[0].name == "AlphaWithoutBackfaces"
assert tree.get_output_node('EEVEE').name == 'Material Output'
assert tree.get_output_node('CYCLES').name == 'Material Output (Cycles)'
assert upstream(tree.nodes['Material Output (Cycles)'], 'Surface')[0].name == 'Mix Shader (Cycles)'
assert upstream(tree.nodes['Mix Shader (Cycles)'], 1)[0].name == 'Principled BSDF'
assert upstream(tree.nodes['Mix Shader (Cycles)'], 2)[0].name == 'HologramCyclesCompositeOverride'
assert upstream(tree.nodes['HologramCyclesCompositeOverride'], 0)[1].name == 'sw Hologram_'
assert upstream(tree.nodes['HologramCyclesCompositeOverride'], 1)[0].name == 'Add Shader'
assert upstream(tree.nodes['HologramCyclesCompositeOverride'], 2)[0].name == 'Cycles Hologram'
assert upstream(tree.nodes['Cycles Hologram'], 'Coverage')[0].name == 'HologramVisibility'
assert tree.nodes['Cycles Hologram'].inputs['First-hit Additive'].default_value is True
assert upstream(tree.nodes["Add Shader"], 0)[0].name == "Emission"
assert upstream(tree.nodes["Add Shader"], 1)[0].name == "Transparent BSDF"
assert tree.nodes["Emission"].inputs["Strength"].default_value == 1.0

# The default selector omits Phantom; Cycles adds it back independently.
gate = tree.nodes["Math.003"]
controls = []
assert upstream(tree.nodes["Math.003"], 0)[0] == upstream(tree.nodes["Math.003"], 1)[0]
assert upstream(tree.nodes["Math.004"], 0)[0].name == "Math.003"
controls.append(upstream(tree.nodes["Math.004"], 1)[1].name)
for name in ("Math.002", "Math.001", "Math"):
    gate = tree.nodes[name]
    assert gate.operation == "MAXIMUM"
    controls.append(upstream(gate, 1)[1].name)
controls.append(upstream(gate, 0)[1].name)
assert set(controls) == {"sw Phantom_", "sw Opacity_", "sw Hologram_", "sw Ghost_",
                         "sw BrokenFlowEmissive0_ _ ___ _4 flags_"}

hologram = tree.nodes["FF7R / Hologram Highlight / Color Only"]
hologram_name = hologram.name
group = hologram.node_tree
assert len(group.nodes) == 32 and len(group.links) == 45
assert tuple(hologram.inputs["Tint"].default_value) == (0.0, 1.0, 1.0, 1.0)
assert upstream(hologram, "Normal")[0].name == "N_SharedWorld"
assert upstream(hologram, "Roughness")[0].name == "LayerBlend"
assert upstream(hologram, "Occlusion") == (tree.nodes["DetailLayer"],
                                         tree.nodes["DetailLayer"].outputs["AO"])
assert not hologram.outputs["Intensity"].is_linked

# Rebuilding an old template must not rebuild a group's interface or reset
# edits on a material instance sharing that group.
instance = material.copy()
instance.name = "Existing layout regression instance"
old_links = links_snapshot(instance.node_tree)
old_group_links = links_snapshot(group)
identifiers = [i.identifier for i in group.interface.items_tree if i.item_type == "SOCKET"]
instance.node_tree.nodes[hologram_name].inputs["Strength"].default_value = 3.0
group.nodes["Head-on highlight / u^5"].inputs[1].default_value = 5.25
tree.nodes.remove(tree.nodes["HologramOverride"])
rebuilt = rmi_surface._ensure_master(master)
assert rebuilt == material
assert rebuilt.node_tree.nodes.get("HologramOverride") is not None
assert links_snapshot(instance.node_tree) == old_links
assert instance.node_tree.nodes[hologram_name].inputs["Strength"].default_value == 3.0
assert links_snapshot(group) == old_group_links
assert [i.identifier for i in group.interface.items_tree if i.item_type == "SOCKET"] == identifiers
assert group.nodes["Head-on highlight / u^5"].inputs[1].default_value == 5.25
group.nodes["Head-on highlight / u^5"].inputs[1].default_value = 5.0

# Capability fallback still creates a complete shader without bundle nodes.
has_bundles = master.HAS_BUNDLES
try:
    master.HAS_BUNDLES = False
    direct = master.build(uv_names=[f"Coordinate{i}" for i in range(4)])
    assert not any(n.bl_idname in {"NodeCombineBundle", "NodeSeparateBundle"} for n in direct.node_tree.nodes)
    source, _socket = upstream(direct.node_tree.nodes["DetailLayer"], "Enable")
    assert source.name == "SW_Detail_"
    source, _socket = upstream(direct.node_tree.nodes["HologramOverride"], "Factor")
    assert source.name == "SW_Hologram_"
    assert upstream(direct.node_tree.nodes["HologramCompositeOverride"], 0)[0].name == "SW_Hologram_"
    assert upstream(direct.node_tree.nodes["HologramNativeAlpha"], 0)[0].name == "E_Coverage_Mode"
    assert upstream(direct.node_tree.nodes['HologramCyclesCompositeOverride'], 0)[0].name == 'SW_Hologram_'
finally:
    master.HAS_BUNDLES = has_bundles
    material = master.build(uv_names=[f"Coordinate{i}" for i in range(4)])

assert not master._LOG, master._LOG
assert all(l.is_valid for l in material.node_tree.links)
print("RMI_SURFACE_LAYOUT_PASS: two sorted columns; labeled routing; hologram/compositor; shared-group preservation; direct fallback")
