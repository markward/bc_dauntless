"""Running-light look dials (running-lights spec §4.5).

Play-test values calibrated from Mark's reference screenshot, not recovered BC
numbers (BC never visibly drew these lights). Read at use: the host loop
pushes current() to native every frame there are lights. Tuned live with the
shared / L O keys once Developer Options -> Diagnostics -> "Dial keys"
selects "running lights" (engine/dev_dial_groups.py). Not persisted.
"""
DEFAULTS: dict = {
    "size_gu_per_radius": 0.02,   # Radius 1.5 => 0.03 GU ~ 5 m
    "min_px": 2.5,                # smallest on-screen diameter; below ~2 px a
                                  # sprite centred on a pixel corner twinkles
    "intensity": 4.0,             # HDR multiplier; above the bloom threshold
}
DIAL_ORDER: tuple = tuple(DEFAULTS)
_STEP = {"size_gu_per_radius": 0.002, "min_px": 0.25, "intensity": 0.25}
_MIN = {"size_gu_per_radius": 0.001, "min_px": 0.5, "intensity": 0.25}

_dials: dict = dict(DEFAULTS)


def reset() -> None:
    global _dials
    _dials = dict(DEFAULTS)


def current() -> dict:
    return dict(_dials)


def _step(name: str, direction: int) -> None:
    v = _dials[name] + (_STEP[name] if direction > 0 else -_STEP[name])
    _dials[name] = max(_MIN[name], round(v, 4))


def register() -> None:
    from engine import dev_dial_groups
    dev_dial_groups.register_group("running lights", DIAL_ORDER, current, _step)
