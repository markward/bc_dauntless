"""SPIKE (developer-only): the radial profile's `nebula` column drawn by the
existing nebula passes as one synthetic volume around the player.

Throwaway until Mark approves the look live (plan Task 13). Visibility uses
the spec's fit (a + b / i); sparseness raises the fbm floor as i falls.
"""
from __future__ import annotations

from engine.appc.nebula import DEFAULT_FBM_DIALS
from engine.appc.nebula_density import seed_for

SPIKE_RADIUS_GU = 3000.0
VIS_A, VIS_B = 55.625, 89.375
MIN_NEBULA = 0.01


def synthetic_volume(player):
    from engine.systems import profile as _profile
    found = _profile.locate(player)
    if found is None or found[0] is None or found[0].color is None:
        return None
    prof, r = found
    i = _profile.evaluate(prof, r).nebula
    if i < MIN_NEBULA:
        return None
    loc = player.GetWorldLocation()
    freq, gain, floor = DEFAULT_FBM_DIALS
    return {
        "spheres": [(loc.x, loc.y, loc.z, SPIKE_RADIUS_GU)],
        "rgb": tuple(prof.color),
        "visibility": VIS_A + VIS_B / i,
        "external_tex": "",
        "internal_tex": "",
        "fbm": (freq, gain, floor + (1.0 - i) * 0.6),
        "seed": seed_for(0.0, 0.0, 0.0),
    }
