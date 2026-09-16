"""Camera modes for the tactical view.

Each mode is a separate class returning (eye, look_at, up) in world
space. The director dispatches based on the active mode flag.

Adding a new mode = new file in this package + new entry in CameraMode
enum + one branch in the director. No edits to existing modes.
"""
import math

# Default vertical field of view for the exterior camera. Seeds
# _CameraDirector.fov_y_rad and _TrackingCamera.v_fov_rad at
# construction; runtime changes go through _CameraDirector.set_fov,
# which also re-syncs the tracking solver's projection math.
# host_loop.py reads director.fov_y_rad when calling r.set_camera,
# so the constant is the source of truth at startup only.
EXTERIOR_FOV_Y_RAD: float = math.radians(35.0)

def fov_distance_scale(fov_y_rad: float) -> float:
    """Framing-distance multiplier that keeps a ship's apparent size constant
    across the exterior FOV setting.

    BC had no FOV option; every framing distance here was tuned at
    EXTERIOR_FOV_Y_RAD. Apparent size goes as r / (d · tan(fov/2)), so
    holding it constant means d · tan(fov/2) is constant:

        scale = tan(ref/2) / tan(fov/2)

    45° against the 35° reference is ×0.761 — two BC zoom notches
    (0.875² = 0.766). Applied at eye-placement time only, so the stored
    distances and their clamps stay in reference-FOV units and a FOV change
    never eats the player's zoom setting.

    Narrow side (2026-09-16 live pass): the pure invariant was "about
    perfect" at 45° but "a little too close" at 25° — a telephoto view of a
    ship at the same screen size reads as too dominant. Below the reference
    the ratio is raised to FOV_NARROW_EXPONENT; above it the ratio stands.
    Continuous at the reference, and 45° is untouched. With 1.5: 30° is
    ×1.30 (was ×1.19), 25° is ×1.69 (was ×1.42).
    """
    ratio = math.tan(EXTERIOR_FOV_Y_RAD / 2.0) / math.tan(fov_y_rad / 2.0)
    if ratio > 1.0:
        return ratio ** FOV_NARROW_EXPONENT
    return ratio


# Exponent on the tan ratio for FOVs NARROWER than the reference — see
# fov_distance_scale. 1.0 would be the pure apparent-size invariant.
FOV_NARROW_EXPONENT = 1.5


# Speed-linked FOV (ours, not BC's — BC had no FOV setting at all): the
# exterior FOV widens linearly with the player's speed, reaching
# +SPEED_FOV_BOOST_DEG at SPEED_FOV_FULL_KPH and holding there (warp is far
# past it). 4000 kph is a hair above a Galaxy's full impulse (6.3 GU/s =
# 3969 kph), so full impulse ≈ the full boost. Additive on the user's FOV
# setting; deliberately NOT fed to fov_distance_scale, which would dolly the
# camera in to cancel the widening.
SPEED_FOV_BOOST_DEG = 4.0
SPEED_FOV_FULL_KPH  = 4000.0


def speed_fov_boost_rad(speed_gups: float) -> float:
    """Extra vertical FOV, in radians, for a player moving at `speed_gups`."""
    from engine.units import GUPS_TO_KPH
    t = (speed_gups * GUPS_TO_KPH) / SPEED_FOV_FULL_KPH
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    return math.radians(SPEED_FOV_BOOST_DEG) * t


# BC's Chase mode, as authored (CameraModes.Chase, CameraModes.py:12-32) and
# as the binary reads it (ChaseCameraMode::GetIdealPosition 0x00422400, RE'd
# 2026-09-16):  eye = T + R · unit(DefaultPosition) · (Distance · r).
# DefaultPosition is a DIRECTION (normalised at set time, 0x004220A0) — 5.7°
# above dead astern; Distance is the standoff in multiples of the ship's NIF
# bounding-sphere radius (what GetRadius() returns); Min/MaximumDistance are
# the same units and bound only the zoom step (FUN_0041F920).
CHASE_DEFAULT_POSITION = (0.0, -1.0, 0.1)   # body frame: X right, Y fwd, Z up
BC_CHASE_DISTANCE_RADII = 4.0               # BC's authored Distance — faithful
CHASE_MIN_RADII        =  2.0
CHASE_MAX_RADII        = 40.0
# DELIBERATE DEVIATION (2026-09-16 live pass): the authored 4.0 is BC's exact
# framing — our GetRadius() is within 10% of BC's merged NiBound for every
# hull measured (Galaxy 4.03 vs 4.46 GU) and our 35° vertical FOV is
# narrower than Gamebryo's 41° default — but on a widescreen window the same
# angular size reads as "too far out" (a Galaxy saucer is ~24% of the frame
# width vs ~28% at 4:3). Mark asked for it closer. Set back to
# BC_CHASE_DISTANCE_RADII to restore the original. Min/Max stay authored.
CHASE_DISTANCE_RADII   =  3.0

# CameraObjectClass.Zoom(f) → mode vt+0x84 → FUN_0041F920:
#   Distance = clamp(Distance · (1 − 0.5·f), Min, Max)
# The shipped keyboard binds f = ±0.25 (DefaultUKKeyboardBinding.py:27-30),
# so one press is ×0.875 in / ×1.125 out. They are not inverses: an in/out
# pair drifts ~1.6% inward. Every BC mode shares this one body.
ZOOM_IN_FACTOR  = 0.875
ZOOM_OUT_FACTOR = 1.125

# Tracking-mode (our inscribed-angle solver — no BC analogue) follow distances
# as multiples of the player ship's GetRadius().
CAM_BACK_RADII  =  1.5
CAM_UP_RADII    =  0.25
CAM_MIN_RADII   =  0.6
CAM_MAX_RADII   = 30.0

# Extra zoom-out clicks baked into Tracking's default framing, nudging the
# camera further back by default. One click = ÷ the per-notch zoom factor
# (~0.9), so N clicks ≈ ×(1/0.9)^N. Applied on top of the base distance.
DEFAULT_ZOOM_OUT_CLICKS = 5

from engine.cameras.director import CameraMode, _CameraDirector  # noqa: E402
