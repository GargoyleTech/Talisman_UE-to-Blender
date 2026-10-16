"""Run with Blender --background --factory-startup --python this_file."""
from pathlib import Path
import sys

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from addon.games.rebirth.materials import rmi_surface


EXPECTED_PROFILE_COUNTS = {"surface": 99, "eye": 3, "hair": 2}


masters, variant_helper, ground_truth = rmi_surface._module_set()
templates = {}
counts = {name: 0 for name in EXPECTED_PROFILE_COUNTS}

# A saved pre-split ordinary master has the old eye controls on the same
# datablock name. A profile revision must rebuild it rather than preserving
# inactive controls beside the new surface-only graph.
legacy_surface = rmi_surface._ensure_master(masters["surface"])
legacy_surface["sw Eye_ + IrisColor_ + IrisNormal_ + ScleraNormal_"] = True
legacy_surface["Eye Cornea Slope"] = 0.5
legacy_surface["_RMI_Profile_Revision"] = 0
rebuilt_surface = rmi_surface._ensure_master(masters["surface"])
assert "sw Eye_ + IrisColor_ + IrisNormal_ + ScleraNormal_" not in rebuilt_surface
assert "Eye Cornea Slope" not in rebuilt_surface
assert rebuilt_surface["_RMI_Profile_Revision"] == masters["surface"].PROFILE_REVISION

for variant_name, raw_switches in ground_truth.items():
    switches = set(raw_switches)
    master = rmi_surface._master_for_switches(switches)
    profile = master.PROFILE_NAME
    unsupported = (switches - set(master.ENGINE_ONLY_SWITCHES)
                   - set(master.KNOWN_SWITCHES))
    assert not unsupported, (variant_name, profile, unsupported)
    template = templates.get(profile)
    if template is None:
        template = rmi_surface._ensure_master(master)
        assert template["_RMI_Profile"] == profile
        assert template["_RMI_Profile_Revision"] == master.PROFILE_REVISION
        templates[profile] = template
    material = template.copy()
    material.name = "ProfileTest_" + variant_name
    variant_helper.apply_variant(material, master, variant_name, switches)
    assert material["Shading Model"] == variant_helper.shading_model_for(switches)
    counts[profile] += 1

assert counts == EXPECTED_PROFILE_COUNTS, counts
assert templates["surface"].node_tree.nodes.get("FRAME_EyePath") is None
assert templates["surface"].node_tree.nodes.get("FRAME_HairPath") is None
assert templates["eye"].node_tree.nodes.get("FRAME_EyePath") is not None
assert templates["eye"].node_tree.nodes.get("FRAME_HairPath") is None
assert templates["hair"].node_tree.nodes.get("FRAME_HairPath") is not None
assert templates["hair"].node_tree.nodes.get("FRAME_EyePath") is None

# A Constant Menu in a ShaderNodeTree has no authorable enum definition, so
# all profiles deliberately retain the numeric selector that drives the
# portable comparison ladders.  This prevents an empty-menu assignment such
# as ``Standard (SM1)`` from aborting material creation on Blender 5.2+.
for template in templates.values():
    assert template.node_tree.nodes["E_Shading_Model"].bl_idname == "ShaderNodeValue"

print("RMI_PROFILE_PASS", counts, "variants=", len(ground_truth))
