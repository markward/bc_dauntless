"""Engine emitters for three of the twelve gaps in docs/engine/event-emitter-gaps.md.

The q13 constant sweep made every one of these event types a real int, but
nothing in the engine POSTED them, so their SDK handlers stayed unreachable.
These three are the ones where the post is the only missing piece — no new
state and no fidelity guess (see the doc's tier split).

Events are captured by spying on App.g_kEventManager.AddEvent rather than by
registering SDK handlers: the contract under test is "the engine posts exactly
this event, exactly this often", and the negative cases (no post on spawn, no
post on a no-op abort, one post per cycle rather than per tick) are the whole
risk. AddEvent dispatches synchronously, so there is no drain step.
"""
import App
import pytest

from engine.appc.objects import ObjectClass
from engine.appc.ships import ShipClass
from engine.appc.ship_motion import _step_ship_motion
from engine.appc.subsystems import ImpulseEngineSubsystem, WarpEngineSubsystem

_DT = 1.0 / 60.0


@pytest.fixture
def posted(monkeypatch):
    """Every event the engine posts during the test, in order."""
    events = []
    monkeypatch.setattr(App.g_kEventManager, "AddEvent", events.append)
    return events


def _of_type(posted, event_type):
    return [e for e in posted if e.GetEventType() == event_type]


def _make_ship(x=0.0, y=0.0, z=0.0) -> ShipClass:
    s = ShipClass()
    s.SetTranslateXYZ(x, y, z)
    ies = ImpulseEngineSubsystem("IES")
    ies.SetMaxSpeed(6.3)
    ies.SetMaxAccel(1.5)
    s._impulse_engine_subsystem = ies
    return s


# ── ET_SET_WARP_SEQUENCE ─────────────────────────────────────────────────────
# Conditions/ConditionWarpingToSet.py:69 casts GetDestination() to
# WarpEngineSubsystem and re-reads GetWarpSequence() off it; the event carries
# no payload of its own. It is a "something changed, go re-check" ping.

def test_set_warp_sequence_posts_with_the_subsystem_as_destination(posted):
    warp = WarpEngineSubsystem("WES")
    warp.SetWarpSequence("Belaruz1")

    evts = _of_type(posted, App.ET_SET_WARP_SEQUENCE)
    assert len(evts) == 1
    assert evts[0].GetDestination() is warp


# ── ET_NAME_CHANGE ───────────────────────────────────────────────────────────
# ScienceMenuHandlers.py:272 (PropertyChange) casts GetSource() to ObjectClass
# and re-runs ExitedSet/ShipIdentified bookkeeping so a RENAMED ship's
# target-list row picks up the new name.
#
# SetName is also the spawn-time setter — backdrops, planets, asteroid fields,
# placements, lights, sets.py:183 and ships.py:1792 all call it, plus 114 SDK
# files. Posting on initial naming would run that bookkeeping for every object
# as it is constructed, before it is necessarily in a set. In BC the initial
# name is set inside Appc at construction, not through a broadcasting script
# call, so rename-only is the faithful reading as well as the quiet one.

def test_renaming_an_object_posts_with_the_object_as_source(posted):
    obj = ObjectClass()
    obj.SetName("Berkeley")          # initial naming — must be silent
    posted.clear()

    obj.SetName("Berkeley (derelict)")

    evts = _of_type(posted, App.ET_NAME_CHANGE)
    assert len(evts) == 1
    assert evts[0].GetSource() is obj


def test_initial_naming_does_not_post(posted):
    obj = ObjectClass()
    obj.SetName("Enterprise")
    assert _of_type(posted, App.ET_NAME_CHANGE) == [], (
        "spawn-time naming must stay silent — SetName is how every backdrop, "
        "planet, placement and ship gets its name at construction")


def test_setting_the_same_name_again_does_not_post(posted):
    obj = ObjectClass()
    obj.SetName("Enterprise")
    posted.clear()

    obj.SetName("Enterprise")

    assert _of_type(posted, App.ET_NAME_CHANGE) == []


# ── ET_IN_SYSTEM_WARP ────────────────────────────────────────────────────────
# ScienceMenuHandlers.py:515 (InSystemWarp) reads GetBool() and toggles the
# Launch Probe button while the player is mid-transit. Destination is the ship.

def test_engaging_in_system_warp_posts_true(posted):
    ship, target = _make_ship(), _make_ship(0.0, 1000.0, 0.0)

    assert ship.InSystemWarp(target, 295.0) == 1

    evts = _of_type(posted, App.ET_IN_SYSTEM_WARP)
    assert len(evts) == 1
    assert evts[0].GetBool() == 1
    assert evts[0].GetDestination() is ship


def test_a_rejected_engage_does_not_post(posted):
    """Already inside the threshold — InSystemWarp returns 0 without engaging."""
    ship, target = _make_ship(), _make_ship(0.0, 100.0, 0.0)

    assert ship.InSystemWarp(target, 295.0) == 0
    assert _of_type(posted, App.ET_IN_SYSTEM_WARP) == []


def test_explicit_abort_posts_false_once(posted):
    ship, target = _make_ship(), _make_ship(0.0, 1000.0, 0.0)
    ship.InSystemWarp(target, 295.0)
    posted.clear()

    ship.StopInSystemWarp()

    evts = _of_type(posted, App.ET_IN_SYSTEM_WARP)
    assert len(evts) == 1
    assert evts[0].GetBool() == 0
    assert evts[0].GetDestination() is ship


def test_abort_with_nothing_warping_does_not_post(posted):
    """AI LostFocus calls StopInSystemWarp unconditionally; a cancel that
    cancels nothing must not announce a stop."""
    ship = _make_ship()

    ship.StopInSystemWarp()

    assert _of_type(posted, App.ET_IN_SYSTEM_WARP) == []


def test_natural_completion_posts_false_exactly_once(posted):
    """The transit clears itself inside _step_in_system_warp. The stop must
    fire once on arrival, not once per tick of the transit."""
    ship, target = _make_ship(), _make_ship(0.0, 1000.0, 0.0)
    ship.InSystemWarp(target, 295.0)
    posted.clear()

    for _ in range(2000):
        if ship._insystem_warp_transit is None:
            break
        _step_ship_motion(ship, _DT)
    else:
        raise AssertionError("warp transit never completed")

    evts = _of_type(posted, App.ET_IN_SYSTEM_WARP)
    assert len(evts) == 1, "exactly one stop per transit, not one per tick"
    assert evts[0].GetBool() == 0
