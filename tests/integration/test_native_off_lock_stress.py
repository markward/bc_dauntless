"""The kernels compute with the GIL released while another Python thread
churns: nothing it does reaches the fight (kernels off the lock, Task 3; spec
docs/superpowers/specs/2026-11-03-kernels-off-the-lock-design.md goal 4,
plan Review Focus 5).

The 64-ship combat_stress fight, switch on, driven the host's way with the
K1 differential's seeded op stream (tests/integration/
tests/helpers/k1_fight.py's _Scene), is fought twice from fresh loads
with the same seeds:

- the reference, alone;
- the stressed arm, with a churn thread. Each tick the main loop wakes it
  (an Event), lets it run through the tick's ops, weapons and combat, then
  halts it and waits for it (two more) before the tick boundary, so its
  work is bounded and lands inside the tick. Its batch makes cyclic garbage
  with __del__ methods and weakref finalizers and collects it (cyclic GC on
  the churn thread, which also collects the fight's own garbage there:
  mirror-row and transform-slot finalizers off the main thread), and makes
  cyclic "pushers" whose __del__ writes a live ship's `_radius` / `_scale`
  back to itself: an idempotent NativeField push from whichever thread
  collects it. The switch interval is shortened so the thread takes the GIL
  at every compute release, and the GIL probe (host_bindings.cc GilProbe)
  holds the tick's first compute call until the thread has stepped: it
  provably runs Python while a kernel computes with the GIL released.

Compared:
- per tick, the K1 differential's record (every weapon system and bank,
  every ship's hull and shields, every torpedo in flight; floats by
  .hex()), the ordered event log with each hit's payload, the queued
  weapon events, every apply_hit in order and the presentation per tick;
- the pushes the churn's pushers made OFF the main thread are exactly the
  ones the drains applied for them, by label, in order and in the tick they
  were made (Task 2 queues them and re-pushes the value at the drain, so the
  labels, not values, are the queue's evidence). A pusher collected on the
  main thread pushed directly, as today, and is not queued.

The pushers are idempotent, so the state comparison alone could not see a
race on them. The RATE WRITES can (final review I1): every RATE_EVERY ticks
the churn thread, while K0's first compute call of the tick is held with the
GIL released, writes a DIFFERENT `_recharge_rate` into a charging phaser
bank (a NativeField K0 reads), then steps the probe so K0 computes. The
reference arm's main thread makes the same write at the same point: right
after the drain that applies the stressed arm's queued push (the first
drain after K0's session, by `nc.drain`'s own rule). So "deferred to the
drain" fights the same fight, and a write that reached the mirror during
compute charges that bank at the new rate a tick early: the per-tick record
(every bank's charge level) differs. The mirror is also read before and
after that drain: the old rate until it, the new one after.
"""
import gc
import random
import sys
import threading
import time
import weakref

import pytest

import App

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

from engine import host_loop
from engine.appc import combat
from engine.appc import effect_queue
from engine.appc import native_combat as nc
from engine.appc import sensor_contacts
from engine.appc import weapon_subsystems as ws
from engine.appc.objects import ObjectClass
from engine.appc.ship_iter import iter_ships
from engine.core import ids
from engine.core import loop as game_loop
from engine.core.loop import TICK_DELTA
from tests.helpers import bc_assets, effect_split
from tests.helpers.k3_fight import compare_calls
from tests.helpers import k1_fight as k1d

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_gil_probe_arm"),
    reason="native combat bindings (GIL probe) not built")

SHIPS = "64"
TICKS = 600
# Headless ships have radius 0, so no torpedo could touch one (the K3
# differential's note): a nominal hull, so K3 hits land and apply_hits runs.
RADIUS = 4.0
# The churn thread's work per tick: until halted, at most MAX_BATCH.
MAX_BATCH = 20000       # iterations
PUSH_EVERY = 25         # a pusher every this many iterations
COLLECT_EVERY = 100     # a gen-0 collection every this many
HOLD_MS = 2000.0        # the held compute call's wait for a step, at most
WAIT_S = 60.0           # the main loop's wait for a batch, at most
SWITCH_S = 1e-4         # the stressed arm's switch interval
SPARES = 2              # spare Object rows dropped as garbage each tick
RATE_EVERY = 25         # a rate write every this many ticks (I1)

_MAIN = threading.main_thread().ident


@pytest.fixture(autouse=True)
def _needs_assets_and_hermetic_mods(monkeypatch, tmp_path):
    bc_assets.require_game_dir("data/Models/Ships/Galaxy")
    monkeypatch.setenv("DAUNTLESS_MODS_DIR", str(tmp_path / "empty_mods"))
    nc.reset()
    _h.combat_gil_probe_arm(False)
    _h.combat_gil_probe_take()
    yield
    _h.combat_gil_probe_arm(False)
    _h.combat_gil_probe_take()
    nc.reset()


class _Node:
    """Cyclic garbage with a finalizer."""

    def __init__(self, churn):
        self.churn = churn
        self.peer = None
        self.payload = [churn.made] * 8

    def __del__(self):
        self.churn.deleted += 1


class _Pusher:
    """Cyclic garbage whose __del__ writes a live ship's field back to
    itself: an idempotent NativeField push, from the collecting thread."""

    def __init__(self, churn, field):
        self.churn = churn
        self.field = field
        self.me = self

    def __del__(self):
        c, ship = self.churn, self.churn.ship
        setattr(ship, self.field, ship.__dict__[self.field])
        c.issued.append((c.tick, self.field,
                         threading.get_ident() != _MAIN))


class _Churn(threading.Thread):
    def __init__(self, ship):
        super().__init__(name="off-lock-churn", daemon=True)
        self.ship = ship
        self.go = threading.Event()
        self.halt = threading.Event()
        self.done = threading.Event()
        self.quit = False
        self.error = None
        self.tick = 0
        self.made = self.deleted = self.finalized = 0
        self.issued = []        # (tick, field, off_main) per pusher __del__
        # The tick's rate write (I1): set by the main thread as K0's first
        # compute call starts (k0_entered), made by batch() before its first
        # step, which is what lets the held call compute.
        self.rate_tick = False
        self.rate_write = None          # (bank, new rate)
        self.k0_entered = threading.Event()
        self.rate_written = threading.Event()

    def _finalized(self):
        self.finalized += 1

    def run(self):
        while True:
            self.go.wait()
            self.go.clear()
            if self.quit:
                self.done.set()
                return
            try:
                # Automatic collection only inside the batch: one this
                # thread's allocations triggered after the batch (signalling
                # done, waiting for go) could collect a pusher past the
                # tick's last drain, and its push would drain the tick after
                # it was labelled (final review M8). The batch's own last
                # collection runs with it already disabled.
                gc.enable()
                self.batch()
            except BaseException as e:      # reported by the main thread
                self.error = e
            finally:
                gc.disable()
                self.done.set()

    def batch(self):
        step = _h.combat_gil_probe_step
        fields = ("_radius", "_scale")
        if self.rate_tick:
            # K0 is held in compute, GIL released, until this thread steps.
            assert self.k0_entered.wait(WAIT_S), "K0 never started"
            bank, rate = self.rate_write
            bank._recharge_rate = rate          # off the main thread
            self.rate_written.set()
        i = 0
        while i < MAX_BATCH and not self.halt.is_set():
            step()
            a, b = _Node(self), _Node(self)
            a.peer, b.peer = b, a
            weakref.finalize(a, self._finalized)
            self.made += 2
            if i % PUSH_EVERY == 0:
                _Pusher(self, fields[(i // PUSH_EVERY) % 2])
            del a, b
            if i % COLLECT_EVERY == COLLECT_EVERY - 1:
                gc.collect(0)
            i += 1
        gc.disable()
        gc.collect(1)


def _rate_bank(scene):
    """The tick's rate write (I1): a registered phaser bank charging with
    room for a whole tick at its rate (so halving the rate changes its
    charge), from a start that walks the bank list; (bank, new rate, old
    rate), or None. Both arms are the same fight here, so pick alike."""
    banks = [w for w in scene.emitters if isinstance(w, ws.PhaserBank)]
    start = (scene.tick // RATE_EVERY) % len(banks)
    for w in banks[start:] + banks[:start]:
        d = w.__dict__
        rate = d.get("_recharge_rate", 0.0)
        if (d.get("_nslot") is not None and rate > 0.0
                and d["_max_charge"] - d["_charge_level"] > rate * TICK_DELTA):
            return w, rate * 0.5, rate
    return None


def _arm(monkeypatch, churn):
    """One fresh fight, fought TICKS ticks; `churn` True runs the churn
    thread. Returns the scene, with the drained pushers' labels and the
    churn's tallies."""
    with monkeypatch.context() as mp:
        apply_hit = combat.apply_hit
        scene = k1d._Scene(mp, k1d.ON, ships=SHIPS)
        # The scene spies on combat.apply_hit, which hands every hit to
        # Python (a patched damage path): unpatched, the kernels apply
        # damage natively, inside compute. The per-tick record holds every
        # ship's hull and shields, and the event log every hit's payload.
        mp.setattr(combat, "apply_hit", apply_hit)
        for s in scene.ships:
            s.SetRadius(RADIUS)
        target = scene.player
        # The drains' applications of a queued NativeField push on the
        # pushers' ship, in order (native_combat._repush_native, which only
        # a drain calls).
        scene.drained = []
        repush = nc._repush_native

        def repush_spy(obj, field, _orig=repush):
            if obj is target:
                scene.drained.append((scene.tick, field._name))
            return _orig(obj, field)
        mp.setattr(nc, "_repush_native", repush_spy)
        # Frees recorded off the main thread (the fight's own finalizers,
        # run by a collection the churn thread made).
        scene.off_main_frees = 0
        defer = nc.defer_free

        def defer_spy(*a, _orig=defer, **kw):
            if threading.get_ident() != _MAIN:
                scene.off_main_frees += 1
            return _orig(*a, **kw)
        mp.setattr(nc, "defer_free", defer_spy)
        # Where frees are APPLIED: only a drain, on the main thread.
        scene.applied_frees = {True: 0, False: 0}     # off main -> count
        apply_free = nc._apply_free

        def apply_free_spy(*a, _orig=apply_free):
            scene.applied_frees[threading.get_ident() != _MAIN] += 1
            return _orig(*a)
        mp.setattr(nc, "_apply_free", apply_free_spy)

        worker = None
        # The rate writes (I1). K0's first compute call of a rate tick: the
        # stressed arm holds it and lets the churn thread write; then the
        # write is due at the first drain that applies (nc.drain's rule).
        scene.rate_tick = scene.k0_seen = False
        scene.rate_due = None           # (bank, new rate, old rate)
        scene.rate_checks = []
        scene.rate_late = 0

        def k0_next_spy(_orig=_h.combat_k0_next):
            if not scene.rate_tick or scene.k0_seen:
                return _orig()
            scene.k0_seen = True
            pick = _rate_bank(scene)
            if worker is not None:
                worker.rate_write = None if pick is None else pick[:2]
                _h.combat_gil_probe_hold(1, HOLD_MS)
                worker.k0_entered.set()
            rec = _orig()
            if pick is not None:
                if worker is not None and not worker.rate_written.is_set():
                    scene.rate_late += 1
                scene.rate_due = pick
            return rec
        mp.setattr(_h, "combat_k0_next", k0_next_spy)
        drain = nc.drain

        def drain_spy(*a, _orig=drain, **kw):
            due = scene.rate_due
            if (due is None or threading.get_ident() != _MAIN
                    or nc._session_open()):
                return _orig(*a, **kw)
            bank, rate, old = due
            h = bank.__dict__["_nslot"]
            mirror_before = _h.combat_dump(h)["_recharge_rate"]
            python_before = bank.__dict__["_recharge_rate"]
            _orig(*a, **kw)
            if worker is None:
                bank._recharge_rate = rate      # the main thread, at the drain
            scene.rate_checks.append((
                scene.tick, scene.label(bank), old.hex(), rate.hex(),
                mirror_before.hex(), python_before.hex(),
                _h.combat_dump(h)["_recharge_rate"].hex()))
            scene.rate_due = None
        mp.setattr(nc, "drain", drain_spy)

        switch = sys.getswitchinterval()
        gc_was_enabled = gc.isenabled()
        if churn:
            worker = _Churn(target)
            worker.start()
            sys.setswitchinterval(SWITCH_S)
            _h.combat_gil_probe_arm(True)
        rng = random.Random(k1d.SEED)
        t0 = time.perf_counter()
        try:
            while scene.tick < TICKS:
                scene.tick += 1
                scene.rate_tick = scene.tick % RATE_EVERY == 0
                scene.k0_seen = False
                if worker is not None:
                    worker.tick = scene.tick
                    worker.rate_tick = scene.rate_tick
                    worker.rate_write = None
                    worker.k0_entered.clear()
                    worker.rate_written.clear()
                    worker.halt.clear()
                    worker.done.clear()
                    worker.go.set()
                    if not scene.rate_tick:     # K0's spy holds that one
                        _h.combat_gil_probe_hold(1, HOLD_MS)
                # Spare objects, each with a mirror row and a transform slot,
                # dropped as cyclic garbage in both arms: collected on
                # whichever thread collects next (in the stressed arm,
                # mostly the churn thread, during compute), so their frees
                # are recorded there and wait for a drain.
                for _ in range(SPARES):
                    o = ObjectClass()
                    ids.unregister(o.GetObjID())    # the id registry's hold
                    o._off_lock_cycle = o
                del o
                # The K1 differential's frame (one tick a frame).
                for _ in range(rng.randint(0, 2)):
                    scene.op(rng, k1d.OPS)
                App.g_kTimerManager._time += TICK_DELTA
                game_loop._update_ship_subsystems()
                for _ in range(rng.randint(0, 2)):
                    scene.op(rng, k1d.OPS)
                ships = list(iter_ships())
                with host_loop._combat_effect_scope():
                    host_loop._advance_weapons(ships, TICK_DELTA)
                    host_loop._advance_combat(ships, TICK_DELTA,
                                              player=scene.player,
                                              push_render_data=False)
                if worker is not None:
                    worker.halt.set()
                    assert worker.done.wait(WAIT_S), "churn batch hung"
                    assert worker.error is None, worker.error
                host_loop._combat_tick_boundary()
                assert scene.rate_due is None, scene.tick   # drained
                scene.record()
                if rng.random() < 0.3:
                    scene.op(rng, k1d.OPS)
                sensor_contacts.tick(scene.player,
                                     App.g_kUtopiaModule.GetGameTime())
        finally:
            sys.setswitchinterval(switch)
            _h.combat_gil_probe_arm(False)
            if worker is not None:
                worker.quit = True
                worker.halt.set()
                worker.go.set()
                worker.join(WAIT_S)
            if gc_was_enabled:
                gc.enable()
        scene.seconds = time.perf_counter() - t0
        nc.audit_mirror()
        scene.audit = list(nc.audit_failures())
        assert _h.combat_k1_depth() == 0
        scene.counts = nc.counts()
        scene.effects = effect_queue.counts()
        scene.probe = _h.combat_gil_probe_take()
        scene.churn = worker
        return scene


def _compare(ref, st):
    assert len(ref.log) == len(st.log)
    for tick, (a, b) in enumerate(zip(ref.log, st.log), start=1):
        assert len(a) == len(b), tick
        for x, y in zip(a, b):
            assert x == y, "tick %d differs:\n alone   %r\n churned %r" % (
                tick, x, y)
    for i, (x, y) in enumerate(zip(ref.events, st.events)):
        assert x == y, "event %d differs:\n alone   %r\n churned %r" % (
            i, x, y)
    assert len(ref.events) == len(st.events)
    effect_split.compare(ref.queued, st.queued)
    compare_calls(ref.calls, st.calls)
    assert ref.audit == [] and st.audit == [], (ref.audit, st.audit)


def test_a_churning_thread_during_compute_changes_nothing(monkeypatch):
    ref = _arm(monkeypatch, churn=False)
    st = _arm(monkeypatch, churn=True)
    c, p = st.churn, st.probe
    print("\noff-lock stress: alone %.1f s, churned %.1f s; churn made %d, "
          "__del__ %d, finalizers %d, pushers %d (%d off the main thread), "
          "fight frees recorded off the main thread %d; rate writes %d; "
          "probe %r"
          % (ref.seconds, st.seconds, c.made, c.deleted, c.finalized,
             len(c.issued), sum(1 for i in c.issued if i[2]),
             st.off_main_frees, len(st.rate_checks), p))
    _compare(ref, st)
    # The rate writes (I1): made off the main thread while K0 computed
    # (written before the step that released the held call), reaching the
    # mirror only at the drain -- the reference's main-thread write point,
    # so the fights above matched. The mirror held the old rate until that
    # drain and the new one after it; Python held the new one throughout.
    assert st.rate_late == 0
    assert len(st.rate_checks) >= TICKS // RATE_EVERY - 2, st.rate_checks
    assert [r[:4] for r in ref.rate_checks] == \
        [r[:4] for r in st.rate_checks]
    for _t, _bank, old, rate, mirror, python, after in ref.rate_checks:
        assert (mirror, python, after) == (old, old, rate)
    for _t, _bank, old, rate, mirror, python, after in st.rate_checks:
        assert (mirror, python, after) == (old, rate, rate)
    # The fight ran natively, every kernel, and K3's hits landed natively.
    for key in ("k1_records", "k2_native_pulses", "k3_native_hits"):
        assert st.counts[key] > 0, (key, st.counts)
    assert st.effects["failed"] == 0, st.effects
    # The churn thread ran Python while a kernel computed, GIL released:
    # every compute call was released, and steps arrived inside releases.
    # Only the combat kernels K0-K4 (indices 0-4): index 5 is kernel M, the
    # motion step (native motion phase 2), which this fight never runs (it
    # drives no GameLoop tick), so its count is 0.
    assert p["calls"][:4] == p["released"][:4] and all(p["calls"][:5]), p
    assert p["released"][4] == p["calls"][4] > 0, p
    assert sum(p["ran"]) >= TICKS, p
    # ... and stepped across the compute call itself (thousands a run; the
    # hold guarantees only the release window).
    assert sum(p["during"]) > 0, p
    # It made garbage, collected it, and its pushers pushed off the main
    # thread: the queue took every one of those, and the drains applied
    # exactly them, in order, in the tick they were made.
    assert c.deleted > 0 and c.finalized > 0
    # Real rows were freed by finalizers the churn thread ran: recorded
    # there, applied at a drain on the main thread, never where recorded.
    assert st.off_main_frees > 0
    assert st.applied_frees[False] > 0
    assert st.applied_frees[True] == 0, st.applied_frees
    queued = [(t, f) for t, f, off in c.issued if off]
    assert queued, c.issued[:10]
    assert st.drained == queued, (st.drained[:10], queued[:10])
    # The reference queued none of its own on that ship.
    assert ref.drained == []
