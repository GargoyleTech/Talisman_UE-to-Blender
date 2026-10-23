"""Nonblocking texture browser transport. No worker threads or Blender data access."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

from ...core.bridge import gargoyle_command


class TextureBrowserSession:
    """One mounted bridge with atomic request/result files and one request in flight."""

    def __init__(self, profile, paths, cache_root):
        self.directory = tempfile.TemporaryDirectory(prefix="talisman_texture_browser_", ignore_cleanup_errors=True)
        self.root = Path(self.directory.name)
        self.process = None
        self.pending = None
        self.serial = 0
        self.started = time.monotonic()
        self.ready = False
        self.signature = configuration_signature(profile, paths)
        self.cache_path = str(Path(cache_root) / ("texture_index_" + self.signature + ".json")) if cache_root else ""
        try:
            command = gargoyle_command(Path(__file__).resolve().parents[2], profile, paths,
                                       str(self.root), operation="texture-browser")
            self.process = subprocess.Popen(
                command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception:
            self.close()
            raise

    def poll(self):
        """Return a completed (tag, response), or None; never wait for pipe I/O."""
        if self.process is None or self.process.poll() is not None:
            raise RuntimeError("The texture bridge stopped. Check the game folder, profile, mappings, AES key, and compression library, then refresh.")
        if not self.ready:
            self.ready = (self.root / "ready.json").is_file()
            if not self.ready and time.monotonic() - self.started > 180:
                raise RuntimeError("Mounting the game packages timed out. Check the game configuration, then refresh.")
        if self.pending is None:
            return None
        serial, tag, started = self.pending
        path = self.root / f"response-{serial:08d}.json"
        if not path.is_file():
            timeout = 1200 if tag[0] == "index" else 180
            if time.monotonic() - started > timeout:
                raise RuntimeError("The texture request timed out. Refresh to restart the browser.")
            return None
        response = json.loads(path.read_text(encoding="utf-8-sig"))
        path.unlink(missing_ok=True)
        self.pending = None
        return tag, response

    def send(self, tag, **payload):
        if not self.ready or self.pending is not None:
            raise RuntimeError("The texture bridge is busy.")
        self.serial += 1
        path = self.root / f"request-{self.serial:08d}.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(temporary, path)
        self.pending = self.serial, tag, time.monotonic()

    def progress(self):
        try:
            return json.loads((self.root / "progress.json").read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return {}

    def remove_image(self, info):
        path = Path(info.get("output") or "")
        if path.is_file() and path.resolve().is_relative_to(self.root.resolve()):
            path.unlink(missing_ok=True)

    def close(self):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.kill()
            try:
                self.process.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                pass
            self.process = None
        self.pending = None
        self.directory.cleanup()


def configuration_signature(profile, paths):
    values = [profile.gargoyle_profile, paths.aes_key]
    for value in (paths.install_root, paths.oodle_dll, paths.usmap_path):
        value = os.path.normcase(os.path.abspath(value)) if value else ""
        values.append(value)
        if value and os.path.isfile(value):
            stat = os.stat(value)
            values.extend((stat.st_size, stat.st_mtime_ns))
    # Keys never appear in cache files, UI state, diagnostics, or filenames.
    return hashlib.sha256(json.dumps(values).encode()).hexdigest()
