# Hi-Fi Rush StaticMesh header

Use `GAME_UE4_27` for the tested Steam build. The title's native mesh format
conditionally serializes `BodySetup` using the tagged `bTngUseBodySetup`
property. When that property is false, the BodySetup index is absent; the
next index resolves to a `NavCollision` export. LightingGuid, sockets and
ordinary cooked render data follow it.

CUE4Parse and CUE4Parse-Conversion were updated from `1.2.2.202608` to
`1.2.2.202610`. The updated upstream reader still consumes BodySetup
unconditionally. This moves the subsequent reads four bytes past their
correct positions, producing invalid Boolean values in the LOD/render-data
reader or an invalid FName index (often 3081) in per-platform screen sizes.

`UHifiRushStaticMesh` recognizes the exact UE4.27 property/false combination
and reads that header, retaining the correct null BodySetup and NavCollision
reference. It uses CUE4Parse's ordinary render-data and vertex/index readers,
then reads occluder, SpeedTree and material metadata. Other meshes continue
through the upstream reader. Registration is limited to generic sessions;
the FF7 title adapters retain their existing readers.

The Stage 4 inventory and its referenced sublevels contain 1,230 unique static
meshes. Both the August and October upstream builds read 1,121 and fail 109.
The corrected reader reads all 1,230; the previous successes have identical
hashes over their decoded LOD attributes, indices, section ranges and material
references. The recovered assets account for 522 placements across 24 maps.
Every recovered LOD was checked for finite attributes, matching buffer sizes,
valid indices and valid section/material ranges.

`blender_generic_mesh_decode_test.py` retries an ignored baseline manifest
through the actual bridge, binary geometry loader and Blender mesh importer.
The manifest is an array containing `path` and `status`; entries whose status
is not `readable` are retried. It verifies geometry counts, coordinates, UV
sets and material assignment without embedding game data or keys in source:

```text
blender --background --factory-startup --threads 4 --python-exit-code 2
  --python bridge/blender_generic_mesh_decode_test.py --
  --config <private-config.json> --game hi_fi_rush
  --baseline <geometry.json> --report <report.json>
```

All 109 previously failing meshes imported in Blender 5.1.2 (3,320,441
vertices and 2,628,886 triangles at their first usable LOD). Registered map
operator tests cover St04_Rail02_Env in Blender 5.1.2 and St04_ARLabo01_Env
in Blender 4.5.3, plus St04_Drill_GD's rigid and skeletal components in 5.1.2.
These tests reported no missing mesh assets. Spline deformation and custom
poseable components identified by the separate component audit still need
their own import support.
