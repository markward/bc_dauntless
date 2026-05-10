"""_PlayerControl reads MaxSpeed/MaxAccel/MaxAngularVelocity from the ship's
ImpulseEngineSubsystem (populated by SetupProperties from the hardpoint).

When the ship has no IES or MaxSpeed=0, the integrator falls back to legacy
constants (IMPULSE_UNIT and TURN_RATE_RAD_PER_S) so existing fake-ship tests
keep working.
"""
from engine.host_loop import _PlayerControl
from engine.appc.ships import ShipClass_Create


class _Keys:
    KEY_W = 1; KEY_S = 2; KEY_A = 3; KEY_D = 4; KEY_Q = 5; KEY_E = 6
    KEY_R = 7
    KEY_0 = 10; KEY_1 = 11; KEY_2 = 12; KEY_3 = 13; KEY_4 = 14
    KEY_5 = 15; KEY_6 = 16; KEY_7 = 17; KEY_8 = 18; KEY_9 = 19


class _Reader:
    keys = _Keys()
    def __init__(self):
        self.held = set()
        self.pressed_once = set()
    def key_state(self, key): return key in self.held
    def key_pressed(self, key):
        if key in self.pressed_once:
            self.pressed_once.discard(key); return True
        return False


def _galaxy_like_ship():
    """A ShipClass with a populated ImpulseEngineSubsystem (Galaxy values).

    Bypasses the hardpoint pipeline by setting the live subsystem fields
    directly so the test isolates _PlayerControl's behaviour from
    SetupProperties' wiring.
    """
    ship = ShipClass_Create("Galaxy")
    ies = ship.GetImpulseEngineSubsystem()
    ies.SetMaxSpeed(6.3)
    ies.SetMaxAccel(1.5)
    ies.SetMaxAngularVelocity(0.28)
    ies.SetMaxAngularAccel(0.12)
    return ship


# ── Throttle target speed ─────────────────────────────────────────────────────

def test_throttle_level_9_targets_max_speed():
    pc = _PlayerControl()
    ship = _galaxy_like_ship()
    reader = _Reader()
    reader.pressed_once.add(reader.keys.KEY_9)
    pc.apply(ship, dt=1.0/60, h=reader)
    assert pc.GetTargetSpeed(ship) == 6.3


def test_throttle_level_5_targets_five_ninths_max_speed():
    pc = _PlayerControl()
    ship = _galaxy_like_ship()
    reader = _Reader()
    reader.pressed_once.add(reader.keys.KEY_5)
    pc.apply(ship, dt=1.0/60, h=reader)
    assert abs(pc.GetTargetSpeed(ship) - (5.0 / 9.0) * 6.3) < 1e-9


def test_reverse_targets_negative_quarter_max_speed():
    pc = _PlayerControl()
    ship = _galaxy_like_ship()
    reader = _Reader()
    reader.pressed_once.add(reader.keys.KEY_R)
    pc.apply(ship, dt=1.0/60, h=reader)
    assert abs(pc.GetTargetSpeed(ship) - (-0.25 * 6.3)) < 1e-9


def test_zero_targets_zero():
    pc = _PlayerControl()
    ship = _galaxy_like_ship()
    reader = _Reader()
    reader.pressed_once.add(reader.keys.KEY_5)
    pc.apply(ship, dt=1.0/60, h=reader)
    reader.pressed_once.add(reader.keys.KEY_0)
    pc.apply(ship, dt=1.0/60, h=reader)
    assert pc.GetTargetSpeed(ship) == 0.0


# ── Speed ramps at MaxAccel ───────────────────────────────────────────────────

def test_speed_ramps_at_max_accel_from_rest():
    """At level 9 from rest, after 1.0 s the integrated speed is MaxAccel
    (not MaxSpeed) — assuming MaxSpeed > MaxAccel * 1.0."""
    pc = _PlayerControl()
    ship = _galaxy_like_ship()  # MaxSpeed=6.3, MaxAccel=1.5
    reader = _Reader()
    reader.pressed_once.add(reader.keys.KEY_9)
    for _ in range(60):
        pc.apply(ship, dt=1.0/60, h=reader)
    # speed ramps from 0 toward MaxSpeed at MaxAccel rate.  After 1.0 s,
    # current speed = min(MaxSpeed, 1.0 * MaxAccel) = 1.5.
    assert abs(pc.GetCurrentSpeed() - 1.5) < 1e-3


def test_speed_caps_at_target_speed():
    """After enough time, current speed converges to target — no overshoot."""
    pc = _PlayerControl()
    ship = _galaxy_like_ship()
    reader = _Reader()
    reader.pressed_once.add(reader.keys.KEY_9)
    for _ in range(60 * 30):  # 30 seconds — way more than needed
        pc.apply(ship, dt=1.0/60, h=reader)
    assert abs(pc.GetCurrentSpeed() - 6.3) < 1e-3


def test_speed_decelerates_toward_zero_on_full_stop():
    """After reaching speed and then pressing 0, speed ramps down toward 0
    at MaxAccel rate (still positive during the deceleration window)."""
    pc = _PlayerControl()
    ship = _galaxy_like_ship()
    reader = _Reader()
    reader.pressed_once.add(reader.keys.KEY_9)
    for _ in range(60 * 10):
        pc.apply(ship, dt=1.0/60, h=reader)
    speed_before = pc.GetCurrentSpeed()
    assert abs(speed_before - 6.3) < 1e-3
    reader.pressed_once.add(reader.keys.KEY_0)
    pc.apply(ship, dt=1.0/60, h=reader)  # one tick into deceleration
    for _ in range(30):
        pc.apply(ship, dt=1.0/60, h=reader)
    speed_after = pc.GetCurrentSpeed()
    # After ~0.5 s of decel at 1.5 units/s², speed = 6.3 - 0.75 = ~5.55
    assert speed_after < speed_before
    assert speed_after > 0.0


# ── Angular rate uses MaxAngularVelocity ──────────────────────────────────────

def test_held_W_pitch_rate_saturates_at_max_angular_velocity():
    """Holding W long enough — pitch rate caps at MaxAngularVelocity, not past."""
    pc = _PlayerControl()
    ship = _galaxy_like_ship()  # MaxAngularVelocity=0.28, MaxAngularAccel=0.12
    reader = _Reader()
    reader.held.add(reader.keys.KEY_W)
    for _ in range(60 * 30):
        pc.apply(ship, dt=1.0/60, h=reader)
    assert abs(pc.GetCurrentPitchRate() - 0.28) < 1e-3


def test_held_D_yaw_rate_saturates_at_negative_max_angular_velocity():
    """D = yaw left = -MaxAngularVelocity target.  Cap is symmetric."""
    pc = _PlayerControl()
    ship = _galaxy_like_ship()
    reader = _Reader()
    reader.held.add(reader.keys.KEY_D)
    for _ in range(60 * 30):
        pc.apply(ship, dt=1.0/60, h=reader)
    assert abs(pc.GetCurrentYawRate() - (-0.28)) < 1e-3


# ── Movement uses ramped speed in ship-forward direction ──────────────────────

def test_movement_uses_ramped_current_speed_along_forward():
    """Position integration uses the per-frame current_speed, not
    target_speed — so during the ramp the ship covers less ground than a
    constant-speed model would."""
    pc = _PlayerControl()
    ship = _galaxy_like_ship()  # MaxSpeed=6.3, MaxAccel=1.5
    reader = _Reader()
    reader.pressed_once.add(reader.keys.KEY_9)
    for _ in range(60):
        pc.apply(ship, dt=1.0/60, h=reader)
    p = ship.GetTranslate()
    # During 1.0 s ramp at MaxAccel, distance ≈ 0.5 * a * t² = 0.5 * 1.5 * 1 = 0.75.
    # Allow a small tolerance for discrete-time integration (Euler) drift.
    assert 0.7 < p.y < 0.85, f"p.y={p.y}, expected ~0.75"
    assert abs(p.x) < 1e-6
    assert abs(p.z) < 1e-6


# ── Angular rates ramp at MaxAngularAccel ─────────────────────────────────────
# Symmetric to the linear-speed model: each held turn key sets a target rate,
# and the current rate accelerates toward it at MaxAngularAccel rad/s².

def test_yaw_rate_ramps_at_max_angular_accel_from_rest():
    """Hold A from rest with MaxAngularVelocity=0.28, MaxAngularAccel=0.12.
    After 1.0 s the yaw rate is 0.12 rad/s (still below the cap)."""
    pc = _PlayerControl()
    ship = _galaxy_like_ship()
    reader = _Reader()
    reader.held.add(reader.keys.KEY_A)
    for _ in range(60):
        pc.apply(ship, dt=1.0/60, h=reader)
    assert abs(pc.GetCurrentYawRate() - 0.12) < 1e-3


def test_yaw_rate_caps_at_max_angular_velocity():
    """Hold A long enough — yaw rate converges to MaxAngularVelocity, not past."""
    pc = _PlayerControl()
    ship = _galaxy_like_ship()
    reader = _Reader()
    reader.held.add(reader.keys.KEY_A)
    for _ in range(60 * 30):  # 30 seconds
        pc.apply(ship, dt=1.0/60, h=reader)
    assert abs(pc.GetCurrentYawRate() - 0.28) < 1e-3


def test_pitch_rate_ramps_negative_for_S():
    """S = pitch up = -ang_rate target.  After 1.0 s, pitch rate = -0.12."""
    pc = _PlayerControl()
    ship = _galaxy_like_ship()
    reader = _Reader()
    reader.held.add(reader.keys.KEY_S)
    for _ in range(60):
        pc.apply(ship, dt=1.0/60, h=reader)
    assert abs(pc.GetCurrentPitchRate() - (-0.12)) < 1e-3


def test_angular_rate_decelerates_on_key_release():
    """Spin up yaw rate, release A — yaw rate ramps back toward 0 at
    MaxAngularAccel.  Halfway through the decel ramp, rate is still positive."""
    pc = _PlayerControl()
    ship = _galaxy_like_ship()
    reader = _Reader()
    reader.held.add(reader.keys.KEY_A)
    for _ in range(60 * 5):  # 5 s — well past the cap
        pc.apply(ship, dt=1.0/60, h=reader)
    rate_before = pc.GetCurrentYawRate()
    assert abs(rate_before - 0.28) < 1e-3
    reader.held.discard(reader.keys.KEY_A)
    for _ in range(60):  # 1.0 s of decel — 0.28 - 0.12 = 0.16 rad/s expected
        pc.apply(ship, dt=1.0/60, h=reader)
    rate_after = pc.GetCurrentYawRate()
    assert abs(rate_after - 0.16) < 1e-3, f"rate_after={rate_after}"


def test_rotation_integrates_ramped_angular_rate():
    """Hold D from rest with MaxAngularVelocity=0.28, MaxAngularAccel=0.12.
    Over 1.0 s, ship's heading rotates by ∫(yaw_rate dt) = 0.5*0.12*1² = 0.06 rad."""
    import math
    pc = _PlayerControl()
    ship = _galaxy_like_ship()
    reader = _Reader()
    reader.held.add(reader.keys.KEY_D)
    for _ in range(60):
        pc.apply(ship, dt=1.0/60, h=reader)
    forward = ship.GetWorldRotation().GetRow(1)
    expected_x = -math.sin(0.06)
    expected_y = math.cos(0.06)
    assert abs(forward.x - expected_x) < 1e-3, f"forward.x={forward.x}"
    assert abs(forward.y - expected_y) < 1e-3, f"forward.y={forward.y}"
