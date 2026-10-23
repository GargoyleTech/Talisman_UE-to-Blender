# Basic map component conversions

The package map importer accepts these components on both generic and explicit
SQEX profile routes. The bridge preserves `SourceType` while normalizing the
two title aliases to their shared Blender handlers. Raw JSON entries with the
original alias names are accepted too.

| Unreal component | Blender result | Current limits |
|---|---|---|
| `DecalComponent` | One UV-mapped, textured quad in the local Y/Z plane, at the component origin | No surface projection, wrapping, receiver selection or runtime fading. Complex UE material graphs remain approximations. |
| `DirectionalLightComponent` | Sun light with authored rotation, color, intensity, source angle, shadows and visibility | No atmosphere, cascaded-shadow settings or renderer parity. |
| `CameraComponent` | Perspective or orthographic camera with the serialized viewpoint and field of view/width | No game camera controllers, runtime view switching or post-process simulation. |
| `CineCameraComponent` | Camera with filmback, focal length, aperture and supported static manual-focus settings | No automatic tracking or animated cinematic evaluation. Dedicated cinematic import remains a separate workflow. |
| `TresStaticMeshComponent` | The existing shared static-mesh placement path, including inherited mesh references | Existing geometry/material decoder limits still apply. |
| `EndTextRenderComponent` | Editable text through the existing text renderer | Uses Blender's font approximation. Construction scripts that generate text are not executed. |

## Controls and transforms

Decals, cameras and text follow **Import models**. Directional lights have a
separate **Import sun lights** checkbox in every package UMAP dialog and follow
the master light switch for scripted imports. Camera import preserves the
scene's active camera and render resolution. Per-camera aspect ratios are
stored as custom properties because Blender uses a scene-wide render aspect.

The bridge resolves the new components' authored properties through template
chains and retains required local attachment ancestors. The shared map code
handles deferred parents and sockets. Camera and sun local axes are corrected
from Unreal +X forward/+Z up to Blender -Z forward/+Y up.

## Decal approximation

`DecalSize` is an unscaled box extent. Quad spans are twice its Y and Z values;
`RelativeScale3D` is applied separately. Missing stock UE4 sizes use extents
(128, 256, 256) cm; explicitly serialized zero sizes remain zero. UVs follow the
engine's local (Z,Y) swizzle and the importer's usual image-space V flip.
These details were checked against the provided UE 4.27 engine source:
`DecalComponent.cpp` and `DeferredDecal.usf`.

The material inventory follows parent materials and resolves textures through
the active import session, including explicit SQEX profiles. Profile texture
mappings take precedence. Otherwise, identifiable color and normal textures
receive a small surface preview graph; a single unambiguously color-like
texture is also accepted. Color texture alpha supplies transparency when no
explicit alpha mapping exists. Other discovered textures remain available in
the material inventory. Missing/ambiguous textures are recorded on the object.
Preview materials have a separate cache identity and do not alter the original
mesh material. Their textures follow the importer's texture loading/packing
options. The plane remains at the projector origin and can float or intersect
the scene until positioned manually.

## Light and camera defaults

Directional intensity uses the existing scene calibration of 683 lm/W:
Blender sun energy = Unreal lux / 683, multiplied by import exposure. Distance
scaling does not change sun irradiance. The stock UE4 default is 10 lux and a
0.5357-degree source angle. Local-light attenuation nodes are not used.

Ordinary camera field of view is horizontal. A 36 mm sensor supplies an
equivalent Blender focal length. Cine cameras prefer authored filmback and
focal length; where filmback is omitted but field of view is retained, the
effective sensor width is derived from those values. If both are missing, the
UE 4.27 default digital-film width (23.76 mm) and 35 mm focal length are used
and the fallback is marked on the object. A game's unexported configuration
can override that engine default. Manual depth of field requires an authored
focus distance; disabled and tracking modes are retained without executing
tracking logic.

## Validation

- `bridge/blender_basic_map_components_test.py`: real Blender objects, quad
  extents and UVs, texture/alpha links, material-cache isolation, camera optics
  and direction, sun calibration/direction, late attachment, title aliases,
  visibility and import switches. Passed in Blender 4.5.3 and 5.0.1.
- Existing rectangular-light/text, generic map and shared UMAP option tests
  passed in Blender 5.0.1.
- Installed-game component samples passed across 12 map/class cases from
  Hogwarts Legacy, Marvel Rivals, Rebirth, Remake, Crisis Core, KH III and
  KH 0.2. These checks export the real maps and import selected components
  and their attachment transforms; they do not validate every complete map.
- KH 0.2's sampled collision mesh retains an existing warning for a plain
  master material that is not a MaterialInstance. Geometry imports successfully.

The earlier exhaustive class audit is a frozen assessment of the importer
before these conversions. This note records the subsequent implementation;
the old report's hashes and categories have not been rewritten.
