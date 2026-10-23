"""Real FNaF rect-light operator and text/default checks using ignored config.

Blender --background --factory-startup --python-exit-code 1 --python this_file
  -- --config .local/generic-test-games.json [--output .local/rect-text-live.json]
"""
import argparse
import json
import math
from pathlib import Path
import sys

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import addon
bpy.ops.preferences.addon_enable(module="addon")
from addon.core.profiles import GamePaths
from addon.formats.unreal_mesh.session import GenericSession
from addon.formats.ue_map import lights, map_import
from addon.ui.preferences import ensure_generic_unreal_profiles

parser = argparse.ArgumentParser()
parser.add_argument("--config", required=True)
parser.add_argument("--output")
args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
config = json.loads(Path(args.config).read_text())
prefs = bpy.context.preferences.addons["addon"].preferences
profiles = ensure_generic_unreal_profiles(prefs)
reports = []
cases = {
    "security_breach": ("MAP_Night_03.umap", "MAP_NightLighting.umap", "MAP_Doors.umap"),
    "secret_of_the_mimic": ("MAP_L_14.umap", "MAP_AdminBasement_Gameplay_3.umap", "MAP_MainHall_North_Gameplay_2.umap"),
}
for game, names in cases.items():
    settings = config[game]
    paths = GamePaths(settings["root"], settings.get("oodle") or str(ROOT / ".local/oodle/oo2core_7_win64.dll"),
                      settings.get("usmap", ""), settings.get("key", ""))
    profile = profiles.add()
    profile.profile_id = "rect_text_fixture_" + game
    profile.name = profile.profile_id
    profile.game_path, profile.game_version = paths.install_root, settings["version"]
    profile.usmap_path, profile.aes_key = paths.usmap_path, paths.aes_key
    prefs.oodle_dll = paths.oodle_dll
    with GenericSession(paths, settings["version"], import_textures=False) as mounted:
        index = mounted.request({"action": "umap_index"})["umaps"]
        selected = [next(path for path in index if Path(path).name == name) for name in names]
        payloads = [mounted.umap_actors(path) for path in selected]
    light_path, blueprint_path, text_path = selected
    light_payload, blueprint_payload, text_payload = payloads
    expected = [entry for entry in light_payload["actors"] if entry["Type"] == "RectLightComponent"]
    assert expected
    before = set(bpy.data.objects)
    assert bpy.ops.import_scene.sqex_generic_unreal_umap(
        cue4parse_profile=profile.profile_id, virtual_path=light_path, import_models=False,
        import_textures=False, import_point_lights=False, import_spot_lights=False,
        import_rect_lights=True, import_light_probes=False, exposure=1.0,
    ) == {"FINISHED"}
    objects = set(bpy.data.objects) - before
    areas = [obj for obj in objects if obj.type == "LIGHT"]
    assert len(areas) == len(expected) and all(obj.data.type == "AREA" for obj in areas)
    by_path = {obj.get("ue_component_path"): obj for obj in areas}
    for entry in expected:
        props = entry["Properties"]
        key = entry["Outer"]["ObjectPath"] + "." + entry["Name"]
        obj = by_path[key]
        assert math.isclose(obj.data.size, props["SourceWidth"] * 0.01, rel_tol=1e-5)
        assert math.isclose(obj.data.size_y, props["SourceHeight"] * 0.01, rel_tol=1e-5)
        from addon.formats.ue_map.light_photometry import radiant_power
        expected_power = radiant_power('AREA', props['Intensity'], props.get('IntensityUnits', 'Unitless'),
                                       exposure=2, width=obj.data.size, height=obj.data.size_y)
        assert math.isclose(obj.data.energy, expected_power, rel_tol=1e-5)
        assert obj.get("ue_source_id") and obj.parent
    # These authored Blueprint components omit their area dimensions/intensity
    # on the map instance. The bridge must expose the inherited values.
    blueprint_rects = [entry for entry in blueprint_payload["actors"] if entry["Type"] == "RectLightComponent"]
    first = next(entry for entry in blueprint_rects if entry["Name"] == "RectLight")
    props = first["Properties"]
    width, height, power = (225.45143, 22.985443, 250.0) if game == "security_breach" else (45.0, 30.0, 0.2)
    assert math.isclose(props["SourceWidth"], width, rel_tol=1e-5), props
    assert math.isclose(props["SourceHeight"], height, rel_tol=1e-5), props
    assert math.isclose(props["Intensity"], power, rel_tol=1e-5), props
    # Keep all authored attachment transforms, and use empty parents in this
    # focused text check so no mesh/material assets need to be reconstructed.
    text_entries = [entry for entry in text_payload["actors"] if entry["Type"] == "TextRenderComponent"]
    assert text_entries and all(isinstance(entry["Properties"].get("Text"), str) for entry in text_entries)
    transforms = [dict(entry, Type="SceneComponent", Properties={
        key: value for key, value in entry["Properties"].items()
        if key.startswith("Relative") or key in {"AttachParent", "AttachSocketName"}
    }) for entry in text_payload["actors"] if entry["Type"] != "TextRenderComponent"]
    before = set(bpy.data.objects)
    map_import.import_map_entries([*text_entries, *transforms], text_path, 1, 1,
        import_lights=False, import_reflection_probes=False, game_features=False)
    fonts = [obj for obj in set(bpy.data.objects) - before if obj.type == "FONT"]
    assert len(fonts) == len(text_entries)
    assert all(obj.data.body and obj.data.size > 0 for obj in fonts)
    if game == "security_breach":
        assert all(obj.hide_render for obj in fonts)
    else:
        assert any(not obj.hide_render for obj in fonts)
    report = {"game": game, "areaMap": light_path, "areaLights": len(areas),
              "inheritedAreaDimensions": [width, height], "textMap": text_path,
              "editableTextObjects": len(fonts), "hiddenTextObjects": sum(obj.hide_render for obj in fonts)}
    reports.append(report)
    print("RECT_TEXT_REAL_GAME", json.dumps(report), flush=True)
if args.output:
    Path(args.output).write_text(json.dumps(reports, indent=2))
addon.unregister()
print("RECT_TEXT_REAL_GAME_OK")
