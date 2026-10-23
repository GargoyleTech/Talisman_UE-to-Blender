# FF7 Rebirth Phantom: compact material function

Open `ff7r_phantom.py` in Blender's Text Editor, select an object with the
destination material active, and run it. It inserts **FF7R Phantom — BodyA**
and a connected surface-normal node. Existing nodes and shader connections
remain intact. If invoked from a Shader Editor, `insert_phantom()` also supports
its currently edited subgroup and pinned material.

The core contains **27 nodes**, including Group Input and Group Output.
The optional general occlusion path contains **35**. These counts include
every internal node; there are no hidden helper groups or script/OSL nodes.
Texture sampling and the optional BC5 normal decoder live upstream, so their
cost is additional: one UV node per UV set, two nodes per scalar image, and
one image plus eight nodes for a BC5 normal. Reuse an existing mapped normal
and image samplers by linking their outputs directly to the group instead.

## Connections

Connect **Color** to an Emission shader's Color or a shader's emission colour.
Use emission strength **1** for the captured unlit result. Adding diffuse
lighting changes the intended Phantom appearance. **Alpha** is a separate
output: Blender shader colour sockets do not provide a writable alpha channel.
The two outputs together represent the requested RGBA. Connecting Color alone
does not make the material transparent; connect Alpha to the destination's
alpha control or a Transparent/Emission shader mix as appropriate.

| Input | Expected data |
|---|---|
| Normal | Unit **world-space** mapped normal. The script initially connects the surface normal. |
| Roughness | Red of `Material_Texture2D_3` at UV0; use directly. Default 0.5. |
| Wide Occlusion | Red of `Material_Texture2D_11` at UV1. Default 1. |
| Blue Noise | Scalar red sample of `View_BlueNoiseVolumeTexture`, **not** a dissolve threshold. Default 0.5 gives the smooth mean response. |
| Tone 0 / Tone 1 | Linear HDR RGB from `ToneGradient.Load(0,0)` / `.Load(1,0)`. Black/white defaults are neutral placeholders. |
| External Emissive | `Material_VectorExpressions[19].rgb`, including any desired exposure compensation. Default white. |
| Depth Gap | Linear scene depth minus surface view depth, both in the same units. Default large positive value disables intersection fading. |
| Fade Distance | Depth-fade span in those units. Insertion converts the game's default 50 cm into the scene's unit scale. |

Set the optional `IMAGES` dictionary near the start of the script to image
datablocks or absolute filenames. The supported roles are `Normal`, `Roughness`,
`Wide Occlusion`, and `Tone Gradient`; `Occlusion` additionally requires
`INCLUDE_LOCAL_OCCLUSION = True`. Set `WIDE_UV_MAP` to the mesh's actual UV1
name. `UV_MAP = ""` uses the active render UV layer for UV0.

The scalar-image helpers explicitly extract **red**. Plugging an RGB image
directly into a float socket invokes Blender's luminance conversion and can
change a packed map. The normal helper reconstructs BC5 blue as
`sqrt(max(0, 1-x*x-y*y))`, then converts DirectX tangent space exactly once at
strength 1. Set `DIRECTX_NORMAL = False` for an already converted OpenGL map.
Data images receive a Non-Color copy when needed, preserving other materials'
interpretation of the original image.

The gradient helper reads the two unfiltered texels into the group's colour
parameters, adding **zero shader nodes**. Re-run `set_tone_gradient(node, image)`
after editing or replacing that image. Use the original **2×1 linear HDR/EXR**
texture. The helper handles the reference CUE4Parse HDR's short-scanline RLE
encoding, which Blender otherwise reads incorrectly. Its decoded exported
texels are `(0.0146484375, 0.0283203125, 0.044921875)` and
`(0.921875, 3.328125, 2.3125)`. These come from the RGBE export; they are not a
claim to have recovered additional precision from the original GPU texture.

No game assets or absolute asset paths are required at runtime. Insertion enables
material nodes if needed and preserves existing shader links and renderer settings.
Each run inserts a new instance; an existing source group is reused without
overwriting edits to its nodes.

## Reconstructed equations

Let `N` be the mapped world normal, `V = normalize(camera - position)`, `r` the
roughness red channel, `o` the wide occlusion red channel, `b` the original
blue-noise red sample, and `sat(x) = clamp(x, 0, 1)`:

```text
d = sat(dot(N, V))
e = 2^(-1 - 16*r)
s = sat(o - 1 + (o + d)^e)
t = sat((d^5 + (1-d)^5) * (0.5*N.z + 0.5) * b * s)
C = max(0, mix(Tone0, Tone1, t) * ExternalEmissive)

x = sat(DepthGap / FadeDistance)
A = x*x*(3 - 2*x)
RGB = C * A^8
RGBA = (RGB, A)
```

The mapped normal's **world Z** component is an independent up-facing weight.
The camera term has both `d^5` and `(1-d)^5`; replacing it with an ordinary
Fresnel node loses the front-facing lobe. Roughness changes an exponential
occlusion/facing term, rather than a BSDF's roughness. ToneGradient is a linear
mix of its first **two texels**, not an arbitrary sampled colour ramp.

The camera vector uses Camera Data transformed into world space. It remains
relative to the render camera when Cycles evaluates secondary rays. Geometry
Incoming would instead follow each incoming reflection/transmission ray.

For the captured BodyA, local `Occlusion` is the white renderer placeholder.
The original two-map expression simplifies **exactly** to `Wide Occlusion`.
For another Phantom material, enable the optional path to use the original:

```text
p = LocalOcclusion * WideOcclusion
m = min(LocalOcclusion, WideOcclusion)
o = m + (p-m) * (1 - (1 + p-m)^5)^5
```

The raw fade context is `Material_VectorExpressions[20].x`:
`FadeDistance_cm = max(1, context*50 if context > 0 else 50)`.
Supply that physical span when reproducing a non-default context.

## What remains supplied by the renderer

The group's math is exact **given its inputs**. A Blender surface shader cannot
fetch Unreal's resolved scene depth or its private 3D blue-noise texture.
Supply Depth Gap and the original Blue Noise sample upstream for those effects.
The default produces no intersection fade and no grain; it does not substitute
Ambient Occlusion, Perlin noise, or Ray Length for those resources.

The original spatial noise index is:

```text
q = roundToNearestEven(frac(VERTEX_EXPRESSION.xyz * 0.5) * 64)
index = (int(q.x) & 63, int(q.y) & 63, int(q.z) & 255)
b = View_BlueNoiseVolumeTexture.Load(index).r
```

Scene fog, scene pre-exposure, and primitive dynamic-visibility discard are
outside the function. With neutral fog and unit pre-exposure, the equations
above match the shader's output. To combine the original scene fog explicitly,
its final RGB form is `C*A^8*T + S*A`, where `T` and `S` are the combined fog
transmittance and in-scattering. Apply scene pre-exposure after that. Alpha
remains `A`. A full game-frame match additionally requires those renderer data,
the authored images, and the live material constants.

## Evidence and checks

The research folder's `SHADER_FINDINGS.md` identifies Gi Nattak
`NP0132_01_BodyA`, event **9187**, archive
`23354_3F1D1C73EF867FE4B547B5AC6E5B2B43152CC635`.
The capture index maps that event to:

```text
C:\temp\GiNattak\rd_dxil_shaders\09147_pi736266_Shader_8b8409ac_MainPS.dxil
C:\temp\GiNattak\rd_graphics_shaders\09147_ps736266_Shader_8b8409ac_MainPS__DXBC_DXIL.txt
```

The embedded shader hash is `ac09848bb2fd60b7d752433cd0496724`.
The capture and archive DXIL are byte-for-byte identical; both have SHA-256
`ffd96d0560611485e172a585e2650fa549e6c84ee60db063dd8d2a73cf74201a`.
In the disassembly, lines 764–811 decode the maps and combine occlusion,
814–860 build the camera/roughness/noise factor, 861–878 mix the gradient,
880–907 compute smooth depth fade, and 1335–1366 apply fade and write outputs.

Two earlier research interpretations are corrected by the actual bindings and
dataflow: the four Texture3D resources are **two noise resources plus two scene
fog resources**, and the Rec.709 dot in alpha receives `(A,A,A)`, so its result
is simply `A`. It does **not** measure the material's RGB luminance.

Verified in Blender **5.2.0 LTS**, Cycles and EEVEE: **144 numerical pixel
comparisons** across 36 input combinations and two camera positions per engine.
Checks cover HDR gradients, roughness, world-normal orientation, occlusion,
noise inputs, depth fading, and the optional full occlusion formula. Maximum
absolute pixel difference was 0.00348, including pixel-position sampling
differences. Group construction and insertion also pass in Blender **5.1.2**.
Existing material node identities and links were checked for preservation.
Additional rendered checks confirm BC5 reconstruction and DirectX conversion,
red-channel sampling from packed RGB data, preservation of unsaved input image
pixels, decoding of the reference HDR gradient, scene-unit conversion, and
execution through the script's normal Run Script entry point.
