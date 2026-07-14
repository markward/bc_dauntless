"""Reset re-arms the node and reaches the script; UpdateStatus values match Appc.

Values read out of the binary's swig_const_info table (0x0090d9ac+) on
2026-07-14: US_ACTIVE=0, US_DONE=1, US_DORMANT=2, US_INVALID=3. These are the
values this engine has always had. ai-architecture.md sec.2 lists DORMANT/DONE
swapped — that is a doc transcription error. This test exists to stop anyone
"correcting" our (right) values to match the (wrong) doc.

Appc's Reset zeroes nextUpdateTime, forcing an update on the next tick. Four
PlainAI scripts define a script-side Reset() and
AI/Compound/TractorDockTargets.py:20 calls it.
"""
from engine.appc.ai import ArtificialIntelligence, PlainAI_Create


def test_update_status_values_match_the_binary():
    # DO NOT "fix" these against ai-architecture.md sec.2 — the doc is wrong.
    assert ArtificialIntelligence.US_ACTIVE == 0
    assert ArtificialIntelligence.US_DONE == 1
    assert ArtificialIntelligence.US_DORMANT == 2
    assert ArtificialIntelligence.US_INVALID == 3
    assert ArtificialIntelligence.US_NUM_STATUSES == 4


def test_reset_zeroes_the_cadence_and_reaches_the_script():
    class _Script:
        def __init__(self):
            self.resets = 0

        def Reset(self):
            self.resets += 1

    ai = PlainAI_Create(None, "leaf")
    script = _Script()
    ai._script_instance = script

    ai._status = ArtificialIntelligence.US_DONE
    ai._next_update_time = 99.0

    ai.Reset()

    assert ai._status == ArtificialIntelligence.US_ACTIVE
    assert ai._next_update_time == 0.0, "must run on the very next tick"
    assert script.resets == 1


def test_reset_on_a_node_with_no_script_does_not_raise():
    ai = PlainAI_Create(None, "bare")
    ai.Reset()
    assert ai._next_update_time == 0.0


def test_reset_reaches_the_real_followwaypoints_script_and_rewinds_the_cursor():
    """End-to-end payoff: the real SDK FollowWaypoints.Reset() rewinds its
    waypoint cursor when reached through ArtificialIntelligence.Reset()."""
    from engine.appc.ships import ShipClass

    ship = ShipClass()
    pai = PlainAI_Create(ship, "TestFollowWaypoints")
    pai.SetScriptModule("FollowWaypoints")
    script = pai.GetScriptInstance()

    # Set up the original target, then simulate progress partway through the
    # waypoint list the way FollowWaypoints.Update() itself advances it
    # (AI/PlainAI/FollowWaypoints.py:162).
    script.SetTargetWaypointName("WP1")
    assert script.sOriginalWaypoint == "WP1"
    script.pcTargetWaypoint = "WP4"  # cursor has advanced to a later waypoint
    script.fUpdateTime = 0.05        # and the cadence has sped up

    pai.Reset()

    assert script.pcTargetWaypoint == "WP1", "Reset must rewind the cursor to the original waypoint"
    assert script.fUpdateTime == 0.25, "Reset must restore the script's own cadence default"
    assert pai._next_update_time == 0.0, "Reset must also re-arm the node's own cadence"
