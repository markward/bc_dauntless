"""Developer Options -> "Hull damage": coarse tuning rows for layered hull
damage (spec 2026-10-22-layered-damage-p4-finish §2.5).

Each value row cycles five presets around its default (default x 0.5, 0.75,
1, 1.5, 2; the rooms near distance 10/15/20/30/40 GU) and writes through the
path its owner already uses, so nothing here keeps a second copy of a value:

* the plating rows go through `plating_dials.set_value`, the same dials the
  developer / L O keys step (group "plating"), so a row and a dial step
  always agree and a dial step starts from the cycled value;
* the phaser rate and collision threshold are `hull_wear` module values, and
  the big blast tier's chance is `death_cascade.set_big_tier_chance` -- all
  read at use;
* the rooms near distance is the renderer's `set_interior_near_gu`.

"Reset hull damage dials" restores every row: plating rows from
`plating_dials.defaults()` (the native g_params defaults once registered),
the Python knobs from their DEFAULT_* constants. Debug dials (debug,
force_program, enabled) are not rows and are left alone.

None of these rows feeds structure-part detection (voxel::
detect_structure_parts runs with its own StructureParams defaults), so the
structure-parts disk cache key needs no change.

Developer-only: `rows()` is empty and `dispatch` refuses outside
--developer. Session-only, never persisted.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

import engine.dev_mode as dev_mode

_FACTORS = (0.5, 0.75, 1.0, 1.5, 2.0)
DEFAULT_NEAR_GU = 20.0          # renderer::InteriorPolicy::near_gu (drift-tested)
NEAR_PRESETS = (10.0, 15.0, 20.0, 30.0, 40.0)

# Plating rows: row key -> (label, plating dial name).
_PLATING = (
    ("hull_strip_wear", "Plating Strip Wear", "strip_wear"),
    ("hull_breach_wear", "Breach Wear", "breach_wear"),
    ("hull_deck_break_wear", "Deck Break Wear", "deck_break_wear"),
    ("hull_toughness_spread", "Toughness Spread", "toughness_spread"),
    ("hull_breach_lumps", "Breach Lumps", "breach_lumps"),
    ("hull_soot", "Soot", "soot"),
)
_PLATING_DIAL = {key: dial for key, _label, dial in _PLATING}

# (key, label, kind) in display order. kind: value | toggle | action.
_ROWS: Tuple[Tuple[str, str, str], ...] = tuple(
    (key, label, "value") for key, label, _dial in _PLATING) + (
    ("hull_phaser_rate", "Phaser Wear Rate", "value"),
    ("hull_collision_min", "Collision Wear Threshold", "value"),
    ("hull_big_blast_chance", "Big Death Blast Chance", "value"),
    ("hull_interior", "Interior Behind Holes", "toggle"),
    ("hull_near_gu", "Rooms Near Distance", "value"),
    ("hull_reset", "Reset hull damage dials", "action"),
)
ROW_KEYS: Tuple[str, ...] = tuple(key for key, _l, _k in _ROWS)
# Keys the panel dispatches as "action:" (everything but the toggle).
ACTION_KEYS = frozenset(key for key, _l, kind in _ROWS if kind != "toggle")

# Python-side mirror of the near distance, updated only when the setter
# succeeds: shown when the native getter is unavailable.
_near_gu = DEFAULT_NEAR_GU


def _plating():
    from engine.appc import plating_dials
    return plating_dials


def _hull_wear():
    from engine.appc import hull_wear
    return hull_wear


def _death_cascade():
    from engine.appc import death_cascade
    return death_cascade


def _scaled(default: float, cap: Optional[float] = None) -> tuple:
    out = []
    for f in _FACTORS:
        v = round(default * f, 4)
        out.append(min(v, cap) if cap is not None else v)
    return tuple(out)


def presets(key: str) -> tuple:
    if key in _PLATING_DIAL:
        pd = _plating()
        dial = _PLATING_DIAL[key]
        return _scaled(pd.defaults()[dial], pd._MAX.get(dial))
    if key == "hull_phaser_rate":
        return _scaled(_hull_wear().DEFAULT_PHASER_RATE)
    if key == "hull_collision_min":
        return _scaled(_hull_wear().DEFAULT_COLLISION_MIN_HULL_DAMAGE)
    if key == "hull_big_blast_chance":
        dc = _death_cascade()
        return _scaled(dc.DEFAULT_BLAST_SIZE_TIERS[-1][0])
    if key == "hull_near_gu":
        return NEAR_PRESETS
    raise KeyError(key)


def _near_value() -> float:
    try:
        from engine import renderer
        return float(renderer.interior_near_gu())
    except Exception:
        return _near_gu


def _set_near(gu: float) -> None:
    global _near_gu
    try:
        from engine import renderer
        renderer.set_interior_near_gu(gu)
    except Exception as e:  # a host without the binding: the row stays put
        dev_mode.log_swallowed("hull damage near distance", e)
        return
    _near_gu = gu


def value(key: str) -> float:
    if key in _PLATING_DIAL:
        return _plating().current()[_PLATING_DIAL[key]]
    if key == "hull_phaser_rate":
        return _hull_wear().PHASER_RATE
    if key == "hull_collision_min":
        return _hull_wear().COLLISION_MIN_HULL_DAMAGE
    if key == "hull_big_blast_chance":
        return _death_cascade().big_tier_chance()
    if key == "hull_near_gu":
        return _near_value()
    if key == "hull_interior":
        return _plating().current()["interior"]
    raise KeyError(key)


def _apply(key: str, v: float) -> None:
    if key in _PLATING_DIAL:
        _plating().set_value(_PLATING_DIAL[key], v)
    elif key == "hull_phaser_rate":
        _hull_wear().PHASER_RATE = v
    elif key == "hull_collision_min":
        _hull_wear().COLLISION_MIN_HULL_DAMAGE = v
    elif key == "hull_big_blast_chance":
        _death_cascade().set_big_tier_chance(v)
    elif key == "hull_near_gu":
        _set_near(v)
    else:
        raise KeyError(key)


def _next_preset(options: tuple, cur: float) -> float:
    for i, p in enumerate(options):
        if abs(p - cur) <= 1e-6 * max(1.0, abs(p)):
            return options[(i + 1) % len(options)]
    # Off-preset (a dial step moved it): the first preset above, else wrap.
    for p in options:
        if p > cur:
            return p
    return options[0]


def cycle(key: str) -> float:
    """Advance a value row to its next preset, apply it, return it."""
    nxt = _next_preset(presets(key), value(key))
    _apply(key, nxt)
    return value(key)


def toggle(key: str) -> bool:
    """Flip the interior row; returns the new state."""
    if key != "hull_interior":
        raise KeyError(key)
    on = value(key) <= 0.5
    _plating().set_value("interior", 1.0 if on else 0.0)
    return on


def reset() -> None:
    """Restore every row's default (debug dials untouched)."""
    pd = _plating()
    d = pd.defaults()
    pd.set_values({dial: d[dial] for dial in
                   list(_PLATING_DIAL.values()) + ["interior"]})
    hw = _hull_wear()
    hw.PHASER_RATE = hw.DEFAULT_PHASER_RATE
    hw.COLLISION_MIN_HULL_DAMAGE = hw.DEFAULT_COLLISION_MIN_HULL_DAMAGE
    _death_cascade().reset_blast_size_tiers()
    try:
        from engine import renderer
        near_default = float(renderer.interior_near_gu_default())
    except Exception:
        near_default = DEFAULT_NEAR_GU
    _set_near(near_default)


def reset_python_state() -> None:
    """The Python-side half of `reset`, touching nothing native: the
    hull_wear knobs, the blast tier table and the near-distance mirror,
    plus plating_dials back to import state (no push). For
    tests/conftest.py's autouse reset, which must stay headless-safe."""
    global _near_gu
    hw = _hull_wear()
    hw.PHASER_RATE = hw.DEFAULT_PHASER_RATE
    hw.COLLISION_MIN_HULL_DAMAGE = hw.DEFAULT_COLLISION_MIN_HULL_DAMAGE
    _death_cascade().reset_blast_size_tiers()
    _near_gu = DEFAULT_NEAR_GU
    _plating().reset_state()


def _num(v: float) -> str:
    return ("%.4f" % v).rstrip("0").rstrip(".")


def _text(key: str, v: float) -> str:
    if key == "hull_phaser_rate":
        return _num(v) + "×"
    if key == "hull_collision_min":
        return _num(v) + " hull"
    if key == "hull_big_blast_chance":
        return _num(v * 100.0) + "%"
    if key == "hull_near_gu":
        return _num(v) + " GU"
    return _num(v)


def rows() -> List[dict]:
    """The payload rows, in display order: {key, label, kind, value}. A
    value row's value is display text, the toggle's a bool, the action's
    None. Empty outside --developer."""
    if not dev_mode.is_enabled():
        return []
    out = []
    for key, label, kind in _ROWS:
        if kind == "value":
            val = _text(key, value(key))
        elif kind == "toggle":
            val = value(key) > 0.5
        else:
            val = None
        out.append({"key": key, "label": label, "kind": kind, "value": val})
    return out


def dispatch(action: str) -> bool:
    """Route a panel event ("action:hull_*" / "toggle:hull_interior").
    False for anything else, and for everything outside --developer."""
    if not dev_mode.is_enabled():
        return False
    verb, _, key = action.partition(":")
    if key not in ROW_KEYS:
        return False
    if verb == "toggle" and key == "hull_interior":
        toggle(key)
        return True
    if verb != "action" or key not in ACTION_KEYS:
        return False
    if key == "hull_reset":
        reset()
    else:
        cycle(key)
    return True
