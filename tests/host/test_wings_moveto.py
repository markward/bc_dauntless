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


def test_moveto_never_done():
    ship, member, script = _scene()
    for p in (None, (0.0, 500.0, 0.0), (0.0, 1.0, 0.0)):
        member.move_point = p
        assert script.Update() == AIC.US_ACTIVE
