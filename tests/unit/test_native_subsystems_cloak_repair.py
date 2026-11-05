"""The native cloak and repair pieces (phase 6 A1, Task 5; subsystem_step.h
THE CLOAK PIECE, THE REPAIR PIECE): the cloak's transition and the repair
bay's tick, native only since Task 8 (there is no Python copy), their SDK
events handed back to Python as EVENT records at the point BC posts them.
The goldens pin them bit for bit; these pin the contract one piece at a
time.
"""
import random

import App
import pytest

from engine.appc import effect_queue
from engine.appc import native_combat as nc
from engine.appc import native_subsystems
from engine.appc.ship_iter import iter_non_rock_ships
from engine.appc.subsystems import _notify_key, iter_subsystems
from engine.core import loop as game_loop
from tests.helpers import bc_assets, headless_mission

SHIPS = 3               # the player and two combat ships
_CLOAK = ("_cloak_state", "_transition_elapsed", "_transition_duration",
          "_backup_reserve")

_HANDLER = {}


def RepairCannotHandler(_dest, evt):
    """ET_REPAIR_CANNOT_BE_COMPLETED, fired mid-walk: the scene's queue
    edit (test_handler_editing_the_queue_mid_walk)."""
    edit = _HANDLER.get("edit")
    if edit is not None:
        edit(evt)


@pytest.fixture(autouse=True)
def _clean():
    bc_assets.require_game_dir("data/Models/Ships/BirdOfPrey")
    nc.reset()
    yield
    _HANDLER.clear()
    nc.reset()


def _world(mp):
    mp.setenv("DAUNTLESS_COMBAT_SHIPS", "2")
    App.g_kTimerManager._time = 0.0
    random.seed(0)
    headless_mission.clear_in_flight()
    headless_mission.load("engine.dev_missions.combat_stress")
    nc.configure({"DAUNTLESS_NATIVE_COMBAT": "1"})
    ships = list(iter_non_rock_ships())
    assert len(ships) == SHIPS
    return ships


def _events(mp, types):
    """Every AddEvent of one of `types`, in order: (type, source label)."""
    log = []
    mgr = App.g_kEventManager
    orig = mgr.AddEvent

    def add_event(e, _orig=orig):
        if e.GetEventType() in types:
            src = e.GetSource()
            log.append((e.GetEventType(),
                        src.GetName() if hasattr(src, "GetName") else None))
        return _orig(e)
    mp.setattr(mgr, "AddEvent", add_event)
    return log


def _tick(n=1):
    for _ in range(n):
        App.g_kTimerManager._time += game_loop.TICK_DELTA
        game_loop._update_ship_subsystems()
        effect_queue.boundary()


def _hex(v):
    return float(v).hex() if isinstance(v, float) else v


def _repair_state(ships):
    """Every field the repair piece writes: the queue, the notified set
    (by label), every subsystem's condition and threshold state."""
    rows = []
    for ship in ships:
        subs = list(iter_subsystems(ship))
        names = {_notify_key(s): s.GetName() for s in subs}
        bay = ship.GetRepairSubsystem()
        rows.append([s.GetName() for s in bay._queue])
        rows.append(sorted(names.get(k, "?")
                           for k in bay._cannot_complete_notified))
        rows.append([(s.GetName(), _hex(s._condition), s._threshold_state,
                      s._in_repair_queue) for s in subs])
    return rows


def _cloak_state(cloak):
    return [_hex(cloak.__dict__[n]) for n in _CLOAK]


def _no_skips():
    """Every piece ran: none was skipped (subsystem_step.h THE SKIPS)."""
    assert native_subsystems.skip_counts() == {}


def _damage(sub, fraction):
    sub.SetCondition(sub.GetMaxCondition() * fraction)


def test_mission_set_max_repair_points_reaches_the_native_step():
    """Review Focus 2, the E2M0 shape (DamageSovereign: ``pRepair =
    pShip.GetRepairSubsystem(); pProp = pRepair.GetProperty();
    pProp.SetMaxRepairPoints(0.0)``, later 50.0): a SHARED
    RepairSubsystemProperty template changed at runtime is what the next
    native repair tick reads, for every bay using it -- the setter pushes
    the template's one mirror row."""
    with pytest.MonkeyPatch.context() as mp:
        ships = _world(mp)
        a, b = (s.GetRepairSubsystem() for s in ships[1:])
        prop = a.GetProperty()
        b.SetProperty(prop)             # the two now share a template
        for ship in ships[1:]:
            for sub in list(iter_subsystems(ship))[2:5]:
                _damage(sub, 0.4)
        _tick(1)                        # REPAIR_ADD delivered: queued
        native_subsystems.reset_counts()
        before = _repair_state(ships)
        _tick(30)
        moving = _repair_state(ships)
        prop.SetMaxRepairPoints(0.0)    # E2M0:754, the template once
        _tick(1)
        frozen = _repair_state(ships)
        _tick(30)
        still = _repair_state(ships)
        prop.SetMaxRepairPoints(50.0)   # E2M0:2935
        _tick(60)
        row = nc._h.combat_dump(prop.__dict__["_nslot"])
        after = _repair_state(ships)
        counts = native_subsystems.counts()
    assert moving != before, "nothing was repaired before the change"
    # Repair stopped for both bays the tick after the template went to 0.
    assert frozen == still
    assert row["MaxRepairPoints"] == 50.0 and row["repair_props_ok"] == 1
    assert after != still, "the restored points repaired nothing"
    assert counts["stages"] == 121
    _no_skips()


def test_handler_editing_the_queue_mid_walk():
    """Review Focus 5: ET_REPAIR_CANNOT_BE_COMPLETED fires while the bay
    walks its queue, and its handler edits the queue -- a damaged member
    the walk has NOT reached yet is removed, which shifts every later
    member down one index. The walk goes on as Python's list iterator does
    (the next index of the list as it is now): the native piece re-reads
    the queue from the mirror, which every edit pushed. A walk over the
    queue as it was at begin would still repair the removed member."""
    def run():
        with pytest.MonkeyPatch.context() as mp:
            ships = _world(mp)
            ship = ships[1]
            bay = ship.GetRepairSubsystem()
            subs = [s for s in iter_subsystems(ship)
                    if s is not bay and s is not ship.GetHull()
                    and s is not ship.GetPowerSubsystem()]
            x, y, z, w = subs[:4]
            log = _events(mp, (App.ET_REPAIR_CANNOT_BE_COMPLETED,
                               App.ET_REPAIR_COMPLETED))

            def edit(evt):
                if evt.GetObjPtr() is x and any(s is y for s in bay._queue):
                    bay._queue.remove(y)        # not reached yet
            _HANDLER["edit"] = edit
            App.g_kEventManager.AddBroadcastPythonFuncHandler(
                App.ET_REPAIR_CANNOT_BE_COMPLETED, ship,
                __name__ + ".RepairCannotHandler")
            bay._queue.extend([x, y, z, w])
            x.SetCondition(0.0)
            _damage(y, 0.5)
            _damage(z, 0.9995)          # completes within the run
            _damage(w, 0.5)
            y_before = y._condition
            effect_queue.boundary()
            native_subsystems.reset_counts()
            states = []
            for _ in range(90):
                _tick(1)
                states.append(_repair_state(ships))
            App.g_kEventManager.RemoveBroadcastHandler(
                App.ET_REPAIR_CANNOT_BE_COMPLETED, ship,
                __name__ + ".RepairCannotHandler")
            assert y._condition == y_before     # removed before its turn
            return (states, list(log), native_subsystems.counts(),
                    native_subsystems.event_counts())

    _states, log, counts, events = run()
    # CANNOT once (x is told once), then the completion of z.
    assert [t for t, _ in log].count(App.ET_REPAIR_CANNOT_BE_COMPLETED) == 1
    assert any(t == App.ET_REPAIR_COMPLETED for t, _ in log)
    assert events.get("REPAIR_CANNOT", 0) >= 1, events
    assert events.get("REPAIR_DONE", 0) >= 1, events
    _no_skips()


def test_cloak_completion_and_forced_decloak():
    """The cloak's transition completes natively (CLOAK_DONE: the state
    written, then Python's _fire), and a dry reserve forces it off
    (FORCE_DECLOAK: Python's _force_decloak), in that order."""
    def run():
        with pytest.MonkeyPatch.context() as mp:
            ships = _world(mp)
            ship = next(s for s in ships
                        if s.GetCloakingSubsystem() is not None)
            cloak = ship.GetCloakingSubsystem()
            log = _events(mp, (App.ET_CLOAK_COMPLETED,
                               App.ET_DECLOAK_COMPLETED))
            native_subsystems.reset_counts()
            states = []
            _tick(5)
            cloak.StartCloaking()
            for _ in range(300):
                _tick(1)
                states.append(_cloak_state(cloak))
            ship.GetPowerSubsystem().SetBackupBatteryPower(0.0)
            for _ in range(30):
                _tick(1)
                states.append(_cloak_state(cloak))
            cloak.StartCloaking()
            for _ in range(10):
                _tick(1)
                states.append(_cloak_state(cloak))
            return (states, list(log), native_subsystems.counts(),
                    native_subsystems.event_counts(), cloak)

    states, log, counts, events, cloak = run()
    assert [t for t, _ in log] == [App.ET_CLOAK_COMPLETED,
                                   App.ET_DECLOAK_COMPLETED]
    assert events.get("CLOAK_DONE", 0) == 1, events
    assert events.get("FORCE_DECLOAK", 0) >= 1, events
    # Cloaked, then forced off by the dry reserve, then held off by it.
    assert [cloak.CLOAK_CLOAKED] in [[st[0]] for st in states[:300]]
    assert states[-1][0] == cloak.CLOAK_DECLOAKED
    _no_skips()


def test_the_mirror_agrees_after_native_repairs_and_cloaks():
    """The audit: every field the two pieces wrote back -- the cloak's
    clock and state, the bay's notified set, the items' conditions -- and
    every queue change pushed is what the mirror holds."""
    with pytest.MonkeyPatch.context() as mp:
        ships = _world(mp)
        for ship in ships[1:]:
            subs = list(iter_subsystems(ship))[2:6]
            for sub in subs:
                _damage(sub, 0.4)
            subs[0].SetCondition(0.0)
            cl = ship.GetCloakingSubsystem()
            if cl is not None:
                cl.StartCloaking()
        _tick(120)
        ships[1].GetRepairSubsystem().HandleIncreasePriority(
            ships[1].GetRepairSubsystem()._queue[-1])
        _tick(5)
        nc._failures.clear()
        nc.audit_mirror()
        assert nc._failures == []


def test_every_queue_reordering_pushes_the_mirrored_order():
    """The mirror holds the queue's ORDER (the native walk's): the in-place
    reorderings list inherits -- sort, reverse, *= -- push it like every
    other mutator, and keep each member's _in_repair_queue."""
    from engine.appc.subsystems import RepairSubsystem, ShipSubsystem
    nc.configure({"DAUNTLESS_NATIVE_COMBAT": "1"})
    bay = RepairSubsystem("Repair")
    subs = [ShipSubsystem("S%d" % i) for i in range(3)]
    bay._queue.extend(subs)

    def mirrored():
        return nc._h.combat_dump(bay.__dict__["_nslot"])["_queue"]

    def handles():
        return [s.__dict__["_nslot"] for s in bay._queue]
    bay._queue.reverse()
    assert mirrored() == handles() == [s.__dict__["_nslot"]
                                       for s in reversed(subs)]
    bay._queue.sort(key=lambda s: s.GetName())
    assert mirrored() == handles() == [s.__dict__["_nslot"] for s in subs]
    bay._queue *= 2
    assert mirrored() == handles() and len(handles()) == 6
    assert all(s._in_repair_queue for s in subs)
    bay._queue *= 0
    assert mirrored() == [] and not any(s._in_repair_queue for s in subs)


def test_an_item_the_native_chain_cannot_repair_is_repaired_alone_in_python():
    """Ruling R8-3: a worked item whose condition write the native damage
    chain hands back (here a condition watcher it cannot stand in for) is
    repaired by itself through its SDK-facing ``Repair`` (REPAIR_SET), with
    the same share as every other worked item; the items before and after
    it stay native, and nothing is skipped."""
    from engine.appc.float_range_watcher import FloatRangeWatcher

    class _Foreign(FloatRangeWatcher):
        pass

    with pytest.MonkeyPatch.context() as mp:
        ships = _world(mp)
        ship = ships[1]
        bay = ship.GetRepairSubsystem()
        subs = [s for s in iter_subsystems(ship)
                if s is not bay and s is not ship.GetHull()
                and s is not ship.GetPowerSubsystem()]
        a, b, c = subs[:3]
        for sub in (a, b, c):
            _damage(sub, 0.5)
        b._condition_watcher = _Foreign()
        effect_queue.boundary()
        bay._queue.clear()
        bay._queue.extend([a, b, c])
        bay.GetProperty().SetNumRepairTeams(3)
        before = [s._condition for s in (a, b, c)]
        native_subsystems.reset_counts()
        _tick(1)
        events = native_subsystems.event_counts()
        after = [s._condition for s in (a, b, c)]
    assert events.get("REPAIR_SET") == 1, events
    shares = [(y - x) * s.GetRepairComplexity()
              for x, y, s in zip(before, after, (a, b, c))]
    assert shares[0] > 0.0
    assert shares[1] == pytest.approx(shares[0])
    assert shares[2] == pytest.approx(shares[0])
    _no_skips()
