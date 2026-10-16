"""Package configuration for CRISIS CORE -FINAL FANTASY VII- REUNION."""

from ...core.profiles import GameProfile


PROFILE = GameProfile(
    key="crisis_core",
    label="CRISIS CORE -FINAL FANTASY VII- REUNION",
    gargoyle_profile="crisis-core",
    engine_label="UE 4.27",
    package_relative_path=("CCFF7R", "Content", "Paks"),
    install_root_property="crisis_core_install_root",
    usmap_property="crisis_core_usmap_path",
)

