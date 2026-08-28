"""Per-tick paths resolve their subsystem helpers from module globals.

`from engine.appc.subsystems import ...` inside a function that runs once per
ship per tick is not free: it is a sys.modules lookup plus an attribute fetch
on every call. This branch already deleted one such import from
subsystems._is_offline, where it cost 115,279 importlib lookups over 150 ticks
at 100 ships; these are the two survivors on the same cadence.

A monkeypatch on the MODULE GLOBAL is the honest probe. If the name is
resolved by a function-local import, patching the module attribute changes
nothing — the import re-fetches the real function from engine.appc.subsystems
and the sentinel is never seen. So "the patch takes effect" is exactly the
property "the name is a module global", tested through behaviour rather than
by grepping the source.
"""
import pytest

from engine.appc import ship_motion, ships
from engine.appc.math import TGPoint3
from engine.appc.objects import PhysicsObjectClass
from engine.appc.subsystems import ImpulseEngineSubsystem


def test_turn_solver_reads_impulse_output_fraction_from_module_scope(monkeypatch):
    """ShipClass.TurnDirectionsToDirections' braking cap. AI.TurnToOrientation
    drives this every 0.5 s per turning ship."""
    ship = ships.ShipClass()
    ship.SetImpulseEngineSubsystem(ImpulseEngineSubsystem("Impulse Engines"))
    ies = ship.GetImpulseEngineSubsystem()
    ies.SetMaxAngularVelocity(0.5)
    ies.SetMaxAngularAccel(1.0)
    ies.SetMaxSpeed(100.0)
    ies.SetMaxAccel(10.0)

    seen = []

    def _spy(arg):
        seen.append(arg)
        return 1.0

    monkeypatch.setattr(ships, "impulse_output_fraction", _spy, raising=True)

    pf = TGPoint3(0.0, 1.0, 0.0)
    pt = TGPoint3(1.0, 0.0, 0.0)
    zero = TGPoint3(0.0, 0.0, 0.0)
    ship.TurnDirectionsToDirections(pf, pt, zero, zero)

    assert seen == [ies]


def test_motion_integrator_reads_impulse_fractions_from_module_scope(monkeypatch):
    """ship_motion._step_ship_motion runs for EVERY setpoint-driven ship every
    tick — the hottest of the two."""
    ship = ships.ShipClass()
    ship.SetImpulseEngineSubsystem(ImpulseEngineSubsystem("Impulse Engines"))
    ies = ship.GetImpulseEngineSubsystem()
    ies.SetMaxSpeed(10.0)
    ies.SetMaxAccel(5.0)
    ship._speed_setpoint = (1.0, TGPoint3(0.0, 1.0, 0.0),
                            PhysicsObjectClass.DIRECTION_MODEL_SPACE)

    seen = []

    def _spy(arg):
        seen.append(arg)
        return (1.0, 1.0)

    monkeypatch.setattr(ship_motion, "impulse_fractions", _spy, raising=True)

    ship_motion._step_ship_motion(ship, 1.0 / 60.0)

    assert seen and seen[0] is ies


def test_effective_motion_reads_impulse_output_fraction_from_module_scope(
        monkeypatch):
    """_effective_motion sits on the same per-ship-per-tick path as
    _step_ship_motion, so it carried the identical local import."""
    ship = ships.ShipClass()
    ship.SetImpulseEngineSubsystem(ImpulseEngineSubsystem("Impulse Engines"))
    ies = ship.GetImpulseEngineSubsystem()
    ies.SetMaxSpeed(10.0)
    ies.SetMaxAccel(5.0)

    seen = []

    def _spy(arg):
        seen.append(arg)
        return 1.0

    monkeypatch.setattr(ship_motion, "impulse_output_fraction", _spy,
                        raising=True)

    ship_motion._effective_motion(ship)

    assert seen == [ies]
