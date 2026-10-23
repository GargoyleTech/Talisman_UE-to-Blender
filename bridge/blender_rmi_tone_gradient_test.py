"""Blender --background --factory-startup --python this_file; no game files."""
from pathlib import Path
import sys

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from addon.games.rebirth.materials import rmi_surface


class Session:
    texture_namespace = "tone-gradient-fixture"

    def __init__(self):
        self.paths = []
        self.image = bpy.data.images.new("ToneGradient HDR", width=2, height=1, float_buffer=True)
        self.image.colorspace_settings.name = "Non-Color"
        self.image.pixels[:] = [0.01, 0.02, 0.04, 1.0, 0.9, 3.3, 2.3, 1.0]

    def __call__(self, path):
        self.paths.append(path)
        return self.image


masters, _helper, truth = rmi_surface._module_set()
master = masters["surface"]
template = rmi_surface._ensure_master(master)
# Saved templates without the slot must rebuild, without a version bump.
template.node_tree.nodes.remove(template.node_tree.nodes["TEX_ToneGradient"])
template = rmi_surface._ensure_master(master)
assert template.node_tree.nodes["TEX_ToneGradient"].bl_idname == "ShaderNodeTexImage"

session = Session()
variants = [name for name, switches in truth.items() if "ToneGradient_" in switches]
assert len(variants) == 7
for variant in variants:
    assert rmi_surface._master_for_switches(truth[variant]) is master
    data = {"properties": [
        {"name": "Parent", "value": {"ObjectPath": "/Game/Materials/" + variant}},
        {"name": "TextureParameterValues", "value": [{
            "ParameterInfo": {"Name": "ToneGradient"},
            "ParameterValue": {"ObjectPath": "/Game/Textures/ToneGradient"},
        }]},
    ]}
    path = "/Game/ToneGradientFixture/" + variant
    material = rmi_surface.build_material(variant, path, data, session)
    node = material.node_tree.nodes["TEX_ToneGradient"]
    assert node.image == session.image and not node.mute
    assert node.image.colorspace_settings.name == "Non-Color"
    assert node.interpolation == "Linear" and node.extension == "EXTEND"
    assert node.parent.name == "FRAME_ToneGradient"
    assert material[master.CONTROL_FOR_SWITCH["ToneGradient_"]] is True
    assert material["ff7r_rmi_texture_images"] == 1
    assert material.node_tree.nodes["USE_ToneGradient"].outputs["Result"].links[0].to_node.name == "External emissive tint"
    assert rmi_surface.build_material(variant, path, data, session) == material
# Initial assignment plus the first cached refresh/texture-quality request.
assert session.paths == ["/Game/Textures/ToneGradient"] * (2 * len(variants))
assert session.image.pixels[5] > 3.0, "HDR data must remain unclamped"
assert all("ToneGradient" not in {spec[1] for spec in masters[profile].ROLES}
           for profile in ("eye", "hair"))
print("RMI_TONE_GRADIENT_PASS: seven variants; image import; linear HDR; lookup filtering; saved master rebuild; cache reuse")
