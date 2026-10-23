#!/usr/bin/env python3
"""Publish and deploy the Windows x64 bridge, removing obsolete build files."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PROJECT = ROOT / "bridge" / "RebirthPackageLister.csproj"
DESTINATION = ROOT / "addon" / "bridge"
ASSEMBLY = "TalismanGameAssetBridge"


def validate_publish(directory: Path) -> None:
    """Reject incomplete or portable output before replacing the shipped bridge."""
    required = {
        f"{ASSEMBLY}.exe",
        f"{ASSEMBLY}.dll",
        f"{ASSEMBLY}.deps.json",
        f"{ASSEMBLY}.runtimeconfig.json",
        "libSkiaSharp.dll",
    }
    missing = required - {path.name for path in directory.iterdir() if path.is_file()}
    if missing:
        raise RuntimeError(f"Bridge publish is missing: {', '.join(sorted(missing))}")
    deps = json.loads((directory / f"{ASSEMBLY}.deps.json").read_text(encoding="utf-8"))
    if not deps["runtimeTarget"]["name"].endswith("/win-x64"):
        raise RuntimeError("Bridge publish must target win-x64")
    # A RID-specific publish puts selected native libraries beside the executable.
    # Reject subfolders containing native assets for other platforms.
    unwanted = [
        path.name for path in directory.iterdir()
        if path.is_dir() or path.suffix.lower() in {".pdb", ".dylib", ".so"}
    ]
    if unwanted:
        raise RuntimeError(f"Unexpected bridge publish files: {', '.join(sorted(unwanted))}")


def main() -> None:
    # Build in a fresh directory: publishing over addon/bridge would retain stale
    # native libraries from older NuGet versions and portable builds.
    build_root = ROOT / "bridge" / "bin"
    build_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="publish-", dir=build_root) as temporary:
        publish = Path(temporary) / "publish"
        subprocess.run(
            [
                "dotnet", "publish", str(PROJECT), "--configuration", "Release",
                "--runtime", "win-x64", "--self-contained", "false",
                "-p:CopyOutputSymbolsToPublishDirectory=false",
                "--output", str(publish),
            ],
            check=True,
        )
        validate_publish(publish)
        subprocess.run(
            [str(publish / f"{ASSEMBLY}.exe"), "--capabilities"],
            check=True, stdout=subprocess.DEVNULL,
        )
        # Only replace the expected repository folder, never a redirected path.
        if DESTINATION.resolve() != ROOT / "addon" / "bridge":
            raise RuntimeError(f"Refusing to replace redirected directory: {DESTINATION}")
        previous = Path(temporary) / "previous"
        if DESTINATION.exists():
            DESTINATION.rename(previous)
        try:
            publish.rename(DESTINATION)
        except OSError:
            if previous.exists():
                previous.rename(DESTINATION)
            raise
        size = sum(path.stat().st_size for path in DESTINATION.rglob("*") if path.is_file())
        print(f"addon/bridge: Windows x64, {size / 1024 / 1024:.1f} MiB")


if __name__ == "__main__":
    main()
