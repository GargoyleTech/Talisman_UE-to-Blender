"""UE4 authoring units to Blender's normalized radiant power.

The RGB convention is 683 photometric lumens per radiant watt. This is an
explicit scene-linear calibration, not an estimate of a bulb's electrical
wattage or spectrum. Import exposure is a separate multiplier. Distances are
scaled with the imported geometry; at 0.01 Blender units per cm, a unit is a m.
"""

import math

LUMENS_PER_WATT = 683.0
UNIT_CODES = {'UNITLESS': 0, 'CANDELAS': 1, 'LUMENS': 2, 'NITS': 3}


def unit_name(value):
    if isinstance(value, (int, float)):
        return {value: key for key, value in UNIT_CODES.items()}.get(int(value), 'UNITLESS')
    name = str(value or 'UNITLESS').rsplit('::', 1)[-1].strip().upper()
    # Remake's custom UE4 profile exports singular Candela/Lumen enum names.
    return {'CANDELA': 'CANDELAS', 'LUMEN': 'LUMENS', 'NIT': 'NITS'}.get(name, name)


def srgb_to_linear(value):
    value = max(0.0, value)
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def light_color(props):
    # FColor uses sRGB bytes. Explicit FLinearColor/HDR paths and Sequencer
    # channels are already linear and must not be divided by 255 or gamma'd.
    color = props.get('LinearLightColor', props.get('LightColor', {})) or {}
    linear = ('LinearLightColor' in props or props.get('LightColorSpace') == 'Linear'
              or props.get('LightColorType') == 'LinearColor')
    if isinstance(color, dict) and color.get('Type') in {'LinearColor', 'FLinearColor'}:
        linear = True
        color = color.get('Value', color)
    if not isinstance(color, dict):
        return (1.0, 1.0, 1.0)
    default = 1.0 if linear else 255.0
    values = tuple(float(color.get(channel, default)) for channel in 'RGB')
    return values if linear else tuple(srgb_to_linear(value / 255.0) for value in values)


def cone_angles(props, profile='UE4'):
    """Return UE-clamped half angles in radians, accepting both export dialects."""
    full = any(name in props for name in ('InnerFullConeAngle', 'OuterFullConeAngle'))
    full = full or (profile == 'FF7' and not any(name in props for name in ('InnerConeAngle', 'OuterConeAngle')))
    def number(name, default):
        value = props.get(name)
        return default if value is None else float(value)
    if full:
        inner = number('InnerFullConeAngle', 0) * 0.5
        outer = number('OuterFullConeAngle', 90) * 0.5
    else:
        inner = number('InnerConeAngle', 0)
        outer = number('OuterConeAngle', 44)
    inner = math.radians(min(89, max(0, inner)))
    outer = min(math.radians(89) + 0.001, max(inner + 0.001, math.radians(outer)))
    return inner, outer


def energy_expression(kind, *, native_exposure=False):
    """A save/load-safe Blender driver using only built-in math functions.

    i=intensity, u=unit code, q=inverse square, s=units/cm, e=exposure,
    k=lumens/W, a=outer half angle, r=radius, l=length, w/h=rect dimensions.
    Cycles spot power uses a hypothetical full sphere, even for a narrow cone.
    """
    pi = 'pi'
    if kind == 'AREA':
        photometric = f'(1 if u==2 else ({pi} if u==1 else (w*h*{pi} if u==3 else 16*s*s*{pi})))'
    else:
        lumens = '1' if kind == 'POINT' else '(2/max(1-cos(a),0.000001))'
        nits = f'(4*{pi}*{pi}*r*r+2*{pi}*{pi}*r*l)'
        photometric = f'((({lumens}) if u==2 else (4*{pi} if u==1 else ({nits} if u==3 else 64*{pi}*s*s))) if q else 4*{pi})'
    # Physical units refer to metres; preserve illumination when geometry is
    # imported at a non-default scale. Unitless conversion includes s already.
    scale = '(1 if u==0 or not q or u==3 else (s/0.01)**2)' if kind != 'AREA' else '(1 if u==0 or u==3 else (s/0.01)**2)'
    exposure = '(1 if e>0 else 0)' if native_exposure else 'e'
    return f'max(i,0)*{exposure}*{photometric}*{scale}/max(k,0.000001)'


def radiant_power(kind, intensity, units='UNITLESS', inverse_squared=True, scale=0.01,
                  exposure=1.0, efficacy=LUMENS_PER_WATT, outer=math.radians(44),
                  radius=0.0, length=0.0, width=0.64, height=0.64):
    # This function and the RNA driver intentionally share the conversion so
    # animated cones/dimensions cannot drift from their initial static values.
    values = dict(i=float(intensity), u=UNIT_CODES.get(unit_name(units), 0), q=bool(inverse_squared),
                  s=scale, e=exposure, k=efficacy, a=outer, r=radius, l=length, w=width, h=height,
                  max=max, cos=math.cos, pi=math.pi)
    return eval(energy_expression(kind), {'__builtins__': {}}, values)
