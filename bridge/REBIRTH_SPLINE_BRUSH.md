# Rebirth EndSplineBrushComponent inspection

Inspected 20 October 2026 against the installed Rebirth packages and current
bundled CUE4Parse. The original inspection covered format and ownership;
curve support was subsequently implemented as described below. Solid volume
conversion remains separate work.

## FindingFro
`/Script/EndGame.EndSplineBrushComponent` supplies an authored outline for a
volume brush. Its curve data is straightforward, but its owning objects are
streaming, location, minimap, water and gameplay volumes. It is a useful
candidate for optional level-authoring/debug outlines. The observed exports
do not establish missing rendered roads, rails, vegetation or terrain meshes.

All **985 components across 110 maps** were deserialized and their ownership
and properties inspected. Those maps contained 39,085 exports in total; the
diagnostic export reported no package warnings. Native cooked brush data was
also inspected in **13 cases**: one per owning class plus the empty-curve case.

| Owning class | Components |
|---|---:|
| EndStreamingVolume | 246 |
| EndLocationVolume | 216 |
| EndChocoboJetSettingVolume | 156 |
| EndNaviMapVolume | 144 |
| EndFieldGridActor | 89 |
| EndCharaPopSwitchVolume | 59 |
| EndStreamingSwitchVolume | 32 |
| EndWaterVolume | 23 |
| EndStreamingHideVolume | 7 |
| EndShadowStreamVolume | 6 |
| EndNaviMapClearVolume | 6 |
| EndPartyChocoboRestrictedAreaVolume | 1 |

## Curve payload

CUE4Parse already deserializes the class as `USplineComponent`.
**984 components contain SplineCurves.Position**, with **10,981 control
points** in total. Every observed position key uses `CIM_Linear`; every
position has local Z = 0. This is an XY polygon outline rather than a curved
mesh-deformation path. All components attach to their owning brush component.

`bClosedLoop` is absent from all 985 serialized instances. The position curves
also omit explicit loop metadata in the inspected payloads. No component
templates were present in the 13 native probes. A stock open-spline default
must therefore not be treated as proof of the brush's closure semantics.
The stored solid brush topology is better evidence for the boundary.

There are 56 serialized component translations and 49 serialized component
scales. Some scales compensate for their parent brush scales: one inspected
minimap root has scale `(10240, 10240, 512)`, while its spline child has
`(1/10240, 1/10240, 1/512)`. Curve points belong to the spline component's
space; cooked brush points belong to the brush root's space. Applying the
same matrix to both would produce incorrect geometry.

## Cooked brush geometry

Owners reference a separate native `UModel` through `Brush`, and a
`BrushComponent` through `RootComponent`/`BrushComponent`. The model already
contains Points, Nodes, Surfs, Verts and Bounds, including vertical extent
that the flat spline does not encode. The inspected model data shows top and
bottom faces and side topology. The 124 sampled surface records have no
material reference; they are consistent with volume geometry rather than
ordinary rendered surfaces.

For example, the first streaming outline has seven spline points; its model
has 14 points and nine BSP surfaces, with local Z bounds of +/-50,000.
The sampled water outline has 28 points, but its model has 63 points and 38
surfaces. Generated BSP vertices are not necessarily original outline
control points. Faithful mesh recovery should read the cooked topology,
rather than assuming every model is just two copies of the control polygon.
All these coordinates are in their respective local Unreal spaces; parent
transforms must be applied before interpreting world dimensions.

One component has **no SplineCurves at all**:
`2240-CORLF_State_Level_NaviMap_Layer0`, actor
`NaviMap_2240-CORLF_Layer00_Open002_Visit005_1`. It still has a valid eight-point,
six-surface box model with local half extents `(1500, 2500, 750)`.
An empty spline must not be interpreted as an empty volume.

## Implementation assessment

An optional editable-outline import is a small extension of the shared spline
converter: add an explicit class route to the SQEX exporter and generic
normalizer, retain the brush attachment chain, tag the owning volume class,
and handle polygon closure deliberately. Empty outlines should retain their
transform/reference, with a separately identified cooked-brush fallback if
desired. There is no need to invent Hermite tangents for these linear keys.

A volume mesh importer is a separate feature: decode the model's face/index
relationships, use brush-root transforms, and preserve the owning volume's
role and references. Loading/unloading rules, minimap discovery, character
spawning, chocobo restrictions and water gameplay remain runtime metadata.
An outline or solid debug mesh does not implement those systems or create a
rendered water surface.

The original gap was an omitted Rebirth whitelist entry and generic alias:
its name does not end in SplineComponent, despite CUE4Parse recognizing its
native base type. Both routes now explicitly normalize it to SplineComponent.
Full support for the owning volumes is not claimed from adding that alias.

## Implemented curve support

The existing **Import splines** switch now imports these as editable local
Bezier outlines, including with models and lights disabled. Linear edges stay
straight. Missing loop flags use the closed-brush-boundary convention, marked
by `ue_spline_closed_loop_inferred`; explicit loop flags are respected.

The complete attachment chain preserves parent/child scale compensation.
`ue_spline_kind=VOLUME_OUTLINE`, `ue_volume_type` and the JSON
`ue_spline_brush_owner` identify the owning volume and its cooked brush.
The component with no point payload remains a tagged transform Empty rather
than inventing a curve from its separate box model.

No cooked brush mesh, volume gameplay or water surface is generated. Version
metadata is unchanged. Regression coverage includes raw and normalized input,
closing edges, explicit open overrides, reciprocal scales, empty outlines and
the disabled spline option. The installed-game test is
`bridge/blender_rebirth_spline_brush_test.py`.

Installed-game validation through the Rebirth title backend in Blender 5.0.1
passed for all 110 maps: **984 closed curves, one tagged Empty, 10,981 control
points**, and all twelve owner classes. Maximum measured world-point error was
0.000977 meters; maximum local sampled linear-edge error was 0.001092 meters.
The fixture passed in Blender 4.5.3, including disabled curves and the explicit
open-loop override. Local results and the saved scene are retained under
`.local/end-spline-brush/curve-tests/`.

Local reproducibility data is retained under `.local/end-spline-brush/`:
the complete component inventory, per-map diagnostic exports, summary,
native-probe source and thirteen native brush samples. Private AES input
configuration remains outside this note.
