"""Niagara resource import fixtures; optional --config validates the real effect.

blender --background --factory-startup --python this_file -- [--config private.json]
"""

import argparse
from collections import Counter
import importlib
import json
from pathlib import Path
import sys

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import addon
from addon.core.profiles import GamePaths
from addon.formats.niagara import package_data, resources
from addon.games.rebirth.importers import niagara
from addon.games.rebirth.profile import PROFILE


ASSET = 'End/Content/Fixture/Effect.uasset'
BASE = '/Game/Fixture/Effect.Effect'
MESH = '/Game/Fixture/Mesh.Mesh'
SECOND = '/Game/Fixture/Second.Second'
RED = '/Game/Fixture/Red.Red'
BLUE = '/Game/Fixture/Blue.Blue'


def reference(path):
    return {'ObjectPath': path, 'ObjectName': "Object'" + path.rsplit('.', 1)[-1] + "'"}


def export(index, kind, path, props):
    return {'exportIndex': index, 'name': path.rsplit('.', 1)[-1], 'type': kind,
            'fullName': kind + "'" + path + "'", 'propertyStatus': 'partial',
            'properties': [{'name': name, 'propertyType': 'Fixture', 'value': value} for name, value in props.items()]}


def renderer(index, mesh, overrides, enabled=True):
    return export(index, 'NiagaraMeshRendererProperties', BASE + ':Emitter.Render' + str(index), {
        'Meshes': [{'StructType': {'Mesh': reference(mesh), 'Scale': {'StructType': {'X': 7, 'Y': 8, 'Z': 9}},
                                 'PivotOffset': {'StructType': {'X': 100, 'Y': 200, 'Z': 300}}}}],
        'bOverrideMaterials': enabled,
        'OverrideMaterials': [{'StructType': {'ExplicitMat': reference(path or 'None'),
            'UserParamBinding': {'StructType': {'VarData': [0] * 65537}}}} for path in overrides],
    })


def fixture_report():
    return {'exports': [
        export(0, 'NiagaraSystem', BASE, {}),
        export(1, 'NiagaraEmitter', BASE + ':Emitter', {'RendererProperties': [reference(BASE + ':Emitter.Render2')]}),
        renderer(2, MESH, [RED]), renderer(3, MESH.upper(), [RED.upper(), None]),
        renderer(4, MESH, [BLUE]), renderer(5, SECOND, [None, BLUE]),
        export(6, 'NiagaraSpriteRendererProperties', BASE + ':Emitter.Sprite', {'Material': reference(RED)}),
        renderer(7, 'None', [RED]),
        export(8, 'NiagaraScript', BASE + ':Emitter.SpawnScript', {'Usage': 'ENiagaraScriptUsage::ParticleSpawnScript'}),
    ], 'limitations': ['Fixture partial system']}


class FixtureSession:
    cache_namespace = 'niagara-resource-fixture'
    texture_namespace = cache_namespace
    pbr_mapping = {}
    profile = PROFILE

    def __init__(self, *args, fail_mesh=False, **options):
        self.mesh_requests = Counter()
        self.material_cache = {}
        self.fail_mesh = fail_mesh
        self.options = options

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def static_mesh(self, path):
        self.mesh_requests[path] += 1
        if self.fail_mesh and 'Second' in path:
            raise ValueError('Fixture unreadable geometry')
        return {'name': Path(path).stem, 'positions': [[0, 0, 0], [100, 0, 0], [100, 100, 0], [0, 100, 0]],
                'normals': [[0, 0, 1]] * 4, 'indices': [0, 1, 2, 0, 2, 3],
                'uvChannels': [[[0, 0], [1, 0], [1, 1], [0, 1]]],
                'sections': [{'materialIndex': 0, 'firstIndex': 0, 'triangleCount': 1,
                              'materialPath': '/Game/Fixture/Default.Default'},
                             {'materialIndex': 1, 'firstIndex': 3, 'triangleCount': 1,
                              'materialPath': '/Game/Fixture/Other.Other'}]}

    def material_instance(self, path):
        self.material_cache.setdefault(path.casefold(), {'type': 'MaterialInstanceConstant', 'textures': []})
        return self.material_cache[path.casefold()]

    def material_asset_path(self, path):
        return path

    def niagara_asset(self, path):
        return fixture_report()

    def __call__(self, path):
        raise AssertionError('The fixture declares no textures')


def check_fixture():
    model = package_data.decode_package(fixture_report(), ASSET)
    assert len(model.resources) == 3
    assert len(model.resources[0].references) == 2
    assert model.resources[2].material_paths == (None, BLUE)
    assert len(json.dumps(model.manifest())) < 15000
    assert 'VarData' not in json.dumps(model.manifest())
    assert model.scripts[0].usage.endswith('ParticleSpawnScript')
    groups_before = set(bpy.data.node_groups)
    mounted = FixtureSession()
    result = resources.import_mesh_resources(bpy.context, model, mounted, profile=PROFILE)
    assert len(result.objects) == 3 and result.mesh_count == 2 and result.skipped_renderers == 1
    assert not result.failures and result.warnings
    first, blue, second = result.objects
    assert first.data == blue.data and first.data != second.data
    assert first.material_slots[0].material['ue_virtual_path'] == RED
    assert blue.material_slots[0].material['ue_virtual_path'] == BLUE
    assert first.material_slots[1].material == blue.material_slots[1].material
    assert second.material_slots[1].material == blue.material_slots[0].material
    assert second.material_slots[0].link == 'DATA'
    assert tuple(first.data.vertices[1].co) == (1, 0, 0)
    assert tuple(first.data.vertices[2].co) == (1, -1, 0)
    assert set(bpy.data.node_groups) == groups_before
    for obj in result.objects:
        assert obj.type == 'MESH' and not obj.modifiers and not obj.animation_data and obj.parent is None
        assert tuple(obj.location) == (0, 0, 0) and tuple(obj.scale) == (1, 1, 1)
        assert all(slot.material.get('ue_texture_inventory_complete') for slot in obj.material_slots)
    assert sorted(mounted.mesh_requests.values()) == [1, 1]
    assert len(json.loads(result.collection['ue_niagara_manifest'])['renderers']) == 6

    # Explicitly disabled/empty overrides use mesh defaults and collapse to the
    # same variant. Unknown override mode is retained as unknown, never true.
    report_data = fixture_report()
    report_data['exports'] = report_data['exports'][:2] + [renderer(9, MESH, [RED], False), renderer(10, MESH, [None]),
        renderer(11, MESH, [BLUE], None)]
    defaults = package_data.decode_package(report_data, ASSET)
    assert len(defaults.resources) == 1 and defaults.resources[0].material_paths == ()
    assert defaults.renderers[-1].override_materials is None and defaults.warnings

    failures = resources.import_mesh_resources(bpy.context, model, FixtureSession(fail_mesh=True), profile=PROFILE)
    assert len(failures.objects) == 2 and failures.mesh_count == 1 and len(failures.failures) == 1
    before = (len(bpy.data.objects), len(bpy.data.collections))
    sprite_only = package_data.decode_package({'exports': [fixture_report()['exports'][0], fixture_report()['exports'][6]]}, ASSET)
    empty = resources.import_mesh_resources(bpy.context, sprite_only, FixtureSession(), profile=PROFILE)
    assert not empty.objects and empty.collection is None
    assert before == (len(bpy.data.objects), len(bpy.data.collections))
    try:
        package_data.decode_package({'exports': []}, ASSET)
    except ValueError:
        pass
    else:
        raise AssertionError('Non-Niagara package accepted')

    # The registered operator's explicit path must bypass browser indexing and
    # use this same backend. No saved preferences are modified by this test.
    old_session, old_paths = niagara.NiagaraSession, niagara._paths
    niagara.NiagaraSession = FixtureSession
    niagara._paths = lambda context: GamePaths(str(ROOT))
    try:
        assert bpy.ops.import_scene.ff7r_rebirth_niagara_game_packages(virtual_path=ASSET, import_textures=False) == {'FINISHED'}
        operator_type = bpy.ops.import_scene.ff7r_rebirth_niagara_game_packages.get_rna_type()
        assert operator_type.description == addon.strings.REBIRTH_NIAGARA_DESCRIPTION
        assert operator_type.properties['scale_factor'].description == addon.strings.SHARED_SCALE_FACTOR
    finally:
        niagara.NiagaraSession, niagara._paths = old_session, old_paths
    print('NIAGARA_RESOURCES_FIXTURE_OK', flush=True)


def check_game(config_path, save_blend):
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for collection in list(bpy.data.collections):
        if collection.get('ue_niagara_asset'):
            bpy.data.collections.remove(collection)
    bpy.data.orphans_purge(do_recursive=True)
    config = json.loads(Path(config_path).read_text())['rebirth']
    paths = GamePaths(config['root'], config.get('oodle', ''), config['usmap'])
    asset = 'End/Content/Effect/Character/Property/UI7034_ConsumedItem/Particle/FX_UI7034_Materia_Yellow_01.uasset'
    with niagara.NiagaraSession(paths, max_texture_resolution=256) as mounted:
        index = mounted.request({'action': 'niagara_index', 'pathFilter': 'FX_UI7034_Materia_Yellow_01.uasset'})['index']
        assert index['paths'] == [asset] and index['readablePackages'] == 1
        model = package_data.decode_package(mounted.niagara_asset(asset), asset)
        result = resources.import_mesh_resources(bpy.context, model, mounted, profile=PROFILE)
        assert len(result.objects) == 7 and result.mesh_count == 4 and result.skipped_renderers == 1, result.failures
        assert not result.failures and not model.warnings
        assigned = {slot.material['ue_virtual_path'] for obj in result.objects for slot in obj.material_slots if slot.material}
        assert len(assigned) == 5, assigned
        assert mounted.request_counts['static_mesh'] == 4
        assert mounted.request_counts.get('generic_material', 0) >= 5
        assert mounted.request_counts.get('generic_texture', 0) > 0
        assert not mounted.request_counts.get('material') and not mounted.request_counts.get('texture')
        assert all(not obj.modifiers and tuple(obj.location) == (0, 0, 0) for obj in result.objects)
        assert any(image.packed_file for image in mounted.cache.values() if image is not None)
        print('NIAGARA_RESOURCES_GAME_OK', json.dumps({'objects': len(result.objects), 'meshes': result.mesh_count,
              'materials': len(assigned), 'textures': mounted.loaded, 'failedTextures': mounted.failed}), flush=True)
    if save_blend:
        bpy.ops.wm.save_as_mainfile(filepath=str(Path(save_blend).resolve()))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config')
    parser.add_argument('--save-blend')
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])
    addon.register()
    check_fixture()
    if args.config:
        check_game(args.config, args.save_blend)
    # Registration remains valid on an in-place reload.
    importlib.reload(addon)
    addon.register()
    assert bpy.ops.import_scene.ff7r_rebirth_niagara_game_packages.get_rna_type()
    addon.unregister()
    print('NIAGARA_RELOAD_OK', flush=True)
