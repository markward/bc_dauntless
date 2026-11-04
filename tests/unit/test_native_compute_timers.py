"""The native combat kernels' compute-only timers (kernels off the lock,
Task 1; spec docs/superpowers/specs/2026-11-03-kernels-off-the-lock-design.md
goal 1).

A steady_clock span in the binding wraps exactly the kernel compute call
(K0-K3's next(), K4's k4_eligible) and accumulates per kernel;
combat_compute_take(k) reads and resets it. native_combat reads it once a
session and reports it to the frame profiler as `k<k>.compute`, a child of
the kernel's home row (sim.weapons, cb.held_weapons, cb.phasers,
cb.projectiles, cb.eligibility). A session that runs under any other scope
(an AI-started K1 session in gl.ai) reports as `k<k>.compute@<scope>`, a
child of THAT scope.
"""
import random

import pytest

import App

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

from engine import host_loop
from engine.appc import native_combat as nc
from engine.appc.ship_iter import iter_ships
from engine.core import frame_profiler as fp
from engine.core import loop as game_loop
from engine.core.loop import TICK_DELTA
from tests.helpers import bc_assets

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_k0_next"),
    reason="native combat bindings not built")

HOME = {0: "sim.weapons", 1: "cb.held_weapons", 2: "cb.phasers",
        3: "cb.projectiles", 4: "cb.eligibility"}


@pytest.fixture(autouse=True)
def _clean():
    nc.reset()
    fp.set_enabled(False, native=False)
    fp.reset()
    yield
    fp.set_enabled(False, native=False)
    fp.reset()
    nc.reset()


# ── The binding's accumulator ───────────────────────────────────────────────

_NEXT = {0: "combat_k0_next", 1: "combat_k1_next", 2: "combat_k2_next",
         3: "combat_k3_next"}


@pytest.mark.parametrize("k", [0, 1, 2, 3])
def test_a_compute_call_is_timed_and_take_resets(k):
    """next() with no session open throws from inside the kernel: the span
    still closes (RAII), so the call is counted; a second take reads 0."""
    _h.combat_compute_take(k)
    with pytest.raises(Exception):
        getattr(_h, _NEXT[k])()
    ms, n = _h.combat_compute_take(k)
    assert n == 1
    assert 0.0 <= ms < 1000.0
    assert _h.combat_compute_take(k) == (0.0, 0)


def test_k4_eligible_is_timed_and_take_resets():
    _h.combat_compute_take(4)
    _h.combat_step_reset()          # nothing representable: k4 says None
    assert _h.combat_k4_eligible(-1, 4, 1.0, 1.0) is None
    ms, n = _h.combat_compute_take(4)
    assert n == 1 and ms >= 0.0
    assert _h.combat_compute_take(4) == (0.0, 0)


def test_each_kernel_has_its_own_accumulator():
    for k in range(6):
        _h.combat_compute_take(k)
    with pytest.raises(Exception):
        _h.combat_k2_next()
    # Kernel M (5, native motion phase 2) has its own accumulator too.
    assert [_h.combat_compute_take(k)[1] for k in range(6)] == \
        [0, 0, 1, 0, 0, 0]


def test_take_rejects_an_unknown_kernel():
    with pytest.raises(ValueError):
        _h.combat_compute_take(6)
    with pytest.raises(ValueError):
        _h.combat_compute_take(-1)


def test_reset_clears_the_accumulators():
    with pytest.raises(Exception):
        _h.combat_k1_next()
    nc.reset()
    assert _h.combat_compute_take(1) == (0.0, 0)


# ── K1's nested sessions ────────────────────────────────────────────────────

def test_a_nested_k1_session_reports_only_its_own_compute(monkeypatch):
    """A K1 session a record's handler starts (inside the outer session)
    banks what the outer one computed so far before it begins: each session
    reports the compute made while it was innermost, under the scope it
    started in."""
    takes = iter([(1.0, 2),     # the outer session's, banked at nesting
                  (0.5, 1),     # the inner session's own, at its end
                  (0.25, 1)])   # the outer's after the inner returned
    monkeypatch.setattr(_h, "combat_compute_take", lambda k: next(takes))
    fp.set_enabled(True, native=False)
    fp.begin_frame()
    fp.mark("sim")
    with fp.scope("cb.held_weapons"):
        nc._k1_compute_enter()
        with fp.scope("fx"):
            nc._k1_compute_enter()
            nc._k1_compute_exit()
        nc._k1_compute_exit()
    fp.end_frame()
    assert fp._last_raw["k1.compute"] == pytest.approx(1.25)
    assert fp.calls()["k1.compute"] == 3
    assert fp.parents()["k1.compute"] == "cb.held_weapons"
    assert fp._last_raw["k1.compute@fx"] == pytest.approx(0.5)
    assert fp.parents()["k1.compute@fx"] == "fx"
    assert nc._k1_compute == []


# ── The profiler rows, in a headless fight ──────────────────────────────────

FRAMES = 40
TICKS_PER_FRAME = 3


def _fight(monkeypatch, env):
    """combat_stress, driven the host's way under the profiler: per frame a
    mark("sim"), ops that start firing inside a gl.ai scope (as the AI's
    FireScript does), then per tick sim.weapons and sim.combat. Returns
    [(raw ms per name, parents)] per frame."""
    from tests.helpers import k1_fight as k1d
    frames = []
    with monkeypatch.context() as mp:
        scene = k1d._Scene(mp, env)
        rng = random.Random(k1d.SEED)
        fp.set_enabled(True, native=False)
        for _ in range(FRAMES):
            fp.begin_frame()
            fp.mark("sim")
            with fp.scope("gl.ai"):
                for _ in range(rng.randint(1, 3)):
                    scene.op(rng, k1d.OPS)
            for _ in range(TICKS_PER_FRAME):
                App.g_kTimerManager._time += TICK_DELTA
                game_loop._update_ship_subsystems()
                ships = list(iter_ships())
                with host_loop._combat_effect_scope():
                    with fp.scope("sim.weapons"):
                        host_loop._advance_weapons(ships, TICK_DELTA)
                    with fp.scope("sim.combat"):
                        host_loop._advance_combat(ships, TICK_DELTA,
                                                  player=scene.player,
                                                  push_render_data=False)
                host_loop._combat_tick_boundary()
            fp.end_frame()
            frames.append((dict(fp._last_raw), fp.parents()))
        fp.set_enabled(False, native=False)
    return frames


def _compute_rows(raw):
    return {n for n in raw if ".compute" in n}


@pytest.fixture
def _assets(monkeypatch, tmp_path):
    bc_assets.require_game_dir("data/Models/Ships/Galaxy")
    monkeypatch.setenv("DAUNTLESS_MODS_DIR", str(tmp_path / "empty_mods"))


def test_compute_rows_nest_under_their_parents_with_the_switch_on(
        monkeypatch, _assets):
    from tests.helpers import k1_fight as k1d
    frames = _fight(monkeypatch, k1d.ON)
    seen = set()
    for raw, parents in frames:
        for name in _compute_rows(raw):
            seen.add(name)
            base, _, where = name.partition("@")
            k = int(base[1])
            parent = parents[name]
            # Its home row, or the scope it was recorded under by name.
            assert parent == (where or HOME[k]), (name, parent)
            # Measured inside its parent's span: never more than it.
            assert raw[name] <= raw[parent], (name, raw[name], raw[parent])
    # Every kernel ran under its home row at least once...
    assert {"k%d.compute" % k for k in range(5)} <= seen, sorted(seen)
    # ...and the AI-started K1 sessions (StartFiring in gl.ai) are apart.
    assert "k1.compute@gl.ai" in seen, sorted(seen)
    # Every session drained its kernel's accumulator into the profiler.
    assert [_h.combat_compute_take(k) for k in range(6)] == [(0.0, 0)] * 6


def test_only_k1_compute_rows_with_the_switch_off(monkeypatch, _assets):
    """With DAUNTLESS_NATIVE_COMBAT=0 K0, K2, K3 and K4 run in Python, so
    they record no compute row; fire control is native whatever the switch
    (fire control native only, M9), so K1's rows still appear."""
    from tests.helpers import k1_fight as k1d
    frames = _fight(monkeypatch, k1d.OFF)
    seen = set()
    for raw, _ in frames:
        seen |= _compute_rows(raw)
    assert frames and seen, seen
    assert all(name.partition("@")[0] == "k1.compute" for name in seen), \
        sorted(seen)
    assert [_h.combat_compute_take(k) for k in range(6)] == [(0.0, 0)] * 6
