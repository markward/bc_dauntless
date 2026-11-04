"""The kernels compute with the GIL released (kernels off the lock, Task 3;
spec docs/superpowers/specs/2026-11-03-kernels-off-the-lock-design.md goal 3,
plan Review Focus 3).

host_bindings.cc's released_compute releases the GIL around exactly each
compute call -- K0-K3's next(), K3's apply_hits (the native damage of its
hits) and kernel M's motion step (native motion phase 2: the fight runs the
motion stage too) -- and its source guard is
tests/unit/test_native_k1_holds_gil.py. This
file is the behavioural half, through the test-only GIL probe
(combat_gil_probe_*): armed, each released compute call records whether
PyGILState_Check() read 0 inside it, and can be made to throw from inside
the released region.

- In a headless fight every compute call of every site ran with the GIL
  released, and the probe counted nothing while unarmed.
- A throw inside compute (GIL released) re-acquires the GIL as it unwinds:
  the driver abandons its session as for any other exception, the exception
  reaches the caller, and the fight carries on with nothing left open,
  pending or failing the mirror audit.
- apply_hits' compute is K3's: the k3.compute row counts it.
"""
import random
import threading

import pytest

import App

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

from engine import host_loop
from engine.appc import effect_queue
from engine.appc import native_combat as nc
from engine.appc import native_motion as nm
from engine.appc import ship_motion
from engine.appc.ship_iter import iter_ships
from engine.core import frame_profiler as fp
from engine.core import loop as game_loop
from engine.core.loop import TICK_DELTA
from tests.helpers import bc_assets

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_k0_next"),
    reason="native combat bindings not built")

# The probe's sites (host_bindings.cc ComputeSite), in order; "motion" is
# kernel M's (native motion phase 2), driven by the motion stage.
SITES = ("k0", "k1", "k2", "k3", "k3_hits", "motion")
K0, K1, K2, K3, K3_HITS, MOTION = range(6)
RADIUS = 4.0


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    bc_assets.require_game_dir("data/Models/Ships/Galaxy")
    monkeypatch.setenv("DAUNTLESS_MODS_DIR", str(tmp_path / "empty_mods"))
    nc.reset()
    _h.combat_gil_probe_arm(False)
    _h.combat_gil_probe_take()
    yield
    _h.combat_gil_probe_arm(False)
    _h.combat_gil_probe_take()
    fp.set_enabled(False, native=False)
    fp.reset()
    nc.reset()


class _Fight:
    """combat_stress with the native switch on (the K1 differential's
    scene), its op stream, and the host's per-tick drive."""

    def __init__(self, mp):
        from tests.helpers import k1_fight as k1d
        self.k1d = k1d
        self.scene = k1d._Scene(mp, k1d.ON)
        self.rng = random.Random(k1d.SEED)
        # Headless ships have radius 0, so no torpedo could touch one (the
        # K3 differential's note): a nominal hull, so K3 hits land and
        # apply_hits computes.
        for s in self.scene.ships:
            s.SetRadius(RADIUS)
        # Kernel M flies the motion stage (GameLoop.__init__ would).
        nm.configure({})

    def tick(self):
        """One frame of one tick. An exception (the probe's throw) still
        reaches the boundary, as the host's next frame would."""
        try:
            for _ in range(self.rng.randint(0, 2)):
                self.scene.op(self.rng, self.k1d.OPS)
            App.g_kTimerManager._time += TICK_DELTA
            ship_motion.tick_all_ship_motion(TICK_DELTA)
            game_loop._update_ship_subsystems()
            ships = list(iter_ships())
            with host_loop._combat_effect_scope():
                host_loop._advance_weapons(ships, TICK_DELTA)
                host_loop._advance_combat(ships, TICK_DELTA,
                                          player=self.scene.player,
                                          push_render_data=False)
        finally:
            host_loop._combat_tick_boundary()


def _spy_calls(mp, names):
    """Count Python-level calls of each binding in `names`."""
    calls = dict.fromkeys(names, 0)
    for name in names:
        orig = getattr(_h, name)

        def spy(*a, _orig=orig, _name=name, **kw):
            calls[_name] += 1
            return _orig(*a, **kw)
        mp.setattr(_h, name, spy)
    return calls


def test_the_probe_reads_one_with_the_gil_held():
    """The negative control: PyGILState_Check() is 1 where the GIL is held,
    so a 0 inside compute is the release, not a probe that always reads 0."""
    assert _h.combat_gil_probe_check() == 1


def test_every_compute_call_runs_with_the_gil_released(monkeypatch):
    with monkeypatch.context() as mp:
        fight = _Fight(mp)
        for _ in range(10):                 # unarmed: the probe is idle
            fight.tick()
        idle = _h.combat_gil_probe_take()
        assert idle["calls"] == [0] * 6, idle
        spied = _spy_calls(mp, ("combat_k0_next", "combat_k1_next",
                                "combat_k2_next", "combat_k3_next",
                                "combat_k3_apply_hits",
                                "combat_motion_step"))
        _h.combat_gil_probe_arm(True)
        for _ in range(240):
            fight.tick()
        _h.combat_gil_probe_arm(False)
        got = _h.combat_gil_probe_take()
    print("GIL probe:", got, "binding calls:", spied)
    # Every binding call made one compute call, and each ran released.
    assert got["calls"] == [spied["combat_k0_next"], spied["combat_k1_next"],
                            spied["combat_k2_next"], spied["combat_k3_next"],
                            spied["combat_k3_apply_hits"],
                            spied["combat_motion_step"]], (got, spied)
    assert all(n > 0 for n in got["calls"]), got
    assert got["released"] == got["calls"], got


def _throw_arm(fight, site, ticks=400):
    """Arm a throw at `site`'s next compute call and tick until it fires.
    Returns the exception and the tick it came on."""
    _h.combat_gil_probe_arm(True, throw_site=site)
    for t in range(ticks):
        try:
            fight.tick()
        except RuntimeError as e:
            if "GIL probe" in str(e):
                return e, t
            raise
    raise AssertionError("site %s never computed in %d ticks"
                         % (SITES[site], ticks))


@pytest.mark.parametrize("site", range(len(SITES)), ids=SITES)
def test_a_throw_in_compute_reacquires_and_abandons(monkeypatch, site):
    """Review Focus 3: compute throws with the GIL released. The release's
    destructor re-acquires the GIL as the throw unwinds (pybind translates
    it to RuntimeError with the GIL held), the driver abandons the session
    as for any exception, and the fight goes on with nothing left open."""
    with monkeypatch.context() as mp:
        fight = _Fight(mp)
        err, _t = _throw_arm(fight, site)
        assert "thrown in compute" in str(err)
        got = _h.combat_gil_probe_take()
        # The throwing call ran released and was the site's last call.
        assert got["released"][site] == got["calls"][site] >= 1, got
        assert got["thrown"] == 1, got
        # The GIL is held again, here and on another thread's turn.
        assert _h.combat_gil_probe_check() == 1
        out = []
        th = threading.Thread(target=lambda: out.append(sum(range(1000))))
        th.start()
        th.join(10.0)
        assert out == [499500]
        # No session left open; the abandoned one's records are gone.
        assert not _h.combat_k0_open()
        assert _h.combat_k1_depth() == 0
        assert not _h.combat_k2_open()
        assert not _h.combat_k3_open()
        assert _h.combat_effect_size() == 0
        # The fight carries on natively, and the mirror still agrees.
        records = nc.counts()["k1_records"]
        for _ in range(60):
            fight.tick()
        assert nc.counts()["k1_records"] > records
        nc.audit_mirror()
        assert list(nc.audit_failures()) == []
        assert _h.combat_gil_probe_take()["thrown"] == 0


def test_apply_hits_compute_is_k3_compute(monkeypatch):
    """apply_hits (the native damage of K3's hits) is timed into K3's
    accumulator and reported in the k3.compute row with next()'s: the row's
    calls are every K3 next() and apply_hits call, and nothing is left in
    the accumulator after a tick."""
    with monkeypatch.context() as mp:
        fight = _Fight(mp)
        spied = _spy_calls(mp, ("combat_k3_next", "combat_k3_apply_hits"))
        fp.set_enabled(True, native=False)
        rows = 0
        for _ in range(240):
            fp.begin_frame()
            fp.mark("sim")
            before = dict(spied)
            with fp.scope("sim.combat"):
                fight.tick()
            fp.end_frame()
            n = sum(spied[k] - before[k] for k in spied)
            assert fp.calls().get("k3.compute", 0) == n, (fp.calls(), n)
            assert _h.combat_compute_take(3) == (0.0, 0)
            rows += n
        fp.set_enabled(False, native=False)
    assert spied["combat_k3_apply_hits"] > 0, spied
    assert effect_queue.counts()["failed"] == 0
