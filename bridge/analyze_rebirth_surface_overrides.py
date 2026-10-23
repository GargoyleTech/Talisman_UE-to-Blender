"""Audit FModel Surface instance switches without assuming omitted defaults.

Example (from the repository root):
    python bridge/analyze_rebirth_surface_overrides.py SOURCE --output-dir docs/data
"""

import argparse
import collections
import csv
import hashlib
import json
from pathlib import Path


ALPHA_SWITCHES = {"Opacity_", "Ghost_", "Hologram_", "Phantom_", "BrokenFlow_"}
GROUPS = ("inherited", "masked", "alpha_inherited_layer", "alpha_TRL_1")


def audit(source, output):
    rows = []
    switches_by_group = {group: collections.Counter() for group in GROUPS}
    group_counts = collections.Counter()
    switch_values = collections.Counter()
    switch_overrides = collections.Counter()
    associations = collections.Counter()
    prediction_errors = []
    source_digest = hashlib.sha256()
    for path in sorted(source.rglob("*.json")):
        raw = path.read_bytes()
        relative = path.relative_to(source).as_posix()
        source_digest.update(relative.encode("utf-8") + b"\0" + raw + b"\0")
        objects = json.loads(raw.decode("utf-8-sig"))
        if not isinstance(objects, list) or len(objects) != 1:
            raise ValueError(f"Expected exactly one exported object: {path}")
        obj = objects[0]
        if obj.get("Type") != "MaterialInstanceConstant":
            raise ValueError(f"Unexpected export type: {path}")
        props = obj["Properties"]
        base = props.get("BasePropertyOverrides", {})
        blend = base.get("BlendMode") if base.get("bOverride_BlendMode") else None
        layer = (base.get("TranslucencyRenderLayer")
                 if base.get("bOverride_TranslucencyRenderLayer") else None)
        if blend is None and layer is None:
            group = "inherited"
        elif blend == "EBlendMode::BLEND_Masked" and layer is None:
            group = "masked"
        elif blend == "EBlendMode::BLEND_AlphaCompositeColored" and layer is None:
            group = "alpha_inherited_layer"
        elif (blend == "EBlendMode::BLEND_AlphaCompositeColored"
              and layer == "ETranslucencyRenderLayer::TRL_1"):
            group = "alpha_TRL_1"
        else:
            raise ValueError(f"New base override combination: {path}: {base}")
        entries = props.get("StaticParameters", {}).get("StaticSwitchParameters", [])
        enabled = set()
        seen = set()
        for entry in entries:
            info = entry["ParameterInfo"]
            key = (info["Name"], info.get("Association"), info.get("Index"))
            if key in seen:
                raise ValueError(f"Duplicate static switch: {path}: {key}")
            seen.add(key)
            switch_values[str(entry.get("Value", "absent"))] += 1
            switch_overrides[str(entry.get("bOverride", "absent"))] += 1
            associations[str(key[1:])] += 1
            if entry.get("bOverride") is True and entry.get("Value") is True:
                if key[1:] != ("EMaterialParameterAssociation::GlobalParameter", -1):
                    raise ValueError(f"Cannot flatten a non-global switch: {path}: {key}")
                enabled.add(info["Name"])
        group_counts[group] += 1
        switches_by_group[group].update(enabled)
        predicted = ("EBlendMode::BLEND_AlphaCompositeColored"
                     if enabled & ALPHA_SWITCHES else "EBlendMode::BLEND_Masked"
                     if enabled & {"Coverage_", "MateriaIndexed_"} else None)
        if predicted != blend:
            prediction_errors.append(obj["Name"])
        rows.append({
            "file": relative,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "name": obj["Name"],
            "parent": props.get("Parent", {}).get("ObjectPath", "absent"),
            "blend_override_flag": base.get("bOverride_BlendMode", "absent"),
            "blend_stored_value": base.get("BlendMode", "absent"),
            "layer_override_flag": base.get("bOverride_TranslucencyRenderLayer", "absent"),
            "layer_stored_value": base.get("TranslucencyRenderLayer", "absent"),
            "group": group,
            "switch_entry_count": len(entries),
            "enabled_local_switches": ";".join(sorted(enabled)),
        })
    if not rows:
        raise ValueError(f"No JSON exports found in {source}")
    output.mkdir(parents=True, exist_ok=True)
    with (output / "rebirth_surface_override_inventory.csv").open(
            "w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    names = sorted(set().union(*(set(counts) for counts in switches_by_group.values())))
    with (output / "rebirth_surface_switch_frequencies.csv").open(
            "w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["switch", *GROUPS, "total"])
        for name in names:
            counts = [switches_by_group[group][name] for group in GROUPS]
            writer.writerow([name, *counts, sum(counts)])
    summary = {
        "source": str(source),
        "source_sha256": source_digest.hexdigest(),
        "source_hash_method": "Sorted relative POSIX path + NUL + file bytes + NUL, per file",
        "instances": len(rows),
        "parents": dict(collections.Counter(row["parent"] for row in rows)),
        "groups": {group: group_counts[group] for group in GROUPS},
        "switch_entries": sum(switch_values.values()),
        "unique_enabled_local_switches": len(names),
        "switch_values": dict(switch_values),
        "switch_override_flags": dict(switch_overrides),
        "switch_associations": dict(associations),
        "observed_blend_rule_errors": prediction_errors,
    }
    parent_path = source.parent.parent / "Material" / "RM_Surface.json"
    if parent_path.exists():
        parent_bytes = parent_path.read_bytes()
        parent_props = json.loads(parent_bytes.decode("utf-8-sig"))[0]["Properties"]
        summary["parent_export"] = {
            "path": str(parent_path),
            "sha256": hashlib.sha256(parent_bytes).hexdigest(),
            "BlendMode": parent_props.get("BlendMode", "absent"),
            "TranslucencyRenderLayer": parent_props.get("TranslucencyRenderLayer", "absent"),
            "StaticParameters": parent_props.get("StaticParameters", "absent"),
        }
    (output / "rebirth_surface_override_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    audit(args.source, args.output_dir)
