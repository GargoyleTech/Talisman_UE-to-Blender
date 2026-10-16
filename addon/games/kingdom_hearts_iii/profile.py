"""Package configuration for KINGDOM HEARTS III."""

from ...core.profiles import GameProfile


PROFILE = GameProfile(
    key="kingdom_hearts_iii",
    label="KINGDOM HEARTS III",
    gargoyle_profile="kingdom-hearts-3",
    engine_label="UE 4.18 (Kingdom Hearts III profile)",
    package_relative_path=("KINGDOM HEARTS III", "Content", "Paks"),
    install_root_property="kingdom_hearts_iii_install_root",
    aes_key_property="kingdom_hearts_iii_aes_key",
)
