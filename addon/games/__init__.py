"""Registered game profiles for the Retrilogy tools."""

from .crisis_core.profile import PROFILE as CRISIS_CORE
from .rebirth.profile import PROFILE as REBIRTH
from .remake.profile import PROFILE as REMAKE

SUPPORTED_PROFILES = (REMAKE, REBIRTH, CRISIS_CORE)
PROFILE_BY_KEY = {profile.key: profile for profile in SUPPORTED_PROFILES}

__all__ = (
    "CRISIS_CORE",
    "REBIRTH",
    "REMAKE",
    "SUPPORTED_PROFILES",
    "PROFILE_BY_KEY",
)

