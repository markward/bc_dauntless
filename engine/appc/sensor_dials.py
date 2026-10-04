"""The sensor model's tunables (sensor-tiers spec §7).

Defaults are BC's own, recovered by reverse engineering
(STBC-Reverse-Engineering-1/docs/gameplay/sensor-subsystem.md): a hard-coded
4.0 s identification dwell (GetIdentificationTime @0x005671C0), the near band at
half sensor range (IsObjectNear @0x00567440) and a 1.0 s periodic sweep
(interval at 0x008E50F4). RE tier, not tested.

Read at use. Not persisted; tuned live through the shared / L O keys once
Developer Options -> Lighting -> "Dial keys" selects "sensors"
(engine/dev_dial_groups.py).
"""
DEFAULTS: dict = {
    "identification_time_s": 4.0,
    "near_fraction": 0.5,
    "sweep_period_s": 1.0,
}
DIAL_ORDER: tuple = tuple(DEFAULTS)
_STEP = {"identification_time_s": 0.5, "near_fraction": 0.05,
         "sweep_period_s": 0.25}
_MIN = {"identification_time_s": 0.5, "near_fraction": 0.05,
        "sweep_period_s": 0.25}
_MAX = {"near_fraction": 1.0}

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
