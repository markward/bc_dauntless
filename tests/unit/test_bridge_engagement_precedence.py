"""An open crew menu must outrank a lingering AT_LOOK_AT_ME.

E1M1's crew intros are the case. IntroduceSaffi and IntroduceSaffiAgain each end
with AT_LOOK_AT_ME(Picard) (E1M1.py:2030, 2356) and the SDK never pairs
AT_LOOK_AT_ME with an AT_STOP_WATCHING_ME anywhere. The only release we have runs
on EndCutscene — and StartCutscene is at E1M1.py:1845 while its EndCutscene sits
at :2622 inside IntroduceKiska, so the whole crew-intro block is one cutscene.
With a flat "watch beats menu" rule the stale Picard target therefore outranked
Brex's and Miguel's AT_MENU_UP and the camera held Picard's face through every
introduction — it never framed the aft stations at all.

BC's own scripts draw the line: AT_WATCH_ME is always paired with
AT_STOP_WATCHING_ME, and IntroduceSaffiAgain deliberately sequences that release
BEFORE raising Saffi's menu (pStopSaffiWatch/pSaffiMenuUp, E1M1.py:2344-2345).
AT_LOOK_AT_ME is never released, because it is the resting aim something later is
expected to supersede. So AT_WATCH_ME holds above the menu; AT_LOOK_AT_ME sits
below it and still wins when no menu is open.
"""
import pytest

from engine.bridge_camera_watch import BridgeCameraWatchController
from engine.host_loop import _pick_bridge_engagement

_PICARD = (10.0, 90.0, 60.0)
_BREX = (40.0, 150.0, 45.0)
_ZOOM = 0.64


class _Char:
    def __init__(self, name, iid=1):
        self.name = name
        self._render_instance = iid


def _pick(watch_world=None, watch_holds=False, watch_char=None,
          menu_world=None, menu_char=None, hail=None):
    return _pick_bridge_engagement(
        watch_world=watch_world, watch_holds=watch_holds, watch_char=watch_char,
        menu_world=menu_world, menu_char=menu_char, menu_zoom=_ZOOM, hail=hail)


def test_at_watch_me_holds_above_an_open_crew_menu():
    """A live AT_WATCH_ME is an active follow — BC releases it before raising a
    menu, so if both are somehow live the follow still wins."""
    picard, brex = _Char("picard"), _Char("brex")
    engaged, look_at, _zoom, char = _pick(
        watch_world=_PICARD, watch_holds=True, watch_char=picard,
        menu_world=_BREX, menu_char=brex)
    assert (engaged, look_at, char) == (True, _PICARD, picard)


def test_at_look_at_me_yields_to_an_open_crew_menu():
    """The E1M1 regression: Picard's lingering look-at must NOT block the camera
    from framing the station whose menu just came up."""
    picard, brex = _Char("picard"), _Char("brex")
    engaged, look_at, zoom, char = _pick(
        watch_world=_PICARD, watch_holds=False, watch_char=picard,
        menu_world=_BREX, menu_char=brex)
    assert (engaged, look_at, char) == (True, _BREX, brex)
    assert zoom == _ZOOM


def test_at_look_at_me_wins_when_no_menu_is_open():
    """Between menus the look-at is still the resting aim — IntroduceSaffi holds
    on Saffi, then on Picard, with no menu involved at all."""
    picard = _Char("picard")
    engaged, look_at, _zoom, char = _pick(
        watch_world=_PICARD, watch_holds=False, watch_char=picard)
    assert (engaged, look_at, char) == (True, _PICARD, picard)


def test_hail_is_last_resort():
    kiska = _Char("kiska")
    engaged, look_at, zoom, char = _pick(hail=(kiska, 0.5))
    assert (engaged, look_at, char) == (True, None, kiska)   # None = viewscreen-forward
    assert zoom == 0.5


def test_nothing_engaged_is_the_captain_view():
    engaged, look_at, _zoom, char = _pick()
    assert (engaged, look_at, char) == (False, None, None)


# ── the verb -> hold mapping ────────────────────────────────────────────────
def test_watch_me_records_a_holding_target():
    ctrl = BridgeCameraWatchController()
    ctrl.watch(_Char("picard"), hold=True)
    assert ctrl.is_holding() is True


def test_look_at_me_records_a_non_holding_target():
    ctrl = BridgeCameraWatchController()
    ctrl.watch(_Char("picard"), hold=False)
    assert ctrl.is_holding() is False


def test_clear_drops_the_hold():
    ctrl = BridgeCameraWatchController()
    ctrl.watch(_Char("picard"), hold=True)
    ctrl.clear()
    assert ctrl.is_holding() is False


@pytest.mark.parametrize("verb_attr,expect_hold", [
    ("AT_WATCH_ME", True),
    ("AT_LOOK_AT_ME", False),
    ("AT_LOOK_AT_ME_NOW", False),
])
def test_character_action_verbs_map_to_the_right_hold(verb_attr, expect_hold, monkeypatch):
    """AT_WATCH_ME holds; both AT_LOOK_AT_ME forms are a resting aim."""
    import engine.bridge_camera_watch as bcw
    from engine.appc.ai import CharacterAction

    ctrl = BridgeCameraWatchController()
    bcw.set_controller(ctrl)
    try:
        ch = _Char("picard")
        monkeypatch.setattr("engine.appc.characters.CharacterClass_Cast",
                            lambda o: o)
        act = CharacterAction.__new__(CharacterAction)
        act._character = ch
        act._set_camera_watch(snap=False,
                              hold=(verb_attr == "AT_WATCH_ME"))
        assert ctrl.is_holding() is expect_hold
    finally:
        bcw.clear_controller()
