"""Sensor-model sub-project 4: probes (2026-10-07-sensor-probes-design.md).

A probe is a ShipClass with its own SensorSubsystem (SDK Hardpoints/probe.py:
1000 GU). The launching ship's sensors hold its object ID (BC AddProbe); its
sensors see for the launcher. Fixtures reuse test_sensor_reach's helpers."""
import pytest

import App
from engine.appc import contact_index
from engine.appc import sensor_detection as sd
from engine.appc.sets import SetClass
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import SensorSubsystem
from tests.unit.test_sensor_reach import _observer_in_set, _ship_at, _Neb, _nebulae
from tests.helpers.rocks import occlusion_enabled  # noqa: F401  (fixture)


def _probe_at(s, owner_sensors, x, base_range=1000.0):
    probe = ShipClass_Create("Probe")
    probe.SetTranslateXYZ(float(x), 0.0, 0.0)
    ps = SensorSubsystem("Sensor Array")
    ps._max_condition = 100.0
    ps._condition = 100.0
    ps.SetBaseSensorRange(base_range)
    probe.SetSensorSubsystem(ps)
    s.AddObjectToSet(probe, "Probe %d" % probe.GetObjID())
    owner_sensors.AddProbe(probe.GetObjID())
    return probe


# ── count ───────────────────────────────────────────────────────────────────

def test_num_probes_round_trips():
    sensors = SensorSubsystem("Sensors")
    assert sensors.GetNumProbes() == 0
    sensors.SetNumProbes(7)
    assert sensors.GetNumProbes() == 7


def test_num_probes_is_seeded_from_max_probes_by_setup_properties():
    from engine.appc.properties import SensorProperty
    ship = ShipClass_Create("Galaxy")
    prop = SensorProperty("Sensor Array")
    prop.SetBaseSensorRange(2000.0)
    prop.SetMaxProbes(10)
    prop.SetMaxCondition(8000.0)
    ship.GetPropertySet().AddToSet("Scene Root", prop)
    ship.SetupProperties()
    sensors = ship.GetSensorSubsystem()
    assert sensors.GetMaxProbes() == 10
    assert sensors.GetNumProbes() == 10


def test_repair_ship_fully_refills_probes():
    import Actions.ShipScriptActions as ssa
    from engine.appc.properties import SensorProperty
    ship = ShipClass_Create("Galaxy")
    prop = SensorProperty("Sensor Array")
    prop.SetBaseSensorRange(2000.0)
    prop.SetMaxProbes(10)
    prop.SetMaxCondition(8000.0)
    ship.GetPropertySet().AddToSet("Scene Root", prop)
    ship.SetupProperties()
    sensors = ship.GetSensorSubsystem()
    sensors.SetNumProbes(2)
    ssa.RepairShipFully(None, ship.GetObjID())
    assert sensors.GetNumProbes() == 10


# ── list ────────────────────────────────────────────────────────────────────

def test_add_probe_lists_the_live_probe():
    s, obs, sensors = _observer_in_set()
    probe = _probe_at(s, sensors, 3000.0)
    assert sensors.probes() == [probe]


def test_probes_prunes_a_deleted_probe():
    from engine.core import ids
    s, obs, sensors = _observer_in_set()
    keep = _probe_at(s, sensors, 3000.0)
    gone = _probe_at(s, sensors, 4000.0)
    ids.unregister(gone.GetObjID())
    assert sensors.probes() == [keep]
    assert sensors._probe_ids == [keep.GetObjID()]


# ── reach ───────────────────────────────────────────────────────────────────

def test_probe_sees_a_ship_beyond_the_observers_range():
    s, obs, sensors = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 4500.0)
    assert sd.can_detect(obs, far) is False
    _probe_at(s, sensors, 4000.0)                     # 500 GU from the target
    assert sd.can_detect(obs, far) is True


def test_target_beyond_the_probes_range_is_not_reached():
    s, obs, sensors = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 9000.0)
    _probe_at(s, sensors, 4000.0)                     # 5000 GU away from it
    assert sd.can_detect(obs, far) is False


def test_probe_in_another_set_does_not_reach():
    s, obs, sensors = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 4500.0)
    other = SetClass()
    probe = ShipClass_Create("Probe")
    probe.SetTranslateXYZ(4400.0, 0.0, 0.0)
    ps = SensorSubsystem("Sensor Array")
    ps._max_condition = 100.0
    ps._condition = 100.0
    ps.SetBaseSensorRange(1000.0)
    probe.SetSensorSubsystem(ps)
    other.AddObjectToSet(probe, "Probe 1")
    sensors.AddProbe(probe.GetObjID())
    assert sd.can_detect(obs, far) is False


def test_probe_with_offline_sensors_does_not_reach():
    s, obs, sensors = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 4500.0)
    probe = _probe_at(s, sensors, 4000.0)
    probe.GetSensorSubsystem()._condition = 0.0
    assert sd.can_detect(obs, far) is False


def test_dead_observer_sensors_ignore_probes():
    s, obs, sensors = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 4500.0)
    _probe_at(s, sensors, 4000.0)
    sensors._condition = 10.0                         # below the disabled threshold
    assert sd.can_detect(obs, far) is False


def test_rock_between_probe_and_target_hides_it(occlusion_enabled):
    from tests.helpers.rocks import make_major_rock
    s, obs, sensors = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 4500.0)
    _probe_at(s, sensors, 4000.0)
    make_major_rock(s, "Rock", at=(4250.0, 0.0, 0.0), radius_gu=3.0)
    assert sd.can_detect(obs, far) is False


def test_jam_does_not_cancel_the_probe_branch(monkeypatch):
    s, obs, sensors = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 4500.0)
    _probe_at(s, sensors, 4000.0)
    _nebulae(monkeypatch, _Neb(far, obs))
    assert sd.jammed(obs, far) is True
    assert sd.can_detect(obs, far) is True


def test_dense_core_still_hides_from_the_probe(monkeypatch):
    s, obs, sensors = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 4500.0)
    _probe_at(s, sensors, 4000.0)
    monkeypatch.setattr(sd, "concealment_at", lambda ship: 0.9)
    assert sd.can_detect(obs, far) is False


def test_probe_branch_does_not_identify():
    s, obs, sensors = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 4500.0)
    _probe_at(s, sensors, 4000.0)
    assert sd.can_detect(obs, far) is True
    assert sensors.IsObjectKnown(far) == 0


def test_own_probe_is_detected_and_not_a_recursion_hazard():
    s, obs, sensors = _observer_in_set(2000.0)
    probe = _probe_at(s, sensors, 2500.0)             # beyond own range
    probe.GetSensorSubsystem().AddProbe(obs.GetObjID())   # pathological cycle
    assert sd.can_detect(obs, probe) is True          # its own sensors see itself at 0 GU
    near = _probe_at(s, sensors, 500.0)
    assert sd.can_detect(obs, near) is True


def test_cross_set_dist_sq_path_ignores_probes():
    s, obs, sensors = _observer_in_set(2000.0)
    other = SetClass()
    ship = ShipClass_Create("BirdOfPrey")
    other.AddObjectToSet(ship, "elsewhere")
    _probe_at(s, sensors, 0.0)
    assert sd.can_detect(obs, ship, dist_sq_gu=5000.0 ** 2) is False


# ── in_reach ────────────────────────────────────────────────────────────────

def test_in_reach_includes_probes_and_ignores_rocks(occlusion_enabled):
    from tests.helpers.rocks import make_major_rock
    s, obs, sensors = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 4500.0)
    assert sd.in_reach(obs, far) is False
    _probe_at(s, sensors, 4000.0)
    make_major_rock(s, "Rock", at=(4250.0, 0.0, 0.0), radius_gu=3.0)
    assert sd.can_detect(obs, far) is False
    assert sd.in_reach(obs, far) is True


def test_in_reach_via_probe_needs_live_observer_sensors():
    s, obs, sensors = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 4500.0)
    _probe_at(s, sensors, 4000.0)
    sensors._condition = 10.0
    assert sd.in_reach(obs, far) is False
