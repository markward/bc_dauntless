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


def test_second_haven_hail_turns_the_camera_off_kiska_to_the_viewscreen(
        monkeypatch):
    """SecondHavenHail is StartCutscene -> AT_LOOK_AT_ME(Kiska) ->
    ViewscreenOn(MiscEng, Soams). In a cutscene ViewscreenOn calls the bridge
    zoom camera's LookForward(), which supersedes the resting look-at on Kiska.
    While Soams is on screen the camera must no longer be framing Kiska —
    otherwise the per-frame engagement pick keeps the view on her (a resting
    look-at outranks the viewscreen hail)."""
    from tests.integration.test_sdk_bridge_load import _fresh_world
    from engine import host_loop
    from engine import bridge_camera_watch as bcw
    from engine.appc.ships import ShipClass_Create

    _fresh_world()
    try:
        mission, episode, game, mod = host_loop._init_mission(
            "Maelstrom.Episode1.E1M2.E1M2")
    except Exception:
        pytest.skip("E1M2 could not be loaded headless (BC game data absent)")

    ctrl = bcw.BridgeCameraWatchController()
    bcw.set_controller(ctrl)
    try:
        import MissionLib

        player = ShipClass_Create("Galaxy")
        player.SetName("player")
        game.SetPlayer(player)

        miscEng = App.g_kSetManager.GetSet("MiscEng")
        if miscEng is None or App.CharacterClass_GetObject(miscEng, "Soams") is None:
            pytest.skip("E1M2 MiscEng/Soams not present headless")

        # Sample the camera-watch target either side of every ViewscreenOn.
        # Mission load already played FirstHavenHail (no look-at), so pick out
        # the call that runs while Kiska is being framed.
        watched_at_viewon = []
        _orig_von = MissionLib.ViewscreenOn

        def _von(pA, s, n=None, *a):
            before = ctrl.watched_character()
            r = _orig_von(pA, s, n, *a)
            watched_at_viewon.append((before, ctrl.watched_character()))
            return r
        monkeypatch.setattr(MissionLib, "ViewscreenOn", _von)
        import engine.appc.crew_speech as crew_speech
        monkeypatch.setattr(
            crew_speech, "emit", lambda *a, **k: 0.0)

        # The state SecondHavenHail requires: first hail done, none running.
        mod.g_bHavenFirstHail = 1
        mod.g_bHavenSecondHail = 0
        mod.g_bSequenceRunning = 0
        mod.SecondHavenHail(None)
        # SecondHavenHail waits (2 s loops) for the load-time FirstHavenHail
        # sequence to finish before it plays, so pump past both.
        _pump(10.0)

        kiska = mod.g_pKiska
        on_kiska = [after for before, after in watched_at_viewon
                    if before is kiska]
        assert on_kiska, ("SecondHavenHail never turned the viewscreen on "
                          "while the camera was framing Kiska")
        assert on_kiska[0] is not kiska, (
            "camera still framing Kiska while Soams is on the viewscreen")
    finally:
        bcw.clear_controller()
        App.g_kSetManager._sets.clear()
        from engine.core.game import _set_current_game
        _set_current_game(None)
