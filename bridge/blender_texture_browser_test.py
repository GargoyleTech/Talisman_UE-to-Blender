"""Node/browser lifecycle, real subprocess scheduling, multiselect and packing; no game data."""

import importlib
from pathlib import Path
import shutil
import sys
import tempfile
import time

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
bpy.ops.preferences.addon_enable(module="addon")
import addon
from addon.ui import texture_browser as browser
from addon.formats.unreal_package import texture_browser as transport


def pump(predicate, timeout=15):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        browser.tick()
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("Texture browser did not reach the expected state: " + repr([(s.message, s.error, s.preview_message, s.preview_key, s.preview_due, s.preview_icon, list(s.preview_cache), s.session.pending if s.session else None) for s in browser._STATES.values()]))


def folder(node, path):
    assert bpy.ops.node.sqex_texture_browse(node_id=node.browser_id, directory=path) == {"FINISHED"}
    current = browser.state(node)
    pump(lambda: current.displayed_revision == current.browse_revision)


prefs = bpy.context.preferences.addons["addon"].preferences
prefs.texture_browser_last_game = "NONE"
prefs.oodle_dll = ""
original_command = transport.gargoyle_command
fixture = str(ROOT / "bridge/texture_browser_fixture.py")
python = shutil.which("python")
assert python
transport.gargoyle_command = lambda root, profile, paths, output, **options: [python, fixture, output]

with tempfile.TemporaryDirectory(prefix="texture_browser_test_") as directory:
    profile = prefs.generic_unreal_profiles.add()
    profile.profile_id, profile.name, profile.game_path = "browser_fixture", "a Browser Fixture", directory
    profile.game_version = "GAME_UE4_27"
    material = bpy.data.materials.new("Browser fixture")
    if bpy.app.version < (5, 0, 0):
        material.use_nodes = True
    tree = material.node_tree
    node = tree.nodes.new(browser.NODE_TYPE)
    assert node.game == "NONE" and node.image is None
    browser.touch(node)
    browser.tick()
    assert browser.state(node).session is None
    choices = browser.game_choices()
    assert choices[0] == ("NONE", " ")
    assert choices[1:] == sorted(choices[1:], key=lambda item: (item[1].casefold(), item[0]))
    assert all(any(key == "title:" + title.key for key, _name in choices) for title in addon.game_registry.SUPPORTED_PROFILES)
    node.game = "custom:browser_fixture"
    current = browser.state(node)
    pump(lambda: current.indexed and current.displayed_revision == current.browse_revision)
    assert current.indexing
    folder(node, "Fixture/Content/Textures")
    node.browser_entries[0].selected = True
    node.active_index = 0
    first = node.browser_entries[0].object_path
    pump(lambda: first in current.preview_cache)
    assert current.indexing  # Preview requests interleave with metadata indexing.
    pump(lambda: not current.indexing and current.displayed_revision == current.browse_revision)
    assert current.count == 263
    assert prefs.texture_browser_last_game == "custom:browser_fixture"
    folder(node, "")
    assert len(node.browser_entries) == 1 and node.browser_entries[0].is_directory
    folder(node, "Fixture/Content/Textures")
    assert len(node.browser_entries) == 128 and current.total == 260
    node.browser_entries[0].selected = True
    checked = node.browser_entries[0].object_path
    assert checked in current.selected
    assert bpy.ops.node.sqex_texture_page(node_id=node.browser_id, direction=1) == {"FINISHED"}
    pump(lambda: current.displayed_revision == current.browse_revision)
    node.browser_entries[0].selected = True
    assert len(current.selected) == 2
    assert bpy.ops.node.sqex_texture_selection(node_id=node.browser_id, mode="CLEAR") == {"FINISHED"}
    assert not current.selected
    folder(node, "Fixture/Content/Textures")
    # A delayed preview must never freeze polling, load a full Image, or replace a newer selection.
    node.active_index = 3
    image_count = len(bpy.data.images)
    pump(lambda: current.session.pending and current.session.pending[1][0] == "preview")
    obsolete = node.browser_entries[3].object_path
    node.active_index = 4
    newest = node.browser_entries[4].object_path
    start = time.monotonic()
    browser.tick()
    assert time.monotonic() - start < 0.1
    pump(lambda: newest in current.preview_cache)
    assert current.preview_key == newest and newest in current.preview_cache and obsolete not in current.preview_cache
    assert len(bpy.data.images) == image_count
    # Independent node state and a persisted preference for the next new node.
    other = tree.nodes.new(browser.NODE_TYPE)
    assert other.game == node.game and other.browser_id != node.browser_id
    assert not browser.state(other).selected and browser.state(other).session is None
    node.browser_entries[0].selected = True
    folder(node, "Fixture/Content/Other")
    node.browser_entries[0].selected = True
    node.browser_entries[1].selected = True
    node.browser_entries[2].selected = True
    assert len(current.selected) == 4
    assert bpy.ops.node.sqex_load_unreal_textures(node_id=node.browser_id) == {"FINISHED"}
    loaded = [item for item in tree.nodes if item.bl_idname == browser.NODE_TYPE and item.image]
    assert len(loaded) == 3
    assert all(tuple(item.image.size) == (32, 16) and item.image.packed_file for item in loaded)
    assert len({item.image["ue_virtual_path"] for item in loaded}) == 3
    assert all(item.node_tree.nodes["Unreal Image"].image == item.image for item in loaded)
    # Linked/unlinked Vector behavior, source persistence, copies, and addon reload.
    coordinates = tree.nodes.new("ShaderNodeTexCoord")
    link = tree.links.new(coordinates.outputs["UV"], node.inputs["Vector"])
    node.update()
    assert node.node_tree.nodes["Unreal Image"].inputs["Vector"].is_linked
    tree.links.remove(link)
    node.update()
    assert not node.node_tree.nodes["Unreal Image"].inputs["Vector"].is_linked
    clone = tree.nodes.new(browser.NODE_TYPE)
    clone.copy(node)
    clone.image = node.image
    assert clone.browser_id != node.browser_id and clone.node_tree != node.node_tree
    clone.interpolation = "Closest"
    assert node.node_tree.nodes["Unreal Image"].interpolation != clone.node_tree.nodes["Unreal Image"].interpolation
    profile.name = "z Renamed Fixture"
    assert node.game == "custom:browser_fixture"
    active_process = current.session.process
    node_name = node.name
    addon = importlib.reload(addon)
    addon.register()
    assert active_process.poll() is not None
    from addon.ui import texture_browser as browser
    assert not browser._STATES
    node = bpy.data.materials["Browser fixture"].node_tree.nodes[node_name]
    assert node.image and node.node_tree.nodes["Unreal Image"].image == node.image
    # Packed images survive removal of every disposable bridge image and save/reload.
    blend = str(Path(directory) / "browser.blend")
    material.use_fake_user = True
    bpy.ops.wm.save_as_mainfile(filepath=blend)
    bpy.ops.wm.open_mainfile(filepath=blend)
    material = bpy.data.materials["Browser fixture"]
    nodes = [item for item in material.node_tree.nodes if item.bl_idname == browser.NODE_TYPE and item.image]
    assert len(nodes) == 4 and all(item.image.packed_file and tuple(item.image.size) == (32, 16) for item in nodes)
    node = nodes[0]
    assert len(node.browser_entries) == 0
    node.game = "NONE"
    browser.tick()
    assert node.image is None and browser.state(node).session is None
    node.game_key = "custom:deleted_profile"
    assert node.game == "NONE"
    browser.touch(node)
    browser.tick()
    assert node.game_key == "NONE"
    node.game = "title:rebirth"
    browser.tick()
    assert node.game_key == "NONE"  # Missing game paths fall back to blank, never another profile.

addon.unregister()
print("TEXTURE_BROWSER_FIXTURE_OK")
