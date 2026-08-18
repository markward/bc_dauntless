# tests/host/test_cutscene_camera_selection.py
import App
from engine.host_loop import _active_cutscene_camera
from engine.appc.bridge_set import BridgeSet_Create, CameraObjectClass_Create
from engine.appc.math import TGPoint3


def _space_set_with_cutscene_cam(name, target):
    s = App.SetClass_Create()
    App.g_kSetManager.AddSet(s, name)
    cam = CameraObjectClass_Create(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, "CutsceneCam")
    s.AddCameraToSet(cam, "CutsceneCam")
    s.SetActiveCamera("CutsceneCam")
    mode = cam.GetNamedCameraMode("Chase")
    mode.SetAttrIDObject("Target", target)
    cam.PushCameraMode(mode)
    App.g_kSetManager.MakeRenderedSet(name)
    return s, cam, mode


def test_active_cutscene_camera_found_when_rendered_set_has_live_mode():
    ship = App.ShipClass_Create("Galaxy")
    ship.SetTranslate(TGPoint3(10.0, 0.0, 0.0))
    s, cam, mode = _space_set_with_cutscene_cam("cc_sel_set", ship)
    got = _active_cutscene_camera()
    assert got is not None
    assert got[0] is cam and got[1] is mode
    App.g_kSetManager.DeleteSet("cc_sel_set")


def test_none_when_no_mode_pushed():
    s = App.SetClass_Create()
    App.g_kSetManager.AddSet(s, "cc_none_set")
    cam = CameraObjectClass_Create(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, "CutsceneCam")
    s.AddCameraToSet(cam, "CutsceneCam")
    s.SetActiveCamera("CutsceneCam")
    App.g_kSetManager.MakeRenderedSet("cc_none_set")
    assert _active_cutscene_camera() is None
    App.g_kSetManager.DeleteSet("cc_none_set")


def test_none_when_rendered_set_unset():
    App.g_kSetManager.MakeRenderedSet("__nonexistent__")
    assert _active_cutscene_camera() is None


def test_none_when_mode_target_dead():
    s = App.SetClass_Create()
    App.g_kSetManager.AddSet(s, "cc_dead_set")
    cam = CameraObjectClass_Create(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, "CutsceneCam")
    s.AddCameraToSet(cam, "CutsceneCam")
    s.SetActiveCamera("CutsceneCam")
    mode = cam.GetNamedCameraMode("Chase")            # no Target set => invalid
    cam.PushCameraMode(mode)
    App.g_kSetManager.MakeRenderedSet("cc_dead_set")
    assert _active_cutscene_camera() is None
    App.g_kSetManager.DeleteSet("cc_dead_set")


# ── BC cinematic mode (F9): the player camera's resolved mode wins ──────────
# While the cinematic window holds focus, the exterior view is driven by the
# player camera's hierarchy-RESOLVED mode (Task 1's GetCurrentCameraMode());
# the mission cutscene camera and the director only get the frame back when
# the resolution dead-ends invalid (default InvalidCinematic->DropAndWatch
# edge, no DropAndWatch mode class) or cinematic mode is off.

def _current_game():
    """Install a current Game if the harness has none. The conftest autouse
    _reset_leakable_engine_globals clears it again after each test."""
    game = App.Game_GetCurrentGame()
    if game is None:
        from engine.core.game import Game, _set_current_game
        game = Game()
        _set_current_game(game)
    return game


def _enter_cinematic_with_player():
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    game = _current_game()
    ship = App.ShipClass_Create("CineSelPlayer")
    game.SetPlayer(ship)
    tw.ToggleCinematicWindow()
    return tw, game, game.GetPlayerCamera()


def test_cinematic_mode_drives_the_player_camera_resolved_mode():
    tw, game, cam = _enter_cinematic_with_player()
    cam.AddModeHierarchy("InvalidCinematic", "Chase")   # what F2 does
    got = _active_cutscene_camera()
    tw.ToggleCinematicWindow()                          # leave before asserts
    assert got is not None
    got_cam, got_mode = got
    assert got_cam is cam
    assert getattr(got_mode, "_named", None) == "Chase"
    assert got_mode.IsValid()


def test_mission_cutscene_camera_beats_cinematic_mode():
    """BC precedence: the rendered set's live cutscene camera outranks the
    F9 cinematic window. Evidence: AI/Compound/DockWithStarbase.py
    SetupCutscene (lines 26-42) enters cinematic mode AND installs an
    authored "DockingCam" (CutsceneCameraBegin + Camera.Placement +
    MakeRenderedSet) — in BC the set's active camera renders the docking
    sweep even though the cinematic window holds focus and the player
    camera's resolved mode is valid. If cinematic focus outranked the set
    camera, that authored sweep would be dead code. The player camera
    takes over only once the set camera is gone (e.g. after DeleteSet)."""
    ship = App.ShipClass_Create("CineSelRival")
    ship.SetTranslate(TGPoint3(10.0, 0.0, 0.0))
    s, set_cam, set_mode = _space_set_with_cutscene_cam("cc_cine_set", ship)
    tw, game, pcam = _enter_cinematic_with_player()
    pcam.AddModeHierarchy("InvalidCinematic", "Chase")
    got = _active_cutscene_camera()
    App.g_kSetManager.DeleteSet("cc_cine_set")
    after = _active_cutscene_camera()
    tw.ToggleCinematicWindow()
    assert got is not None and got[0] is set_cam        # set camera wins under F9
    assert after is not None and after[0] is pcam       # cinematic takes over once gone


def test_cinematic_mode_with_unresolvable_mode_falls_through():
    """Default edge dead-ends invalid (no DropAndWatch class): the existing
    logic keeps the frame — None here, absent a mission cutscene camera."""
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    App.g_kSetManager.MakeRenderedSet("__nonexistent__")
    game = _current_game()
    game.GetPlayerCamera()
    tw.ToggleCinematicWindow()
    got = _active_cutscene_camera()
    tw.ToggleCinematicWindow()
    assert got is None
