# tests/host/test_cutscene_camera_override.py
"""End-to-end: an in-space cutscene camera on the explicitly-rendered set
overrides the bridge render pass and drives the main-scene camera, without ever
mutating the bridge flag. Models the E1M1 drydock undock shot."""
import App
import Camera
from engine.appc.math import TGPoint3
from engine.appc.bridge_set import CameraObjectClass_Create
from engine.appc.top_window import bridge_flag
from engine.host_loop import (
    _active_cutscene_camera, _cutscene_pose, _apply_bridge_pass_state,
)


class _FakeBindings:
    def __init__(self):
        self.bridge_pass_calls = []

    def bridge_pass_set_enabled(self, enabled):
        self.bridge_pass_calls.append(enabled)


class _Latch:
    pass


def _drydock_scene():
    """DryDock space set: player ship at origin, "Cam Pos 1" placement 50 GU to
    port, and a CutsceneCam that is the set's active camera (CutsceneCameraBegin)."""
    s = App.SetClass_Create()
    App.g_kSetManager.AddSet(s, "DryDock")
    ship = App.ShipClass_Create("Galaxy")
    ship.SetTranslate(TGPoint3(0.0, 0.0, 0.0))
    s.AddObjectToSet(ship, "player")
    wp = App.Waypoint_Create("Cam Pos 1", "DryDock", None)
    wp.SetTranslate(TGPoint3(-50.0, 0.0, 0.0))
    cam = CameraObjectClass_Create(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, "CutsceneCam")
    s.AddCameraToSet(cam, "CutsceneCam")
    s.SetActiveCamera("CutsceneCam")
    App.g_kSetManager.MakeRenderedSet("DryDock")
    return s, cam, ship, wp


def test_placement_watch_produces_live_cutscene_camera_and_pose():
    before = bridge_flag()
    s, cam, ship, wp = _drydock_scene()
    # PlacementWatch("DryDock", "player", "Cam Pos 1") routes here (bSweep=0).
    Camera.Placement("Cam Pos 1", "player", "DryDock", 0, 1)
    cc = _active_cutscene_camera()
    assert cc is not None
    assert cc[0] is cam
    eye, look_at, up = _cutscene_pose(cc[1], 0.0)
    assert abs(eye[0] - (-50.0)) < 1e-6             # eye sits at the placement
    assert look_at[0] > eye[0]                      # looks +X toward the ship
    assert bridge_flag() == before                  # flag NEVER mutated
    App.g_kSetManager.DeleteSet("DryDock")


def test_bridge_pass_off_while_cutscene_active_then_on_after_end():
    s, cam, ship, wp = _drydock_scene()
    Camera.Placement("Cam Pos 1", "player", "DryDock", 0, 1)
    h = _FakeBindings()
    latch = _Latch()

    # During the shot: player is on the bridge in state (is_bridge=True) but a
    # cutscene camera owns the frame → effective_bridge False → pass OFF.
    cc = _active_cutscene_camera()
    _apply_bridge_pass_state(True and cc is None, h, latch)
    assert h.bridge_pass_calls == [False]

    # CutsceneCameraEnd: delete the cutscene camera → no live mode → pass ON.
    s.DeleteCameraFromSet("CutsceneCam")
    cc_after = _active_cutscene_camera()
    assert cc_after is None
    _apply_bridge_pass_state(True and cc_after is None, h, latch)
    assert h.bridge_pass_calls == [False, True]
    App.g_kSetManager.DeleteSet("DryDock")


def test_player_ship_visible_while_cutscene_camera_active_in_bridge_state():
    """The subject of an in-space cutscene must render even though the player is
    on the bridge in state. Player-ship visibility uses the SAME effective-bridge
    predicate as the bridge pass (`is_bridge and _cc is None`); without it the
    hide-on-bridge leaves the cutscene exterior empty (ship invisible)."""
    from engine.host_loop import _apply_bridge_player_visibility
    s, cam, ship, wp = _drydock_scene()
    Camera.Placement("Cam Pos 1", "player", "DryDock", 0, 1)
    cc = _active_cutscene_camera()
    assert cc is not None

    class _R:
        def __init__(self):
            self.calls = []

        def set_visible(self, iid, vis):
            self.calls.append((iid, vis))

    # On the bridge in state (is_bridge True) BUT a cutscene camera owns the
    # frame → effective is_bridge False → ship visible.
    r = _R()
    _apply_bridge_player_visibility(r, 7, is_bridge=(True and cc is None),
                                    spv_open=False)
    assert r.calls == [(7, True)]

    # No cutscene camera → the normal hide-on-bridge still applies.
    r2 = _R()
    _apply_bridge_player_visibility(r2, 7, is_bridge=(True and None is None),
                                    spv_open=False)
    assert r2.calls == [(7, False)]
    App.g_kSetManager.DeleteSet("DryDock")


def test_cutscene_pose_returns_lookat_point_not_direction():
    """Regression for the merged 365207f7 seam: mode.Update returns a forward
    DIRECTION; _cutscene_pose must return a look-at POINT (eye+fwd), else a
    far-from-origin chase looks at ~origin."""
    from engine.appc.camera_modes import ChaseMode
    ship = App.ShipClass_Create("Galaxy")
    ship.SetTranslate(TGPoint3(1000.0, 0.0, 0.0))
    m = ChaseMode()
    m.SetAttrIDObject("Target", ship)
    eye, look_at, up = _cutscene_pose(m, None)
    assert look_at[0] > 900.0                        # look-at is at the ship, not ~origin
