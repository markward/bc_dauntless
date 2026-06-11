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
