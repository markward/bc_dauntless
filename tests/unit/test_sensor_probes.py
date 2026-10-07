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


def test_probe_reach_obeys_apply_concealment_false(monkeypatch):
    """The ENHANCED_SENSOR_CONTEST-off UI path (apply_concealment=False) skips
    the nebula gate for a directly seen contact; a probe-reached one must
    obey the same switch, not re-sample the core from the probe."""
    s, obs, sensors = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 4500.0)
    _probe_at(s, sensors, 4000.0)
    monkeypatch.setattr(sd, "concealment_at", lambda ship: 0.9)
    assert sd.can_detect(obs, far, apply_concealment=False) is True


def test_probe_walk_samples_concealment_once(monkeypatch):
    """concealment_at depends only on the target: one sample per can_detect,
    however many probes the walk visits."""
    s, obs, sensors = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 9300.0)
    for x in (3000.0, 6000.0, 9000.0):
        _probe_at(s, sensors, x)
    calls = []

    def _sample(ship):
        calls.append(ship)
        return 0.0
    monkeypatch.setattr(sd, "concealment_at", _sample)
    assert sd.can_detect(obs, far) is True
    assert calls == [far]


def test_cloak_bubble_applies_from_the_probe():
    """Rule 3: the cloak bubble (CLOAK_DETECTION_BASE_GU + the probe's own
    effective range x CLOAK_RANGE_FACTOR) is measured from the PROBE. A fully
    cloaked ship inside the probe's bubble is detected through it; one just
    outside is not, though both are far beyond the observer's own bubble."""
    from engine.appc.subsystems import CloakingSubsystem
    s, obs, sensors = _observer_in_set(2000.0)
    probe = _probe_at(s, sensors, 4000.0)
    bubble = (sd.CLOAK_DETECTION_BASE_GU
              + sd.effective_sensor_range(probe) * sd.CLOAK_RANGE_FACTOR)
    own_bubble = (sd.CLOAK_DETECTION_BASE_GU
                  + sd.effective_sensor_range(obs) * sd.CLOAK_RANGE_FACTOR)
    inside = _ship_at(s, "inside", 4000.0 + 0.5 * bubble)
    outside = _ship_at(s, "outside", 4000.0 + bubble + 1.0)
    assert 4000.0 - own_bubble > bubble       # both far beyond the observer's
    for ship in (inside, outside):
        ship.SetCloakingSubsystem(CloakingSubsystem("Cloaking Device"))
        ship.GetCloakingSubsystem().InstantCloak()
    assert sd.can_detect(obs, inside) is True
    assert sd.can_detect(obs, outside) is False


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


# ── fix round 1: an observer-side rock must not block the probe walk ───────

def test_probe_sees_past_a_rock_that_blocks_only_the_observer(occlusion_enabled):
    from tests.helpers.rocks import make_major_rock
    s, obs, sensors = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 4500.0)
    probe = _probe_at(s, sensors, 4500.0)
    probe.SetTranslateXYZ(4500.0, 500.0, 0.0)
    make_major_rock(s, "Rock", at=(1000.0, 0.0, 0.0), radius_gu=3.0)
    assert sd.can_detect(obs, far) is True


def test_probe_sees_an_in_range_target_behind_an_observer_side_rock(occlusion_enabled):
    from tests.helpers.rocks import make_major_rock
    s, obs, sensors = _observer_in_set(2000.0)
    near = _ship_at(s, "near", 1500.0)                # in the observer's own range
    make_major_rock(s, "Rock", at=(700.0, 0.0, 0.0), radius_gu=3.0)
    assert sd.can_detect(obs, near) is False           # fresh world: the rock blocks it
    probe = _probe_at(s, sensors, 1500.0)
    probe.SetTranslateXYZ(1500.0, 300.0, 0.0)
    assert sd.can_detect(obs, near) is True


def test_observer_side_rock_still_cancels_memory_without_a_probe(occlusion_enabled):
    from tests.helpers.rocks import make_major_rock
    s, obs, sensors = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 5000.0)
    sensors.AddKnownObject(far)
    make_major_rock(s, "Rock", at=(2500.0, 0.0, 0.0), radius_gu=3.0)
    assert sd.can_detect(obs, far) is False


def test_is_concealed_false_when_a_probe_sees_past_the_rock(occlusion_enabled):
    from tests.helpers.rocks import make_major_rock
    from engine.core.game import Game, _set_current_game
    import engine.appc.sensor_contacts as sensor_contacts
    s, obs, sensors = _observer_in_set(2000.0)
    far = _ship_at(s, "far", 4500.0)
    probe = _probe_at(s, sensors, 4500.0)
    probe.SetTranslateXYZ(4500.0, 500.0, 0.0)
    make_major_rock(s, "Rock", at=(1000.0, 0.0, 0.0), radius_gu=3.0)
    game = Game()
    game.SetPlayer(obs)
    _set_current_game(game)
    try:
        assert sensor_contacts.is_concealed(obs, far) is False
    finally:
        _set_current_game(None)


# ── bands ───────────────────────────────────────────────────────────────────

def test_bands_include_the_probes_bands():
    s, obs, sensors = _observer_in_set(2000.0)
    probe = _probe_at(s, sensors, 4000.0)
    in_near = _ship_at(s, "near_probe", 4400.0)   # 400 from probe (< 500)
    in_far = _ship_at(s, "far_probe", 4800.0)     # 800 from probe (< 1000)
    out = _ship_at(s, "out", 6000.0)
    assert (sensors.IsObjectNear(in_near), sensors.IsObjectFar(in_near)) == (1, 1)
    assert (sensors.IsObjectNear(in_far), sensors.IsObjectFar(in_far)) == (0, 1)
    assert (sensors.IsObjectNear(out), sensors.IsObjectFar(out)) == (0, 0)


def test_probe_bands_need_the_probe_in_the_owners_set():
    s, obs, sensors = _observer_in_set(2000.0)
    other = SetClass()
    tgt = ShipClass_Create("BirdOfPrey")
    tgt.SetTranslateXYZ(4400.0, 0.0, 0.0)
    other.AddObjectToSet(tgt, "elsewhere")
    _probe_at(s, sensors, 4000.0)
    assert sensors.IsObjectNear(tgt) == 0 and sensors.IsObjectFar(tgt) == 0


# ── the player's sweep ──────────────────────────────────────────────────────

def _player_world(base_range=2000.0):
    from engine.core.game import Game, _set_current_game
    s, player, sensors = _observer_in_set(base_range)
    game = Game()
    game.SetPlayer(player)
    _set_current_game(game)
    return s, player, sensors


@pytest.fixture
def _no_game():
    yield
    from engine.core.game import _set_current_game
    _set_current_game(None)


def test_sweep_identifies_a_contact_in_the_probes_near_band(_no_game):
    from engine.appc import sensor_contacts
    s, player, sensors = _player_world()
    bird = _ship_at(s, "Bird", 4400.0)
    _probe_at(s, sensors, 4000.0)
    sensor_contacts.tick(player, 0.0)
    assert sensors.IsObjectKnown(bird) == 0
    for t in (1.0, 2.0, 3.0, 4.0, 5.0):
        sensor_contacts.tick(player, t)
    assert sensors.IsObjectKnown(bird) == 1


def test_sweep_posts_far_and_near_via_probe(_no_game, monkeypatch):
    from engine.appc import sensor_contacts
    posted = []
    monkeypatch.setattr(sensor_contacts, "_post",
                        lambda et, obj, entered, sensors: posted.append((et, obj, entered)))
    s, player, sensors = _player_world()
    bird = _ship_at(s, "Bird", 4400.0)
    _probe_at(s, sensors, 4000.0)
    sensor_contacts.tick(player, 0.0)
    assert (App.ET_SENSORS_SHIP_FAR_PROXIMITY, bird, True) in posted
    assert (App.ET_SENSORS_SHIP_NEAR_PROXIMITY, bird, True) in posted


def test_sweep_posts_nothing_via_probe_when_player_sensors_dead(_no_game, monkeypatch):
    from engine.appc import sensor_contacts
    posted = []
    monkeypatch.setattr(sensor_contacts, "_post",
                        lambda et, obj, entered, sensors: posted.append((et, obj, entered)))
    s, player, sensors = _player_world()
    bird = _ship_at(s, "Bird", 4400.0)
    _probe_at(s, sensors, 4000.0)
    sensors._condition = 10.0
    sensor_contacts.tick(player, 0.0)
    assert [p for p in posted if p[1] is bird] == []


def test_continuity_runs_for_a_known_probe_reached_contact_behind_a_rock(_no_game, occlusion_enabled, monkeypatch):
    from engine.appc import sensor_contacts
    from tests.helpers.rocks import make_major_rock
    monkeypatch.setattr(sensor_contacts, "_helm_exited_set", lambda obj: None)
    s, player, sensors = _player_world()
    bird = _ship_at(s, "Bird", 4500.0)
    _probe_at(s, sensors, 4000.0)
    # unknown to the player on purpose: memory cannot be why it is in reach
    make_major_rock(s, "Rock", at=(4250.0, 0.0, 0.0), radius_gu=3.0)
    assert sensor_contacts.is_concealed(player, bird) is True
