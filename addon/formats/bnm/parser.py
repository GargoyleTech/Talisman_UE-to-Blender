"""Parse FF7 Rebirth Bonamik (``*_BNM``) data without simulating it.

The package gargoyle returns a mapping-compatible representation of a cooked
``SQEX_BonamikAsset``.  FModel-style one-element JSON arrays work too.  The
parser keeps every mapped property intact while adding the indexes needed by a
future physics backend:

* a SkeletalMesh's authored ``BonamikDataList`` paths;
* BNM bodies resolved to their ultimate skeleton anchor bone; and
* the link, cone, KDI and collision-shape records touching a selected bone.

No coordinate conversion happens here.  Bonamik values remain in the game's
authored Unreal-space units until a real simulator defines its own conversion
contract.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


BNM_ASSET_TYPE = "SQEX_BonamikAsset"
"""Expected UE export class for a Bonamik physics asset."""


_BODY_IDENTITY_KEYS = frozenset({"mName", "mParentName", "mGroupName"})


def _mapping(value: Any) -> dict[str, Any]:
    """Return a shallow string-keyed copy of one JSON object, if present."""
    if not isinstance(value, Mapping):
        return {}
    return {str(key): item for key, item in value.items()}


def _records(value: Any) -> tuple[dict[str, Any], ...]:
    """Keep valid object entries from an optional mapped array."""
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return ()
    return tuple(_mapping(item) for item in value if isinstance(item, Mapping))


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _casefold(value: str) -> str:
    return value.casefold() if value else ""


@dataclass(frozen=True)
class BonamikBody:
    """One authored Bonamik body and its skeleton-anchor resolution.

    ``parent_name`` is the literal ``mParentName`` value.  It may point at a
    skeletal bone or at another ``BonamikBody_*`` record.  ``skeleton_bone`` is
    the latter chain resolved to its terminal skeletal-bone anchor.  The
    gargoyle's original field names and values remain available in ``properties``.
    """

    name: str
    parent_name: str
    skeleton_bone: str
    group_name: str
    is_kinematic: bool | None
    is_collision: bool | None
    properties: Mapping[str, Any]

    @property
    def physics_values(self) -> dict[str, Any]:
        """Return body values without its name, parent, or group identifiers."""
        return {
            key: value
            for key, value in self.properties.items()
            if key not in _BODY_IDENTITY_KEYS
        }


@dataclass(frozen=True)
class BonamikBonePhysics:
    """All parsed Bonamik records directly relevant to one skeleton bone."""

    bone_name: str
    bodies: tuple[BonamikBody, ...]
    groups: tuple[Mapping[str, Any], ...]
    links: tuple[Mapping[str, Any], ...]
    cones: tuple[Mapping[str, Any], ...]
    kdis: tuple[Mapping[str, Any], ...]
    shapes: tuple[Mapping[str, Any], ...]
    collision_cliques: tuple[Mapping[str, Any], ...]

    @property
    def body_values(self) -> tuple[dict[str, Any], ...]:
        """Convenience view of just each matching body's authored values."""
        return tuple(body.physics_values for body in self.bodies)


@dataclass(frozen=True)
class BonamikAsset:
    """Mapped, read-only view of one ``SQEX_BonamikAsset`` export.

    The named record arrays are intentionally represented as generic mappings.
    Their exact solver semantics are not yet established, and retaining all
    fields avoids losing values a later physics implementation may need.
    """

    name: str
    asset_type: str
    package: str
    version: Any
    scene_manager: Mapping[str, Any]
    groups: tuple[Mapping[str, Any], ...]
    bodies: tuple[BonamikBody, ...]
    collision_cliques: tuple[Mapping[str, Any], ...]
    kdis: tuple[Mapping[str, Any], ...]
    links: tuple[Mapping[str, Any], ...]
    cones: tuple[Mapping[str, Any], ...]
    shapes: tuple[Mapping[str, Any], ...]
    properties: Mapping[str, Any]
    source: Mapping[str, Any]

    def bodies_for_bone(self, bone_name: str) -> tuple[BonamikBody, ...]:
        """Return bodies rooted at ``bone_name`` (case-insensitive).

        This follows chains whose immediate parent is another Bonamik body, so
        querying a skeleton anchor includes its downstream simulated bodies.
        """
        key = _casefold(bone_name)
        if not key:
            return ()
        return tuple(
            body for body in self.bodies
            if _casefold(body.skeleton_bone) == key
        )

    def physics_for_bone(self, bone_name: str) -> BonamikBonePhysics:
        """Collect body values and relationship records affecting one bone."""
        bodies = self.bodies_for_bone(bone_name)
        body_names = {_casefold(body.name) for body in bodies if body.name}
        group_names = {_casefold(body.group_name) for body in bodies if body.group_name}

        def references_body(record: Mapping[str, Any]) -> bool:
            endpoints = (_text(record.get("mA")), _text(record.get("mB")))
            if any(_casefold(endpoint) in body_names for endpoint in endpoints):
                return True
            linked_bodies = record.get("mBodies")
            return (
                isinstance(linked_bodies, Sequence)
                and not isinstance(linked_bodies, (str, bytes, bytearray))
                and any(
                    _casefold(item) in body_names
                    for item in linked_bodies
                    if isinstance(item, str)
                )
            )

        groups = tuple(
            group for group in self.groups
            if _casefold(_text(group.get("m_GroupName"))) in group_names
        )
        links = tuple(record for record in self.links if references_body(record))
        cones = tuple(record for record in self.cones if references_body(record))
        kdis = tuple(record for record in self.kdis if references_body(record))
        shapes = tuple(record for record in self.shapes if references_body(record))
        shape_ids = {shape.get("mShapeId") for shape in shapes}
        collision_cliques = tuple(
            record for record in self.collision_cliques
            if isinstance(record.get("mShapeIds"), Sequence)
            and not isinstance(record.get("mShapeIds"), (str, bytes, bytearray))
            and any(shape_id in shape_ids for shape_id in record["mShapeIds"])
        )
        return BonamikBonePhysics(
            bone_name=bone_name,
            bodies=bodies,
            groups=groups,
            links=links,
            cones=cones,
            kdis=kdis,
            shapes=shapes,
            collision_cliques=collision_cliques,
        )


def _unwrap_asset(payload: Any) -> dict[str, Any]:
    """Accept an asset, gargoyle response, or FModel-style one-item export list."""
    if isinstance(payload, Mapping) and isinstance(payload.get("bnm"), Mapping):
        payload = payload["bnm"]
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        if len(payload) != 1:
            raise ValueError("Expected a BNM JSON root containing exactly one asset")
        payload = payload[0]
    asset = _mapping(payload)
    if not asset:
        raise ValueError("BNM data does not contain an asset object")
    return asset


def _resolve_skeleton_bone(
    parent_name: str,
    parents_by_body_name: Mapping[str, str],
) -> str:
    """Resolve ``BonamikBody_*`` parent links until reaching a skeletal bone."""
    current = parent_name
    seen: set[str] = set()
    while current:
        key = _casefold(current)
        if key not in parents_by_body_name:
            return current
        if key in seen:
            # A malformed cyclic body chain has no meaningful skeleton anchor.
            return ""
        seen.add(key)
        current = parents_by_body_name[key]
    return ""


def parse_bnm(payload: Any) -> BonamikAsset:
    """Parse a gargoyle/FModel representation of one BNM asset.

    The function intentionally validates only the asset envelope and preserves
    unknown properties.  Bonamik versions evolve independently of the gargoyle,
    so rejecting a new per-body field would make the future physics layer less
    capable than a raw package read.
    """
    asset = _unwrap_asset(payload)
    asset_type = _text(asset.get("Type"))
    if asset_type.casefold() != BNM_ASSET_TYPE.casefold():
        raise ValueError(
            f"Expected {BNM_ASSET_TYPE}, got {asset_type or 'an untyped asset'}"
        )
    properties = _mapping(asset.get("Properties"))
    if not properties:
        raise ValueError("BNM asset does not contain a Properties object")

    raw_bodies = _records(properties.get("mBodies"))
    parents_by_body_name = {
        _casefold(_text(body.get("mName"))): _text(body.get("mParentName"))
        for body in raw_bodies
        if _text(body.get("mName"))
    }
    bodies = tuple(
        BonamikBody(
            name=_text(body.get("mName")),
            parent_name=_text(body.get("mParentName")),
            skeleton_bone=_resolve_skeleton_bone(
                _text(body.get("mParentName")), parents_by_body_name
            ),
            group_name=_text(body.get("mGroupName")),
            is_kinematic=(
                bool(body["m_IsKinematic"])
                if isinstance(body.get("m_IsKinematic"), bool) else None
            ),
            is_collision=(
                bool(body["m_IsCollision"])
                if isinstance(body.get("m_IsCollision"), bool) else None
            ),
            properties=body,
        )
        for body in raw_bodies
    )
    return BonamikAsset(
        name=_text(asset.get("Name")),
        asset_type=asset_type,
        package=_text(asset.get("Package")),
        version=properties.get("m_VersionNo"),
        scene_manager=_mapping(properties.get("mSceneManager")),
        groups=_records(properties.get("mGroups")),
        bodies=bodies,
        collision_cliques=_records(properties.get("mCollisionCliques")),
        kdis=_records(properties.get("mKDIs")),
        links=_records(properties.get("mLinks")),
        cones=_records(properties.get("mCones")),
        shapes=_records(properties.get("mShapes")),
        properties=properties,
        source=asset,
    )


def read_bnm_json(path: str | Path) -> BonamikAsset:
    """Read a loose FModel/gargoyle BNM JSON file and parse its one asset."""
    raw = Path(path).read_bytes()
    return parse_bnm(json.loads(raw.decode("utf-8-sig")))


def associated_bnm_paths(skeletal_mesh: Mapping[str, Any]) -> tuple[str, ...]:
    """Return normalized, deduplicated ``bnmPaths`` authored on a mesh.

    A BNM belongs to a specific SkeletalMesh variant, not necessarily to its
    shared Skeleton.  Call this on the gargoyle's ``skeletalMesh`` result instead
    of guessing a sibling filename.
    """
    values = skeletal_mesh.get("bnmPaths")
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        return ()
    paths: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        path = value.strip().replace("\\", "/").lstrip("/")
        key = path.casefold()
        if path and key not in seen:
            paths.append(path)
            seen.add(key)
    return tuple(paths)


def physics_values_for_bone(
    asset: BonamikAsset,
    bone_name: str,
) -> tuple[dict[str, Any], ...]:
    """Return each matching body's authored physics values for ``bone_name``.

    Use :meth:`BonamikAsset.physics_for_bone` when a solver also needs links,
    cones, groups, shapes, or collision-clique relationships.
    """
    return asset.physics_for_bone(bone_name).body_values


# A descriptive alias for callers that read a gargoyle SkeletalMesh payload.
bnm_paths_from_skeletal_mesh = associated_bnm_paths
