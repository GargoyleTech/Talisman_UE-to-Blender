# Generic Unreal cutscenes

The generic cutscene importer reads cooked stock Unreal `LevelSequence` and
`MovieScene` data through CUE4Parse. It does not depend on a FNaF or Final
Fantasy game profile, execute Blueprints, or reconstruct the game's runtime.

## Importing

1. Configure a CUE4Parse game profile in Talisman's preferences: package folder,
   engine/game version, and optional AES key and `.usmap`. Oodle uses the shared
   library setting. Use the same profile and scale as your model/map imports.
2. Open **File > Import > Talisman > Generic UE4 > Cutscene (LevelSequence)**. Choose the
   profile, optionally filter the path, then **Load / Refresh Sequence List**.
3. Select one or more LevelSequences, or enter an exact mounted package path
   (which takes priority over the checklist). Choose a master sequence to include
   nested shots automatically; its shots stay together in the same scene.
4. For a single selection, optionally use **Inspect Actor Bindings** and choose
   scene objects as explicit targets. Empty targets use automatic resolution.
   Existing generic map imports are matched by source actor/component paths,
   not ambiguous names. Multiple selections use automatic binding resolution
   in new, empty scenes; explicit binding overrides require a single selection.
5. Set the start frame and import options, then import. A dedicated collection
   holds newly created actors. The scene frame rate is unchanged; authored tick
   times and nested playback rates are converted to that frame rate.
   A single selection imports into the current scene. Multiple selections each
   get a separate scene named after the selected sequence, with independent
   actors, animation, camera-cut markers and playback range. These scenes use
   the original scene's frame rate and the chosen start frame/options. Existing
   scenes are preserved, and Blender adds a suffix when a scene name is already
   in use. The first successful cutscene in browser order becomes active.
6. Read **UE Sequence Report | collection name** in Blender's Text Editor. The
   collection's `ue_import_report` property identifies the report. It records
   resolved/unresolved bindings, skipped tracks, asset failures and timing
   approximations. An import can finish with a useful partial scene and warnings.
   If one cutscene in a batch fails, its import is rolled back and its new scene
   is removed; the remaining selections are still imported. The import summary
   gives the failure count, with individual errors in the console.

**Load Missing Bound Actors** loads individual referenced level actors and
serialized Blueprint component defaults. This includes inherited component
overrides, but never runs construction scripts. It is not an automatic full-map
import. Unavailable/unsupported components can remain transform placeholders.

**Replace Existing Animation** is off by default. Occupied animation targets
are skipped and reported. Enabling it retains the previous active Action with
a fake user and mutes existing NLA tracks instead of deleting them. Shared
camera/light data becomes single-user when animated by a binding. A fatal
import rolls back imported animation and restores affected existing targets.

## Supported data

- Spawnable actors, level-bound actors, component bindings and explicit object
  overrides; static/skeletal models use the generic material/texture pipeline.
- Nested cinematic shots and subsequences, rational frame/tick rates, section
  bounds, start/end trims, positive playback scales and looping subsequences.
- Translation, rotation and scale channels, transform masks, absolute/additive
  transform blending, and linear section easing. Curves are baked at scene FPS
  with extra samples at section boundaries; quaternion signs stay continuous.
- Generic AnimSequences as retained Actions and timed NLA strips, including
  trim offsets, first-loop offsets, loop seams, reverse playback and overlapping
  absolute clip weights. Skeleton compatibility is checked without retargeting.
- Camera transforms, focal length/FOV, sensor dimensions, aperture and focus
  distance; camera cuts become timeline camera markers. Nested cuts take
  precedence, and gaps restore the original camera when one exists.
- Point/spot lights, intensity/color channels, spawn/visibility channels and
  KeepRelative attachments to actors, components, bones or skeleton sockets.
- Unsupported event times are retained as labelled markers, never executed.

Unreal units default to centimeters (scale 0.01); coordinates are converted
without title-specific root/rig corrections. New generic skeletal models keep
their reference-pose and source metadata for subsequent animation imports.
Material textures follow the selected generic material settings; unsupported
texture types retain labelled empty nodes rather than silently disappearing.

## Deliberate limitations

- No Blueprint gameplay/construction execution, Wwise/audio playback, Niagara
  or Cascade simulation, fades, postprocessing, runtime material animation,
  gameplay cameras, Control Rig or procedural animation. Their tracks are
  reported; this is not a frame-exact recreation of the game's rendering.
- KeepWorld/Snap attachment rules, reverse subsequence time scales, relative
  transform blends and AdditiveFromBase are skipped/reported. Non-local cooked
  sequence binding IDs only fall back to a GUID when it identifies one concrete
  actor unambiguously; other cases need an explicit binding override.
- Weighted cubic tangents and non-linear section easing are approximated and
  reported. Camera/light photometric and rendering behavior can differ from UE.
  Property tracks outside the supported camera/light/visibility set are skipped.
- Additive skeletal clips supported by the generic animation decoder are baked
  onto their reference pose, not reproduced as runtime additive animation layers.
  Montages, animation Blueprints, morph/material curves and notifies are excluded.
- Cyclic subsequences/attachments are guarded. Imports are limited to 512
  sequence instances and 100,000 scene-frame samples; extremely fast clip loops
  have a 10,000-seam limit and fall back to scene-FPS sampling with a warning.

## Validation

The neutral Blender fixtures cover nested tick rates/trims, looping, reverse
clips, overlapping clip weights, camera axes/lens/cuts, socket attachments,
visibility, shared camera data, separate scenes for multiple selections,
independent batch camera cuts/frame ranges, and partial/total failure rollback
on Blender 4.5 and 5.1.

Real stock UE4.27 assets tested include Security Breach's
`BurntrapBossMaster` (eight nested shots, 149 bindings and 11 animation sections)
and Secret of the Mimic's `LS_ReleaseItem` (two animation sections). Unsupported
event/audio/effect tracks remain report entries. Game data, AES keys, local
configuration, preview scenes and the user-provided Oodle DLL are not packaged.
