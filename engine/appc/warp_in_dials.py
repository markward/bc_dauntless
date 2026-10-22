"""Warp-in look/slide dials (warp-in spec 6.1).

Play-test values, not recovered BC numbers. Read at use. Tuned live with the
shared / L O keys once Developer Options -> Diagnostics -> "Dial keys" selects
"warp in" (engine/dev_dial_groups.py). Not persisted.
"""
DEFAULTS: dict = {
    "slide_radii": 10.0,
    "core_radii": 1.5,
    "streak_radii": 8.0,
    "ring_radii": 3.0,
    "intensity": 4.0,
    "life_frac": 0.5,
    "tint_r": 0.75,
    "tint_g": 0.85,
    "tint_b": 1.0,
    "fallback_radius_gu": 2.0,
    # Timing (fractions of the flash life). Defaults = kStreakEnd / kRingRise
    # in native renderer/warp_in_flash_shape.h.
    "streak_end": 0.9,
    "ring_rise": 0.05,
}
DIAL_ORDER: tuple = tuple(DEFAULTS)
_STEP = {"slide_radii": 0.5, "core_radii": 0.5, "streak_radii": 0.5,
         "ring_radii": 0.5, "intensity": 0.5, "life_frac": 0.05,
         "tint_r": 0.05, "tint_g": 0.05, "tint_b": 0.05,
         "fallback_radius_gu": 0.25, "streak_end": 0.05, "ring_rise": 0.01}
_MAX = {"tint_r": 1.0, "tint_g": 1.0, "tint_b": 1.0, "streak_end": 1.0}
# Floors above 0: both are divisors / smoothstep edges in the shape.
_MIN = {"streak_end": 0.05, "ring_rise": 0.01}

_dials: dict = dict(DEFAULTS)


def reset() -> None:
    global _dials
    _dials = dict(DEFAULTS)


def get(name: str) -> float:
    return _dials[name]


def current() -> dict:
    return dict(_dials)


def _step(name: str, direction: int) -> None:
    v = _dials[name] + (_STEP[name] if direction > 0 else -_STEP[name])
    _dials[name] = min(_MAX.get(name, float("inf")),
                       max(_MIN.get(name, 0.0), round(v, 4)))


def register() -> None:
    from engine import dev_dial_groups
    dev_dial_groups.register_group("warp in", DIAL_ORDER, current, _step)
