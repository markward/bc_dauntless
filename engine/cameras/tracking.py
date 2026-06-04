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

        Builds a 2D solver plane spanned by (T−S) and ship-body-up,
        places the eye on the inscribed-angle locus arc above and
        behind the player at distance d_chase, and constructs the
        camera basis so player projects to y_p and target to y_t.

        dt is currently unused; springs land in Task 9.
        """
        from engine.appc.math import TGPoint3

        S = player.GetWorldLocation()
        T = target.GetWorldLocation()
        R = player.GetWorldRotation()
        B = R.GetCol(2)  # ship body-up in world space

        # Plane basis (e1, e3): e1 along ship→target, e3 = body-up
        # projected perpendicular to e1, normalised.
        e1, e3 = self._plane_basis(S, T, B)

        # 2D coords: S = (0,0), T = (D,0). Solve for eye (e_x, e_y).
        D    = TGPoint3(T.x-S.x, T.y-S.y, T.z-S.z).Length()
        a_p  = self._screen_y_to_angle(self.y_p)
        a_t  = self._screen_y_to_angle(self.y_t)
        beta = a_t - a_p

        e_x, e_y = self._solve_eye_2d(D, self.d_chase, beta)

        # Lift back to 3D: E = S + e_x * e1 + e_y * e3.
        eye = (S.x + e_x * e1.x + e_y * e3.x,
               S.y + e_x * e1.y + e_y * e3.y,
               S.z + e_x * e1.z + e_y * e3.z)

        # Project (S − E) onto the solver plane (e1, e3), then rotate
        # that 2D direction by −α_p so the player appears at screen-Y y_p
        # exactly.  Working in the 2D plane avoids the wrong-axis rotation
        # result that rotating around e3 would produce: with (S − E) tilted
        # off the e1 axis, an axis-e3 rotation leaves the e3 component intact
        # and mis-aims forward.
        s_minus_e = (S.x - eye[0], S.y - eye[1], S.z - eye[2])
        es_e1 = s_minus_e[0]*e1.x + s_minus_e[1]*e1.y + s_minus_e[2]*e1.z
        es_e3 = s_minus_e[0]*e3.x + s_minus_e[1]*e3.y + s_minus_e[2]*e3.z
        # Rotate (es_e1, es_e3) by −α_p in the plane:
        #   angle_forward = atan2(es_e3, es_e1) − α_p
        # atan2 is scale-invariant, so no normalisation is needed.
        angle_es  = _math.atan2(es_e3, es_e1)
        angle_fwd = angle_es - a_p
        f_2d = (_math.cos(angle_fwd), _math.sin(angle_fwd))

        # Lift forward from 2D plane coords to 3D world space.
        forward = (
            f_2d[0]*e1.x + f_2d[1]*e3.x,
            f_2d[0]*e1.y + f_2d[1]*e3.y,
            f_2d[0]*e1.z + f_2d[1]*e3.z,
        )

        # Up = e3 with the forward-parallel component projected out
        # (Gram-Schmidt). Forward lies in the (e1, e3) plane, so up stays
        # in-plane. Magnitude before normalising is |cos(angle(e3, forward))|;
        # the divide below is load-bearing, not defensive.
        dot_u_f = e3.x*forward[0] + e3.y*forward[1] + e3.z*forward[2]
        ux = e3.x - dot_u_f * forward[0]
        uy = e3.y - dot_u_f * forward[1]
        uz = e3.z - dot_u_f * forward[2]
        ulen = _math.sqrt(ux*ux + uy*uy + uz*uz)
        up = (ux/ulen, uy/ulen, uz/ulen)

        look_at = (eye[0] + forward[0], eye[1] + forward[1], eye[2] + forward[2])
        return eye, look_at, up

    # ── solver internals ─────────────────────────────────────────────

    @staticmethod
    def _plane_basis(S, T, B):
        """Return (e1, e3) as TGPoint3 unit vectors in world space.

        e1 = (T − S).normalised
        e3 = (B − (B·e1) e1).normalised — body-up perpendicularised
        """
        from engine.appc.math import TGPoint3
        dx, dy, dz = T.x - S.x, T.y - S.y, T.z - S.z
        D = _math.sqrt(dx*dx + dy*dy + dz*dz)
        e1 = TGPoint3(dx/D, dy/D, dz/D)
        dot_b_e1 = B.x*e1.x + B.y*e1.y + B.z*e1.z
        ux = B.x - dot_b_e1 * e1.x
        uy = B.y - dot_b_e1 * e1.y
        uz = B.z - dot_b_e1 * e1.z
        ulen = _math.sqrt(ux*ux + uy*uy + uz*uz)
        if ulen < 1e-9:
            # Body-up parallel to (T − S). Pick any unit vector
            # perpendicular to e1. Use the world-X axis unless e1 is
            # already aligned with it; then fall back to world-Y.
            if abs(e1.x) < 0.9:
                ax, ay, az = 1.0, 0.0, 0.0
            else:
                ax, ay, az = 0.0, 1.0, 0.0
            dot = ax*e1.x + ay*e1.y + az*e1.z
            px, py, pz = ax - dot*e1.x, ay - dot*e1.y, az - dot*e1.z
            plen = _math.sqrt(px*px + py*py + pz*pz)
            return e1, TGPoint3(px/plen, py/plen, pz/plen)
        return e1, TGPoint3(ux/ulen, uy/ulen, uz/ulen)

    @staticmethod
    def _solve_eye_2d(D, d_chase, beta):
        """Return (e_x, e_y) of camera in 2D (e1, e3) coords.

        Standard case: closed-form via inscribed-angle / chase-circle
        intersection (spec §3 step 4).
        Fallback (d_chase ≥ D cot β): place E on the locus arc
        directly behind the player (spec §3 step 5).
        """
        sin_b = _math.sin(beta)
        cos_b = _math.cos(beta)
        r     = D / (2.0 * sin_b)
        h     = D / (2.0 * _math.tan(beta))    # locus centre e3-coord

        # Condition: d_chase < D / tan β  ↔  back-of-player solution exists.
        if d_chase < D / _math.tan(beta):
            a       = (d_chase * d_chase) / (2.0 * r)
            disc    = d_chase * d_chase - a * a
            h_chord = _math.sqrt(max(disc, 0.0))
            e_x = a * sin_b - h_chord * cos_b
            e_y = a * cos_b + h_chord * sin_b
            return e_x, e_y

        # Fallback: closest point on locus arc to the −e1 ray (the ray
        # behind the player along the ship→target axis).
        # The locus circle centred at (D/2, h) intersects the e1 axis
        # at S = (0,0) and T = (D, 0). Going "left" along the major
        # arc from S puts the camera at the leftmost point of the
        # circle: (D/2 − r, h). That's the fallback eye.
        return (D / 2.0 - r, h)
