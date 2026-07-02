"""QueueActionToPlay appends onto an already-PLAYING master TGSequence
(MissionLib.QueueActionToPlay: `pPlayingSequence.AppendAction(pActionToAdd)`).

Regression: a step appended after Play() was never subscribed for completion
(only _launch subscribed members), so the master never learned the appended
action finished. The first append still ran (its dependency was a launch-time
member), but a SECOND append chained onto the first never started — the master
never got the first append's completion event to trigger it. In E1M2 this
silently dropped the second Haven-hail comm ("hailing frequencies open" then
nothing).
"""
import App
from engine.appc.actions import TGAction


class _Gate(TGAction):
    """Plays but does not auto-complete until finish() is called."""
    def __init__(self):
        super().__init__()
        self.played = False

    def Play(self):
        self._playing = True
        self.played = True   # deliberately no Completed()

    def finish(self):
        self.Completed()


class _Marker(TGAction):
    """Auto-completing action that records that it ran."""
    def __init__(self):
        super().__init__()
        self.played = False

    def _do_play(self):
        self.played = True


def test_single_midflight_append_completes_master():
    seq = App.TGSequence_Create()
    gate = _Gate()
    seq.AddAction(gate)
    seq.Play()
    assert gate.played and seq._playing

    marker = _Marker()
    seq.AppendAction(marker)     # appended onto the playing master
    assert not marker.played     # waits on the gate

    gate.finish()                # gate completes -> marker should run
    assert marker.played
    # Master completed and invalidated its id (so the next QueueActionToPlay
    # starts a fresh master instead of appending onto a dead one).
    assert App.TGObject_GetTGObjectPtr(seq.GetObjID()) is None


def test_chained_midflight_appends_all_run():
    """The load-bearing case: append B onto a playing master, then append C
    chained onto B. C must run when B completes."""
    seq = App.TGSequence_Create()
    gateA = _Gate()
    seq.AddAction(gateA)
    seq.Play()

    gateB = _Gate()
    markerC = _Marker()
    seq.AppendAction(gateB)      # dep = gateA (a launch-time member)
    seq.AppendAction(markerC)    # dep = gateB (itself appended mid-flight)

    gateA.finish()
    assert gateB.played          # first append ran
    assert not markerC.played    # waits on gateB

    gateB.finish()
    assert markerC.played        # second append ran (regressed: never did)
    assert App.TGObject_GetTGObjectPtr(seq.GetObjID()) is None


def test_append_after_dependency_completed_still_runs():
    """If the append happens after its dependency already completed (but the
    master is still playing on another branch), the new step must still fire."""
    seq = App.TGSequence_Create()
    gateA = _Gate()   # keeps the master alive
    gateB = _Gate()
    seq.AddAction(gateA)
    seq.AddAction(gateB)
    seq.Play()
    gateB.finish()               # gateB done, but master still playing (gateA)

    marker = _Marker()
    seq.AppendAction(marker, gateB)   # explicit dep on the already-done gateB
    assert marker.played              # begins immediately

    gateA.finish()
    assert App.TGObject_GetTGObjectPtr(seq.GetObjID()) is None
