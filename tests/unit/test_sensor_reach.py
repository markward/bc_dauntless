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
from tests.helpers.rocks import occlusion_enabled  # noqa: F401  (fixture)


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


# ── memory ──────────────────────────────────────────────────────────────────

def test_known_contact_beyond_range_is_detected():
    s, obs, sensors = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 5000.0)
    assert sd.can_detect(obs, far) is False
    sensors.AddKnownObject(far)
    assert sd.can_detect(obs, far) is True


def test_unknown_contact_beyond_range_is_not_detected():
    s, obs, _ = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 5000.0)
    assert sd.can_detect(obs, far) is False


@pytest.mark.parametrize("who", ["target", "observer"])
def test_jam_cancels_memory(monkeypatch, who):
    s, obs, sensors = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 5000.0)
    sensors.AddKnownObject(far)
    _nebulae(monkeypatch, _Neb(far if who == "target" else obs))
    assert sd.can_detect(obs, far) is False


def test_known_target_in_another_set_is_not_reached():
    s, obs, sensors = _observer_in_set(2000.0)
    other = SetClass()
    ship = ShipClass_Create("BirdOfPrey")
    ship.SetTranslateXYZ(5000.0, 0.0, 0.0)
    other.AddObjectToSet(ship, "elsewhere")
    sensors.AddKnownObject(ship)
    sensors._power_factor = 1.25
    assert sd.can_detect(obs, ship) is False


def test_cross_set_dist_sq_path_is_range_only():
    # projectiles.py hands a cross-set offset in via dist_sq_gu; that path must
    # keep answering by range alone.
    s, obs, sensors = _observer_in_set(2000.0)
    other = SetClass()
    ship = ShipClass_Create("BirdOfPrey")
    other.AddObjectToSet(ship, "elsewhere")
    sensors.AddKnownObject(ship)
    assert sd.can_detect(obs, ship, dist_sq_gu=1000.0 ** 2) is True
    assert sd.can_detect(obs, ship, dist_sq_gu=5000.0 ** 2) is False


def test_memory_never_reveals_a_fully_cloaked_target():
    s, obs, sensors = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 5000.0)
    far.SetCloakingSubsystem(CloakingSubsystem("Cloaking Device"))
    far.GetCloakingSubsystem().InstantCloak()
    sensors.AddKnownObject(far)
    assert sd.can_detect(obs, far) is False


def test_memory_drops_with_dead_sensors_and_returns_on_repair():
    s, obs, sensors = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 5000.0)
    sensors.AddKnownObject(far)
    sensors._condition = 10.0             # below the 25% disabled threshold
    assert sd.can_detect(obs, far) is False
    sensors._condition = 100.0
    assert sd.can_detect(obs, far) is True   # memory itself was never wiped


def test_memory_respects_occlusion(occlusion_enabled):
    from tests.helpers.rocks import make_major_rock
    s, obs, sensors = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 5000.0)
    sensors.AddKnownObject(far)
    make_major_rock(s, "Rock", at=(2500.0, 0.0, 0.0), radius_gu=3.0)
    assert sd.can_detect(obs, far) is False


def test_ai_observer_never_reaches_by_memory():
    # AI has no identification tier: a fresh AI ship's sensors know nothing.
    s, ai, _ = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 5000.0)
    assert sd.can_detect(ai, far) is False


# ── over-boost ──────────────────────────────────────────────────────────────

def test_boost_above_threshold_sees_the_whole_set():
    s, obs, sensors = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 500000.0)
    sensors._power_factor = 1.2 + 1e-6
    assert sd.can_detect(obs, far) is True


def test_boost_exactly_at_threshold_does_not():
    s, obs, sensors = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 500000.0)
    sensors._power_factor = 1.2
    assert sd.can_detect(obs, far) is False


def test_boost_threshold_is_the_dial(monkeypatch):
    s, obs, sensors = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 500000.0)
    sensors._power_factor = 1.1
    assert sd.can_detect(obs, far) is False
    monkeypatch.setitem(sensor_dials._dials, "overboost_threshold", 1.05)
    assert sd.can_detect(obs, far) is True


@pytest.mark.parametrize("who", ["target", "observer"])
def test_jam_cancels_boost(monkeypatch, who):
    s, obs, sensors = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 500000.0)
    sensors._power_factor = 1.25
    _nebulae(monkeypatch, _Neb(far if who == "target" else obs))
    assert sd.can_detect(obs, far) is False


def test_boost_never_reveals_a_fully_cloaked_target():
    s, obs, sensors = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 500000.0)
    far.SetCloakingSubsystem(CloakingSubsystem("Cloaking Device"))
    far.GetCloakingSubsystem().InstantCloak()
    sensors._power_factor = 1.25
    assert sd.can_detect(obs, far) is False


def test_boost_does_not_identify():
    s, obs, sensors = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 500000.0)
    sensors._power_factor = 1.25
    assert sd.can_detect(obs, far) is True
    assert sensors.IsObjectKnown(far) == 0


def test_boost_through_the_real_power_path():
    s, obs, sensors = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 500000.0)
    sensors._normal_power = 1.0

    class _Grid:
        def __init__(self, cap):
            self.cap = cap

        def _draw(self, wanted, mode):
            return min(wanted, self.cap)

    sensors.SetPowerPercentageWanted(1.25)
    sensors._update_power(1.0, _Grid(cap=10.0))           # fully fed: 1.25
    assert sensors.GetNormalPowerPercentage() == pytest.approx(1.25)
    assert sd.can_detect(obs, far) is True
    sensors._update_power(1.0, _Grid(cap=1.2))            # under-fed: exactly 1.2
    assert sensors.GetNormalPowerPercentage() == pytest.approx(1.2)
    assert sd.can_detect(obs, far) is False


# ── in_reach (for the continuity clock) ────────────────────────────────────

def test_in_reach_ignores_occlusion(occlusion_enabled):
    from tests.helpers.rocks import make_major_rock
    s, obs, sensors = _observer_in_set(2000.0)
    near = _ship_at(s, "near", 500.0)
    make_major_rock(s, "Rock", at=(250.0, 0.0, 0.0), radius_gu=3.0)
    assert sd.can_detect(obs, near) is False
    assert sd.in_reach(obs, near) is True


def test_in_reach_uses_the_unshrunk_range(monkeypatch):
    # A ship in the dense nebula core is hidden, but still in reach.
    s, obs, _ = _observer_in_set(2000.0)
    tgt = _ship_at(s, "t", 1500.0)
    monkeypatch.setattr(sd, "concealment_at", lambda ship: 0.9)
    assert sd.can_detect(obs, tgt) is False
    assert sd.in_reach(obs, tgt) is True


def test_in_reach_includes_memory_and_respects_the_jam(monkeypatch):
    s, obs, sensors = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 5000.0)
    assert sd.in_reach(obs, far) is False
    sensors.AddKnownObject(far)
    assert sd.in_reach(obs, far) is True
    _nebulae(monkeypatch, _Neb(far))
    assert sd.in_reach(obs, far) is False


def test_in_reach_is_false_with_dead_sensors():
    s, obs, sensors = _observer_in_set(2000.0)
    near = _ship_at(s, "near", 10.0)
    sensors._condition = 10.0
    assert sd.in_reach(obs, near) is False
