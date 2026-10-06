"""The sensor model's tunables (sensor-tiers spec §7).

The first three defaults are BC's own, recovered by reverse engineering
(STBC-Reverse-Engineering-1/docs/gameplay/sensor-subsystem.md): a hard-coded
4.0 s identification dwell (GetIdentificationTime @0x005671C0), the near band at
half sensor range (IsObjectNear @0x00567440) and a 1.0 s periodic sweep
(interval at 0x008E50F4). RE tier, not tested.

The last four are play-test dials for sub-project 2
(2026-10-05-sensor-continuity-occlusion-design.md), not recovered BC values.

"overboost_threshold" is BC's recovered over-boost constant (1.2f at 0x0089054c, compared strictly-greater against NormalPowerPercentage in IsObjectVisible @0x005671D0; sub-project 3, 2026-10-06-sensor-overboost-memory-design.md). RE tier, not tested.

Read at use. Not persisted; tuned live through the shared / L O keys once
Developer Options -> Lighting -> "Dial keys" selects "sensors"
(engine/dev_dial_groups.py).
"""
DEFAULTS: dict = {
    "identification_time_s": 4.0,
    "near_fraction": 0.5,
    "sweep_period_s": 1.0,
    # Sub-project 2 (2026-10-05-sensor-continuity-occlusion-design.md) --
    # play-test dials, not recovered BC values.
    "continuity_window_s": 5.0,       # Mark's rule: concealed < this keeps identity
    "min_blocker_radius_gu": 2.0,     # rocks smaller than this never occlude
    "field_unknown_threshold": 0.5,   # field a(x) at/above this reads Unknown
    "nebula_unknown_threshold": 0.14, # half of sensor_detection.LOCK_BREAK_T
    # Sub-project 3 (2026-10-06-sensor-overboost-memory-design.md) -- BC's
    # recovered constant (0x0089054c), RE tier.
    "overboost_threshold": 1.2,       # NormalPowerPercentage strictly above this sees the set
}
DIAL_ORDER: tuple = tuple(DEFAULTS)
_STEP = {"identification_time_s": 0.5, "near_fraction": 0.05,
         "sweep_period_s": 0.25, "continuity_window_s": 0.5,
         "min_blocker_radius_gu": 0.25, "field_unknown_threshold": 0.05,
         "nebula_unknown_threshold": 0.01, "overboost_threshold": 0.01}
_MIN = {"identification_time_s": 0.5, "near_fraction": 0.05,
        "sweep_period_s": 0.25, "continuity_window_s": 0.5,
        "min_blocker_radius_gu": 0.25, "field_unknown_threshold": 0.05,
        "nebula_unknown_threshold": 0.01, "overboost_threshold": 0.5}
_MAX = {"near_fraction": 1.0, "field_unknown_threshold": 1.0,
        "nebula_unknown_threshold": 1.0, "overboost_threshold": 2.0}

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
    dev_dial_groups.register_group("sensors", DIAL_ORDER, current, _step)
