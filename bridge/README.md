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

## Build

Requires the [.NET SDK](https://dotnet.microsoft.com/download) matching the
`TargetFramework` in `RebirthPackageLister.csproj` (currently `net10.0`).

```
dotnet build -c Release
```

This restores CUE4Parse/CUE4Parse-Conversion from NuGet and produces
`bin/Release/net10.0/FF7RGameAssetBridge.exe` plus its dependency DLLs.

## Deploying a rebuilt bridge

Copy the contents of `bin/Release/net10.0/` (the `.exe`, `.dll`, `.pdb`, and
`runtimes/` folder) into `../addon/bridge/`, replacing what's there.

## Usage

The add-on invokes the bridge as a subprocess in `asset-server` mode (one
JSON request per line on stdin, one JSON response per line on stdout). See
`PackageTextureLoader` in `../addon/games/rebirth/importers/packages.py` for the calling
convention, and the `Usage:` string at the top of `Program.cs` for the
one-shot CLI form.

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

`blender_generic_umap_test.py` indexes, probes, and imports real map packages
using the same ignored test config. `blender_generic_umap_fixture_test.py`
checks parenting, object material overrides, instanced props, shared armatures,
and separate collections for identically named maps. Generic map exports use
standard component classes and their template defaults; title adapters remain
disabled. Non-block-compressed generic textures use PNG/HDR rather than an
empty DDS payload.

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
