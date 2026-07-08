"""Developer-only live probe for the in-space cutscene camera-direction system.

Fires a PlacementWatch cutscene on the CURRENT player ship from a vantage
waypoint, so the cutscene-camera render override can be verified on demand — in
QuickBattle or any loaded mission — WITHOUT having to reach a scripted mission
beat (e.g. the E1M1 drydock-undock button, which is gated behind the whole
mission intro).

Toggle it from the Developer pause menu. When active, the exterior view should
snap to a fixed 3/4 vantage watching your ship (the director's chase camera is
overridden); toggle again to revert. Press SPACE to the bridge while active and
the view should STAY on the exterior placement (bridge pass off) — that is the
"cutscene camera overrides the bridge render" behaviour.

Dev-only: this module is imported and its pause-menu row registered only under
`--developer`. It never runs in production. Diagnostics use print() (the host
has no logging handler — see memory feedback on dev observability).
"""
import App
import Camera
import MissionLib

from engine.appc.math import TGPoint3

_CAM_NAME = "DevCutsceneCam"
_WP_NAME = "DevCutsceneCamPos"
_active = [False]


def is_active():
    return _active[0]


def _vantage(player):
    """A fixed 3/4 exterior vantage in the player's own body frame: to
    starboard, slightly up and behind, scaled to the ship's radius so it frames
    any hull. Column-vector convention (GetCol(0)=right, (1)=forward, (2)=up)."""
    loc = player.GetWorldLocation()
    R = player.GetWorldRotation()
    right, fwd, up = R.GetCol(0), R.GetCol(1), R.GetCol(2)
    d = 6.0 * max(player.GetRadius(), 1.0)
    x = loc.x + right.x * d + up.x * 0.4 * d - fwd.x * 0.4 * d
    y = loc.y + right.y * d + up.y * 0.4 * d - fwd.y * 0.4 * d
    z = loc.z + right.z * d + up.z * 0.4 * d - fwd.z * 0.4 * d
    return (x, y, z)


def start():
    """Set up + push a PlacementWatch cutscene on the player. Idempotent-ish:
    re-running re-poses the vantage to the player's current location."""
    player = MissionLib.GetPlayer()
    if player is None:
        print("[cutscene-probe] no player ship — load QuickBattle or a mission first")
        return
    pSet = player.GetContainingSet()
    if pSet is None:
        print("[cutscene-probe] player has no containing set")
        return
    set_name = pSet.GetName()
    cx, cy, cz = _vantage(player)

    # Vantage waypoint = the placement's Source (eye). Waypoint_Create overwrites
    # the same-named marker on re-run and re-adds it to the set.
    wp = App.Waypoint_Create(_WP_NAME, set_name, None)
    wp.SetTranslate(TGPoint3(cx, cy, cz))

    # Make this set the explicit render target (get_explicit_rendered_set is the
    # render-target authority the override reads).
    App.g_kSetManager.MakeRenderedSet(set_name)

    # CutsceneCam becomes the set's active camera (CutsceneCameraBegin shape).
    cam = App.CameraObjectClass_GetObject(pSet, _CAM_NAME)
    if cam is None:
        cam = App.CameraObjectClass_Create(cx, cy, cz, 0.0, 0.0, 0.0, 1.0, _CAM_NAME)
        pSet.AddCameraToSet(cam, _CAM_NAME)
    else:
        cam.SetTranslate(TGPoint3(cx, cy, cz))
    pSet.SetActiveCamera(_CAM_NAME)

    # Push the Placement mode: eye at the vantage waypoint, looking at the player
    # (bSweep=0 → snap). Object-level call so it works regardless of whether the
    # player ship is registered under the name "player" in this set.
    Camera.LowPlacementWatch(cam, wp, player, 0, 1)
    _active[0] = True

    # Observability: did the host-side override actually engage?
    from engine.host_loop import _active_cutscene_camera
    cc = _active_cutscene_camera()
    print("[cutscene-probe] START set=%s player=%s -> active_cutscene_camera=%s"
          % (set_name, player.GetName(),
             "OK (override engaged)" if cc is not None else "None (FAILED — override off)"))


def stop():
    """Remove the cutscene camera so the override reverts (deleting the active
    camera clears the set's active-camera name → _active_cutscene_camera() None
    → director/bridge resumes)."""
    player = MissionLib.GetPlayer()
    pSet = player.GetContainingSet() if player is not None else None
    if pSet is not None:
        pSet.DeleteCameraFromSet(_CAM_NAME)
    _active[0] = False
    print("[cutscene-probe] STOP — director/bridge camera resumes")


def toggle():
    if _active[0]:
        stop()
    else:
        start()
