"""The native subsystem stage over a busy combat scene (phase 6 A1). This
was Task 2's differential against the Python stage; Task 8 deleted the
Python stage (ruling R2), so no second implementation is left to compare
with: the scene now holds the native stage to what it must still do.

combat_stress at 16 ships gets the seeded op stream below, and the stage:

* skips nothing (subsystem_step.h THE SKIPS; ruling R8-1: every skip count
  is 0 at the end);
* ran every shield, power, cloak and repair piece natively (articulation:
  one RUN_PYTHON record per rigged ship per stage, one per rigless ship in
  all) and handed back the SDK events -- the cloak's completions and forced
  decloaks, the bay's cannot-complete and completions, the watchers'
  crossings;
* leaves the mirror agreeing with every Python object (the audit).

* and reproduces, tick for tick, every field it writes and every event it
  posts: the whole per-tick log is pinned as a golden
  (tests/fixtures/golden_fights/native_subsystems_scene.<platform>.json.gz,
  through tests/helpers/golden_fight.py's record/check; re-record only with
  UPDATE_COMBAT_GOLDEN=1 and a COMBAT_GOLDEN_REASON). It covers what the
  fight goldens do not: every consumer's draw fields, the cloak's reserve,
  the watchers and the repair queue under the op stream.

Review Focus 1 is pinned by a handler on shield watchers: a range check on
each face of the first few ships, fired mid-stage by the shield regen's
upward crossing, writes to the NEXT ship in the walk (its shields off or
on, a sensor slider, its main battery), which the walk then reaches the
same tick. The same handler is on those ships' battery watchers (Task 4),
fired mid-stage by a drain or a recharge crossing half charge.

Deterministic by construction: no GameLoop tick (AI draws on the unseeded module ``random``), the clock and
``random`` reset before each load, the ops from their own seeded Random.
"""
import os
import random

import App
import pytest

from engine.appc import articulation, effect_queue
from engine.appc import native_combat as nc
from engine.appc import native_subsystems, passive_state
from engine.appc.ship_iter import iter_non_rock_ships
from engine.appc.subsystems import (ShipSubsystem, _notify_key,
                                    iter_subsystems)
from engine.core import loop as game_loop
from engine.core.loop import TICK_DELTA
from tests.helpers import bc_assets, golden_fight, headless_mission

SHIPS = "16"
TICKS = 600
SEED = 20261105
OP_CHANCE = 0.2
SOURCES = 5             # ships whose shield watchers carry the handler
THRESHOLD = 0.5
KINDS = ("shield_dip", "shield_dip", "damage", "destroy", "repair_full",
         "slider", "turn_off", "turn_on", "drain", "cloak", "decloak",
         "target", "alert", "nick", "starve")

_HANDLER = {}


def ShieldWatcherHandler(_dest, evt):
    """A shield-watcher crossing on a source ship: write to the ship after it
    in the walk (Review Focus 1)."""
    world = _HANDLER.get("world")
    if world is None:
        return
    world.on_crossing(evt)


def _hex(v):
    return float(v).hex()


def _ser(v, label):
    """A field's value, comparable across the two worlds: floats by hex,
    objects by label, containers element by element."""
    if isinstance(v, bool) or v is None or isinstance(v, (int, str)):
        return v
    if isinstance(v, float):
        return v.hex()
    if isinstance(v, (list, tuple)):
        return [_ser(x, label) for x in v]
    if isinstance(v, (set, frozenset)):
        return sorted(repr(_ser(x, label)) for x in v)
    if isinstance(v, dict):
        return sorted([repr(_ser(k, label)), _ser(x, label)]
                      for k, x in v.items())
    if hasattr(v, "x") and hasattr(v, "y") and hasattr(v, "z"):
        return [_hex(v.x), _hex(v.y), _hex(v.z)]
    return label(v)


_SHIELD = ("_charge_accum", "_ramp_fraction", "_current_shields", "_is_on",
           "_power_wanted", "_power_received", "_efficiency", "_power_factor")
_PLANT = ("_available_power", "_main_battery_power", "_backup_battery_power",
          "_main_conduit_current", "_backup_conduit_current",
          "_interval_elapsed", "_power_dispensed", "_power_wanted_total",
          "_breach_fired")
_CONSUMER = ("_power_wanted", "_power_received", "_efficiency",
             "_power_factor", "_is_on", "_normal_power",
             "_power_percentage_wanted")
_CLOAK = ("_cloak_state", "_transition_elapsed", "_transition_duration",
          "_backup_reserve")
_SUBSYSTEM = ("_condition", "_threshold_state", "_in_repair_queue")
_SHIP = ("_articulation_poses", "_articulation_transitions")
_WATCHERS = ("_condition_watcher", "_combined_watcher")
TRACKED = (_SHIELD + _PLANT + _CONSUMER + _CLOAK + _SUBSYSTEM + _SHIP
           + _WATCHERS)


class _World:
    def __init__(self, mp):
        mp.setenv("DAUNTLESS_COMBAT_SHIPS", SHIPS)
        mp.delenv("DAUNTLESS_PASSIVE_STATE", raising=False)
        mp.delenv("DAUNTLESS_PASSIVE_AUDIT", raising=False)
        App.g_kTimerManager._time = 0.0
        random.seed(0)
        headless_mission.clear_in_flight()
        headless_mission.load("engine.dev_missions.combat_stress")
        passive_state.configure({})
        nc.configure({"DAUNTLESS_NATIVE_COMBAT": "1"})
        self.tick = 0
        self.in_stage = False
        self.handled = {"in_stage": 0, "outside": 0}
        self.events = []
        self.dynamic = {}
        self.ships = list(iter_non_rock_ships())
        # Rigged ships run tick_ship every tick; a rigless ship's is found
        # rigless once and then skipped natively (Task 6).
        self.rigged = sum(1 for s in self.ships
                          if articulation.rig_for(articulation.leaf_for(s)))
        assert len(self.ships) == int(SHIPS) + 1
        self.cloaked = [s for s in self.ships
                        if s.GetCloakingSubsystem() is not None]
        assert self.cloaked, "no cloak in the cast"
        self.next_ship = {}
        # Every tracked field name, once it has been seen holding a value:
        # a renamed field would otherwise compare None with None forever.
        self.seen = set()
        self._install_events(mp)
        self._install_handler()
        # Condition watchers exist once an SDK condition asks for one
        # (Conditions/ConditionSystemBelow.py): asked for here on the
        # sources' subsystems, so repair's condition writes feed them.
        for ship in self.ships[:SOURCES]:
            for sub in iter_subsystems(ship):
                sub.GetConditionWatcher()

    # ── Labels ───────────────────────────────────────────────────────────────

    def label(self, obj):
        if obj is None:
            return None
        name = obj.GetName() if hasattr(obj, "GetName") else None
        if not isinstance(name, str):
            return type(obj).__name__
        ship = obj._owning_ship() if isinstance(obj, ShipSubsystem) else None
        if ship is not None:
            return "%s/%s" % (ship.GetName(), name)
        return name

    def _etype(self, et):
        if et == getattr(self, "et", None):
            return "watcher"            # our range checks' type
        if et == getattr(self, "bet", None):
            return "battery"            # ... on the battery watchers
        if isinstance(et, int) and 1200 <= et < 0x10000:
            return self.dynamic.setdefault(et, "dyn#%d" % len(self.dynamic))
        return et

    def _install_events(self, mp):
        orig = App.g_kEventManager.AddEvent

        def add_event(evt, _orig=orig):
            payload = None
            if hasattr(evt, "GetFloat"):
                try:
                    payload = _hex(evt.GetFloat())
                except Exception:   # noqa: BLE001 -- not a float event
                    payload = None
            self.events.append((self.tick, self.in_stage,
                                self._etype(evt.GetEventType()),
                                self.label(evt.GetSource()),
                                self.label(evt.GetDestination()), payload))
            return _orig(evt)

        mp.setattr(App.g_kEventManager, "AddEvent", add_event)

    def _install_handler(self):
        self.et = App.Game_GetNextEventType()
        self.handler = __name__ + ".ShieldWatcherHandler"
        self.registered = []
        # One broadcast handler for the type: every source's crossings.
        App.g_kEventManager.AddBroadcastPythonFuncHandler(
            self.et, self.ships[0], self.handler)
        for i, ship in enumerate(self.ships[:SOURCES]):
            self.next_ship[id(ship)] = self.ships[i + 1]
            shields = ship.GetShields()
            if shields is None:
                continue
            self.registered.append(ship)
            for face in range(7):
                evt = App.TGFloatEvent_Create()
                evt.SetEventType(self.et)
                evt.SetSource(shields)
                shields.GetShieldWatcher(face).AddRangeCheck(
                    THRESHOLD, App.FloatRangeWatcher.FRW_BOTH, evt)
        assert len(self.registered) >= 3, self.registered
        # The battery watchers (Task 4: the power piece's EVENTs): both of
        # each source's plant, at half charge, either way.
        self.bet = App.Game_GetNextEventType()
        App.g_kEventManager.AddBroadcastPythonFuncHandler(
            self.bet, self.ships[0], self.handler)
        for ship in self.ships[:SOURCES]:
            plant = ship.GetPowerSubsystem()
            for watcher in (plant.GetMainBatteryWatcher(),
                            plant.GetBackupBatteryWatcher()):
                evt = App.TGFloatEvent_Create()
                evt.SetEventType(self.bet)
                evt.SetSource(plant)
                watcher.AddRangeCheck(THRESHOLD,
                                      App.FloatRangeWatcher.FRW_BOTH, evt)
        _HANDLER["world"] = self

    def close(self):
        _HANDLER.clear()
        App.g_kEventManager.RemoveBroadcastHandler(
            self.et, self.ships[0], self.handler)
        App.g_kEventManager.RemoveBroadcastHandler(
            self.bet, self.ships[0], self.handler)

    def on_crossing(self, evt):
        source = evt.GetSource().GetParentShip()
        target = self.next_ship[id(source)]
        n = self.handled["in_stage"] + self.handled["outside"]
        self.handled["in_stage" if self.in_stage else "outside"] += 1
        action = n % 5
        if action == 0:
            target.GetShields().TurnOff()
        elif action == 1:
            target.GetShields().TurnOn()
        elif action == 2:
            target.GetSensorSubsystem().SetPowerPercentageWanted(0.5)
        elif action == 3:
            plant = target.GetPowerSubsystem()
            plant.SetMainBatteryPower(plant.GetMainBatteryPower() * 0.5)
        else:
            target.GetSensorSubsystem().SetPowerPercentageWanted(1.0)
        self.events.append((self.tick, self.in_stage, "handler", action,
                            self.label(source), self.label(target)))

    # ── Ops ──────────────────────────────────────────────────────────────────

    def _damageable(self, ship):
        """Subsystems an op may damage: never the hull or the power plant
        (a dead ship or a breach would end the scene's interest)."""
        plant = ship.GetPowerSubsystem()
        return [s for s in iter_subsystems(ship)
                if s is not ship.GetHull() and s is not plant]

    def op(self, rng):
        kind = rng.choice(KINDS)
        ship = self.ships[rng.randrange(len(self.ships))]
        consumers = ship._powered_consumers
        consumer = consumers[rng.randrange(len(consumers))]
        if kind == "shield_dip":
            ship = self.registered[rng.randrange(len(self.registered))]
            shields = ship.GetShields()
            face = rng.randrange(6)
            shields.SetCurShields(face, shields.GetMaxShields(face)
                                  * rng.choice((0.3, 0.45, 0.49)))
        elif kind == "starve":
            # A cloaked ship's reserve dry: the cloak is forced off.
            ship = self.cloaked[rng.randrange(len(self.cloaked))]
            ship.GetPowerSubsystem().SetBackupBatteryPower(0.0)
        elif kind in ("damage", "destroy", "repair_full", "nick"):
            subs = self._damageable(ship)
            bay = ship.GetRepairSubsystem()
            queued = [] if bay is None else [s for s in bay._queue
                                             if s in subs]
            if kind == "destroy" and queued:
                # A queued item destroyed: the bay's CANNOT_BE_COMPLETED.
                subs = queued
            sub = subs[rng.randrange(len(subs))]
            top = sub.GetMaxCondition()
            if kind == "damage":
                sub.SetCondition(top * rng.choice((0.2, 0.5, 0.8)))
            elif kind == "nick":
                # Barely damaged: the bay completes it within the run.
                sub.SetCondition(top * 0.9995)
            elif kind == "destroy":
                sub.SetCondition(0.0)
            else:
                sub.SetCondition(top)
        elif kind == "slider":
            consumer.SetPowerPercentageWanted(rng.choice((0.0, 0.5, 1.25)))
        elif kind == "turn_off":
            consumer.TurnOff()
        elif kind == "turn_on":
            consumer.TurnOn()
        elif kind == "drain":
            ship.GetPowerSubsystem().SetMainBatteryPower(0.0)
        elif kind in ("cloak", "decloak"):
            cloak = self.cloaked[rng.randrange(len(self.cloaked))] \
                .GetCloakingSubsystem()
            if kind == "cloak":
                cloak.StartCloaking()
            else:
                cloak.StopCloaking()
        elif kind == "target":
            other = self.ships[rng.randrange(len(self.ships))]
            ship.SetTarget(None if other is ship else other)
        elif kind == "alert":
            ship.SetAlertLevel(rng.choice((App.ShipClass.GREEN_ALERT,
                                           App.ShipClass.YELLOW_ALERT,
                                           App.ShipClass.RED_ALERT)))
        else:
            raise AssertionError(kind)

    # ── The snapshot ─────────────────────────────────────────────────────────

    def _fields(self, obj, names):
        d = obj.__dict__
        out = []
        for n in names:
            v = d.get(n)
            if v is not None:
                self.seen.add(n)
            out.append(_ser(v, self.label))
        return out

    def _watchers(self, sub):
        out = []
        for attr in _WATCHERS:
            w = sub.__dict__.get(attr)
            if w is not None:
                self.seen.add(attr)
            out.append(None if w is None else _hex(w._value))
        return out

    def snapshot(self):
        rows = []
        for ship in iter_non_rock_ships():
            name = ship.GetName()
            rows.append(["ship", name] + self._fields(ship, _SHIP))
            subs = list(iter_subsystems(ship))
            labels = {_notify_key(s): self.label(s) for s in subs}
            for sub in subs:
                rows.append(["sub", self.label(sub)]
                            + self._fields(sub, _SUBSYSTEM)
                            + self._watchers(sub))
            shields = ship.GetShieldSubsystem()
            if shields is not None:
                rows.append(["shield", name]
                            + self._fields(shields, _SHIELD)
                            + [_hex(w._value)
                               for w in shields._shield_watchers])
            plant = ship.GetPowerSubsystem()
            if plant is not None:
                rows.append(["plant", name] + self._fields(plant, _PLANT)
                            + [_hex(plant._main_battery_watcher._value),
                               _hex(plant._backup_battery_watcher._value)])
            for c in ship._powered_consumers:
                rows.append(["consumer", self.label(c)]
                            + self._fields(c, _CONSUMER))
            cloak = ship.GetCloakingSubsystem()
            if cloak is not None:
                rows.append(["cloak", name] + self._fields(cloak, _CLOAK))
            bay = ship.GetRepairSubsystem()
            if bay is not None:
                rows.append(["repair", name,
                             [self.label(s) for s in bay._queue],
                             sorted(labels.get(i, "?") for i in
                                    bay._cannot_complete_notified)])
        return rows

    # ── Run ──────────────────────────────────────────────────────────────────

    def run(self):
        rng = random.Random(SEED)
        log = []
        native_subsystems.reset_counts()
        while self.tick < TICKS:
            if rng.random() < OP_CHANCE:
                self.op(rng)
            self.tick += 1
            App.g_kTimerManager._time += TICK_DELTA
            self.in_stage = True
            game_loop._update_ship_subsystems()
            self.in_stage = False
            effect_queue.boundary()
            nc.drain(boundary=True)
            events, self.events = self.events, []
            log.append((self.snapshot(), events))
        return log


def _run():
    with pytest.MonkeyPatch.context() as mp:
        world = _World(mp)
        try:
            log = world.run()
            nc._failures.clear()
            nc.audit_mirror()
            audit = list(nc._failures)
        finally:
            world.close()
        assert world.seen == set(TRACKED), (
            "tracked fields never seen holding a value (renamed?): %s"
            % sorted(set(TRACKED) - world.seen))
        return (log, dict(world.handled), native_subsystems.counts(),
                native_subsystems.event_counts(),
                native_subsystems.skip_counts(), world.rigged, audit)


@pytest.fixture(autouse=True)
def _clean():
    bc_assets.require_game_dir("data/Models/Ships/BirdOfPrey")
    nc.reset()
    yield
    nc.reset()


GOLDEN = "native_subsystems_scene"


def _golden_rows(log):
    """The log in golden_fight's canonical tick shape (tick, state, events,
    queued, calls, presented, notes); tick 0 is the scene before its first
    stage."""
    rows = [(0, [], [], [], [], [], [])]
    for t, (snap, evs) in enumerate(log, 1):
        rows.append((t, snap, evs, [], [], [], []))
    return [tuple(r) for r in golden_fight._norm(rows)]


def test_combat_scene_runs_every_piece_natively(monkeypatch):
    log, handled, counts, events, skips, rigged, audit = _run()
    monkeypatch.setitem(golden_fight.SCENES, GOLDEN, golden_fight.Scene(
        name=GOLDEN, arm="native", seed=SEED, ships=SHIPS, ticks=TICKS,
        tpf=1, run=None))
    rows = _golden_rows(log)
    golden_fight.record(GOLDEN, rows, os.environ.get("COMBAT_GOLDEN_REASON"))
    golden_fight.check(GOLDEN, rows)
    assert counts["stages"] == TICKS, counts
    assert len(log) == TICKS
    assert skips == {}, skips
    assert audit == [], audit
    # Every shield, power, cloak and repair piece ran natively
    # (articulation: one RUN_PYTHON record per rigged ship per stage, one per
    # rigless ship in all), and their SDK events -- the handler's mid-stage
    # writes among them -- came back as EVENTs.
    ships = int(SHIPS) + 1
    assert rigged < ships, "the scene needs rigless ships too"
    assert counts["run_python"] == (ships - rigged) + rigged * TICKS, \
        (counts, rigged)
    assert counts["events"] > 0, counts
    for kind in ("CLOAK_DONE", "FORCE_DECLOAK", "REPAIR_CANNOT",
                 "REPAIR_DONE", "SHIELD_WATCHER", "BATTERY_WATCHER"):
        assert events.get(kind, 0) > 0, (kind, events)
    # The scene is what it claims: the handler wrote mid-stage, and the
    # stage had work of every kind to do.
    assert handled["in_stage"] > 0, handled
    rows = [r for snap, _ in log for r in snap]
    assert any(r[0] == "repair" and r[2] for r in rows), "no repair queued"
    assert any(r[0] == "repair" and r[3] for r in rows), \
        "no repair could not be completed"
    assert {r[2] for r in rows if r[0] == "cloak"} == {0, 1, 2, 3}
    evs = [e for _, es in log for e in es]
    assert any(e[1] and e[2] == "watcher" for e in evs)
    assert any(e[1] and e[2] == "battery" for e in evs), \
        "no battery crossing in the stage"
    assert any(e[1] and e[2] == "handler" for e in evs)
    assert any(e[1] and e[2] not in ("handler", "watcher")
               for e in evs), "no stage-posted event besides ours"


def test_scene_skips_identical_writes_and_audit_is_clean(monkeypatch):
    """The stage does not log a write the mirror already holds bit for bit:
    Python holds it too (the audit proves the two agree at the end), and the
    golden of the test above is unchanged by the skipping."""
    monkeypatch.setenv("DAUNTLESS_NATIVE_AUDIT", "1")
    log, _handled, _counts, _events, skips, _rigged, audit = _run()
    stats = native_subsystems.write_stats()
    print("subsystem write stats:", stats)
    assert stats["identical"] > 0, stats
    assert stats["logged"] > 0, stats
    assert skips == {}, skips
    assert audit == [], audit
    monkeypatch.setitem(golden_fight.SCENES, GOLDEN, golden_fight.Scene(
        name=GOLDEN, arm="native", seed=SEED, ships=SHIPS, ticks=TICKS,
        tpf=1, run=None))
    golden_fight.check(GOLDEN, _golden_rows(log))


def test_a_ship_whose_shields_start_at_zero_gets_float_ramps():
    """A face never ramped holds None in Python; its first ramp must land as
    a float even when it is 0.0 (the native stage must not skip it as
    identical to the mirror's encoded 0.0)."""
    with pytest.MonkeyPatch.context() as mp:
        world = _World(mp)
        try:
            gens = []
            for ship in world.ships:
                gen = ship.GetShields()
                if gen is None:
                    continue
                gen._current_shields = [0.0] * 6
                gen._ramp_fraction = [None] * 6
                gens.append(gen)
            assert gens
            for _ in range(60):
                world.tick += 1
                App.g_kTimerManager._time += TICK_DELTA
                game_loop._update_ship_subsystems()
                effect_queue.boundary()
                nc.drain(boundary=True)
            for gen in gens:
                assert all(isinstance(r, float) for r in gen._ramp_fraction), \
                    gen._ramp_fraction
            nc._failures.clear()
            nc.audit_mirror()
            assert list(nc._failures) == [], nc._failures
        finally:
            world.close()
