"""Validate a built ZIP in factory Blender without changing installed add-ons."""

import argparse
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import tomllib
import types
import zipfile

import bpy


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--archive', required=True)
    parser.add_argument('--config', help='Optional ignored game config: verify keys are absent')
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    root = Path(__file__).resolve().parents[1]
    manifest = tomllib.loads((root / 'addon/blender_manifest.toml').read_text())
    package_id, version = manifest['id'], tuple(map(int, manifest['version'].split('.')))
    with tempfile.TemporaryDirectory(prefix='generic-package-', dir=root / '.local') as directory:
        with zipfile.ZipFile(args.archive) as archive:
            names = archive.namelist()
            roots = {name.split('/')[0] for name in names}
            assert len(roots) == 1, 'Installable ZIP needs one add-on folder'
            package = roots.pop()
            assert all(name.startswith(package+'/') for name in names)
            assert not any('..' in Path(name).parts or '.local/' in name or 'oo2core' in name.casefold()
                           or name.endswith(('.blend', '.pyc', '.usmap')) for name in names)
            assert package+'/formats/unreal_mesh/sequence_import.py' in names
            assert package+'/formats/niagara/package_data.py' in names
            assert package+'/formats/niagara/resources.py' in names
            assert package+'/games/rebirth/importers/niagara.py' in names
            assert package+'/formats/unreal_mesh/binary_geometry.py' in names
            assert package+'/formats/ue_map/instance_geometry.py' in names
            assert package+'/formats/ue_map/splines.py' in names
            assert package+'/formats/ue_map/README_SPLINES.md' in names
            assert package+'/formats/unreal_mesh/README_NANITE.md' in names
            assert package+'/ui/nanite.py' in names
            assert package+'/ui/texture_node.py' in names
            assert package+'/ui/texture_browser.py' in names
            assert package+'/formats/unreal_package/texture_browser.py' in names
            if args.config:
                scripts = [archive.read(name) for name in names if name.endswith(('.py', '.toml', '.md', '.json'))]
                for config in json.loads(Path(args.config).read_text()).values():
                    key = config.get('key')
                    if key:
                        assert all(key.encode() not in script for script in scripts), 'Local key found in package'
            binary_name = 'bridge/TalismanGameAssetBridge.dll'
            binary = archive.read(package+'/'+binary_name)
            assert hashlib.sha256(binary).digest() == hashlib.sha256((root/'addon'/binary_name).read_bytes()).digest()
            archive.extractall(directory)
        sys.path.insert(0, directory)
        bpy.ops.preferences.addon_enable(module=package)
        module = importlib.import_module(package)
        assert module.bl_info['version'] == version
        niagara_props = bpy.ops.import_scene.ff7r_rebirth_niagara_game_packages.get_rna_type().properties
        assert 'virtual_path' in niagara_props and abs(niagara_props['scale_factor'].default - 0.01) < 1e-6
        assert Path(module.__file__).is_relative_to(directory)
        assert module.gargoyle_core.gargoyle_executable_path(Path(module.__file__).parent).is_relative_to(directory)
        profile_ui = importlib.import_module(package+'.ui.preferences')
        preferences = bpy.context.preferences.addons[package].preferences
        last_flag = next(profile for profile in profile_ui.ensure_generic_unreal_profiles(preferences)
                         if profile.profile_id == 'last_flag')
        assert (last_flag.name, last_flag.game_version, last_flag.usmap_path, last_flag.aes_key,
                last_flag.game_path) == ('Last Flag', 'GAME_UE5_5', '', 'n/a', '')
        assert any(match.slot == 'roughness' and match.parameter == 'ORM Texture' and match.channel == 'G'
                   for match in last_flag.pbr_slot_matches)
        for operator in (bpy.ops.import_scene.sqex_generic_unreal_mesh,
                         bpy.ops.object.sqex_import_generic_unreal_animation, bpy.ops.import_scene.sqex_generic_unreal_sequence):
            assert 'cue4parse_profile' in operator.get_rna_type().properties
        mesh_kind = bpy.ops.import_scene.sqex_generic_unreal_mesh.get_rna_type().properties['mesh_kind']
        assert 'UMAP' in mesh_kind.enum_items
        spline_option = bpy.ops.import_scene.sqex_generic_unreal_umap.get_rna_type().properties['import_splines']
        assert spline_option.default is True
        for operator in (bpy.ops.import_scene.sqex_generic_unreal_static_mesh,
                         bpy.ops.import_scene.sqex_generic_unreal_umap):
            props = operator.get_rna_type().properties
            assert props['nanite_mode'].default == 'AUTO'
            assert set(props['nanite_mode'].enum_items.keys()) == {'AUTO', 'NATIVE', 'FALLBACK'}
            assert props['max_nanite_triangles'].default == 2_000_000
            assert props['nanite_cache_mb'].default == 256
        module = importlib.reload(module)
        module.register()
        assert bpy.ops.wm.sqex_inspect_generic_sequence_bindings.get_rna_type()
        bpy.ops.preferences.addon_disable(module=package)
        # Exercise extension-style namespaces without installing an extension.
        for parent in ('bl_ext', 'bl_ext.offline_validation'):
            if parent not in sys.modules:
                namespace = types.ModuleType(parent)
                namespace.__path__ = []
                sys.modules[parent] = namespace
        name = 'bl_ext.offline_validation.'+package_id
        source = Path(directory)/package/'__init__.py'
        spec = importlib.util.spec_from_file_location(name, source, submodule_search_locations=[str(source.parent)])
        extension = importlib.util.module_from_spec(spec)
        sys.modules[name] = extension
        spec.loader.exec_module(extension)
        extension.register()
        assert extension.generic_sequences.importer.addon_package_name(extension.generic_sequences.__package__) == name
        assert bpy.ops.import_scene.sqex_generic_unreal_sequence.get_rna_type()
        extension.unregister()
    print('GENERIC_PACKAGE_OK: version, bridge match, operators, reload, extension namespace, no local game data/keys/Oodle')


if __name__ == '__main__':
    main()
