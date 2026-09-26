"""Every campaign mission loads, Warp is pressed headlessly with a plotted
course and with none, and nothing raises (spec: Testing, Sweep).

A handler on the Warp button's instance chain raising escapes the event
dispatch (events.py dispatches destinations unguarded), so each mission's
WarpHandler -- and the engine step below it -- is exercised for crashes.
This catches crashes, not wrong behaviour (spec: Risks)."""
import pytest

from tools import mission_harness
from tests.helpers import headless_mission as hm
from engine.appc import warp_button

MISSIONS = [m for m in mission_harness.discover_missions()
            if m.startswith("Maelstrom.")]


def test_the_sweep_covers_the_campaign():
    assert len(MISSIONS) >= 26


@pytest.mark.parametrize("name", MISSIONS)
def test_pressing_warp_never_raises(name):
    hm.load(name)
    btn = hm.the_warp_button()
    assert btn is not None
    # With a course: the mission's own, else the first the menu offers.
    course = btn.GetDestination() or hm.first_offered_course()
    if course:
        hm.plot_course(btn, course)
    warp_button.press(btn)
    hm.tick(5.0)
    # With none.
    btn.set_player_destination(None)
    warp_button.press(btn)
    hm.tick(5.0)
