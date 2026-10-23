# Authored spline paths

All package UMAP imports, including SQEX titles, have an independent **Import splines** switch
(enabled by default). It works with **Import models** disabled and follows the
same selected maps and recursive streaming-level queue. Curves are placed in
each map's `_Splines` collection, under that map's origin.

`SplineComponent` and native subclasses whose names end in `SplineComponent`
(including Hi-Fi Rush's `TngSplineComponent`) become editable 3D Bezier curves.
Their component transforms, parent attachments, input points, cooked arrive/leave
tangents, nonuniform input keys and closed loops are retained. Curve handles are
free handles: Blender must not recalculate Unreal's cooked auto tangents.
Blender path animation is disabled so attached spans inherit only the authored
component transform, without an extra offset along the parent curve.
Linear spans remain straight; constant-interpolation jumps are split into
disconnected splines so the importer does not invent connecting geometry.

Hogwarts Legacy's `PathRuntime.PathComponent` is an explicit alias for this
same converter. It uses authored `SplineCurves.Position` points and cooked
tangents; `LinearizedPath` and `UUID` are retained in `ue_spline_properties`
as source metadata. The sampled linearized path does not replace the authored
Bezier shape. This does not run the game's path-following or movement logic.

The source uses Unreal coordinates; the Blender points/handles use `(X, -Y, Z)`
multiplied by the import scale. For each Hermite span, the Bezier handles are
`P0 + LeaveTangent0 * key_interval / 3` and
`P1 - ArriveTangent1 * key_interval / 3`. Closing spans use the serialized loop
key interval, including an explicit loop-position override when present.

The Curve datablock retains:

- `ue_spline_properties`: JSON containing the original `SplineCurves` (position,
  quaternion rotation, XYZ scale and reparameterization data) and serialized
  spline settings, including the default up vector. Older `SplineInfo`,
  `SplineRotInfo` and `SplineScaleInfo` are retained when present.
- `ue_spline_point_indices`: JSON mapping each Blender spline's control points
  to the original position-curve indices, including split constant spans.
- `ue_spline_coordinate_scale` and `ue_spline_schema` (currently `1`).

Objects carry the normal map/component source identities plus
`ue_spline_closed_loop` and `ue_spline_point_count`. Quaternion rotation and XYZ
scale curves are retained as source data for a future deformation system;
Blender's scalar tilt/radius are left at their defaults. No bevel or mesh is
generated. Empty paths without serialized points are logged and retained as
transform empties, so their children keep the correct placement. Disabling the
spline switch also retains transform nodes needed by mesh/light imports.

`SplineMeshComponent` and native subclasses (including `HbkSplineMeshComponent`)
also import as curves, using the exact two-point Hermite span in `SplineParams`.
Their source mesh, material overrides, up direction, forward axis, boundaries
and roll/scale interpolation settings are retained in `ue_spline_properties`
when serialized. `ue_spline_kind` distinguishes `PATH` from `MESH_SPAN` objects.
Deformed mesh geometry is still separate work; these centerlines have no mesh
or modifier attached yet. Spans preserve their attachment to longer path curves.

Run `bridge/blender_spline_import_test.py` in background Blender for numeric
Hermite/Bezier, transform, attachment, loop, interpolation and import-option
coverage. The bridge GeometryTests cover native subclass classification.

## Rebirth brush outlines

`EndSplineBrushComponent` imports through **Import splines** on both the Rebirth
title route and the generic route. It creates editable Bezier outlines in the
map's `_Splines` collection, independently of mesh/light import. Authored linear
edges remain straight, including the closing edge. These are outlines for
streaming, location, minimap, water and gameplay volumes; no volume mesh or
rendered water surface is generated.

The brush class defaults to a closed boundary when serialized loop flags are
absent. Explicit `bClosedLoop`/`bIsLooped` values take precedence. Objects record
`ue_spline_closed_loop_inferred` so this class-specific convention is visible
without fabricating a flag in the original `ue_spline_properties` data.
Ordinary spline defaults are unchanged.

Points remain local to the spline component, with their complete brush-parent
attachment chain. This preserves the reciprocal child/parent scales used by
some minimap volumes. Transform-only ancestor Empties are grouped with the
outlines in `_Splines`. `ue_spline_kind` is `VOLUME_OUTLINE`; `ue_volume_type`
identifies the owning class, and `ue_spline_brush_owner` stores its identity
and cooked `Brush` reference as JSON. An outline without points remains an
Empty with the same owner/reference and an explanatory `ue_spline_empty_reason`;
its separate cooked brush can still contain a valid solid volume.

`bridge/blender_rebirth_spline_brush_test.py` exercises installed maps through
the Rebirth title exporter and the shared importer. The SQEX spline fixture
also covers raw/normalized aliases, reciprocal scales, inferred/explicit
closure, empty outlines and the disabled spline option.

Installed-game validation in Blender 5.0.1 covered all 985 components across
110 Rebirth maps: 984 closed curves, one tagged Empty and 10,981 control points.
Maximum measured world-point error was 0.000977 meters; maximum sampled local
linear-edge error was 0.001092 meters. The SQEX fixture passed in Blender 4.5.3.

## Kingdom Hearts SQEX splines

`SQEX_SplineComponent` uses the shared curve converter, including its older
`SplineInfo` position curve. `SQEX_SplineRootComponent` becomes a transform
Empty in the map's `_Splines` collection. Both the explicit KH profile routes
and generic component normalization retain the original `SourceType`.
The spline switch works independently of model and light import on all title
operators, and required attachment ancestors are retained in spline-only mode.
With curves disabled, their transform nodes remain available to other imports.

The inspected KH III rail and KH 0.2 camera paths store their legacy
`SplineInfo` points and tangents in **world space**. Their first points match
their root locations even when those roots have nontrivial rotation and scale.
Applying both raw points and the root matrix would displace/deform the path
twice. The importer converts this legacy geometry into local space after the
complete attachment chain is resolved, preserving its original world shape
and its editable root hierarchy. Modern `SplineCurves.Position` data continues
to follow the ordinary local-space path.

`ue_spline_authored_space` identifies the retained source coordinate space;
`ue_spline_localized` records the completed world-to-local conversion. Original
`SplineInfo`, `SplineReparamTable`, `SplineColor`,
`m_SplineReparamRateToDistance`, `m_qBaseQuat` and `m_qNextQuat` values are retained
when present. Rotation/reparameterization controls are metadata; this does not
execute KH camera, movement or rail-riding logic. A singular attachment matrix
cannot represent a world-space path; that case retains readable geometry
without its parent and records an object warning.

`bridge/blender_sqex_splines_streaming_test.py` checks raw and normalized aliases,
world-space Hermite/Bezier agreement under rotated/nonuniform roots, root edits,
disabled curves, and recursive Kismet-to-spline-only import through a registered
title operator. It passes in Blender 4.5.3 and 5.0.1. Installed-game checks covered
28 curves and 35 roots across KH III/KH 0.2 samples; the largest measured
world-curve discrepancy was approximately 0.000062 meters.
