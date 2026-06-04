"""Camera mode dispatch.

The director owns the mode flag, the C-key toggle, and the
target-loss fallback. compute() forwards to the active camera. Mode
transitions snap the receiving camera so the first frame in the new
mode lands directly on the solver pose without springing in from
stale state.
"""
from enum import Enum

from engine.cameras.chase    import _ChaseCamera
from engine.cameras.tracking import _TrackingCamera


class CameraMode(Enum):
    CHASE    = "chase"
    TRACKING = "tracking"


class _CameraDirector:
    def __init__(self):
        self.mode              = CameraMode.CHASE
        self.chase             = _ChaseCamera()
        self.tracking          = _TrackingCamera()
        self._opted_out_target = None  # target the user manually toggled OUT of Tracking

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
        else:
            # Leaving Tracking manually: record the current target so
            # auto-engage doesn't immediately re-fire next frame.
            tgt = self._valid_target(player)
            self._opted_out_target = tgt  # None if no target (defensive)
            self.mode = CameraMode.CHASE

    def snap(self) -> None:
        """Propagate snap() to both cameras. Use on mission swap /
        hard cut."""
        self.chase.snap()
        self.tracking.snap()
        self._opted_out_target = None

    # ── per-frame dispatch ───────────────────────────────────────────

    def compute(self, *, player, dt):
        loc = player.GetWorldLocation()
        rot = player.GetWorldRotation()
        if self.mode is CameraMode.TRACKING:
            tgt = self._valid_target(player)
            if tgt is None:
                # Target lost → durable fallback to Chase; clear opt-out so
                # re-acquiring any target (including the old one) auto-engages.
                self.mode = CameraMode.CHASE
                self._opted_out_target = None
            else:
                return self.tracking.compute(player=player, target=tgt, dt=dt)
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
                return self.tracking.compute(player=player, target=tgt, dt=dt)
        return self.chase.compute_camera(loc, rot, dt=dt)

    # ── helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _valid_target(player):
        get_target = getattr(player, "GetTarget", None)
        if get_target is None:
            return None
        tgt = get_target()
        if tgt is None or tgt is player:
            return None
        return tgt
