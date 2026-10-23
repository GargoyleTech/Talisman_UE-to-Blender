# UE4 local lights

Imported point, spot and rectangular lights share the **UE4 Light Attenuation**
node group. Edit their authored values under **Light Data Properties > Talisman
UE4 Light**. These controls drive the native emitter and the shader together;
animate the object controls instead of replacing the derived native Power,
Size or Spot Size drivers. The graphs and drivers work in saved files without
the add-on enabled.

Enable **Bake light parameters** in any package UMAP importer to replace the
parameter drivers with their evaluated static values. The option is on by
default and remembered with the other import settings. Power, exposure, emitter radius,
dimensions, temperature and helper placements then remain directly editable.
Baking happens after attachment transforms and material-parameter light
overrides. Lights with actions, NLA strips, animated source flags, unrelated
drivers or animated parents are skipped, as are lights whose data is shared
with unrelated objects. Cutscene imports retain their live controls.

The UE attenuation graph, source textures and emitter helpers remain intact.
After baking, native settings and UE shader-mask controls are independent:
edit Power/Radius/Size on the native light and attenuation/cone/barn-door masks
in the Talisman panel. Helper values are static too. **Apply UE Controls** on a
baked point/spot reapplies the retained UE authoring values, refreshes its
helpers and bakes the parameters again; it also restores power/radius from
those authoring values. Leave baking disabled when you want automatic
synchronization while editing UE controls.

The shader masks require **Cycles**. EEVEE uses native light settings and does
not evaluate light shader nodes. Use Cycles for the tube/soft-highlight helpers
as well: EEVEE does not reproduce their ray visibility and energy weighting.

## Falloff and emitter shape

- Inverse-square lights use UE's radius mask
  `clamp(1 - (distance / radius)^4, 0, 1)^2`. Cycles supplies distance falloff;
  the point/spot correction applies UE's fixed **1 cm²** distance bias.
- Exponent lights use `clamp(1 - (distance / radius)^2, 0, 1)^exponent`,
  canceling Cycles' inverse-square factor. Source Radius is an emitter size,
  independent of the distance bias. Zero attenuation radius emits no light.
- Spotlights use UE's squared cosine ramp between inner and outer half angles.
  The native cone has no additional feathering. Stock UE `InnerConeAngle` and
  `OuterConeAngle` are half angles; FF7 `InnerFullConeAngle` and
  `OuterFullConeAngle` are full angles. The displayed controls are half angles.
  Source-sized or nonuniformly scaled spots open the native cone to avoid clipping rays before the
  center-based UE mask is evaluated.
- Rectangular lights use distance from the light's center for their radius
  mask, independent of the sampled point on the emitter. Barn doors mask rays
  against a rectangular aperture. Available SourceTexture images color the
  emitter using its UV coordinates; missing images leave neutral emission and
  a visible status. Package imports use the existing session's texture options.
- Source Length uses five evenly weighted emitters along UE's local Z axis.
  Soft Source Radius adds glossy-only emitters with radius
  `sqrt(SourceRadius² + SoftSourceRadius²)`. Diffuse/volume lighting and its
  shadows retain Source Radius. These are approximations of UE's capsule
  integral and BRDF broadening; small, close or highly reflective subjects
  may reveal the samples. Blender's area integration, shadows, source-texture
  filtering and barn-door sampling also differ from UE's deferred renderer.

Use **Refresh Source Shape** after enabling or disabling Source Length or Soft
Source Radius manually. Existing samples follow edits automatically. Importing
an animated length or soft radius creates the necessary helpers even when the
first value is zero. Helpers are children of the primary light; move, hide and
animate the primary. Helper lights should not be edited independently.

**Use Blender Native Attenuation** bypasses the radial/cone/barn-door masks and
restores native spot feathering. Authored intensity conversion, source shape
and source textures remain active.

## Intensity, scale and color

The importer preserves authored **Intensity** and **IntensityUnits**. Derived
`IntensityNits` is used only when Intensity is absent. Lumens, candelas and legacy
unitless brightness follow the distinct point/spot/rect conversions in UE4.27.
Spot lumens depend on outer-cone solid angle. The drivers account for Cycles'
spot Power convention (the equivalent full sphere), so cone edits keep the
correct on-axis intensity. Nits-only exports use the emitter area.

Conversion uses an explicit RGB calibration of **683 lumens per radiant watt**.
It is a scene-linear convention, not electrical power or a measured lamp
spectrum. Change **Lumens per Watt** for another calibration. **Exposure
Multiplier** remains a separate artistic control. Map dialogs default to **Light exposure 5** stops. When supported, this sets native light Exposure while Power retains the converted base intensity; older Blender versions apply the same factor to Power. The Exposure driver is frozen along with Power when baking. UE pre-exposure, camera
exposure and tone mapping are not reproduced by the light shader. Physical
power scales with the square of the geometry import scale, preserving
illumination when importing an otherwise identical scene at another size.

Byte `LightColor` values are decoded from sRGB to linear RGB. Explicit
`LinearLightColor` / typed `FLinearColor` and Sequencer color channels retain
linear/HDR values. Temperature respects `bUseTemperature`. Blender 4.5 and 5.x
use native light power/color/temperature with neutral emission nodes. Earlier
versions use a Blackbody tint for temperature; power/color stay native.

Sparse stock UE exports use local-light defaults: intensity 5000 unitless,
attenuation radius 1000 cm, source radius/length/soft radius zero, spot inner
0° / outer 44° half angles, rect 64 × 64 cm, barn doors 88° / 20 cm. FF7 routes
retain their 90° full outer-cone default. Resolved component/template values
override defaults. Hidden/disabled component flags are preserved.

Static maps, generic Sequencer and FF7 EndCinema use the same control paths.
Animation supports intensity, color, radius, exponent, inverse-square mode,
source dimensions, both cone angles, barn doors and temperature/enabling.
VolumetricScatteringIntensity remains retained animation metadata; it does not
change Cycles volume scattering. IES profiles and light functions are deferred.

Reimport older lights to recover authored units, byte colors and all new
controls reliably. Rebuilding a shared group preserves its output links but
cannot infer authoring data that an older import discarded.

## References and verification

Implementation was checked against the local UE4.27 source:

- `Engine/Shaders/Private/DynamicLightingCommon.ush`: radial/spot attenuation.
- `DeferredLightingCommon.ush` and `CapsuleLightIntegrate.ush`: radius mask,
  fixed distance bias, capsule radius/length and soft source handling.
- `RectLight.ush`: rectangular light geometry and barn-door clipping.
- `Engine/Source/Runtime/Engine/Private/Components/LocalLightComponent.cpp`,
  `PointLightComponent.cpp`, `SpotLightComponent.cpp`, `RectLightComponent.cpp`:
  class defaults and photometric conversions.
- `Engine/Source/Runtime/Core/Private/Math/Color.cpp`: FColor sRGB decoding.
- Blender's [Cycles light synchronization](https://github.com/blender/blender/blob/v4.5.0/intern/cycles/blender/light.cpp)
  and [light controls](https://developer.blender.org/docs/release_notes/4.5/rendering/#lights):
  native power/color multiplication, normalization and temperature.

`bridge/blender_ue_light_test.py` checks controls and measures scene-linear
Cycles renders against the analytical radial/cone masks, area cutoff,
barn-door aperture and source texture. `bridge/blender_ue_light_animation_test.py`
checks both animation importers, import scale and saved-file drivers. Run with
Blender `--background --factory-startup --python-exit-code 1 --python <script>`.
