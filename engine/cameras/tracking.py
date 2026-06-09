"""Tracking Mode — two-angle inscribed-angle solver.

Frames player and target at fixed screen-Y fractions across all
ranges. Camera-up is derived from the player ship body frame; no
world-Z reference. Springs on eye position and camera basis.

See:
    docs/superpowers/specs/2026-06-04-tracking-camera-rework-design.md
"""
import math as _math

from engine.cameras import (
    EXTERIOR_FOV_Y_RAD, CAM_BACK_RADII, CAM_UP_RADII,
)


class _TrackingCamera:
    """Two-angle solver + ZoomTarget sub-mode + eye/basis springs."""

    # Default screen-Y fractions of the half-image, signed:
    #   negative = below centre, positive = above centre.
    y_p: float = -0.25   # player
    y_t: float = +0.25   # target

    # Spring time constants — see tracking-camera-rework spec §4.
    POS_SPRING_TAU_S: float = 0.25
    ROT_SPRING_TAU_S: float = 0.50

    # Sticky zoom — see tracking-zoom-and-zoom-target spec §2.
    ZOOM_FACTOR_PER_PRESS: float = 0.9     # one =/- press = ×0.9 / ÷0.9
    ZOOM_MIN_RADII:        float = 0.74    # = 0.6 / 0.9² — pull the floor back
                                            # 2 zoom-out clicks from the
                                            # CAM_MIN_RADII baseline so the
                                            # closest framing is less oppressive
                                            # (post-playtest tuning).
    ZOOM_MAX_RADII:        float = 30.0    # reuse CAM_MAX_RADII semantics
    ZOOM_DEFAULT_RADII:    float = 0.74    # ZoomTarget seed = ZOOM_MIN_RADII

    def __init__(self):
        self.v_fov_rad        = EXTERIOR_FOV_Y_RAD
        # Two persistent distance slots. d_chase_tracking is the chase
        # distance from the player in normal Tracking framing.
        # d_chase_zoom is the eye-to-target distance in ZoomTarget mode.
        self.d_chase_tracking = 1.0   # seeded by set_ship_radius()
        self.d_chase_zoom     = 1.0   # seeded by set_ship_radius()
        self.zoom_min         = 1.0   # seeded by set_ship_radius()
        self.zoom_max         = 1.0   # seeded by set_ship_radius()
        # ZoomTarget sub-mode flag — toggled by enter/exit_zoom_target.
        self.zoom_target_active = False
        # Spring state (unchanged).
        self._smoothed_eye   = None
        self._smoothed_basis = None

    # ── small helpers ────────────────────────────────────────────────

    def _screen_y_to_angle(self, y: float) -> float:
        """Convert a screen-Y fraction in [-1, +1] to a signed angle from
        camera-forward, using the camera's vertical FOV."""
        return _math.atan(y * _math.tan(self.v_fov_rad / 2))

    # ── public surface ───────────────────────────────────────────────

    def set_ship_radius(self, radius: float) -> None:
        radius = max(radius, 1e-6)
        self.d_chase_tracking = _math.sqrt(CAM_BACK_RADII**2 + CAM_UP_RADII**2) * radius
        self.zoom_min         = self.ZOOM_MIN_RADII * radius
        self.zoom_max         = self.ZOOM_MAX_RADII * radius
        # ZoomTarget seeds at minimum so the first `=` press is a no-op
        # (matches BC behaviour observed in playtest).
        self.d_chase_zoom     = self.ZOOM_DEFAULT_RADII * radius

    def zoom_in(self) -> None:
        """Sticky zoom (= key): bring the camera closer to its anchor.
        Modifies whichever distance is active based on zoom_target_active."""
        if self.zoom_target_active:
            self.d_chase_zoom = max(
                self.d_chase_zoom * self.ZOOM_FACTOR_PER_PRESS,
                self.zoom_min,
            )
        else:
            self.d_chase_tracking = max(
                self.d_chase_tracking * self.ZOOM_FACTOR_PER_PRESS,
                self.zoom_min,
            )

    def zoom_out(self) -> None:
        """Sticky zoom (- key): push the camera farther from its anchor."""
        if self.zoom_target_active:
            self.d_chase_zoom = min(
                self.d_chase_zoom / self.ZOOM_FACTOR_PER_PRESS,
                self.zoom_max,
            )
        else:
            self.d_chase_tracking = min(
                self.d_chase_tracking / self.ZOOM_FACTOR_PER_PRESS,
                self.zoom_max,
            )

    def enter_zoom_target(self) -> None:
        """Activate the ZoomTarget sub-mode. Does NOT reset
        d_chase_zoom — preserves it across press/release."""
        self.zoom_target_active = True

    def exit_zoom_target(self) -> None:
        """Deactivate the ZoomTarget sub-mode."""
        self.zoom_target_active = False

    def snap(self) -> None:
        """Drop both smoothing states and reset zoom to defaults.

        Use on mode-enter (Chase → Tracking transitions), mission swap,
        and hard cuts (teleport / warp exit). All three sites are valid
        because snap() re-seeds the distance slots from the current
        ship radius (recovered via zoom_max / ZOOM_MAX_RADII).
        """
        self._smoothed_eye   = None
        self._smoothed_basis = None
        # Reset zoom by re-seeding from the current ship radius.
        # Recover the radius from zoom_max / ZOOM_MAX_RADII.
        if self.zoom_max > 0.0:
            radius = self.zoom_max / self.ZOOM_MAX_RADII
            self.d_chase_tracking = _math.sqrt(CAM_BACK_RADII**2 + CAM_UP_RADII**2) * radius
            self.d_chase_zoom     = self.ZOOM_DEFAULT_RADII * radius
        # Flag reset is unconditional — runs even when zoom_max == 0
        # (i.e. snap() called before set_ship_radius).
        self.zoom_target_active = False

    def compute(self, player, target, dt, aim_point=None):
        """Return (eye, look_at, up) in world space.

        Builds a 2D solver plane spanned by (T−S) and ship-body-up,
        places the eye on the inscribed-angle locus arc above and
        behind the player at distance d_chase_tracking, and constructs the
        camera basis so player projects to y_p and target to y_t.

        When zoom_target_active is True, delegates to _compute_zoom_target
        which places the eye on the player→target axis at d_chase_zoom
        behind the target instead of the inscribed-angle solver.

        When dt is None, returns the solver output directly (no springs).
        When dt is a float, applies position + rotation springs.

        When `aim_point` is given, it replaces the target hull centre as the framed point T.
        """
        from engine.appc.math import TGPoint3, TGMatrix3

        S = player.GetWorldLocation()
        T = aim_point if aim_point is not None else target.GetWorldLocation()
        R = player.GetWorldRotation()
        B = R.GetCol(2)  # ship body-up in world space

        # Plane basis (e1, e3): e1 along ship→target, e3 = body-up
        # projected perpendicular to e1, normalised.
        e1, e3 = self._plane_basis(S, T, B)

        if self.zoom_target_active:
            eye_solver, forward_solver, up_solver = self._compute_zoom_target(
                S=S, T=T, e1=e1, e3=e3,
            )
        else:
            eye_solver, forward_solver, up_solver = self._compute_tracking(
                S=S, T=T, e1=e1, e3=e3,
            )

        # Build the solver basis matrix (columns: right, forward, up).
        right_solver = (
            up_solver[1]*forward_solver[2] - up_solver[2]*forward_solver[1],
            up_solver[2]*forward_solver[0] - up_solver[0]*forward_solver[2],
            up_solver[0]*forward_solver[1] - up_solver[1]*forward_solver[0],
        )
        basis_solver = TGMatrix3()
        basis_solver.SetCol(0, TGPoint3(*right_solver))
        basis_solver.SetCol(1, TGPoint3(*forward_solver))
        basis_solver.SetCol(2, TGPoint3(*up_solver))

        if dt is None:
            # No springs — return solver output directly. (Used by
            # geometry tests in Tasks 6–8.)
            eye_out   = eye_solver
            forward_o = forward_solver
            up_o      = up_solver
        else:
            eye_out, basis_out = self._advance_springs(
                eye_solver=eye_solver, basis_solver=basis_solver, dt=dt,
            )
            f = basis_out.GetCol(1); u = basis_out.GetCol(2)
            forward_o = (f.x, f.y, f.z)
            up_o      = (u.x, u.y, u.z)

        look_at = (
            eye_out[0] + forward_o[0],
            eye_out[1] + forward_o[1],
            eye_out[2] + forward_o[2],
        )
        return eye_out, look_at, up_o

    # ── spring engine ────────────────────────────────────────────────

    def _advance_springs(self, *, eye_solver, basis_solver, dt):
        """Apply position + rotation springs. Seeds on first call.

        Returns (eye_smoothed_tuple, basis_smoothed_TGMatrix3).
        """
        from engine.appc.math import TGPoint3, TGMatrix3

        if self._smoothed_eye is None:
            self._smoothed_eye = list(eye_solver)
        if self._smoothed_basis is None:
            self._smoothed_basis = TGMatrix3()
            for i in range(3):
                self._smoothed_basis.SetCol(i, basis_solver.GetCol(i))

        # Position spring.
        alpha_p = 1.0 - _math.exp(-dt / self.POS_SPRING_TAU_S) if dt > 0.0 else 0.0
        for i in range(3):
            self._smoothed_eye[i] += alpha_p * (eye_solver[i] - self._smoothed_eye[i])

        # Rotation spring — Gram-Schmidt re-orthonormalisation.
        alpha_r = 1.0 - _math.exp(-dt / self.ROT_SPRING_TAU_S) if dt > 0.0 else 0.0
        blended = [None, None, None]
        for i in range(3):
            s = self._smoothed_basis.GetCol(i)
            l = basis_solver.GetCol(i)
            blended[i] = TGPoint3(
                s.x + alpha_r * (l.x - s.x),
                s.y + alpha_r * (l.y - s.y),
                s.z + alpha_r * (l.z - s.z),
            )

        def _norm(v):
            m = _math.sqrt(v.x*v.x + v.y*v.y + v.z*v.z)
            return TGPoint3(v.x/m, v.y/m, v.z/m)

        f = _norm(blended[1])
        u_in = blended[2]
        dot_uf = u_in.x*f.x + u_in.y*f.y + u_in.z*f.z
        u = _norm(TGPoint3(
            u_in.x - dot_uf * f.x,
            u_in.y - dot_uf * f.y,
            u_in.z - dot_uf * f.z,
        ))
        r = TGPoint3(
            f.y*u.z - f.z*u.y,
            f.z*u.x - f.x*u.z,
            f.x*u.y - f.y*u.x,
        )
        self._smoothed_basis.SetCol(0, r)
        self._smoothed_basis.SetCol(1, f)
        self._smoothed_basis.SetCol(2, u)
        return tuple(self._smoothed_eye), self._smoothed_basis

    # ── per-branch solver ────────────────────────────────────────────

    def _compute_tracking(self, *, S, T, e1, e3):
        """Two-angle inscribed-angle solver against the player anchor.
        See tracking-camera-rework spec §3."""
        from engine.appc.math import TGPoint3

        D    = TGPoint3(T.x-S.x, T.y-S.y, T.z-S.z).Length()
        a_p  = self._screen_y_to_angle(self.y_p)
        a_t  = self._screen_y_to_angle(self.y_t)
        beta = a_t - a_p

        e_x, e_y = self._solve_eye_2d(D, self.d_chase_tracking, beta)
        eye_solver = (S.x + e_x * e1.x + e_y * e3.x,
                      S.y + e_x * e1.y + e_y * e3.y,
                      S.z + e_x * e1.z + e_y * e3.z)

        # Project (S − E) onto the solver plane, rotate by −α_p so the
        # player projects at y_p, then perpendicularise e3 against forward.
        s_minus_e = (S.x - eye_solver[0], S.y - eye_solver[1], S.z - eye_solver[2])
        es_e1 = s_minus_e[0]*e1.x + s_minus_e[1]*e1.y + s_minus_e[2]*e1.z
        es_e3 = s_minus_e[0]*e3.x + s_minus_e[1]*e3.y + s_minus_e[2]*e3.z
        angle_fwd = _math.atan2(es_e3, es_e1) - a_p
        f_2d = (_math.cos(angle_fwd), _math.sin(angle_fwd))

        forward_solver = (
            f_2d[0]*e1.x + f_2d[1]*e3.x,
            f_2d[0]*e1.y + f_2d[1]*e3.y,
            f_2d[0]*e1.z + f_2d[1]*e3.z,
        )
        dot_u_f = e3.x*forward_solver[0] + e3.y*forward_solver[1] + e3.z*forward_solver[2]
        ux = e3.x - dot_u_f * forward_solver[0]
        uy = e3.y - dot_u_f * forward_solver[1]
        uz = e3.z - dot_u_f * forward_solver[2]
        ulen = _math.sqrt(ux*ux + uy*uy + uz*uz)
        up_solver = (ux/ulen, uy/ulen, uz/ulen)

        return eye_solver, forward_solver, up_solver

    def _compute_zoom_target(self, *, S, T, e1, e3):
        """ZoomTarget framing: eye on the ship→target axis at
        effective_distance behind target, look-at = target.
        See tracking-zoom-and-zoom-target spec §3.
        """
        D = _math.sqrt((T.x-S.x)**2 + (T.y-S.y)**2 + (T.z-S.z)**2)
        # Clamp the *effective* distance to 0.9 × D only when target is
        # strictly closer than d_chase_zoom. Stored field unchanged
        # (preserves user's zoom setting for when D grows back).
        if self.d_chase_zoom <= D:
            effective = self.d_chase_zoom
        else:
            effective = 0.9 * D

        eye_solver = (T.x - effective * e1.x,
                      T.y - effective * e1.y,
                      T.z - effective * e1.z)
        # Forward = (T − eye) / |T − eye| = e1 (eye lies on the e1 line).
        forward_solver = (e1.x, e1.y, e1.z)
        # Up = e3 perpendicularised against forward. Identical pattern
        # to the Tracking solver's up step.
        dot_u_f = e3.x*forward_solver[0] + e3.y*forward_solver[1] + e3.z*forward_solver[2]
        ux = e3.x - dot_u_f * forward_solver[0]
        uy = e3.y - dot_u_f * forward_solver[1]
        uz = e3.z - dot_u_f * forward_solver[2]
        ulen = _math.sqrt(ux*ux + uy*uy + uz*uz)
        up_solver = (ux/ulen, uy/ulen, uz/ulen)

        return eye_solver, forward_solver, up_solver

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
        Fallback (d_chase ≥ D cot β): place E at the leftmost point of
        the locus arc (furthest in −e1 direction), at e3 = h above the
        ship→target line (spec §3 step 5).
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

        # Fallback: the leftmost point of the locus circle — the point
        # on the arc furthest in the −e1 direction (behind the player
        # along the ship→target axis). The locus circle centred at
        # (D/2, h) with radius r has its leftmost point at (D/2 − r, h).
        return (D / 2.0 - r, h)
