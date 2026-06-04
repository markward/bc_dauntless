"""Camera mode dispatch.

The director owns one camera object per CameraMode and a current-mode
flag. compute(...) forwards to the active camera. Mode transitions
(C-key toggle, target-loss fallback) arrive in Task 10.
"""
from enum import Enum

from engine.cameras.chase    import _ChaseCamera
from engine.cameras.tracking import _TrackingCamera


class CameraMode(Enum):
    CHASE    = "chase"
    TRACKING = "tracking"


class _CameraDirector:
    """Mode flag + per-mode camera objects + dispatch."""

    def __init__(self):
        self.mode     = CameraMode.CHASE
        self.chase    = _ChaseCamera()
        self.tracking = _TrackingCamera()

    def compute(self, *, player, dt):
        """Return (eye, look_at, up) in world space for the active mode."""
        loc = player.GetWorldLocation()
        rot = player.GetWorldRotation()
        if self.mode is CameraMode.CHASE:
            return self.chase.compute_camera(loc, rot, dt=dt)
        raise RuntimeError(f"unhandled camera mode: {self.mode}")
