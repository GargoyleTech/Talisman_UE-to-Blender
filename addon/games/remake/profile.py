"""Package configuration for FINAL FANTASY VII REMAKE INTERGRADE."""

from ...core.profiles import GameProfile


PROFILE = GameProfile(
    key="remake",
    label="FINAL FANTASY VII REMAKE INTERGRADE",
    bridge_profile="remake",
    engine_label="UE 4.18 (FF7 Remake custom profile)",
    package_relative_path=("End", "Content", "Paks"),
    install_root_property="remake_install_root",
    oodle_property="remake_oodle_dll",
    usmap_property="remake_usmap_path",
    # Remake ships the compatible Oodle library itself.  The optional
    # preference is an override; otherwise this path is resolved automatically.
    bundled_oodle_relative_path=(
        "Engine", "Binaries", "ThirdParty", "Oodle", "Win64",
        "oo2core_7_win64.dll",
    ),
)
