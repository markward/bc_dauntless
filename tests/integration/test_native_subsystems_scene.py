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

import App
import pytest

from engine.appc import effect_queue
from engine.appc import native_combat as nc
from engine.appc import native_subsystems
from engine.core import loop as game_loop
from engine.core.loop import TICK_DELTA
from tests.helpers import bc_assets, golden_fight
from tests.helpers.subsystems_scene import (SEED, SHIPS, TICKS, _World,
                                            canonical_rows, run)

@pytest.fixture(autouse=True)
def _clean():
    bc_assets.require_game_dir("data/Models/Ships/BirdOfPrey")
    nc.reset()
    yield
    nc.reset()


GOLDEN = "native_subsystems_scene"


def test_combat_scene_runs_every_piece_natively(monkeypatch):
    log, handled, counts, events, skips, rigged, audit = run()
    monkeypatch.setitem(golden_fight.SCENES, GOLDEN, golden_fight.Scene(
        name=GOLDEN, arm="native", seed=SEED, ships=SHIPS, ticks=TICKS,
        tpf=1, run=None))
    rows = canonical_rows(log)
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
    log, _handled, _counts, _events, skips, _rigged, audit = run()
    stats = native_subsystems.write_stats()
    print("subsystem write stats:", stats)
    assert stats["identical"] > 0, stats
    assert stats["logged"] > 0, stats
    assert skips == {}, skips
    assert audit == [], audit
    monkeypatch.setitem(golden_fight.SCENES, GOLDEN, golden_fight.Scene(
        name=GOLDEN, arm="native", seed=SEED, ships=SHIPS, ticks=TICKS,
        tpf=1, run=None))
    golden_fight.check(GOLDEN, canonical_rows(log))


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
