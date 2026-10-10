"""Emitter profiles evaluated over time (spec 2026-10-08-bridge-emitters
§6.3, §11.3). Pure functions, no GL: one profile drives a shape's glow and
its cast light, so both read the same numbers.

A state is {tint, level, wave}; a missing state is off. `rgb = tint x level
x wave` is DISPLAY space (the glow adds it as is; lights convert, lights.py).
The wave runs on the bridge clock `t` (seconds, frozen under pause);
`phase` is a fraction of a period. An alert change cross-fades from the old
state to the new over the profile's `fade_s`, both evaluated live."""
import math

STATES = ("green", "yellow", "red")
DEFAULT_FADE_S = 0.5
STEADY_WHITE = {s: {"tint": [1, 1, 1], "level": 1} for s in STATES}


def state_name(alert_level) -> str:
    return {1: "yellow", 2: "red"}.get(int(alert_level), "green")


def profile_of(doc, emitter) -> dict:
    """The emitter's named profile, or the built-in steady white (§9.6)."""
    name = emitter.get("profile")
    return STEADY_WHITE if name is None else doc["profiles"][name]


def _smooth(x):
    x = min(max(x, 0.0), 1.0)
    return x * x * (3.0 - 2.0 * x)


def wave_factor(wave, t, phase=0.0) -> float:
    """1 at the peak, `min` at the trough. `sine` peaks at phase 0. `square`
    is on for `duty` of the period; `soft` is its rise (and fall) time as a
    fraction of the period, eased with a smoothstep (0 = a hard blink)."""
    if not wave or wave["shape"] == "steady":
        return 1.0
    lo = float(wave.get("min", 0.0))
    x = (float(t) / float(wave["period_s"]) + float(phase)) % 1.0
    if wave["shape"] == "sine":
        f = 0.5 + 0.5 * math.cos(2.0 * math.pi * x)
    else:
        duty = float(wave.get("duty", 0.5))
        soft = float(wave.get("soft", 0.0))
        if soft <= 0.0:
            f = 1.0 if x < duty else 0.0
        else:
            f = min(_smooth(x / soft), 1.0 - _smooth((x - duty) / soft))
    return lo + (1.0 - lo) * f


def state_output(profile, state, t, phase=0.0):
    """((r, g, b), k) for one state at time t: rgb = tint x level x wave,
    k = level x wave. A missing state is off."""
    st = profile.get(state)
    if st is None:
        return (0.0, 0.0, 0.0), 0.0
    k = float(st["level"]) * wave_factor(st.get("wave"), t, phase)
    return tuple(float(c) * k for c in st["tint"]), k


MAX_FADE_CHAIN = 4


class AlertFade:
    """Which state the bridge shows and how far through the cross-fade into
    it. One per bridge: every profile fades on the same alert change, each
    over its own `fade_s`. A fade starts from the LIVE output (spec §6.3):
    a change mid-fade freezes the fade in progress as its `source`, so the
    output never jumps. Waves keep running inside a frozen source; only its
    blend weight stops. The chain is cut after MAX_FADE_CHAIN changes inside
    one fade (rapid toggling), the oldest becoming a plain state."""

    def __init__(self, alert_level=0):
        self.state = state_name(alert_level)
        self.since = math.inf
        self.source = None

    def set_alert(self, alert_level):
        s = state_name(alert_level)
        if s == self.state:
            return
        frozen = AlertFade.__new__(AlertFade)
        frozen.state, frozen.since, frozen.source = self.state, self.since, self.source
        node, depth = frozen, 1
        while node.source is not None:
            if depth >= MAX_FADE_CHAIN:
                node.source = None
                break
            node, depth = node.source, depth + 1
        self.state, self.since, self.source = s, 0.0, frozen

    def advance(self, dt):
        self.since += max(float(dt), 0.0)

    def output(self, profile, t, phase=0.0):
        new_rgb, new_k = state_output(profile, self.state, t, phase)
        fade = float(profile.get("fade_s", DEFAULT_FADE_S))
        if self.source is None or fade <= 0.0 or self.since >= fade:
            return new_rgb, new_k
        old_rgb, old_k = self.source.output(profile, t, phase)
        f = self.since / fade
        return (tuple(a + (b - a) * f for a, b in zip(old_rgb, new_rgb)),
                old_k + (new_k - old_k) * f)
