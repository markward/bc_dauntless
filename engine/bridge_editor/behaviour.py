"""Material behaviour over time (spec 2026-10-08-bridge-emitters §13.2, §14).
Pure.

The Finish `emission` is a steady white glow at that level in every state
but Power offline (dark, as an `_emissive` map is); unset, it is 1 on a
texture with an emission map (the map as painted) and 0 without. Modifiers
carry a scope (bridge states): State modifiers scoped to s REPLACE it there
(rgb = sum(tint x level)), Animations scoped to s multiply, and the blend
INTO s takes the last Transition scoped to s, else 0.5 s. k = the level
sum (the received-light dip, §11.2). DISPLAY space; lights convert
(lights.py). State changes cross-fade from the LIVE output."""
import math

from engine.bridge_editor import lighting_doc as ld

STATES = ld.STATES
_BY_INDEX = {0: "green", 1: "yellow", 2: "red", 3: "offline", 4: "special"}
DEFAULT_FADE_S = ld.DEFAULT_FADE_S
MAX_FADE_CHAIN = 4
WHITE = {"modifiers": [{"type": "state", "scope": list(STATES), "tint": [1, 1, 1],
                        "level": 1}]}


def state_name(i) -> str:
    return _BY_INDEX.get(int(i), "green")


def state_index(name) -> int:
    return {v: k for k, v in _BY_INDEX.items()}[name]


def drives_glow(material) -> bool:
    """Whether the material sets its surfaces' glow at all: an emission
    level, or a State or Animation modifier. Otherwise the texture's default
    stands (its `_emissive` map as painted, dark at offline; else nothing)."""
    return "emission" in material or any(
        m["type"] in ("state", "animation") for m in material.get("modifiers", ()))


def transition_s(material, state) -> float:
    """How long the blend INTO `state` takes: the last Transition scoped to
    it, else DEFAULT_FADE_S."""
    out = DEFAULT_FADE_S
    for m in material.get("modifiers", ()):
        if m["type"] == "transition" and state in m["scope"]:
            out = float(m["seconds"])
    return out


def _smooth(x):
    x = min(max(x, 0.0), 1.0)
    return x * x * (3.0 - 2.0 * x)


def wave_factor(anim, t) -> float:
    """1 at the peak, `min` at the trough; sine peaks at phase 0; square is
    on for `duty` with `soft` rise/fall (fractions of the period)."""
    lo = float(anim.get("min", 0.0))
    x = (float(t) / float(anim["period_s"]) + float(anim.get("phase", 0.0))) % 1.0
    if anim["shape"] == "sine":
        f = 0.5 + 0.5 * math.cos(2.0 * math.pi * x)
    else:
        duty, soft = float(anim.get("duty", 0.5)), float(anim.get("soft", 0.0))
        if soft <= 0.0:
            f = 1.0 if x < duty else 0.0
        else:
            f = min(_smooth(x / soft), 1.0 - _smooth((x - duty) / soft))
    return lo + (1.0 - lo) * f


def output(material, state, t, has_map=False):
    rgb, k, f, overridden = [0.0, 0.0, 0.0], 0.0, 1.0, False
    for m in material.get("modifiers", ()):
        if state not in m["scope"]:
            continue
        if m["type"] == "state":
            overridden = True
            lv = float(m["level"])
            for i in range(3):
                rgb[i] += float(m["tint"][i]) * lv
            k += lv
        elif m["type"] == "animation":
            f *= wave_factor(m, t)
    if not overridden and state != "offline":
        k = float(material.get("emission", 1.0 if has_map else 0.0))
        rgb = [k, k, k]
    return tuple(c * f for c in rgb), k * f


class StateFade:
    """The state the bridge shows and the cross-fade into it. A change mid-
    fade freezes the fade in progress as the new fade's source (never a jump);
    the chain is capped at MAX_FADE_CHAIN."""

    def __init__(self, state="green"):
        self.state, self.since, self.source = state, math.inf, None

    def set_state(self, state):
        if state == self.state:
            return
        frozen = StateFade.__new__(StateFade)
        frozen.state, frozen.since, frozen.source = self.state, self.since, self.source
        node, depth = frozen, 1
        while node.source is not None:
            if depth >= MAX_FADE_CHAIN:
                node.source = None
                break
            node, depth = node.source, depth + 1
        self.state, self.since, self.source = state, 0.0, frozen

    def advance(self, dt):
        self.since += max(float(dt), 0.0)

    def output(self, material, t, has_map=False):
        new_rgb, new_k = output(material, self.state, t, has_map)
        fade = transition_s(material, self.state)
        if self.source is None or fade <= 0.0 or self.since >= fade:
            return new_rgb, new_k
        old_rgb, old_k = self.source.output(material, t, has_map)
        f = self.since / fade
        return (tuple(a + (b - a) * f for a, b in zip(old_rgb, new_rgb)),
                old_k + (new_k - old_k) * f)
