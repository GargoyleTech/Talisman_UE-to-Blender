"""Run with Blender --background --factory-startup --python this_file.

Checks real RNA hover descriptions, dynamic operators, generated material/rig
properties, extension package names, and edited catalog reloads without game data.
"""

import importlib
import importlib.util
from pathlib import Path
import shutil
import sys
import tempfile

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import addon
from addon.language import strings


def check_registered_descriptions():
    # Registration needs no game or bridge process for this tooltip fixture.
    addon.generic_unreal_importer._VERSION_ITEMS[:] = [
        ("GAME_UE4_26", "UE4_26", "GAME_UE4_26", 0x041A0000),
        ("GAME_UE4_27", "UE4_27", "GAME_UE4_27", 0x041B0000),
        ("GAME_HogwartsLegacy", "HogwartsLegacy", "GAME_HogwartsLegacy", 0x041B0003),
    ]
    addon.generic_unreal_importer._VERSIONS_LOADED = True
    addon.register()
    rebirth = addon.game_packages
    def rna(cls):
        category, name = cls.bl_idname.split(".")
        return getattr(getattr(bpy.ops, category), name).get_rna_type()

    static = rna(rebirth.FF7R_REBIRTH_OT_import_static_mesh_game_packages)
    skeletal = rna(rebirth.FF7R_REBIRTH_OT_import_skeletal_mesh_game_packages)
    skeleton = rna(rebirth.FF7R_REBIRTH_OT_import_skeleton_game_packages)
    assert static.description == strings.REBIRTH_STATIC_MESH_DESCRIPTION
    assert static.properties["scale_factor"].description == strings.SHARED_SCALE_FACTOR
    for cls in (static, skeletal):
        prop = cls.properties["offset_opposite_faces"]
        assert prop.description == strings.SHARED_OFFSET_OPPOSITE_FACES
        assert prop.enum_items["BAKED"].description == strings.SHARED_OFFSET_FACES_BAKED
    assert skeletal.properties["attachment_sockets"].description == strings.SHARED_SKELETAL_ATTACHMENT_SOCKETS
    assert skeleton.properties["attachment_sockets"].description == strings.REBIRTH_SKELETAL_MESH_ATTACHMENT_SOCKETS
    remake = rna(addon.remake_static_mesh.FF7R_REMAKE_OT_import_static_mesh_game_packages)
    assert "Remake" in remake.description
    assert "{definition_" not in remake.description

    # Inapplicable legacy properties stay hidden; shared UE4 properties have
    # the same tooltip in the generic importer and every title.
    generic = rna(addon.generic_unreal_importer.SQEX_OT_import_generic_unreal_skeletal_mesh)
    assert generic.properties["import_kdi"].is_hidden
    assert generic.properties["attachment_sockets"].description == strings.SHARED_SKELETAL_ATTACHMENT_SOCKETS
    assert rna(addon.ui_preferences.SQEX_OT_reset_generic_unreal_profile).description == strings.PREFERENCES_RESET_GENERIC_PROFILE


def check_generated_properties():
    # Material builders are loaded by file path, rather than normal imports.
    masters, _variant, _truth = addon.rmi_surface._module_set()
    for profile, builder in masters.items():
        material = bpy.data.materials.new("TooltipFixture_" + profile)
        builder._ensure_props(material)
        assert material.id_properties_ui("Shading Model").as_dict()["description"] == (
            strings.MATERIALS_SHADING_MODEL
        )
        name, members, _default = builder.SWITCH_CONTROLS[0]
        expected = (strings.MATERIALS_STATIC_SWITCH if len(members) == 1 else
                    strings.MATERIALS_GROUPED_STATIC_SWITCH_PREFIX + " + ".join(members))
        assert material.id_properties_ui(name).as_dict()["description"] == expected
        bpy.data.materials.remove(material)

    obj = bpy.data.objects.new("TooltipRigFixture", None)
    addon.mouth_rig._property(obj, "influence", 1.0, strings.SCENE_TOOLS_INFLUENCE)
    assert obj.id_properties_ui("influence").as_dict()["description"] == (
        strings.SCENE_TOOLS_INFLUENCE
    )
    bpy.data.objects.remove(obj)


def check_catalog_reload():
    # A different package name models installed extensions without importing bpy.
    # Work on a temporary copy so this never edits the user's language files.
    package = "tooltip_fixture_language"
    with tempfile.TemporaryDirectory(prefix="talisman-language-") as directory:
        destination = Path(directory) / package
        shutil.copytree(ROOT / "addon" / "language", destination,
                        ignore=shutil.ignore_patterns("__pycache__"))
        spec = importlib.util.spec_from_file_location(package, destination / "__init__.py")
        language = importlib.util.module_from_spec(spec)
        sys.modules[package] = language
        spec.loader.exec_module(language)
        master = importlib.import_module(package + ".strings")
        consumer = master
        category = destination / "tooltip_import.py"
        with category.open("a", encoding="utf-8") as output:
            output.write('\nSHARED_SCALE_FACTOR = "Edited translation fixture"\n')
        importlib.invalidate_caches()
        importlib.reload(master)
        assert consumer.SHARED_SCALE_FACTOR == "Edited translation fixture"
    for name in list(sys.modules):
        if name == package or name.startswith(package + "."):
            del sys.modules[name]


try:
    check_registered_descriptions()
    check_generated_properties()
    check_catalog_reload()
    importlib.reload(addon)
    check_registered_descriptions()
    check_generated_properties()
    print("LANGUAGE_TOOLTIPS_PASS: RNA, shared choices, dynamic menus, materials, reload")
finally:
    addon.unregister()
