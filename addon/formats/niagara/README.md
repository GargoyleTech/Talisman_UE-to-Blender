# Niagara mesh resources

In **File > Import > Talisman > FF7R**, choose **Niagara (Mesh resources)**
under Rebirth. The normal Rebirth install, Oodle and mapping preferences apply.
The initial asset list scans `End/Content/Effect`; change **Asset Folder** and
click **Refresh Assets** to scan another folder or path fragment. The list reads
IoStore export classes, so an unreadable cooked NiagaraSystem property schema
does not prevent asset discovery.

This first backend imports the explicit `Meshes[].Mesh` references from mesh
renderer exports. Each system receives a collection containing one object per
distinct mesh/material-override combination. Repeated combinations collapse to
one object; different materials on the same mesh share its geometry and use
object-linked material slots. Slot order and section assignments are retained.
Absent or null material overrides use the mesh's own material for that slot.

Materials and packed textures use the **generic Unreal** material pipeline.
There is no Rebirth particle-ubershader reconstruction or automatic PBR mapping.
Meshes keep their local geometry, with the ordinary Unreal-to-Blender axis and
unit conversion. All source objects are placed at the origin. Particle counts,
renderer transforms, bounds, visibility and spawn/update logic are not applied.
Sprites, ribbons, lights, simulation, animation and Geometry Nodes are not built.
Unreadable resources are reported while other readable resources can import.
Reimporting creates a new resource collection and does not edit prior objects.

## Implementation boundaries

- `package_data.py` normalizes bridge JSON into a Blender-independent model of
  systems, emitters, script usages, renderers, material slots and mesh resources.
  It preserves export/object identity and partial-read status, retains missing
  settings as unknown, and does not inspect opaque parameter-variable payloads.
- `resources.py` consumes that model to load meshes and generic materials. It
  creates no particle logic. Geometry is read once per unique mesh per system.
- `games/rebirth/importers/niagara.py` owns the Rebirth session, browser and
  operator. It retains native Rebirth mesh decoding while reusing generic UE
  material/texture requests. Those requests translate object references into
  Rebirth's mounted package paths while keeping their object selectors.
- `bridge/NiagaraAssetIndex.cs` supplies the header-only `niagara_index` request.

Collections store `ue_niagara_manifest`, a compact source manifest containing
emitter/script/renderer/resource relationships and decode limitations. Objects
store their mesh path, material overrides and all originating renderer/emitter
references. Export indices are zero-based report indices, not encoded Unreal
package references. The manifest excludes inflated/unvalidated raw variable
arrays. A future parser can add validated program/parameter data to the model,
and a separate Geometry Nodes backend can reuse these source resources.

## Scripted import

```python
bpy.ops.import_scene.ff7r_rebirth_niagara_game_packages(
    virtual_path="End/Content/Effect/Character/Property/UI7034_ConsumedItem/Particle/FX_UI7034_Materia_Yellow_01.uasset",
    scale_factor=0.01,
    max_texture_resolution=1024,
)
```

Explicit paths bypass the browser scan. `/Game/...Asset.Asset` object paths are
also accepted. Generic image inventory nodes preserve recovered texture
references; they are not an approximation of the particle shader's behavior.

## Validation

`bridge/blender_niagara_resources_test.py` checks deduplication, shared geometry,
ordered material overrides and fallback slots, failure isolation, unchanged
source transforms, sprite-only packages, compact metadata, registration and
reload. Its optional `--config` real-game check uses a local JSON `rebirth` entry
with `root`, `usmap` and optional `oodle` fields. The Materia Yellow system yields
seven objects, four mesh datablocks, five assigned materials and eight packed
textures through the generic pipeline. No game data is included in the tests.
