"""ZoomCameraObjectClass.LookForward must supersede a resting AT_LOOK_AT_ME aim.

BC's MissionLib.ViewscreenOn calls pZoomCamera.LookForward() whenever a cutscene
is running (MissionLib.py:1260-1262), and MissionLib.LookForward does the same
as a script action ("Sweep takes 1 second", MissionLib.py:2124-2150). Scenes
pair it with an earlier AT_LOOK_AT_ME and never release that look-at:
E1M2 SecondHavenHail does StartCutscene -> AT_LOOK_AT_ME(Kiska) ->
ViewscreenOn(MiscEng, Soams); E7M2 does AT_LOOK_AT_ME(Saffi) -> ViewscreenOn ->
LookForward. LookForward IS the next beat that supersedes the resting aim.

Our bridge camera re-picks its engagement every frame and ranks a resting
look-at above the viewscreen hail (host_loop._pick_bridge_engagement), so unless
LookForward drops it, the camera stays on Kiska for the whole comm.

AT_WATCH_ME (hold=True) is an active follow BC always releases explicitly with
AT_STOP_WATCHING_ME; LookForward leaves it alone.
"""
import engine.bridge_camera_watch as bcw
from engine.appc.bridge_set import ZoomCameraObjectClass


def _cam():
    return ZoomCameraObjectClass(0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, "maincamera")


def test_look_forward_releases_a_resting_look_at_me_target():
    ctrl = bcw.BridgeCameraWatchController()
    bcw.set_controller(ctrl)
    try:
        ctrl.watch(object(), hold=False)      # AT_LOOK_AT_ME(Kiska)
        _cam().LookForward()
        assert ctrl.is_watching() is False
    finally:
        bcw.clear_controller()


def test_look_forward_keeps_a_held_watch_me_target():
    ctrl = bcw.BridgeCameraWatchController()
    bcw.set_controller(ctrl)
    try:
        who = object()
        ctrl.watch(who, hold=True)            # AT_WATCH_ME
        _cam().LookForward()
        assert ctrl.watched_character() is who
        assert ctrl.is_holding() is True
    finally:
        bcw.clear_controller()


def test_look_forward_without_a_controller_is_safe():
    bcw.clear_controller()
    _cam().LookForward()                      # must not raise
