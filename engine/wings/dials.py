"""Wing tunables (spec 2026-11-09-wing-leaders-phase-a-design.md §7-§10).

Play-test values, not recovered BC numbers. Read at use; not persisted; tuned
live through / L O once Developer Options selects the "wings" dial group.
"""
DEFAULTS: dict = {
    "leash_gu": 200.0,
    "leash_slack_gu": 100.0,
    "regroup_gather_gu": 100.0,
    "engage_gu": 350.0,
    "wing_popularity": -0.3,
    "stickiness": 0.25,
    "odds_ratio": 0.8,
    "desperate_hull": 0.4,
    "ram_chance": 0.3,
    "brain_period_s": 1.0,
}
DIAL_ORDER: tuple = tuple(DEFAULTS)
_STEP = {"leash_gu": 25.0, "leash_slack_gu": 25.0, "regroup_gather_gu": 25.0,
         "engage_gu": 25.0, "wing_popularity": 0.1, "stickiness": 0.05,
         "odds_ratio": 0.05, "desperate_hull": 0.05, "ram_chance": 0.05,
         "brain_period_s": 0.25}
_MIN = {"leash_gu": 25.0, "leash_slack_gu": 0.0, "regroup_gather_gu": 25.0,
        "engage_gu": 25.0, "wing_popularity": -2.0, "stickiness": 0.0,
        "odds_ratio": 0.1, "desperate_hull": 0.0, "ram_chance": 0.0,
        "brain_period_s": 0.25}
_MAX = {"wing_popularity": 2.0, "stickiness": 1.0, "odds_ratio": 3.0,
        "desperate_hull": 1.0, "ram_chance": 1.0}

_dials: dict = dict(DEFAULTS)


def reset() -> None:
    global _dials
    _dials = dict(DEFAULTS)


def get(name: str) -> float:
    return float(_dials[name])


def current() -> dict:
    return dict(_dials)


def step(dials: dict, name: str, direction: int) -> dict:
    """Pure: one additive step, clamped to [_MIN, _MAX]."""
    out = dict(dials)
    v = round(out[name] + (_STEP[name] if direction > 0 else -_STEP[name]), 4)
    v = max(_MIN[name], v)
    if name in _MAX:
        v = min(_MAX[name], v)
    out[name] = v
    return out


def _step(name: str, direction: int) -> None:
    global _dials
    _dials = step(_dials, name, direction)


def register() -> None:
    from engine import dev_dial_groups
    dev_dial_groups.register_group("wings", DIAL_ORDER, current, _step)
