"""Bridge AO look dials (renderer::BridgeAoTuning, bridge_ao_pass.h).

The defaults are renderer::BridgeAoTuning's: radius 30 / strength 1.8 were
Mark's live picks (2026-10-08), the detail kernel at 8 samples applied after
the diffuse ceiling his (2026-10-30, the DBridge panel frames). Tuned live
with the shared / L O keys once Developer Options -> Lighting -> "Dial keys"
selects "bridge ao" (engine/dev_dial_groups.py); every step pushes the whole
set to native. Not persisted.

The main kernel cannot see a step shallower than ~0.077 x radius (2.3 units
at radius 30): the DBridge side-panel frame is 1.5 deep. Two ways to try:
`min_len` (shorter main samples) with `bias_facing` 1, or the detail kernel
(`detail_samples` > 0, its own small radius, same pass).

AO only darkens the ambient downlight, so a wall lit mostly by an area light
(the DBridge panel bank under its cove strip) shows none of it: `detail_direct`
lets the detail AO also darken spot/area diffuse. A bright wall also sits on
the diffuse ceiling's knee, which flattens any darkening before it:
`detail_final` applies that share of the detail AO after the ceiling instead.
`main_direct` / `main_final` do the same for the main kernel (the pool under a
chair, which the ceiling strips otherwise light in full).
"""
from typing import Callable, Optional

DEFAULTS: dict = {
    "radius": 30.0,           # main kernel, view-space units
    "strength": 1.8,
    "bias": 0.5,              # view-space units
    "bias_dist": 0.01,        # bias per unit of distance from the eye
    "bias_facing": 0.0,       # 0 = distance bias in full, 1 = x (1 - N.V)
    "min_len": 0.1,           # shortest main sample, fraction of radius
    "main_direct": 0.0,       # 0..1 of the main AO on spot/area diffuse
    "main_final": 0.0,        # 0..1 of the main AO after the diffuse ceiling
    "detail_samples": 8,      # 0 = detail kernel off
    "detail_radius": 2.0,
    "detail_strength": 1.0,
    "detail_bias": 0.1,
    "detail_direct": 0.0,     # 0..1 of the detail AO on spot/area diffuse
    "detail_final": 1.0,      # 0..1 of the detail AO after the diffuse ceiling
}
DIAL_ORDER: tuple = tuple(DEFAULTS)
_STEP = {"radius": 2.0, "strength": 0.1, "bias": 0.1, "bias_dist": 0.002,
         "bias_facing": 0.1, "min_len": 0.01, "main_direct": 0.25,
         "main_final": 0.25, "detail_samples": 4,
         "detail_radius": 0.5, "detail_strength": 0.1, "detail_bias": 0.05,
         "detail_direct": 0.25, "detail_final": 0.25}
_MIN = {"radius": 1.0, "strength": 0.0, "bias": 0.0, "bias_dist": 0.0,
        "bias_facing": 0.0, "min_len": 0.01, "main_direct": 0.0,
        "main_final": 0.0, "detail_samples": 0,
        "detail_radius": 0.5, "detail_strength": 0.0, "detail_bias": 0.0,
        "detail_direct": 0.0, "detail_final": 0.0}
_MAX = {"bias_facing": 1.0, "min_len": 1.0, "main_direct": 1.0,
        "main_final": 1.0, "detail_samples": 32,
        "detail_direct": 1.0, "detail_final": 1.0}

_dials: dict = dict(DEFAULTS)
_push: Optional[Callable[[dict], None]] = None


def reset() -> None:
    global _dials, _push
    _dials = dict(DEFAULTS)
    _push = None


def current() -> dict:
    return dict(_dials)


def _step(name: str, direction: int) -> None:
    v = _dials[name] + (_STEP[name] if direction > 0 else -_STEP[name])
    v = min(_MAX.get(name, v), max(_MIN[name], v))
    _dials[name] = int(v) if name == "detail_samples" else round(v, 4)
    if _push is not None:
        _push(current())


def register(push: Callable[[dict], None]) -> None:
    """`push(dials)` sends the whole set to native (set_bridge_ao_tuning)."""
    global _push
    _push = push
    from engine import dev_dial_groups
    dev_dial_groups.register_group("bridge ao", DIAL_ORDER, current, _step)
