"""Unit tests for _PlayerControl — the keyboard → ship-transform integrator.

Uses a mock `key_reader` (duck-typed to expose key_state, key_pressed, and
a `keys` attribute) so the integration logic is testable without a real
keyboard or window."""
from engine.host_loop import _PlayerControl


class _FakeKeys:
    KEY_W = 1
    KEY_S = 2
    KEY_A = 3
    KEY_D = 4
    KEY_Q = 5
    KEY_E = 6
    KEY_R = 7
    KEY_0 = 10
    KEY_1 = 11
    KEY_2 = 12
    KEY_3 = 13
    KEY_4 = 14
    KEY_5 = 15
    KEY_6 = 16
    KEY_7 = 17
    KEY_8 = 18
    KEY_9 = 19


class _FakeKeyReader:
    """A controllable key reader. `held` is the set of currently-held keys.
    `pressed_once` is consumed on first read (for rising-edge semantics)."""
    keys = _FakeKeys()

    def __init__(self):
        self.held = set()
        self.pressed_once = set()

    def key_state(self, key):
        return key in self.held

    def key_pressed(self, key):
        if key in self.pressed_once:
            self.pressed_once.discard(key)
            return True
        return False


class _FakePoint:
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x, self.y, self.z = float(x), float(y), float(z)


class _FakeShip:
    """Minimal duck-typed ship matching the engine.appc.objects.ObjectClass
    transform API used by _PlayerControl."""
    def __init__(self):
        from engine.appc.math import TGMatrix3
        self._pos = _FakePoint(0.0, 0.0, 0.0)
        self._rot = TGMatrix3()  # identity
        self._vel = _FakePoint(0.0, 0.0, 0.0)

    def GetTranslate(self):
        return _FakePoint(self._pos.x, self._pos.y, self._pos.z)

    def SetVelocity(self, v):
        self._vel = _FakePoint(v.x, v.y, v.z)

    def GetVelocity(self):
        return _FakePoint(self._vel.x, self._vel.y, self._vel.z)

    def SetTranslateXYZ(self, x, y, z):
        self._pos = _FakePoint(x, y, z)

    def GetWorldRotation(self):
        from engine.appc.math import TGMatrix3
        out = TGMatrix3()
        out._m = [row[:] for row in self._rot._m]
        return out

    def SetMatrixRotation(self, mat):
        self._rot = mat


def test_initial_impulse_level_is_zero():
    pc = _PlayerControl()
    assert pc.impulse_level == 0


def test_digit_5_sets_forward_5():
    pc = _PlayerControl()
    ship = _FakeShip()
    reader = _FakeKeyReader()
    reader.pressed_once.add(reader.keys.KEY_5)
    pc.apply(ship, dt=1.0/60, h=reader)
    assert pc.impulse_level == 5


def test_R_sets_reverse_negative_two():
    pc = _PlayerControl()
    ship = _FakeShip()
    reader = _FakeKeyReader()
    reader.pressed_once.add(reader.keys.KEY_R)
    pc.apply(ship, dt=1.0/60, h=reader)
    assert pc.impulse_level == -2


def test_0_sets_full_stop():
    pc = _PlayerControl()
    pc.impulse_level = 7
    ship = _FakeShip()
    reader = _FakeKeyReader()
    reader.pressed_once.add(reader.keys.KEY_0)
    pc.apply(ship, dt=1.0/60, h=reader)
    assert pc.impulse_level == 0


def test_digit_after_R_returns_to_forward():
    pc = _PlayerControl()
    ship = _FakeShip()
    reader = _FakeKeyReader()
    # Press R first, then 7.
    reader.pressed_once.add(reader.keys.KEY_R)
    pc.apply(ship, dt=1.0/60, h=reader)
    assert pc.impulse_level == -2
    reader.pressed_once.add(reader.keys.KEY_7)
    pc.apply(ship, dt=1.0/60, h=reader)
    assert pc.impulse_level == 7


def test_digit_press_overrides_simultaneous_R_press():
    """If R and 1-9 both fire on the same frame (unlikely but possible),
    R is checked first, then digits — so R wins. Document this semantic."""
    pc = _PlayerControl()
    ship = _FakeShip()
    reader = _FakeKeyReader()
    reader.pressed_once.add(reader.keys.KEY_R)
    reader.pressed_once.add(reader.keys.KEY_5)
    pc.apply(ship, dt=1.0/60, h=reader)
    assert pc.impulse_level == -2  # R won


def test_no_input_no_rotation():
    """With no keys held, rotation stays at identity across many ticks."""
    pc = _PlayerControl()
    ship = _FakeShip()
    reader = _FakeKeyReader()
    initial = ship.GetWorldRotation()
    for _ in range(120):
        pc.apply(ship, dt=1.0/60, h=reader)
    final = ship.GetWorldRotation()
    for r in range(3):
        for c in range(3):
            assert abs(final._m[r][c] - initial._m[r][c]) < 1e-9


def test_pitch_down_rotates_forward_below_horizontal():
    """Hold W (pitch down) for one second of dt at 60Hz. The ship's
    forward vector (col 1 of the column-vector rotation matrix; see
    CLAUDE.md) should pitch down from +Y toward -Z by 1.5 radians
    (one second × 1.5 rad/s)."""
    import math
    pc = _PlayerControl()
    ship = _FakeShip()
    reader = _FakeKeyReader()
    reader.held.add(reader.keys.KEY_W)
    for _ in range(60):
        pc.apply(ship, dt=1.0/60, h=reader)
    forward = ship.GetWorldRotation().GetCol(1)
    # After pitching down 1.5 rad: forward.y = cos(1.5), forward.z = -sin(1.5)
    expected_y = math.cos(1.5)
    expected_z = -math.sin(1.5)
    assert abs(forward.x) < 1e-3
    assert abs(forward.y - expected_y) < 1e-3, f"forward.y={forward.y}, expected {expected_y}"
    assert abs(forward.z - expected_z) < 1e-3, f"forward.z={forward.z}, expected {expected_z}"


def test_pitch_up_rotates_forward_above_horizontal():
    """Hold S (pitch up) for one second. Forward should rotate up by
    +1.5 rad (toward +Z)."""
    import math
    pc = _PlayerControl()
    ship = _FakeShip()
    reader = _FakeKeyReader()
    reader.held.add(reader.keys.KEY_S)
    for _ in range(60):
        pc.apply(ship, dt=1.0/60, h=reader)
    forward = ship.GetWorldRotation().GetCol(1)
    expected_y = math.cos(1.5)
    expected_z = math.sin(1.5)
    assert abs(forward.y - expected_y) < 1e-3
    assert abs(forward.z - expected_z) < 1e-3


def test_yaw_d_rotates_forward_toward_plus_x():
    """Hold D for one second. D produces +yaw_rate, which _apply_body_rotation
    NEGATES (right-handed un-mirror, 2026-06-18), so forward rotates around
    world Z by -1.5 rad: from +Y toward +X (nose swings to starboard)."""
    import math
    pc = _PlayerControl()
    ship = _FakeShip()
    reader = _FakeKeyReader()
    reader.held.add(reader.keys.KEY_D)
    for _ in range(60):
        pc.apply(ship, dt=1.0/60, h=reader)
    forward = ship.GetWorldRotation().GetCol(1)
    expected_x = math.sin(1.5)
    expected_y = math.cos(1.5)
    assert abs(forward.x - expected_x) < 1e-3, f"forward.x={forward.x}, expected {expected_x}"
    assert abs(forward.y - expected_y) < 1e-3
    assert abs(forward.z) < 1e-3


def test_no_throttle_no_movement():
    pc = _PlayerControl()
    ship = _FakeShip()
    reader = _FakeKeyReader()
    for _ in range(60):
        pc.apply(ship, dt=1.0/60, h=reader)
    p = ship.GetTranslate()
    assert abs(p.x) < 1e-9
    assert abs(p.y) < 1e-9
    assert abs(p.z) < 1e-9


def test_impulse_5_advances_along_world_y_at_identity():
    """At identity rotation, forward = +Y. After 1.0s at impulse 5,
    position should be (0, 5 * IMPULSE_UNIT * 1.0, 0) = (0, 250, 0)."""
    pc = _PlayerControl()
    ship = _FakeShip()
    reader = _FakeKeyReader()
    reader.pressed_once.add(reader.keys.KEY_5)
    for _ in range(60):
        pc.apply(ship, dt=1.0/60, h=reader)
    p = ship.GetTranslate()
    assert abs(p.x) < 1e-3
    assert abs(p.y - 250.0) < 1e-1, f"p.y={p.y}, expected ~250.0"
    assert abs(p.z) < 1e-3


def test_reverse_advances_negative_along_world_y():
    """R sets level=-2. After 1.0s, position is (0, -100, 0)."""
    pc = _PlayerControl()
    ship = _FakeShip()
    reader = _FakeKeyReader()
    reader.pressed_once.add(reader.keys.KEY_R)
    for _ in range(60):
        pc.apply(ship, dt=1.0/60, h=reader)
    p = ship.GetTranslate()
    assert abs(p.y - (-100.0)) < 1e-1, f"p.y={p.y}, expected ~-100.0"


def test_full_stop_after_movement_stops_advancement():
    """Set impulse 5, run 30 frames, set 0, run 30 more. Position
    advances during the first 30, stays put for the next 30."""
    pc = _PlayerControl()
    ship = _FakeShip()
    reader = _FakeKeyReader()
    reader.pressed_once.add(reader.keys.KEY_5)
    for _ in range(30):
        pc.apply(ship, dt=1.0/60, h=reader)
    pos_after_first_half = ship.GetTranslate()
    assert pos_after_first_half.y > 0
    reader.pressed_once.add(reader.keys.KEY_0)
    for _ in range(30):
        pc.apply(ship, dt=1.0/60, h=reader)
    pos_after_second_half = ship.GetTranslate()
    assert abs(pos_after_second_half.y - pos_after_first_half.y) < 1e-3


def test_roll_e_rotates_up_toward_plus_x():
    """Hold E for one second at identity start. Roll is around ship-Y (forward
    axis). E produces -roll_rate, which _apply_body_rotation NEGATES (right-
    handed un-mirror), so up (col 2) starts at +Z and rolls toward +X."""
    import math
    pc = _PlayerControl()
    ship = _FakeShip()
    reader = _FakeKeyReader()
    reader.held.add(reader.keys.KEY_E)
    for _ in range(60):
        pc.apply(ship, dt=1.0/60, h=reader)
    up = ship.GetWorldRotation().GetCol(2)
    expected_x = math.sin(1.5)
    expected_z = math.cos(1.5)
    assert abs(up.x - expected_x) < 1e-3, f"up.x={up.x}, expected {expected_x}"
    assert abs(up.y) < 1e-3
    assert abs(up.z - expected_z) < 1e-3


def test_roll_after_yaw_is_body_frame_not_world():
    """Regression: after yawing 90° left, holding Q must roll around the
    ship's own forward axis (now world -X), not around world +Y. Under a
    body-frame integrator the forward vector is invariant under roll, so
    after rolling for one second the forward axis still points along -X.

    Under a (buggy) world-frame integrator, Q rolls around world +Y, which
    *does* rotate the -X forward vector and tilts it toward -Z — the bug
    the user describes ("roll acts like pitch after yaw")."""
    import math
    from engine.appc.math import TGMatrix3, TGPoint3
    pc = _PlayerControl()
    ship = _FakeShip()
    reader = _FakeKeyReader()

    # Pre-yaw the ship 90° left so forward = -X. Under col-vector
    # convention (see CLAUDE.md) MakeRotation(+π/2, +Z) maps body-Y to
    # world-(-X) — that's a left yaw.
    R_yaw90 = TGMatrix3()
    R_yaw90.MakeRotation(math.pi / 2, TGPoint3(0.0, 0.0, 1.0))
    ship.SetMatrixRotation(R_yaw90)
    fwd0 = ship.GetWorldRotation().GetCol(1)
    assert abs(fwd0.x - (-1.0)) < 1e-9, "precondition: forward should be -X after 90° left yaw"
    assert abs(fwd0.y) < 1e-9
    assert abs(fwd0.z) < 1e-9

    # Now hold Q (roll) for one second.
    reader.held.add(reader.keys.KEY_Q)
    for _ in range(60):
        pc.apply(ship, dt=1.0/60, h=reader)

    # Roll about ship-forward leaves the forward axis invariant.
    fwd = ship.GetWorldRotation().GetCol(1)
    assert abs(fwd.x - (-1.0)) < 1e-3, f"forward.x={fwd.x}, expected -1.0 (roll must not change forward)"
    assert abs(fwd.y) < 1e-3, f"forward.y={fwd.y}, expected 0"
    assert abs(fwd.z) < 1e-3, f"forward.z={fwd.z}, expected 0 (this is the bug: world-frame roll tilts forward toward -Z)"

    # And the up vector must rotate in the world Y-Z plane (around -X),
    # not in the X-Z plane (which would be world-frame roll around +Y).
    up = ship.GetWorldRotation().GetCol(2)
    assert abs(up.x) < 1e-3, f"up.x={up.x}, expected 0 (up should stay in Y-Z plane under body roll about -X)"
