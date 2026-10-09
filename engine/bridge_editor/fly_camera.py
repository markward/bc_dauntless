"""Free fly camera for the bridge editor (spec 2026-10-08-bridge-emitters §4).

Hold RMB to look; W/S forward/back, A/D strafe, Q/E down/up; Shift fast, Alt
slow. Pure: the panel feeds it mouse deltas and key axes. Conventions match
host_loop._BridgeCamera -- bridge-local units, up +Z, forward at yaw 0 is +Y,
+dx looks right, +dy (screen down) looks down."""
import math

FOV_Y_RAD = math.radians(45.0)        # _BridgeCamera.FOV_Y_RAD
BASE_SPEED = 60.0                     # bridge units / s; a DBridge is ~400 across
FAST_MULT = 4.0
SLOW_MULT = 0.25
SENSITIVITY = 0.0015                  # rad per pixel, _BridgeCamera's
PITCH_LIMIT_RAD = math.radians(85.0)
UP = (0.0, 0.0, 1.0)


class FlyCamera:
    def __init__(self, eye, yaw, pitch):
        self.eye = (float(eye[0]), float(eye[1]), float(eye[2]))
        self.yaw = float(yaw)
        self.pitch = max(-PITCH_LIMIT_RAD, min(PITCH_LIMIT_RAD, float(pitch)))

    @classmethod
    def from_pose(cls, eye, target):
        fx, fy, fz = (target[0] - eye[0], target[1] - eye[1], target[2] - eye[2])
        n = math.sqrt(fx * fx + fy * fy + fz * fz)
        if n < 1e-9:
            return cls(eye, 0.0, 0.0)
        fx, fy, fz = fx / n, fy / n, fz / n
        pitch = math.asin(max(-1.0, min(1.0, fz)))
        yaw = math.atan2(-fx, fy)
        return cls(eye, yaw, pitch)

    def forward(self):
        cp = math.cos(self.pitch)
        return (-math.sin(self.yaw) * cp, math.cos(self.yaw) * cp,
                math.sin(self.pitch))

    def right(self):
        # forward x UP, horizontal: (cos yaw, sin yaw, 0).
        return (math.cos(self.yaw), math.sin(self.yaw), 0.0)

    def look(self, dx, dy):
        self.yaw -= dx * SENSITIVITY
        self.pitch -= dy * SENSITIVITY
        self.pitch = max(-PITCH_LIMIT_RAD, min(PITCH_LIMIT_RAD, self.pitch))

    def move(self, dt, forward, strafe, lift, fast=False, slow=False):
        if dt <= 0.0:
            return
        speed = BASE_SPEED * (FAST_MULT if fast else 1.0) * (SLOW_MULT if slow else 1.0)
        f, r = self.forward(), self.right()
        step = speed * dt
        self.eye = tuple(
            self.eye[i] + (f[i] * forward + r[i] * strafe + UP[i] * lift) * step
            for i in range(3))

    def pose(self):
        f = self.forward()
        target = (self.eye[0] + f[0], self.eye[1] + f[1], self.eye[2] + f[2])
        return self.eye, target, UP, FOV_Y_RAD
