"""Normalize partial Niagara exports without inventing simulation behavior."""

from dataclasses import asdict, dataclass


def _struct(value):
    while isinstance(value, dict) and "StructType" in value:
        value = value["StructType"]
    return value if isinstance(value, dict) else {}


def object_path(value):
    """Read an object reference, preserving its package and object identity."""
    if isinstance(value, dict):
        value = value.get("ObjectPath") or value.get("ObjectName")
    if not isinstance(value, str):
        return None
    value = value.strip().replace("\\", "/")
    if "'" in value:
        value = value.split("'", 2)[1]
    if not value or value.casefold() == "none":
        return None
    return value if value.startswith("/") or "/content/" in value.casefold() else None


def _properties(export):
    return {p["name"]: p.get("value") for p in export.get("properties", [])
            if isinstance(p, dict) and p.get("name") and p.get("status") != "unreadable"}


def _array(value):
    return value if isinstance(value, (list, tuple)) else ()


@dataclass(frozen=True)
class ExportIdentity:
    index: int
    name: str
    type: str
    path: str
    status: str


@dataclass(frozen=True)
class Emitter:
    source: ExportIdentity
    renderer_paths: tuple[str, ...]
    spawn_script: str | None
    update_script: str | None
    gpu_script: str | None


@dataclass(frozen=True)
class Script:
    source: ExportIdentity
    usage: str | None


@dataclass(frozen=True)
class MeshEntry:
    index: int
    mesh_path: str


@dataclass(frozen=True)
class Renderer:
    source: ExportIdentity
    emitter_path: str
    meshes: tuple[MeshEntry, ...]
    override_materials: bool | None
    material_paths: tuple[str | None, ...]


@dataclass(frozen=True)
class ResourceReference:
    renderer_path: str
    renderer_export: int
    emitter_path: str
    mesh_index: int


@dataclass(frozen=True)
class MeshResource:
    mesh_path: str
    material_paths: tuple[str | None, ...]
    references: tuple[ResourceReference, ...]


@dataclass(frozen=True)
class NiagaraPackage:
    asset_path: str
    systems: tuple[ExportIdentity, ...]
    emitters: tuple[Emitter, ...]
    scripts: tuple[Script, ...]
    renderers: tuple[Renderer, ...]
    resources: tuple[MeshResource, ...]
    limitations: tuple[str, ...]
    warnings: tuple[str, ...]

    def manifest(self):
        """Compact source relationships; never embed opaque variable payloads."""
        return asdict(self)


def decode_package(report, asset_path):
    """Project the bridge report into a backend-independent resource model.

    Every mesh/material variant keeps all of its renderer and emitter sources.
    Missing fields stay unknown. Only explicitly enabled material overrides are
    used; unresolved dynamic bindings fall back to the mesh's own material slot.
    """
    if not isinstance(report, dict) or not isinstance(report.get("exports"), list):
        raise ValueError("The bridge returned no Niagara package exports.")
    systems, emitters, scripts, renderers, warnings = [], [], [], [], []
    resources = {}
    for export in report["exports"]:
        kind = export.get("type", "")
        source = ExportIdentity(
            int(export["exportIndex"]), str(export.get("name", "")), kind,
            object_path(export.get("fullName")) or f"export:{export['exportIndex']}",
            export.get("propertyStatus", "partial"),
        )
        props = _properties(export)
        if kind == "NiagaraSystem":
            systems.append(source)
        elif kind == "NiagaraEmitter":
            emitters.append(Emitter(
                source,
                tuple(path for ref in _array(props.get("RendererProperties")) if (path := object_path(ref))),
                object_path(_struct(props.get("SpawnScriptProps")).get("Script")),
                object_path(_struct(props.get("UpdateScriptProps")).get("Script")),
                object_path(props.get("GPUComputeScript")),
            ))
        elif kind == "NiagaraScript":
            scripts.append(Script(source, props.get("Usage")))
        elif kind.endswith("RendererProperties"):
            owner = source.path.rsplit(".", 1)[0]
            enabled = props.get("bOverrideMaterials")
            enabled = enabled if isinstance(enabled, bool) else None
            materials = tuple(object_path(_struct(value).get("ExplicitMat"))
                              for value in _array(props.get("OverrideMaterials")))
            meshes = []
            if kind == "NiagaraMeshRendererProperties":
                if enabled is None:
                    warnings.append(f"{source.name}: material override mode is unreadable; mesh materials are used.")
                if enabled and "OverrideMaterials" not in props:
                    warnings.append(f"{source.name}: material overrides are unreadable; mesh materials are used.")
                for index, value in enumerate(_array(props.get("Meshes"))):
                    mesh = object_path(_struct(value).get("Mesh"))
                    if mesh is None:
                        warnings.append(f"{source.name}: mesh entry {index} has no readable mesh reference.")
                        continue
                    meshes.append(MeshEntry(index, mesh))
                    overrides = list(materials if enabled else ())
                    # None is a per-slot fallback, including trailing empty
                    # overrides. Preserve leading/interior slots and their order.
                    while overrides and overrides[-1] is None:
                        overrides.pop()
                    key = (mesh.casefold(), tuple(p.casefold() if p else None for p in overrides))
                    if key not in resources:
                        resources[key] = [mesh, tuple(overrides), []]
                    resources[key][2].append(ResourceReference(source.path, source.index, owner, index))
                if not meshes:
                    warnings.append(f"{source.name}: no readable mesh entries.")
            renderers.append(Renderer(source, owner, tuple(meshes), enabled, materials))
    if not systems:
        raise ValueError("The selected package contains no NiagaraSystem export.")
    return NiagaraPackage(
        asset_path, tuple(systems), tuple(emitters), tuple(scripts), tuple(renderers),
        tuple(MeshResource(mesh, materials, tuple(refs)) for mesh, materials, refs in resources.values()),
        tuple(str(value) for value in report.get("limitations", [])), tuple(dict.fromkeys(warnings)),
    )
