"""Every campaign mission loads, Warp is pressed headlessly with a plotted
course and with none, and nothing raises (spec: Testing, Sweep).

A handler on the Warp button's instance chain raising escapes the event
dispatch (events.py dispatches destinations unguarded). Broadcast handlers and
warp-sequence actions are logged and swallowed instead, so every case also
reads the captured output (no_logged_failures): a swallowed traceback fails
it too. This catches crashes, not wrong behaviour (spec: Risks)."""
import pytest

import App
from tools import mission_harness
from engine.appc import events, warp_button
from tests.helpers import headless_mission as hm
from tests.helpers.headless_mission import no_logged_failures  # noqa: F401 (fixture)

MISSIONS = [m for m in mission_harness.discover_missions()
            if m.startswith("Maelstrom.")]


def test_the_sweep_covers_the_campaign():
    assert len(MISSIONS) >= 26


@pytest.mark.parametrize("name", MISSIONS)
def test_pressing_warp_never_raises(name, monkeypatch, no_logged_failures):
    hm.load(name)
    btn = hm.the_warp_button()
    assert btn is not None
    player = App.Game_GetCurrentPlayer()
    # With a course: the mission's own, else the first other region the
    # menu offers.
    here = player.GetContainingSet() if player is not None else None
    course = btn.GetDestination() or hm.first_offered_course(
        here.GetName() if here is not None else None)
    if course:
        hm.plot_course(btn, course)
    warp_button.press(btn)
    hm.tick(5.0)
    # Let that warp finish, so the next press is not ignored as a second warp.
    if player is not None and warp_button.is_warp_active(player):
        hm.tick_until(lambda: not warp_button.is_warp_active(player),
                      bound_s=hm.MASTER_DIALOGUE_BOUND_S)
    # With none.
    player = App.Game_GetCurrentPlayer()
    btn.set_player_destination(None)
    ran = []
    real_resolve = events._resolve_handler

    def _recording(qualified):
        ran.append(qualified)
        return real_resolve(qualified)
    monkeypatch.setattr(events, "_resolve_handler", _recording)
    warp_button.press(btn)
    monkeypatch.setattr(events, "_resolve_handler", real_resolve)
    # The chain ran newest-first and stopped either at the engine step, which
    # starts nothing without a course, or at a mission handler that consumed
    # the press (8 missions refuse a course-less Warp with their own line,
    # e.g. E1M2's WarpButtonHandler).
    chain = list(reversed(btn._handlers.get(App.ET_WARP_BUTTON_PRESSED, [])))
    assert ran and ran == chain[:len(ran)], (ran, chain)
    if ran[-1] == warp_button.ENGINE_STEP:
        assert player is None or not warp_button.is_warp_active(player)
    else:
        assert ran[-1].startswith("Maelstrom."), ran
    hm.tick(5.0)
