"""Blender --background --factory-startup --disable-autoexec --python this_file.

No game assets required. Includes raw linear render assertions in both engines.
"""
from pathlib import Path
import sys
import tempfile

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from addon.games.rebirth.materials import rmi_surface
from addon.core.blender.import_cache import ImportCache


surface, helper, truth = rmi_surface._modules()
template = rmi_surface._ensure_master(surface)
groups = set()


def collect_groups(tree):
    for node in tree.nodes:
        if node.type == 'GROUP' and node.node_tree not in groups:
            groups.add(node.node_tree)
            collect_groups(node.node_tree)


collect_groups(template.node_tree)
print('RMI_HOLOGRAM_GRAPH_COUNTS', len(template.node_tree.nodes), len(template.node_tree.links),
      len(groups), len(template.node_tree.nodes) + sum(len(g.nodes) for g in groups),
      len(template.node_tree.links) + sum(len(g.links) for g in groups))
control = surface.CONTROL_FOR_SWITCH['Hologram_']
coverage_control = surface.CONTROL_FOR_SWITCH['Coverage_']
detail_control = surface.CONTROL_FOR_SWITCH['DetailCoverage_']
scene = bpy.context.scene
cube = bpy.context.active_object


def links(tree):
    return sorted((l.from_node.name, l.from_socket.identifier,
                   l.to_node.name, l.to_socket.identifier) for l in tree.links)


def evaluate(material, enabled):
    old_settings = (material.surface_render_method, material.use_transparency_overlap)
    cube.data.materials.clear()
    cube.data.materials.append(material)
    material[control] = enabled
    material.update_tag()
    scene.frame_set(scene.frame_current + 1)
    bpy.context.view_layer.update()
    assert (material.surface_render_method, material.use_transparency_overlap) == old_settings


# All six hologram variants are ordinary surfaces, including the fur/hair one.
holograms = [(name, set(flags)) for name, flags in truth.items() if 'Hologram_' in flags]
assert len(holograms) == 6
for name, flags in holograms:
    assert rmi_surface._master_for_switches(flags) == surface
    for keep_all in (False, True):
        material = template.copy()
        helper.apply_variant(material, surface, name, flags, keep_all_switches=keep_all)
        assert all(material.node_tree.nodes.get(n) for n in surface.HOLOGRAM_ALPHA_NODES)
        assert material.use_transparency_overlap is False
        assert material.surface_render_method == 'DITHERED'
        evaluate(material, True)
        if keep_all:
            evaluate(material, False)
            evaluate(material, True)
        cube.data.materials.clear()
        bpy.data.materials.remove(material)

# Other compositor families retain their additive shader and get Blended.
for family in ('Ghost_', 'Phantom_', 'Opacity_', 'BrokenFlowEmissive0_'):
    name, flags = next((n, set(f)) for n, f in truth.items()
                       if family in f and 'Hologram_' not in f)
    builder = rmi_surface._master_for_switches(flags)
    if builder != surface:
        continue
    material = template.copy()
    helper.apply_variant(material, surface, name, flags)
    assert control not in material
    assert not material.animation_data or not material.animation_data.drivers
    assert material.use_transparency_overlap is True
    assert material.surface_render_method == 'BLENDED'
    assert material.node_tree.nodes['SW_Hologram_'].outputs[0].default_value == 0
    bpy.data.materials.remove(material)


def make_legacy(material):
    tree = material.node_tree
    for name in (*surface.HOLOGRAM_CYCLES_NODES, *surface.HOLOGRAM_ALPHA_NODES):
        tree.nodes.remove(tree.nodes[name])
    tree.links.new(tree.nodes['Add Shader'].outputs[0], tree.nodes['Mix Shader'].inputs[2])
    material.use_transparency_overlap = True
    material.surface_render_method = 'BLENDED'


# Old saved instances and templates upgrade locally and idempotently.
legacy = template.copy()
legacy.name = 'Legacy hologram'
legacy['sqex_rmi_variant'] = holograms[0][0]
legacy[control] = True
legacy['Object Fade'] = 0.71
texture = bpy.data.images.new('Alpha migration texture', width=1, height=1)
legacy.node_tree.nodes['TEX_Coverage'].image = texture
highlight = legacy.node_tree.nodes['FF7R / Hologram Highlight / Color Only']
highlight.inputs['Tint'].default_value = (0.2, 0.4, 0.7, 1.0)
highlight.inputs['Strength'].default_value = 3.25
make_legacy(legacy)
old_nodes = {n.name: (n.as_pointer(), tuple(n.location)) for n in legacy.node_tree.nodes}
old_links = [edge for edge in links(legacy.node_tree) if edge[2] != 'Mix Shader' or edge[0] != 'Add Shader']
old_groups = {g.name: [s.identifier for s in g.interface.items_tree if s.item_type == 'SOCKET']
              for g in bpy.data.node_groups}
make_legacy(template)
assert rmi_surface._ensure_master(surface, import_cache=ImportCache()) == template
assert all(legacy.node_tree.nodes.get(n) for n in surface.HOLOGRAM_ALPHA_NODES)
assert all(legacy.node_tree.nodes[n].as_pointer() == p and tuple(legacy.node_tree.nodes[n].location) == pos
           for n, (p, pos) in old_nodes.items())
assert all(edge in links(legacy.node_tree) for edge in old_links)
assert legacy.node_tree.nodes['TEX_Coverage'].image == texture
assert legacy['Object Fade'] == 0.71
assert abs(highlight.inputs['Strength'].default_value - 3.25) < 1e-6
assert all(abs(a - b) < 1e-6 for a, b in zip(highlight.inputs['Tint'].default_value, (0.2, 0.4, 0.7, 1)))
assert all([s.identifier for s in bpy.data.node_groups[n].interface.items_tree if s.item_type == 'SOCKET'] == ids
           for n, ids in old_groups.items())
before = links(legacy.node_tree)
assert rmi_surface.refresh_hologram_material(legacy)
assert links(legacy.node_tree) == before

# Respect custom terminal/output wiring and artist-owned setting drivers.
custom = template.copy()
make_legacy(custom)
custom.node_tree.links.new(custom.node_tree.nodes['Emission'].outputs[0],
                           custom.node_tree.nodes['Material Output'].inputs['Surface'])
before = links(custom.node_tree)
assert not rmi_surface.refresh_hologram_material(custom)
assert links(custom.node_tree) == before and custom.use_transparency_overlap
artist = template.copy()
make_legacy(artist)
artist[control] = True
curve = artist.driver_add('use_transparency_overlap')
curve.driver.expression = '1'
assert rmi_surface.refresh_hologram_material(artist)
assert curve.driver.expression == '1'

# Cached material path: migrate without resetting a live switch from metadata.
class Loader:
    texture_namespace = 'hologram-alpha-fixture'

    def __call__(self, _path):
        return None


plain = next(n for n, f in truth.items() if 'Hologram_' not in f and 'Eye_' not in f and 'Hair_' not in f)
data = {'properties': [{'name': 'Parent', 'value': {'ObjectPath': '/Game/' + plain}}]}
old_policy = rmi_surface._import_all_material_switches
try:
    rmi_surface._import_all_material_switches = lambda: True
    loader = Loader()
    cached = rmi_surface.build_material('Cached live hologram', '/Game/AlphaFixture', data, loader)
    cached[control] = True
    make_legacy(cached)
    cached['Object Fade'] = 0.61
    assert rmi_surface.build_material('Cached live hologram', '/Game/AlphaFixture', data, loader) == cached
    assert cached[control] is True and cached['Object Fade'] == 0.61
    assert cached.use_transparency_overlap
    assert cached.surface_render_method == 'BLENDED', 'Live switch must not override imported variant settings'
    assert all(cached.node_tree.nodes.get(n) for n in surface.HOLOGRAM_ALPHA_NODES)
finally:
    rmi_surface._import_all_material_switches = old_policy

# Save/reload keeps static renderer settings with Auto Run Python disabled.
legacy.use_fake_user = True
evaluate(legacy, True)
with tempfile.TemporaryDirectory(prefix='rmi_hologram_reload_') as directory:
    filepath = str(Path(directory) / 'hologram.blend')
    bpy.ops.wm.save_as_mainfile(filepath=filepath)
    bpy.ops.wm.open_mainfile(filepath=filepath)
    cube = bpy.context.active_object
    scene = bpy.context.scene
    legacy = bpy.data.materials['Legacy hologram']
    evaluate(legacy, False)
    evaluate(legacy, True)
    assert not legacy.use_transparency_overlap
    assert legacy.surface_render_method == 'DITHERED'
    assert not legacy.animation_data or not legacy.animation_data.drivers
assert not any(getattr(h, '_ff7r_hologram_settings', False)
               for handlers in (bpy.app.handlers.depsgraph_update_post,
                                bpy.app.handlers.load_post, bpy.app.handlers.render_pre)
               for h in handlers)

print('RMI_HOLOGRAM_ALPHA_LOGIC_PASS: 6 variants x 2 policies; static presets; migrations; artist edits; cache; reload')

# Render an array of controlled production surface graphs. Only emission color
# and texture values are substituted: the real coverage/alpha/compositor paths
# stay intact. Mesh layers share one object, covering Eevee's overlap setting.
for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)
template = rmi_surface._ensure_master(surface)
scene.world.color = (0, 0, 0)
scene.world.node_tree.nodes['Background'].inputs['Color'].default_value = (0, 0, 0, 1)
bpy.ops.object.camera_add(location=(0, 0, 10))
scene.camera = bpy.context.object
scene.camera.data.type = 'ORTHO'
scene.camera.data.ortho_scale = 24
scene.render.resolution_x = 768
scene.render.resolution_y = 256
scene.render.resolution_percentage = 100
scene.render.film_transparent = False
scene.render.image_settings.file_format = 'OPEN_EXR'
scene.render.image_settings.color_depth = '32'
scene.render.image_settings.color_mode = 'RGBA'
scene.cycles.samples = 8
scene.cycles.use_denoising = False
scene.cycles.max_bounces = 8
scene.cycles.transparent_max_bounces = 16
scene.eevee.taa_render_samples = 16


def render_material(name, value=1, mode=0, coverage=True, fade=1, detail=1,
                    hologram=True, color=1, clip=.3333):
    mat = template.copy()
    mat.name = name
    mat[control] = hologram
    mat[coverage_control] = coverage
    mat[detail_control] = detail != 1
    # For the non-hologram control select the original additive branch.
    mat[surface.CONTROL_FOR_SWITCH['Ghost_']] = not hologram
    mat['Coverage Mode'] = mode
    mat['Object Fade'] = fade
    mat['Opacity Clip'] = clip
    tree = mat.node_tree
    # The cutout path is exercised here. The default Cycles first-hit
    # additive path has a separate production-graph render suite.
    tree.nodes['Cycles Hologram'].inputs['First-hit Additive'].default_value = False
    for role, val in (('Coverage', value), ('DetailCoverage', detail)):
        rmi_surface._make_colour_node(tree, tree.nodes['TEX_' + role], (val, val, val, 1))
    # Isolate alpha from the unchanged complex hologram RGB response.
    for link in list(tree.nodes['Emission'].inputs['Color'].links):
        tree.links.remove(link)
    tree.nodes['Emission'].inputs['Color'].default_value = (color, color, color, 1)
    mat.surface_render_method = 'BLENDED'
    surface.configure_surface_render_settings(mat)
    return mat


solid = render_material('Solid hologram')
hole = render_material('Hologram hole', value=0)
dark = render_material('Dark occupied hologram', color=0)
additive = render_material('Original ghost additive', hologram=False)
additive_reference = additive.copy()
additive_reference.name = 'Pre-change ghost output'
additive_reference.node_tree.links.new(additive_reference.node_tree.nodes['Add Shader'].outputs[0],
                                       additive_reference.node_tree.nodes['Mix Shader'].inputs[2])
additive_reference.node_tree.links.new(additive_reference.node_tree.nodes['Add Shader'].outputs[0],
                                       additive_reference.node_tree.nodes['Mix Shader (Cycles)'].inputs[2])
cases = []


def panel(name, materials, expected, backface=False):
    index = len(cases)
    x = (index % 12) * 2 - 11
    y = 2 - (index // 12) * 2
    verts, faces = [], []
    for layer in range(len(materials)):
        base = len(verts)
        z = -layer * 0.15
        verts.extend(((x - .8, y - .8, z), (x + .8, y - .8, z),
                      (x + .8, y + .8, z), (x - .8, y + .8, z)))
        face = (base, base + 1, base + 2, base + 3)
        faces.append(tuple(reversed(face)) if backface else face)
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    scene.collection.objects.link(obj)
    for material in materials:
        mesh.materials.append(material)
    for index, poly in enumerate(mesh.polygons):
        poly.material_index = index
    cases.append((name, x, y, expected))


panel('single', [solid], 1)
panel('triple', [solid] * 3, 1)
panel('front hole reveals back', [hole, solid, solid], 1)
panel('all holes', [hole] * 3, 0)
panel('dark hit blocks bright back', [dark, solid], 0)
panel('original additive triple', [additive] * 3, 3)
panel('native below clip', [render_material('Native .2', value=.2)], 0)
panel('native above clip', [render_material('Native .6', value=.6)] * 3, 1)
panel('native fade below clip', [render_material('Fade .2', value=1, fade=.2)], 0)
panel('native fade above clip', [render_material('Fade .6', value=1, fade=.6)] * 3, 1)
panel('no coverage ignores clip and fade', [render_material('No coverage', coverage=False, value=0, fade=0)] * 3, 1)
panel('backfaces', [solid] * 3, 0, backface=True)
panel('hard below clip', [render_material('Hard .2', value=.2, mode=1)], 0)
panel('hard above clip', [render_material('Hard .6', value=.6, mode=1)] * 3, 1)
panel('hard preserves old fade semantics', [render_material('Hard fade', value=1, mode=1, fade=0)], 1)
panel('dither empty', [render_material('Dither empty', value=0, mode=2)], 0)
panel('dither full', [render_material('Dither full', value=1, mode=2)] * 3, 1)
panel('detail coverage hole', [render_material('Detail hole', value=1, detail=0)], 0)
panel('detail coverage occupied', [render_material('Detail hit', value=1, detail=.8)] * 3, 1)
panel('pre-change additive reference', [additive_reference] * 3, 3)
panel('custom clip rejects native', [render_material('Custom clip high', value=.6, clip=.7)], 0)
panel('custom clip accepts native', [render_material('Custom clip low', value=.3, clip=.2)] * 3, 1)
# Use exact scalar sockets for this boundary: RGB luminance conversion and
# AVERAGE property drivers can round nominally equal values differently.
equality = render_material('Clip equality', value=.5, clip=.5)
clip_socket = equality.node_tree.nodes['P_Opacity_Clip'].outputs[0]
clip_socket.driver_remove('default_value')
clip_socket.default_value = .5
exact = equality.node_tree.nodes.new('ShaderNodeValue')
exact.outputs[0].default_value = .5
equality.node_tree.links.new(exact.outputs[0], equality.node_tree.nodes['Coverage'].inputs['Coverage'])
panel('native equals clip is empty', [equality], 0)
panel('coverage off ignores clip one', [render_material('No coverage clip one', coverage=False, clip=1)] * 3, 1)

with tempfile.TemporaryDirectory(prefix='rmi_hologram_render_') as directory:
    for engine in ('CYCLES', 'CYCLES', 'BLENDER_EEVEE', 'BLENDER_EEVEE'):
        method = 'DITHERED' if scene.get('last_engine') != engine else 'BLENDED'
        scene['last_engine'] = engine
        scene.render.engine = engine
        for mat in bpy.data.materials:
            if not mat.get(control, False):
                mat.surface_render_method = method
        scene.render.filepath = str(Path(directory) / (engine + '_' + method + '.exr'))
        bpy.ops.render.render(write_still=True)
        assert solid.surface_render_method == 'DITHERED', 'Hologram import preset must use cutout depth'
        result = bpy.data.images.load(scene.render.filepath, check_existing=False)
        pixels = list(result.pixels)
        readings = {}
        for name, x, y, expected in cases:
            px = round((x / 24 + .5) * scene.render.resolution_x)
            py = round((y / 8 + .5) * scene.render.resolution_y)
            offset = 4 * (py * result.size[0] + px)
            actual = pixels[offset]
            readings[name] = actual
            # Eevee Dithered cannot represent a purely additive transparent
            # surface. Verify this family against its additive graph.
            if engine == 'BLENDER_EEVEE' and method == 'DITHERED' and 'additive' in name:
                continue
            assert abs(actual - expected) < .03, (engine, method, name, actual, expected)
            print('PIXEL', engine, method, name, round(actual, 5))
        bpy.data.images.remove(result)
        assert abs(readings['original additive triple'] - readings['pre-change additive reference']) < .01
        print('RMI_HOLOGRAM_ALPHA_RENDER_PASS', engine, 'holograms=DITHERED', 'others=' + method, len(cases), 'panels')
