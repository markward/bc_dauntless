"""Immunity flags and the boundary death check (spec
docs/superpowers/specs/2026-11-02-native-damage-design.md, rulings M1, M3,
M5, R2, R4, R5).

* M1: ShipClass.SetHurtable(0) -- the ship takes no damage.
  ShipClass.SetInvincible(1) -- damage lands, the ship never begins dying.
  ShipSubsystem.SetInvincible(1) -- that subsystem takes no damage.
* M3 + M5: a critical subsystem at 0 kills, from ANY condition write
  (DamageSystem, SetCondition, SetConditionPercentage, severance), but the
  check runs at the tick boundary (death_check.drain), re-reading
  invincibility there -- E3M5's KillGonDev zeroes the hull, THEN sets the
  ship invincible, and the derelict must survive.
* R5: the zero crossings (hull cascade, breach arm) follow the same rule.
* R4: clearing invincibility does not kill retroactively.
"""
import pytest

from engine.appc import death_check, ship_death, subsystem_cascade, warp_core_breach
from engine.appc.combat import apply_hit
from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass, ShipClass_Create
from engine.appc.subsystems import (HullSubsystem, PowerSubsystem,
                                    SensorSubsystem, ShieldSubsystem)


@pytest.fixture(autouse=True)
def _clean():
    death_check.reset()
    subsystem_cascade.reset()
    warp_core_breach.reset()
    yield
    death_check.reset()
    subsystem_cascade.reset()
    warp_core_breach.reset()


def _ship(name="Keldon", hull_max=1000.0, face_max=1000.0):
    ship = ShipClass_Create(name)
    hull = HullSubsystem("Hull")
    hull.SetMaxCondition(hull_max)
    hull.SetCritical(1)
    ship.SetHull(hull)
    ss = ShieldSubsystem("Shield Generator")
    ss.SetMaxCondition(100.0)
    ss.SetDisabledPercentage(0.25)
    for f in range(ShieldSubsystem.NUM_SHIELDS):
        ss.SetMaxShields(f, face_max)
    ship.SetShieldSubsystem(ss)
    ship._radius = 20.0
    ship.SetAlertLevel(ShipClass.YELLOW_ALERT)
    return ship


def _drop_shields(ship):
    for f in range(ShieldSubsystem.NUM_SHIELDS):
        ship.GetShields().SetCurrentShields(f, 0.0)


# ── M1: what each flag means ──────────────────────────────────────────────────

def test_unhurtable_ship_takes_no_damage():
    ship = _ship()
    ship.SetHurtable(0)
    _drop_shields(ship)
    apply_hit(ship, 5000.0, TGPoint3(0, 10, 0), source=None)
    assert ship.GetHull().GetCondition() == 1000.0


def test_unhurtable_ship_shields_take_no_damage():
    ship = _ship()
    ship.SetHurtable(0)
    ship.GetShields().SetCurrentShields(0, 1000.0)
    apply_hit(ship, 300.0, TGPoint3(0, 10, 0), source=None)
    assert ship.GetShields().GetCurrentShields(0) == 1000.0


def test_invincible_ship_takes_damage():
    ship = _ship()
    ship.SetInvincible(1)
    _drop_shields(ship)
    apply_hit(ship, 400.0, TGPoint3(0, 10, 0), source=None)
    assert ship.GetHull().GetCondition() == 600.0


def test_invincible_ship_never_dies_at_hull_zero():
    ship = _ship()
    ship.SetInvincible(1)
    _drop_shields(ship)
    apply_hit(ship, 5000.0, TGPoint3(0, 10, 0), source=None)
    death_check.drain()
    assert ship.GetHull().GetCondition() == 0.0
    assert ship.IsDying() == 0
    assert ship.IsDead() == 0


def test_invincible_ship_at_hull_zero_keeps_its_systems():
    """R5: no hull cascade (and no breach arm) for an invincible ship."""
    ship = _ship()
    ship.SetInvincible(1)
    ship.DamageSystem(ship.GetHull(), 5000.0)
    death_check.drain()
    assert subsystem_cascade._active == []


def test_invincible_ship_reactor_at_zero_does_not_arm_a_breach(monkeypatch):
    armed = []
    monkeypatch.setattr(warp_core_breach, "arm", lambda s: armed.append(s))
    ship = _ship()
    core = PowerSubsystem("Warp Core")
    core.SetMaxCondition(500.0)
    ship.SetPowerSubsystem(core)
    ship.SetInvincible(1)
    ship.DamageSystem(core, 900.0)
    death_check.drain()
    assert armed == []


def test_invincible_ship_destroyed_reactor_does_not_breach_on_update(monkeypatch):
    """The plant's own destroyed-reactor trigger (PowerSubsystem.Update ->
    _trigger_breach) honours invincibility too: no breach, no death."""
    armed = []
    monkeypatch.setattr(warp_core_breach, "arm", lambda s: armed.append(s))
    ship = _ship()
    core = PowerSubsystem("Warp Core")
    core.SetMaxCondition(500.0)
    ship.SetPowerSubsystem(core)
    ship.SetInvincible(1)
    core._condition = 0.0                 # destroyed, by whatever path
    core.Update(1.0 / 60.0)
    death_check.drain()
    assert armed == []
    assert ship.IsDying() == 0


def test_invincible_subsystem_takes_nothing():
    ship = _ship()
    sensor = SensorSubsystem("Sensor Array")
    sensor.SetMaxCondition(400.0)
    sensor.SetRadius(5.0)
    sensor._position = TGPoint3(0.0, 10.0, 0.0)
    ship.SetSensorSubsystem(sensor)
    sensor.SetInvincible(1)
    apply_hit(ship, 300.0, TGPoint3(0, 10, 0), source=None,
              splash_radius=5.0, bypass_shields=True)
    assert sensor.GetCondition() == 400.0
    assert ship.GetHull().GetCondition() < 1000.0


# ── M3 + M5: a critical subsystem at 0 kills, at the boundary ────────────────

def test_damage_system_kills_at_the_boundary_not_in_the_write():
    ship = _ship()
    ship.DamageSystem(ship.GetHull(), 5000.0)
    assert ship.IsDying() == 0            # not inside the write (M5)
    death_check.drain()
    assert ship.IsDying() == 1


def test_set_condition_zero_on_the_hull_kills_at_the_boundary():
    ship = _ship()
    ship.GetHull().SetCondition(0.0)
    assert ship.IsDying() == 0
    death_check.drain()
    assert ship.IsDying() == 1


def test_set_condition_percentage_zero_on_the_hull_kills_at_the_boundary():
    ship = _ship()
    ship.GetHull().SetConditionPercentage(0.0)
    death_check.drain()
    assert ship.IsDying() == 1


def test_hull_zero_crossing_schedules_the_cascade_at_the_boundary():
    ship = _ship()
    ship.GetHull().SetCondition(0.0)
    assert subsystem_cascade._active == []
    death_check.drain()
    assert [e["ship"] for e in subsystem_cascade._active] == [ship]


def test_non_critical_subsystem_at_zero_does_not_kill():
    ship = _ship()
    sensor = SensorSubsystem("Sensor Array")
    sensor.SetMaxCondition(100.0)
    ship.SetSensorSubsystem(sensor)
    sensor.SetCondition(0.0)
    death_check.drain()
    assert ship.IsDying() == 0


def test_hull_zeroed_then_made_invincible_survives():
    """E3M5 KillGonDev: SetCondition(0) on the hull, then SetInvincible(1)."""
    ship = _ship()
    ship.GetHull().SetCondition(0)
    ship.SetInvincible(1)
    death_check.drain()
    assert ship.IsDying() == 0
    assert subsystem_cascade._active == []


def test_hull_restored_before_the_boundary_does_not_die():
    ship = _ship()
    ship.GetHull().SetCondition(0.0)
    ship.GetHull().SetCondition(500.0)
    death_check.drain()
    assert ship.IsDying() == 0


def test_clearing_invincibility_does_not_kill_retroactively():
    """R4: the derelict sat at hull 0 while invincible; making it vulnerable
    kills nothing until the next write leaves a critical subsystem at 0."""
    ship = _ship()
    ship.GetHull().SetCondition(0)
    ship.SetInvincible(1)
    death_check.drain()
    ship.SetInvincible(0)
    death_check.drain()
    assert ship.IsDying() == 0
    ship.DamageSystem(ship.GetHull(), 1.0)
    death_check.drain()
    assert ship.IsDying() == 1


def test_the_death_carries_the_killer(monkeypatch):
    begun = []
    monkeypatch.setattr(ship_death, "begin",
                        lambda s, killer=None: begun.append((s, killer)))
    ship = _ship()
    shooter = _ship("Shooter")
    ship.DamageSystem(ship.GetHull(), 5000.0, shooter)
    death_check.drain()
    assert begun == [(ship, shooter)]


def test_two_fatal_writes_begin_one_death(monkeypatch):
    begun = []
    real = ship_death.begin

    def spy(s, killer=None):
        begun.append(s)
        real(s, killer=killer)
    monkeypatch.setattr(ship_death, "begin", spy)
    ship = _ship()
    ship.DamageSystem(ship.GetHull(), 5000.0)
    ship.DamageSystem(ship.GetHull(), 5000.0)
    death_check.drain()
    assert begun == [ship]
    ship_death.reset()


def test_severed_critical_subsystem_kills(monkeypatch):
    """R2: a part carrying a critical subsystem severs -> the ship dies at
    the boundary (the old severance bypass is closed)."""
    from engine.appc import articulation, part_severance, physical_parents
    ship = _ship()
    hull = ship.GetHull()
    monkeypatch.setattr(articulation, "leaf_for", lambda s: None)
    monkeypatch.setattr(part_severance, "_mounted_subsystems",
                        lambda s: [(hull, (0.0, 0.0, 0.0))])
    monkeypatch.setattr(physical_parents, "property_of", lambda s: None)
    monkeypatch.setattr(physical_parents, "part_for_property",
                        lambda leaf, prop, point, iid: "saucer")
    assert part_severance._destroy_subsystems_on_part(ship, "saucer") == [hull]
    death_check.drain()
    assert ship.IsDying() == 1


# ── where the boundary is ─────────────────────────────────────────────────────

def test_a_headless_game_loop_tick_is_a_boundary():
    from engine.core.loop import GameLoop
    ship = _ship()
    ship.GetHull().SetCondition(0.0)
    GameLoop().tick()
    assert ship.IsDying() == 1


def test_a_host_owned_game_loop_tick_leaves_the_check_to_the_host():
    """Live, the boundary is the host's per-tick combat flush
    (host_loop._combat_tick_boundary), so a GameLoop the host drives does not
    drain: a script's write waits for the flush."""
    from engine.core.loop import GameLoop
    ship = _ship()
    ship.GetHull().SetCondition(0.0)
    GameLoop(owns_boundary=False).tick()
    assert ship.IsDying() == 0
    death_check.drain()
    assert ship.IsDying() == 1


def test_reset_drops_pending_checks():
    ship = _ship()
    ship.GetHull().SetCondition(0.0)
    death_check.reset()
    death_check.drain()
    assert ship.IsDying() == 0
