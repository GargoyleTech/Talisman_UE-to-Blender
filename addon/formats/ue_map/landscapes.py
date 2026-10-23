"""Cooked Landscape heightfields, paint weights and bounded map import planning."""

import hashlib
import json
from pathlib import Path

import bpy
import numpy as np

from ...core.blender.mesh_geometry import populate_triangle_mesh


OPTION_NAMES = ("import_landscapes", "landscape_lod", "max_landscape_vertices", "landscape_layer_preview")


def import_options(operator):
    defaults = (True, 1, 2_000_000, False)
    return {name: getattr(operator, name, default) for name, default in zip(OPTION_NAMES, defaults)}


def component_quads(info, lod):
    sub, sections = info.get("subsectionQuads"), info.get("subsections")
    if (type(sub) is not int or type(sections) is not int or sections not in (1, 2)
            or not 1 <= sub <= 255 or (sub + 1) & sub or info.get("quads") != sub * sections):
        raise ValueError("Unsupported Landscape subsection topology.")
    return sections * max(1, ((sub + 1) >> lod) - 1)


def plan_lod(entries, requested=1, budget=2_000_000):
    """Choose one LOD for the map before creating any terrain components."""
    if type(requested) is not int or not 0 <= requested <= 7 or type(budget) is not int or budget < 0:
        raise ValueError("Invalid terrain LOD or vertex budget.")
    infos = [e["Landscape"] for e in entries if isinstance(e, dict) and e.get("Type") == "LandscapeComponent" and isinstance(e.get("Landscape"), dict)]
    for lod in range(requested, 8):
        count = sum((component_quads(info, lod) + 1) ** 2 for info in infos)
        if not budget or count <= budget:
            return lod, count
    raise ValueError(f"Terrain needs at least {count:,} vertices; increase the terrain vertex budget or set it to zero.")


def load_landscape(payload, output_root):
    """Load only complete, bounded streams belonging to this bridge request."""
    manifest = payload.get("binaryLandscape") or {}
    q, vertices = payload.get("quads"), payload.get("vertexCount")
    layers = payload.get("layers")
    if (manifest.get("version") != 1 or type(q) is not int or not 1 <= q <= 510
            or type(vertices) is not int or vertices != (q + 1) ** 2
            or not isinstance(layers, list) or len(layers) > 256 or any(not isinstance(layer, dict) for layer in layers)):
        raise ValueError("Invalid Landscape stream metadata; rebuild the matching bridge.")
    root = Path(output_root).resolve()
    directory = Path(manifest.get("directory", "")).resolve()
    if directory.parent != root:
        raise ValueError("Terrain directory is outside this request's output folder.")
    allowed = {"positions": ("<f4", [vertices, 3]), "normals": ("<f4", [vertices, 3]),
               "holes": ("|u1", [q, q]), **{f"paint{i}": ("|u1", [vertices]) for i in range(len(layers))}}
    streams = manifest.get("streams") or {}
    if streams.keys() != allowed.keys():
        raise ValueError("Landscape streams are incomplete or unexpected.")
    result = {k: v for k, v in payload.items() if k != "binaryLandscape"}
    for name, (dtype, shape) in allowed.items():
        descriptor = streams[name]
        if (descriptor.get("dtype"), descriptor.get("shape")) != (dtype, shape):
            raise ValueError(f"Invalid terrain stream descriptor: {name}.")
        path = (directory / descriptor["file"]).resolve()
        count = int(np.prod(shape, dtype=np.int64))
        if path.parent != directory or path.suffix != ".bin" or path.stat().st_size != count * np.dtype(dtype).itemsize:
            raise ValueError(f"Invalid or incomplete terrain stream: {name}.")
        values = np.fromfile(path, dtype=dtype, count=count).reshape(shape)
        if values.dtype.kind == 'f' and not np.isfinite(values).all():
            raise ValueError(f"Non-finite terrain stream: {name}.")
        result[name] = values
    holes = result["holes"]
    if np.any(holes > 1) or payload.get("triangleCount") != 2 * (q * q - int(holes.sum())):
        raise ValueError("Terrain hole mask and triangle count disagree.")
    return result


def _material(layers, preview):
    identities = [(layer.get('name'), layer.get('path')) for layer in layers] if preview else []
    key = hashlib.sha256(json.dumps([preview, identities]).encode()).hexdigest()
    name = "UE terrain " + ("layer preview " if preview else "neutral ") + key[:12]
    material = bpy.data.materials.get(name)
    if material is not None and material.get("ue_landscape_material_key") == key:
        return material
    material = bpy.data.materials.new(name)
    material["ue_landscape_material_key"] = key
    material["ue_landscape_material_mode"] = "LAYER_PREVIEW" if preview else "NEUTRAL"
    material.diffuse_color = (.28, .33, .27, 1)
    material.use_nodes = True
    nodes, links = material.node_tree.nodes, material.node_tree.links
    bsdf = next(n for n in nodes if n.type == 'BSDF_PRINCIPLED')
    bsdf.inputs['Base Color'].default_value = material.diffuse_color
    bsdf.inputs['Roughness'].default_value = .9
    if preview and layers:
        total = colour = None
        for i, layer in enumerate(layers):
            attribute = nodes.new('ShaderNodeAttribute'); attribute.attribute_name = f"ue_landscape_weight_{i:03}"
            attribute.label = str(layer.get('name') or layer.get('path') or i)
            digest = hashlib.sha256(str(layer.get('path') or layer.get('name') or i).encode()).digest()
            scale = nodes.new('ShaderNodeVectorMath'); scale.operation = 'SCALE'
            scale.inputs[0].default_value = tuple(.12 + value / 255 * .6 for value in digest[:3])
            links.new(attribute.outputs['Fac'], scale.inputs['Scale'])
            if total is None:
                total, colour = attribute.outputs['Fac'], scale.outputs['Vector']
            else:
                add = nodes.new('ShaderNodeMath'); add.operation = 'ADD'; links.new(total, add.inputs[0]); links.new(attribute.outputs['Fac'], add.inputs[1]); total = add.outputs[0]
                add_colour = nodes.new('ShaderNodeVectorMath'); add_colour.operation = 'ADD'; links.new(colour, add_colour.inputs[0]); links.new(scale.outputs['Vector'], add_colour.inputs[1]); colour = add_colour.outputs[0]
        denominator = nodes.new('ShaderNodeMath'); denominator.operation = 'MAXIMUM'; denominator.inputs[1].default_value = .0001; links.new(total, denominator.inputs[0])
        reciprocal = nodes.new('ShaderNodeMath'); reciprocal.operation = 'DIVIDE'; reciprocal.inputs[0].default_value = 1; links.new(denominator.outputs[0], reciprocal.inputs[1])
        normalize = nodes.new('ShaderNodeVectorMath'); normalize.operation = 'SCALE'; links.new(colour, normalize.inputs[0]); links.new(reciprocal.outputs[0], normalize.inputs['Scale'])
        links.new(normalize.outputs[0], bsdf.inputs['Base Color'])
    return material


def create_terrain(name, payload, collection, scale=.01, preview=False):
    q, count = payload['quads'], payload['vertexCount']
    positions = np.asarray(payload['positions'], dtype=np.float32).copy()
    positions *= (scale, -scale, scale)
    base = (np.arange(q, dtype=np.int32)[None, :] + np.arange(q, dtype=np.int32)[:, None] * (q + 1))[payload['holes'] == 0]
    triangles = np.empty((len(base) * 2, 3), dtype=np.int32)
    triangles[::2] = np.column_stack((base, base + q + 1, base + q + 2))
    triangles[1::2] = np.column_stack((base, base + q + 2, base + 1))
    mesh = bpy.data.meshes.new(name)
    obj = None
    try:
        populate_triangle_mesh(mesh, positions, triangles, smooth=True)
        if len(mesh.polygons):
            normals = np.asarray(payload['normals'], dtype=np.float32).copy(); normals[:, 1] *= -1
            mesh.normals_split_custom_set_from_vertices(normals)
        layers = payload['layers']
        for i, _layer in enumerate(layers):
            attribute = mesh.attributes.new(f'ue_landscape_weight_{i:03}', 'FLOAT', 'POINT')
            attribute.data.foreach_set('value', payload[f'paint{i}'].astype(np.float32) / 255)
        yy, xx = np.indices((q + 1, q + 1), dtype=np.float32)
        section = payload['sectionBase']; ratio = payload['sourceQuads'] / q
        for label, uv in [('TerrainLocal', np.column_stack((xx.ravel()/q, 1-yy.ravel()/q))),
                          ('LandscapeXY', np.column_stack((xx.ravel()*ratio+section[0], -(yy.ravel()*ratio+section[1]))))]:
            layer = mesh.uv_layers.new(name=label)
            layer.data.foreach_set('uv', uv[triangles.ravel()].ravel())
        mesh.materials.append(_material(layers, preview))
        mesh['ue_geometry_source'] = 'LANDSCAPE_HEIGHTFIELD'
        mesh['ue_landscape_layers'] = json.dumps(layers)
        mesh['ue_landscape_materials'] = json.dumps(payload.get('materials') or [])
        mesh['ue_landscape_material_context'] = json.dumps({key: payload.get(key) for key in
            ('overrideMaterial', 'overrideHoleMaterial', 'landscapeMaterial', 'landscapeHoleMaterial')})
        obj = bpy.data.objects.new(name, mesh); collection.objects.link(obj)
        obj['ue_geometry_source'] = 'LANDSCAPE_HEIGHTFIELD'; obj['ue_landscape_lod'] = payload['lod']
        obj['ue_landscape_source_quads'] = payload['sourceQuads']; obj['ue_landscape_section_base'] = section
        obj['ue_landscape_heightmap'] = payload['heightmap']; obj['ue_landscape_xy_offsets'] = payload['xyOffsets']
        obj['ue_landscape_hole_quads'] = payload['holeQuads']; obj['ue_landscape_hole_policy'] = payload['holePolicy']
        obj['ue_component_path'] = payload['objectPath']
        obj['ue_landscape_owner'] = payload.get('owner') or ''
        return obj
    except Exception:
        if obj is not None: bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.meshes.remove(mesh)
        raise
