"""The power draw program: a consumer whose demand is steady and met in full
is frozen, and the plant repeats only its draw until a watched field is
written (spec docs/superpowers/specs/2026-10-30-passive-subsystem-state-design.md
§4 and §8 "Phase 2 as planned"). Hand-built ships, driven through
PowerSubsystem.Update, compared with the per-tick model by float.hex.
"""
import App
import pytest

from engine.appc import passive_power, passive_state
from engine.appc.properties import PowerProperty
from engine.appc.subsystems import (
    CloakingSubsystem, ImpulseEngineSubsystem, PowerSubsystem,
    SensorSubsystem, ShieldSubsystem,
)
from engine.appc.weapon_subsystems import TractorBeamSystem
from engine.core.loop import TICK_DELTA

PER_TICK = {"DAUNTLESS_PASSIVE_STATE": "0"}
PASSIVE = {}


def _plant(main=1000.0, backup=500.0):
    plant = PowerSubsystem("Warp Core")
    prop = PowerProperty("Warp Core")
    prop.SetPowerOutput(300.0)
    prop.SetMainBatteryLimit(main)
    prop.SetBackupBatteryLimit(backup)
    prop.SetMainConduitCapacity(1200.0)
    prop.SetBackupConduitCapacity(200.0)
    plant.SetProperty(prop)
    # Start on an interval boundary, so the first tick seeds the conduit
    # budgets and every draw is met: a steady ship from tick 1.
    plant._interval_elapsed = plant.POWER_INTERVAL
    return plant


def _ship(name="Ship", cloak=False, tractor=False, main=1000.0, backup=500.0):
    ship = App.ShipClass_Create(name)
    ship.SetPowerSubsystem(_plant(main, backup))
    for setter, sub, pw in (
            (ship.SetSensorSubsystem, SensorSubsystem("Sensors"), 100.0),
            (ship.SetShieldSubsystem, ShieldSubsystem("Shields"), 250.0),
            (ship.SetImpulseEngineSubsystem,
             ImpulseEngineSubsystem("Impulse"), 150.0)):
        sub.SetNormalPowerPerSecond(pw)
        sub.TurnOn()
        setter(sub)
    if cloak:
        c = CloakingSubsystem("Cloak")
        c.SetNormalPowerPerSecond(50.0)
        c.TurnOn()
        ship.SetCloakingSubsystem(c)
    if tractor:
        t = TractorBeamSystem("Tractors")
        t.SetNormalPowerPerSecond(600.0)
        t.TurnOn()
        ship.SetTractorBeamSystem(t)
    return ship


def _consumers(ship):
    return list(ship._powered_consumers)


def _drawing(ship):
    """The three consumers _ship turned on with a demand. ShipClass_Create's
    own default subsystems are consumers too (zero demand, or the tractor)."""
    return [ship.GetSensorSubsystem(), ship.GetShieldSubsystem(),
            ship.GetImpulseEngineSubsystem()]


def _tick(ship, mode, n=1):
    passive_state.configure(mode)
    for _ in range(n):
        ship.GetPowerSubsystem().Update(TICK_DELTA)


def _hex(v):
    return float(v).hex()


def _values(ship):
    plant = ship.GetPowerSubsystem()
    row = [_hex(plant.GetMainBatteryPower()), _hex(plant.GetBackupBatteryPower()),
           _hex(plant.GetPowerDispensed()), _hex(plant.GetPowerWanted()),
           _hex(plant.GetAvailablePower())]
    for c in _consumers(ship):
        row += [_hex(c.GetPowerWanted()), _hex(c.GetPowerReceived()),
                _hex(c.GetPowerPercentage()), _hex(c.GetNormalPowerPercentage())]
    return row


def test_steady_ship_runs_the_program():
    ship = _ship()
    _tick(ship, PASSIVE, 3)
    counts = passive_power.counts()
    assert counts["full_ticks"] == 1
    assert counts["program_ticks"] == 2
    for c in _consumers(ship):              # the idle default tractor too
        assert c.__dict__["_power_frozen"] is True
    assert all(c.__dict__["_power_frozen"] for c in _drawing(ship))


def test_write_thaws_and_next_tick_is_full():
    ship = _ship()
    _tick(ship, PASSIVE, 3)
    sensor = ship.GetSensorSubsystem()
    sensor.TurnOff()
    assert sensor.__dict__["_power_frozen"] is False
    assert ship.GetPowerSubsystem().__dict__["_passive_power"] is None
    before = passive_power.counts()["full_ticks"]
    _tick(ship, PASSIVE)
    assert passive_power.counts()["full_ticks"] == before + 1


def _fields(c):
    return [_hex(c._power_wanted), _hex(c._power_received),
            _hex(c._efficiency), _hex(c._power_factor)]


def test_record_draw_matches_update_power():
    for main_battery in (0.0, 1.0):
        plants, subs = [], []
        for _ in range(2):
            plant = _plant()
            plant.Update(TICK_DELTA)      # seeds the conduit budgets
            plant.SetMainBatteryPower(main_battery)
            plant.SetBackupBatteryPower(0.0)
            sub = SensorSubsystem("Sensors")
            sub.SetNormalPowerPerSecond(100.0)
            sub.SetPowerPercentageWanted(1.25)
            sub.TurnOn()
            plants.append(plant)
            subs.append(sub)
        subs[0]._update_power(TICK_DELTA, plants[0])
        base = subs[1]._normal_power * TICK_DELTA
        wanted = base * subs[1]._power_percentage_wanted
        subs[1]._record_draw(wanted,
                             plants[1]._draw(wanted, subs[1].POWER_MODE), base)
        assert _fields(subs[0]) == _fields(subs[1])
        assert _hex(plants[0].GetMainBatteryPower()) == \
            _hex(plants[1].GetMainBatteryPower())


def _demand_per_tick(ship):
    return sum(c._normal_power * TICK_DELTA * c._power_percentage_wanted
               for c in _consumers(ship))


def test_shortfall_mid_program_matches_per_tick():
    ref, ship = _ship("Ref"), _ship("Passive")
    for s, mode in ((ref, PER_TICK), (ship, PASSIVE)):
        _tick(s, mode)
        plant = s.GetPowerSubsystem()
        plant.SetMainBatteryPower(_demand_per_tick(s) * 1.5)
        plant.SetBackupBatteryPower(0.0)
    assert _values(ref) == _values(ship)
    for tick in range(5):
        _tick(ref, PER_TICK)
        _tick(ship, PASSIVE)
        assert _values(ref) == _values(ship), "differs at tick %d" % tick
    counts = passive_power.counts()
    assert counts["program_ticks"] > 0 and counts["thawed"] > 0


WRITES = {
    # From 0%: SetPowerPercentageWanted cannot rescale _power_wanted (old is
    # 0), so only the slider field itself can thaw the consumer.
    "slider_from_zero": (lambda c: c.SetPowerPercentageWanted(0.0),
                         lambda c: c.SetPowerPercentageWanted(1.25)),
    "normal_power": (lambda c: None,
                     lambda c: c.SetNormalPowerPerSecond(170.0)),
    "off_then_on": (lambda c: c.TurnOff(), lambda c: c.TurnOn()),
    "power_wanted": (lambda c: None, lambda c: c.SetPowerWanted(0.25)),
}


@pytest.mark.parametrize("name", sorted(WRITES))
def test_watched_input_writes_match_per_tick(name):
    first, second = WRITES[name]
    ref, ship = _ship("Ref"), _ship("Passive")
    for step in (first, second):
        for s, mode in ((ref, PER_TICK), (ship, PASSIVE)):
            step(s.GetShieldSubsystem())
        for tick in range(3):
            _tick(ref, PER_TICK)
            _tick(ship, PASSIVE)
            assert _values(ref) == _values(ship), "%s differs" % name
    assert passive_power.counts()["program_ticks"] > 0


def test_consumer_added_drops_the_program():
    ship = _ship()
    _tick(ship, PASSIVE, 3)
    assert ship.GetPowerSubsystem().__dict__["_passive_power"] is not None
    extra = SensorSubsystem("Extra Sensors")
    extra.SetNormalPowerPerSecond(10.0)
    extra.TurnOn()
    ship.AddPoweredConsumer(extra)
    assert ship.GetPowerSubsystem().__dict__["_passive_power"] is None


def test_replaced_plant_starts_full():
    ref, ship = _ship("Ref"), _ship("Passive")
    _tick(ref, PER_TICK, 3)
    _tick(ship, PASSIVE, 3)
    for s in (ref, ship):
        s.SetPowerSubsystem(_plant())
    before = passive_power.counts()["full_ticks"]
    _tick(ref, PER_TICK)
    _tick(ship, PASSIVE)
    assert passive_power.counts()["full_ticks"] == before + 1
    assert _values(ref) == _values(ship)
    for _ in range(4):
        _tick(ref, PER_TICK)
        _tick(ship, PASSIVE)
        assert _values(ref) == _values(ship)


def test_reattached_old_plant_does_not_run_its_stale_program():
    ref, ship = _ship("Ref"), _ship("Passive")
    _tick(ref, PER_TICK, 3)
    _tick(ship, PASSIVE, 3)
    old = {s: s.GetPowerSubsystem() for s in (ref, ship)}
    for s, mode in ((ref, PER_TICK), (ship, PASSIVE)):
        s.SetPowerSubsystem(_plant())
        _tick(s, mode, 2)
        s.GetShieldSubsystem().SetPowerPercentageWanted(0.5)
        _tick(s, mode, 2)
        s.SetPowerSubsystem(old[s])
    for _ in range(3):
        _tick(ref, PER_TICK)
        _tick(ship, PASSIVE)
        assert _values(ref) == _values(ship)


def test_cloak_is_a_call_op():
    ref, ship = _ship("Ref", cloak=True), _ship("Passive", cloak=True)
    for s in (ref, ship):
        s.GetCloakingSubsystem().StartCloaking()
    cloak = ship.GetCloakingSubsystem()
    calls = []
    real = cloak._update_power

    def spy(dt, plant):
        calls.append(dt)
        real(dt, plant)

    cloak._update_power = spy
    for tick in range(6):
        _tick(ref, PER_TICK)
        _tick(ship, PASSIVE)
        assert not cloak.__dict__.get("_power_frozen")
        assert len(calls) == tick + 1
        assert _values(ref) == _values(ship)
        assert _hex(ref.GetCloakingSubsystem()._backup_reserve) == \
            _hex(cloak._backup_reserve)
    assert passive_power.counts()["program_ticks"] == 5


def test_idle_tractor_engaging_matches_per_tick():
    """With _any_child_firing patched on the instance the tractor is a call op
    (the instance-patch rule), so when a beam engages its direct steal starts
    on the same tick as the per-tick model."""
    ref = _ship("Ref", tractor=True)
    ship = _ship("Passive", tractor=True)
    firing = {ref: [False], ship: [False]}
    for s in (ref, ship):
        t = s.GetTractorBeamSystem()
        t._any_child_firing = (lambda f=firing[s]: f[0])
    for tick in range(6):
        if tick == 3:
            firing[ref][0] = firing[ship][0] = True
        _tick(ref, PER_TICK)
        _tick(ship, PASSIVE)
        assert _values(ref) == _values(ship), "differs at tick %d" % tick
    assert passive_power.counts()["program_ticks"] > 0


def test_unmet_draw_is_promoted_once_met():
    """A consumer whose draw was short when the program was built is a call
    op; once its draw is met again the program is rebuilt and it freezes."""
    ship = _ship()
    ship.GetPowerSubsystem()._interval_elapsed = 0.0   # no budget yet
    _tick(ship, PASSIVE, 3)
    assert not any(c.__dict__.get("_power_frozen") for c in _drawing(ship))
    _tick(ship, PASSIVE, 62)                           # crosses a boundary
    assert all(c.__dict__.get("_power_frozen") for c in _drawing(ship))


def test_audit_reference_run_is_not_a_thaw():
    """The audit runs the full pump beside each program tick; its rewrites of
    frozen fields are undone, not counted, and the two agree bit for bit."""
    ship = _ship()
    _tick(ship, {"DAUNTLESS_PASSIVE_AUDIT": "1"}, 5)
    counts = passive_power.counts()
    assert counts["program_ticks"] == 4
    assert counts["thawed"] == 0
    assert all(c.__dict__["_power_frozen"] for c in _drawing(ship))
    assert passive_state.audit_failures() == []


def test_audit_passes_through_a_shortfall():
    ref, ship = _ship("Ref"), _ship("Passive")
    audit = {"DAUNTLESS_PASSIVE_AUDIT": "1"}
    for s, mode in ((ref, PER_TICK), (ship, audit)):
        _tick(s, mode)
        plant = s.GetPowerSubsystem()
        plant.SetMainBatteryPower(_demand_per_tick(s) * 1.5)
        plant.SetBackupBatteryPower(0.0)
    for _ in range(5):
        _tick(ref, PER_TICK)
        _tick(ship, audit)
        assert _values(ref) == _values(ship)
    assert passive_state.audit_failures() == []
    assert passive_power.counts()["thawed"] > 0


def test_switch_off_never_builds():
    ship = _ship()
    _tick(ship, PER_TICK, 3)
    assert passive_power.counts()["program_ticks"] == 0
    for c in _consumers(ship):
        assert not c.__dict__.get("_power_frozen")


class _Obj:
    pass


def test_audit_compare_reports_a_difference():
    o = _Obj()
    o.f = 1.0

    def ref():
        o.f = 2.0

    passive_state.audit_compare([o], ref, lambda: setattr(o, "f", 2.0))
    assert passive_state.audit_failures() == []
    assert o.f == 2.0
    passive_state.audit_compare([o], ref, lambda: setattr(o, "f", 3.0))
    assert passive_state.audit_failures() == [("_Obj", "f")]
    assert o.f == 3.0


# ── Phase 2, task 2: structural freezability, idle tractor, zero slider ───


def _tractor_ship(name):
    from engine.appc.weapon_subsystems import TractorBeam
    ship = _ship(name, tractor=True)
    beam = TractorBeam("Beam")
    ship.GetTractorBeamSystem().AddChildSubsystem(beam)
    return ship, beam


def _ops(ship):
    return [op[0] for op in ship.GetPowerSubsystem().__dict__["_passive_power"].ops]


def test_idle_tractor_is_frozen():
    ship, beam = _tractor_ship("Ship")
    _tick(ship, PASSIVE, 2)
    tractor = ship.GetTractorBeamSystem()
    assert tractor.__dict__["_power_frozen"] is True
    assert tractor not in _ops(ship)


def test_beam_firing_thaws_the_tractor_system():
    ref, ref_beam = _tractor_ship("Ref")
    ship, beam = _tractor_ship("Passive")
    _tick(ref, PER_TICK, 2)
    _tick(ship, PASSIVE, 2)
    tractor = ship.GetTractorBeamSystem()
    assert tractor.__dict__["_power_frozen"] is True
    ref_beam._firing = True
    beam._firing = True
    assert tractor.__dict__["_power_frozen"] is False
    full = passive_power.counts()["full_ticks"]
    _tick(ref, PER_TICK)
    _tick(ship, PASSIVE)
    assert passive_power.counts()["full_ticks"] == full + 1
    for t in range(5):
        _tick(ref, PER_TICK)
        _tick(ship, PASSIVE)
        assert _values(ref) == _values(ship), "differs at tick %d" % t
        assert _fields(ref.GetTractorBeamSystem()) == _fields(tractor)
    assert tractor.GetPowerReceived() > 0.0
    assert tractor in _ops(ship)            # engaged: a call op


def test_beam_firing_write_keeps_phase_one_wake():
    """The thaw descriptor still does everything WakeField does."""
    ship, beam = _tractor_ship("Ship")
    beam.__dict__["_passive_asleep"] = True
    beam._firing = True
    assert not beam.__dict__.get("_passive_asleep")


def test_class_override_without_opt_in_is_a_call_op():
    class Odd(SensorSubsystem):
        def _wants_power(self):
            return bool(self.IsOn())

    ship = _ship()
    odd = Odd("Odd")
    odd.SetNormalPowerPerSecond(80.0)
    odd.TurnOn()
    ship.SetSensorSubsystem(odd)
    assert odd in _consumers(ship)
    _tick(ship, PASSIVE, 3)
    assert odd in _ops(ship)
    assert not odd.__dict__.get("_power_frozen")


def test_override_opt_in_by_providing_class():
    class Ok(SensorSubsystem):
        _POWER_FREEZABLE = True

        def _wants_power(self):
            return bool(self.IsOn())

    class Child(Ok):
        pass

    assert passive_power.class_is_call_op(Ok) is False
    assert passive_power.class_is_call_op(Child) is False
    assert passive_power.class_is_call_op(CloakingSubsystem) is True

    class NoOptIn(SensorSubsystem):
        def GetPowerWanted(self):
            return 0.0

    assert passive_power.class_is_call_op(NoOptIn) is True
    assert passive_power.class_is_call_op(SensorSubsystem) is False
    assert passive_power.class_is_call_op(TractorBeamSystem) is False


def test_instance_patched_update_power_is_a_call_op():
    ship = _ship()
    sensor = ship.GetSensorSubsystem()
    real = sensor._update_power
    sensor._update_power = lambda dt, power: real(dt, power)
    _tick(ship, PASSIVE, 3)
    assert sensor in _ops(ship)
    assert not sensor.__dict__.get("_power_frozen")


def test_zero_slider_is_a_frozen_no_op():
    ref, ship = _ship("Ref"), _ship("Passive")
    for s in (ref, ship):
        s.GetSensorSubsystem().SetPowerPercentageWanted(0.0)
    for t in range(5):
        _tick(ref, PER_TICK)
        _tick(ship, PASSIVE)
        assert _values(ref) == _values(ship), "differs at tick %d" % t
        assert _fields(ref.GetSensorSubsystem()) == _fields(ship.GetSensorSubsystem())
    sensor = ship.GetSensorSubsystem()
    assert sensor.__dict__["_power_frozen"] is True
    assert sensor not in _ops(ship)


def test_released_tractor_refreezes_and_matches_per_tick():
    """Engage then release a tractor beam: the release drops the program so
    the next rebuild can freeze the idle tractor again, and every value
    matches the per-tick model by float.hex throughout."""
    ref, ref_beam = _tractor_ship("Ref")
    ship, beam = _tractor_ship("Passive")
    tractor = ship.GetTractorBeamSystem()
    _tick(ref, PER_TICK, 2)
    _tick(ship, PASSIVE, 2)
    for step in (True, False):
        ref_beam._firing = step
        beam._firing = step
        for t in range(5):
            _tick(ref, PER_TICK)
            _tick(ship, PASSIVE)
            assert _values(ref) == _values(ship), "differs at tick %d" % t
            assert _fields(ref.GetTractorBeamSystem()) == _fields(tractor)
    _tick(ref, PER_TICK, 2)
    _tick(ship, PASSIVE, 2)
    assert _values(ref) == _values(ship)
    assert tractor.__dict__["_power_frozen"] is True
    assert tractor not in _ops(ship)


def test_equal_value_firing_write_keeps_the_program():
    """FireScript StopFiring rewrites _firing=False at up to 5 Hz: an equal
    value must not thaw the parent or drop the plant's program."""
    ship, beam = _tractor_ship("Ship")
    _tick(ship, PASSIVE, 2)
    plant = ship.GetPowerSubsystem()
    program = plant.__dict__["_passive_power"]
    thawed = passive_power.counts()["thawed"]
    beam._firing = False
    assert plant.__dict__["_passive_power"] is program
    assert passive_power.counts()["thawed"] == thawed
    assert ship.GetTractorBeamSystem().__dict__["_power_frozen"] is True
