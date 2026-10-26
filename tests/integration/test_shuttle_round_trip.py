"""One Tau Ceti shuttle flies a whole round trip in free roam: out of the
Starbase 12 bay, through warp to the Dry Docks, twice round a dry dock, back
through warp and into the bay. Pins the service's legs together.

Measured 2026-10-26 (headless, 1 s steps): see the printed line; shuttle 1's
first cycle is about 455 s. Holds (a bay taken, an orbit band full) can
stretch a cycle to ~1,600 s with ten shuttles queueing, so the bound is
1,800 s: the worst case plus margin.
"""
import pytest

pytest.importorskip("_dauntless_host")

from tests.helpers import headless_mission as hm  # noqa: E402
from tests.integration.test_home_stations_free_roam import (  # noqa: E402
    _warp_to_starbase_12)
from tests.integration.test_quickbattle_setup_e2e import world  # noqa: E402,F401

_BOUND_S = 1800
_ORDER = ["UNDOCKING", "DEPARTING", "WARPING_OUT", "TO_DOCK", "CIRCLING",
          "LEAVING_DOCKS", "WARPING_BACK", "APPROACHING", "ENTERING",
          "DOCKED"]
_HOLDS = {"WAITING"}


def test_a_shuttle_completes_a_round_trip(world):
    from engine.systems import shuttle_service as ss
    from engine.systems import system_loader
    player = _warp_to_starbase_12()
    system_loader.ensure_loaded(player)
    hm.tick(2.0)
    first = ss.roster()[0]
    assert first.name == "TC Shuttle 1"
    seen = []          # phase changes, in order
    docks = set()
    elapsed = 2
    while elapsed < _BOUND_S:
        hm.tick(1.0)
        elapsed += 1
        name = first.phase.name
        if first.phase is ss.Phase.CIRCLING and first.dock_name:
            docks.add(first.dock_name)
        if not seen or seen[-1] != name:
            seen.append(name)
        if name == "DOCKED" and len(seen) > 1:
            break
    else:
        pytest.fail("no round trip in %d s: %s" % (_BOUND_S, seen))
    print("round trip: %d s, phases %s, docks %s" % (elapsed, seen, docks))
    # Ordered subsequence: every leg in order; only holds may interleave.
    # (It starts launched, so a leading DOCKED may or may not be seen.)
    steps = [p for p in seen if p not in _HOLDS]
    if steps[0] == "DOCKED":
        steps = steps[1:]
    assert steps == _ORDER, seen
    assert len(docks) == 1 and docks <= {"Dry Dock", "Dry Dock2", "Dry Dock3"}
    assert ss.losses() == []
