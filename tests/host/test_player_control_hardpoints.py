"""_PlayerControl reads MaxSpeed/MaxAccel/MaxAngularVelocity from the ship's
ImpulseEngineSubsystem (populated by SetupProperties from the hardpoint).

When the ship has no IES or MaxSpeed=0, the integrator falls back to legacy
constants (IMPULSE_UNIT and TURN_RATE_RAD_PER_S) so existing fake-ship tests
keep working.
"""
from engine.host_loop import _PlayerControl
from engine.appc.ships import ShipClass_Create


class _Keys:
    # Real GLFW key codes — _PlayerControl reads flight/reverse/full-stop keys
    # via InputMap (GLFW ints), so the fake must match.
    KEY_W = 87; KEY_S = 83; KEY_A = 65; KEY_D = 68; KEY_Q = 81; KEY_E = 69
    KEY_R = 82
    KEY_0 = 48; KEY_1 = 49; KEY_2 = 50; KEY_3 = 51; KEY_4 = 52
    KEY_5 = 53; KEY_6 = 54; KEY_7 = 55; KEY_8 = 56; KEY_9 = 57


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


# ── Engine power slider: commanded speed scales with the REQUESTED power ─────
#
# BC's ImpulseEngineSubsystem::GetMaxSpeed multiplies by the slider fraction
# (+0x90, GetPowerPercentageWanted) — not by received/normal power. See
# subsystems.impulse_output_fraction.

def test_boost_power_raises_commanded_speed():
    """At the slider's 125 % ceiling, level-9 throttle targets 1.25 × MaxSpeed.

    BC manual: >100 % engine power raises max impulse speed.  Before the fix,
    GetTargetSpeed returned (lvl/9) × raw_max (no power term at all), so
    boosting the cap never translated into a higher command and the ship was
    capped at the authored MaxSpeed.
    """
    pc = _PlayerControl()
    ship = _galaxy_like_ship()
    ies = ship.GetImpulseEngineSubsystem()
    ies.SetPowerPercentageWanted(1.25)          # 125 % engine power
    reader = _Reader()
    reader.pressed_once.add(reader.keys.KEY_9)
    pc.apply(ship, dt=1.0/60, h=reader)
    assert abs(pc.GetTargetSpeed(ship) - 6.3 * 1.25) < 1e-9, (
        f"Expected {6.3*1.25}, got {pc.GetTargetSpeed(ship)}"
    )


def test_reduced_power_lowers_commanded_speed():
    """At 50 % engine power, level-9 throttle targets 0.5 × MaxSpeed.

    Ensures the power term is applied symmetrically in both directions.
    """
    pc = _PlayerControl()
    ship = _galaxy_like_ship()
    ies = ship.GetImpulseEngineSubsystem()
    ies.SetPowerPercentageWanted(0.5)
    reader = _Reader()
    reader.pressed_once.add(reader.keys.KEY_9)
    pc.apply(ship, dt=1.0/60, h=reader)
    assert abs(pc.GetTargetSpeed(ship) - 6.3 * 0.5) < 1e-9, (
        f"Expected {6.3*0.5}, got {pc.GetTargetSpeed(ship)}"
    )


def test_normal_power_unchanged():
    """At exactly 100 % power the commanded speed is unchanged (regression guard)."""
    pc = _PlayerControl()
    ship = _galaxy_like_ship()
    ies = ship.GetImpulseEngineSubsystem()
    ies.SetPowerPercentageWanted(1.0)
    reader = _Reader()
    reader.pressed_once.add(reader.keys.KEY_9)
    pc.apply(ship, dt=1.0/60, h=reader)
    assert abs(pc.GetTargetSpeed(ship) - 6.3) < 1e-9


def test_boost_power_converges_above_raw_max_speed():
    """With 125 % power the ship actually reaches 1.25 × MaxSpeed after
    sufficient time (not just the command — the integrated speed must exceed
    raw MaxSpeed).
    """
    pc = _PlayerControl()
    ship = _galaxy_like_ship()   # MaxSpeed=6.3, MaxAccel=1.5
    ies = ship.GetImpulseEngineSubsystem()
    ies.SetPowerPercentageWanted(1.25)
    reader = _Reader()
    reader.pressed_once.add(reader.keys.KEY_9)
    for _ in range(60 * 30):   # 30 s — well past convergence
        pc.apply(ship, dt=1.0/60, h=reader)
    assert abs(pc.GetCurrentSpeed() - 6.3 * 1.25) < 1e-2, (
        f"Expected {6.3*1.25:.3f}, got {pc.GetCurrentSpeed():.3f}"
    )


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
    # 10 s = ~6.8τ after the linear-phase crossover (BC_IMPULSE_TAU = 1 s
    # asymptotic approach), so the residual gap is exp(-6.8)·MaxAccel·τ
    # ≈ 0.0017 GU/s. Tolerance accounts for the asymptotic tail.
    assert abs(speed_before - 6.3) < 5e-3
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
    """Holding W long enough — pitch rate (signed) caps at the cap
    magnitude.  W produces a negative pitch_rate under the column-vector
    convention (see CLAUDE.md): MakeXRotation(-rate*dt) pitches the nose
    down."""
    pc = _PlayerControl()
    ship = _galaxy_like_ship()  # MaxAngularVelocity=0.28, MaxAngularAccel=0.12
    reader = _Reader()
    reader.held.add(reader.keys.KEY_W)
    for _ in range(60 * 30):
        pc.apply(ship, dt=1.0/60, h=reader)
    assert abs(pc.GetCurrentPitchRate() - (-0.28)) < 1e-3


def test_held_D_yaw_rate_saturates_at_negative_max_angular_velocity():
    """D = yaw left.  Under column-vector convention (see CLAUDE.md),
    D drives yaw_target to +MaxAngularVelocity so MakeZRotation(+rate*dt)
    yaws the forward axis toward -X."""
    pc = _PlayerControl()
    ship = _galaxy_like_ship()
    reader = _Reader()
    reader.held.add(reader.keys.KEY_D)
    for _ in range(60 * 30):
        pc.apply(ship, dt=1.0/60, h=reader)
    assert abs(pc.GetCurrentYawRate() - 0.28) < 1e-3


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
    After 1.0 s the yaw rate magnitude is 0.12 rad/s (still below cap).
    A produces negative yaw_rate under the column-vector convention
    (see CLAUDE.md): MakeZRotation(-rate*dt) yaws toward +X (right)."""
    pc = _PlayerControl()
    ship = _galaxy_like_ship()
    reader = _Reader()
    reader.held.add(reader.keys.KEY_A)
    for _ in range(60):
        pc.apply(ship, dt=1.0/60, h=reader)
    assert abs(pc.GetCurrentYawRate() - (-0.12)) < 1e-3


def test_yaw_rate_caps_at_max_angular_velocity():
    """Hold A long enough — yaw rate converges to -MaxAngularVelocity."""
    pc = _PlayerControl()
    ship = _galaxy_like_ship()
    reader = _Reader()
    reader.held.add(reader.keys.KEY_A)
    for _ in range(60 * 30):  # 30 seconds
        pc.apply(ship, dt=1.0/60, h=reader)
    assert abs(pc.GetCurrentYawRate() - (-0.28)) < 1e-3


def test_pitch_rate_ramps_positive_for_S():
    """S = pitch up = +ang_rate target under the column-vector
    convention (see CLAUDE.md).  After 1.0 s, pitch rate = +0.12."""
    pc = _PlayerControl()
    ship = _galaxy_like_ship()
    reader = _Reader()
    reader.held.add(reader.keys.KEY_S)
    for _ in range(60):
        pc.apply(ship, dt=1.0/60, h=reader)
    assert abs(pc.GetCurrentPitchRate() - 0.12) < 1e-3


def test_angular_rate_decelerates_on_key_release():
    """Spin up yaw rate (negative under A; see test_yaw_rate_ramps_*),
    release A — yaw rate ramps back toward 0 at MaxAngularAccel.
    Halfway through the decel ramp, magnitude has dropped by 0.12."""
    pc = _PlayerControl()
    ship = _galaxy_like_ship()
    reader = _Reader()
    reader.held.add(reader.keys.KEY_A)
    for _ in range(60 * 5):  # 5 s — well past the cap
        pc.apply(ship, dt=1.0/60, h=reader)
    rate_before = pc.GetCurrentYawRate()
    assert abs(rate_before - (-0.28)) < 1e-3
    reader.held.discard(reader.keys.KEY_A)
    for _ in range(60):  # 1.0 s of decel — magnitude 0.28 → 0.16
        pc.apply(ship, dt=1.0/60, h=reader)
    rate_after = pc.GetCurrentYawRate()
    assert abs(rate_after - (-0.16)) < 1e-3, f"rate_after={rate_after}"


def test_speed_ramp_matches_bc_shuttle_curve():
    """Ground-truth from the original BC: holding impulse 9 on a Shuttle
    from rest, instrumented speeds at each whole second (measured 2026-06-03).

    Implies dv/dt = min(MaxAccel, (MaxSpeed - v) / τ) with τ = 1 s — see
    docs/gap_analysis.md (impulse curve fit). For Shuttle (MaxSpeed=4.0,
    MaxAccel=2.5) the crossover is at v* = 1.5 GU/s reached at t=0.6 s;
    after that the velocity gap to MaxSpeed decays with τ=1 s.

    Speeds are stored as kph (what the helm tooltip shows) so the
    assertion failure message matches the measured-value table.
    """
    pc = _PlayerControl()
    ship = ShipClass_Create("Shuttle")
    ies = ship.GetImpulseEngineSubsystem()
    ies.SetMaxSpeed(4.0)
    ies.SetMaxAccel(2.5)
    reader = _Reader()
    reader.pressed_once.add(reader.keys.KEY_9)

    expected_kph = {1: 1463, 2: 2137, 3: 2379, 4: 2469,
                    5: 2501, 6: 2513, 7: 2517, 8: 2519}

    seen_kph = {}
    for tick in range(1, 60 * 8 + 1):
        pc.apply(ship, dt=1.0 / 60.0, h=reader)
        if tick % 60 == 0:
            seen_kph[tick // 60] = pc.GetCurrentSpeed() * 630.0

    for sec, want in expected_kph.items():
        got = seen_kph[sec]
        # 1% relative tolerance, 15 kph floor for the early samples where
        # a single tick of timing drift dominates.
        tol = max(15.0, want * 0.01)
        assert abs(got - want) <= tol, (
            f"t={sec}s: BC measured {want} kph, integrator gave {got:.1f} kph"
        )


def test_rotation_integrates_ramped_angular_rate():
    """Hold D from rest with MaxAngularVelocity=0.28, MaxAngularAccel=0.12.
    Over 1.0 s, ship's heading rotates by ∫(yaw_rate dt) = 0.06 rad. D produces
    +yaw_rate, which _apply_body_rotation NEGATES (right-handed un-mirror), so
    MakeZRotation(-0.06).GetCol(1) gives forward = (+sin 0.06, cos 0.06, 0) —
    nose swings toward starboard (+X)."""
    import math
    pc = _PlayerControl()
    ship = _galaxy_like_ship()
    reader = _Reader()
    reader.held.add(reader.keys.KEY_D)
    for _ in range(60):
        pc.apply(ship, dt=1.0/60, h=reader)
    forward = ship.GetWorldRotation().GetCol(1)
    expected_x = math.sin(0.06)
    expected_y = math.cos(0.06)
    assert abs(forward.x - expected_x) < 1e-3, f"forward.x={forward.x}"
    assert abs(forward.y - expected_y) < 1e-3, f"forward.y={forward.y}"
