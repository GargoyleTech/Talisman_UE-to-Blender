"""Editable Unreal path splines, with cooked Hermite tangents preserved."""

import json
import math

import bpy
from mathutils import Matrix, Vector


_SPLINE_PROPERTIES = (
    "SplineCurves", "SplineInfo", "SplineRotInfo", "SplineScaleInfo",
    "bClosedLoop", "bLoopPositionOverride", "LoopPosition", "DefaultUpVector",
    "Duration", "ReparamStepsPerSegment", "bStationaryEndpoints", "bAllowDiscontinuousSpline",
    "SplineParams", "SplineUpDir", "ForwardAxis", "SplineBoundaryMin", "SplineBoundaryMax",
    "bSmoothInterpRollScale", "StaticMesh", "OverrideMaterials",
    "SplineReparamTable", "SplineColor", "m_SplineReparamRateToDistance", "m_qBaseQuat", "m_qNextQuat",
    "LinearizedPath", "UUID",
)


def _number(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Spline coordinates and keys must be finite")
    return result


def _vector(value, scale):
    value = value if isinstance(value, dict) else {}
    return Vector((_number(value.get("X", 0)), -_number(value.get("Y", 0)),
                   _number(value.get("Z", 0)))) * scale


def _mode(point):
    mode = point.get("InterpMode", "CIM_CurveAuto")
    if isinstance(mode, int):
        return {0: "CIM_Linear", 2: "CIM_Constant"}.get(mode, "CIM_CurveUser")
    return str(mode).rsplit("::", 1)[-1]


def _point_runs(points, closed):
    """Split constant-interpolation jumps instead of drawing false connectors."""
    count = len(points)
    edge_count = count if closed else count - 1
    breaks = {i for i in range(edge_count) if _mode(points[i]) == "CIM_Constant"}
    if not breaks:
        return [(list(range(count)), closed)]
    start = (min(breaks) + 1) % count if closed else 0
    indices = [(start + i) % count for i in range(count)]
    runs, run = [], []
    for index in indices:
        run.append(index)
        if index in breaks:
            runs.append((run, False))
            run = []
    if run:
        runs.append((run, False))
    return runs


def create_spline(entry, name, collection, location_scale):
    """Return a local-space Curve; the map importer applies component transforms.

    Unreal tangents are derivatives with respect to the input key. Multiplying
    each by its segment's key interval / 3 gives exact cubic Bezier handles,
    including broken tangents and nonuniform input keys. Cooked auto tangents
    stay FREE so Blender cannot recalculate a different path.
    """
    props = entry.get("Properties") or {}
    curves = props.get("SplineCurves") or {}
    position = curves.get("Position") or props.get("SplineInfo") or {}
    source_type = entry.get("SourceType") or entry.get("Type")
    is_brush = source_type == "EndSplineBrushComponent"
    is_mesh_span = entry.get("Type") == "SplineMeshComponent"
    if is_mesh_span:
        params = props.get("SplineParams") or {}
        if not params:
            return None
        position = {"Points": [
            {"InVal": 0, "OutVal": params.get("StartPos", {}),
             "LeaveTangent": params.get("StartTangent", {}), "InterpMode": "CIM_CurveUser"},
            {"InVal": 1, "OutVal": params.get("EndPos", {}),
             "ArriveTangent": params.get("EndTangent", {}), "InterpMode": "CIM_CurveUser"},
        ]}
    points = position.get("Points") or []
    if not points:
        return None
    keys = [_number(point.get("InVal", i)) for i, point in enumerate(points)]
    if any(right <= left for left, right in zip(keys, keys[1:])):
        raise ValueError("Spline input keys must be strictly increasing")
    coords = [_vector(point.get("OutVal"), location_scale) for point in points]
    # Rebirth's brush-authoring outlines bound closed volumes, but their cooked
    # instances omit bClosedLoop. Apply that class-specific boundary convention
    # without changing ordinary paths or overriding explicit serialized flags.
    closed = not is_mesh_span and bool(props.get("bClosedLoop", position.get("bIsLooped", is_brush)))
    loop_interval = _number(position.get("LoopKeyOffset", 1))
    if props.get("bLoopPositionOverride") and "LoopPosition" in props:
        loop_interval = _number(props["LoopPosition"]) - keys[-1]
    if closed and loop_interval <= 0:
        raise ValueError("Spline loop key must follow the final input key")
    runs = _point_runs(points, closed)

    curve = bpy.data.curves.new(name, "CURVE")
    obj = None
    try:
        curve.dimensions = "3D"
        curve.resolution_u = 12
        curve.twist_mode = "MINIMUM"
        # UE attachment to a spline uses the component transform. Blender's
        # path animation would additionally move children along the curve.
        curve.use_path = False
        for indices, cyclic in runs:
            spline = curve.splines.new("BEZIER")
            spline.bezier_points.add(len(indices) - 1)
            spline.use_cyclic_u = cyclic
            for point, index in zip(spline.bezier_points, indices):
                point.handle_left_type = point.handle_right_type = "FREE"
                point.co = coords[index]
                point.handle_left = point.handle_right = coords[index]
            pairs = list(zip(range(len(indices) - 1), range(1, len(indices))))
            if cyclic:
                pairs.append((len(indices) - 1, 0))
            for left, right in pairs:
                i, j = indices[left], indices[right]
                interval = keys[j] - keys[i] if j > i else loop_interval
                if _mode(points[i]) == "CIM_Linear":
                    tangent = (coords[j] - coords[i]) / 3
                    leave, arrive = tangent, tangent
                else:
                    leave = _vector(points[i].get("LeaveTangent"), location_scale) * (interval / 3)
                    arrive = _vector(points[j].get("ArriveTangent"), location_scale) * (interval / 3)
                spline.bezier_points[left].handle_right = coords[i] + leave
                spline.bezier_points[right].handle_left = coords[j] - arrive

        # Blender's radius/tilt cannot represent UE's full XYZ scale and
        # quaternion rotation curves. Retain the original data for deformation
        # instead of silently reducing it to scalar radius/roll values.
        curve["ue_spline_properties"] = json.dumps(
            {key: props[key] for key in _SPLINE_PROPERTIES if key in props},
            ensure_ascii=False, separators=(",", ":"),
        )
        curve["ue_spline_point_indices"] = json.dumps([indices for indices, _ in runs])
        curve["ue_spline_coordinate_scale"] = location_scale
        curve["ue_spline_schema"] = 1
        world_space = ((entry.get("SourceType") or entry.get("Type")) == "SQEX_SplineComponent"
                       and bool(props.get("SplineInfo")) and not curves.get("Position"))
        curve["ue_spline_authored_space"] = "WORLD" if world_space else "LOCAL"
        obj = bpy.data.objects.new(name, curve)
        obj["source_type"] = entry.get("SourceType") or entry.get("Type") or "SplineComponent"
        obj["ue_spline_closed_loop"] = closed
        obj["ue_spline_point_count"] = len(points)
        obj["ue_spline_kind"] = "MESH_SPAN" if is_mesh_span else "PATH"
        if is_brush:
            obj["ue_spline_closed_loop_inferred"] = "bClosedLoop" not in props and "bIsLooped" not in position
            tag_brush_outline(obj, entry)
        collection.objects.link(obj)
        return obj
    except Exception:
        if obj is not None:
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.curves.remove(curve)
        raise


def tag_brush_outline(obj, entry):
    """Keep volume identity on both editable curves and empty-outline helpers."""
    if (entry.get("SourceType") or entry.get("Type")) != "EndSplineBrushComponent":
        return
    owner = entry.get("SplineBrushOwner") or {}
    obj["ue_spline_kind"] = "VOLUME_OUTLINE"
    obj["ue_spline_brush_owner"] = json.dumps(owner, ensure_ascii=False, separators=(",", ":"))
    obj["ue_volume_type"] = owner.get("Type") or ""
    if obj.type == "EMPTY":
        obj["ue_spline_point_count"] = 0
        obj["ue_spline_empty_reason"] = "No serialized outline points; cooked brush may still contain a volume"


def finalize_world_space_paths(objects):
    """Localize legacy SQEX points/handles while keeping their root hierarchy."""
    paths = [obj for obj in objects if obj.type == "CURVE"
             and obj.data.get("ue_spline_authored_space") == "WORLD"
             and not obj.data.get("ue_spline_localized")]
    if not paths:
        return
    bpy.context.view_layer.update()
    for obj in paths:
        try:
            inverse = obj.matrix_world.inverted()
        except ValueError:
            # A zero-scale parent cannot represent a world-space path. Keep
            # readable geometry and record why this one could not be attached.
            obj["ue_spline_attachment_warning"] = "Singular parent transform; world path retained without parent"
            obj.parent = None
            obj.matrix_world = Matrix.Identity(4)
            inverse = Matrix.Identity(4)
        obj.data.transform(inverse)
        obj.data["ue_spline_localized"] = True
