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
        self.mode     = CameraMode.CHASE
        self.chase    = _ChaseCamera()
        self.tracking = _TrackingCamera()

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
        else:
            self.mode = CameraMode.CHASE

    def snap(self) -> None:
        """Propagate snap() to both cameras. Use on mission swap /
        hard cut."""
        self.chase.snap()
        self.tracking.snap()

    # ── per-frame dispatch ───────────────────────────────────────────

    def compute(self, *, player, dt):
        loc = player.GetWorldLocation()
        rot = player.GetWorldRotation()
        if self.mode is CameraMode.TRACKING:
            tgt = self._valid_target(player)
            if tgt is None:
                # Target lost → durable fallback to Chase.
                self.mode = CameraMode.CHASE
            else:
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
