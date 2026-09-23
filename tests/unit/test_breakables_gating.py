# tests/unit/test_breakables_gating.py
"""Which stock ships may shed chunks -- pinned, with plan 1's caveat.

Radii are LITERALS from the spec's table (parent spec section 2.4, measured
2026-09-08), not read from GetRadius or a hull asset. So this test detects a
change to BREAKABLE_MIN_RADIUS_GU -- it names exactly which ships moved
sides -- but NOT a change to how GetRadius itself is derived. That would
re-sort the fleet silently; see the parent spec's section 8 for why.
"""
import pytest

from engine.appc import damage_geometry as dg


class _Ship:
    def __init__(self, r): self._r = r
    def GetRadius(self): return self._r


FLEET = {
    "Shuttle": 0.14, "BirdOfPrey": 1.34, "Freighter": 1.96, "CardFreighter": 2.00,
    "Marauder": 2.02, "Galor": 2.38,
    "Nebula": 2.42, "Akira": 2.55, "Ambassador": 3.14, "Keldon": 3.16,
    "Transport": 3.24, "KessokLight": 3.34, "Galaxy": 3.50, "Vorcha": 3.52,
    "Sovereign": 3.81, "CardHybrid": 4.96, "Warbird": 6.52, "KessokHeavy": 7.50,
}
# Every stock hull EXCEPT the Shuttle, as of the 2026-09-23 floor change
# (2.381 -- a Galor -- to 0.6, derived from kHullCarveRadiusMaxGu). The Shuttle
# stays out because its whole hull is a 5x6x4 voxel grid.
BREAKABLE = set(FLEET) - {"Shuttle"}


@pytest.fixture(autouse=True)
def _reset():
    dg.reset(); yield; dg.reset()


@pytest.mark.parametrize("name,radius", sorted(FLEET.items()))
def test_fleet_falls_on_the_documented_side_of_the_gate(name, radius):
    assert dg.breakables_allowed_for(_Ship(radius)) is (name in BREAKABLE), (
        f"{name} (radius {radius}) is on the wrong side of "
        f"BREAKABLE_MIN_RADIUS_GU={dg.BREAKABLE_MIN_RADIUS_GU}")


def test_the_sdk_flag_still_switches_it_off():
    dg.set_breakable_components_enabled(0)
    assert dg.breakables_allowed_for(_Ship(3.5)) is False
