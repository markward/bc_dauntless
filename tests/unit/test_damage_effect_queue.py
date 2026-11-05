"""Every effect of a hit is queued to the tick boundary (native damage,
spec docs/superpowers/specs/2026-11-02-native-damage-design.md M2, M5, §4.3;
controller rulings R7-R9), in BOTH switch states.

A condition write and a hit change state at once; what they REPORT goes into
the combat effect queue as the damage kinds -- COND_WATCH, SUBSYS_EVENT,
REPAIR_ADD, ZERO_CROSS (the boundary death check), SPLASH, HIT_PRESENT,
WEAPON_HIT -- in today's synchronous order minus nesting, and is delivered
at a BOUNDARY (effect_queue.boundary: the tick's combat flush, the host's
frame-end drain, a host-less GameLoop tick's end). Outside the tick scope
they are held until then (R8), never delivered at the end of the call.
"""
import logging

import App
import pytest

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_effect_take"),
    reason="combat effect queue bindings not built")

from engine.appc import effect_queue as eq  # noqa: E402
from engine.appc import internal_blast, ship_death  # noqa: E402
from engine.appc import subsystem_cascade, warp_core_breach  # noqa: E402
from engine.appc.combat import apply_hit  # noqa: E402
from engine.appc.float_range_watcher import FloatRangeWatcher  # noqa: E402
from engine.appc.math import TGPoint3  # noqa: E402
from engine.appc.ships import ShipClass, ShipClass_Create  # noqa: E402
from engine.appc.subsystems import (HullSubsystem, PowerSubsystem,  # noqa: E402
                                    RepairSubsystem, SensorSubsystem,
                                    ShieldSubsystem)
from tests.helpers.subsystem_stage import tick_subsystem

DAMAGE_KINDS = ("COND_WATCH", "SUBSYS_EVENT", "REPAIR_ADD", "ZERO_CROSS",
                "SPLASH", "HIT_PRESENT", "WEAPON_HIT")


@pytest.fixture(autouse=True)
def _clean():
    eq.reset()
    subsystem_cascade.reset()
    warp_core_breach.reset()
    yield
    eq.reset()
    subsystem_cascade.reset()
    warp_core_breach.reset()


@pytest.fixture
def events(monkeypatch):
    """Every AddEvent, as (type, destination), in post order."""
    log = []
    orig = App.g_kEventManager.AddEvent

    def add_event(evt, _orig=orig):
        log.append((evt.GetEventType(), evt.GetDestination()))
        return _orig(evt)

    monkeypatch.setattr(App.g_kEventManager, "AddEvent", add_event)
    return log


@pytest.fixture
def delivered(monkeypatch):
    """Every queue delivery, as (kind name, operands), in delivery order."""
    log = []

    def wrap(kind, fn):
        def deliver(*ops):
            log.append((eq.KIND_NAMES[kind], ops))
            return fn(*ops)
        return deliver

    monkeypatch.setattr(eq, "_DELIVER", tuple(
        wrap(k, fn) for k, fn in enumerate(eq._DELIVER)))
    return log


@pytest.fixture
def scratch_set():
    """A registered set (the splash walks registered sets), dropped after."""
    name = "DamageQueueTest"
    pset = App.SetClass_Create()
    App.g_kSetManager.AddSet(pset, name)
    yield pset
    App.g_kSetManager.DeleteSet(name)


def _ship(name="Keldon", hull_max=1000.0):
    """A hull (critical, disabled below 50%), a sensor array mounted at the
    hit point (0, 10, 0), a repair bay and a shield generator, shields down.
    Everything but the sensor sits at the origin, out of the splash."""
    ship = ShipClass_Create(name)
    hull = HullSubsystem("Hull")
    hull.SetMaxCondition(hull_max)
    hull.SetCritical(1)
    hull.SetDisabledPercentage(0.5)
    ship.SetHull(hull)
    sensor = SensorSubsystem("Sensor Array")
    sensor.SetMaxCondition(100.0)
    sensor.SetRadius(1.0)
    sensor._position = TGPoint3(0.0, 10.0, 0.0)
    ship.SetSensorSubsystem(sensor)
    ship.SetRepairSubsystem(RepairSubsystem("Engineering"))
    ss = ShieldSubsystem("Shield Generator")
    ss.SetMaxCondition(100.0)
    for f in range(ShieldSubsystem.NUM_SHIELDS):
        ss.SetMaxShields(f, 1000.0)
        ss.SetCurrentShields(f, 0.0)
    ship.SetShieldSubsystem(ss)
    ship._radius = 20.0
    ship.SetAlertLevel(ShipClass.YELLOW_ALERT)
    return ship


_AT = TGPoint3(0.0, 10.0, 0.0)


def _check(watcher, threshold=0.5):
    evt = App.TGFloatEvent_Create()
    evt.SetEventType(App.ET_AI_SYSTEM_STATUS_WATCHER)
    return watcher.AddRangeCheck(threshold, FloatRangeWatcher.FRW_BOTH, evt)


def _queued():
    """The queue's entries, taken (undelivered): (kind name, operands)."""
    return [(eq.KIND_NAMES[k], ops) for k, _native, ops
            in _h.combat_effect_take()]


def _peek():
    """The queue's entries, left queued in their order -- each put back the
    way it was posted: a Python entry through eq.post, a native one (native
    damage: objects named by mirror handle) as a native entry typed by its
    kind's layout, so its delivery still resolves the handles."""
    taken = _h.combat_effect_take()
    for kind, native, ops in taken:
        if native:
            # A native entry may carry a Python object where its layout
            # names a handle (a producer without its row): typed as an
            # object ("H") there, as the binding took it.
            types = "".join(
                "H" if t == "R" and not isinstance(v, int) else t
                for t, v in zip(eq.OPERANDS[kind], ops))
            _h.combat_effect_post_typed(kind, types, *ops)
        else:
            eq.post(kind, *ops)
    return [(eq.KIND_NAMES[k], ops) for k, _native, ops in taken]


# ── The kinds ────────────────────────────────────────────────────────────────

def test_the_damage_kinds_follow_the_weapon_kinds_in_the_native_order():
    assert eq.KIND_NAMES[-len(DAMAGE_KINDS):] == DAMAGE_KINDS
    assert _h.combat_effect_kinds() == {
        name: i for i, name in enumerate(eq.KIND_NAMES)}


# ── Emission: today's synchronous order, minus nesting ───────────────────────

def test_a_hit_emits_its_effects_in_todays_order():
    ship = _ship()
    killer = _ship("Killer")
    hull, sensor = ship.GetHull(), ship.GetSensorSubsystem()
    _check(hull.GetCombinedPercentageWatcher())
    _check(sensor.GetConditionWatcher())

    apply_hit(ship, 800.0, _AT, source=killer, weapon_type="phaser")

    assert hull.GetCondition() == 200.0          # the state changed at once
    assert sensor.GetCondition() == 0.0
    got = [(kind, ops[:2]) for kind, ops in _queued()]
    assert got == [
        # the hull: 1000 -> 200, its watcher, DISABLED, the repair queue
        ("COND_WATCH", (hull, eq.WATCH_COMBINED)),
        ("SUBSYS_EVENT", (hull, eq.SUBSYS_DISABLED)),
        ("REPAIR_ADD", (hull,)),
        # the sensor: 100 -> 0, a zero crossing (not critical: no death)
        ("COND_WATCH", (sensor, eq.WATCH_CONDITION)),
        ("SUBSYS_EVENT", (sensor, eq.SUBSYS_DESTROYED)),
        ("REPAIR_ADD", (sensor,)),
        ("ZERO_CROSS", (ship, sensor)),
        # then the hit itself: presentation, ET_WEAPON_HIT
        ("HIT_PRESENT", (ship, killer)),
        ("WEAPON_HIT", (ship, killer)),
    ]


def test_each_kind_carries_its_contract_fields():
    ship = _ship()
    killer = _ship("Killer")
    hull, sensor = ship.GetHull(), ship.GetSensorSubsystem()
    _check(hull.GetCombinedPercentageWatcher())

    apply_hit(ship, 800.0, _AT, source=killer, weapon_type="phaser")

    entries = dict()
    for kind, ops in _queued():
        entries.setdefault(kind, ops)
    assert entries["COND_WATCH"] == (hull, eq.WATCH_COMBINED, 1.0, 0.2)
    assert entries["ZERO_CROSS"] == (ship, sensor, True, killer)
    present = dict(zip(eq.HIT_PRESENT_FIELDS, entries["HIT_PRESENT"]))
    assert present["ship"] is ship and present["source"] is killer
    assert present["absorbed_hull"] == 800.0
    assert present["subsystem"] is sensor
    assert present["weapon_type"] == eq.HIT_WEAPON_PHASER
    hit = dict(zip(eq.WEAPON_HIT_FIELDS, entries["WEAPON_HIT"]))
    assert hit["ship"] is ship and hit["source"] is killer
    assert hit["damage"] == 800.0
    assert (hit["hit_x"], hit["hit_y"], hit["hit_z"]) == (0.0, 10.0, 0.0)
    assert hit["subsystem"] is sensor and hit["is_hull_hit"] is True
    assert hit["weapon_type"] == eq.WEAPON_HIT_PHASER


# ── Held outside the scope; delivered at the boundary ────────────────────────

def test_a_hit_outside_the_scope_reports_nothing_until_the_boundary(events):
    ship = _ship()
    del events[:]                                # the ship's own setup
    apply_hit(ship, 800.0, _AT, source=None)
    assert ship.GetHull().GetCondition() == 200.0
    assert events == []

    eq.boundary()

    types = [t for t, _ in events]
    assert App.ET_SUBSYSTEM_DISABLED in types
    assert App.ET_SUBSYSTEM_DESTROYED in types
    assert types[-1] == App.ET_WEAPON_HIT


def test_handlers_run_at_the_flush_and_see_every_same_tick_hit(events,
                                                              monkeypatch):
    """Two hits in one tick, then the boundary: each ET_WEAPON_HIT handler
    sees both hits applied (M2: the handler runs at the flush, not inside
    the hit)."""
    ship = _ship()
    hull = ship.GetHull()
    seen = []
    orig = App.g_kEventManager.AddEvent

    def spy(evt, _orig=orig):
        if evt.GetEventType() == App.ET_WEAPON_HIT:
            seen.append(hull.GetCondition())
        return _orig(evt)

    monkeypatch.setattr(App.g_kEventManager, "AddEvent", spy)
    with eq.scope():
        apply_hit(ship, 100.0, TGPoint3(0.0, -10.0, 0.0), source=None)
        apply_hit(ship, 100.0, TGPoint3(0.0, -10.0, 0.0), source=None)
    assert seen == [800.0, 800.0]


def test_a_handlers_flag_takes_effect_after_the_flush_never_retroactively(
        monkeypatch):
    """Review Focus 3: a WEAPON_HIT handler makes the ship unhurtable. Both
    same-tick hits already landed; a hit after the flush takes nothing."""
    ship = _ship()
    hull = ship.GetHull()
    orig = App.g_kEventManager.AddEvent

    def spy(evt, _orig=orig):
        if evt.GetEventType() == App.ET_WEAPON_HIT:
            ship.SetHurtable(0)
        return _orig(evt)

    monkeypatch.setattr(App.g_kEventManager, "AddEvent", spy)
    away = TGPoint3(0.0, -10.0, 0.0)
    apply_hit(ship, 100.0, away, source=None)
    apply_hit(ship, 100.0, away, source=None)
    eq.boundary()
    assert hull.GetCondition() == 800.0          # both landed
    apply_hit(ship, 100.0, away, source=None)
    assert hull.GetCondition() == 800.0          # the flag, from now on


def test_a_handlers_invincibility_saves_the_ship_from_a_same_tick_kill(
        monkeypatch):
    """Review Focus 3 for SetInvincible (M5, "invincible by then"): the
    first hit's ET_WEAPON_HIT handler makes the ship invincible; the second,
    killing hit of the same tick has its death check later in the flush, so
    the ship survives at hull 0. Unlike SetHurtable, which only stops later
    hits, the death check reads the flag as of its delivery."""
    ship = _ship()
    hull = ship.GetHull()
    orig = App.g_kEventManager.AddEvent

    def spy(evt, _orig=orig):
        if evt.GetEventType() == App.ET_WEAPON_HIT:
            ship.SetInvincible(1)
        return _orig(evt)

    monkeypatch.setattr(App.g_kEventManager, "AddEvent", spy)
    away = TGPoint3(0.0, -10.0, 0.0)
    with eq.scope():
        apply_hit(ship, 100.0, away, source=None)
        apply_hit(ship, 5000.0, away, source=None)
    assert hull.GetCondition() == 0.0
    assert not ship.IsDying()
    assert subsystem_cascade._active == []


def test_a_condition_watcher_commits_at_once_and_fires_the_checks_at_delivery():
    """Ruling E3 for condition watchers: the value is committed in the write;
    delivery fires the checks crossed, as registered THEN."""
    ship = _ship()
    hull = ship.GetHull()
    watcher = hull.GetConditionWatcher()
    fired = []
    first = _check(watcher)
    hull.SetCondition(200.0)
    assert watcher.GetWatchedVariable() == 0.2   # committed at once
    watcher.RemoveRangeCheck(first)
    evt = App.TGFloatEvent_Create()
    evt.SetEventType(App.ET_AI_SYSTEM_STATUS_WATCHER)
    watcher.AddRangeCheck(0.5, FloatRangeWatcher.FRW_BELOW, evt)
    orig = watcher._fire
    watcher._fire = lambda e, v: (fired.append((e, v)), orig(e, v))

    eq.boundary()

    assert fired == [(evt, 0.2)]


def test_a_destroyed_subsystem_queues_its_internal_blast_at_delivery(
        monkeypatch):
    ship = _ship()
    sensor = ship.GetSensorSubsystem()
    blasts = []
    monkeypatch.setattr(internal_blast, "queue", blasts.append)
    ship.DamageSystem(sensor, 500.0)
    assert blasts == []
    eq.boundary()
    assert blasts == [sensor]


def test_the_repair_list_is_added_to_at_delivery(events):
    ship = _ship()
    hull = ship.GetHull()
    bay = ship.GetRepairSubsystem()
    hull.SetCondition(900.0)
    assert bay._queue == []
    eq.boundary()
    assert bay._queue == [hull]
    assert (App.ET_ADD_TO_REPAIR_LIST, bay) in events


def _repairing_ship():
    """_ship with a working bay: 50 points, 3 teams."""
    from engine.appc.properties import RepairSubsystemProperty
    ship = _ship()
    bay = ship.GetRepairSubsystem()
    bay.SetMaxCondition(8000.0)
    prop = RepairSubsystemProperty("Engineering")
    prop.SetMaxRepairPoints(50.0)
    prop.SetNumRepairTeams(3)
    bay.SetProperty(prop)
    return ship


def test_a_repair_bay_tick_emits_no_repair_add():
    """Ruling I3: REPAIR_ADD is emitted only when the subsystem is not in its
    bay's queue already, so a bay working an item emits nothing for it."""
    ship = _repairing_ship()
    hull = ship.GetHull()
    bay = ship.GetRepairSubsystem()
    hull.SetCondition(500.0)
    eq.boundary()
    assert bay._queue == [hull] and hull._in_repair_queue is True
    tick_subsystem(bay, 1.0)
    assert 500.0 < hull.GetCondition() < 1000.0      # repaired, still below
    assert "REPAIR_ADD" not in [k for k, _ in _queued()]
    hull.SetCondition(400.0)                          # damaged again, queued
    assert "REPAIR_ADD" not in [k for k, _ in _queued()]


def test_leaving_the_repair_queue_clears_the_membership():
    """The flag follows the queue: completion, a cleared list and a demote
    to the tail; a subsystem out of the queue emits REPAIR_ADD again."""
    ship = _repairing_ship()
    hull = ship.GetHull()
    bay = ship.GetRepairSubsystem()
    hull.SetCondition(999.0)
    eq.boundary()
    tick_subsystem(bay, 1.0)                                   # completes it
    assert bay._queue == [] and hull._in_repair_queue is False
    hull.SetCondition(500.0)
    assert [k for k, _ in _queued()].count("REPAIR_ADD") == 1
    hull.SetCondition(500.0)
    eq.boundary()
    bay.HandleIncreasePriority(hull)                  # demoted, still queued
    assert hull._in_repair_queue is True
    bay._queue.clear()                                # as repair_ship_fully
    assert hull._in_repair_queue is False
    hull.SetCondition(400.0)
    assert [k for k, _ in _queued()].count("REPAIR_ADD") == 1


# ── ZERO_CROSS: the death check, in emission order (R7) ──────────────────────

def test_a_ship_hit_again_after_its_killing_hit_dies_once(delivered, events):
    """Review Focus 1: the second hit damages, begins no second death; one
    death, one SPLASH, after the first hit's entries."""
    ship = _ship()
    ship.SetSplashDamage(100.0, 5.0)
    sensor = ship.GetSensorSubsystem()
    with eq.scope():
        apply_hit(ship, 5000.0, TGPoint3(0.0, -10.0, 0.0), source=None)
        assert not ship.IsDying()                 # not inside the hit (M5)
        apply_hit(ship, 50.0, _AT, source=None)
        assert sensor.GetCondition() == 50.0      # the second hit damages
    kinds = [k for k, _ in delivered]
    assert kinds.count("SPLASH") == 1
    first_hit = kinds.index("WEAPON_HIT")
    assert kinds.index("SPLASH") > first_hit
    assert kinds.index("SPLASH") > len(kinds) - 1 - kinds[::-1].index(
        "WEAPON_HIT")                             # after both hits' entries
    assert [t for t, _ in events].count(App.ET_OBJECT_EXPLODING) == 1
    assert sum(1 for rec in ship_death._active if rec["ship"] is ship) == 1


def test_the_killing_hits_death_precedes_its_weapon_hit(events):
    """R7 restores inventory rule R2: ZERO_CROSS is emitted at the write, so
    ET_OBJECT_EXPLODING (posted by its delivery) precedes the hit's
    ET_WEAPON_HIT."""
    ship = _ship()
    apply_hit(ship, 5000.0, TGPoint3(0.0, -10.0, 0.0), source=None)
    eq.boundary()
    types = [t for t, _ in events]
    assert types.index(App.ET_OBJECT_EXPLODING) < types.index(App.ET_WEAPON_HIT)


def test_the_splash_is_delivered_after_the_exploding_handlers(monkeypatch):
    """M2: SPLASH follows its ET_OBJECT_EXPLODING, so a handler there (E2M2's
    partner invincibility) runs before the splash lands."""
    from engine.appc import splash_damage
    ship = _ship()
    ship.SetSplashDamage(100.0, 5.0)
    order = []
    orig = App.g_kEventManager.AddEvent

    def spy(evt, _orig=orig):
        if evt.GetEventType() == App.ET_OBJECT_EXPLODING:
            order.append("exploding")
        return _orig(evt)

    monkeypatch.setattr(App.g_kEventManager, "AddEvent", spy)
    monkeypatch.setattr(splash_damage, "apply",
                        lambda s, ship_instances=None: order.append("splash"))
    ship.DestroySystem(ship.GetHull())
    eq.boundary()
    assert order == ["exploding", "splash"]


def test_a_splash_chain_is_delivered_in_one_flush_and_ends(events,
                                                          scratch_set):
    """Review Focus 2: a splash victim dies and splashes; every entry is
    delivered in the same boundary, and the chain ends (_out_of_action)."""
    a, b, c = _ship("A"), _ship("B"), _ship("C")
    for i, s in enumerate((a, b, c)):
        s.SetTranslateXYZ(0.0, 30.0 * i, 0.0)
        s.SetSplashDamage(1e6, 60.0)
        s.SetRadius(1.0)
        scratch_set.AddObjectToSet(s, s.GetName())
    a.DestroySystem(a.GetHull())

    eq.boundary()

    assert all(s.IsDying() for s in (a, b, c))
    exploding = [d for t, d in events if t == App.ET_OBJECT_EXPLODING]
    assert sorted(id(d) for d in exploding) == sorted(id(s) for s in (a, b, c))
    assert _h.combat_effect_size() == 0


def test_an_invincible_ship_at_hull_zero_is_not_killed_retroactively():
    """Review Focus 5 through a hit: no death, no cascade, the hull stays at
    0; clearing the flag kills nothing until the next write leaves a
    critical subsystem at 0 (R4)."""
    ship = _ship()
    ship.SetInvincible(1)
    away = TGPoint3(0.0, -10.0, 0.0)
    apply_hit(ship, 5000.0, away, source=None)
    eq.boundary()
    assert ship.GetHull().GetCondition() == 0.0
    assert not ship.IsDying()
    assert subsystem_cascade._active == []
    ship.SetInvincible(0)
    eq.boundary()
    assert not ship.IsDying()
    apply_hit(ship, 1.0, away, source=None)
    eq.boundary()
    assert ship.IsDying()


# ── R8: held until a BOUNDARY, never by a session's end ──────────────────────

def test_a_native_session_outside_the_scope_does_not_deliver_held_damage(
        delivered):
    """A K1 session from gl.ai ends between a script's hull 0 and the
    boundary: its own entries are delivered at its end (ruling F3), the held
    damage kinds wait for the boundary (R8)."""
    ship = _ship()
    hull = ship.GetHull()
    hull.SetCondition(0.0)                       # a script's write: held
    with eq.session():
        eq.post(eq.TORPEDO_RELOAD, _Tube())
    assert [k for k, _ in delivered] == ["TORPEDO_RELOAD"]
    assert not ship.IsDying()
    ship.SetInvincible(1)                        # KillGonDev's next line
    eq.boundary()
    assert "ZERO_CROSS" in [k for k, _ in delivered]
    assert not ship.IsDying()


class _Tube:
    def _broadcast_reload(self):
        pass


@pytest.mark.parametrize("arm", ["python", "native"])
def test_damage_held_across_a_sessions_end_keeps_its_order(arm, delivered,
                                                          events):
    """Review M1: a whole killing hit is held across a native session's end
    and delivered at the boundary in emission order -- its death (ZERO_CROSS,
    ET_OBJECT_EXPLODING) before its ET_WEAPON_HIT (R2). Both damage arms:
    the Python producer (DAUNTLESS_NATIVE_COMBAT=0) and native damage (the
    default), whose entries name objects by mirror handle."""
    from engine.appc import native_combat as nc
    from tests.helpers.native_off import ZERO
    nc.configure(ZERO if arm == "python" else {})
    assert nc.enabled() is (arm == "native")
    before = nc.damage_counts()["hits"]
    ship = _ship()
    ship.SetSplashDamage(100.0, 5.0)
    apply_hit(ship, 5000.0, _AT, source=None)    # outside the scope: held
    assert nc.damage_counts()["hits"] - before == (arm == "native")
    emitted = [k for k, _ in _peek()]
    assert emitted.index("ZERO_CROSS") < emitted.index("WEAPON_HIT")
    with eq.session():
        eq.post(eq.TORPEDO_RELOAD, _Tube())
    del events[:]
    eq.boundary()
    kinds = [k for k, _ in delivered]
    assert kinds[0] == "TORPEDO_RELOAD"
    assert kinds[1:] == emitted + ["SPLASH"]
    types = [t for t, _ in events]
    assert types.index(App.ET_OBJECT_EXPLODING) < types.index(App.ET_WEAPON_HIT)


def test_a_host_less_game_loop_tick_is_a_boundary_and_the_hosts_is_not():
    from engine.core.loop import GameLoop
    ship = _ship()
    ship.GetHull().SetCondition(0.0)
    GameLoop(owns_boundary=False).tick()
    assert not ship.IsDying()
    GameLoop().tick()
    assert ship.IsDying()


# ── I2: the per-tick boundary is "sim.effects" in both switch states ─────────

@pytest.fixture
def profiler():
    from engine.core import frame_profiler as fp
    fp.set_enabled(False, native=False)
    fp.reset()
    fp.set_enabled(True, native=False)
    yield fp
    fp.set_enabled(False, native=False)
    fp.reset()


@pytest.mark.parametrize("native", [False, True])
def test_the_tick_boundary_is_timed_as_sim_effects_in_both_switch_states(
        native, profiler, monkeypatch):
    """Ruling I2: a tick's hits report under "sim.effects" whichever the
    switch, once per tick -- with it off that is _combat_tick_boundary's own
    row, with it on the scope's exit flush (the boundary after it is then
    empty) -- so "sim.combat" is like for like in both states."""
    from engine import host_loop
    from engine.appc import native_combat as nc
    fp = profiler
    stacks = []
    real = eq._DELIVER[eq.WEAPON_HIT]
    monkeypatch.setattr(
        eq, "_DELIVER",
        eq._DELIVER[:eq.WEAPON_HIT] + (
            lambda *ops: (stacks.append(list(fp._scope_stack)),
                          real(*ops)),) + eq._DELIVER[eq.WEAPON_HIT + 1:])
    nc.reset()
    if native:
        nc.configure({"DAUNTLESS_NATIVE_COMBAT": "1"})
    try:
        ship = _ship()
        fp.begin_frame()
        with fp.scope("sim"):
            with host_loop._combat_effect_scope():
                with fp.scope("sim.combat"):
                    apply_hit(ship, 100.0, _AT, source=None)
            host_loop._combat_tick_boundary()
        fp.end_frame()
    finally:
        nc.reset()
    assert stacks == [["sim", "sim.effects"]]
    assert fp.calls()["sim.effects"] == 1
    assert fp.parents()["sim.effects"] == "sim"


# ── R9: the destroyed-plant trigger is the same seam ─────────────────────────

def _plant_ship(critical):
    ship = _ship()
    plant = PowerSubsystem("Warp Core")
    plant.SetMaxCondition(100.0)
    plant.SetCritical(1 if critical else 0)
    plant.SetTargetable(1)
    ship.SetPowerSubsystem(plant)
    return ship, plant


def test_a_destroyed_plant_kills_at_the_boundary_through_the_seam():
    """R9: PowerSubsystem's destroyed-plant trigger emits ZERO_CROSS; the
    breach arms and the ship dies at the boundary, even with a non-critical
    plant (a breach destroys the ship)."""
    ship, plant = _plant_ship(critical=False)
    plant._condition = 0.0                       # destroyed, unannounced
    tick_subsystem(plant, 0.1)
    assert not ship.IsDying()
    assert warp_core_breach._armed == []
    eq.boundary()
    assert ship.IsDying()
    assert warp_core_breach._armed == [ship]


def test_a_destroyed_plant_on_a_ship_invincible_by_the_boundary_does_nothing():
    ship, plant = _plant_ship(critical=False)
    plant._condition = 0.0
    tick_subsystem(plant, 0.1)
    ship.SetInvincible(1)
    eq.boundary()
    assert not ship.IsDying()
    assert warp_core_breach._armed == []


# ── Decision 13 on the new kinds ─────────────────────────────────────────────

def test_a_raising_delivery_does_not_stop_the_rest_and_is_raised_under_tests(
        events, monkeypatch):
    ship = _ship()
    _check(ship.GetHull().GetCombinedPercentageWatcher())

    def boom(self, old, new):
        raise RuntimeError("watcher boom")

    monkeypatch.setattr(FloatRangeWatcher, "_fire_crossed", boom)
    apply_hit(ship, 800.0, _AT, source=None)
    with pytest.raises(RuntimeError, match="watcher boom"):
        eq.boundary()
    assert App.ET_WEAPON_HIT in [t for t, _ in events]
    assert eq.counts()["failed"] == 1


def test_in_play_a_raising_delivery_is_logged_and_the_rest_delivered(
        events, monkeypatch, caplog):
    ship = _ship()
    _check(ship.GetHull().GetCombinedPercentageWatcher())

    def boom(self, old, new):
        raise RuntimeError("watcher boom")

    monkeypatch.setattr(FloatRangeWatcher, "_fire_crossed", boom)
    monkeypatch.setattr(eq, "_strict", lambda modules=None: False)
    apply_hit(ship, 800.0, _AT, source=None)
    with caplog.at_level(logging.ERROR, logger=eq.__name__):
        eq.boundary()
    assert App.ET_WEAPON_HIT in [t for t, _ in events]
    assert "COND_WATCH delivery raised" in caplog.text
