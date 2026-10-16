"""Read-only Bonamik (BNM) parsing and persistence helpers.

BNM assets are Square Enix's ``SQEX_BonamikAsset`` jiggle-physics data.  This
package deliberately does not evaluate physics; it makes the authored data
available to a future solver without coupling that solver to package I/O.
"""

from .parser import (
    BNM_ASSET_TYPE,
    BonamikAsset,
    BonamikBody,
    BonamikBonePhysics,
    associated_bnm_paths,
    parse_bnm,
    physics_values_for_bone,
    read_bnm_json,
)

__all__ = (
    "BNM_ASSET_TYPE",
    "BonamikAsset",
    "BonamikBody",
    "BonamikBonePhysics",
    "associated_bnm_paths",
    "parse_bnm",
    "physics_values_for_bone",
    "read_bnm_json",
)
