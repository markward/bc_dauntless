"""E1M2 second Haven hail: after clearing the debris the player hails Haven,
which must play the Soams "asteroids incoming" comm and advance the mission.

Regression: the second-hail comm is queued via MissionLib.QueueActionToPlay,
which APPENDS onto the already-playing master sequence (DebrisCleared() queued a
dialogue master moments earlier). Appended steps were never subscribed for
completion, so the queued comm was silently dropped — the player heard Kiska's
"hailing frequencies open" and then nothing. See TGSequence mid-flight append
(tests/unit/test_sequence_midflight_append.py).
"""
import App
from engine import host_loop
from engine.appc import ship_death
from tests.integration.test_sdk_bridge_load import _fresh_world


E1M2_MODULE = "Maelstrom.Episode1.E1M2.E1M2"


def _init_e1m2():
    _fresh_world()
    mission, episode, game, mod = host_loop._init_mission(E1M2_MODULE)
    return mod


def _pump(seconds=100.0, dt=0.25):
    # Both clocks: comm say-line / viewscreen completions defer on wall-clock
    # (g_kRealtimeTimerManager); sequence step delays use game time.
    for _ in range(int(seconds / dt)):
        App.g_kTimerManager.tick(dt)
        App.g_kRealtimeTimerManager.tick(dt)


def test_clearing_debris_then_hailing_haven_advances_mission():
    mod = _init_e1m2()
    pSet = App.g_kSetManager.GetSet("Vesuvi6")

    # Clear the debris the real way (ship death -> ET_OBJECT_EXPLODING ->
    # E1M2.ObjectDestroyed), which sets g_bDebrisCleared and queues the
    # DebrisCleared() dialogue master.
    mod.CreateDebris()
    for nm in list(mod.g_lDebrisNames):
        s = App.ShipClass_GetObject(pSet, nm)
        if s is not None:
            ship_death.begin(s)
    assert mod.g_bDebrisCleared == 1

    # Hail Haven through the real handler branch (source == Haven planet).
    haven = pSet.GetObject("Haven")
    assert haven is not None
    evt = App.TGObjPtrEvent_Create()
    evt.SetEventType(App.ET_HAIL)
    evt.SetSource(haven)
    mod.HailHandler(None, evt)     # debris cleared -> SecondHavenHail branch

    # The comm flips the second-hail flag immediately...
    assert mod.g_bHavenSecondHail == 1
    assert mod.g_bSequenceRunning == 1   # sequence in progress

    _pump()

    # ...and the whole queued comm runs to completion: the tail actions fire
    # (previously the appended master jammed, leaving these stuck).
    assert mod.g_bSequenceRunning == 0        # SetSequenceRunning tail ran
    assert mod.g_bHavenHailDone == 1          # SetHavenHailDone tail ran
    assert len(mod.g_dAsteroidInfo) == 5      # CreateMovingAsteroids ran
