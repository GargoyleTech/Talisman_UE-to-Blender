"""Package configuration for KINGDOM HEARTS 0.2 Birth by Sleep."""

from ...core.profiles import GameProfile


PROFILE = GameProfile(
    key="kingdom_hearts_0_2",
    label="KINGDOM HEARTS 0.2 Birth by Sleep -A fragmentary passage-",
    gargoyle_profile="kingdom-hearts-0.2",
    engine_label="UE 4.17 (Kingdom Hearts render layout)",
    package_relative_path=("Content", "Paks"),
    install_root_property="kingdom_hearts_0_2_install_root",
    virtual_content_root=("KINGDOM HEARTS 0.2 Birth by Sleep", "Content"),
    aes_key_property="kingdom_hearts_0_2_aes_key",
)
