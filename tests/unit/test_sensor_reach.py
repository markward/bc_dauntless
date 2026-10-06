"""Sensor-model sub-project 3: BC's out-of-range ways in -- sensor memory and
over-boost -- and the nebula jam that cancels both
(2026-10-06-sensor-overboost-memory-design.md). Nebulae are fakes fed through
contact_index.nebulae_in, as tests/unit/test_sensor_bands_and_visibility.py
does: a real MetaNebula also adds density (concealment_at), which would let the
dense-core gate answer instead of the jam and hide what these tests pin."""
import pytest

from engine.appc import contact_index, sensor_dials
from engine.appc import sensor_detection as sd
from engine.appc.sets import SetClass
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import SensorSubsystem, CloakingSubsystem


def _observer_in_set(base_range=2000.0):
    s = SetClass()
    obs = ShipClass_Create("Galaxy")
    sensors = SensorSubsystem("Sensors")
    sensors._max_condition = 100.0
    sensors._condition = 100.0
    sensors.SetBaseSensorRange(base_range)
    obs.SetSensorSubsystem(sensors)
    s.AddObjectToSet(obs, "observer")
    return s, obs, sensors


def _ship_at(s, name, x):
    ship = ShipClass_Create("BirdOfPrey")
    ship.SetTranslateXYZ(float(x), 0.0, 0.0)
    s.AddObjectToSet(ship, name)
    return ship


class _Neb:
    """A nebula that contains exactly the objects it is given."""
    def __init__(self, *inside):
        self._inside = inside

    def IsObjectInNebula(self, obj):
        return 1 if any(obj is o for o in self._inside) else 0


def _nebulae(monkeypatch, *nebs):
    monkeypatch.setattr(contact_index, "nebulae_in", lambda pSet: tuple(nebs))


# ── jammed ──────────────────────────────────────────────────────────────────

def test_jammed_when_the_target_is_in_a_nebula(monkeypatch):
    s, obs, _ = _observer_in_set()
    tgt = _ship_at(s, "t", 5000.0)
    _nebulae(monkeypatch, _Neb(tgt))
    assert sd.jammed(obs, tgt) is True


def test_jammed_when_the_observer_is_in_a_nebula(monkeypatch):
    s, obs, _ = _observer_in_set()
    tgt = _ship_at(s, "t", 5000.0)
    _nebulae(monkeypatch, _Neb(obs))
    assert sd.jammed(obs, tgt) is True


def test_not_jammed_when_neither_is_in_any_nebula(monkeypatch):
    s, obs, _ = _observer_in_set()
    tgt = _ship_at(s, "t", 5000.0)
    other = _ship_at(s, "o", 9000.0)
    _nebulae(monkeypatch, _Neb(other))
    assert sd.jammed(obs, tgt) is False


def test_not_jammed_with_no_nebulae_even_inside_profile_concealment(monkeypatch):
    # The radial system-profile nebula is density, not a MetaNebula: never a jam.
    s, obs, _ = _observer_in_set()
    tgt = _ship_at(s, "t", 5000.0)
    monkeypatch.setattr(sd, "concealment_at", lambda ship: 0.19)
    assert sd.jammed(obs, tgt) is False


def test_jammed_never_raises_on_a_broken_nebula(monkeypatch):
    s, obs, _ = _observer_in_set()
    tgt = _ship_at(s, "t", 5000.0)

    class _Broken:
        def IsObjectInNebula(self, obj):
            raise RuntimeError("boom")

    _nebulae(monkeypatch, _Broken())
    assert sd.jammed(obs, tgt) is False


def test_jammed_is_false_for_an_observer_in_no_set():
    obs = ShipClass_Create("Galaxy")
    tgt = ShipClass_Create("BirdOfPrey")
    assert sd.jammed(obs, tgt) is False
