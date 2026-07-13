"""ReloadTorpedo broadcasts ET_TORPEDO_RELOAD with the TUBE as Destination.

Conditions/ConditionTorpsReady.py:140  registers a broadcast handler filtered on
                                       the tube (4th arg = destination filter)
Conditions/ConditionTorpsReady.py:169  reads App.TorpedoTube_Cast(pEvent.GetDestination())

ET_TORPEDO_FIRED is deliberately NOT covered here -- it is blocked on probe q12.
Episode7.TorpedoFired destroys the event's GetDestination() subsystem on a 10%
roll, so a wrong Destination destroys the wrong subsystem.
"""
import pytest

import App
from engine.appc.subsystems import TorpedoSystem, TorpedoTube


@pytest.fixture
def clock():
    App.g_kTimerManager._time = 0.0
    yield lambda t: setattr(App.g_kTimerManager, "_time", float(t))
    App.g_kTimerManager._time = 0.0


def test_et_torpedo_reload_is_a_real_int_not_a_stub():
    """An undefined App.ET_* falls through App's module __getattr__ to a
    _NamedStub, which is minted fresh on every access -- so a handler registered
    under it is unreachable forever."""
    assert isinstance(App.ET_TORPEDO_RELOAD, int)


def test_reload_broadcasts_with_the_tube_as_destination(clock):
    system = TorpedoSystem("Torpedoes")
    system.TurnOn()
    tube = TorpedoTube("Forward Torpedo 1")
    tube._reload_delay = 40.0
    tube._immediate_delay = 0.25
    tube._max_ready = 1
    tube._num_ready = 1
    tube._resize_slots()
    system.AddChildSubsystem(tube)

    seen = []
    App.g_kEventManager.AddBroadcastPythonFuncHandler(
        App.ET_TORPEDO_RELOAD, tube, __name__ + "._on_reload")
    globals()["_on_reload"] = lambda _obj, evt: seen.append(evt)

    clock(100.0)
    tube.Fire()
    assert tube.GetNumReady() == 0
    assert seen == []                     # nothing yet

    clock(140.0)
    tube.UpdateReload(0.0)

    assert tube.GetNumReady() == 1
    assert len(seen) == 1
    assert seen[0].GetDestination() is tube          # THE load-bearing assertion
    assert seen[0].GetSource() is system
    assert seen[0].GetEventType() == App.ET_TORPEDO_RELOAD
