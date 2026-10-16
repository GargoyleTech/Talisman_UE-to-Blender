"""Package configuration for FINAL FANTASY VII REMAKE INTERGRADE."""

from ...core.profiles import GameProfile


PROFILE = GameProfile(
    key="remake",
    label="FINAL FANTASY VII REMAKE INTERGRADE",
    gargoyle_profile="remake",
    engine_label="UE 4.18 (FF7 Remake custom profile)",
    package_relative_path=("End", "Content", "Paks"),
    install_root_property="remake_install_root",
    usmap_property="remake_usmap_path",
    aes_key_property="remake_aes_key",
)
