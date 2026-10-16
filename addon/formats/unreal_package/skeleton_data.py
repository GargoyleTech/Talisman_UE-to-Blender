"""Skeleton subsets and variant bone collections for package assets."""

import json


def _create_variant_bone_collections(armature_obj, usage: dict) -> dict[str, int]:
    """Assign variant-exclusive, directly weighted bones to named collections.

    Collections are additional memberships: unlike KDI's hidden-helper collections,
    these never remove a bone from a normal visible collection or alter its hide state.
    The gargoyle returns names rather than mesh-local indices, which lets a mesh's
    reduced ReferenceSkeleton map back to the armature's complete master skeleton.
    """
    armature = armature_obj.data
    created: dict[str, int] = {}
    collection_data: dict[str, list[str]] = {}
    for variant_id, variant_info in (usage.get("variants") or {}).items():
        bone_names = {
            name
            for name in (variant_info.get("exclusiveWeightedBoneNames") or [])
            if armature.bones.get(name) is not None
        }
        if not bone_names:
            continue
        collection = armature.collections.get(variant_id)
        if collection is None:
            collection = armature.collections.new(variant_id)
        for bone_name in sorted(bone_names, key=str.casefold):
            bone = armature.bones[bone_name]
            if collection not in list(bone.collections):
                collection.assign(bone)
        created[variant_id] = len(bone_names)
        collection_data[variant_id] = sorted(bone_names, key=str.casefold)

    armature_obj["ff7r_variant_bone_usage"] = json.dumps(
        {
            "skeletonAssetPath": usage.get("skeletonAssetPath", ""),
            "searchedMeshCount": usage.get("searchedMeshCount", 0),
            "parsedMeshCount": usage.get("parsedMeshCount", 0),
            "collections": collection_data,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return created


def _restrict_skeleton_to_referenced_bones(
    skeleton_asset: dict,
    referenced_bones: set[str],
) -> tuple[dict, int, int]:
    """Keep a mesh ReferenceSkeleton and every parent needed to build it."""
    if not referenced_bones:
        raise ValueError("The SkeletalMesh has no ReferenceSkeleton bones.")

    source_bones = list(skeleton_asset.get("bones") or [])
    index_by_name = {bone.get("name"): index for index, bone in enumerate(source_bones)}
    included = {
        index_by_name[name] for name in referenced_bones if name in index_by_name
    }
    if not included:
        raise ValueError(
            "The mesh-referenced bone names did not occur in this Skeleton."
        )

    # A mesh can weight a child while Blender still needs every parent in order to
    # reconstruct that child's component-space bind transform.
    pending = list(included)
    while pending:
        index = pending.pop()
        parent_index = int(source_bones[index].get("parentIndex", -1))
        if 0 <= parent_index < len(source_bones) and parent_index not in included:
            included.add(parent_index)
            pending.append(parent_index)

    retained_indices = [
        index for index in range(len(source_bones)) if index in included
    ]
    remapped_indices = {
        old_index: new_index for new_index, old_index in enumerate(retained_indices)
    }
    reduced_bones = []
    for old_index in retained_indices:
        bone = dict(source_bones[old_index])
        parent_index = int(bone.get("parentIndex", -1))
        bone["parentIndex"] = remapped_indices.get(parent_index, -1)
        reduced_bones.append(bone)

    reduced_asset = dict(skeleton_asset)
    reduced_asset["bones"] = reduced_bones
    reduced_asset["sockets"] = [
        socket
        for socket in (skeleton_asset.get("sockets") or [])
        if socket.get("boneName") in {bone.get("name") for bone in reduced_bones}
    ]
    return reduced_asset, len(referenced_bones), len(reduced_bones)
