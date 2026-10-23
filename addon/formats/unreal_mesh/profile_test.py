"""Read-only profile probes, polled on Blender's main thread without blocking UI."""

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import textwrap

import bpy

from ...core.bridge import gargoyle_command
from ...core.profiles import GamePaths, normalize_optional_input
from .session import make_profile


RESULTS = {}
_JOBS = {}


def configuration(preferences, profile):
    def absolute(value):
        return bpy.path.abspath(value) if value else ""

    paths = GamePaths(absolute(profile.game_path), absolute(preferences.oodle_dll),
                      absolute(normalize_optional_input(profile.usmap_path)), profile.aes_key)
    signature = hashlib.sha256(repr((paths, profile.game_version)).encode()).hexdigest()
    return paths, profile.game_version, signature


def running(profile_id):
    return profile_id in _JOBS


def _redraw():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            area.tag_redraw()


def draw_result(layout, result):
    box = layout.box()
    for message in result.get("messages", []):
        level = message.get("level", "INFO")
        column = box.column(align=True)
        column.alert = level == "ERROR"
        for index, line in enumerate(textwrap.wrap(message["text"], width=94)):
            column.label(text=line, icon=("ERROR" if level in {"ERROR", "WARNING"} else "INFO") if index == 0 else "NONE")


def _close(job):
    process = job["process"]
    if process.poll() is None:
        process.kill()
    process.wait()
    job["output"].close()
    job["directory"].cleanup()


def cancel(profile_id):
    job = _JOBS.pop(profile_id, None)
    if job is not None:
        _close(job)
    RESULTS.pop(profile_id, None)
    _redraw()


def _poll():
    for profile_id, job in list(_JOBS.items()):
        if job["process"].poll() is None:
            continue
        try:
            job["output"].seek(0)
            result = json.load(job["output"])
            if job["process"].returncode or not isinstance(result.get("messages"), list):
                raise ValueError("Unexpected profile test response")
        except (ValueError, OSError, AttributeError):
            # Do not display raw process output: third-party exceptions can
            # contain the configured AES key.
            result = {"success": False, "messages": [{"level": "ERROR", "text":
                "The profile test could not complete. Check that the bundled bridge is up to date and the packages are readable."}]}
        finally:
            _JOBS.pop(profile_id)
            _close(job)
        RESULTS[profile_id] = (job["signature"], result)
        _redraw()
    return 0.25 if _JOBS else None


def start(preferences, profile):
    paths, version, signature = configuration(preferences, profile)
    if not paths.install_root or not Path(paths.install_root).is_dir():
        raise ValueError("Choose a valid Game / Package Folder before testing the profile.")
    command = gargoyle_command(Path(__file__).resolve().parents[2], make_profile(version),
                               paths, "-", operation="generic-profile-test")
    directory = tempfile.TemporaryDirectory(prefix="talisman_profile_test_")
    output = None
    try:
        output = open(Path(directory.name) / "result.json", "w+b")
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=output,
                                   stderr=subprocess.DEVNULL,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        if output is not None:
            output.close()
        directory.cleanup()
        raise
    RESULTS.pop(profile.profile_id, None)
    _JOBS[profile.profile_id] = dict(process=process, output=output, directory=directory, signature=signature)
    if bpy.app.background:
        process.wait()
        _poll()
    elif not bpy.app.timers.is_registered(_poll):
        bpy.app.timers.register(_poll, first_interval=0.25)
    _redraw()


def unregister():
    if bpy.app.timers.is_registered(_poll):
        bpy.app.timers.unregister(_poll)
    for job in _JOBS.values():
        _close(job)
    _JOBS.clear()
    RESULTS.clear()
