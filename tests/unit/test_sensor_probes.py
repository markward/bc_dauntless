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
