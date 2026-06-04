"""Camera modes for the tactical view.

Each mode is a separate class returning (eye, look_at, up) in world
space. The director dispatches based on the active mode flag.

Adding a new mode = new file in this package + new entry in CameraMode
enum + one branch in the director. No edits to existing modes.
"""
import math

# Vertical field of view for the exterior camera, used by the
# Tracking solver to convert screen-Y fractions to angles via
#     α = atan(y × tan(v_fov / 2))
# Must stay in sync with the value passed to r.set_camera in
# host_loop.py (see Task 4).
EXTERIOR_FOV_Y_RAD: float = math.radians(60.0)

# Camera-follow distances as multiples of the player ship's GetRadius().
CAM_BACK_RADII             =  1.5
CAM_UP_RADII               =  0.25
CAM_MIN_RADII              =  0.6
CAM_MAX_RADII              = 30.0
CAM_LOOK_UP_RADII          =  0.20
CAM_TARGET_LOCK_LIFT_RADII =  1.0

from engine.cameras.director import CameraMode, _CameraDirector  # noqa: E402
