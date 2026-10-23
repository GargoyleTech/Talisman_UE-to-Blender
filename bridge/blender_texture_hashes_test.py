"""Blender --background --factory-startup --python bridge/blender_texture_hashes_test.py"""

import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import addon
from addon.formats.mec import material, texture_hashes
from addon.ui import preferences


class Process:
    def __init__(self, returncode=0):
        self.returncode = returncode
        self.killed = False

    def poll(self):
        return self.returncode

    def wait(self):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9


addon.register()
assert bpy.ops.preferences.sqex_generate_rebirth_texture_hashes.get_rna_type().description
assert not (ROOT / "addon/formats/mec/texture_hashes.csv").exists()
assert not texture_hashes.running()

with tempfile.TemporaryDirectory(prefix="hash-test-", dir=ROOT / ".local") as temporary:
    root = Path(temporary)
    target = root / "userdata" / "texture_hashes.csv"
    prefs = SimpleNamespace(rebirth_install_root=str(root), rebirth_usmap_path=str(root / "mapping.usmap"),
                            oodle_dll=str(root / "oodle.dll"))
    Path(prefs.rebirth_usmap_path).touch()
    Path(prefs.oodle_dll).touch()
    with patch.object(texture_hashes, "cache_path", return_value=target), \
            patch.object(preferences, "_addon_preferences", return_value=prefs):
        material.load_hash_table()
        assert material.resolve_hash("7B17921F50C10AAA") is None
        assert not target.exists()  # Reading/importing never starts generation.

        def success(command, **kwargs):
            assert command[10:12] == ["rebirth-texture-hashes", "rebirth"]
            assert command[1] == str(root)
            assert command[6] == prefs.rebirth_usmap_path
            Path(command[2]).write_text(
                "/Game/Environment/Athletic/Texture/T_BaseTexture_Athletic_A,7B17921F50C10AAA\n")
            kwargs["stdout"].write((json.dumps(dict(textureHashes=True, complete=True, count=1, failures=0)) + "\n").encode())
            kwargs["stdout"].flush()
            return Process()

        with patch.object(texture_hashes.subprocess, "Popen", side_effect=success):
            assert bpy.ops.preferences.sqex_generate_rebirth_texture_hashes() == {"FINISHED"}
        assert not texture_hashes.running()
        assert "Generated 1" in texture_hashes.STATUS
        assert material.resolve_hash("7b17921f50c10aaa").endswith("T_BaseTexture_Athletic_A")
        previous = target.read_bytes()

        with patch.object(texture_hashes.subprocess, "Popen", return_value=Process(1)):
            texture_hashes.start(prefs)
        assert "Generation failed" in texture_hashes.STATUS
        assert target.read_bytes() == previous
        assert not list(target.parent.glob("generating-*"))

        # Pending jobs keep the previous cache during progress, cancellation and reload.
        def pending_job():
            directory = tempfile.TemporaryDirectory(dir=target.parent)
            log = Path(directory.name) / "progress.jsonl"
            log.write_text(json.dumps(dict(textureHashes=True, scanned=5, total=10, count=2)) + "\n")
            process = Process(None)
            texture_hashes._job = dict(process=process, directory=directory, output=open(log, "ab"),
                                      log=log, csv=Path(directory.name) / "cache.csv", target=target, position=0)
            return process, Path(directory.name)

        process, directory = pending_job()
        assert texture_hashes._poll() == 0.25
        assert "5 / 10" in texture_hashes.STATUS
        assert bpy.ops.preferences.sqex_generate_rebirth_texture_hashes() == {"FINISHED"}
        assert process.killed and not directory.exists()
        assert target.read_bytes() == previous

        process, directory = pending_job()
        addon.unregister()
        assert process.killed and not directory.exists() and not texture_hashes.running()
        material.load_hash_table()
        assert material.resolve_hash("7B17921F50C10AAA") is not None
        assert target.read_bytes() == previous

print("REBIRTH_TEXTURE_HASH_CACHE_OK: optional loading, operator, progress, success, failure, cancel, unregister")
