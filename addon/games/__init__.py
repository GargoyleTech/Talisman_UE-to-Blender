"""Registered game profiles for the Retrilogy tools."""

from .crisis_core.profile import PROFILE as CRISIS_CORE
from .kingdom_hearts_0_2.profile import PROFILE as KINGDOM_HEARTS_0_2
from .kingdom_hearts_iii.profile import PROFILE as KINGDOM_HEARTS_III
from .rebirth.profile import PROFILE as REBIRTH
from .remake.profile import PROFILE as REMAKE

SUPPORTED_PROFILES = (
    REMAKE,
    REBIRTH,
    CRISIS_CORE,
    KINGDOM_HEARTS_III,
    KINGDOM_HEARTS_0_2,
)
PROFILE_BY_KEY = {profile.key: profile for profile in SUPPORTED_PROFILES}

__all__ = (
    "CRISIS_CORE",
    "KINGDOM_HEARTS_0_2",
    "KINGDOM_HEARTS_III",
    "REBIRTH",
    "REMAKE",
    "SUPPORTED_PROFILES",
    "PROFILE_BY_KEY",
)

