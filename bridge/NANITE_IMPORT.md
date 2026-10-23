# Native Nanite import implementation

The goal is to import the finest stored Nanite triangle surface for static meshes,
including generated landscape meshes embedded in map packages, with their material
assignments, UV sets, vertex normals, colors and available explicit tangents.
Cooked source triangle counts describe the build input; they do not guarantee that
an untrimmed original mesh remains in the cooked game.

## Work plan

1. Verify the deployed CUE4Parse page decoder against Last Flag's UE5.5 assets,
   including cross-page vertex references, finest-cluster selection, materials,
   and complete-page failure detection.
2. Add a bounded page-decoding exporter with atomic binary geometry output. Select
   finest clusters only; retain all stored UV channels and vertex attributes. Reject
   incomplete native output rather than quietly presenting a partial mesh as full.
3. Add explicit native/automatic/fallback selection and per-mesh triangle and decoder
   cache limits. Expose these controls in generic static-mesh and map imports and
   include settings in geometry cache identity. Keep material/image sharing separate.
4. Load binary streams as typed arrays and build Blender geometry with bulk RNA
   writes, avoiding large JSON messages, Python vertex objects and per-loop writes.
   Continue sharing mesh datablocks and foliage instances across map placements.
5. Verify small and large native assets, embedded Nanite terrain, material/UV/color
   preservation, budget/failure behavior, cache isolation, repeated placements,
   non-Nanite fallback, and existing importer fixtures. Measure time and memory.
6. Rebuild the workspace bridge without changing version numbers, document the
   final options and measured limits, and retain Blender test artifacts.

## Acceptance criteria

- Native mode reports native geometry and never silently substitutes a fallback.
- Auto mode records its fallback reason; ordinary non-Nanite meshes remain usable.
- Finest clusters are selected coherently; coarser hierarchy clusters are excluded.
- Missing/failed pages, invalid indices, non-finite attributes and invalid material
  assignments are detected before committing the geometry payload.
- A triangle limit aborts the complete native candidate rather than truncating it.
- Large payloads use binary streams and bulk Blender construction.
- The same quality settings reuse geometry across placements; different quality
  settings cannot accidentally reuse a lower-detail mesh.

## Implemented path

`NaniteMeshExporter.cs` uses the deployed CUE4Parse decoder and selects negative
`EdgeLength` finest clusters, matching its upstream converter. Every page must
decode, and its cluster total must match the resource header. Unsupported rigid
surface layouts, incomplete references, invalid indices/materials and non-finite
export attributes reject the candidate. Assembly/skinning/voxel/curve resources
are explicitly unsupported rather than flattened incorrectly.

Pages with future dependencies remain in an estimated LRU cache. Dead pages are
released immediately. For ordered dependency graphs, evicted pages spill their
resolved raw positions and complete attributes to one temporary file. Minimal
reference-only CUE4Parse page objects restore those values on demand; they never
serve as primary geometry. This prevents recursive re-decoding at low cache
targets without forking the CUE4Parse bitstream decoder. Other acyclic dependency
orders retain its native reference decoder; cycles are rejected.

Output attributes go to buffered binary streams as pages are visited. Triangle
indices spool per material and concatenate into contiguous sections. Successful
output commits by renaming its generated directory after writers close; handled
failures remove generated partial output. The loader validates stream paths,
shapes, lengths, dtypes, indices and finite values before retaining NumPy arrays.
Blender receives bulk vertex, loop, polygon, UV, color, tangent and material-index
writes. No full mesh is represented as JSON or Python vertex/face object lists.

Generic static-mesh and map dialogs persist Auto/Native/Fallback, a 2M default
per-mesh triangle limit (0 unlimited), and a 256 MiB decoded page cache target
(0 unlimited). Auto records fallback reasons; Native propagates errors. An older
bridge that ignores the geometry mode is rejected by the Python session. Mesh
metadata records the source, decoding statistics and quality identity. Materials
and images keep their separate source identity and sharing behavior.

See the [user guide](../addon/formats/unreal_mesh/README_NANITE.md) for settings
and support boundaries. No version metadata was changed.

## Measurements and checks

Last Flag build CL-68113, UE5.5.4, `GAME_UE5_5`, matching dumped mappings, no AES
key, Blender 5.2. These are measurements on the test machine, not throughput
guarantees. Concurrent verification can affect timings.

| Asset | Native triangles | Blender vertices | UV sets | Materials | Measured result |
| --- | ---: | ---: | ---: | ---: | --- |
| Round launchpad | 1,952 | 1,502 | 1 | 2 | 0.22 s decode + Blender construction/material loading |
| RockSet 03 | 363,952 | 255,079 | 1 | 1 | 1.15 s decode + Blender construction/material loading |
| Copper Falls embedded terrain | 8,133,707 | 5,452,483 | 4 | 16 | 8.7–13.0 s native export; 118.6 s through Blender and landscape texture inventory |

The terrain uses 1,688 pages and 64,572 finest clusters. Its exported triangle
count exactly equals its build-input triangle count. A 32 MiB cache target peaked
at an estimated 40.8 MiB of decoded page objects, used about 410 MiB of temporary
reference storage, and avoided the prior repeated-decoding slowdown. Whole bridge
resident memory was about 721–734 MiB, demonstrating why the page target must not
be described as a process-memory ceiling. The complete Blender terrain test peaked
at about 2,777 MiB for Blender and 4,830 MiB summed across its process tree.
An isolated geometry-only run loaded/validated the binary streams in 0.23 s and
built the Blender mesh in 19.26 s, with approximately 3,044 MiB peak Blender
resident memory sampled every 100 ms. The complete test used 250 ms sampling and
can miss shorter memory peaks. The bulk builder releases conversion and loop-UV
buffers as soon as their Blender writes finish.

The full terrain retained 90 packed images; the engine weight-map array
placeholder remains unsupported by the generic Texture2D loader. The prop test
retained 18 packed images without texture/material read failures. Environment PBR
parameter names differ from Scout's shader and require profile alternatives;
Unreal landscape layer blending is not reconstructed by native geometry decoding.

Validation completed:

- Four binary-loader tests cover valid payloads, truncation, invalid indices,
  non-finite values, traversal, missing streams, dtypes and shapes.
- Blender typed-array fixtures preserve UV sets, normals, colors, tangents,
  material gaps/sections, transforms and geometry quality identity; an older
  bridge is rejected instead of silently ignoring Native mode.
- Existing generic, skeletal/options, map/options, shared-runtime, sequence and
  texture/mip/alpha fixtures pass after the shared bulk-construction change.
- Seven real bridge requests check all modes, a triangle budget, strict rejection,
  recovery after rejection, conventional non-Nanite meshes and invalid settings.
- Disk-backed and original native rock streams are byte-identical. Changing
  decoder cache limits does not change exported geometry.
- Saved native prop and 8.13M-triangle terrain files reopen with their geometry,
  attributes and packed images intact. Workbench previews were inspected; a prop
  texture preview exercised alternate generic PBR parameter names.
- The installable ZIP passes bridge-hash, unchanged-version, new controls,
  registration/reload and extension-namespace checks in factory Blender.

The normal generic UMAP operator imported Copper Falls and eight linked maps in
Auto mode with the default 2M per-mesh triangle limit. It produced **537 native
Nanite source meshes / 11,493,524 unique native triangles**, 32,240 scene objects,
25,019 reused regular-mesh placements, 2,014 foliage components with 360,448
instances, 14 armatures, 833 lights, 43 text objects and **503 packed images**.
The only automatic Nanite fallback was the 8.13M-triangle terrain exceeding the
configured limit. The two conventional mesh failures from the baseline remain
(launchpad collision and pneumatic glass with non-finite conventional data), as
do four unavailable generic textures. No additional Nanite decode failures were
reported. The scene saved successfully.

That complete map test took approximately 319 s to import / 324 s including save
and process overhead. Peak sampled resident memory was approximately 4,916 MiB for
Blender / 8,694 MiB summed across its process tree. This is an ordinary Blender
scene with shared mesh/foliage instances, not a recreation of Nanite's GPU LOD
selection or rasterizer. Water, spline deformation, decals and authored game
shaders retain the limitations of the existing generic map importer.

A fresh Blender process reopened that Auto map and verified its native geometry,
22,193 reused native placements, all nine map roots and 503 packed images. The
validated full native terrain binary was then built with the same shared mesh
importer and assigned to its existing map placement, retaining transforms and
material slots. This produced a compressed full-detail snapshot with **538 native
source meshes / 19,627,231 unique native triangles** and no remaining Nanite
fallback datablock. This snapshot upgrade used cached decoded terrain output;
the complete operator run above used Auto with its explicit limit.
A further fresh-process reopen verified all 538 native meshes, 19,627,231 native
triangles, four terrain UV sets, nine map roots and 503 packed images in that
full-detail snapshot. The compressed Auto/full snapshots are approximately
471/828 MiB. The rebuilt installable ZIP is 46.5 MiB and retains version 1.0.0.
