#!/usr/bin/env python3
"""Build the Blender extension package and static repository listing."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "addon"
MANIFEST = SOURCE / "blender_manifest.toml"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--blender-executable",
        default=shutil.which("blender"),
        help="Path to Blender 4.2 or newer; defaults to blender on PATH",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "dist" / "blender-extensions",
        help="Static repository directory to create or update",
    )
    args = parser.parse_args()

    if not args.blender_executable:
        parser.error("provide --blender-executable or add blender to PATH")

    manifest = tomllib.loads(MANIFEST.read_text(encoding="utf-8"))
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="talisman-extension-build-") as temporary:
        package_source = Path(temporary) / "source"
        blender_resources = Path(temporary) / "blender-user-resources"
        shutil.copytree(SOURCE, package_source)
        shutil.copy2(ROOT / "LICENSE", package_source / "LICENSE")
        shutil.copy2(ROOT / "NOTICE.md", package_source / "NOTICE.md")
        environment = os.environ.copy()
        environment["BLENDER_USER_RESOURCES"] = str(blender_resources)
        environment["BLENDER_USER_CONFIG"] = str(blender_resources / "config")
        environment["BLENDER_USER_SCRIPTS"] = str(blender_resources / "scripts")
        environment["BLENDER_USER_DATAFILES"] = str(blender_resources / "datafiles")
        environment["BLENDER_USER_EXTENSIONS"] = str(blender_resources / "extensions")

        subprocess.run(
            [
                args.blender_executable,
                "--background",
                "--factory-startup",
                "--command",
                "extension",
                "build",
                "--source-dir",
                str(package_source),
                "--output-dir",
                str(output_dir),
            ],
            check=True,
            env=environment,
        )
        subprocess.run(
            [
                args.blender_executable,
                "--background",
                "--factory-startup",
                "--command",
                "extension",
                "server-generate",
                "--repo-dir",
                str(output_dir),
                "--html",
            ],
            check=True,
            env=environment,
        )
    print(f"Repository updated: {output_dir}")
    print(f"Package: {manifest['id']}-{manifest['version']}.zip")


if __name__ == "__main__":
    main()
