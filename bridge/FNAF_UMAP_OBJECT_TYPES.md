# FNaF UMAP object-type gap probe

Probe date: 2026-10-17. This is an inventory of the current local Security Breach and Secret of the Mimic installs against the generic UMAP import path.

Implementation follow-up: rectangular area lights and approximate editable text
are now supported. The counts and export spot checks below preserve the original
probe baseline from before those changes. The real-game follow-up imported 361
Security Breach area lights and 145 Mimic area lights; text checks created 828
hidden Security Breach labels and 22 visible Mimic labels. See the add-on README
and `blender_rect_light_text_game_test.py` for the supported behavior.

The largest shared visual gaps are decals and rectangular lights. Rectangular lights have the most direct initial Blender mapping; decals have the greatest placement count and need a projection/material implementation. Child actors are already partially represented as transform parents, and several high-count text components are deliberately hidden.

## Coverage and method

| | Security Breach | Secret of the Mimic |
|---|---:|---:|
| UMAP packages indexed/read | 742/742 | 485/485 |
| Raw package exports | 860,945 | 381,715 |
| Distinct raw class names | 1,648 | 935 |
| Inventory failures | 0 | 0 |
| Unique component/object detail samples | 82 | 64 |
| Complete maps checked through the shipped actor-export API | 3 | 3 |

- Mounted both games with their existing local profile credentials and `GAME_UE4_27`; no `.usmap` was supplied. CUE4Parse assembly version: `1.2.2.0`.
- Enumerated every current mounted `.umap` and read each export table before the importer class filter. Both indexes include `Engine/Content/Maps/Entry.umap`; Security Breach includes DLC content. Counts cover the complete indexes.
- Counts are serialized component/object exports across packages. Lighting scenarios, camera maps, AR/non-AR maps, VR variants, and repeated authored content remain separate. Counts do not establish unique visible objects in one playable world.
- Deserialized representative objects and their template chains, including high-count maps. Invoked the shipped `GenericUnreal.ComponentType` method directly, then checked six complete maps through `umap_actors`.
- All header inventories and detail samples completed without failures. Four DDGI detail samples emitted the custom-version warning described below. This was a data/export investigation; Blender rendering fidelity was not tested.
- Actor wrappers such as `StaticMeshActor`, `RectLight`, `DecalActor`, and `NiagaraActor` are not added to their component counts. Game-specific Blueprint actors are not classified as missing solely because their wrapper class is absent from the payload.

## Shared types without a dedicated generic UMAP import

Cells show **object/component count (number of containing maps)**. The component filter rejects these classes as dedicated output types. If one is an attachment ancestor of a supported component, it can still survive as a `SceneComponent` transform carrier.

| Raw Unreal type | Security Breach | Secret of the Mimic | Evidence / scope |
|---|---:|---:|---|
| `DecalComponent` | 25,779 (332) | 1,798 (88) | Deferred decals; material and transform are readable. Projection/material conversion required. |
| `RectLightComponent` | 7,486 (118) | 817 (63) | Area-light candidate; dimensions, intensity, color, units, temperature and transforms are readable. |
| `TextRenderComponent` | 2,900 (210) | 190 (48) | Text/font/material/alignment data; visibility checks matter because samples include hidden labels. |
| `NiagaraComponent` | 1,224 (136) | 485 (70) | Effect asset and placement metadata; placeholder support is feasible, effect simulation is separate work. |
| `WidgetComponent` | 500 (99) | 181 (54) | World-space UI; preserving a marker/reference is feasible, reconstructing UMG needs a separate renderer. |
| `CameraComponent` | 81 (39) | 126 (25) | Placed map cameras; separate from existing LevelSequence camera import. |
| `AkComponent` | 3,591 (226) | 1,293 (156) | Wwise sound emitters; markers and references are feasible, playback/decoding is separate work. |
| `AudioComponent` | 483 (16) | 138 (46) | Native audio component placements and sound references. |
| `DDGIVolumeComponent` | 375 (18) | 265 (32) | RTXGI probe-volume metadata; all four sampled volumes warn about an unknown DDGI custom version. |
| `PostProcessVolume` | 137 (87) | 23 (17) | Authored exposure/color/bloom settings; Unreal-to-Blender translation needed. |
| `PostProcessComponent` | 14 (9) | 36 (9) | Component form of post-processing, often inherited from Blueprint templates. |
| `DirectionalLightComponent` | 4 (4) | 22 (7) | Sun/moon light candidate; small counts can still affect a complete exterior. |
| `SkyLightComponent` | 3 (3) | 21 (7) | Ambient/cubemap light candidate; requires environment-light conversion. |
| `ExponentialHeightFogComponent` | 6 (6) | 7 (7) | Density/falloff/color/start-distance metadata; the existing title-specific fog helper is not a stock UE fog conversion. |
| `SkyAtmosphereComponent` | 1 (1) | 7 (7) | Atmosphere properties; requires approximation or metadata preservation. |

## Important title-specific gaps

| Raw Unreal type | Security Breach | Secret of the Mimic | Evidence / scope |
|---|---:|---:|---|
| `SplineMeshComponent` | 3,280 (65) | 0 (0) | Explicitly excluded before the static-mesh subclass check. Samples have `SplineParams`, tangents, `ForwardAxis`, parent/material references, and inherited `StaticMesh`. Cables and pipes require per-placement vertex deformation. |
| `LandscapeComponent` | 0 (0) | 5,904 (2) | Mimic: 2,955 components in `MAP_ExteriorParkingLot` and 2,949 in `MAP_BigtopChase_00_Rooftop`. Samples expose heightmap references, section bases, scale/bias, subsection sizes and material references. Terrain reconstruction is separate work. |
| `PaperSpriteComponent` | 3,056 (11) | 0 (0) | Security Breach 2D minigame sprite placements; no generic sprite geometry conversion. |
| `PaperFlipbookComponent` | 296 (8) | 0 (0) | Security Breach animated 2D minigame sprites; frame evaluation would also be needed. |
| `ParticleSystemComponent` | 794 (108) | 0 (0) | Security Breach Cascade effects; references/transforms can be preserved as markers. |
| `CineCameraComponent` | 42 (25) | 0 (0) | Security Breach placed cine cameras; not currently created by generic UMAP import. |
| `SceneCaptureComponent2D` | 1,274 (67) | 0 (0) | Security Breach render-to-texture cameras; captured images are not static mesh placements. |
| `VolumetricCloudComponent` | 0 (0) | 14 (7) | Mimic cloud/aurora components; requires material/volume approximation. |
| `ProceduralMeshComponent` | 1 (1) | 0 (0) | One Security Breach component in `MAP_Atrium_3rd_Floor`; serialized `ProcMeshSections` contain vertex/index buffers. Readable but uncommon. |
| `ModelComponent` | 376 (30) | 6 (3) | Cooked BSP/model geometry. Large Security Breach examples are whitebox maps; assess visible geometry separately from collision/navigation volumes. |

## Partial support and misleading counts

- `ChildActorComponent`: 1,200 (120) in Security Breach and 1,702 (80) in Mimic. Samples contain a local `ChildActor` and inherited `ChildActorClass`/template references. The existing parent walk retains these components when supported children attach to them. `MAP_Backstage_Gameplay` exports four of nine as transform parents; `MAP_AdminBasement_Gameplay_2` exports all three. Existing serialized child meshes can already import. Blueprint spawning/evaluation and full child-actor semantics remain unsupported; expanding templates must avoid duplicating serialized children.
- `InstancedStaticMeshComponent` is already normalized to `FoliageInstancedStaticMeshComponent`: 798 components across 23 maps in Security Breach and 179 across 11 maps in Mimic. Native foliage components are also already supported (190/106). These are not missing geometry classes.
- `PoseableMeshComponent` is already normalized to `SkeletalMeshComponent`. Security Breach has 26; sampled vines and hologram stands take the supported skeletal placement route. Their runtime pose logic is a separate concern.
- `TextRenderComponent` counts overstate visible signage. Security Breach door samples inherit `bVisible=false`; Mimic has labels such as `LookAtActor` and `Cinematics Actor` with `bHiddenInGame=true`, alongside ordinary placed digits. Visibility/default resolution belongs in any text importer.
- Decal defaults also matter: Security Breach door decals can inherit `bVisible=false` and their decal material, while sampled DLC dirt/leakage/pothole decals have explicit materials and transforms. Some dimensions/defaults are omitted from instance tags.
- Raw `BoxComponent`, `SphereComponent`, `CapsuleComponent`, `BrushComponent`, navigation volumes, `ArrowComponent` and `BillboardComponent` mostly represent collision, navigation or helper metadata; some already survive as attachment parents. Their raw counts are not missing renderable-mesh counts.
- `SplineComponent` is a curve/path, separate from `SplineMeshComponent`: 692 across 111 maps in Security Breach and 59 across 28 maps in Mimic. It may be an attachment carrier or gameplay path.
- `LevelStreamingVolume` exists in both games (1,414/6). Streaming-level references already use `LevelStreamingAlwaysLoaded` and `LevelStreamingDynamic`; trigger-volume simulation is outside the current recursive map import.

## End-to-end export spot checks

| Game / map | Raw export count | Generic payload entries | Confirmed behavior |
|---|---:|---:|---|
| Security Breach: `MAP_Bowling_DLC` | 8,613 | 2,555 | 1,306 decals; no dedicated entries exported |
| Security Breach: `MAP_Night_03` | 1,548 | 344 | 361 rectangular lights; no dedicated entries exported |
| Security Breach: `MAP_Backstage_Gameplay` | 1,034 | 286 | 4 of 9 child-actor components retained as transform parents |
| Mimic: `MAP_Workshops_Main` | 7,200 | 3,456 | 131 decals; no dedicated entries exported |
| Mimic: `MAP_L_14` | 627 | 122 | 145 rectangular lights; no dedicated entries exported |
| Mimic: `MAP_AdminBasement_Gameplay_2` | 69 | 30 | 3 of 3 child-actor components retained as transform parents |

## Implementation order suggested by this probe

1. **Rectangular lights:** add native `RectLightComponent` export plus inherited area-light fields, then create Blender rectangular area lights with unit/axis conversion and visibility handling. Preserve barn-door and temperature metadata when no exact Blender equivalent exists.
2. **Decals:** export material, transform, dimensions and visibility/defaults, then implement a controlled projected-material approximation. This addresses the largest shared visual omission.
3. **Sun, skylight and stock height fog:** few objects, potentially large scene impact. Resolve Blueprint defaults before approximating sky/environment behavior.
4. **Optional text, camera and effect/audio markers:** preserve useful editable authoring information; keep hidden/debug content opt-in or filtered through authored visibility.
5. **Security Breach spline deformation and Mimic landscape reconstruction:** substantial geometry work with clear real-map fixtures. DDGI and post-process conversion need explicit approximation policies and further format validation.

## Relevant implementation locations

- `bridge/GenericUnreal.cs`, `ComponentType`: generic component allowlist, native class normalization, explicit spline-mesh exclusion.
- `bridge/Program.cs`, `ExportUmapActors`: selected component export, attachment-ancestor retention, and template property inheritance. The current inherited-name set omits area-light/decal/text/effect-specific properties.
- `addon/formats/unreal_mesh/maps.py`, `import_map`: generic map route calls the shared placement code with `game_features=False`.
- `addon/formats/ue_map/map_import.py`, `import_map_entries`: creates the current mesh, point/spot light, parent and reflection-probe objects.
- `addon/formats/ue_map/worlds.py`: existing fog helpers expect title-specific environment structures; stock `FogDensity`/`FogHeightFalloff` need a new neutral conversion.
- `addon/formats/ue_map/particles.py`: existing Niagara placeholder helpers offer a starting point; the generic UMAP route does not currently supply those effects.

## Local evidence and reruns

Credentials remain in `.local/generic-test-games.json`. No credentials, game binaries, texture data or serialized property payloads are copied into this report. Raw inventories, detail exports and the probe source remain under the ignored `.local/UmapObjectProbe/` directory.

Local outputs:

- `results/security_breach-inventory.json` and `results/secret_of_the_mimic-inventory.json`: complete per-map class counts and examples.
- `results/*-details.json`: sampled properties, template defaults, runtime class normalization and warnings.
- `results/*-bridge-check.json`: six complete-map export comparisons.
- `results/summary.json`: complete aggregate counts/prevalence for every raw class.

Rerun the local probe from the repository root (the game drive must be available):

```powershell
dotnet build .local/UmapObjectProbe/UmapObjectProbe.csproj -c Release
& ./.local/UmapObjectProbe/bin/Release/net10.0/UmapObjectProbe.exe (Get-Location).Path security_breach inventory
& ./.local/UmapObjectProbe/bin/Release/net10.0/UmapObjectProbe.exe (Get-Location).Path secret_of_the_mimic inventory
& ./.local/UmapObjectProbe/bin/Release/net10.0/UmapObjectProbe.exe (Get-Location).Path security_breach details
& ./.local/UmapObjectProbe/bin/Release/net10.0/UmapObjectProbe.exe (Get-Location).Path secret_of_the_mimic details
python .local/UmapObjectProbe/audit_bridge.py
python .local/UmapObjectProbe/write_report.py
```

This probe changes no importer behavior, package artifacts or version metadata.
