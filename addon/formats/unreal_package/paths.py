"""Unreal object references to mounted package paths."""


def _texture_package_path(
    game_path: str,
    *,
    profile,
) -> tuple[str, str]:
    """Turn a texture object path into the active title's mounted package path."""
    package_path = game_path.split(":", 1)[0]
    slash = package_path.rfind("/")
    dot = package_path.rfind(".")
    if dot > slash:
        package_path = package_path[:dot]
    content_root = profile.mounted_content_root
    if package_path.casefold().startswith("/game/"):
        virtual_path = content_root + "/" + package_path[6:]
    elif package_path.casefold().startswith(content_root.casefold() + "/"):
        virtual_path = package_path
    elif package_path.casefold().startswith("/engine/"):
        virtual_path = "Engine/Content/" + package_path[8:]
    else:
        raise ValueError(f"Unsupported Unreal texture path: {game_path}")
    stem = virtual_path.rsplit("/", 1)[-1]
    return virtual_path + ".uasset", stem


def _game_asset_path_to_virtual_uasset(
    asset_path: str,
    *,
    profile,
) -> str | None:
    """Convert a UE ObjectName such as StaticMesh'/Game/A/B.B' to a package path."""
    if not isinstance(asset_path, str):
        return None
    path = asset_path.strip().strip("'")
    if "'" in path:
        parts = path.split("'", 2)
        if len(parts) >= 2:
            path = parts[1]
    path = path.split(":", 1)[0].strip()
    # Object references append ``.ObjectName`` after the final path segment.
    # Do not split on every dot: the KH 0.2 mounted root itself contains one.
    dot = path.rfind(".")
    slash = max(path.rfind("/"), path.rfind("\\"))
    package_path = path[:dot] if dot > slash else path
    # ``package_relative_path`` identifies the on-disk Paks directory; virtual
    # package paths stop one segment earlier at the Unreal content root.
    content_root = profile.mounted_content_root
    if package_path.casefold().startswith("/game/"):
        return content_root + "/" + package_path[6:] + ".uasset"
    # Conventional package exports may expose an FPackageIndex as an already
    # mounted virtual path (for example ``End/Content/.../Wall.1``) instead of
    # the ``/Game/...`` object path used by Rebirth IoStore packages.  Both
    # describe the same asset; retain the title's own content root and discard
    # only the UE object suffix before addressing the package gargoyle.
    if package_path.casefold().startswith(content_root.casefold() + "/"):
        return package_path + ".uasset"
    if package_path.casefold().startswith("/engine/"):
        return "Engine/Content/" + package_path[8:] + ".uasset"
    return None
