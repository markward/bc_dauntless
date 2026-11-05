"""The native subsystem stage against the Python stage, tick for tick (phase
6 A1, Task 2; plan docs/superpowers/plans/2026-11-05-phase6-b0-a1-
subsystems.md, ruling R2: the Python ``Update`` methods are the bit-exact
oracle until Task 8 deletes them).

Two fresh loads of combat_stress at 16 ships, one with
``DAUNTLESS_NATIVE_SUBSYSTEMS=0`` (the Python loop in
engine/core/loop.py) and one with the switch on (the native session and its
driver, engine/appc/native_subsystems.py), get the same seeded op stream
and are compared after EVERY tick for exact equality (floats by
``.hex()``):

* every field the stage writes (the stage map's §2,
  docs/superpowers/plans/2026-11-05-phase6-a1-subsystem-stage-map.md): the
  shield generator's charge accumulator, ramp and faces; the plant's
  batteries, conduits, interval, dispensed and wanted totals and breach
  latch; every consumer's draw fields; the cloak's state, transition and
  reserve; the repair queue and its cannot-complete set; every subsystem's
  condition, threshold state and queue flag; the articulation poses and
  transitions;
* every watcher's value (seven shield watchers, both battery watchers,
  each subsystem's condition watchers);
* every event posted (type, source, destination, payload), in order, and
  whether it was posted inside the stage.

Review Focus 1 is pinned by a handler on shield watchers: a range check on
each face of the first few ships, fired mid-stage by the shield regen's
upward crossing, writes to the NEXT ship in the walk (its shields off or
on, a sensor slider, its main battery), which the walk then reaches the
same tick.

Deterministic by construction, as test_passive_power_differential.py: no
GameLoop tick (AI draws on the unseeded module ``random``), the clock and
``random`` reset before each load, the ops from their own seeded Random.
"""
import random

import App
import pytest

from engine.appc import effect_queue
from engine.appc import native_combat as nc
from engine.appc import native_subsystems, passive_state
from engine.appc.ship_iter import iter_non_rock_ships
from engine.appc.subsystems import ShipSubsystem, iter_subsystems
from engine.core import loop as game_loop
from engine.core.loop import TICK_DELTA
from tests.helpers import bc_assets, headless_mission

SHIPS = "16"
TICKS = 600
SEED = 20261105
OP_CHANCE = 0.2
SOURCES = 5             # ships whose shield watchers carry the handler
THRESHOLD = 0.5
KINDS = ("shield_dip", "shield_dip", "damage", "destroy", "repair_full",
         "slider", "turn_off", "turn_on", "drain", "cloak", "decloak",
         "target", "alert")

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


class _World:
    def __init__(self, mp, native):
        mp.setenv("DAUNTLESS_COMBAT_SHIPS", SHIPS)
        mp.delenv("DAUNTLESS_PASSIVE_STATE", raising=False)
        mp.delenv("DAUNTLESS_PASSIVE_AUDIT", raising=False)
        App.g_kTimerManager._time = 0.0
        random.seed(0)
        headless_mission.clear_in_flight()
        headless_mission.load("engine.dev_missions.combat_stress")
        passive_state.configure({})
        nc.configure({"DAUNTLESS_NATIVE_COMBAT": "1",
                      "DAUNTLESS_NATIVE_SUBSYSTEMS": "1" if native else "0"})
        assert native_subsystems.enabled() is native
        self.native = native
        self.tick = 0
        self.in_stage = False
        self.handled = {"in_stage": 0, "outside": 0}
        self.events = []
        self.dynamic = {}
        self.ships = list(iter_non_rock_ships())
        assert len(self.ships) == int(SHIPS) + 1
        self.cloaked = [s for s in self.ships
                        if s.GetCloakingSubsystem() is not None]
        assert self.cloaked, "no cloak in the cast"
        self.next_ship = {}
        self._install_events(mp)
        self._install_handler()

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
        _HANDLER["world"] = self

    def close(self):
        _HANDLER.clear()
        App.g_kEventManager.RemoveBroadcastHandler(
            self.et, self.ships[0], self.handler)

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
        elif kind in ("damage", "destroy", "repair_full"):
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
        return [_ser(d.get(n), self.label) for n in names]

    def _watchers(self, sub):
        out = []
        for attr in ("_condition_watcher", "_combined_watcher"):
            w = sub.__dict__.get(attr)
            out.append(None if w is None else _hex(w._value))
        return out

    def snapshot(self):
        rows = []
        for ship in iter_non_rock_ships():
            name = ship.GetName()
            rows.append(["ship", name] + self._fields(ship, _SHIP))
            subs = list(iter_subsystems(ship))
            labels = {id(s): self.label(s) for s in subs}
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


def _arm(native):
    with pytest.MonkeyPatch.context() as mp:
        world = _World(mp, native)
        try:
            log = world.run()
        finally:
            world.close()
        return log, dict(world.handled), native_subsystems.counts()


def _first_difference(a, b):
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return i, x, y
    return len(a), a[len(b):], b[len(a):]


@pytest.fixture(autouse=True)
def _clean():
    bc_assets.require_game_dir("data/Models/Ships/BirdOfPrey")
    nc.reset()
    yield
    nc.reset()


def test_differential_combat_scene_bit_exact():
    python, py_handled, py_counts = _arm(native=False)
    native, na_handled, na_counts = _arm(native=True)
    assert py_counts["stages"] == 0, py_counts
    assert na_counts["stages"] == TICKS, na_counts
    assert na_counts["run_python"] > 0, na_counts
    assert len(python) == len(native) == TICKS
    for tick, ((ps, pe), (ns, ne)) in enumerate(zip(python, native), 1):
        if ps != ns:
            i, x, y = _first_difference(ps, ns)
            pytest.fail("tick %d: stage state differs at row %d\n python %r\n"
                        " native %r" % (tick, i, x, y))
        if pe != ne:
            i, x, y = _first_difference(pe, ne)
            pytest.fail("tick %d: events differ at %d\n python %r\n native %r"
                        % (tick, i, x, y))
    # The scene is what it claims: the handler wrote mid-stage, and the
    # stage had work of every kind to do.
    assert na_handled == py_handled
    assert py_handled["in_stage"] > 0, py_handled
    rows = [r for snap, _ in python for r in snap]
    assert any(r[0] == "repair" and r[2] for r in rows), "no repair queued"
    assert any(r[0] == "repair" and r[3] for r in rows), \
        "no repair could not be completed"
    assert {r[2] for r in rows if r[0] == "cloak"} == {0, 1, 2, 3}
    events = [e for _, evs in python for e in evs]
    assert any(e[1] and e[2] == "watcher" for e in events)
    assert any(e[1] and e[2] == "handler" for e in events)
    assert any(e[1] and e[2] not in ("handler", "watcher")
               for e in events), "no stage-posted event besides ours"
