"""Camera shake — energy pool + decaying-noise perturbation.

Energy accumulates via apply_kick(damage), decays each tick via
update(dt), and produces a per-tick (yaw, pitch, lateral) perturbation
via perturb(eye, target, up). Up vector is left unchanged to keep the
horizon stable.

Waveform: sum of two incommensurate sinusoids per axis. Deterministic
(no RNG), reset()-able.

Tuning constants (spec §5.2):
    DAMAGE_PER_UNIT_ENERGY = 50.0     100 damage → 2.0 energy
    MAX_KICK_ENERGY        = 4.0      single-hit ceiling
    MAX_ENERGY             = 8.0      sustained-fire ceiling
    TAU                    = 0.15s    decay time constant
    ANGULAR_GAIN           = 0.013    rad per energy unit (~0.75°)
    LATERAL_GAIN           = 0.03     world units per energy unit
"""
import math


DAMAGE_PER_UNIT_ENERGY = 50.0
MAX_KICK_ENERGY        = 4.0
MAX_ENERGY             = 8.0
TAU                    = 0.15
ANGULAR_GAIN           = 0.013
LATERAL_GAIN           = 0.03


_energy: float = 0.0
_phase:  float = 0.0


def reset() -> None:
    """Zero the energy pool and the phase accumulator. Called by tests
    and by host_loop on view-mode transitions."""
    global _energy, _phase
    _energy = 0.0
    _phase = 0.0


def get_energy() -> float:
    """Introspection for tests."""
    return _energy


def apply_kick(damage: float) -> None:
    """Inject energy proportional to `damage`. Clamped per-hit to
    MAX_KICK_ENERGY; cumulative energy clamped to MAX_ENERGY."""
    global _energy
    if damage <= 0.0:
        return
    delta = min(damage / DAMAGE_PER_UNIT_ENERGY, MAX_KICK_ENERGY)
    _energy = min(_energy + delta, MAX_ENERGY)


def update(dt: float) -> None:
    """Exponential decay of energy; advance phase by dt."""
    global _energy, _phase
    if dt <= 0.0:
        return
    _energy *= math.exp(-dt / TAU)
    _phase += dt


def perturb(eye, target, up):
    """Apply yaw + pitch rotation to (target - eye) and a small lateral
    eye-translation along the camera-right axis. `up` is returned
    unchanged.

    Returns a fresh (eye, target, up) tuple-of-tuples.

    No-op when _energy == 0.0 (within float precision).
    """
    if _energy <= 1e-9:
        return eye, target, up

    amp = ANGULAR_GAIN * _energy
    yaw   = amp * (math.sin(_phase * 47.1)         + 0.5 * math.sin(_phase * 113.7 + 1.3))
    pitch = amp * (math.sin(_phase * 59.3 + 0.7)   + 0.5 * math.sin(_phase *  91.1 + 2.1))
    lateral_offset = LATERAL_GAIN * _energy * math.sin(_phase * 31.5)

    # Build basis: forward = normalize(target - eye), right = normalize(forward × up).
    fx = target[0] - eye[0]
    fy = target[1] - eye[1]
    fz = target[2] - eye[2]
    flen = math.sqrt(fx*fx + fy*fy + fz*fz)
    if flen < 1e-9:
        return eye, target, up
    fx, fy, fz = fx / flen, fy / flen, fz / flen
    # right = forward × up
    rx = fy * up[2] - fz * up[1]
    ry = fz * up[0] - fx * up[2]
    rz = fx * up[1] - fy * up[0]
    rlen = math.sqrt(rx*rx + ry*ry + rz*rz)
    if rlen < 1e-9:
        return eye, target, up
    rx, ry, rz = rx / rlen, ry / rlen, rz / rlen

    # Rotate forward vector by yaw around up, then by pitch around right.
    cy, sy = math.cos(yaw), math.sin(yaw)
    cp, sp = math.cos(pitch), math.sin(pitch)

    # Yaw rotation around `up` axis. r = forward × up, so up × forward = -r;
    # Rodrigues' formula gives v' = v cos + (axis × v) sin, hence the -r term.
    f2x = fx * cy - rx * sy
    f2y = fy * cy - ry * sy
    f2z = fz * cy - rz * sy
    # Pitch around the pre-yaw right axis. For sub-3° shakes the
    # O(yaw²) error from not recomputing right post-yaw is negligible.
    # forward' = forward * cos(pitch) + up * sin(pitch)
    f3x = f2x * cp + up[0] * sp
    f3y = f2y * cp + up[1] * sp
    f3z = f2z * cp + up[2] * sp

    # Restore length (rotation is length-preserving in theory; numerical
    # cleanup so callers don't accumulate drift).
    new_target = (
        eye[0] + f3x * flen,
        eye[1] + f3y * flen,
        eye[2] + f3z * flen,
    )
    new_eye = (
        eye[0] + rx * lateral_offset,
        eye[1] + ry * lateral_offset,
        eye[2] + rz * lateral_offset,
    )
    # Shift target by same lateral offset so the look direction stays roughly fixed
    # relative to the lateral rumble (otherwise we'd swing wildly).
    new_target = (
        new_target[0] + rx * lateral_offset,
        new_target[1] + ry * lateral_offset,
        new_target[2] + rz * lateral_offset,
    )
    return new_eye, new_target, up
