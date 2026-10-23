"""Index, preview, import, and restart actual game browsers without saving preferences.

blender --background --factory-startup --python-exit-code 1 --python THIS --
  --config IGNORED_JSON --game CONFIG_ENTRY [--bridge BUILT_EXE] [--report OUTPUT_JSON]
Config entries use root, profile (title key) or version (generic), optional oodle/usmap/key/texture.
"""

import argparse
import json
from pathlib import Path
import sys
import time

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
parser = argparse.ArgumentParser()
parser.add_argument("--config", required=True)
parser.add_argument("--game", required=True)
parser.add_argument("--bridge")
parser.add_argument("--report")
parser.add_argument("--direct", action="store_true", help="Check a configured texture directly, without waiting for a complete index")
parser.add_argument("--finish-index", action="store_true", help="Also wait for a complete persistent index")
args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
config = json.loads(Path(args.config).read_text())[args.game]
bpy.ops.preferences.addon_enable(module="addon")
import addon
from addon.ui import texture_browser as browser
from addon.formats.unreal_package import texture_browser as transport

original_poll = transport.TextureBrowserSession.poll
def diagnostic_poll(self):
    result = original_poll(self)
    if result and not result[1].get("ok"):
        print("BROWSER_REQUEST_FAILURE", result[0][0], result[1].get("errorType", "unknown"), flush=True)
    return result
transport.TextureBrowserSession.poll = diagnostic_poll

prefs = bpy.context.preferences.addons["addon"].preferences
prefs.oodle_dll = config.get("oodle") or str(ROOT / ".local/oodle/oo2core_7_win64.dll")
prefs.texture_browser_last_game = "NONE"
if config.get("profile"):
    profile = addon.game_registry.PROFILE_BY_KEY[config["profile"]]
    setattr(prefs, profile.install_root_property, config["root"])
    if profile.usmap_property:
        setattr(prefs, profile.usmap_property, config.get("usmap", ""))
    if profile.aes_key_property:
        setattr(prefs, profile.aes_key_property, config.get("key", ""))
    key = "title:" + profile.key
else:
    profile = prefs.generic_unreal_profiles.add()
    profile.profile_id, profile.name = "browser_live_test", args.game
    profile.game_path, profile.game_version = config["root"], config["version"]
    profile.aes_key, profile.usmap_path = config.get("key", ""), config.get("usmap", "")
    key = "custom:" + profile.profile_id
browser.cache_root = lambda: str(ROOT / ".local/texture-browser-cache")
if args.bridge:
    original = transport.gargoyle_command
    def command(*values, **options):
        result = original(*values, **options)
        result[0] = str(Path(args.bridge).resolve())
        return result
    transport.gargoyle_command = command

if args.direct:
    from addon.core.blender.material_nodes import load_packed_image
    profile, paths = browser.configuration(key)
    session = transport.TextureBrowserSession(profile, paths, browser.cache_root())
    try:
        until = time.monotonic() + 180
        while not session.ready and time.monotonic() < until:
            session.poll()
            time.sleep(0.05)
        assert session.ready
        sizes = []
        for action in ("preview", "texture"):
            session.send((action,), action=action, assetPath=config["texture"], objectPath=config["texture"])
            result = None
            while result is None and time.monotonic() < until:
                result = session.poll()
                time.sleep(0.02)
            assert result and result[1].get("ok"), result
            info = result[1]["payload"]
            image = load_packed_image(info["output"], "Direct " + action)
            sizes.append(tuple(image.size))
            assert image.packed_file and min(image.size) > 0
            if action == "preview":
                assert max(image.size) <= 384
                assert all(alpha > 0.99 for alpha in image.pixels[:][3::4])
            bpy.data.images.remove(image)
        report = {"game": args.game, "previewSize": sizes[0], "fullSize": sizes[1]}
        if args.report:
            Path(args.report).write_text(json.dumps(report, indent=2))
        print("TEXTURE_BROWSER_DIRECT_OK", json.dumps(report), flush=True)
    finally:
        session.close()
        addon.unregister()
    raise SystemExit(0)

material = bpy.data.materials.new("Texture browser game test")
if bpy.app.version < (5, 0, 0):
    material.use_nodes = True
node = material.node_tree.nodes.new(browser.NODE_TYPE)
node.game = key
current = browser.state(node)
poll_max = 0

def pump(predicate, timeout=1200):
    global poll_max
    start = last_report = time.monotonic()
    while time.monotonic() - start < timeout:
        before = time.monotonic()
        browser.touch(node)
        browser.tick()
        poll_max = max(poll_max, time.monotonic() - before)
        if current.error or node.game_key == "NONE":
            raise AssertionError(current.message or node.browser_message)
        if predicate():
            return time.monotonic() - start
        if time.monotonic() - last_report > 15:
            print("BROWSER_PROGRESS", args.game, current.message, flush=True)
            last_report = time.monotonic()
        time.sleep(0.05)
    raise AssertionError("Texture browser operation timed out")

try:
    index_seconds = pump(lambda: current.indexed and current.count > 0 and current.displayed_revision == current.browse_revision)
    assert current.count > 0
    node.search = config.get("texture", "").split(".")[0].split("/")[-1] or "texture"
    pump(lambda: current.displayed_revision == current.browse_revision and
         (any(not item.is_directory for item in node.browser_entries) or not current.indexing))
    if not any(not item.is_directory for item in node.browser_entries):
        node.search = ""
        pump(lambda: current.displayed_revision == current.browse_revision)
        while node.browser_entries and all(item.is_directory for item in node.browser_entries):
            bpy.ops.node.sqex_texture_browse(node_id=node.browser_id, directory=node.browser_entries[0].virtual_path)
            pump(lambda: current.displayed_revision == current.browse_revision)
    entry = next(item for item in node.browser_entries if not item.is_directory)
    name = entry.display_name
    node.active_index = next(index for index, item in enumerate(node.browser_entries) if item == entry)
    pump(lambda: current.preview_key in current.preview_cache or
         current.preview_message not in {"Loading preview…", "Select a texture to preview"}, timeout=180)
    assert current.preview_key in current.preview_cache, current.preview_message
    preview_path = current.preview_cache[current.preview_key][1]["output"]
    preview = bpy.data.images.load(preview_path, check_existing=False)
    preview_size = tuple(preview.size)
    bpy.data.images.remove(preview)
    assert 0 < max(preview_size) <= 384
    assert node.image is None
    entry.selected = True
    assert bpy.ops.node.sqex_load_unreal_textures(node_id=node.browser_id) == {"FINISHED"}
    assert node.image is not None and node.image.packed_file
    full_size = tuple(node.image.size)
    assert all(full >= thumb for full, thumb in zip(full_size, preview_size))
    if args.finish_index:
        pump(lambda: not current.indexing)
    report = {"game": args.game, "count": current.count, "indexSeconds": index_seconds,
              "indexComplete": not current.indexing, "texture": name, "previewSize": preview_size,
              "fullSize": full_size, "maxPollSeconds": poll_max}
    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2))
    print("TEXTURE_BROWSER_GAME_OK", json.dumps(report), flush=True)
finally:
    addon.unregister()
