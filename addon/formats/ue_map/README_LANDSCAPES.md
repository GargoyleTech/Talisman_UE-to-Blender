# Landscape terrain

Package UMAP import can reconstruct `LandscapeComponent` heightfields through the shared generic and SQEX map paths. Rebirth Massive Environment remains a separate importer.

The converter reads the stored cooked height texture, optional XY-offset texture, paint allocations and visibility layer. It builds indexed terrain meshes under the map's `_Terrain` collection, with attachment-aware placement, stored heightfield normals and two UV maps. Component/subsection atlas borders are handled without adding duplicate quads. Generated `LandscapeNaniteComponent` backing objects are excluded from rigid StaticMesh placement to avoid a second terrain representation.

## Controls

- **Import terrain** enables Landscape geometry while **Import models** is enabled.
- **Terrain LOD** defaults to `1`. `0` uses the full cooked component grid. Higher levels reduce the grid within each subsection while retaining component endpoints. The level is clamped to the smallest valid grid for each component.
- **Terrain vertex budget** defaults to `1,000,000` vertices per map. The importer chooses one planned LOD for the map, raising the requested level until all terrain components fit. It reports reductions in the console and stores the requested/planned level and budget on the terrain collection. `0` disables the budget. An impossible budget fails before terrain placement rather than silently dropping arbitrary tiles.
- **Preview painted layers** uses stable diagnostic layer colors. The default is a neutral material. Neither mode recreates the original Unreal landscape shader.

The terrain budget is per map, not a cap on the entire batch. Streaming maps can choose different LODs and their boundaries are not stitched across different resolutions. Use a consistent explicit LOD with budget `0` when a world requires uniform resolution and its size is known to fit.

Height/XY/mask textures are geometry data, so image-resolution and mip controls for ordinary model textures do not reduce their source precision. Terrain LOD controls the geometry output instead.

## Paint and source data

All non-visibility allocations are retained, including layers beyond the four RGBA channels of one texture. Paint weights are point-domain float attributes named `ue_landscape_weight_000`, `ue_landscape_weight_001`, etc. `mesh["ue_landscape_layers"]` maps these indices to source layer names, paths, weight textures/channels and non-weight-blended flags. Layer previews normalize colors for inspection; they do not implement the game's blend order or height blending.

`TerrainLocal` UVs cover the component from 0 to 1. `LandscapeXY` retains section-relative terrain coordinates before XY displacement, with V mirrored for Blender. Mesh metadata preserves the component material instances and actor/override material references. Object metadata records the source component/owner, height texture, section base, actual LOD, XY presence and hole policy.

At full resolution, the hole conversion follows the UE4 static-export rule: remove a quad when its top-left visibility sample is at least 170. Coarser terrain removes a quad if any full-resolution quad in its covered region is a hole. This conservatively preserves openings but can widen their edges; it is not an exact per-pixel opacity-mask or Nanite reconstruction. Fully masked components are valid meshes with no faces.

## Architecture and limits

`bridge/LandscapeExporter.cs` extracts typed, bounded binary streams. Its decoded terrain-texture cache is limited to 128 MiB and cleared at the batch-memory cleanup boundary. `PackageAssetSession.landscape_mesh` loads the arrays while request files exist; temporary data is removed after loading. Stream readers reject paths outside the request directory, missing/truncated streams, invalid topology, non-finite numbers and inconsistent hole counts. Numeric terrain data does not travel as large JSON arrays.

`landscapes.py` plans the map LOD, constructs Blender meshes in bulk, preserves masks and creates neutral/preview materials. `map_import.py` handles placement through the same deferred attachment and map-root paths as other components. A failed component is reported as missing with its full object identity.

Current support is **partial**. Terrain geometry, source normals, transforms, paint data and static holes are implemented. Original landscape material graphs, height blending, runtime virtual textures, shader WPO/displacement, landscape spline deformation, procedural grass and engine streaming/simulation are separate features. A neutral or layer-preview import should not be described as a fully textured recreation of the game.

## Validation

- `bridge/blender_landscape_test.py`: generic/SQEX deferred placement, a multi-level attachment chain, six paint layers, triangle winding, holes, all-hole components, budget planning, disabled imports and malformed binary streams. Checked in Blender 4.5 LTS and 5.1.
- `bridge/blender_landscape_game_test.py`: production bridge/session/map imports for the investigation's 38 samples across ANOMALOUS, Cosmic Shake, Secret of the Mimic, Hogwarts Legacy, Kingdom Hearts III, Last Flag, Marvel Rivals and Moss. Checks geometry and paint against independently extracted reference data, world placement, lower-LOD corner preservation and conservative hole coverage. Also imports all terrain in a Last Flag map under a small automatic LOD budget.
- Existing shared map-option, generic UMAP, basic component and language tests cover registration and non-terrain behavior.

Game-dependent tests use ignored local configuration/reference files; no AES keys or proprietary engine source are distributed.
