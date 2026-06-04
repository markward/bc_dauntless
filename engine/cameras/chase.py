"""Chase Mode — free-orbit chase camera.

Arrow-key orbit + scroll-wheel zoom in the player ship's body frame.
The orbit angles and distance are stored in ship-relative coordinates
so the camera "rotates with" the ship: banking/pitching/yawing
preserves the relative camera position.

Conventions:
    orbit_yaw_rad   — rotation around ship-Z. 0 = directly behind,
                      +ve = camera moves to ship-right, -ve = ship-left.
                      Wraps freely; not clamped.
    orbit_pitch_rad — elevation above the ship's XY plane. 0 = level
                      with the ship; +ve = camera above. Clamped to
                      ±PITCH_LIMIT.
    distance        — eye-to-ship distance, multiplicative on scroll.

Behaviourally identical to the prior host_loop._CameraControl; this is
a pure rename + move under Task 2 of the tracking-camera rework.
"""
import math as _math

from engine.cameras import (
    CAM_BACK_RADII, CAM_UP_RADII, CAM_MIN_RADII, CAM_MAX_RADII,
)


class _ChaseCamera:
    """Arrow-key orbit + scroll-wheel zoom around the player ship."""

    TURN_RATE_RAD_PER_S    = 1.5                                # ~86°/s
    ZOOM_FACTOR_PER_NOTCH  = 0.9                                # one scroll click ≈ 10%
    PITCH_LIMIT_RAD        = _math.radians(85)                  # avoid pole flip
    DEFAULT_YAW_RAD        = 0.0
    DEFAULT_PITCH_RAD      = _math.atan2(CAM_UP_RADII, CAM_BACK_RADII)
    SPRING_TAU_S           = 0.50                               # ~95% catch-up in 1.5s

    def __init__(self):
        self.orbit_yaw_rad      = self.DEFAULT_YAW_RAD
        self.orbit_pitch_rad    = self.DEFAULT_PITCH_RAD
        self.reverse_active     = False
        self._smoothed_rot      = None  # seeded on first compute_camera(..., dt=...)
        self.set_ship_radius(1.0)

    def set_ship_radius(self, radius: float) -> None:
        """Bind chase distances to the player ship's GetRadius(). Re-seeds
        self.distance if it was sitting at the prior default; preserves any
        user zoom that has occurred since the last reset."""
        radius = max(radius, 1e-6)
        prev_default = getattr(self, "default_distance", None)
        self.default_distance    = _math.sqrt(CAM_BACK_RADII**2 + CAM_UP_RADII**2) * radius
        self.distance_min        = CAM_MIN_RADII * radius
        self.distance_max        = CAM_MAX_RADII * radius
        if prev_default is None or getattr(self, "distance", prev_default) == prev_default:
            self.distance = self.default_distance

    def reset_orbit(self) -> None:
        """Snap orbit angles and distance back to defaults. Does not change
        the rotation-smoothing state."""
        self.orbit_yaw_rad   = self.DEFAULT_YAW_RAD
        self.orbit_pitch_rad = self.DEFAULT_PITCH_RAD
        self.distance        = self.default_distance

    def snap(self) -> None:
        """Drop smoothed rotation so the next compute_camera(..., dt=...) call
        aligns the camera immediately with the live ship rotation. Use on hard
        cuts (mission swap, teleport, warp exit)."""
        self._smoothed_rot = None

    def enter_reverse(self) -> None:
        """V-key down: flip camera to in-front-of-ship perspective."""
        self.reverse_active = True

    def exit_reverse(self) -> None:
        """V-key up: return to behind-ship perspective."""
        self.reverse_active = False

    def apply(self, dt: float, h, scroll_y: float) -> None:
        """Read arrow keys + C reset + accumulated scroll, update orbit state.

        `h` is the bindings module (or fake) with key_state/key_pressed and a
        `keys` namespace containing KEY_LEFT/RIGHT/UP/DOWN/C.
        `scroll_y` is the total wheel delta accumulated since the last call.
        """
        # C-key is now handled by _CameraDirector.toggle_mode; the
        # chase camera only owns orbit reset on its own dedicated
        # binding (none today — kept as a no-op until a future spec
        # rewires it).

        if h.key_state(h.keys.KEY_RIGHT): self.orbit_yaw_rad   += self.TURN_RATE_RAD_PER_S * dt
        if h.key_state(h.keys.KEY_LEFT):  self.orbit_yaw_rad   -= self.TURN_RATE_RAD_PER_S * dt
        if h.key_state(h.keys.KEY_UP):    self.orbit_pitch_rad += self.TURN_RATE_RAD_PER_S * dt
        if h.key_state(h.keys.KEY_DOWN):  self.orbit_pitch_rad -= self.TURN_RATE_RAD_PER_S * dt

        if self.orbit_pitch_rad >  self.PITCH_LIMIT_RAD: self.orbit_pitch_rad =  self.PITCH_LIMIT_RAD
        if self.orbit_pitch_rad < -self.PITCH_LIMIT_RAD: self.orbit_pitch_rad = -self.PITCH_LIMIT_RAD

        if scroll_y != 0.0:
            self.distance *= self.ZOOM_FACTOR_PER_NOTCH ** scroll_y
            if self.distance < self.distance_min: self.distance = self.distance_min
            if self.distance > self.distance_max: self.distance = self.distance_max

    def compute_camera(self, ship_loc, ship_rot, dt=None) -> tuple:
        """Return (eye, target, up) as 3-tuples in world space.

        Offset is built in ship body frame (X=right, Y=forward, Z=up):
            offset_body = (sin(y)*cos(p), -cos(y)*cos(p), sin(p)) * distance
        At y=0, p=0 the camera sits directly behind on the body-Y axis.
        Mapping body→world uses BC's column-vector convention
        (see CLAUDE.md ↦ "Rotation matrix convention"):
        world_axis_j = basis.GetCol(j).

        When `dt` is given, the basis used here is a smoothed copy of the
        ship's rotation that lags the live value with time constant
        SPRING_TAU_S. This produces the "spring" feel where the ship visibly
        rotates against the camera during a manoeuvre, then settles. When
        `dt` is None the live rotation is used directly and no smoothing
        state is touched (legacy / pure-projection path used by tests).
        """
        basis = self._advance_smoothing(ship_rot, dt) if dt is not None else ship_rot

        yaw_effective = self.orbit_yaw_rad + (_math.pi if self.reverse_active else 0.0)
        cy = _math.cos(yaw_effective)
        sy = _math.sin(yaw_effective)
        cp = _math.cos(self.orbit_pitch_rad)
        sp = _math.sin(self.orbit_pitch_rad)
        d  = self.distance

        ox =  sy * cp * d
        oy = -cy * cp * d
        oz =       sp * d

        rgt = basis.GetCol(0)
        fwd = basis.GetCol(1)
        up  = basis.GetCol(2)

        eye = (
            ship_loc.x + ox * rgt.x + oy * fwd.x + oz * up.x,
            ship_loc.y + ox * rgt.y + oy * fwd.y + oz * up.y,
            ship_loc.z + ox * rgt.z + oy * fwd.z + oz * up.z,
        )
        target = (ship_loc.x, ship_loc.y, ship_loc.z)
        up_vec = (up.x, up.y, up.z)
        return eye, target, up_vec

    def _advance_smoothing(self, ship_rot, dt: float):
        """Blend self._smoothed_rot toward ship_rot, renormalize, and return
        the smoothed basis. Seeds from ship_rot on the first call."""
        from engine.appc.math import TGMatrix3, TGPoint3

        if self._smoothed_rot is None:
            seed = TGMatrix3()
            for i in range(3):
                seed.SetCol(i, ship_rot.GetCol(i))
            self._smoothed_rot = seed
            return self._smoothed_rot

        alpha = 1.0 - _math.exp(-dt / self.SPRING_TAU_S) if dt > 0.0 else 0.0
        blended = [None, None, None]
        for i in range(3):
            s = self._smoothed_rot.GetCol(i)
            l = ship_rot.GetCol(i)
            blended[i] = TGPoint3(
                s.x + alpha * (l.x - s.x),
                s.y + alpha * (l.y - s.y),
                s.z + alpha * (l.z - s.z),
            )

        # Gram-Schmidt re-orthonormalize: keep forward (col 1) as primary
        # axis, project up (col 2) perpendicular to it, derive right via
        # cross product. Body axes are right-handed: forward × up = right.
        # (See CLAUDE.md ↦ "Rotation matrix convention".)
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
            f.y * u.z - f.z * u.y,
            f.z * u.x - f.x * u.z,
            f.x * u.y - f.y * u.x,
        )

        self._smoothed_rot.SetCol(0, r)
        self._smoothed_rot.SetCol(1, f)
        self._smoothed_rot.SetCol(2, u)
        return self._smoothed_rot
