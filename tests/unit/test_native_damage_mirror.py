"""The native damage mirror (native damage Task 3, spec 2026-11-02 §4.1):
every input the native hit and condition chain reads that the mirror did not
hold, pushed at every writer.

  ShieldSubsystem   _current_shields, _max_shields (lists), _ramp_fraction
                    (None as unset: `_ramp_set`), at the seven face writers
                    of damage-map-refresh §6: construction, SetMaxShields,
                    SetCurrentShields, the charge tick's ramp refresh, the
                    offline drain, the regen and ApplyDamage
  ShipSubsystem     _threshold_state, _invincible, _critical,
                    _in_repair_queue (kept by _RepairQueue), and each
                    condition watcher's check count and value
                    (`cond_watch_*` / `comb_watch_*`: -2 no watcher, -1 a
                    watcher the native chain cannot stand in for)
  ShipClass         _hurtable
  class flags       dmg_class (Subsystem) and dmg_ship (Object): which
                    stock rules the class follows, -1 / 0 for one the
                    native chain must hand to Python

Each writer is checked against the row itself (combat_dump), and the audit
(audit_mirror) must agree.
"""
import pytest

import App

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

from engine.appc import native_combat as nc
from engine.appc import weapon_subsystems as ws
from engine.appc.float_range_watcher import FloatRangeWatcher
from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass, ShipClass_Create
from engine.appc.subsystems import (HullSubsystem, RepairSubsystem,
                                    SensorSubsystem, ShieldSubsystem,
                                    ShipSubsystem)
from tests.helpers.subsystem_stage import tick_subsystem

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_effect_post_typed"),
    reason="native combat bindings not built")


@pytest.fixture(autouse=True)
def _native():
    nc.reset()
    nc.configure({"DAUNTLESS_NATIVE_COMBAT": "1"})
    assert nc.enabled()
    yield
    nc.reset()


def _row(obj):
    return _h.combat_dump(obj.__dict__["_nslot"])


def _hexes(values):
    return [float(v).hex() for v in values]


def _clean():
    nc.audit_mirror()
    assert nc.audit_failures() == []


def _ship():
    ship = ShipClass_Create("Mirror Test")
    hull = HullSubsystem("Hull")
    hull.SetMaxCondition(500.0)
    ship.SetHull(hull)
    sensor = SensorSubsystem("Sensors")
    sensor.SetMaxCondition(100.0)
    ship.SetSensorSubsystem(sensor)
    ship.SetRepairSubsystem(RepairSubsystem("Engineering"))
    shields = ShieldSubsystem("Shield Generator")
    shields.SetMaxCondition(100.0)
    for f in range(ShieldSubsystem.NUM_SHIELDS):
        shields.SetMaxShields(f, 1000.0)
        shields.SetShieldChargePerSecond(f, 40.0)
    ship.SetShieldSubsystem(shields)
    ship.SetAlertLevel(ShipClass.YELLOW_ALERT)
    return ship


def _faces(sh):
    row = _row(sh)
    return (row["_current_shields"], row["_max_shields"],
            row["_ramp_fraction"], row["_ramp_set"])


def _want(sh):
    return (_hexes(sh._current_shields), _hexes(sh._max_shields),
            [0.0 if r is None else float(r) for r in sh._ramp_fraction],
            [0 if r is None else 1 for r in sh._ramp_fraction])


def _same(sh):
    cur, mx, ramp, rset = _faces(sh)
    want = _want(sh)
    assert (_hexes(cur), _hexes(mx), _hexes(ramp), rset) == (
        want[0], want[1], _hexes(want[2]), want[3])
    _clean()


# ── The seven face writers ───────────────────────────────────────────────────

def test_construction_pushes_every_face_list():               # W1
    sh = ShieldSubsystem("Fresh")
    assert _faces(sh) == ([0.0] * 6, [0.0] * 6, [0.0] * 6, [0] * 6)
    _same(sh)


def test_set_max_shields_pushes_both_lists():                  # W2
    sh = _ship().GetShields()
    sh.SetCurrentShields(2, 0.0)
    sh.SetMaxShields(2, 600.0)          # seeds the empty face in place
    assert _faces(sh)[0][2] == 600.0 and _faces(sh)[1][2] == 600.0
    _same(sh)


def test_set_current_shields_pushes_the_face():                # W3
    sh = _ship().GetShields()
    sh.SetCurrentShields(1, 123.25)
    assert _faces(sh)[0][1] == 123.25
    sh.SetCurShields(4, 7.5)
    assert _faces(sh)[0][4] == 7.5
    _same(sh)


def test_the_charge_tick_pushes_the_ramp_refresh():            # W4
    sh = _ship().GetShields()
    sh.SetCurrentShields(0, 450.0)
    assert _faces(sh)[3] == [0] * 6     # no tick yet: every ramp unset
    tick_subsystem(sh, 0.5)
    cur, _mx, ramp, rset = _faces(sh)
    assert rset == [1] * 6 and ramp[0] == 0.45
    _same(sh)


def test_the_offline_drain_pushes_every_face():                # W5
    sh = _ship().GetShields()
    sh.SetCondition(10.0)               # disabled generator
    tick_subsystem(sh, 0.5)
    assert _faces(sh)[0] == [0.0] * 6
    _same(sh)


def test_the_regen_pushes_every_face():                        # W6
    sh = _ship().GetShields()
    sh.SetCurrentShields(3, 100.0)
    tick_subsystem(sh, 0.5)
    assert _faces(sh)[0][3] == 120.0
    _same(sh)


def test_apply_damage_pushes_the_face():                       # W7
    sh = _ship().GetShields()
    sh.ApplyDamage(0, 350.0)
    assert _faces(sh)[0][0] == 650.0
    sh.ApplyDamage(5, 5000.0)           # the overdraw branch
    assert _faces(sh)[0][5] == 0.0
    _same(sh)


# ── Subsystem and ship fields ───────────────────────────────────────────────

def test_threshold_invincible_and_critical_are_mirrored():
    ship = _ship()
    sensor = ship.GetSensorSubsystem()
    sensor.SetCondition(20.0)           # disabled: the state machine moved
    assert _row(sensor)["_threshold_state"] == sensor._threshold_state == 1
    sensor.SetInvincible(1)
    sensor.SetCritical(1)
    row = _row(sensor)
    assert (row["_invincible"], row["_critical"]) == (1, 1)
    assert _row(ship.GetHull())["_critical"] == 1     # HullSubsystem's own
    _clean()


def test_repair_queue_membership_is_mirrored():
    ship = _ship()
    sensor = ship.GetSensorSubsystem()
    bay = ship.GetRepairSubsystem()
    assert _row(sensor)["_in_repair_queue"] == 0
    sensor.SetCondition(50.0)
    from engine.appc import effect_queue
    effect_queue.boundary()             # REPAIR_ADD delivered: queued
    assert sensor._in_repair_queue is True
    assert _row(sensor)["_in_repair_queue"] == 1
    bay._queue.clear()
    assert _row(sensor)["_in_repair_queue"] == 0
    _clean()


def test_condition_watchers_are_mirrored():
    sensor = _ship().GetSensorSubsystem()
    row = _row(sensor)
    assert (row["cond_watch_checks"], row["comb_watch_checks"]) == (-2, -2)
    watcher = sensor.GetConditionWatcher()
    assert _row(sensor)["cond_watch_checks"] == 0
    evt = App.TGFloatEvent_Create()
    cid = watcher.AddRangeCheck(0.5, FloatRangeWatcher.FRW_BOTH, evt)
    assert _row(sensor)["cond_watch_checks"] == 1
    sensor.SetCondition(30.0)
    assert _row(sensor)["cond_watch_value"] == 0.3
    sensor.GetCombinedPercentageWatcher()
    assert _row(sensor)["comb_watch_checks"] == 0
    assert _row(sensor)["comb_watch_value"] == 0.3
    watcher.RemoveRangeCheck(cid)
    assert _row(sensor)["cond_watch_checks"] == 0
    _clean()


def test_a_watcher_the_chain_cannot_stand_in_for_reads_minus_one():
    class Odd(FloatRangeWatcher):
        pass
    sensor = _ship().GetSensorSubsystem()
    sensor._condition_watcher = Odd()
    assert _row(sensor)["cond_watch_checks"] == -1
    sensor._condition_watcher = None
    assert _row(sensor)["cond_watch_checks"] == -2
    _clean()


def test_hurtable_and_the_class_flags_are_mirrored():
    ship = _ship()
    assert _row(ship)["_hurtable"] == 1
    ship.SetHurtable(0)
    assert _row(ship)["_hurtable"] == 0
    assert _row(ship)["dmg_ship"] == 1
    assert _row(ship.GetSensorSubsystem())["dmg_class"] == nc.DMG_LEAF
    assert _row(ship.GetShields())["dmg_class"] == nc.DMG_LEAF
    system = ws.PhaserSystem("Phasers")
    assert _row(system)["dmg_class"] == nc.DMG_AGGREGATE
    tube = ws.TorpedoTube("Tube")
    assert _row(tube)["dmg_class"] == nc.DMG_LEAF
    _clean()


def test_a_class_overriding_the_chain_is_flagged():
    class Patched(ShipSubsystem):
        def GetConditionPercentage(self):
            return 0.5
    assert _row(Patched("odd"))["dmg_class"] == nc.DMG_PYTHON
    _clean()


# ── What K2 and K3 read to apply a hit in the kernel (native damage Task 4) ──
#
#   PhaserBank   _max_damage, _max_damage_distance, _damage_radius_factor
#                (the pulse's damage and its R_hit), from construction, the
#                property copy and SetDamageRadiusFactor
#   Torpedo      _damage, _damage_radius_factor (the K3 hit's damage and
#                R_hit), in the torpedo table: construction, SetDamage,
#                SetDamageRadiusFactor, the launcher's DRF override and the
#                launch's damage scale
#   ShipClass    _invincible, _splash_damage, _splash_damage_radius


def test_a_banks_pulse_inputs_are_mirrored():
    from engine.appc.properties import PhaserProperty
    bank = ws.PhaserBank("Bank")
    row = _row(bank)
    assert _hexes((row["_max_damage"], row["_max_damage_distance"],
                   row["_damage_radius_factor"])) == _hexes((0.0, 0.0, 0.0))
    prop = PhaserProperty("Phaser Prop")
    prop.SetMaxDamage(275.5)
    prop.SetMaxDamageDistance(61.25)
    prop.SetDamageRadiusFactor(0.375)
    bank.SetProperty(prop)
    row = _row(bank)
    assert _hexes((row["_max_damage"], row["_max_damage_distance"],
                   row["_damage_radius_factor"])) == \
        _hexes((275.5, 61.25, 0.375))
    bank.SetDamageRadiusFactor(0.125)
    assert float(_row(bank)["_damage_radius_factor"]).hex() == \
        (0.125).hex()
    _clean()


def test_a_torpedos_hit_inputs_are_mirrored():
    from engine.appc import projectiles
    nc.torpedo_table_rebuild(projectiles._active)
    t = projectiles.Torpedo()
    projectiles.register(t)
    try:
        d = _h.combat_torp_dump(t.__dict__["_k3_row"])
        assert _hexes((d["damage"], d["damage_radius_factor"])) == \
            _hexes((0.0, 0.0))
        t.SetDamage(412.5)
        t.SetDamageRadiusFactor(0.3125)
        d = _h.combat_torp_dump(t.__dict__["_k3_row"])
        assert _hexes((d["damage"], d["damage_radius_factor"])) == \
            _hexes((412.5, 0.3125))
        # The launch's damage scale (weapon_subsystems: `torp._damage =
        # float(torp._damage) * scale`) is a plain write: pushed too.
        t._damage = float(t._damage) * 1.5
        d = _h.combat_torp_dump(t.__dict__["_k3_row"])
        assert float(d["damage"]).hex() == (412.5 * 1.5).hex()
        _clean()
    finally:
        projectiles.expire(t)


def test_a_ships_invincible_and_splash_are_mirrored():
    ship = _ship()
    row = _row(ship)
    assert row["_invincible"] == 0
    assert _hexes((row["_splash_damage"], row["_splash_damage_radius"])) == \
        _hexes((0.0, 0.0))
    ship.SetInvincible(1)
    ship.SetSplashDamage(150.0, 7.5)
    row = _row(ship)
    assert row["_invincible"] == 1
    assert _hexes((row["_splash_damage"], row["_splash_damage_radius"])) == \
        _hexes((150.0, 7.5))
    ship.SetInvincible(0)
    assert _row(ship)["_invincible"] == 0
    _clean()
