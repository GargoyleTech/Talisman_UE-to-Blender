"""Static map camera viewpoints; cinematic evaluation remains a separate workflow."""

import json
import math

import bpy

from .lights import apply_component_visibility, bool_or_default, float_or_default


def _positive(value, default):
    number = float_or_default(value, default)
    return number if math.isfinite(number) and number > 0 else default


def create_camera_object(name, props, collection, location_scale=0.01, cine=False):
    data = bpy.data.cameras.new(name)
    data.sensor_fit = "HORIZONTAL"
    aspect = _positive(props.get("AspectRatio"), 16 / 9)
    fov = min(179.0, max(0.01, _positive(props.get("FieldOfView"), 90.0)))
    filmback = props.get("Filmback") or props.get("FilmbackSettings") or {}
    focal = _positive(props.get("CurrentFocalLength"), 35.0) if cine else 0.0
    width = _positive(filmback.get("SensorWidth"), 0.0)
    height = _positive(filmback.get("SensorHeight"), 0.0)
    if not width:
        # Older cooked cine instances may retain FoV/focal length but omit
        # their preset filmback. Preserve both by deriving the effective width.
        width = 2 * focal * math.tan(math.radians(fov) / 2) if focal and "FieldOfView" in props else (23.76 if cine else 36.0)
    height = height or width / aspect
    data.sensor_width, data.sensor_height = width, height
    data.lens = focal or width / (2 * math.tan(math.radians(fov) / 2))
    data.clip_start = max(0.00001, 10 * location_scale)
    data.clip_end = max(data.clip_start + 0.001, 100000 * location_scale)
    mode = props.get("ProjectionMode", "Perspective")
    if mode == 1 or str(mode).rsplit("::", 1)[-1].casefold() == "orthographic":
        data.type = "ORTHO"
        data.ortho_scale = _positive(props.get("OrthoWidth"), 512.0) * location_scale
    if bool_or_default(props.get("bOverride_CustomNearClippingPlane")):
        data.clip_start = max(0.00001, _positive(props.get("CustomNearClippingPlane"), 10) * location_scale)
    if data.type == "ORTHO":
        data.clip_start = max(0.00001, float_or_default(props.get("OrthoNearClipPlane"), 0) * location_scale)
        data.clip_end = max(data.clip_start + 0.001, _positive(props.get("OrthoFarClipPlane"), 2097152) * location_scale)
    if cine:
        data.dof.aperture_fstop = _positive(props.get("CurrentAperture"), 2.8)
        focus = props.get("FocusSettings") or {}
        method = str(focus.get("FocusMethod", "")).rsplit("::", 1)[-1].casefold()
        distance = _positive(props.get("CurrentFocusDistance"), 0.0) or _positive(focus.get("ManualFocusDistance"), 0.0)
        # Disabled/DoNotOverride must not enable DoF just because a distance
        # was serialized. Tracking is retained as metadata, not executed.
        data.dof.use_dof = method in {"manual", "1"} and distance > 0
        if distance:
            data.dof.focus_distance = distance * location_scale
        lens_settings = props.get("LensSettings") or {}
        blades = int(float_or_default(lens_settings.get("DiaphragmBladeCount"), 0))
        if blades >= 3:
            data.dof.aperture_blades = min(16, blades)
    obj = bpy.data.objects.new(name, data)
    collection.objects.link(obj)
    obj["ue_camera_aspect_ratio"] = width / height if cine and filmback else aspect
    obj["ue_camera_constrain_aspect_ratio"] = bool_or_default(props.get("bConstrainAspectRatio"))
    obj["ue_camera_field_of_view"] = math.degrees(2 * math.atan(data.sensor_width / (2 * data.lens)))
    if "FieldOfView" in props:
        obj["ue_camera_authored_field_of_view"] = fov
    obj["ue_camera_filmback_fallback"] = bool(cine and not filmback and "FieldOfView" not in props)
    obj["ue_camera_settings"] = json.dumps({k:props[k] for k in ("Filmback", "FilmbackSettings", "LensSettings", "FocusSettings") if k in props})
    apply_component_visibility(obj, props)
    return obj
