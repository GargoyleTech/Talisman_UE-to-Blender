"""Dump reflected Niagara class information from the Rebirth modding editor.

Run with UE4Editor-Cmd's PythonScript commandlet. This is diagnostic-only and
does not load or modify a game asset.
"""

import json
import traceback

import unreal


OUTPUT = r"C:\Users\Ghouls\Proton Drive\GhoulCulture\My files\TheBeastintheTable\Blender\FF7R\ff7r-rebirth-tools\bridge\Inspect\UnrealReflection\niagara-python-reflection.json"

TARGETS = (
    ("NiagaraSystem", "/Script/Niagara.NiagaraSystem"),
    ("NiagaraEmitter", "/Script/Niagara.NiagaraEmitter"),
    ("NiagaraScript", "/Script/Niagara.NiagaraScript"),
    ("NiagaraComponent", "/Script/Niagara.NiagaraComponent"),
    ("VFXNiagaraDataInterfaceFunctionLibrary", "/Script/VFXNiagara.VFXNiagaraDataInterfaceFunctionLibrary"),
    ("VFXNiagaraDataInterfaceMaterial", "/Script/VFXNiagara.VFXNiagaraDataInterfaceMaterial"),
    ("VFXNiagaraDataInterfaceMaterialParameter", "/Script/VFXNiagara.VFXNiagaraDataInterfaceMaterialParameter"),
)


def capture(label, thunk):
    try:
        return {"ok": True, "value": thunk()}
    except Exception:
        return {"ok": False, "error": traceback.format_exc()}


result = {}
for python_name, object_path in TARGETS:
    item = {"objectPath": object_path}
    item["classObject"] = capture("classObject", lambda path=object_path: str(unreal.load_object(None, path)))
    wrapper = getattr(unreal, python_name, None)
    item["pythonWrapper"] = wrapper is not None
    if wrapper is not None:
        item["wrapperDoc"] = getattr(wrapper, "__doc__", "")
        item["wrapperNames"] = sorted(name for name in dir(wrapper) if not name.startswith("_"))
        item["staticClass"] = capture("staticClass", lambda wrapped=wrapper: str(wrapped.static_class()))
        item["defaultObjectNames"] = capture(
            "defaultObjectNames",
            lambda wrapped=wrapper: sorted(name for name in dir(unreal.get_default_object(wrapped)) if not name.startswith("_")),
        )
    result[python_name] = item

with open(OUTPUT, "w", encoding="utf-8") as stream:
    json.dump(result, stream, indent=2, sort_keys=True)

unreal.log("Wrote Niagara reflection dump: {}".format(OUTPUT))
