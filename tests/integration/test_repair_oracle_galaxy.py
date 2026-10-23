"""The repair rule measured on the original game, replayed on a stock Galaxy.

Reference: stbc-oracle 1d57152, docs/bc-behaviour-bible.md §16 and harness
rows R1-R5 (§9); raw captures docs/results/repair_hull50*.json, reduced by
oracle/repair_report.py. Same scenario as the captures: a stock Galaxy, no
weapons, chosen subsystems set below max with SetCondition (no hit), 30 s.

Per item being worked, BC repairs

    MaxRepairPoints x (repair condition / repair max)
        / min(NumRepairTeams, items queued) / item RepairComplexity

points per second. The hull has no regeneration of its own: it is one item in
the repair subsystem's queue. Expected rates below are the captures' measured
numbers, ±3 % (zeros are exact). BC applies repair in ~0.33 s steps and we
repair every tick; a 30 s mean cannot tell the two apart, by design.
"""
import sys

import pytest

import App
from engine.core.loop import GameLoop, TICK_DELTA

RUN_S = 30.0
RATE_TOL = 0.03


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()
    # Flush ships.Hardpoints.galaxy so the next test reloads cleanly.
    for k in list(sys.modules):
        if k == "ships" or k.startswith("ships."):
            del sys.modules[k]


@pytest.fixture
def galaxy():
    """A stock Galaxy via the real SDK helper, headless. Engineering's
    property is a SHARED class template, so any value a case changes on it is
    put back afterwards."""
    import loadspacehelper
    pSet = App.SetClass_Create()
    pSet.SetName("repair_oracle")
    App.g_kSetManager._sets["repair_oracle"] = pSet
    ship = loadspacehelper.CreateShip("Galaxy", pSet, "Galaxy", None, 0, 0)
    assert ship is not None, "loadspacehelper.CreateShip returned None for Galaxy"
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    prop = ship.GetRepairSubsystem().GetProperty()
    saved = (prop.GetMaxRepairPoints(), prop.GetNumRepairTeams())
    yield ship
    prop.SetMaxRepairPoints(saved[0])
    prop.SetNumRepairTeams(saved[1])


def _named(ship, name):
    for s in ship.GetSubsystems():
        if s.GetName() == name:
            return s
    return None


def _preset(ship, preset, enqueue=False):
    """Set each named subsystem to a fraction of max, in order (order is the
    queue order, as in the captures)."""
    bay = ship.GetRepairSubsystem()
    subs = []
    for name, frac in preset:
        sub = _named(ship, name)
        assert sub is not None, name
        sub.SetCondition(sub.GetMaxCondition() * frac)
        if enqueue:
            bay.AddToRepairList(sub)
        subs.append(sub)
    return subs


def _run(seconds):
    loop = GameLoop()
    for _ in range(int(round(seconds / TICK_DELTA))):
        loop.tick()


# (capture, preset in order, change from stock, measured points/s per item)
CASES = [
    ("repair_hull50", [("Hull", 0.5)], {}, {"Hull": 16.73}),
    ("repair_hull50_enq", [("Hull", 0.5)], {"enqueue": True}, {"Hull": 16.74}),
    ("repair_hull50_cx1", [("Hull", 0.5)], {"hull_complexity": 1.0},
     {"Hull": 49.65}),
    ("repair_hull50_pts100", [("Hull", 0.5)], {"max_repair_points": 100.0},
     {"Hull": 33.48}),
    ("repair_hull50_sens50", [("Hull", 0.5), ("Sensor Array", 0.5)], {},
     {"Hull": 8.37, "Sensor Array": 25.09}),
    ("repair_hull50_sens50_t1", [("Hull", 0.5), ("Sensor Array", 0.5)],
     {"teams": 1}, {"Hull": 16.74, "Sensor Array": 0.0}),
    ("repair_hull50_eng50", [("Hull", 0.5), ("Engineering", 0.5)], {},
     {"Hull": 4.25, "Engineering": 6.36}),
    ("repair_hull50_eng0", [("Hull", 0.5), ("Engineering", 0.0)], {},
     {"Hull": 0.0, "Engineering": 0.0}),
]


@pytest.mark.parametrize("capture,preset,change,expected", CASES,
                         ids=[c[0] for c in CASES])
def test_repair_rate_matches_capture(galaxy, capture, preset, change, expected):
    bay = galaxy.GetRepairSubsystem()
    if "max_repair_points" in change:
        bay.GetProperty().SetMaxRepairPoints(change["max_repair_points"])
    if "teams" in change:
        bay.GetProperty().SetNumRepairTeams(change["teams"])
    if "hull_complexity" in change:
        galaxy.GetHull().SetRepairComplexity(change["hull_complexity"])
    subs = _preset(galaxy, preset, enqueue=change.get("enqueue", False))
    start = [s.GetCondition() for s in subs]
    _run(RUN_S)
    for (name, _), sub, c0 in zip(preset, subs, start):
        want = expected[name]
        got = (sub.GetCondition() - c0) / RUN_S
        if want == 0.0:
            assert sub.GetCondition() == c0, (capture, name, got)
        else:
            assert abs(got - want) <= RATE_TOL * want, (capture, name, got, want)


def test_hull_below_max_is_queued_without_a_hit(galaxy):
    """R1: no hit and no AddToRepairList, and the hull is being repaired by
    the next sample (BC: queued=0 straight after SetCondition, 1 a sample
    later, so assert after a tick)."""
    hull = galaxy.GetHull()
    hull.SetCondition(hull.GetMaxCondition() * 0.5)
    _run(TICK_DELTA)
    assert galaxy.GetRepairSubsystem().IsBeingRepaired(hull) == 1


def test_weapon_hit_on_hull_queues_it_for_repair(galaxy):
    from engine.appc.combat import apply_hit
    from engine.appc.math import TGPoint3
    galaxy.GetShields().TurnOff()
    hull = galaxy.GetHull()
    apply_hit(galaxy, 400.0, TGPoint3(0.0, -6.0, 0.0), None)
    assert hull.GetCondition() < hull.GetMaxCondition()
    assert galaxy.GetRepairSubsystem().IsBeingRepaired(hull) == 1


def test_zeroed_repair_subsystem_is_not_being_repaired(galaxy):
    """R5, the capture's being-repaired row: with Engineering at 0 the hull is
    flagged and Engineering never is."""
    hull, eng = _preset(galaxy, [("Hull", 0.5), ("Engineering", 0.0)])
    _run(1.0)
    bay = galaxy.GetRepairSubsystem()
    assert bay.IsBeingRepaired(hull) == 1
    assert bay.IsBeingRepaired(eng) == 0


def _walk(sub):
    yield sub
    for i in range(sub.GetNumChildSubsystems()):
        child = sub.GetChildSubsystem(i)
        if child is not None:
            yield from _walk(child)


def test_every_subsystem_finds_its_ship(galaxy):
    """A subsystem that cannot find its ship never reaches the repair queue,
    and nothing says so. The hull and its Bridge child were such subsystems."""
    lost = [s.GetName() for top in galaxy.GetSubsystems() for s in _walk(top)
            if s.GetParentShip() is not galaxy]
    assert lost == []
