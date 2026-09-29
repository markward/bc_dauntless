"""Nebula visual effects driven by the radial profile as well as BC's clumps.

Hull sparks represent radiation (Mark, 2026-09-29), so they follow the
profile's `radiation` level at the player; the impulse-engine wake follows
the `nebula` column. A local MetaNebula still drives both on its own, as
before. Pure functions; host_loop feeds them.
"""
from __future__ import annotations

from engine.appc.radiation import HULL_PER_S

WAKE_NEBULA_MIN = 0.05   # the cloud's thin floor: any visible gas leaves a wake


def discharge_inputs(in_clump: bool, clump_rate: float, sample, warping: bool):
    """(active, damage-rate in hull/s) for HullDischargeDriver.update.
    The profile contributes HULL_PER_S x radiation — the radiation LEVEL,
    independent of difficulty. Nothing while dashing."""
    if warping:
        return False, 0.0
    profile_rate = HULL_PER_S * max(0.0, sample.radiation)
    active = in_clump or profile_rate > 0.0
    if not active:
        return False, 0.0
    return True, max(clump_rate if in_clump else 0.0, profile_rate)


def wake_active(in_clump: bool, sample, warping: bool) -> bool:
    """Record the impulse wake inside a clump or anywhere the profile's gas
    reaches its floor. Nothing while dashing."""
    if warping:
        return False
    return in_clump or sample.nebula >= WAKE_NEBULA_MIN
