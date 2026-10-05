"""Major rocks block line of sight (sensor continuity/occlusion spec)."""
import App
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import SensorSubsystem
from engine.appc.sets import SetClass
from engine.appc import sensor_occlusion, sensor_dials
from engine.appc import sensor_detection as sd
from tests.helpers.rocks import make_major_rock


def _ship(s, name, x, base_range=2000.0):
    ship = ShipClass_Create("Galaxy")
    ship.SetTranslateXYZ(float(x), 0.0, 0.0)
    sensors = SensorSubsystem("Sensors")
    sensors._max_condition = 100.0
    sensors._condition = 100.0
    sensors.SetBaseSensorRange(base_range)
    ship.SetSensorSubsystem(sensors)
    s.AddObjectToSet(ship, name)
    return ship


def test_rock_on_the_line_blocks():
    s = SetClass()
    a, b = _ship(s, "A", 0.0), _ship(s, "B", 100.0)
    make_major_rock(s, "Rock", at=(50.0, 0.0, 0.0), radius_gu=3.0)
    assert sensor_occlusion.blocked(a, b) is True
    assert sd.can_detect(a, b) is False


def test_rock_off_the_line_does_not_block():
    s = SetClass()
    a, b = _ship(s, "A", 0.0), _ship(s, "B", 100.0)
    make_major_rock(s, "Rock", at=(50.0, 10.0, 0.0), radius_gu=3.0)
    assert sensor_occlusion.blocked(a, b) is False
    assert sd.can_detect(a, b) is True


def test_small_rock_never_blocks_and_the_dial_moves_the_line():
    s = SetClass()
    a, b = _ship(s, "A", 0.0), _ship(s, "B", 100.0)
    make_major_rock(s, "Pebble", at=(50.0, 0.0, 0.0), radius_gu=1.5)
    assert sensor_occlusion.blocked(a, b) is False
    sensor_dials._dials["min_blocker_radius_gu"] = 1.0
    sensor_occlusion.reset()
    assert sensor_occlusion.blocked(a, b) is True


def test_rock_beyond_the_target_does_not_block():
    s = SetClass()
    a, b = _ship(s, "A", 0.0), _ship(s, "B", 100.0)
    make_major_rock(s, "Rock", at=(150.0, 0.0, 0.0), radius_gu=3.0)
    assert sensor_occlusion.blocked(a, b) is False


def test_endpoints_never_occlude():
    s = SetClass()
    a = _ship(s, "A", 0.0)
    rock_target = make_major_rock(s, "BigRock", at=(100.0, 0.0, 0.0), radius_gu=40.0)
    assert sensor_occlusion.blocked(a, rock_target) is False


def test_scaled_radius_is_used_not_raw_get_radius():
    s = SetClass()
    a, b = _ship(s, "A", 0.0), _ship(s, "B", 100.0)
    rock = make_major_rock(s, "Rock", at=(50.0, 2.5, 0.0), radius_gu=1.0)
    rock.SetScale(3.0)                      # effective 3.0 GU: now covers y=2.5
    sensor_occlusion.reset()
    assert sensor_occlusion.blocked(a, b) is True


def test_adding_a_rock_in_the_same_tick_is_seen():
    s = SetClass()
    a, b = _ship(s, "A", 0.0), _ship(s, "B", 100.0)
    assert sensor_occlusion.blocked(a, b) is False
    make_major_rock(s, "Rock", at=(50.0, 0.0, 0.0), radius_gu=3.0)
    assert sensor_occlusion.blocked(a, b) is True     # no reset, same game time


def test_toggle_off_skips_occlusion(monkeypatch):
    s = SetClass()
    a, b = _ship(s, "A", 0.0), _ship(s, "B", 100.0)
    make_major_rock(s, "Rock", at=(50.0, 0.0, 0.0), radius_gu=3.0)
    monkeypatch.setattr(sd, "ENHANCED_SENSOR_CONTEST", False)
    assert sd.can_detect(a, b) is True


def test_ai_candidate_filter_respects_occlusion():
    from engine.appc import ai_sensor_gate
    s = SetClass()
    a, b = _ship(s, "A", 0.0), _ship(s, "B", 100.0)
    make_major_rock(s, "Rock", at=(50.0, 0.0, 0.0), radius_gu=3.0)
    gated = ai_sensor_gate._wrap_active_tuple(lambda self, pSet: (b,))
    with ai_sensor_gate.observing(a):
        assert gated(None, s) == ()


def test_begin_tick_invalidates_cache_on_rock_move():
    """Controller ruling: sensor_occlusion.begin_tick(now_gt) must be folded
    into both cache signatures. tests/integration drive sensor_contacts.tick
    with a STATIC App game time while moving rocks between ticks -- without
    begin_tick in the signature, blocked()'s pair cache would never notice
    the rock moved off the line, because App game time alone is unchanged."""
    s = SetClass()
    a, b = _ship(s, "A", 0.0), _ship(s, "B", 100.0)
    rock = make_major_rock(s, "Rock", at=(50.0, 0.0, 0.0), radius_gu=3.0)
    assert sensor_occlusion.blocked(a, b) is True
    rock.SetTranslateXYZ(50.0, 20.0, 0.0)      # move the rock off the line
    sensor_occlusion.begin_tick(1.0)
    assert sensor_occlusion.blocked(a, b) is False


# ── final-review fix 1: a rock you are INSIDE the sphere of never occludes ──

def test_observer_inside_a_rock_sphere_is_not_blinded():
    """Observer 2.5 GU from the centre of a 3 GU rock, target 500 GU away on
    the far side: you are beside the rock, not behind it."""
    s = SetClass()
    a, b = _ship(s, "A", 0.0), _ship(s, "B", 502.5)
    make_major_rock(s, "Rock", at=(2.5, 0.0, 0.0), radius_gu=3.0)
    assert sensor_occlusion.blocked(a, b) is False
    assert sd.can_detect(a, b) is True


def test_target_inside_a_rock_sphere_is_not_hidden():
    s = SetClass()
    a, b = _ship(s, "A", 0.0), _ship(s, "B", 500.0)
    make_major_rock(s, "Rock", at=(497.5, 0.0, 0.0), radius_gu=3.0)
    assert sensor_occlusion.blocked(a, b) is False
    assert sd.can_detect(a, b) is True


def test_a_rock_between_two_outside_ships_still_blocks_beside_a_hugged_one():
    """The hugged rock is exempt for that pair only; a second rock genuinely
    between the two still blocks."""
    s = SetClass()
    a, b = _ship(s, "A", 0.0), _ship(s, "B", 502.5)
    make_major_rock(s, "Hug", at=(2.5, 0.0, 0.0), radius_gu=3.0)
    make_major_rock(s, "Mid", at=(250.0, 0.0, 0.0), radius_gu=3.0)
    assert sensor_occlusion.blocked(a, b) is True


# ── final-review fix 5: the pair cache is per set ───────────────────────────

def test_pair_cache_survives_queries_alternating_between_sets(monkeypatch):
    s1, s2 = SetClass(), SetClass()
    a1, b1 = _ship(s1, "A", 0.0), _ship(s1, "B", 100.0)
    a2, b2 = _ship(s2, "A", 0.0), _ship(s2, "B", 100.0)
    make_major_rock(s1, "Rock", at=(50.0, 0.0, 0.0), radius_gu=3.0)
    make_major_rock(s2, "Rock", at=(50.0, 10.0, 0.0), radius_gu=3.0)
    calls = []
    real = sensor_occlusion._segment_hits

    def counting(*args):
        calls.append(args)
        return real(*args)

    monkeypatch.setattr(sensor_occlusion, "_segment_hits", counting)
    sensor_occlusion.begin_tick(1.0)
    assert sensor_occlusion.blocked(a1, b1) is True
    assert sensor_occlusion.blocked(a2, b2) is False
    first = len(calls)
    assert first == 2
    for _ in range(3):
        assert sensor_occlusion.blocked(a1, b1) is True
        assert sensor_occlusion.blocked(a2, b2) is False
    assert len(calls) == first          # both sets stayed cached
    sensor_occlusion.begin_tick(2.0)    # a new tick still invalidates each set
    assert sensor_occlusion.blocked(a1, b1) is True
    assert sensor_occlusion.blocked(a2, b2) is False
    assert len(calls) == first + 2


# ── final-review fix 4: a mission swap clears the occlusion caches ─────────

def test_host_loop_reset_sensor_state_resets_occlusion():
    import engine.host_loop as host_loop
    s = SetClass()
    a, b = _ship(s, "A", 0.0), _ship(s, "B", 100.0)
    make_major_rock(s, "Rock", at=(50.0, 0.0, 0.0), radius_gu=3.0)
    sensor_occlusion.begin_tick(7.0)
    assert sensor_occlusion.blocked(a, b) is True
    assert len(sensor_occlusion._pair_cache) == 1
    assert len(sensor_occlusion._rock_cache) == 1
    host_loop._reset_sensor_state()
    assert len(sensor_occlusion._pair_cache) == 0
    assert len(sensor_occlusion._rock_cache) == 0
    assert sensor_occlusion._tick_time is None
