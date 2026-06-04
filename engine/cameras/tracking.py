"""Tracking Mode — two-angle inscribed-angle solver.

Frames player and target at fixed screen-Y fractions across all
ranges. Camera-up is derived from the player ship body frame; no
world-Z reference. Springs on eye position and camera basis.

See:
    docs/superpowers/specs/2026-06-04-tracking-camera-rework-design.md
"""
import math as _math

from engine.cameras import EXTERIOR_FOV_Y_RAD


class _TrackingCamera:
    """Two-angle solver + eye/basis springs."""

    # Default screen-Y fractions of the half-image, signed:
    #   negative = below centre, positive = above centre.
    y_p: float = -0.25   # player
    y_t: float = +0.25   # target

    # Spring time constants — see spec §4.
    POS_SPRING_TAU_S: float = 0.25
    ROT_SPRING_TAU_S: float = 0.50

    def __init__(self):
        self.v_fov_rad      = EXTERIOR_FOV_Y_RAD
        self.d_chase        = 1.0  # set via set_ship_radius (Task 9)
        self._smoothed_eye  = None
        self._smoothed_basis = None

    # ── small helpers ────────────────────────────────────────────────

    def _screen_y_to_angle(self, y: float) -> float:
        """Convert a screen-Y fraction in [-1, +1] to a signed angle from
        camera-forward, using the camera's vertical FOV."""
        return _math.atan(y * _math.tan(self.v_fov_rad / 2))

    # ── public surface ───────────────────────────────────────────────

    def compute(self, player, target, dt):
        """Return (eye, look_at, up) in world space.

        Implementation arrives over Tasks 6–9. For now raises so
        callers fail loudly if they reach Tracking before the solver
        exists.
        """
        raise NotImplementedError("tracking solver lands in Tasks 6–9")
