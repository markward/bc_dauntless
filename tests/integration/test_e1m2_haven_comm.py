"""End-to-end: hailing the E1M2 Haven colony plays Director Soams's viewscreen
comm sequence.

Regression for the master-sequence jam: MissionLib.QueueActionToPlay stores the
running master TGSequence's id and appends every subsequently-queued action onto
it until that id goes invalid. Our engine used to keep completed sequences
registered forever, so once E1M2's first briefing master completed, every later
QueueActionToPlay (including the Soams hail) was appended onto a dead master and
never fired — the hail handler advanced mission state but Soams never appeared or
spoke. TGSequence now invalidates its object id on completion, so the hail opens
a fresh, playing master.

This drives the REAL E1M2 mission end-to-end via host_loop._init_mission and the
real SDK MissionLib. Skips cleanly if the BC game data isn't installed.
"""
import pytest

import App


def _pump(seconds=6.0, step=0.1):
    """Advance both timer managers so delayed sequence steps (ViewscreenOn is
    queued behind a delay) and audio-duration deferrals fire, mimicking the
    run loop."""
    n = int(round(seconds / step))
    for _ in range(n):
        App.g_kTimerManager.tick(step)
        App.g_kRealtimeTimerManager.tick(step)


def test_haven_hail_plays_soams_comm_sequence(monkeypatch):
    from tests.integration.test_sdk_bridge_load import _fresh_world
    from engine import host_loop
    from engine.appc.ships import ShipClass_Create

    _fresh_world()
    try:
        mission, episode, game, mod = host_loop._init_mission(
            "Maelstrom.Episode1.E1M2.E1M2")
    except Exception:
        pytest.skip("E1M2 could not be loaded headless (BC game data absent)")

    try:
        import MissionLib

        # A live, non-dying player so QueueActionToPlay does not skip.
        player = ShipClass_Create("Galaxy")
        player.SetName("player")
        game.SetPlayer(player)

        miscEng = App.g_kSetManager.GetSet("MiscEng")
        soams = (App.CharacterClass_GetObject(miscEng, "Soams")
                 if miscEng is not None else None)
        if miscEng is None or soams is None:
            pytest.skip("E1M2 MiscEng/Soams not present headless")

        # Record what actually plays.
        viewon = []
        _orig_von = MissionLib.ViewscreenOn
        monkeypatch.setattr(
            MissionLib, "ViewscreenOn",
            lambda pA, s, n=None, *a: (viewon.append((s, n)),
                                       _orig_von(pA, s, n, *a))[1])
        spoke = []
        import engine.appc.crew_speech as crew_speech
        # Force lines to complete inline (no audio backend / pumped duration)
        # so the sequence drains deterministically.
        monkeypatch.setattr(
            crew_speech, "emit",
            lambda name, db, line, prio, *a, **k: (spoke.append((name, line)),
                                                   0.0)[1])

        # Soams starts hidden; ViewscreenOn un-hides just him.
        assert soams.IsHidden() == 1

        # Fire the first Haven hail (same QueueActionToPlay path as the second).
        mod.g_bHavenFirstHail = 0
        mod.FirstHavenHail()
        _pump()

        # The comm sequence played: the viewscreen was pointed at Soams in the
        # MiscEng comm set, Soams was un-hidden, and his hail lines were spoken.
        assert ("MiscEng", "Soams") in viewon
        assert soams.IsHidden() == 0
        soams_lines = [line for name, line in spoke if name == "Soams"]
        assert soams_lines, "Soams never spoke — comm sequence did not play"
        assert "E1M2HailHaven1" in soams_lines
    finally:
        App.g_kSetManager._sets.clear()
        from engine.core.game import _set_current_game
        _set_current_game(None)
