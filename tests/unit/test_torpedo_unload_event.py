"""UnloadTorpedo posts ET_TORPEDO_FIRED with the TUBE as Destination, NO source.

BC's TorpedoTube_UnloadTorpedo (0x0057D9A0) ends in
TorpedoTube_PostTorpedoFiredEvent(0) (0x0057DA20): a TGEvent of type 0x800066
(ET_TORPEDO_FIRED), source = the argument (NULL here), destination = the tube.
(STBC-Reverse-Engineering-1 reference/decompiled_fresh/05_game_mission.c.)
It is how ConditionTorpsReady learns a tube was emptied by an ammo-type
switch: its TorpFired handler (Conditions/ConditionTorpsReady.py:177)
re-reads the tube counts. Without it the gate stays latched "ready" for the
whole reload and FedAttack flies torpedo runs with nothing loaded.

Source must stay None: Episode7.TorpedoFired destroys the event's destination
tube on a 10% roll, but only after Torpedo_Cast(pEvent.GetSource()) succeeds.
"""
import pytest

import App
from engine.appc.subsystems import TorpedoSystem, TorpedoTube


@pytest.fixture
def clock():
    App.g_kTimerManager._time = 0.0
    yield lambda t: setattr(App.g_kTimerManager, "_time", float(t))
    App.g_kTimerManager._time = 0.0


def _loaded_tube(name="Forward Torp 1"):
    system = TorpedoSystem("Torpedoes")
    system.TurnOn()
    tube = TorpedoTube(name)
    tube._reload_delay = 40.0
    tube._max_ready = 1
    tube._resize_slots()
    tube.SetNumReady(1)
    system.AddChildSubsystem(tube)
    return tube


def _capture(tube):
    seen = []
    globals()["_on_fired"] = lambda _obj, evt: seen.append(evt)
    App.g_kEventManager.AddBroadcastPythonFuncHandler(
        App.ET_TORPEDO_FIRED, tube, __name__ + "._on_fired")
    return seen


def test_unload_posts_torpedo_fired_with_tube_destination_and_no_source(clock):
    tube = _loaded_tube()
    seen = _capture(tube)
    clock(10.0)

    tube.UnloadTorpedo()

    assert tube.GetNumReady() == 0
    assert len(seen) == 1
    assert seen[0].GetEventType() == App.ET_TORPEDO_FIRED
    assert seen[0].GetDestination() is tube
    assert seen[0].GetSource() is None


def test_unloading_an_empty_tube_posts_nothing(clock):
    tube = _loaded_tube()
    tube.SetNumReady(0)
    seen = _capture(tube)

    tube.UnloadTorpedo()

    assert seen == []        # BC's post sits inside `if (numReady != 0)`
