# FF7R Rebirth Tools

One Blender add-on containing the retained FF7R tools:

All importers are under **File > Import > Talisman**, grouped into **FF7R**,
**Kingdom Hearts**, and **Generic UE4** submenus. FF7R contains Remake, Rebirth,
and Crisis Core sections; Kingdom Hearts contains III and 0.2 sections.
Animation importers are in their corresponding sections or the Generic UE4 menu.

Hover text is collected in [language/](language/README.md). The master
`language/tooltips.py` imports categorized text variables, with comments naming
the menus and controls that use them. Edit those category files to review or
revise tooltips; shared items reuse one definition.

- **Generic Unreal mesh and UMAP importers:** `File > Import > Talisman > Generic UE4 > Static mesh`, **Skeletal mesh**, and **UMAP** use the same editable CUE4Parse game profiles from the add-on preferences. A profile holds the game/package folder, CUE4Parse engine/game version, optional `.usmap`, AES key, and optional PBR texture-parameter mappings; one Oodle library path at the top of the preferences is shared by every CUE4Parse importer. Each asset type has its own dialog and remembered options. Use **Load / Refresh Asset List**, then select assets in the browser. Conventional geometry, normals, UVs, colors, material sections, skin weights, and mesh reference skeletons use the shared import pipeline. Each material contains an unconnected Material Output and unlinked Image Texture nodes for discovered texture parameters and references from its parent/material-function packages. Images are packed; unavailable textures retain labelled empty nodes. Each PBR slot supports an ordered list of Unreal texture-parameter names; the first name found is used. Every Metalness, Roughness, and Alpha name match has its own explicitly labelled R/G/B/A channel setting. KDI, physics, or title rig controls are not generated. Source identities keep materials and images from different game installations separate. Custom mesh layouts and textures CUE4Parse cannot decode remain unsupported.

  Texture-parameter mappings ignore case and support `*` for zero or more characters: `BaseColor*`, `*Normal*`, and `ORM*` can match families of parameter names. Patterns match the whole parameter name; other characters are literal. The first configured matching entry wins, using the first discovered parameter if its pattern matches several. Scalar channel settings belong to each entry and also apply to wildcard matches.

  Use **Test Profile (Skeletal Mesh)** in the profile editor to search the selected folder's packages for a skeletal mesh with readable geometry, without importing objects. Results appear below the button and identify missing/invalid AES keys, locked packages, and unreadable or suspect `.usmap` files. A mapping file that parses is only confirmed compatible when it successfully reads an unversioned skeletal mesh. The test stops at the first readable mesh; it does not certify every asset. **Cancel Profile Test** stops a running search.

  The included **Five Nights at Freddy's: Security Breach** and **Five Nights at Freddy's: Secret of the Mimic** profiles both default to UE 4.27, with their game folder and AES key left blank for you to supply. They were verified without `.usmap` files, including Security Breach DLC plugin content. Both static props and full skinned characters import through the same generic route. The asset list combines base-game and plugin asset registries, with a package-metadata scan when no usable registry is available.

  **Generic UMAPs** support multi-map batches, shared StaticMesh/SkeletalMesh datablocks, skeletal armatures and weights, component parent transforms, native instanced meshes/foliage, per-component material overrides, point/spot lights, and optional reflection probes. Every map receives its own collection and origin. Enable **Recursively import streaming levels** to include referenced sublevels once per batch; this route does not execute Blueprints, apply spline deformation, reconstruct landscape terrain, or import animations. Unsupported/missing texture references remain labelled empty image nodes. Compressed images stay DDS; ordinary grayscale/RGBA images use PNG, with HDR output when available.

- **UMAP importers:** the Rebirth section of `File > Import > Talisman > FF7R` includes separate Massive Environment entries for loose `.umap`/`.ubulk` files and maps mounted directly from Rebirth's packages. The package UMAP browser imports StaticMesh actors from mounted game data, sharing one Blender mesh datablock across repeated actors. **Experimental: Nearby MEC Terrain** checks each top-level map root in the selected East, West, or North continent and selects levels from its `EndStreamingVolume` brushes around a Blender-space radius. It imports those levels' MEC data at its coarsest LoD with one untextured material at continent-local coordinates by default; the continent's `0001-WORLD` origin is an optional placement offset. It is intended as quick rough context around an already-imported cutscene.
- **StaticMesh importer:** `File > Import > Talisman > FF7R`, in the Rebirth section, provides **Static mesh** for a mounted `.uasset` virtual path. It supports the update's flattened/meshlet layout and falls back to the earlier conventional layout, including their respective packed-normal formats. It imports geometry, custom normals and tangents, all UV channels, vertex colors, material slots, and package-path metadata. RMI_Surface material instances are built as their researched variant and their texture parameters are packed automatically; Unreal color parameters are represented by RGB constant nodes instead of image-texture nodes. This currently applies only to direct package StaticMesh imports and package-backed UMAP StaticMesh actors. The dialog is prefilled with `End/Content/Environment/Machine/Model/Machine_MagicStore_01A.uasset` as the verified reference asset.
- **Remake mesh importers:** Remake StaticMesh, SkeletalMesh, and UMAP imports build a basic Principled Blender material from the cooked Color, Metallic/Roughness/Variant, Normal, LDREmissive, and Occlusion texture parameters. Metallic/Roughness/Variant maps red to Metallic and green to Roughness; Variant is retained but not interpreted. Normal maps use DirectX convention. Texture extraction is best-effort because some Remake DDS payloads cannot currently be decoded. Remake's cooked properties still require a compatible mapping file even though the title is based on UE 4.18.
- **Crisis Core StaticMesh importer:** **Static mesh** in the Crisis Core section of `File > Import > Talisman > FF7R` indexes actual `UStaticMesh` assets from Reunion's `AssetRegistry.bin`, then imports conventional UE 4.27 geometry, normals, tangents, UV channels, vertex colors, named material sections, and package metadata. Materials remain placeholders because Crisis Core has its own material setup.
- **Remake and Crisis Core SkeletalMesh importers:** **Skeletal mesh** in the Remake and Crisis Core sections of `File > Import > Talisman > FF7R` indexes conventional `USkeletalMesh` assets alongside their static meshes. They preserve normals, tangents, UVs, material sections, per-vertex skin weights, and the linked Skeleton path. By default, each import builds and binds a new armature from that linked Skeleton; alternatively, it can bind the mesh to the active matching armature. Remake uses the basic material reconstruction described above; Crisis Core has its own material subset.
- **Crisis Core animation importer:** select a package-imported armature, then choose **Animation** in the Crisis Core section of `File > Import > Talisman > FF7R`. It lists AnimSequence clips linked to that exact Skeleton, including compatible clips shared across character variants. Select one or more clips to create separate, retained Actions, with configurable start frame and active Action assignment. Source timing is converted to the scene frame rate; ordinary root motion, the rig's bone axes and forward direction, and the model's import scale are preserved. New package armatures record their scale; older imports default to `0.01`. This uses the existing Crisis Core installation, mapping file, and shared Oodle preferences.
- **Remake and Crisis Core UMAP importers:** **UMAP** in the Remake and Crisis Core sections of `File > Import > Talisman > FF7R` indexes mounted map packages and creates their ordinary UE component placements. They reuse shared StaticMesh/SkeletalMesh datablocks for repeated assets, construct linked skeletons where available, and import point and spot light transforms and settings. Rebirth’s proprietary Massive Environment terrain route remains separate.
- **KineDriver importer:** select an armature, then open `File > Import > Talisman > FF7R` and use the Rebirth section's **KineDriver JSON (Loose files)** for loose files or **KineDriver** for a Rebirth package. The same menu's **Remake** section provides `KineDriver` for a configured Remake install and mapping file. Remake's older connector records are adapted into the shared KDI graph, including keyed link curves and aim/up direction targets. Each import audits the selected KDI internally and builds the driver layer in one operation. The audit graph is saved in the `.blend`; `Object > Retrilogy tools > KDI: Visualize Driver Graph` therefore opens it without asking for the KDI again. In Pose Mode, right-click a KDI-driven bone and choose **KDI: Focus Selected Bone in Graph** to show just the subgraph that drives it in any open node editor.
- **Animation importer (first pass):** select a package-imported armature, then open `File > Import > Talisman > FF7R` and use **Animation** in the Rebirth section. It records the source Skeleton on newly imported package armatures (and can infer it from a bound package SkeletalMesh in older scenes), searches compatible `AnimSequence` assets by Skeleton, and creates a named Blender Action. Source frame timing is converted to the current scene frame rate; UE local transforms retain the package rig's Blender bone-roll convention.
- **Opposite-face fix and KDI removal:** `Object > Retrilogy tools`.
- **Experimental mouth controls:** Rebirth SkeletalMesh and Skeleton import dialogs offer **Generate Mouth Controls (experimental)**, off by default. With **Build Skeleton from Package** enabled, this adds a non-deforming `FF7R_Jaw_CTRL` handle and eight lip handles: three upper, three lower, and two shared corners. Smooth interpolation spreads each handle's translation across nearby lip bones. Cloud `PC0000_00` and Tifa `PC0002_00` each use eight handles to pose 34 original lip/corner bones. Constraints preserve original bone parents, rest transforms, weights, and animation. Sparse facial layouts can still receive just the jaw layer; unsupported jaw layouts are skipped with a warning. This is an approximate posing rig, not a complete speech rig.

In Pose Mode, rotate the jaw handle around its local X axis to open the mouth, and move the rounded lip handles with **G** to shape it. Green upper and blue lower handles are joined by smooth guide curves; shared corner handles are gold. The lower handles follow the jaw. Original lip bones are hidden to reduce clutter; **Alt-H** reveals them for fine adjustments. Helpers remain in hidden bone collections. There is no add-on sidebar panel.

**Create limb IK controls** replaces the earlier naive IK checkbox in Remake/Rebirth package imports and remains off by default. It adds four box-shaped hand/foot targets and four diamond-shaped elbow/knee poles in the **IK Controls** bone collection. In Pose Mode, move a target with **G**, rotate it with **R** to orient its hand or foot, and move the matching pole to steer the bend. Controls follow the skeleton root but stay independent of hip and shoulder movement. The solver does not stretch limbs. Original bone parents and rest transforms stay unchanged; straight limbs receive a small additive bend constraint before IK to avoid solver stalls even after pose rotations are cleared, with normal numerical tolerance near full extension. This does not write to the original pose channels and needs no Python callback during playback. Missing, incomplete, or differently arranged limb chains are skipped. This is a basic posing rig, without foot roll, automatic FK/IK switching, or animation retargeting. For rigs imported with the earlier IK generator, select the armature (or its mesh) and run **F3 > Repair Generated Limb IK**, also available under **Object > Retrilogy tools**. This adds the persistent bend hints without clearing existing poses or animation; running it again does not duplicate them.

Settings live in the jaw control's custom properties: `influence`, `lip_follow`, `corner_follow`, and `jaw_side_follow` control the jaw layer; `lip_controls_influence` blends the eight lip handles; `show_lip_guides` toggles the guide curves. Zero jaw rotation and zero lip-handle translations restore the incoming pose. Set both influence properties to zero to disable all generated motion. These controls can be keyframed. For a different hinge, adjust only the new `FF7R_Jaw_CTRL` bone in Edit Mode. Wide openings and strong expressions may need fine adjustments to the original bones.

Existing imported characters can use **Object > Retrilogy tools > Generate Mouth Controls (experimental)**, also available through **F3**. Running it on the earlier jaw-only rig adds the lip handles in place and preserves the jaw settings and animation. Repeated generation does not duplicate controls. **Remove Generated Mouth Controls** removes the generated layers and restores original lip-bone visibility; both operations support undo. Shared armature data must be made single-user first. The generated constraints, guide curves, and simple property drivers are saved in the `.blend` and need no mouth-specific Python runtime during playback.

When building the KineDriver layer from loose JSON, the file browser includes independent translation and scale mappings and defaults to `X → X, Y → Z, Z → Y`. Package-built Remake and Rebirth armatures carry an intentional +90-degree display-bone roll; their package KDI importers detect that profile and automatically use `X → Y, Y → Z, Z → X` together with the matching rotation-frame conversion.

Implementation is split by responsibility: `core/` contains game-neutral bridge/profile and Blender infrastructure, including shared animation channels, collection routing and material-node helpers; `formats/unreal_package/` owns mounted sessions, indexes, mesh construction and map resolvers; `formats/unreal_mesh/` supplies generic Unreal policies; and the other format modules handle Unreal maps, KineDriver, Massive Environment and Bonamik data. `games/conventional_mesh.py` and `games/conventional_animation.py` provide the common title workflows. `games/<title>/` owns profiles, shaders and title-specific adapters; Rebirth retains MEC integration, RMI reconstruction, bone-space corrections and its extra rig passes. Legacy Rebirth package helper imports remain compatible. `ui/` contains Blender preferences, menus and UI operators; `bridge/` contains the packaged CUE4Parse runtime.

All twelve standard StaticMesh/SkeletalMesh operators, including generic Unreal, are defined by `formats/unreal_package/importer.py`. It owns their properties, saved settings, dialog lifecycle and `MESH_DIALOG_WIDTH`; the common layout lives in `ui/mesh_importer.py`. **UE4 options** appear first: scale, forward axis, opposite-face handling, and (for skeletal meshes) skeleton construction/binding, original bone axes, connected bones, mesh-referenced bone selection and attachment sockets. Native UE4 sockets can be imported as empties or non-deforming bones; generic Unreal leaves them off by default to preserve its earlier behavior. StaticMesh socket decoding is not implemented.

If mesh indexing finds package files but cannot read any of them, the importer reports a red Info-log error: **Zero readable packages. The usmap file might be missing or invalid.** Empty folders, filters with no matches, and readable packages without meshes do not trigger this hint. Failed empty scans are not cached; empty indexes saved by older builds are checked again.

The lower game-specific section contains only supported extras: Rebirth has KDI, variant bone collections, limb IK, eye and mouth controllers; Remake has KDI, variant bone collections and limb IK; Kingdom Hearts III/0.2 have KDI. Crisis Core and generic Unreal have no game-specific section. Unsupported legacy script properties remain hidden and are not remembered. Existing operator IDs, game materials, bone conventions and Rebirth BNM storage are retained.

Direct package imports use CUE4Parse's package import map for texture-path resolution, so they do not depend on `formats/mec/texture_hashes.csv`. The CSV remains available only for loose exports that have no package metadata.

During batch UMAP imports, decoded package data is released as soon as each map's metadata and actor payload has been handed to Blender. The bridge compacts its large-object heap at that boundary and transparently restarts if more than 2 GiB remains allocated, preventing recursive imports from retaining every previously decoded map.

Package-backed Massive Environment imports can also read the referenced block-compressed textures directly from the mounted game data. DDS payloads retain their native BC/DXT encoding, are packed into Blender image datablocks, and leave no extracted texture library behind.

All package UMAP importers share the same option rows: streaming recursion and scale; models, overlapping-face offsets, and packed textures; texture resolution and mip offset; separate point/spot light switches and shadows; exposure, attenuation radius, and light probes. Rebirth adds a **Massive Environment** section for originals, wind sway, and LoD selection. Turning off **Import models** skips both MEC terrain and conventional mesh placements.

All standard package UMAP operators are created by `formats/ue_map/package_importer.py`. It owns their properties, remembered settings, dialog lifecycle, browser row count, and `UMAP_DIALOG_WIDTH`. Game modules supply package/index configuration and import backends; Rebirth enables the optional Massive Environment section. Generic Unreal keeps its profile and index-filter controls above the same browser and options. Change the width once in that module to update every standard package UMAP dialog.

All textured UMAP importers (Rebirth packages and loose MEC files, Remake, Crisis Core, Kingdom Hearts III/0.2, and Generic Unreal) include **Texture Memory** controls. **Max Texture Resolution** limits the longest edge of newly loaded textures in pixels; `0` is unlimited. **Texture Mip Offset** accepts `0` through `-16`: `-1` requests half-size dimensions, `-2` quarter-size, and so on, using stored readable mips. Both controls apply to the highest readable resolution, and the smaller result wins; a 4096 texture with a 2048 cap and offset `-1` loads at 2048. Missing levels fall back to the next smaller readable level, or the smallest available level. If the cap cannot be met by a stored mip, the available image is resized while preserving its aspect ratio. Loose images without a supported DDS mip chain support the cap only. The untextured nearby-terrain importer does not load images.

Images are shared by source and texture path, and can only upgrade in resolution. A map reuses an existing higher-resolution image even when it exceeds that map's cap. A higher-quality map import or a manual StaticMesh/SkeletalMesh import upgrades the existing image datablock in place, updating every material that references it. Manual model imports always request the highest readable resolution. Image names retain their game names; custom properties record `ue_texture_source_width`/`ue_texture_source_height`, actual `ue_texture_width`/`ue_texture_height`, `ue_texture_mip_index` (the cooked mip-array index), and `ue_texture_mip_level` (levels below the highest readable resolution; fractional if a non-power-of-two cap requires resizing). The requested cap and offset are recorded as `ue_max_texture_resolution` and `ue_texture_mip_offset`. Lower-quality requests leave existing image contents and metadata intact.

The package browser supports arbitrary multi-map batches with persistent checkboxes, folder navigation, full-path search, and select/invert/clear controls. It remembers the last browsed folder until Blender is closed. Package mounting, the StaticMesh cache, and the packed-image cache are shared across the complete batch. `AutoGenCollision` paths are omitted because they do not contain usable Massive Environment geometry.

## Generic animation imports

Select an armature imported through the generic SkeletalMesh route, then use
**File > Import > Talisman > Generic UE4 > Animation**. Choose the same CUE4Parse
profile, load the compatible animation list, and select one or more clips.
An exact package path can also be entered directly. Every clip's Skeleton is
checked again when importing; unrelated Skeletons are not retargeted.

Each AnimSequence becomes a separate Action. Root motion, bone translation,
rotation and scale are retained, and source sample times are converted to the
current scene frame rate without changing that rate. The start frame, active
Action assignment and retention of unused Actions are configurable. New
generic model imports record their import scale and source profile, including
armatures placed by the UMAP importer. Older rigs default to scale 0.01; set
**Model Import Scale** to their original value if different.

Supported additive clips are baked onto their authored reference pose, not
imported as raw delta Actions. Skeleton-reference, fixed-animation-frame and
time-scaled-animation bases are supported for local and mesh-space rotation
additives. LocalAnimFrame bases are explicitly unsupported. Codec support
depends on CUE4Parse. Montages, composites, blend spaces, morph/material curves,
notifies, animation Blueprints and runtime procedural animation are not loaded.
The generic UMAP importer does not automatically play level animations.

## Generic cutscene imports

Use **File > Import > Talisman > Generic UE4 > Cutscene (LevelSequence)** with the same
CUE4Parse profile as generic models. Select one sequence; nested shots and
subsequences load automatically. Optional **Inspect Actor Bindings** lets you
map bindings to existing scene objects before importing. Missing bound actors
can be loaded from their serialized templates or level references without
importing the entire map or executing Blueprint scripts.

The importer creates editable transform/property Actions, skeletal NLA clips,
cameras and camera-cut markers, visibility/spawn animation, and supported
relative attachments, including skeleton sockets. Existing animation is
preserved by default. Every import writes a Text Editor report listing
unresolved bindings and unsupported tracks. Blueprint events, Wwise/audio,
effects and game-specific logic are not executed. See
[the cutscene guide](formats/unreal_mesh/README_SEQUENCES.md) for usage,
supported timing features and limitations.

## Installation

Install `ff7r_rebirth_tools.zip` through Blender's **Edit > Preferences > Add-ons > Install from Disk**, then enable **FF7R Rebirth Tools**.

Disable the separate FF7R UMAP importer and the old FF7R Actions add-on first. They register several of the same Blender operator identifiers, so running them together is not supported.

## KineDriver persistence

Keep this add-on enabled for any `.blend` file containing generated KineDriver drivers. The add-on restores the custom driver functions automatically when such a file is opened.

## Attribution

The UMAP importer payload is bundled from the supplied `ff7r_umap.zip`; its original author attribution is retained in the add-on metadata. The opposite-face operator preserves the behavior of the previous FF7R Actions tool.

## RMI_Surface source and provenance

The package StaticMesh RMI integration in `games/rebirth/materials/rmi_surface.py` loads its packaged builder, variant trimmer, and ground-truth table from `games/rebirth/materials/rmi_sources/`, with the sibling research checkout retained as a development fallback. The exact variant switch sets were generated from the current-build Renderer `MaterialInstance` exports' `StaticSwitchParameters`; the shader-method and RenderDoc provenance remain in that research project.

The bridge adds a mapping-independent MaterialInstance parameter read: CUE4Parse and the active `.usmap` provide the cooked `Parent`, texture, vector/color, and scalar parameter arrays. This lets the add-on assign packed DDS images to the appropriate RMI slots and convert matching Unreal vector/color parameters into Blender RGB constants without maintaining a second hand-authored parameter table.

The bundled `assets/Common_Eye_Player_NG_filtered.png` is a lossless 16-bit override for the exact shared game texture `/Game/Character/Common/Eye/Texture/Common_Eye_Player_NG`. It was derived from `O:/Blender/Rebirth DDS/Character/Common/Eye/Texture/Common_Eye_Player_NG.dds` with `tools/generate_common_eye_player_ng_override.py`. Two 3x3 binomial passes (equivalent to a 5x5 Gaussian) suppress BC5's 4x4 block boundaries before the eye shader amplifies them through cornea parallax; no other texture path uses the override.
