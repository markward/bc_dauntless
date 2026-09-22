"""Camera mode dispatch.

The director owns the mode flag, the C-key toggle, and what happens when
the target goes away. compute() forwards to the active camera. Mode
transitions snap the receiving camera so the first frame in the new
mode lands directly on the solver pose without springing in from
stale state.

Target loss does NOT drop the camera to Chase. On the original exe the
Target camera survives its target's destruction: at removal the player's
target clears and the reticule vanishes, but the camera stays in Target
mode aimed at the wreck's last position indefinitely (stbc-oracle bible
§12.2a V7, `camera_kill/*`: ≥ 34 s observed, the aim still 4.7° off the
wreck's bearing after the player yawed 96° away — the same as for a live
target that does not move, since the mode places the camera on the
target→ship line). We keep a ghost of the last target pose and go on
framing it until a new target is selected or the C key is pressed.
"""
from enum import Enum

from engine.cameras          import (
    EXTERIOR_FOV_Y_RAD, fov_distance_scale, speed_fov_boost_rad,
)
from engine.cameras.chase    import _ChaseCamera
from engine.cameras.tracking import _TrackingCamera
from engine.ui.target_reticle import target_aim_point


class CameraMode(Enum):
    CHASE    = "chase"
    TRACKING = "tracking"


class _GhostTarget:
    """The last pose of a target that has gone: what Target mode keeps
    framing after a destruction (V7). Quacks like a ship for the solver."""
    def __init__(self, loc, rot, radius):
        from engine.appc.math import TGPoint3
        self._loc = TGPoint3(loc.x, loc.y, loc.z)
        self._rot = rot
        self._radius = radius

    def GetWorldLocation(self): return self._loc
    def GetWorldRotation(self): return self._rot
    def GetRadius(self):        return self._radius


class _CameraDirector:
    def __init__(self):
        self.mode              = CameraMode.CHASE
        self.chase             = _ChaseCamera()
        self.tracking          = _TrackingCamera()
        self._opted_out_target = None  # target the user manually toggled OUT of Tracking
        # Ghost of the last target (V7): the last pose framed, refreshed
        # every framed frame and used once the target goes away.
        self._ghost            = None
        self._ghost_aim        = None
        # True only while we are COMPUTING FROM the ghost. The ghost itself
        # is present almost always, so it cannot stand in for this: treating
        # its presence as "we were on a ghost" re-snapped the tracking camera
        # every frame, and snap() clears zoom_target_active — live, pressing
        # Z with a target locked did nothing.
        self._on_ghost         = False
        # Vertical FOV used for r.set_camera and Tracking's projection math.
        # Seeded from EXTERIOR_FOV_Y_RAD; runtime changes via set_fov().
        self.fov_y_rad         = EXTERIOR_FOV_Y_RAD
        # Speed-linked widening on top of fov_y_rad (engine.cameras.
        # speed_fov_boost_rad). Kept separate so the settings store, which
        # reads fov_y_rad, never persists a boosted value.
        self._speed_fov_boost  = 0.0

    @property
    def effective_fov_y_rad(self) -> float:
        """The FOV actually rendered this frame: the user's setting plus the
        speed boost. host_loop reads this for r.set_camera and for every
        unprojection that must agree with it (reticle, manual aim)."""
        return self.fov_y_rad + self._speed_fov_boost

    def set_fov(self, rad: float) -> None:
        """Update the exterior vertical FOV (the persisted setting).
        Propagates to the Tracking solver so screen-Y / angle conversions
        stay in sync, and re-derives the FOV distance compensation."""
        self.fov_y_rad           = rad
        self.tracking.v_fov_rad  = self.effective_fov_y_rad
        scale = fov_distance_scale(rad)
        self.chase.fov_scale     = scale
        self.tracking.fov_scale  = scale

    def set_speed(self, forward_speed_gups: float) -> None:
        """Per-frame: widen the effective FOV with the player's FORWARD
        speed (negative astern narrows it). The distance compensation is
        left keyed to the base FOV on purpose — compensating the widening
        away would cancel the speed cue."""
        self._speed_fov_boost    = speed_fov_boost_rad(forward_speed_gups)
        self.tracking.v_fov_rad  = self.effective_fov_y_rad

    # ── mode transitions ─────────────────────────────────────────────

    def toggle_mode(self, *, player) -> None:
        """C-key handler. Chase ↔ Tracking, but only enter Tracking if
        the player has a valid (non-self) target."""
        if self.mode is CameraMode.CHASE:
            tgt = self._valid_target(player)
            if tgt is None:
                return  # no target → stay in Chase
            self.mode = CameraMode.TRACKING
            self.tracking.snap()
            self._opted_out_target = None
            self.chase.exit_reverse()
            self._remember(tgt, target_aim_point(player), None)
        else:
            # Leaving Tracking manually: record the current target so
            # auto-engage doesn't immediately re-fire next frame.
            tgt = self._valid_target(player)
            self._opted_out_target = tgt  # None if no target (defensive)
            self.mode = CameraMode.CHASE
            self.tracking.exit_zoom_target()
            self._release_ghost()

    def snap(self) -> None:
        """Propagate snap() to both cameras. Use on mission swap /
        hard cut."""
        self.chase.snap()
        self.tracking.snap()
        self._opted_out_target = None
        self._release_ghost()

    def _release_ghost(self) -> None:
        self._ghost = None
        self._ghost_aim = None
        self._on_ghost = False

    # ── zoom controls ────────────────────────────────────────────────

    def start_zoom_target(self, *, player) -> None:
        """Z-key down. Enter ZoomTarget if currently in Tracking with a
        valid target. Otherwise no-op."""
        if self.mode is not CameraMode.TRACKING:
            return
        if self._valid_target(player) is None:
            return
        self.tracking.enter_zoom_target()

    def end_zoom_target(self) -> None:
        """Z-key up. Unconditionally exit ZoomTarget (safe to call when
        not active — idempotent)."""
        self.tracking.exit_zoom_target()

    def start_reverse(self) -> None:
        """V-key down. Enter Reverse Chase if currently in CHASE mode.
        No-op in Tracking (V is Chase-only per spec §1)."""
        if self.mode is CameraMode.CHASE:
            self.chase.enter_reverse()

    def end_reverse(self) -> None:
        """V-key up. Idempotent."""
        self.chase.exit_reverse()

    def zoom_in(self) -> None:
        """=-key press. Delegate to the active mode's camera."""
        if self.mode is CameraMode.TRACKING:
            self.tracking.zoom_in()
        else:  # CHASE
            self.chase.zoom_in()

    def zoom_out(self) -> None:
        """-key press. Symmetric to zoom_in."""
        if self.mode is CameraMode.TRACKING:
            self.tracking.zoom_out()
        else:  # CHASE
            self.chase.zoom_out()

    # ── per-frame dispatch ───────────────────────────────────────────

    def compute(self, *, player, dt, pose_of=None):
        if pose_of is not None:
            loc, rot = pose_of(player)
        else:
            loc = player.GetWorldLocation()
            rot = player.GetWorldRotation()
        if self.mode is CameraMode.TRACKING:
            tgt = self._valid_target(player)
            if tgt is None:
                # Target lost (destroyed, or cleared): Target mode holds on
                # the ghost of its last pose (V7). ZoomTarget is released —
                # the capture did not exercise it. If there is no ghost yet
                # (nothing was ever framed), there is nothing to hold on.
                self.tracking.exit_zoom_target()
                self._opted_out_target = None
                if self._ghost is None:
                    self.mode = CameraMode.CHASE
                else:
                    self._on_ghost = True
                    return self.tracking.compute(
                        player=player, target=self._ghost, dt=dt,
                        aim_point=self._ghost_aim,
                        pose_of=self._pose_of_with_ghost(pose_of))
            else:
                if self._on_ghost:
                    # A live target takes over from the ghost we were framing.
                    self._release_ghost()
                    self.tracking.snap()
                aim = target_aim_point(player, pose_of=pose_of)
                self._remember(tgt, aim, pose_of)
                return self.tracking.compute(player=player, target=tgt, dt=dt,
                                             aim_point=aim, pose_of=pose_of)
        else:
            # CHASE: auto-engage Tracking if a target is present and the user
            # hasn't manually opted out of Tracking for this specific target.
            tgt = self._valid_target(player)
            if tgt is None:
                # No target at all — clear any stale opt-out so a future
                # target acquisition (even the same object) auto-engages.
                self._opted_out_target = None
            elif tgt is not self._opted_out_target:
                self.mode = CameraMode.TRACKING
                self.tracking.snap()
                self._opted_out_target = None
                self.chase.exit_reverse()
                aim = target_aim_point(player, pose_of=pose_of)
                self._remember(tgt, aim, pose_of)
                return self.tracking.compute(player=player, target=tgt, dt=dt,
                                             aim_point=aim, pose_of=pose_of)
        return self.chase.compute_camera(loc, rot, dt=dt)

    # ── helpers ──────────────────────────────────────────────────────

    def _remember(self, tgt, aim, pose_of) -> None:
        """Keep the target's current pose so a loss can hold on it."""
        from engine.appc.camera_modes import _target_radius
        if pose_of is not None:
            loc, rot = pose_of(tgt)
        else:
            loc, rot = tgt.GetWorldLocation(), tgt.GetWorldRotation()
        self._ghost = _GhostTarget(loc, rot, _target_radius(tgt))
        self._ghost_aim = aim

    def _pose_of_with_ghost(self, pose_of):
        """The interpolated-pose reader, taught to answer for the ghost."""
        if pose_of is None:
            return None
        ghost = self._ghost
        def _pose(obj):
            if obj is ghost:
                return ghost.GetWorldLocation(), ghost.GetWorldRotation()
            return pose_of(obj)
        return _pose

    @staticmethod
    def _valid_target(player):
        get_target = getattr(player, "GetTarget", None)
        if get_target is None:
            return None
        tgt = get_target()
        if tgt is None or tgt is player:
            return None
        return tgt
