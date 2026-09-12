"""Load the extracted TailFire Niagara system with the Rebirth fork itself.

This runs only in the fork's UE4Editor-Cmd PythonScript commandlet.  It is a
read-only diagnostic: the game package is copied below the project's Content
directory so UE's native unversioned-property serializer can be used as an
independent check on the CUE4Parse result.
"""

import json
import traceback

import unreal


OUTPUT = r"C:\Users\Ghouls\Proton Drive\GhoulCulture\My files\TheBeastintheTable\Blender\FF7R\ff7r-rebirth-tools\bridge\Inspect\UnrealReflection\tailfire-editor-load.json"
ASSET_PATH = "/Game/Effect/Character/Player/PC0004_RedXIII_Body/Particle/FX_PC0004_TailFire_01"

# These include the serialised NiagaraSystem fields from the fork header and
# every system field advertised by the fork's Python wrapper.  A failed lookup
# is recorded rather than treated as evidence that the package failed to load.
PROPERTY_NAMES = (
    "effect_type",
    "override_scalability_settings",
    "scalability_overrides_deprecated",
    "system_scalability_overrides",
    "emitter_handles",
    "parameter_collection_overrides",
    "system_spawn_script",
    "system_update_script",
    "m_vfx_ref_data_interface_asset_map",
    "system_compiled_data",
    "exposed_parameters",
    "fixed_bounds",
    "auto_deactivate",
    "warmup_time",
    "warmup_tick_count",
    "warmup_tick_delta",
    "has_system_script_dis",
    "user_di_names",
    "bake_out_rapid_iteration",
    "bake_out_rapid_iteration_on_cook",
    "trim_attributes",
    "trim_attributes_on_cook",
    "compress_attributes",
    "require_current_frame_data",
    "is_template_asset",
    "template_asset_description",
    "expose_to_library",
    "pool_prime_size",
    "max_pool_size",
    "m_end_effect_extra_data",
)


def display(value, depth=0):
    """Make editor values JSON-safe without invoking any mutation APIs."""
    if depth > 3:
        return str(value)
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, (list, tuple)):
        return [display(item, depth + 1) for item in value]
    try:
        return [display(item, depth + 1) for item in value]
    except Exception:
        return str(value)


def property_value(asset, name):
    try:
        return {"ok": True, "value": display(asset.get_editor_property(name))}
    except Exception:
        return {"ok": False, "error": traceback.format_exc()}


result = {"assetPath": ASSET_PATH}
try:
    asset = unreal.load_asset(ASSET_PATH)
    result["load"] = {"ok": asset is not None, "value": str(asset)}
    if asset is not None:
        result["class"] = str(asset.get_class())
        result["properties"] = {name: property_value(asset, name) for name in PROPERTY_NAMES}
except Exception:
    result["load"] = {"ok": False, "error": traceback.format_exc()}

with open(OUTPUT, "w", encoding="utf-8") as stream:
    json.dump(result, stream, indent=2, sort_keys=True)

unreal.log("Wrote TailFire editor load report: {}".format(OUTPUT))
