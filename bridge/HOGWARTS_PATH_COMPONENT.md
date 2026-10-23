# Hogwarts Legacy PathComponent

`/Script/PathRuntime.PathComponent` is explicitly normalized to `SplineComponent`
by the generic UMAP exporter. Although CUE4Parse reads it as `UObject`, its
serialized `SplineCurves` use the ordinary Unreal spline contract. This alias
does not match `PathFollowingComponent` or arbitrary classes ending in
`PathComponent`.

The existing **Import splines** option creates an editable 3D Bezier Curve in
the map's `_Splines` collection. Cooked tangents, input-key intervals, loop
settings, component transforms and attachments use the shared spline importer.
`SourceType` remains `PathComponent`. `LinearizedPath` and `UUID` are retained
in the Curve's `ue_spline_properties` JSON; the sampled cache does not replace
the authored curve. Quaternion/XYZ-scale curves remain metadata, and game
movement/path-following behavior is not executed.

## Installed-game validation, 20 October 2026

All **571 PathComponent exports across 154 installed Hogwarts Legacy maps**
were checked through the bundled bridge and imported in Blender 5.0.1, with
mesh and light imports disabled. They produced 571 Curves, 9,181 authored
control points and 18 closed paths. Every expected export was present.

The live test checked component identities, metadata, attachment parents,
local/world transform agreement, control points and sampled Hermite/Bezier
agreement. Maximum measured local-space shape error was **0.000091553 meters**
(approximately 0.092 mm at the standard 0.01 import scale).

The shared numeric/placement/options fixture also passed in Blender 4.5.3.
GeometryTests verified the PathComponent alias and rejection of pathfinding
and unfamiliar path-class names. No version number was changed.

Reproduce the live test with private local credentials and an inventory whose
`maps` list contains each `path` and a `types` class-count dictionary:

```powershell
blender --background --factory-startup --python-exit-code 2 `
  --python bridge/blender_spline_game_test.py -- `
  --config <private-config.json> --game hogwarts_legacy `
  --source-type PathComponent --inventory <map-inventory.json> `
  --report <test-report.json> --save-blend <test-scene.blend>
```

This updates the implementation relative to the 19 October class audit, where
PathComponent was still listed as an unsupported provisional candidate.
