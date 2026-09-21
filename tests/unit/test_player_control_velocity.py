"""_PlayerControl.apply must publish the player's world velocity via
SetVelocity so downstream systems (collisions) read an authoritative value.

Branch exercised: the f==0 inertial-drift branch, driven by patching
_get_ies to return a disabled subsystem so impulse_online_fraction == 0.
_drift_velocity is pre-seeded to (0, 5, 0); the drift branch must call
SetVelocity with that same vector before returning.
"""
import App
from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass


class _FakeKeys:
    def __getattr__(self, name):
        return -1  # unique sentinel key codes; never "pressed"/"state"


class _FakeHost:
    keys = _FakeKeys()

    def key_pressed(self, code):
        return False

    def key_state(self, code):
        return False


class _DisabledIES:
    """Stub ImpulseEngineSubsystem that is fully disabled (impulse_online_fraction == 0)."""
    def IsDisabled(self): return True
    def IsDestroyed(self): return False
    def GetNumChildSubsystems(self): return 0


def _player():
    s = ShipClass()
    s.SetTranslateXYZ(0.0, 0.0, 0.0)
    s.SetRadius(1.0)
    return s


def test_player_control_publishes_velocity_when_moving():
    """After apply on a drifting ship, GetVelocity() must return the drift vector."""
    from engine.host_loop import _PlayerControl

    pc = _PlayerControl()
    player = _player()

    # Save original _get_ies so we can restore it after the test.
    _original_get_ies = _PlayerControl.__dict__["_get_ies"]

    # Force the drift branch: patch _get_ies so impulse_online_fraction
    # returns 0.0 (master IES disabled).
    _PlayerControl._get_ies = staticmethod(lambda p: _DisabledIES())

    try:
        # Pre-seed drift velocity: 5 GU/s along world-Y (forward in identity rot).
        pc._drift_velocity = TGPoint3(0.0, 5.0, 0.0)
        pc.apply(player, 1.0 / 60.0, _FakeHost())
        v = player.GetVelocity()
        # Drift branch SetVelocity should mirror _drift_velocity exactly.
        assert v.y == 5.0, f"expected v.y==5.0, got {v.y}"
        assert v.x == 0.0 and v.z == 0.0
    finally:
        # Restore original _get_ies.
        _PlayerControl._get_ies = _original_get_ies


def test_player_control_publishes_velocity_powered_branch():
    """The everyday powered-flight path must also publish world velocity.

    A bare ShipClass has no impulse engine, so f == 1.0 (powered branch) and
    the FALLBACK ramp drives _current_speed to the commanded target in one
    tick. Override GetTargetSpeed to command 5 GU/s; identity rotation makes
    forward = +Y, so GetVelocity() must read (0, 5, 0).
    """
    from engine.host_loop import _PlayerControl

    pc = _PlayerControl()
    player = _player()
    pc.GetTargetSpeed = lambda p: 5.0  # instance override shadows the method

    pc.apply(player, 1.0 / 60.0, _FakeHost())

    v = player.GetVelocity()
    assert v.y == 5.0, f"expected v.y==5.0, got {v.y}"
    assert v.x == 0.0 and v.z == 0.0


def test_player_control_publishes_zero_velocity_when_stationary():
    """Stationary powered ship publishes a zero velocity (not a stale value)."""
    from engine.host_loop import _PlayerControl

    pc = _PlayerControl()
    player = _player()
    player.SetVelocity(TGPoint3(99.0, 99.0, 99.0))  # stale value to be overwritten
    pc.GetTargetSpeed = lambda p: 0.0

    pc.apply(player, 1.0 / 60.0, _FakeHost())

    v = player.GetVelocity()
    assert v.x == 0.0 and v.y == 0.0 and v.z == 0.0


def test_player_control_publishes_body_angular_velocity_for_collisions():
    """Live 2026-09-21 (Collision Sim): the player could pitch the saucer
    180 degrees straight through a Warbird with no contact, because manual
    flight wrote the new rotation matrix directly and never published
    ship._current_angular_velocity -- the field collisions._resolve_body
    reads for contact-point velocity (omega x r). With omega absent a
    rotating hull has zero slip: no grind, no impulse, no scuff. Translation
    (v_cm != 0) registered fine, which is why "it only collides when I fire
    the engines". Mapping is the AI-handoff one: pitch = cav.x, yaw = -cav.z,
    roll = -cav.y (see _sync_ship_integrator_from_control)."""
    from engine.host_loop import _PlayerControl

    pc = _PlayerControl()
    player = _player()

    class _HoldPitchDown(_FakeHost):
        def key_state(self, code):
            return code == pc._input_map.code("pitch_down")

    pc.apply(player, 1.0 / 60.0, _HoldPitchDown())
    assert pc._current_pitch_rate < 0.0, "fixture inert: pitch key not seen"
    cav = player.__dict__["_current_angular_velocity"]
    assert cav.x == pc._current_pitch_rate and cav.y == 0.0 and cav.z == 0.0

    # Releasing the key must zero it again (the fallback ramp is instant), or
    # a parked ship would keep "spinning" against a neighbour forever.
    pc.apply(player, 1.0 / 60.0, _FakeHost())
    cav = player.__dict__["_current_angular_velocity"]
    assert (cav.x, cav.y, cav.z) == (0.0, 0.0, 0.0)
