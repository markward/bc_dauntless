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
        w = k1.World(mp, True, ships, "k1_zero")
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
            assert not any(counts["k1_no_fire"].values()), counts
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
    assert not nc._enabled
    with pytest.raises(RuntimeError, match="stale build"):
        nc.fire_control_native()        # nor a fire-control call (M10)
    monkeypatch.setattr(nc, "_h", None)
    with pytest.raises(RuntimeError, match="_dauntless_host.*did not import"):
        nc.configure({})


@pytest.mark.parametrize("name", ("combat_subsys_begin", "combat_subsys_next",
                                  "combat_subsys_kinds",
                                  "combat_subsys_repair_state",
                                  "combat_subsys_skips",
                                  "combat_subsys_skip_counts",
                                  "combat_subsys_skip_counts_reset",
                                  "combat_subsys_repair_complete"))
def test_each_subsystem_stage_binding_is_required(monkeypatch, name):
    """A .so from before the cloak and repair pieces (Task 5) lacks
    combat_subsys_repair_state -- and has combat_subsys_next's old arity:
    configure() names the stale build instead of the first stage failing."""
    nc.reset()
    monkeypatch.setattr(nc, "_h", _Without(_h, name))
    assert name in nc.missing_bindings()
    with pytest.raises(RuntimeError, match="stale build.*" + name):
        nc.configure({})
    assert not nc._enabled


_K1_BINDINGS = ("combat_k1_begin_dumb", "combat_k1_begin_fire",
                "combat_k1_result", "combat_k1_can_fire",
                "combat_k1_walk_manual_offset")


@pytest.mark.parametrize("name", _K1_BINDINGS)
def test_each_k1_binding_is_required(monkeypatch, name):
    """Final review I1: a .so from before fire control went native only
    lacks the SDK-route and walk-offset bindings; configure() names it
    instead of the first shot failing."""
    nc.reset()
    monkeypatch.setattr(nc, "_h", _Without(_h, name))
    assert name in nc.missing_bindings()
    with pytest.raises(RuntimeError, match="stale build.*" + name):
        nc.configure({})
    assert not nc._enabled


class _Kinds:
    """The bindings module whose kernel reports `kinds`."""

    def __init__(self, real, kinds):
        self._real = real
        self._kinds = kinds

    def __getattr__(self, name):
        if name == "combat_k1_kinds":
            return lambda: dict(self._kinds)
        return getattr(self._real, name)


def test_k1_record_shape_is_checked(monkeypatch):
    """Final review I1: a kernel with record kinds besides DONE (a build
    from before the Python copy was deleted: RUN_PYTHON, ASK, ...) fails
    the self-check, naming the kinds."""
    nc.reset()
    monkeypatch.setattr(nc, "_h", _Kinds(_h, {"DONE": 0, "RUN_PYTHON": 1}))
    with pytest.raises(RuntimeError, match="self-check.*RUN_PYTHON"):
        nc.configure({})
    assert not nc._enabled
    nc.reset()
    monkeypatch.setattr(nc, "_h", _Kinds(_h, {"DONE": 0}))
    nc.configure({})
    assert nc._enabled


def test_failed_self_check_raises(monkeypatch):
    nc.reset()
    real = math.dist
    monkeypatch.setattr(math, "dist",
                        lambda a, b: math.nextafter(real(a, b), math.inf))
    with pytest.raises(RuntimeError, match="self-check.*dist3"):
        nc.configure({})
    assert not nc._enabled
    assert not nc.enabled() and not nc.audit_enabled()
    with pytest.raises(RuntimeError, match="self-check.*dist3"):
        nc.fire_control_native()
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


# ── Fix round 1, I1: native from before the GameLoop exists ─────────────────

def test_fire_control_before_configure_takes_the_native_path(monkeypatch):
    """The host loads the mission (whose Initialize, handlers or mod scripts
    may fire) before it builds the GameLoop that calls configure(). A
    fire-control call in that window is native: it makes the mirror live
    itself. It leaves the switch where it was (configure()'s alone)."""
    from tests.helpers.k0_fight import World
    w = World(monkeypatch, False, "before_configure")    # nc.reset() only
    try:
        assert not nc._enabled
        g, v = w.ships["Galaxy"], w.ships["Vorcha"]
        tube = g.GetTorpedoSystem().GetWeapon(0)
        assert tube.CanFire() in (0, 1)
        assert nc._enabled, "CanFire ran before the mirror was live"
        assert not nc.enabled()          # the switch: configure()'s alone
        logged = nc.counts()["k1_logged"]
        assert logged["sdk_can_fire"] == 1, logged
        nc.reset()
        sessions = []
        k1_system = nc.k1_system
        monkeypatch.setattr(nc, "k1_system",
                            lambda s, dt: (sessions.append(s),
                                           k1_system(s, dt)))
        g.GetPhaserSystem().StartFiring(v)
        assert sessions == [g.GetPhaserSystem()]
        assert nc._enabled and nc.fire_control_native()
    finally:
        w.close()


def test_torpedo_start_firing_before_configure_fires(monkeypatch):
    """Final review I2: StartFiring is itself a fire-control entry. A
    torpedo system's StartFiring(None) before configure() makes the mirror
    live and launches -- not a session over unpushed rows that loses the
    shot (k1_no_fire not_k1_system). No sensor query on the way to make the
    mirror live by a side effect (the phaser case above has can_detect)."""
    from tests.helpers.k0_fight import World
    w = World(monkeypatch, False, "before_configure_torp")
    try:
        assert not nc._enabled
        torps = w.ships["Galaxy"].GetTorpedoSystem()
        torps.StartFiring(None)
        assert nc._enabled, "StartFiring ran before the mirror was live"
        counts = nc.counts()
        assert not any(counts["k1_no_fire"].values()), counts["k1_no_fire"]
        logged = counts["k1_logged"]
        assert logged["dumb_launch"] + logged["tube_launch"] > 0, logged
    finally:
        w.close()


def test_fire_control_before_configure_raises_without_the_module(
        monkeypatch):
    """The same window with a stale build: the first fire-control call
    raises, naming the binding, instead of quietly running Python."""
    from tests.helpers.k0_fight import World
    w = World(monkeypatch, False, "before_configure_stale")
    try:
        tube = w.ships["Galaxy"].GetTorpedoSystem().GetWeapon(0)
        monkeypatch.setattr(nc, "_h", _Without(_h, "combat_k1_begin_tractor"))
        with pytest.raises(RuntimeError,
                           match="stale build.*combat_k1_begin_tractor"):
            tube.CanFire()
        with pytest.raises(RuntimeError, match="stale build"):
            nc.fire_control_native()
    finally:
        monkeypatch.setattr(nc, "_h", _h)
        w.close()
