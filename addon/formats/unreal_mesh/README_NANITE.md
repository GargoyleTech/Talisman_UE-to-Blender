# Native Nanite geometry

The Generic Unreal StaticMesh and UMAP importers can reconstruct the finest
stored Nanite triangle surface as an ordinary editable Blender mesh. This also
works for generated Nanite landscape meshes embedded in map packages. It does
not create a Nanite renderer inside Blender.

## Controls

| Option | Behavior |
| --- | --- |
| **Auto** (StaticMesh default) | Use native geometry where available. If decoding fails or exceeds the triangle limit, import the conventional fallback and report why. |
| **Native** | Require complete native geometry for Nanite assets. A failure or limit rejects that asset. Ordinary non-Nanite assets still import conventionally. |
| **Fallback** (UMAP default) | Use the conventional fallback LOD. This may be substantially less detailed. |
| **Max Native Triangles / Mesh** | Default 2,000,000. Set **0** for unlimited native detail. Exceeding the limit never truncates a mesh. |
| **Nanite Page Cache (MiB)** | Default 256. Target for decoded dependency pages; **0** removes the cache target. Cold vertex references spill to temporary disk storage and are restored without decoding the original pages again. |

For full-detail Last Flag terrain, choose **Native** and set **Max Native
Triangles / Mesh** to **0**. Its Copper Falls terrain has 8,133,707 native
triangles, compared with 18,012 triangles in the fallback.

The page cache is a decoding target, not a total memory limit. Dependency groups
can temporarily exceed it. Blender also needs memory for its finished mesh,
loop UVs, normals, textures and every unique mesh in a map. Repeated map and
foliage placements continue sharing source geometry. Temporary binary geometry
and reference files are removed after a successful import or handled failure.

## Preserved data and reporting

Native imports retain vertex positions, normals, up to eight stored UV sets,
vertex colors, available explicit tangents, and per-triangle material slots and
references. Generic material textures and profile PBR mappings work as before.
Custom Unreal landscape blends, virtual textures and game shaders still require
their own Blender shader implementation.
Environment materials can use different parameter names from character shaders;
for example, Last Flag uses both `Base Color Texture` / `Normal Texture` and
`Base Color` / `Normal`. Add ordered alternatives to the profile's PBR mappings
when needed. Repeated layer names still need a shader-specific material setup.

Cluster boundary vertices remain separate so UV, normal, color and tangent seams
are preserved. Consequently the Blender vertex count can exceed the original
build-input vertex count. Coarser overlapping Nanite hierarchy clusters are
excluded. Cooked trimming may remove source detail before shipping; native
import cannot recover triangles absent from the game files.

The import summary reports native mesh and automatic-fallback counts; the
console records each fallback reason. Mesh datablocks record
`ue_geometry_source` (`NANITE`, `FALLBACK`, or `CONVENTIONAL`), `ue_geometry_id`,
`ue_nanite` decoding statistics, and any `ue_nanite_fallback_reason`.

## Compatibility

Validated with Last Flag's UE 5.5.4 assets in Blender 5.2, including static props
and embedded Copper Falls terrain. Other UE5 layouts depend on the bundled
CUE4Parse decoder and selected game profile. Static Nanite triangle surfaces
are supported; Nanite assemblies, skinned clusters, voxels and curves are
explicitly rejected. Auto can use their conventional fallback when available.
Non-Nanite landscape heightfields are outside this geometry decoder.

Last Flag uses **GAME_UE5_5**, requires matching `.usmap` mappings for its
unversioned properties, and did not require an AES key in the tested build.
