"""Graphical layout and preview smoke test; launch in a disposable factory Blender."""

from pathlib import Path
import shutil
import sys
import tempfile
import time
import traceback

import bpy

bpy.context.preferences.view.show_splash = False

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
bpy.ops.preferences.addon_enable(module="addon")
import addon
from addon.ui import texture_browser as browser
from addon.formats.unreal_package import texture_browser as transport

temporary = tempfile.TemporaryDirectory(prefix="texture_browser_ui_")
transport.gargoyle_command = lambda root, profile, paths, output, **options: [
    shutil.which("python"), str(ROOT / "bridge/texture_browser_fixture.py"), output]
prefs = bpy.context.preferences.addons["addon"].preferences
prefs.texture_browser_last_game = "NONE"
prefs.oodle_dll = ""
profile = prefs.generic_unreal_profiles.add()
profile.profile_id, profile.name, profile.game_path = "browser_ui_fixture", "Browser Fixture", temporary.name
profile.game_version = "GAME_UE4_27"
material = bpy.data.materials.new("Unreal Engine Texture Browser")
if bpy.app.version < (5, 0, 0):
    material.use_nodes = True
bpy.context.object.active_material = material
area = next(area for area in bpy.context.screen.areas if area.type == "VIEW_3D")
area.type = "NODE_EDITOR"
area.ui_type = "ShaderNodeTree"
area.spaces.active.shader_type = "OBJECT"
area.spaces.active.show_region_ui = False
tree = material.node_tree
tree.nodes.clear()
node = tree.nodes.new(browser.NODE_TYPE)
node.location = (0, 0)
node.select = True
tree.nodes.active = node
node.game = "custom:browser_ui_fixture"
current = browser.state(node)
stage = 0
started = time.monotonic()
deadline = 0


def step():
    global stage, deadline, node, current
    try:
        if time.monotonic() - started > 30:
            raise AssertionError("Graphical browser test timed out: " + current.message)
        browser.touch(node)
        if current.error:
            raise AssertionError(current.message)
        if stage == 0 and current.indexed:
            bpy.ops.node.sqex_texture_browse(node_id=node.browser_id, directory="Fixture/Content/Textures")
            stage = 1
        elif stage == 1 and current.displayed_revision == current.browse_revision:
            node.browser_entries[0].selected = True
            node.browser_entries[2].selected = True
            node.active_index = 1
            stage = 2
        elif stage == 2 and current.preview_icon:
            region = next(region for region in area.regions if region.type == "WINDOW")
            with bpy.context.temp_override(area=area, region=region):
                bpy.ops.node.view_selected()
            deadline = time.monotonic() + 1
            stage = 3
        elif stage == 3 and time.monotonic() > deadline:
            output = ROOT / ".local" / ("texture-browser-ui-" + str(bpy.app.version[0]) + ".png")
            bpy.ops.screen.screenshot(filepath=str(output))
            print("TEXTURE_BROWSER_UI_OK", output, flush=True)
            region = next(region for region in area.regions if region.type == "WINDOW")
            with bpy.context.temp_override(area=area, region=region):
                bpy.ops.ed.undo_push(message="Before texture batch")
                assert bpy.ops.node.sqex_load_unreal_textures(node_id=node.browser_id) == {"RUNNING_MODAL"}
            stage = 4
        elif stage == 4 and current.batch is None:
            loaded = [item for item in tree.nodes if item.bl_idname == browser.NODE_TYPE and item.image]
            assert len(loaded) == 2 and all(item.image.packed_file for item in loaded)
            region = next(region for region in area.regions if region.type == "WINDOW")
            with bpy.context.temp_override(area=area, region=region):
                assert bpy.ops.ed.undo() == {"FINISHED"}
                restored = bpy.data.materials["Unreal Engine Texture Browser"].node_tree
                assert not any(item.image for item in restored.nodes if item.bl_idname == browser.NODE_TYPE)
                assert bpy.ops.ed.redo() == {"FINISHED"}
            restored = bpy.data.materials["Unreal Engine Texture Browser"].node_tree
            assert sum(bool(item.image) for item in restored.nodes if item.bl_idname == browser.NODE_TYPE) == 2
            print("TEXTURE_BROWSER_MODAL_UNDO_OK", flush=True)
            addon.unregister()
            temporary.cleanup()
            bpy.ops.wm.quit_blender()
            return None
        return 0.1
    except Exception:
        traceback.print_exc()
        addon.unregister()
        temporary.cleanup()
        bpy.ops.wm.quit_blender()
        return None


bpy.app.timers.register(step, first_interval=0.5)
