"""Blender --background --factory-startup --disable-autoexec --python this_file.

Production-graph first-hit additive tests; no game assets or compositor required.
"""
from pathlib import Path
import math
import sys
import tempfile

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from addon.games.rebirth.materials import rmi_surface


surface, helper, truth = rmi_surface._modules()
template = rmi_surface._ensure_master(surface)
control = surface.CONTROL_FOR_SWITCH['Hologram_']
holograms = [(name, set(flags)) for name, flags in truth.items() if 'Hologram_' in flags]
assert len(holograms) == 6
for name, flags in holograms:
    for keep_all in (False, True):
        mat = template.copy()
        helper.apply_variant(mat, surface, name, flags, keep_all_switches=keep_all)
        assert mat.node_tree.get_output_node('CYCLES').name == 'Material Output (Cycles)'
        assert mat.node_tree.get_output_node('EEVEE').name == 'Material Output'
        assert mat.node_tree.nodes['Cycles Hologram'].inputs['First-hit Additive'].default_value
        assert mat.node_tree.nodes['UV1'].uv_map == 'Coordinate1'
        bpy.data.materials.remove(mat)


def snapshot(tree):
    return sorted((l.from_node.name, l.from_socket.identifier,
                   l.to_node.name, l.to_socket.identifier) for l in tree.links)


def old_cutout(mat):
    for name in surface.HOLOGRAM_CYCLES_NODES:
        mat.node_tree.nodes.remove(mat.node_tree.nodes[name])


# Upgrade the previous six-node cutout graph locally; preserve its images,
# controls, shared groups, and artist-selected opt-out on an already-new copy.
existing = template.copy()
existing.name = 'Pre-Cycles hologram'
existing['sqex_rmi_variant'] = holograms[0][0]
existing[control] = True
existing['Opacity Clip'] = .42
image = bpy.data.images.new('Preserved hologram texture', width=1, height=1)
existing.node_tree.nodes['TEX_Coverage'].image = image
old_cutout(existing)
displacement = existing.node_tree.nodes.new('ShaderNodeVectorMath')
displacement.name = 'Artist displacement'
existing.node_tree.links.new(displacement.outputs[0], existing.node_tree.nodes['Material Output'].inputs['Displacement'])
before_nodes = {n.name: n.as_pointer() for n in existing.node_tree.nodes}
before_links = snapshot(existing.node_tree)
group = template.node_tree.nodes['Cycles Hologram'].node_tree
interface = [s.identifier for s in group.interface.items_tree if s.item_type == 'SOCKET']
edited = template.copy()
edited.name = 'Artist cutout opt-out'
edited['sqex_rmi_variant'] = holograms[0][0]
edited.use_fake_user = True
edited.node_tree.nodes['Cycles Hologram'].inputs['First-hit Additive'].default_value = False
old_cutout(template)
assert rmi_surface._ensure_master(surface) == template
assert all(existing.node_tree.nodes[n].as_pointer() == p for n, p in before_nodes.items())
assert all(edge in snapshot(existing.node_tree) for edge in before_links)
assert existing['Opacity Clip'] == .42 and existing.node_tree.nodes['TEX_Coverage'].image == image
assert existing.node_tree.nodes['Cycles Hologram'].inputs['First-hit Additive'].default_value
assert existing.node_tree.nodes['Material Output (Cycles)'].inputs['Displacement'].links[0].from_node == displacement
assert not edited.node_tree.nodes['Cycles Hologram'].inputs['First-hit Additive'].default_value
assert [s.identifier for s in group.interface.items_tree if s.item_type == 'SOCKET'] == interface
before = snapshot(existing.node_tree)
assert rmi_surface.refresh_hologram_material(existing)
assert snapshot(existing.node_tree) == before

# Do not take over an artist's engine-specific output.
custom = template.copy()
old_cutout(custom)
artist_output = custom.node_tree.nodes.new('ShaderNodeOutputMaterial')
artist_output.name = 'Artist Cycles output'
artist_output.target = 'CYCLES'
custom.node_tree.links.new(custom.node_tree.nodes['Emission'].outputs[0], artist_output.inputs['Surface'])
before = snapshot(custom.node_tree)
assert not rmi_surface.refresh_hologram_material(custom)
assert snapshot(custom.node_tree) == before
assert custom.node_tree.get_output_node('CYCLES') == artist_output
assert custom.node_tree.nodes.get('Cycles Hologram') is None


class Loader:
    texture_namespace = 'cycles-hologram-cache'

    def __call__(self, _path):
        return None


data = {'properties': [{'name': 'Parent', 'value': {'ObjectPath': '/Game/' + holograms[0][0]}}]}
loader = Loader()
cached = rmi_surface.build_material('Cycles cache fixture', '/Game/CyclesHologram', data, loader)
old_cutout(cached)
cached['Object Fade'] = .83
assert rmi_surface.build_material('Cycles cache fixture', '/Game/CyclesHologram', data, loader) == cached
assert cached['Object Fade'] == .83
cached.node_tree.nodes['Cycles Hologram'].inputs['First-hit Additive'].default_value = False
assert rmi_surface.build_material('Cycles cache fixture', '/Game/CyclesHologram', data, loader) == cached
assert not cached.node_tree.nodes['Cycles Hologram'].inputs['First-hit Additive'].default_value
with tempfile.TemporaryDirectory(prefix='rmi_cycles_hologram_reload_') as directory:
    path = str(Path(directory) / 'reload.blend')
    bpy.ops.wm.save_as_mainfile(filepath=path)
    bpy.ops.wm.open_mainfile(filepath=path)
    edited = bpy.data.materials['Artist cutout opt-out']
    assert edited.node_tree.get_output_node('CYCLES').target == 'CYCLES'
    assert not edited.node_tree.nodes['Cycles Hologram'].inputs['First-hit Additive'].default_value
print('RMI_CYCLES_HOLOGRAM_LOGIC_PASS: 6 variants x 2 policies; targets; old cutout/cache migration; opt-out; custom output; reload')

template = rmi_surface._ensure_master(surface)
scene = bpy.context.scene
for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)
scene.render.engine = 'CYCLES'
scene.cycles.samples = 16
scene.cycles.use_denoising = False
scene.cycles.max_bounces = 16
scene.cycles.transmission_bounces = 8
scene.cycles.transparent_max_bounces = 64
scene.world.node_tree.nodes['Background'].inputs['Color'].default_value = (0, 0, 0, 1)
scene.render.resolution_x = 512
scene.render.resolution_y = 256
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = 'OPEN_EXR'
scene.render.image_settings.color_depth = '32'
scene.render.image_settings.color_mode = 'RGBA'
bpy.ops.object.camera_add(location=(0, 0, 10))
scene.camera = bpy.context.object
scene.camera.data.type = 'ORTHO'
scene.camera.data.ortho_scale = 16


def hologram(name, value=1, color=1, mode=0, fade=1, coverage=True, detail=1,
             first_hit=True, enabled=True, flags=None):
    mat = template.copy()
    mat.name = name
    if flags is not None:
        helper.apply_variant(mat, surface, name, flags)
    mat[control] = enabled
    mat[surface.CONTROL_FOR_SWITCH['Ghost_']] = not enabled
    mat[surface.CONTROL_FOR_SWITCH['Coverage_']] = coverage
    mat[surface.CONTROL_FOR_SWITCH['DetailCoverage_']] = detail != 1
    mat['Coverage Mode'] = mode
    mat['Object Fade'] = fade
    tree = mat.node_tree
    for role, value in (('Coverage', value), ('DetailCoverage', detail)):
        rmi_surface._make_colour_node(tree, tree.nodes['TEX_' + role], (value, value, value, 1))
    for link in list(tree.nodes['Emission'].inputs['Color'].links):
        tree.links.remove(link)
    tree.nodes['Emission'].inputs['Color'].default_value = (color, color, color, 1)
    tree.nodes['Cycles Hologram'].inputs['First-hit Additive'].default_value = first_hit
    surface.configure_surface_render_settings(mat)
    return mat


def simple(name, kind, value=.25):
    mat = bpy.data.materials.new(name)
    tree = mat.node_tree
    tree.nodes.clear()
    output = tree.nodes.new('ShaderNodeOutputMaterial')
    node = tree.nodes.new(kind)
    if kind == 'ShaderNodeEmission':
        node.inputs['Color'].default_value = (value, value, value, 1)
        node.inputs['Strength'].default_value = 1
    elif kind == 'ShaderNodeBsdfRefraction':
        node.inputs['Color'].default_value = (1, 1, 1, 1)
        node.inputs['IOR'].default_value = 1
        node.inputs['Roughness'].default_value = 0
    tree.links.new(node.outputs[0], output.inputs['Surface'])
    return mat


background = simple('Scene background .25', 'ShaderNodeEmission')
transparent = simple('Unrelated transparency', 'ShaderNodeBsdfTransparent')
glass = simple('Unrelated IOR1 transmission', 'ShaderNodeBsdfRefraction')
solid = hologram('First-hit solid')
hole = hologram('First-hit hole', value=0)
dark = hologram('First-hit dark', color=0)
cutout = hologram('Cutout opt-out', first_hit=False)
cases = []


def mesh(name, materials, verts, faces):
    data = bpy.data.meshes.new(name)
    data.from_pydata(verts, [], faces)
    data.update()
    obj = bpy.data.objects.new(name, data)
    scene.collection.objects.link(obj)
    for mat in materials:
        data.materials.append(mat)
    for index, face in enumerate(data.polygons):
        face.material_index = index
    return obj


def panel(name, layers, expected, backface=False, separate=False):
    index = len(cases)
    x, y = (index % 8) * 2 - 7, 3 - (index // 8) * 2
    materials = [*layers, background]
    verts, faces = [], []
    for layer in range(len(materials)):
        base = len(verts)
        z = -layer * .03
        verts.extend(((x - .8, y - .8, z), (x + .8, y - .8, z),
                      (x + .8, y + .8, z), (x - .8, y + .8, z)))
        face = (base, base + 1, base + 2, base + 3)
        faces.append(tuple(reversed(face)) if backface and layer < len(layers) else face)
    if separate:
        for i, mat in enumerate(materials):
            mesh(name + str(i), [mat], verts[i * 4:i * 4 + 4], [(0, 1, 2, 3)])
    else:
        mesh(name, materials, verts, faces)
    cases.append((name, x, y, expected))


panel('one', [solid], 1.25)
panel('three', [solid] * 3, 1.25)
panel('twenty', [solid] * 20, 1.25)
panel('hole reveals deeper hit', [hole, solid, solid], 1.25)
panel('all holes', [hole] * 3, .25)
panel('dark hit suppresses rear glow, not scene', [dark, solid, solid], .25)
panel('native below clip', [hologram('Native low', value=.2)], .25)
panel('native above clip', [hologram('Native high', value=.6)] * 3, 1.25)
panel('native fade empty', [hologram('Fade low', fade=.2)], .25)
panel('native fade occupied', [hologram('Fade high', fade=.6)] * 3, 1.25)
panel('hard empty', [hologram('Hard low', value=.2, mode=1)], .25)
panel('hard occupied', [hologram('Hard high', value=.6, mode=1)] * 3, 1.25)
panel('dither empty', [hologram('Dither low', value=0, mode=2)], .25)
panel('dither occupied', [hologram('Dither high', value=1, mode=2)] * 3, 1.25)
panel('detail hole', [hologram('Detail empty', detail=0)], .25)
panel('no coverage', [hologram('No coverage', coverage=False, value=0, fade=0)] * 3, 1.25)
panel('backfaces', [solid] * 3, .25, backface=True)
panel('opt-out cutout blocks scene', [cutout] * 3, 1)
panel('opt-out dark blocks scene', [hologram('Dark cutout', color=0, first_hit=False), solid], 0)
panel('other additive family unchanged', [hologram('Ghost additive', enabled=False)] * 3, 3.25)
panel('unrelated transparency', [transparent, solid, solid], 1.25)
panel('prior transmission limitation', [glass, solid, solid], .25)
panel('separate object shared-counter limitation', [solid, hologram('Rear object bright', color=2)], 1.25, separate=True)
for variant, flags in holograms:
    panel(variant, [hologram(variant, flags=flags)] * 3, 1.25)


def render_pixels(path):
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    image = bpy.data.images.load(str(path), check_existing=False)
    width, height = image.size
    pixels = list(image.pixels)
    bpy.data.images.remove(image)
    return width, height, pixels


with tempfile.TemporaryDirectory(prefix='rmi_cycles_first_hit_') as directory:
    width, height, pixels = render_pixels(Path(directory) / 'matrix.exr')
    for name, x, y, expected in cases:
        px = round((x / 16 + .5) * width)
        py = round((y / 8 + .5) * height)
        actual = pixels[4 * (py * width + px)]
        assert abs(actual - expected) < .025, (name, actual, expected)
        print('CYCLES_PIXEL', name, round(actual, 5))
    print('RMI_CYCLES_HOLOGRAM_RENDER_PASS', len(cases), 'production-graph panels')

    # With the Cycles checkbox still ON, Eevee must select the original
    # cutout output, not accidentally evaluate the transmission-depth trick.
    assert solid.node_tree.nodes['Cycles Hologram'].inputs['First-hit Additive'].default_value
    scene.render.engine = 'BLENDER_EEVEE'
    scene.eevee.taa_render_samples = 16
    width, height, pixels = render_pixels(Path(directory) / 'eevee.exr')
    expected_eevee = {'one': 1, 'three': 1, 'twenty': 1,
                      'hole reveals deeper hit': 1, 'all holes': .25,
                      'dark hit suppresses rear glow, not scene': 0,
                      'opt-out cutout blocks scene': 1, 'other additive family unchanged': 3.25}
    for name, x, y, _expected in cases:
        if name not in expected_eevee:
            continue
        px = round((x / 16 + .5) * width)
        py = round((y / 8 + .5) * height)
        actual = pixels[4 * (py * width + px)]
        assert abs(actual - expected_eevee[name]) < .025, (name, actual, expected_eevee[name])
    print('RMI_CYCLES_HOLOGRAM_EEVEE_ISOLATION_PASS', len(expected_eevee), 'default-enabled panels')
    scene.render.engine = 'CYCLES'

    # A non-emitting marker must not black out ordinary diffuse background
    # lighting. Sun shadow rays cross the fur stack, exercising the explicit
    # transparent-shadow branch rather than an emissive-backdrop shortcut.
    for obj in list(scene.objects):
        if obj.type == 'MESH':
            obj.hide_render = True
    diffuse = simple('Diffuse backdrop', 'ShaderNodeBsdfDiffuse')
    diffuse.node_tree.nodes.get('Diffuse BSDF').inputs['Color'].default_value = (1, 1, 1, 1)
    for x in (-1, 1):
        mesh('Lit floor ' + str(x), [diffuse],
             [(x - .8, -.8, -1), (x + .8, -.8, -1), (x + .8, .8, -1), (x - .8, .8, -1)],
             [(0, 1, 2, 3)])
    for i in range(3):
        z = -.1 * i
        mesh('Dark hologram shadow fixture ' + str(i), [dark],
             [(.2, -.8, z), (1.8, -.8, z), (1.8, .8, z), (.2, .8, z)], [(0, 1, 2, 3)])
    light = bpy.data.lights.new('Sun', 'SUN')
    light.energy = math.pi
    light.angle = 0
    scene.collection.objects.link(bpy.data.objects.new('Sun', light))
    scene.camera.data.ortho_scale = 4
    scene.render.resolution_x, scene.render.resolution_y = 128, 64
    width, height, pixels = render_pixels(Path(directory) / 'shadow.exr')
    bare = pixels[4 * ((height // 2) * width + width // 4)]
    through = pixels[4 * ((height // 2) * width + 3 * width // 4)]
    assert bare > .1 and abs(through - bare) < .025, (bare, through)
    print('RMI_CYCLES_HOLOGRAM_SHADOW_PASS', bare, through)
