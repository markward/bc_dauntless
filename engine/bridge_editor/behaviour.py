"""Material behaviour over time (spec 2026-10-08-bridge-emitters §13.2). Pure.

A material's modifiers each carry a scope (bridge states). In state s the
output is (sum of emitters scoped to s) x (product of animations scoped to
s): rgb = sum(tint x level) x waves, k = sum(level) x waves (the received-
light dip, §11.2). DISPLAY space; lights convert (lights.py). State changes
cross-fade over the material's fade_s from the LIVE output."""
import math

from engine.bridge_editor import lighting_doc as ld

STATES = ld.STATES
_BY_INDEX = {0: "green", 1: "yellow", 2: "red", 3: "offline", 4: "special"}
DEFAULT_FADE_S = 0.5
MAX_FADE_CHAIN = 4
WHITE = {"modifiers": [{"type": "emitter", "scope": list(STATES), "tint": [1, 1, 1],
                        "level": 1}]}


def state_name(i) -> str:
    return _BY_INDEX.get(int(i), "green")


def state_index(name) -> int:
    return {v: k for k, v in _BY_INDEX.items()}[name]


def has_emitter(material) -> bool:
    return any(m["type"] == "emitter" for m in material.get("modifiers", ()))


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


def output(material, state, t):
    rgb, k, f = [0.0, 0.0, 0.0], 0.0, 1.0
    for m in material.get("modifiers", ()):
        if state not in m["scope"]:
            continue
        if m["type"] == "emitter":
            lv = float(m["level"])
            for i in range(3):
                rgb[i] += float(m["tint"][i]) * lv
            k += lv
        else:
            f *= wave_factor(m, t)
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

    def output(self, material, t):
        new_rgb, new_k = output(material, self.state, t)
        fade = float(material.get("fade_s", DEFAULT_FADE_S))
        if self.source is None or fade <= 0.0 or self.since >= fade:
            return new_rgb, new_k
        old_rgb, old_k = self.source.output(material, t)
        f = self.since / fade
        return (tuple(a + (b - a) * f for a, b in zip(old_rgb, new_rgb)),
                old_k + (new_k - old_k) * f)
