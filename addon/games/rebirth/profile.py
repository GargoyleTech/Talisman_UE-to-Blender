"""Package configuration for FINAL FANTASY VII REBIRTH."""

from ...core.profiles import GameProfile


PROFILE = GameProfile(
    key="rebirth",
    label="FINAL FANTASY VII REBIRTH",
    bridge_profile="rebirth",
    engine_label="UE 4.26 (FF7 Rebirth custom profile)",
    package_relative_path=("End", "Content", "Paks"),
    install_root_property="rebirth_install_root",
    oodle_property="rebirth_oodle_dll",
    usmap_property="rebirth_usmap_path",
)

