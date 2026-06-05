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
EXTERIOR_FOV_Y_RAD: float = math.radians(65.0)

# Camera-follow distances as multiples of the player ship's GetRadius().
CAM_BACK_RADII  =  1.5
CAM_UP_RADII    =  0.25
CAM_MIN_RADII   =  0.6
CAM_MAX_RADII   = 30.0

from engine.cameras.director import CameraMode, _CameraDirector  # noqa: E402
