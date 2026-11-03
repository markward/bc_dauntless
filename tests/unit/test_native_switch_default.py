"""The native switch's semantics after fire control went native only
(spec docs/superpowers/specs/2026-11-03-fire-control-native-only-design.md
§4.1, rulings M1, M2, M9, M10 and R1).

* The switch (``DAUNTLESS_NATIVE_COMBAT``) is on unless ``=0`` (M1).
* Fire control (K1, tractors included) is native whenever the module is
  available and its self-check passed, whatever the switch says (M2, M9);
  the switch governs only K0, K2, K3, K4, native damage and the effect
  scope.
* A stale build (a missing binding) or a failed self-check raises at
  ``configure()`` instead of quietly leaving native off (M10).
* The per-test reset in tests/conftest.py leaves fire control native and
  the switch where ``configure()`` puts it from the environment (R1).

No local reset fixture on purpose: the conftest test needs to see exactly
what the autouse reset left.
"""
import math

import pytest

import App

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_k1_next"),
    reason="native combat bindings not built")

from engine import host_loop  # noqa: E402
from engine.appc import native_combat as nc  # noqa: E402
from engine.core import step_memo  # noqa: E402
from tests.unit import test_native_k1_dispatch as k1  # noqa: E402

ZERO = {"DAUNTLESS_NATIVE_COMBAT": "0"}
DT = 1.0 / 60.0


class _Without:
    """The bindings module with `missing` taken out: a stale build."""

    def __init__(self, real, missing):
        self._real = real
        self._missing = missing

    def __getattr__(self, name):
        if name == self._missing:
            raise AttributeError(name)
        return getattr(self._real, name)


def test_switch_on_unless_zero():
    nc.reset()
    nc.configure({})
    assert nc.enabled()
    nc.configure({"DAUNTLESS_NATIVE_COMBAT": "0"})
    assert not nc.enabled()
    nc.configure({"DAUNTLESS_NATIVE_COMBAT": "1"})
    assert nc.enabled()


def test_fire_control_native_with_switch_zero(monkeypatch):
    """With ``=0`` a Galaxy holds phasers and tubes on a Vor'cha: K1 walks
    natively (its records), while K0, K2, K3, K4 and damage take their
    Python paths (their kernels never run) -- and the Vor'cha is hit."""
    ships = (("Galaxy", "galaxy", (0.0, 0.0, 0.0), 0.0),
             ("Vorcha", "vorcha", (20.0, 160.0, 15.0), math.pi))
    with monkeypatch.context() as mp:
        w = k1.World(mp, False, ships, "k1_zero")
        try:
            for s in w.order:
                s.SetRadius(4.0)    # headless hulls are 0: let torpedoes hit
            nc.configure(ZERO)
            assert nc.fire_control_native()
            assert not nc.enabled()
            galaxy, vorcha = w.ships["Galaxy"], w.ships["Vorcha"]
            hull = vorcha.GetHull().GetCondition()
            shields = vorcha.GetShields()
            before = [shields.GetCurShields(i) for i in range(6)]
            galaxy.GetPhaserSystem().StartFiring(vorcha)
            galaxy.GetTorpedoSystem().StartFiring(vorcha)
            for _ in range(240):
                w.clock[0] += DT
                App.g_kTimerManager._time += DT
                with host_loop._combat_effect_scope():
                    host_loop._advance_weapons(w.order, DT)
                    host_loop._advance_combat(w.order, DT,
                                              push_render_data=False)
                host_loop._combat_tick_boundary()
            counts = nc.counts()
            after = [shields.GetCurShields(i) for i in range(6)]
            assert counts["k1_records"] > 0, counts
            assert counts["k1_python_systems"] == 0, counts
            assert counts["k0_steps"] == 0, counts
            assert counts["k2_records"] == 0, counts
            assert counts["k3_runs"] == 0, counts
            assert counts["k4_runs"] == 0, counts
            assert nc.damage_counts()["hits"] == 0, nc.damage_counts()
            assert (after != before
                    or vorcha.GetHull().GetCondition() < hull), \
                "the Vor'cha was never hit"
        finally:
            w.close()
            step_memo.forget()


def test_missing_binding_raises_at_configure(monkeypatch):
    nc.reset()
    monkeypatch.setattr(nc, "_h", _Without(_h, "combat_k1_begin_tractor"))
    assert not nc.available()
    with pytest.raises(RuntimeError,
                       match="stale build.*combat_k1_begin_tractor"):
        nc.configure({})
    with pytest.raises(RuntimeError,
                       match="stale build.*combat_k1_begin_tractor"):
        nc.configure(ZERO)              # the switch does not excuse it
    assert not nc.fire_control_native()
    monkeypatch.setattr(nc, "_h", None)
    with pytest.raises(RuntimeError, match="_dauntless_host.*did not import"):
        nc.configure({})


def test_failed_self_check_raises(monkeypatch):
    nc.reset()
    real = math.dist
    monkeypatch.setattr(math, "dist",
                        lambda a, b: math.nextafter(real(a, b), math.inf))
    with pytest.raises(RuntimeError, match="self-check.*dist3"):
        nc.configure({})
    assert not nc.fire_control_native()
    assert not nc.enabled() and not nc.audit_enabled()
    with pytest.raises(RuntimeError, match="self-check.*dist3"):
        nc.configure({"DAUNTLESS_NATIVE_AUDIT": "1"})
    assert not nc.audit_enabled()


def test_conftest_reset_keeps_fire_control_native(monkeypatch):
    """At a test's start (the autouse reset just ran, the environment has
    no switch) fire control is native and so is the switch; with ``=0`` in
    the environment the reset leaves the switch off and fire control
    native."""
    from tests.conftest import _reset_leakable_engine_globals
    monkeypatch.delenv("DAUNTLESS_NATIVE_COMBAT", raising=False)
    monkeypatch.delenv("DAUNTLESS_NATIVE_AUDIT", raising=False)
    _reset_leakable_engine_globals()
    assert nc.fire_control_native()
    assert nc.enabled()
    monkeypatch.setenv("DAUNTLESS_NATIVE_COMBAT", "0")
    _reset_leakable_engine_globals()
    assert nc.fire_control_native()
    assert not nc.enabled()


def test_lock_latch_has_one_owner_with_switch_zero():
    """With ``=0`` the sensor queries answer in Python but K1's native
    can_detect still latches broken locks: a registered pair's latch stays
    the native one (ruling R7's one owner), so a lock the Python breaks is
    the one K1 reads, and the other way round."""
    from tests.unit import test_native_can_detect as ncd
    from engine.appc import sensor_detection as sd
    ncd._fresh(ncd.OFF)
    s = ncd._set()
    a, b = ncd._ship(s, "A", 0.0), ncd._bare(s, "B", 10.0)
    sd._set_latched(a, b, True)
    assert _h.combat_latched(nc.slot(a), nc.slot(b)) is True
    assert not sd._broken
    _h.combat_set_latched(nc.slot(a), nc.slot(b), False)
    assert sd._latched(a, b) is False


def test_tractors_are_native_with_switch_zero(monkeypatch):
    """A tractor is fire control (k1_tractor_start, tractor_force_step):
    with ``=0`` the Galaxy's StartFiring still engages natively, the pump
    sustains the beam and the native force pulls the Vor'cha in."""
    from engine.appc import tractor
    from engine.appc import weapon_subsystems as ws
    from tests.helpers.k0_fight import World
    w = World(monkeypatch, False, "tractor_zero")
    try:
        g, v = w.ships["Galaxy"], w.ships["Vorcha"]
        v.SetTranslateXYZ(0.0, 30.0, 0.0)
        g.GetTractorBeamSystem().TurnOn()
        nc.configure(ZERO)
        assert nc.fire_control_native() and not nc.enabled()
        tractors = g.GetTractorBeamSystem()
        tractors.SetMode(ws.TractorBeamSystem.TBS_PULL)
        tractors.StartFiring(v)
        assert tractors.IsEngaged() and tractors.IsFiring()
        before = v.GetWorldLocation().y
        for _ in range(5):
            w.tick()
            tractor.advance_tractors(w.order, DT)
        assert tractors.IsFiring()
        assert v.GetWorldLocation().y < before      # pulled toward the Galaxy
        logged = nc.counts()["k1_logged"]
        assert logged["tractor_start"] == 1, logged
        assert logged["tractor_walk"] == 5, logged
    finally:
        w.close()
