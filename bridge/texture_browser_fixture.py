"""Deterministic external-process fixture for the Blender texture browser tests."""

import json
from pathlib import Path
import struct
import sys
import time
import zlib


def write(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value))
    temporary.replace(path)


def png(path, width, height):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    row = b"\0" + bytes((192, 80, 32, 255)) * width
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(row * height)) + chunk(b"IEND", b""))


root = Path(sys.argv[1])
time.sleep(0.15)
write(root / "ready.json", {"ok": True})
entries = [{"path": f"Fixture/Content/Textures/T{i:03d}.uasset", "objectPath": f"/Game/Textures/T{i:03d}.T{i:03d}",
            "name": f"T{i:03d}", "textureType": "Texture2D", "isDirectory": False} for i in range(260)]
entries += [{"path": "Fixture/Content/Other/Container.uasset", "objectPath": f"/Game/Other/Container.{name}",
             "name": name, "textureType": "Texture2D", "isDirectory": False} for name in ("EmbeddedA", "EmbeddedB", "Unavailable")]
exposed = 128
while root.exists():
    files = sorted(root.glob("request-*.json"))
    if not files:
        time.sleep(0.01)
        continue
    request = files[0]
    token = request.stem.split("-", 1)[1]
    data = json.loads(request.read_text())
    action = data["action"]
    if action in {"index", "index_step"}:
        if action == "index_step":
            time.sleep(0.08)
            exposed = min(len(entries), exposed + 16)
        payload = {"count": exposed, "scanned": exposed, "total": len(entries), "complete": exposed == len(entries)}
    elif action == "browse":
        directory, terms = data["directory"], data["search"].casefold().split()
        if terms:
            rows = [entry for entry in entries[:exposed] if all(term in (entry["path"] + " " + entry["name"]).casefold() for term in terms)]
        else:
            prefix = directory + "/" if directory else ""
            matched = [entry for entry in entries[:exposed] if entry["path"].startswith(prefix)]
            folders = sorted({prefix + entry["path"][len(prefix):].split("/")[0] for entry in matched if "/" in entry["path"][len(prefix):]})
            rows = [{"path": path, "objectPath": "", "name": path.split("/")[-1], "textureType": "", "isDirectory": True} for path in folders]
            rows += [entry for entry in matched if "/" not in entry["path"][len(prefix):]]
        page = max(0, min(data["page"], max(0, (len(rows) - 1) // 128)))
        payload = {"rows": rows[page * 128:(page + 1) * 128], "page": page, "total": len(rows)}
    else:
        time.sleep(0.3 if action == "preview" else 0.04)
        if data["objectPath"].endswith(".Unavailable"):
            payload = {"status": "unavailable", "reason": "Fixture texture has no stored pixels"}
        else:
            output = root / ("image-" + token + ".png")
            size = 8 if action == "preview" else 32
            png(output, size, size // 2)
            payload = {"output": str(output), "width": size, "height": size // 2, "sourceWidth": 32, "sourceHeight": 16,
                       "pixelFormat": "PF_R8G8B8A8", "srgb": True, "textureType": "Texture2D", "textureLayout": "2D"}
    write(root / ("response-" + token + ".json"), {"ok": True, "payload": payload})
    request.unlink()
