"""Per-bridge document -> static spot lights (spec 2026-10-08-bridge-emitters
§6.2, §9.6). Before the emitter plan, a profile contributes its CURRENT alert
state's tint x level as a steady colour (waves and fades come later); no
profile = steady white, level 1; a profile with no state for this alert = off."""

MAX_SPOTS = 32               # kBridgeMaxSpots
DEFAULT_INTENSITY = 2000.0   # kBridgeDefaultSpotIntensity; calibrate live
_STATE = {0: "green", 1: "yellow", 2: "red"}


def _colour(doc, emitter, alert_level):
    name = emitter.get("profile")
    if name is None:
        return (1.0, 1.0, 1.0)
    state = doc["profiles"].get(name, {}).get(_STATE.get(int(alert_level), "green"))
    if state is None:
        return None
    t, lv = state["tint"], float(state["level"])
    return (t[0] * lv, t[1] * lv, t[2] * lv)


def spots(doc, matched, alert_level):
    out, warnings = [], []
    for key in sorted(matched, key=lambda k: matched[k]):
        emitter = doc["shapes"].get(key, {}).get("emitter") or {}
        light = emitter.get("light")
        if light is None:
            continue
        colour = _colour(doc, emitter, alert_level)
        if colour is None:
            continue
        if len(out) >= MAX_SPOTS:
            warnings.append(f"{key}: dropped (more than {MAX_SPOTS} bridge lights)")
            continue
        out.append((tuple(light["position"]), tuple(light["direction"]),
                    light.get("inner_deg", 30), light.get("outer_deg", 60),
                    light.get("range", 200), colour,
                    light.get("intensity", DEFAULT_INTENSITY)))
    return out, warnings
