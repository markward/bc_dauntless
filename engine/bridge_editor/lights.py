"""Per-bridge document -> bridge spot lights (spec 2026-10-08-bridge-emitters
§6.2, §11.4). The spot LIST is static -- geometry plus each spot's colour for
the green and the yellow/red probe captures -- and changes only with the
document, so an alert change or a pulse never recaptures the probes. The
live colour is evaluated every frame (`live_colours`), in the same order.

Colours: a profile's rgb is DISPLAY space (the glow adds it as is); a spot
lights in LINEAR, so it takes rgb^2.2 per channel. A capture colour is the
state's steady value, 0 when the state is off or pulsing (a pulsing light
is lit live but absent from the reflections until the probe layers)."""
from engine.bridge_editor import profiles

MAX_SPOTS = 32               # kBridgeMaxSpots
DEFAULT_INTENSITY = 2000.0   # kBridgeDefaultSpotIntensity; calibrate live
GAMMA = 2.2


def to_linear(rgb):
    return tuple(max(float(c), 0.0) ** GAMMA for c in rgb)


def _intensity(light):
    return light.get("intensity", DEFAULT_INTENSITY) * light.get("light_scale", 1.0)


def _capture(profile, state):
    st = profile.get(state)
    if st is None:
        return (0.0, 0.0, 0.0)
    wave = st.get("wave")
    if wave is not None and wave["shape"] != "steady":
        return (0.0, 0.0, 0.0)
    rgb, _ = profiles.state_output(profile, state, 0.0)
    return to_linear(rgb)


def _lit(doc, matched):
    """[(key, emitter)] for every emitter with a light, in mesh order, capped."""
    out, warnings = [], []
    for key in sorted(matched, key=lambda k: matched[k]):
        emitter = doc["shapes"].get(key, {}).get("emitter") or {}
        if emitter.get("light") is None:
            continue
        if len(out) >= MAX_SPOTS:
            warnings.append(f"{key}: dropped (more than {MAX_SPOTS} bridge lights)")
            continue
        out.append((key, emitter))
    return out, warnings


def spots(doc, matched):
    """([(pos3, dir3, inner_deg, outer_deg, range, colour3, intensity,
    capture_green3, capture_alert3)], warnings). Every lit emitter is listed,
    off or not, so live_colours stays index-aligned; `colour3` starts as the
    green capture and is replaced every frame."""
    lit, warnings = _lit(doc, matched)
    out = []
    for _key, e in lit:
        light, prof = e["light"], profiles.profile_of(doc, e)
        green = _capture(prof, "green")
        out.append((tuple(light["position"]), tuple(light["direction"]),
                    light.get("inner_deg", 30), light.get("outer_deg", 60),
                    light.get("range", 200), green, _intensity(light),
                    green, _capture(prof, "yellow")))
    return out, warnings


def live_colours(doc, matched, fade, t):
    """Per spot (spots() order), this frame's linear radiance: the profile
    evaluated through `fade` at bridge time `t`, ^2.2, x intensity."""
    lit, _ = _lit(doc, matched)
    out = []
    for _key, e in lit:
        rgb, _k = fade.output(profiles.profile_of(doc, e), t, e.get("phase", 0.0))
        k = _intensity(e["light"])
        out.append(tuple(c * k for c in to_linear(rgb)))
    return out
