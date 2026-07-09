"""EndCutscene / AbortCutscene must release the camera-watch target.

BC's AT_LOOK_AT_ME / AT_WATCH_ME framing is scoped to a cutscene
(StartCutscene..EndCutscene). The QB intro (QuickBattle.QBExposition) does
AT_LOOK_AT_ME(XO) inside a cutscene with NO AT_STOP_WATCHING_ME — the camera is
meant to revert when the cutscene ends. If EndCutscene doesn't clear the watch
target, the persistent target outranks the menu zoom-to-officer and locks the
camera on Saffi forever. See project_orientation_family.
"""
import engine.bridge_camera_watch as bcw
from engine.appc.top_window import TopWindow_GetTopWindow


def _with_watch_target():
    ctrl = bcw.BridgeCameraWatchController()
    bcw.set_controller(ctrl)
    ctrl.watch(object())
    assert ctrl.is_watching() is True
    return ctrl


def test_end_cutscene_clears_watch_target():
    ctrl = _with_watch_target()
    try:
        tw = TopWindow_GetTopWindow()
        tw.StartCutscene(1.0, 0.125, 1)
        tw.EndCutscene(1.0)
        assert ctrl.is_watching() is False
    finally:
        bcw.clear_controller()


def test_abort_cutscene_clears_watch_target():
    ctrl = _with_watch_target()
    try:
        tw = TopWindow_GetTopWindow()
        tw.StartCutscene(1.0, 0.125, 1)
        tw.AbortCutscene()
        assert ctrl.is_watching() is False
    finally:
        bcw.clear_controller()


def test_end_cutscene_no_controller_is_safe():
    bcw.clear_controller()          # no controller registered
    tw = TopWindow_GetTopWindow()
    tw.EndCutscene()                # must not raise
