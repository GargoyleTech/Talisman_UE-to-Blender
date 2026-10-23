# FF7RGameAssetBridge

The C# helper process the add-on shells out to for reading FINAL FANTASY VII
REBIRTH package data directly from a mounted game install via
[CUE4Parse](https://github.com/FabianFG/CUE4Parse) (Apache-2.0 — see
[../NOTICE.md](../NOTICE.md)).

Most of it lives in `Program.cs`. AnimSequence is the exception: Rebirth's layout
defeats CUE4Parse and its key frames are ACL compressed clips that CUE4Parse cannot
decode, so `RebirthAnimSequence.cs`, `AclDecoder.cs` and `AclDecompressor.cs` handle
that path. See [../docs/REBIRTH_ANIMSEQUENCE_FORMAT.md](../docs/REBIRTH_ANIMSEQUENCE_FORMAT.md).

The compiled binaries already sit in `../addon/bridge/` so the add-on works
without building anything. Rebuild from here only if you're changing the
bridge itself or want to verify the shipped binaries yourself.

The `niagara_index` asset-server action accepts `pathFilter` and identifies
NiagaraSystem assets from IoStore export class tables, without deserializing
their system/script properties. The `niagara` action still exposes partial
properties. Blender's [Niagara resource backend](../addon/formats/niagara/README.md)
uses their explicit mesh/material references while preserving decode limits.

## Build

Requires the [.NET SDK](https://dotnet.microsoft.com/download) matching the
`TargetFramework` in `RebirthPackageLister.csproj` (currently `net10.0`).

From the repository root:

```
python build_bridge.py
```

This restores CUE4Parse/CUE4Parse-Conversion from NuGet, publishes for Windows
x64, checks the result, and replaces `addon/bridge/` with the clean publish.
The bridge remains framework-dependent and requires the .NET 10 x64 runtime.
It ships only the Windows x64 native libraries, without debug symbols or a
bundled .NET runtime. SkiaSharp's legacy multi-platform content copying is
disabled; the .NET SDK selects its native library for `win-x64`.

Both CUE4Parse packages are pinned to `1.2.2.202610`. See
[HIFI_RUSH_STATIC_MESH.md](HIFI_RUSH_STATIC_MESH.md) for Hi-Fi Rush's optional
BodySetup header and the real-game mesh regression checks.

## Deploying a rebuilt bridge

Use `python build_bridge.py`, then `python build_addon_zip.py` to rebuild the
installable ZIP at the existing add-on version. Do not copy a portable build
over the shipped folder: that retains obsolete dependencies and adds other
platforms' native libraries.

For development only, `dotnet build bridge/RebirthPackageLister.csproj -c Release`
produces `bridge/bin/Release/net10.0/win-x64/TalismanGameAssetBridge.exe` and its
dependencies, including debug symbols.

## Usage

`blender_preferences_persistence_test.py` exercises Blender's actual add-on
disable/enable path, source reloads, nested profiles and mappings, deleted
presets, failed backup writes, stale/corrupt backups, and failed registration.
Run it in factory Blender with isolated `BLENDER_USER_CONFIG`,
`BLENDER_USER_SCRIPTS`, and `BLENDER_USER_EXTENSIONS` directories. Then run it
again with `-- --verify-restart` using the same directories to verify recovery
in a fresh process while the add-on was disabled. The fixture uses fake paths
and keys and must not run against a user's normal configuration.

The `texture-browser` operation accepts a temporary mailbox directory as its
output argument. After mounting it writes `ready.json`. Blender atomically
publishes `request-NNNNNNNN.json`; the bridge responds with the corresponding
`response-NNNNNNNN.json`. `index` and `index_step` scan registry/package class
metadata in batches and cache completed indexes using container fingerprints.
`browse` returns one page of folder/search results, including exact object paths
for multiple texture exports in a package. `preview` writes a bounded opaque RGB
PNG; `texture` retains the normal full-resolution DDS/PNG/HDR export and alpha.
The bridge does the decoding and resizing; Blender timers only poll completed
results and display small thumbnails. This protocol is separate from the
existing synchronous asset-server import transport.

`blender_texture_browser_test.py` uses an external-process fixture to check
progressive indexing, independent checklists, paging/search, stale previews,
packed images, profile fallback, and reload cleanup on Blender 4.5/5.1.
`blender_texture_browser_ui_test.py` runs in graphical factory Blender and
checks the actual preview widget, modal batch loading, undo and redo.
`blender_texture_node_render_test.py` compares native/custom texture sampling.
`blender_texture_browser_game_test.py -- --config <ignored-json> --game <entry>`
checks actual indexes, bounded previews, and packed full-size imports; `--direct`
checks a configured `texture` immediately and `--finish-index` verifies disk
caching after a complete scan. See the [texture browser guide](../addon/formats/unreal_package/README_TEXTURE_BROWSER.md).

The `rebirth-texture-hashes` operation writes an optional loose-MEC texture
lookup to the command's output path. It scans Rebirth IoStore export headers,
selects texture exports, and writes their actual `GlobalImportIndex` values in
the byte order used by the MEC parser. JSON progress lines go to stdout.
Blender's preferences manage the subprocess, cancellation, and atomic replacement
of the user-data cache. No generated lookup is shipped with the add-on.

The add-on invokes the bridge as a subprocess in `asset-server` mode (one
JSON request per line on stdin, one JSON response per line on stdout). See
`PackageTextureLoader` in `../addon/games/rebirth/importers/packages.py` for the calling
convention, and the `Usage:` string at the top of `Program.cs` for the
one-shot CLI form.

Mounted package lookup is case-insensitive, matching Unreal object references.
Requests retain the mounted filename's spelling before raw mesh decoding.
`blender_rebirth_package_paths_test.py -- GAME_ROOT OODLE_DLL USMAP [REPORT_JSON]`
checks both G-Bike terrain/gimmick maps through the registered UMAP operator,
including their 35 `Minigame` references to the mounted `MiniGame` folder,
identical geometry for lowercase filenames, and rejection of absent assets.

Generic imports use `generic:GAME_UE4_27` (or another CUE4Parse `EGame` name)
as the game profile. `--capabilities` lists the profiles in the compiled runtime
without mounting a game. `GenericUnreal.cs` handles profile validation, mounted
path resolution, and material texture inventories. Generic sessions use the
conventional mesh exporters and disable add-on title adapters.

The profile editor runs the one-shot `generic-profile-test` operation. It returns
structured AES/mapping diagnostics and stops when a SkeletalMesh export has a
readable conventional geometry LOD. Registry candidates are tried first, followed
by a package-header scan when needed. `blender_generic_profile_test.py` verifies
the editor button, independent key/mapping errors, result invalidation and process
cleanup; optional `--config` exercises local games without storing their keys in
the test source.

`blender_generic_unreal_test.py` tests real games through the registered Blender
operator; supply an ignored local JSON configuration as documented in its
module header. `blender_generic_unreal_fixture_test.py` checks source isolation,
missing textures, and neutral skeleton behavior without game data. The local
development Oodle copy, when present, lives in `.local/oodle/` at repository root
and is never included in the add-on package.

The Crisis Core animation picker uses the registry's exact Skeleton links and
the neutral animation decoder, including its reference-pose and additive handling.
`blender_crisis_core_animation_test.py --config <local-config.json>` exercises
the registered mesh and animation operators against a `crisis_core` config
entry containing `root`, `usmap`, and optional `oodle`. It checks Zack's walk
and idle clips, batch imports, root transforms, custom scale, scene timing,
and rejection of unrelated Skeletons. `--save-blend <path>` retains the result.

`blender_crisis_core_cutscene_test.py --config <local-config.json>` uses that same
`crisis_core` entry to index and import an event master through the registered
Crisis Core cutscene operator. It verifies nested sequences, cameras/cuts,
skeletal animation, title materials, finite transforms and add-on reload.
`--sequence <package>` selects another master; `--report <path>` writes its
diagnostics. The shared neutral sequence fixtures also exercise the Crisis Core
operator's batch selection and explicit-path behavior without game data.

`blender_generic_umap_test.py` indexes, probes, and imports real map packages
using the same ignored test config. `blender_generic_umap_fixture_test.py`
checks parenting, object material overrides, instanced props, shared armatures,
and separate collections for identically named maps. Generic map exports use
standard component classes and their template defaults; title adapters remain
disabled. Non-block-compressed generic textures use PNG/HDR rather than an
empty DDS payload.

Generic map exports retain local `AttachParent` chains through custom
component classes even when CUE4Parse reads those classes as plain UObjects.
Their transforms become SceneComponent helpers with source/component paths.
This includes Hogwarts Legacy's PhysicalResponse and AnimatedLight parents.

`GenericTextureExporter.cs` reads single-layer virtual textures from tiled
VTData, including packages with no conventional mip array. Generic volume
textures are retained as labelled vertical slice atlases in the material
inventory; they do not recreate a 3D material. Images record `ue_texture_type`
and `ue_texture_layout`. Runtime render targets return an explicit unavailable
reason because their pixels are generated by the running game.
`blender_generic_texture_layout_test.py` checks packed image/layout metadata,
resolution caps, volume labels and runtime-target diagnostics.

`blender_rect_light_text_test.py` checks rectangular area-light dimensions and
axes, exposure/attenuation, visibility, text conversion, and deferred/bone
attachments. `blender_rect_light_text_game_test.py -- --config <local-config.json>`
checks the registered area-only UMAP operator against both FNaF titles, verifies
Blueprint-inherited light dimensions/intensity, and imports real text components
with their authored hidden flags. Text uses Blender's font as an approximation;
rect-light barn doors and source textures now drive Cycles emission masks.
`blender_ue_light_test.py` measures radial, cone, area, barn-door and texture
behavior in scene-linear Cycles renders. `blender_ue_light_animation_test.py`
checks both cutscene importers and saved-file controls. See
[UE4 lights](../addon/formats/ue_map/README_LIGHTS.md) for calibration and
finite-source approximation details.
`blender_baked_light_test.py` checks static map light baking, direct native
property edits, animation guards, helper refresh, render equality and save/load.

The `texture` and `generic_texture` asset-server requests accept optional
`maxTextureResolution` (longest edge in pixels, `0` for unlimited) and
`textureMipOffset` (`0` through `-16`, negative values select smaller mips).
Both constraints apply relative to the highest readable mip. Responses include
the selected `width`, `height`, `mipIndex`, and highest readable `sourceWidth` /
`sourceHeight`. Selection uses actual mip dimensions, tolerates missing payloads,
and exports one mip while retaining native BC compression. If no stored mip meets
the cap, the Blender loader resizes the smallest available image. Source-scoped
images and cached materials share upgrades in place and never downgrade.
`dotnet run --project bridge/TextureTests -c Release` checks selection without game
data. `blender_texture_mips_test.py` checks both loaders, packed DDS payloads,
image identity, metadata, shader-cache upgrades, caps, and all map operator controls.

Generic animations use `generic_animation_index` with `skeletonAssetPath` and
optional `pathFilter`. Registries supply AnimSequence candidates and Skeleton
tags; missing tags are verified from animation exports. The normal `animation`
action uses the neutral exporter for generic profiles. It samples through
CUE4Parse, exports the reference hierarchy, preserves endpoint timing and
RateScale, and bakes supported additive clips onto their reference animation.
`GenericAnimationDecoder.cs` contains isolated workarounds for the pinned
CUE4Parse additive reference-frame indexing and implicit per-track scale bugs.

`generic_asset_index` accepts `assetClass` (e.g. `LevelSequence`) and optional
`pathFilter`. `generic_sequence` accepts `assetPath` and returns authored export
properties with local export indices and full external object references.
`generic_actor_template` accepts `assetPath` and `objectPath` (a full object path
or local numeric export reference) and returns the actor's merged defaults and
serialized scene components. It follows native components, SCS templates and
inherited component overrides without running Blueprint scripts. These exports
feed Blender's **Generic Unreal Cutscene (LevelSequence)** importer; see
[`README_SEQUENCES.md`](../addon/formats/unreal_mesh/README_SEQUENCES.md).

Regression checks:

- `dotnet run --project bridge/AnimationTests --configuration Release` tests
  local/mesh-space additive pose math against the shipped CUE4Parse DLLs.
- `blender_generic_animation_fixture_test.py` checks eight scale/axis/facing
  combinations, reference scales, root motion, quoted bone names, FPS conversion,
  skeleton rejection and source lookup from shared armature data.
- `blender_generic_animation_test.py` exercises the registered model, compatible
  clip index and animation operators against ignored local game configurations,
  including evaluated skinned geometry and optional saved `.blend` output.
- `blender_generic_sequence_fixture_test.py` checks neutral nested timing,
  camera/property animation, NLA overlap/loop/reverse mapping, relative socket
  attachments, source-safe binding reuse and rollback on Blender 4.5/5.1.
- `blender_generic_sequence_test.py` exercises the sequence browser, binding
  preflight and registered import operator against ignored game configurations.
- `blender_generic_package_test.py -- --archive PATH` checks an installable ZIP,
  matching bridge, registration/reload and Blender-extension namespaces without
  modifying installed add-ons or saving user preferences.

Generic `static_mesh` requests also accept `naniteMode` (`AUTO`, `NATIVE`,
`FALLBACK`), `maxNaniteTriangles` (0 = unlimited), `naniteCacheMiB` (default 256;
0 = no cache target), and `geometryOutput` (a temporary output directory).
Omitted `naniteMode` retains the legacy fallback response. Native output uses a
version-1 `binaryGeometry` manifest with little-endian float32 attributes, int32
indices, uint8 colors, stream shapes, and material sections. The Python session
validates and loads these arrays before deleting the temporary files. Conventional
static and skeletal requests also emit binary streams when `geometryOutput` is
supplied; requests without it retain JSON geometry. Native failures propagate;
Auto records `naniteFallbackReason` when using conventional geometry.

See [NANITE_IMPORT.md](NANITE_IMPORT.md) for implementation and measurements and
the [user guide](../addon/formats/unreal_mesh/README_NANITE.md) for controls and
compatibility. `test_binary_geometry.py` checks corrupt payload rejection;
`blender_nanite_geometry_test.py` checks typed geometry and attribute preservation.

## Map import performance

Conventional static requests export only the first usable LOD by default.
`includeAllLods: true` explicitly includes the additional `lods` list; the primary
LOD is converted once. `sourceLodCount` remains available with either setting.

The mounted provider reuses package objects and lazy exports in a session-local
LRU cache, including loads made by CUE4Parse's dependency resolver. The cache is
limited to 32 entries and 256 MiB of serialized UAsset/UMAP plus UEXP data.
An additional recent-source cache retains at most eight raw byte buffers and
64 MiB. Rebirth shares primary buffers with its lazy package/raw readers;
other profiles keep CUE4Parse's native archive and partial-read behavior.
These limits describe retained cache entries, not total decoded memory:
lazy bulk payloads and live dependency graphs can be larger. Oversized packages bypass the
cache. `release_batch_memory` drops cache ownership before collection, and
`package_cache_stats` returns entry/byte counts, hits, misses and evictions, raw
source reads/hits, and compact material-inventory cache statistics.

Generic material inventories cache direct texture references, parameter labels,
parent/function paths, package import inventories and complete dependency unions
across requests. The cache
is provider-local and retains strings/records rather than decoded packages or
UObjects, with limits of 4,096 records and eight million string characters.
Nested landscape material parents resolve their owning UMAP independently from
their actor/outer path. Named meshes and materials filter export names and full
outer paths in package headers before deserializing their selected export, avoiding
scans through unrelated level actors. Full inventories and warnings retain the existing union
of parameter, inherited, function and embedded texture references.

For separate uncompressed texture payloads, mounted file sizes can establish the
highest available mip without fetching that mip's bytes. Only the requested mip
is then read. Unknown/custom/inline layouts retain payload probing, and repeated
probes within a request reuse their result. Responses expose `mipPayloadReads`
and `mipPayloadBytes` for diagnostics; source dimensions and relative mip offsets
keep their original meaning.

The Python session requests optional `instanceOutput` with map actor data.
Foliage components then return a version-1 `binaryInstances` descriptor in
`PerInstanceSMData`, naming a temporary little-endian float32 stream shaped
`[instance_count, 10]`: translation XYZ, quaternion WXYZ and scale XYZ. Components
share one file per map, with a `byteOffset` for each component's range. The session
loads that file once and retains array views for individual components. It
validates file bounds, size, shape and finite values before removing temporary
files. Clients omitting `instanceOutput` retain the JSON transform records.
Blender composes ordinary instance transforms in NumPy and writes point positions,
rotations and scales in bulk. Shear, degenerate scales and rotations close to
gimbal lock retain the original mathutils conversion.

Map static sources can be built directly as mesh datablocks. Title hooks and
modifier-based correction still receive an unlinked source object when needed;
map sources do not change the active selection. The custom-normal setter uses
native Python float lists up to one million vertices, bounding the temporary
conversion for larger native geometry. Generic maps perform their final origin
parenting in one scene-update pass.

Python map cleanup sends `force: false`: small working sets keep their package
cache and avoid a blocking collection. At 512 MiB of managed allocations or the
session's working-set restart threshold, cleanup drops package/raw ownership and
compacts once. A process that still exceeds the restart threshold is recycled.
Explicit `force: true` (also the default for older protocol clients) retains full
cleanup. Compact material inventories survive package cleanup until the provider
is replaced. Session `performance_summary()` exposes request times/counts and
bridge restarts without retaining request payloads.

Both package sessions use validated binary geometry for static and skeletal
meshes. Optional `weightOffsets` (int32, vertex count + 1) and `weightPairs`
(float32, influence count by 2) streams preserve ragged skin influences without
building Python pair lists. `skinInfluenceCount` records their total. Native
Nanite retains its existing stream format. Conventional attribute rows are
enumerated into buffered files rather than retained in extra jagged arrays.

Opposite-face correction groups rounded vertex positions and triangle identities
with NumPy, calculating face normals only for coincident candidates. The original
six-decimal Python rounding rule and normal/direction thresholds are retained.

MEC topology now uses the shared `core/blender/mesh_geometry.py` bulk builder,
avoiding Python vertex/face lists and the loop-index readback for UV assignment.
It explicitly preserves flat shading, custom normals, UV names, mesh properties,
vertex order for sway keys, and shared placement datablocks. The custom-normal
setter retains its list conversion: Blender parses that API's sequences faster
than NumPy scalar objects, as verified in the construction benchmark.

Import-scoped material/image indices replace repeated scans of `bpy.data` for
package sources, generic shaders, MEC materials and loose texture files. Builders
register created/upgraded datablocks with every initialized index. Lookups check
renamed/deleted IDs, and each new package batch starts with fresh indices.
Cached materials refresh their texture nodes once per import, namespace, quality
setting and node count. Later imports still upgrade shared images in place;
manual callbacks retain refresh-on-call behavior. Rebirth's master-material
migrations also scan existing materials once per batch rather than per variant.

Package and generic map resolvers initialize skin weights once on each source
mesh. `SharedSkinWeights` captures that mesh's group-index layout and counts;
placements reuse the deform data while setting up their own armature modifier,
parent transform and title hooks. Existing group names are reused rather than
appended again. The layout includes non-bone groups such as opposite-face masks,
and the source object is still discarded. Standalone binding initializes its
supplied weights normally. Assets constructed without the optional shared state
retain the full binding path.

Focused checks (the C# fixture output directory may be any disposable directory):

```text
dotnet run --project bridge/GeometryTests -c Release -- .local/geometry-fixture
python bridge/test_binary_geometry.py
python bridge/test_opposite_face_geometry.py --benchmark
blender --background --factory-startup --python-exit-code 1 --python bridge/blender_nanite_geometry_test.py
blender --background --factory-startup --python-exit-code 1 --python bridge/blender_mec_bulk_geometry_test.py
blender --background --factory-startup --python-exit-code 1 --python bridge/blender_import_cache_test.py
blender --background --factory-startup --python-exit-code 1 --python bridge/blender_map_performance_test.py
blender --background --factory-startup --python-exit-code 1 --python bridge/blender_shared_skin_weights_test.py -- --benchmark
```

On the local 100,000-triangle numerical fixture, opposite-face correction took
approximately 0.17 seconds versus 0.71 seconds for the original implementation,
with identical modified vertices. The full Copper Falls import and eight linked
maps took about 263 seconds with the 32-entry cache (an earlier recorded baseline
was about 319 seconds). A 256-entry cache took about 290 seconds, so the smaller
cache remains the default. These are indicative runs, not controlled throughput
guarantees. Both full-map checks retained the same 32,240 objects, 360,448 foliage
instances, 503 packed images, 537 native meshes, and existing unavailable assets.

The Python batching checks on Blender 4.5/5.1 preserve topology, flat shading,
corner normals, both UV sets, unused vertices, degenerate faces and shape-key
vertex order. A real Rebirth MEC sample retained identical geometry, metadata
and transforms for 429 meshes / 2,283 placements; its construction phase measured
about 2.2 seconds versus 2.6 seconds before these changes. A textured group retained
the same 169 packed images and 40 shader graphs after 32-to-128-pixel upgrades.
The 100k-triangle construction fixture measured about 1.5x faster on Blender 5.1
and 2x on Blender 4.5. These small measurements do not predict whole-map speedups.
The full Copper Falls rerun after Python batching retained all scene counts and
took about 284 seconds, versus the earlier 263-second run; bridge response time
also rose from about 203 to 222 seconds. The runs were not isolated controlled
comparisons, so an overall map-import speedup from Python batching is not established.

The shared-skin fixture on Blender 4.5/5.1 checks one weight pass for JSON and
binary inputs, package/generic source caches, independent posed deformation,
non-bone masks, per-placement hooks, missing rigs and stale layout rejection.
In a local Blender 5.1 comparison against the previous binder, constructing 14
placements of Last Flag's jumppad (15,037 vertices / 22,513 influences) took about
0.38 seconds before versus under 0.01 seconds with shared weights. Five Red XIII
placements (129,090 vertices / 333,544 influences) took about 3.84 seconds before
versus under 0.01 seconds. Their posed evaluated vertices matched, and group
counts stayed at 3 and 326 instead of growing to 45 and 1,956. These measurements
cover repeated placement construction after source initialization, excluding
package reads, material builds and scene evaluation; they are not whole-map timings.

The October 17 map-import pass compared a fresh Copper Falls baseline with the
same nine-map recursive import on Blender 5.2, Auto Nanite with a two-million
triangle limit, and a 512-pixel texture cap. The baseline took 281.94 seconds;
the final implementation took 248.26 seconds (about 12% less elapsed time).
A preceding run before consolidating foliage files took 244.07 seconds, so
these single runs remain indicative rather than a controlled throughput guarantee.
Both final runs retained 32,240 objects, 360,448 foliage instances, 503 packed
images, 537 native meshes and the same unavailable assets. Package-cache misses
fell from 294,357 to 192,829 with the existing 32-entry package limit.

| Request category | Fresh baseline | Final run |
| --- | ---: | ---: |
| Static meshes | 38.65 s | 24.12 s |
| Material inventories | 99.61 s | 40.43 s |
| Textures | 74.87 s | 109.46 s |
| Map actor data | 7.20 s | 7.01 s |

Request times include response handling and reflect dependency-loading/cache
effects between categories; total import time is the primary comparison.
The 604 material texture inventories matched the original bridge, and twelve
sampled texture exports matched its bytes and mip metadata across capped,
offset and unlimited requests. Separate real-game checks preserved Rebirth
static/skeletal geometry and the MEC sample's 429 meshes / 2,283 placements,
including exact topology, UVs, normals, shape keys and placement transforms.
The foliage fixture validates shared stream ranges and compares 6,000 transform
cases with the original mathutils path, including negative/zero scales, shear
and near-gimbal rotations. Its 100,000-instance numerical conversion measured
roughly 16x faster; that is a numerical fixture rather than a whole-map speedup.
