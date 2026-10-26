"""One Tau Ceti shuttle flies a whole round trip in free roam: out of the
Starbase 12 bay, through warp to the Dry Docks, twice round a dry dock, back
through warp and into the bay. Pins the service's legs together.

Measured 2026-10-26 (headless, 1 s steps): see the printed line; shuttle 1's
first cycle is 505 s. Holds (a bay taken, an orbit band full) can
stretch a cycle to ~1,600 s with ten shuttles queueing, so the bound is
1,800 s: the worst case plus margin.

Headless, ships report GetRadius() == 0 (the host seeds it at realise), so
the second test seeds the radii the game gives these models and flies the
warp flythrough the game flies. Without them the trip never meets BC's
Intercept treating Starbase 12 (radius 296 GU) as a "very large ship" in the
shuttle's way, which live sent the fly-out circling the station at in-system
warp speed (2026-10-26).
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
# Live radii (GU), as host_loop._seed_ship_radius computes them from the
# models' boxes: FedStarbase.nif and the Shuttle's NIF.
_LIVE_RADII = {"Starbase 12": 296.4}
_LIVE_SHUTTLE_RADIUS = 0.16
# The open-space legs, flown straight: a turn, a 400 GU/s jump and the last
# 150 GU at impulse (~45 s headless). Circling the station never ends.
_LEG_BOUND_S = {"DEPARTING": 120, "APPROACHING": 120}


def _seed_live_radii():
    import App
    for pSet in App.g_kSetManager.GetAllSets():
        for obj in pSet.GetClassObjectList(App.CT_SHIP):
            if obj.GetRadius() > 0.0:
                continue
            if obj.GetName() in _LIVE_RADII:
                obj.SetRadius(_LIVE_RADII[obj.GetName()])
            elif obj.GetName().startswith("SB12 Shuttle"):
                obj.SetRadius(_LIVE_SHUTTLE_RADIUS)


def _fly_round_trip(capsys, monkeypatch, live=False):
    from engine.systems import shuttle_service as ss
    from engine.systems import system_loader
    player = _warp_to_starbase_12()
    system_loader.ensure_loaded(player)
    hm.tick(2.0)
    first = ss.roster()[0]
    assert first.name == "SB12 Shuttle 1"
    seen = [first.phase.name]   # phase changes, in order, as entered: a
    enter = ss._enter           # headless warp can start and end in one tick

    def _recording_enter(shuttle, phase):
        if shuttle is first:
            seen.append(phase.name)
        enter(shuttle, phase)

    monkeypatch.setattr(ss, "_enter", _recording_enter)
    docks = set()
    leg_s = {}         # seconds spent in each phase (sampled each second)
    elapsed = 2
    while elapsed < _BOUND_S:
        if live:
            _seed_live_radii()
        hm.tick(1.0)
        elapsed += 1
        name = first.phase.name
        leg_s[name] = leg_s.get(name, 0) + 1
        if first.phase is ss.Phase.CIRCLING and first.dock_name:
            docks.add(first.dock_name)
        if name == "DOCKED" and len(seen) > 1:
            if seen[-1] != "DOCKED":    # _dock sets it without _enter
                seen.append(name)
            break
    else:
        pytest.fail("no round trip in %d s: %s %s" % (_BOUND_S, seen, leg_s))
    print("round trip: %d s, phases %s, docks %s, legs %s" % (
        elapsed, seen, docks, leg_s))
    # Ordered subsequence: every leg in order; only holds may interleave.
    # (It starts launched, so a leading DOCKED may or may not be seen.)
    steps = [p for p in seen if p not in _HOLDS]
    if steps[0] == "DOCKED":
        steps = steps[1:]
    assert steps == _ORDER, seen
    assert len(docks) == 1 and docks <= {"Dry Dock", "Dry Dock2", "Dry Dock3"}
    assert ss.losses() == []
    # Docked again: out of the world, in no set at all.
    import App
    assert first.ship.GetContainingSet() is None
    assert not [pSet.GetName() for pSet in App.g_kSetManager.GetAllSets()
                if pSet.GetObject(first.name) is not None]
    assert "[shuttles]" not in capsys.readouterr().out
    return leg_s


def test_a_shuttle_completes_a_round_trip(world, capsys, monkeypatch):
    _fly_round_trip(capsys, monkeypatch)


def test_a_round_trip_with_live_radii_flies_its_open_legs_straight(
        world, capsys, monkeypatch):
    from engine.appc import warp
    warp.configure_warp_vfx(enabled=lambda: True,
                            vantage_of=lambda key: (10.0, 20.0, 0.0))
    try:
        leg_s = _fly_round_trip(capsys, monkeypatch, live=True)
    finally:
        warp.configure_warp_vfx()
    for leg, bound in _LEG_BOUND_S.items():
        assert leg_s[leg] <= bound, (leg, leg_s)
