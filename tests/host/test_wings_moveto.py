"""WingMoveTo: fly to the point the wing brain set on the member record
(spec 2026-11-09-wing-leaders-phase-b-design.md §6). Headless."""
import pytest

pytest.importorskip("_dauntless_host")

import App  # noqa: E402
import loadspacehelper  # noqa: E402

from engine.appc.sets import SetClass_Create  # noqa: E402
from engine.wings import decisions, dials, roster  # noqa: E402

AIC = App.ArtificialIntelligence


@pytest.fixture(autouse=True)
def _isolate():
    def _clear():
        App.g_kSetManager._sets.clear()
        roster.reset()
        dials.reset()
        decisions.reset_registry()
    _clear()
    yield
    _clear()


def _scene():
    pSet = SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "WingTest")
    ship = loadspacehelper.CreateShip("Akira", pSet, "m1", None, 0, 0)
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    group = App.ObjectGroup()
    group.AddName("e1")
    wing = roster.create_wing("blue", group)
    roster.add_member(wing, "m1")
    pAI = App.PlainAI_Create(ship, "MoveTo")
    pAI.SetScriptModule("WingMoveTo")
    return ship, roster.member("m1"), pAI.GetScriptInstance()


def test_moveto_turns_and_moves_toward_point(monkeypatch):
    ship, member, script = _scene()
    seen = []
    real = ship.TurnTowardLocation
    monkeypatch.setattr(ship, "TurnTowardLocation",
                        lambda v: (seen.append((v.x, v.y, v.z)), real(v))[1])
    member.move_point = (0.0, 500.0, 0.0)
    script.Update()
    assert seen == [(0.0, 500.0, 0.0)]
    assert ship.GetSpeedSetpoint()[0] > 0.0


def test_moveto_slows_near_and_stops_at_point():
    ship, member, script = _scene()
    speeds = {}
    for d in (500.0, 10.0, 1.0):
        member.move_point = (0.0, d, 0.0)
        script.Update()
        speeds[d] = ship.GetSpeedSetpoint()[0]
    assert speeds[500.0] > speeds[10.0] > 0.0
    assert speeds[1.0] == 0.0


def test_moveto_no_point_stops():
    ship, member, script = _scene()
    member.move_point = (0.0, 500.0, 0.0)
    script.Update()
    assert ship.GetSpeedSetpoint()[0] > 0.0
    member.move_point = None
    assert script.Update() == AIC.US_ACTIVE
    assert ship.GetSpeedSetpoint()[0] == 0.0


def test_moveto_never_done_while_a_member():
    ship, member, script = _scene()
    for p in (None, (0.0, 500.0, 0.0), (0.0, 1.0, 0.0)):
        member.move_point = p
        assert script.Update() == AIC.US_ACTIVE


def test_moveto_update_period_lets_the_tree_sleep():
    """Review I4: not every AI tick (0.0 pinned the tree walk awake); the
    move point only changes at the brain's 1 Hz. FollowObject's 0.2 s."""
    _ship, _member, script = _scene()
    assert script.GetNextUpdateTime() == pytest.approx(0.2)


def test_moveto_done_when_wing_gone():
    """Review M4: no member record (the wing was reset) -> DONE, like
    WingRejoin, instead of parking the ship forever."""
    ship, member, script = _scene()
    member.move_point = (0.0, 500.0, 0.0)
    script.Update()
    roster.reset()
    assert script.Update() == AIC.US_DONE


# ── attack slots (phase C) ─────────────────────────────────────────────────

def _slot_scene():
    ship, member, script = _scene()
    pSet = ship.GetContainingSet()
    target = loadspacehelper.CreateShip("BirdOfPrey", pSet, "e1", None, 0, 0)
    target.SetTranslateXYZ(0.0, 1000.0, 0.0)
    member.slot = ("e1", (-1.0, 0.0, 0.0), 120.0)
    return ship, member, script, target


def _record_turns(ship, monkeypatch):
    seen = []
    real = ship.TurnTowardLocation
    monkeypatch.setattr(ship, "TurnTowardLocation",
                        lambda v: (seen.append((v.x, v.y, v.z)), real(v))[1])
    return seen


def _slot_world(target, body_dir, standoff):
    R = target.GetWorldRotation()
    p = target.GetWorldLocation()
    cols = [R.GetCol(i) for i in range(3)]
    return tuple(
        (p.x, p.y, p.z)[k] + sum((cols[i].x, cols[i].y, cols[i].z)[k]
                                 * body_dir[i] for i in range(3)) * standoff
        for k in range(3))


def test_slot_tracks_target_live_pose(monkeypatch):
    ship, member, script, target = _slot_scene()
    seen = _record_turns(ship, monkeypatch)
    script.Update()
    first = _slot_world(target, (-1.0, 0.0, 0.0), 120.0)
    assert seen[-1] == pytest.approx(first, abs=1e-3)
    tp = target.GetWorldLocation()
    # Rotate 90 degrees about up: forward/right swap.
    m = App.TGMatrix3()
    m.MakeZRotation(1.5707963267948966)
    target.SetMatrixRotation(m)
    script.Update()
    second = _slot_world(target, (-1.0, 0.0, 0.0), 120.0)
    assert seen[-1] == pytest.approx(second, abs=1e-3)
    assert second != pytest.approx(first, abs=1.0)


def test_slot_faces_target_when_close(monkeypatch):
    ship, member, script, target = _slot_scene()
    p = _slot_world(target, (-1.0, 0.0, 0.0), 120.0)
    ship.SetTranslateXYZ(*p)
    seen = _record_turns(ship, monkeypatch)
    script.Update()
    tp = target.GetWorldLocation()
    assert seen[-1] == pytest.approx((tp.x, tp.y, tp.z), abs=1e-3)


def test_slot_dead_target_falls_back_to_move_point(monkeypatch):
    ship, member, script, target = _slot_scene()
    member.move_point = (0.0, 500.0, 0.0)
    monkeypatch.setattr(target, "IsDying", lambda: True)
    seen = _record_turns(ship, monkeypatch)
    script.Update()
    assert seen == [(0.0, 500.0, 0.0)]


# ── holding the slot (final review I3) ─────────────────────────────────────
# The ship is unrotated: its nose is world +y. The slot is at (-120, 1000, 0)
# (LEFT of the target at (0, 1000, 0), standoff 120).

def _speed(ship):
    return ship.GetSpeedSetpoint()[0]


def test_hold_no_thrust_when_the_slot_is_behind(monkeypatch):
    """Inside 20 GU the ship turns to the target and thrusts only by the
    slot offset along its nose: a slot behind it gets none (it used to
    drive on toward the target and through the slot)."""
    ship, member, script, target = _slot_scene()
    ship.SetTranslateXYZ(-120.0, 1010.0, 0.0)        # the slot 10 GU behind
    seen = _record_turns(ship, monkeypatch)
    script.Update()
    tp = target.GetWorldLocation()
    assert seen[-1] == pytest.approx((tp.x, tp.y, tp.z), abs=1e-3)
    assert member.slot_hold is True
    assert _speed(ship) == 0.0


def test_hold_thrust_scales_with_the_slot_ahead():
    ship, member, script, target = _slot_scene()
    ship.SetTranslateXYZ(-120.0, 990.0, 0.0)         # the slot 10 GU ahead
    script.Update()
    half = _speed(ship)
    ship.SetTranslateXYZ(-120.0, 1000.0, 0.0)        # on the slot
    script.Update()
    assert _speed(ship) == 0.0
    ship.SetTranslateXYZ(-120.0, 981.0, 0.0)         # 19 GU ahead
    script.Update()
    near_full = _speed(ship)
    assert 0.0 < half < near_full
    assert half / near_full == pytest.approx(10.0 / 19.0, rel=1e-3)


def test_hold_no_thrust_when_the_slot_is_beside():
    ship, member, script, target = _slot_scene()
    ship.SetTranslateXYZ(-105.0, 1000.0, 0.0)        # the slot 15 GU abeam
    script.Update()
    assert member.slot_hold is True
    assert _speed(ship) == pytest.approx(0.0, abs=1e-9)


def test_hold_hysteresis_twenty_in_forty_out(monkeypatch):
    ship, member, script, target = _slot_scene()
    seen = _record_turns(ship, monkeypatch)
    tp = target.GetWorldLocation()
    face = pytest.approx((tp.x, tp.y, tp.z), abs=1e-3)
    slot = pytest.approx((-120.0, 1000.0, 0.0), abs=1e-3)
    ship.SetTranslateXYZ(-120.0, 970.0, 0.0)         # 30 GU: not yet holding
    script.Update()
    assert member.slot_hold is False and seen[-1] == slot
    ship.SetTranslateXYZ(-120.0, 985.0, 0.0)         # 15 GU: holds
    script.Update()
    assert member.slot_hold is True and seen[-1] == face
    ship.SetTranslateXYZ(-120.0, 965.0, 0.0)         # 35 GU: still holds
    script.Update()
    assert member.slot_hold is True and seen[-1] == face
    ship.SetTranslateXYZ(-120.0, 955.0, 0.0)         # 45 GU: leaves
    script.Update()
    assert member.slot_hold is False and seen[-1] == slot
    assert _speed(ship) > 0.0


def test_hold_hysteresis_scales_with_the_standoff(monkeypatch):
    """Ruling 2026-11-09: in within min(20, 0.25 x standoff) of the slot,
    out beyond twice that. A 48 GU standoff: in at 12, out past 24. The
    slot is then at (-48, 1000, 0)."""
    ship, member, script, target = _slot_scene()
    member.slot = ("e1", (-1.0, 0.0, 0.0), 48.0)
    seen = _record_turns(ship, monkeypatch)
    tp = target.GetWorldLocation()
    face = pytest.approx((tp.x, tp.y, tp.z), abs=1e-3)
    slot = pytest.approx((-48.0, 1000.0, 0.0), abs=1e-3)
    ship.SetTranslateXYZ(-48.0, 985.0, 0.0)          # 15 GU: not yet
    script.Update()
    assert member.slot_hold is False and seen[-1] == slot
    ship.SetTranslateXYZ(-48.0, 989.0, 0.0)          # 11 GU: holds
    script.Update()
    assert member.slot_hold is True and seen[-1] == face
    ship.SetTranslateXYZ(-48.0, 977.0, 0.0)          # 23 GU: still holds
    script.Update()
    assert member.slot_hold is True and seen[-1] == face
    ship.SetTranslateXYZ(-48.0, 975.0, 0.0)          # 25 GU: leaves
    script.Update()
    assert member.slot_hold is False and seen[-1] == slot


def test_hold_radius_capped_at_twenty():
    """An 80 GU standoff (the cap) keeps 20 in / 40 out."""
    ship, member, script, target = _slot_scene()
    member.slot = ("e1", (-1.0, 0.0, 0.0), 80.0)
    ship.SetTranslateXYZ(-80.0, 981.0, 0.0)          # 19 GU
    script.Update()
    assert member.slot_hold is True
    ship.SetTranslateXYZ(-80.0, 961.0, 0.0)          # 39 GU
    script.Update()
    assert member.slot_hold is True
    ship.SetTranslateXYZ(-80.0, 959.0, 0.0)          # 41 GU
    script.Update()
    assert member.slot_hold is False
