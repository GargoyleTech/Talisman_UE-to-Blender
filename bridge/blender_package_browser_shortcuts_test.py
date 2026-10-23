"""Exercise actual popup keyboard events; run without --background.

blender --factory-startup --enable-event-simulate --python <this file>
No game files or saved Blender preferences are required.
"""

from pathlib import Path
import sys
import traceback

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import addon
addon.register()

from addon.games import package_browser
from addon.formats.ue_map.package_importer import (
    MapBrowserState, PackageMapSource, make_package_map_importer,
)

PATHS = [f"Fixture/Content/Maps/Map{i}.umap" for i in range(1, 4)]
state = package_browser.make_state(
    "Fixture UMAPs", initial_directory="Fixture/Content/Maps", file_icon="WORLD",
)
source = PackageMapSource(
    "Fixture", lambda *args, **kwargs: MapBrowserState(state, PATHS, key="fixture"),
    lambda *args: {"FINISHED"},
)
dialog_class = make_package_map_importer(
    class_name="SQEX_OT_test_package_map_dialog", bl_idname="wm.sqex_test_package_map_dialog",
    source=source, module_name=__name__,
)
bpy.utils.register_class(dialog_class)

window = bpy.context.window
area = next(area for area in window.screen.areas if area.type == 'VIEW_3D')
main_region = next(region for region in area.regions if region.type == 'WINDOW')
browser = bpy.context.window_manager.sqex_package_asset_browser
pointer = (0, 0)


def move(x, y):
    global pointer
    pointer = (x, y)
    window.event_simulate(type='MOUSEMOVE', value='NOTHING', x=x, y=y)


def key(kind, *, text='', **modifiers):
    window.event_simulate(type=kind, value='PRESS', unicode=text, x=pointer[0], y=pointer[1], **modifiers)
    window.event_simulate(type=kind, value='RELEASE', x=pointer[0], y=pointer[1], **modifiers)


def active_path():
    region = package_browser._DIALOG_SESSION['region']
    with bpy.context.temp_override(window=window, area=area, region=region):
        prop = getattr(bpy.context, 'property', None)
    return prop[1] if prop else None


def open_dialog():
    move(650, 750)
    with bpy.context.temp_override(window=window, area=area, region=main_region):
        assert bpy.ops.wm.sqex_test_package_map_dialog('INVOKE_DEFAULT') == {'RUNNING_MODAL'}


def run():
    open_dialog()
    yield 0.5
    region = package_browser._DIALOG_SESSION['region']
    assert region is not None
    x = region.x + region.width // 2
    list_y, search_y = [], []
    # Find real controls through Blender's hovered-property context, so the
    # fixture works at different window sizes and display scaling settings.
    for y in range(region.y + 30, region.y + region.height - 30, 8):
        move(x, y)
        yield 0.02
        path = active_path()
        if path == 'sqex_package_asset_browser.active_index':
            list_y.append(y)
        elif path == 'sqex_package_asset_browser.filter_text':
            search_y.append(y)
    assert list_y and search_y, (list_y, search_y)
    row_y = max(list_y) - 4
    move(x, row_y)
    yield 0.1
    assert browser.active_index == 0
    key('SPACE')
    yield 0.1
    assert state['selected'] == {PATHS[0]}, state['selected']
    key('SPACE')
    yield 0.1
    assert not state['selected']
    key('DOWN_ARROW')
    yield 0.1
    assert browser.active_index == 1
    key('SPACE')
    yield 0.1
    assert state['selected'] == {PATHS[1]}, state['selected']
    assert browser.active_index == 1
    # Moving onto another row must still toggle the highlighted row.
    move(x, min(list_y) + 4)
    yield 0.1
    key('SPACE')
    yield 0.1
    assert not state['selected'] and browser.active_index == 1

    binding = package_browser._DIALOG_SESSION['select_all_events'][0]
    key(binding[0], shift=bool(binding[3]), ctrl=bool(binding[4]), alt=bool(binding[5]), oskey=bool(binding[6]))
    yield 0.1
    assert state['selected'] == set(PATHS)

    move(region.x - 20, region.y + region.height // 2)
    yield 0.1
    key('SPACE')
    yield 0.1
    assert state['selected'] == set(PATHS)

    # Search retains spaces after the pointer moves back over the map list.
    move(x, sum(search_y) // len(search_y))
    yield 0.1
    key('LEFTMOUSE')
    yield 0.1
    move(x, row_y)
    yield 0.1
    key('SPACE', text=' ')
    key('A', text='a')
    yield 0.1
    assert browser.filter_text == ' a', repr(browser.filter_text)
    assert state['selected'] == set(PATHS)
    key('ESC')
    yield 0.1
    key('ESC')
    yield 0.1
    assert package_browser._DIALOG_SESSION is None
    assert not bpy.ops.wm.sqex_package_asset_toggle_highlighted.poll()
    assert not any(op.bl_idname == 'WM_OT_sqex_package_asset_dialog_shortcuts' for op in window.modal_operators)

    # Reopening and confirming must release the listener as well.
    open_dialog()
    yield 0.2
    key('RET')
    yield 0.2
    assert package_browser._DIALOG_SESSION is None
    print('PACKAGE_BROWSER_SHORTCUTS_OK', bpy.app.version_string, flush=True)


steps = run()


def tick():
    try:
        return next(steps)
    except StopIteration:
        bpy.ops.wm.quit_blender()
    except Exception:
        traceback.print_exc()
        print('PACKAGE_BROWSER_SHORTCUTS_FAILED', flush=True)
        bpy.ops.wm.quit_blender()


bpy.app.timers.register(tick, first_interval=1.0)
