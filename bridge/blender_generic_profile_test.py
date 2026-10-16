"""Blender --background --factory-startup --python this_file [-- --config ignored.json].

The optional game config uses the same private schema as blender_generic_unreal_test.py.
Never print local keys or put game configuration in this source file.
"""

import argparse
import json
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from addon.formats.unreal_mesh import profile_test
from addon.ui import preferences as ui


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    bpy.ops.preferences.addon_enable(module="addon")
    preferences = bpy.context.preferences.addons["addon"].preferences
    profile = preferences.generic_unreal_profiles.add()
    profile.profile_id = "profile_test_fixture"
    profile.name = "Profile Test Fixture"
    profile.game_version = "GAME_UE4_27"
    before = set(bpy.data.objects)

    def probe(**settings):
        for name, value in settings.items():
            setattr(profile, name, value)
        assert bpy.ops.preferences.sqex_test_generic_unreal_profile(profile_id=profile.profile_id) == {"FINISHED"}
        signature, result = profile_test.RESULTS[profile.profile_id]
        assert signature == profile_test.configuration(preferences, profile)[2]
        assert not profile_test.running(profile.profile_id)
        assert set(bpy.data.objects) == before
        return result

    with tempfile.TemporaryDirectory() as directory:
        bad_mapping = Path(directory) / "bad.usmap"
        bad_mapping.write_bytes(b"Not a mapping file")
        # Valid format with one deliberately unrelated, empty struct. A
        # versioned mesh must not cause this mapping to be called compatible.
        valid_mapping = Path(directory) / "unrelated.usmap"
        name = b"UnrelatedFixture"
        payload = (struct.pack("<I", 1) + bytes([len(name)]) + name +
                   struct.pack("<IIiiHH", 0, 1, 0, -1, 0, 0))
        valid_mapping.write_bytes(struct.pack("<HBBII", 0x30C4, 0, 0, len(payload), len(payload)) + payload)
        profile.game_path = directory
        result = probe(aes_key="bad-key", usmap_path=str(bad_mapping))
        assert not result["success"]
        assert result["aesStatus"] == "invalid_format"
        assert result["mappingsStatus"] == "invalid"
        old_signature = profile_test.RESULTS[profile.profile_id][0]
        profile.aes_key = ""
        assert old_signature != profile_test.configuration(preferences, profile)[2]
        result = probe(aes_key="", usmap_path=str(Path(directory) / "missing.usmap"))
        assert result["mappingsStatus"] == "invalid"
        result = probe(usmap_path=str(valid_mapping))
        assert result["mappingsStatus"] == "loaded"
        (Path(directory) / "broken.pak").write_bytes(b"Not a package container")
        result = probe(usmap_path="")
        assert not result["success"] and result["mount"]["mountedVfsCount"] == 0

        # Verify the editor routes the button to the displayed profile, even
        # when another profile is remembered as active; drawing is read-only.
        controls = []
        class Layout:
            def row(self, **kwargs): return self
            def column(self, **kwargs): return self
            def box(self): return self
            def prop(self, *args, **kwargs): pass
            def label(self, **kwargs): pass
            def operator(self, name, **kwargs):
                control = SimpleNamespace(name=name)
                controls.append(control)
                return control
        preferences.generic_unreal_active_profile = preferences.generic_unreal_profiles[0].profile_id
        original = profile.as_pointer(), len(preferences.generic_unreal_profiles)
        ui.SQEX_OT_edit_generic_unreal_profiles.draw(
            SimpleNamespace(layout=Layout(), profile_id=profile.profile_id), bpy.context)
        test = next(control for control in controls if control.name == ui.SQEX_OT_test_generic_unreal_profile.bl_idname)
        assert test.profile_id == profile.profile_id
        assert original == (profile.as_pointer(), len(preferences.generic_unreal_profiles))

        if args.config:
            games = json.loads(Path(args.config).read_text())
            for name, game in games.items():
                preferences.oodle_dll = game.get("oodle") or str(ROOT / ".local/oodle/oo2core_7_win64.dll")
                result = probe(game_path=game["root"], game_version=game["version"],
                               aes_key=game.get("key", ""), usmap_path=game.get("usmap", ""))
                assert result["success"] and result["sample"].endswith(".uasset"), name
                if game.get("key"):
                    result = probe(aes_key="")
                    assert result["aesStatus"] == "required", name
                    result = probe(aes_key="0x" + "01" * 32)
                    assert result["aesStatus"] == "rejected", name
                    result = probe(aes_key="malformed-key", usmap_path=str(bad_mapping))
                    assert result["aesStatus"] == "invalid_format" and result["mappingsStatus"] == "invalid"
                result = probe(aes_key=game.get("key", ""), usmap_path=str(bad_mapping))
                assert result["success"] and result["mappingsStatus"] == "invalid", name
                result = probe(usmap_path=str(valid_mapping))
                assert result["success"] and result["mappingsStatus"] == "loaded", name
                assert "still unverified" in " ".join(message["text"] for message in result["messages"])
                print("PROFILE_TEST_GAME_OK", name)

    # Exercise polling, cancellation, and disable/reload cleanup independently
    # of scan duration, including result JSON that cannot be decoded.
    class Process:
        def __init__(self): self.returncode = None
        def poll(self): return self.returncode
        def kill(self): self.returncode = -1
        def wait(self): return self.returncode

    def job():
        directory = tempfile.TemporaryDirectory()
        output = open(Path(directory.name) / "result", "w+b")
        return dict(process=Process(), output=output, directory=directory, signature="fixture")

    first = job()
    profile_test._JOBS[profile.profile_id] = first
    assert profile_test._poll() == 0.25
    assert bpy.ops.preferences.sqex_test_generic_unreal_profile(profile_id=profile.profile_id) == {"FINISHED"}
    assert first["process"].returncode == -1 and first["output"].closed
    assert not Path(first["directory"].name).exists()

    failed = job()
    failed["process"].returncode = 1
    profile_test._JOBS[profile.profile_id] = failed
    assert profile_test._poll() is None
    assert not profile_test.RESULTS[profile.profile_id][1]["success"]
    assert failed["output"].closed

    last = job()
    profile_test._JOBS[profile.profile_id] = last
    import addon
    addon.unregister()
    assert not profile_test._JOBS and not profile_test.RESULTS
    assert last["process"].returncode == -1 and last["output"].closed
    addon.register()
    assert bpy.ops.preferences.sqex_test_generic_unreal_profile.get_rna_type()
    addon.unregister()
    print("GENERIC_PROFILE_TEST_OK")


if __name__ == "__main__":
    main()
