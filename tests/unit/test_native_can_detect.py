"""Every sensor-detection caller dispatches to the native kernel (Task 6).

Each differential test builds the SAME world twice from real engine objects,
once with ``DAUNTLESS_NATIVE_COMBAT=0`` (the Python path) and once with
``=1`` (native whenever both objects are registered), and compares the
answers, the lock-break latch and the floats (by ``float.hex()``, never a
tolerance) step by step. World state changes only through real setters and
public APIs, so the mirror sees every change the way it would in the game.

The native arm also counts the kernel calls that ANSWERED (no fallback), so
a test can never pass because the native arm quietly ran the Python.
"""
import math
from collections import Counter

import pytest

import App

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_can_detect"),
    reason="native combat bindings not built")

from engine.appc import native_combat as nc  # noqa: E402
from engine.appc import sensor_contacts  # noqa: E402
from engine.appc import sensor_detection as sd  # noqa: E402
from engine.appc import sensor_occlusion as occ  # noqa: E402
from engine.appc.ships import ShipClass_Create  # noqa: E402
from engine.appc.subsystems import CloakingSubsystem, SensorSubsystem  # noqa: E402
from engine.core import step_memo  # noqa: E402
from tests.helpers.rocks import make_major_rock  # noqa: E402

OFF = {"DAUNTLESS_NATIVE_COMBAT": "0"}
ON = {"DAUNTLESS_NATIVE_COMBAT": "1"}
AUDIT = {"DAUNTLESS_NATIVE_AUDIT": "1"}

_QUERIES = ("combat_can_detect", "combat_concealment_at",
            "combat_effective_sensor_range", "combat_in_reach",
            "combat_is_hidden_by_cloak", "combat_jammed",
            "combat_occ_blocked")


@pytest.fixture(autouse=True)
def _switch():
    nc.reset()
    yield
    nc.reset()


@pytest.fixture
def answered(monkeypatch):
    """Counts the native queries that ANSWERED (a ValueError fallback is not
    counted). The dispatch reads the binding at call time, so this sees it."""
    counts = Counter()
    for name in _QUERIES:
        real = getattr(_h, name)

        def counted(*args, _real=real, _name=name, **kwargs):
            out = _real(*args, **kwargs)
            counts[_name] += 1
            return out
        monkeypatch.setattr(_h, name, counted)
    return counts


def _fresh(env):
    """A clean engine for one arm: the switch, the latch, the occlusion
    caches, the memo and the game clock."""
    nc.reset()
    sd.reset_concealment_state()
    occ.reset()
    step_memo.forget()
    App.g_kTimerManager._time = 0.0
    nc.configure(env)
    assert nc.enabled() is (env is not OFF)


def _both(scenario, envs=(OFF, ON)):
    """Run `scenario` once per arm; return the traces (all must be equal)."""
    traces = []
    for env in envs:
        _fresh(env)
        traces.append(scenario())
    for trace in traces[1:]:
        assert trace == traces[0]
    return traces[0]


def _latch(observer, target) -> bool:
    """The pair's latch from its owner: native while the mirror is live,
    whatever the switch says (ruling R7; fire control native only, M9)."""
    if nc.fire_control_native():
        return _h.combat_latched(nc.slot(observer), nc.slot(target))
    targets = sd._broken.get(observer)
    return targets is not None and target in targets


def _hex(x) -> str:
    return float(x).hex()


def _set():
    return App.SetClass_Create()


def _ship(pSet, name, x, y=0.0, z=0.0, base_range=2000.0):
    ship = ShipClass_Create("Galaxy")
    ship.SetTranslateXYZ(float(x), float(y), float(z))
    sensors = SensorSubsystem("Sensors")
    sensors._max_condition = 100.0
    sensors._condition = 100.0
    sensors.SetBaseSensorRange(base_range)
    ship.SetSensorSubsystem(sensors)
    pSet.AddObjectToSet(ship, name)
    return ship


def _bare(pSet, name, x):
    """A ShipClass with NO sensor subsystem: the sensorless dial applies."""
    ship = ShipClass_Create("BirdOfPrey")
    ship.SetTranslateXYZ(float(x), 0.0, 0.0)
    pSet.AddObjectToSet(ship, name)
    return ship


def _dense_nebula(pSet):
    """test_nebula_concealment's dense core: sphere r=200 at the origin."""
    n = App.MetaNebula_Create(0.5, 0.5, 0.7, 145.0, 1.0, "i.tga", "e.tga")
    n.SetupDamage(0.0, 0.0)
    n.AddNebulaSphere(0.0, 0.0, 0.0, 200.0)
    n.SetFbmDials(0.02, 3.0, 0.0)
    pSet.AddObjectToSet(n, "neb")
    return n


# ── Kernel-typed constants (Task 5 review) ───────────────────────────────────

def test_kernel_typed_constants_match_python():
    """sensor_detect.cc types these two rather than reading a global: kCloak-
    Cloaked (IsCloaked) and kDyingThreshold (IsDying). Pinned here so a
    Python change cannot drift silently."""
    from engine.appc import objects
    assert CloakingSubsystem.CLOAK_CLOAKED == 2
    assert objects.DYING_THRESHOLD == 1.0e6


# ── step_memo.on_forget ──────────────────────────────────────────────────────

def test_on_forget_runs_at_forget_and_at_the_outermost_exit(monkeypatch):
    calls = []
    monkeypatch.setattr(step_memo, "_forget_hooks", [])
    step_memo.on_forget(lambda: calls.append("x"))
    step_memo.forget()
    assert calls == ["x"]
    with step_memo.combat_step():
        with step_memo.combat_step():
            pass
        assert calls == ["x"]              # inner exit: no forget
    assert calls == ["x", "x"]             # outermost exit forgets


def test_native_memo_clear_is_registered():
    assert _h.combat_memo_clear in step_memo._forget_hooks


# ── Differential scenarios ───────────────────────────────────────────────────

def test_cloak_offline_sensorless_cases(answered):
    def scenario():
        s = _set()
        obs = _ship(s, "obs", 0.0)
        near_cloaked = _ship(s, "nc", 4.0)
        near_cloaked.SetCloakingSubsystem(CloakingSubsystem("Cloak"))
        near_cloaked.GetCloakingSubsystem().InstantCloak()
        far_cloaked = _ship(s, "fc", 400.0)
        far_cloaked.SetCloakingSubsystem(CloakingSubsystem("Cloak"))
        far_cloaked.GetCloakingSubsystem().InstantCloak()
        mid = _ship(s, "mid", 400.0, 10.0)
        mid.SetCloakingSubsystem(CloakingSubsystem("Cloak"))
        mid.GetCloakingSubsystem().StartCloaking()
        bare = _bare(s, "bare", 1500.0)
        far = _bare(s, "far", 2600.0)
        trace = []
        for o, t in ((obs, near_cloaked), (obs, far_cloaked), (obs, mid),
                     (obs, bare), (obs, far), (bare, obs), (bare, far),
                     (far, bare)):
            trace.append((sd.can_detect(o, t), sd.is_hidden_by_cloak(t),
                          _hex(sd.effective_sensor_range(o)),
                          sd.in_reach(o, t), sd.jammed(o, t)))
        sensors = obs.GetSensorSubsystem()
        sensors.SetCondition(20.0)                      # disabled
        trace.append((sd.can_detect(obs, bare),
                      _hex(sd.effective_sensor_range(obs))))
        sensors.SetCondition(60.0)                      # damaged: 0.6 range
        trace.append((sd.can_detect(obs, bare), sd.can_detect(obs, far),
                      _hex(sd.effective_sensor_range(obs))))
        sensors.SetCondition(0.0)                       # destroyed
        trace.append((sd.can_detect(obs, bare), sd.in_reach(obs, bare),
                      _hex(sd.effective_sensor_range(obs))))
        return trace

    trace = _both(scenario)
    assert trace[0][0] is True and trace[1][0] is False      # the bubble
    assert answered["combat_can_detect"] >= 11
    assert answered["combat_effective_sensor_range"] >= 11
    assert answered["combat_is_hidden_by_cloak"] >= 8
    assert answered["combat_in_reach"] >= 9


def _latch_walk():
    """An observer in clear space, a target walked through the dense core
    and out the other side in 40 steps, the game clock advancing each step.
    Records answer, latch and concealment (hex) per step.

    The clock jumps 30 s a step so the two clocks can never be confused:
    can_detect's own density sample reads the drift clock (_game_time, 0.0
    today) while the occlusion cache reads the Utopia game time; a kernel fed
    the wrong one samples a visibly drifted field."""
    s = _set()
    _dense_nebula(s)
    obs = _ship(s, "obs", 0.0, 0.0, 1000.0)
    tgt = _bare(s, "tgt", -400.0)
    trace = []
    for i in range(40):
        tgt.SetTranslateXYZ(-400.0 + 20.0 * i, 0.0, 0.0)
        App.g_kTimerManager.tick(30.0)
        trace.append((sd.can_detect(obs, tgt), _latch(obs, tgt),
                      _hex(sd.concealment_at(tgt))))
    return trace


def test_nebula_latch_sequence(answered):
    trace = _both(_latch_walk)
    latches = [step[1] for step in trace]
    assert True in latches and False in latches              # not vacuous
    # The hysteresis band answers differently on the way in and out.
    band = [step for step in trace
            if sd.LOCK_BREAK_T - sd.HYSTERESIS
            <= float.fromhex(step[2]) < sd.LOCK_BREAK_T]
    assert {step[0] for step in band} == {True, False}
    assert answered["combat_can_detect"] == 40
    assert answered["combat_concealment_at"] == 40
    assert not sd._broken                     # R7: one latch owner (native)


def test_nebula_latch_sequence_under_audit_matches_python_only():
    """Under audit both paths run: the answers and the latch must end exactly
    as the Python-only run's, and the two paths must agree."""
    _both(_latch_walk, envs=(OFF, AUDIT))
    assert nc.audit_failures() == []


def test_can_detect_feeds_the_kernel_both_python_clocks(monkeypatch):
    """The Python reads two clocks that are NOT the same value today: the
    nebula drift reads sensor_detection._game_time() (App.g_kTimerManager.
    GetGameTime, which the shim's TGTimerManager lacks: 0.0), the occlusion
    cache sensor_occlusion._now() (the Utopia game time). The dense test
    nebula is saturated, so a swapped drift clock barely moves its density;
    the wiring is pinned here directly."""
    _fresh(ON)
    s = _set()
    a, b = _ship(s, "A", 0.0), _bare(s, "B", 100.0)
    App.g_kTimerManager.tick(42.5)
    seen = []
    real = _h.combat_can_detect

    def spy(*args, **kw):
        seen.append(args)
        return real(*args, **kw)
    monkeypatch.setattr(_h, "combat_can_detect", spy)
    sd.can_detect(a, b)
    (args,) = seen
    assert _hex(args[2]) == _hex(sd._game_time()) == _hex(nc.now())
    assert _hex(args[7]) == _hex(occ._now()) == _hex(42.5)


def test_rock_occlusion_and_probe(answered):
    def scenario():
        s = _set()
        obs = _ship(s, "obs", 0.0, base_range=2000.0)
        tgt = _bare(s, "tgt", 100.0)
        rock = make_major_rock(s, "Rock", at=(50.0, 0.0, 0.0), radius_gu=3.0)
        trace = [(sd.can_detect(obs, tgt), occ.blocked(obs, tgt),
                  sd.in_reach(obs, tgt))]
        probe = ShipClass_Create("Probe")
        probe.SetTranslateXYZ(100.0, 50.0, 0.0)
        ps = SensorSubsystem("Sensor Array")
        ps._max_condition = 100.0
        ps._condition = 100.0
        ps.SetBaseSensorRange(1000.0)
        probe.SetSensorSubsystem(ps)
        s.AddObjectToSet(probe, "Probe")
        obs.GetSensorSubsystem().AddProbe(probe.GetObjID())
        App.g_kTimerManager.tick(0.25)
        trace.append((sd.can_detect(obs, tgt), occ.blocked(obs, tgt),
                      sd.in_reach(obs, tgt)))
        # The rock moves off the observer's line onto the probe's.
        App.g_kTimerManager.tick(0.25)
        rock.SetTranslateXYZ(100.0, 25.0, 0.0)
        trace.append((sd.can_detect(obs, tgt), occ.blocked(obs, tgt),
                      occ.blocked(probe, tgt)))
        App.g_kTimerManager.tick(0.25)
        rock.SetTranslateXYZ(500.0, 500.0, 0.0)
        trace.append((sd.can_detect(obs, tgt), occ.blocked(obs, tgt)))
        return trace

    trace = _both(scenario)
    assert trace[0][:2] == (False, True)
    assert trace[1][0] is True                    # the probe sees past it
    assert answered["combat_can_detect"] >= 4
    assert answered["combat_occ_blocked"] >= 5


def test_occlusion_cache_shared_with_scan_blocked(answered):
    def scenario():
        s = _set()
        a = _ship(s, "A", 0.0)
        b = _ship(s, "B", 100.0)
        rock = make_major_rock(s, "Rock", at=(50.0, 0.0, 0.0), radius_gu=3.0)
        App.g_kTimerManager.tick(1.0)
        trace = [sensor_contacts._scan_blocked(a, b)]
        rock.SetTranslateXYZ(50.0, 100.0, 0.0)      # off the line
        trace.append(sd.can_detect(a, b))           # same t: cached block
        App.g_kTimerManager.tick(1.0)
        trace.append(sd.can_detect(a, b))           # new t: recomputed
        return trace

    assert _both(scenario) == [True, False, True]
    assert answered["combat_occ_blocked"] == 1
    assert answered["combat_can_detect"] == 2


def test_memo_staleness_matches(answered):
    """TurnOff does not change a sensor's range (the power plant does, a
    tick later), so the sensor is DESTROYED through SetCondition instead: an
    immediate change the memo must hide until forget()."""
    def scenario():
        s = _set()
        a = _ship(s, "A", 0.0)
        b = _bare(s, "B", 100.0)
        trace = []
        with step_memo.combat_step():
            trace.append(sd.can_detect(a, b))
            a.GetSensorSubsystem().SetCondition(0.0)
            trace.append(sd.can_detect(a, b))       # stale in both arms
            step_memo.forget()
            trace.append(sd.can_detect(a, b))       # fresh
        return trace

    assert _both(scenario) == [True, True, False]
    assert answered["combat_can_detect"] == 3


def test_outermost_block_exit_clears_the_native_memo(answered):
    def scenario():
        s = _set()
        a = _ship(s, "A", 0.0)
        b = _bare(s, "B", 100.0)
        trace = []
        with step_memo.combat_step():
            trace.append(sd.can_detect(a, b))
            a.GetSensorSubsystem().SetCondition(0.0)
        with step_memo.combat_step():
            trace.append(sd.can_detect(a, b))       # the exit forgot
        return trace

    assert _both(scenario) == [True, False]
    assert answered["combat_can_detect"] == 2


class _Fake:
    """A plain object: no mirror row, so it takes the Python path."""

    def __init__(self, pSet, x):
        self._s, self._x = pSet, x

    def GetContainingSet(self):
        return self._s

    def GetWorldLocation(self):
        return App.TGPoint3(self._x, 0.0, 0.0)

    def GetWorldTranslate(self):
        return App.TGPoint3(self._x, 0.0, 0.0)


def test_unregistered_pair_uses_python(answered):
    def scenario():
        s = _set()
        real = _ship(s, "real", 0.0)
        fake = _Fake(s, 500.0)
        assert nc.slot(fake) is None
        return [sd.can_detect(real, fake), sd.can_detect(fake, real),
                _hex(sd.concealment_at(fake)),
                _hex(sd.effective_sensor_range(fake)),
                _hex(sd.effective_sensor_range(None)),
                sd.is_hidden_by_cloak(fake), sd.jammed(real, fake),
                occ.blocked(real, fake)]

    _both(scenario)
    # The pair never reaches the kernel. The Python body's per-object pieces
    # (the real ship's range and concealment) are native: one live rule.
    assert answered["combat_can_detect"] == 0
    assert answered["combat_jammed"] == 0
    assert answered["combat_occ_blocked"] == 0
    assert answered["combat_effective_sensor_range"] >= 1


def test_a_torpedo_uses_python(answered):
    """Torpedo hides the mirrored _containing_set and _radius behind its own
    properties (projectiles.py), so a row would never see its set: native
    would answer its concealment as 0.0 in a nebula. It takes the Python
    path, with the Python's answer (final review, Important 2)."""
    from engine.appc import projectiles
    from engine.appc.projectiles import Torpedo

    def scenario():
        s = _set()
        _dense_nebula(s)
        obs = _ship(s, "obs", 0.0, 0.0, 1000.0)
        torp = Torpedo()
        s.AddObjectToSet(torp, "torp")
        try:
            assert torp.GetContainingSet() is s
            return [_hex(sd.concealment_at(torp)), sd.can_detect(obs, torp),
                    sd.can_detect(torp, obs),
                    _hex(sd.effective_sensor_range(torp)),
                    sd.is_hidden_by_cloak(torp), sd.jammed(obs, torp)]
        finally:
            projectiles.expire(torp)

    trace = _both(scenario)
    assert trace[0] != _hex(0.0)          # the nebula conceals the torpedo
    assert answered["combat_can_detect"] == 0
    assert answered["combat_jammed"] == 0


def test_a_fallback_answer_matches_python(answered):
    """A registered pair whose query reaches something the mirror cannot
    name (here: a set list entry whose row was dropped) answers through the
    Python body, with the same answer and latch."""
    def scenario():
        s = _set()
        _dense_nebula(s)
        obs = _ship(s, "obs", 0.0, 0.0, 1000.0)
        tgt = _bare(s, "tgt", 0.0)
        dropped = _bare(s, "dropped", 5000.0)
        # Its set entry now reads -2: occlusion's walk of the set's ships
        # reaches it, so the kernel falls back.
        nc._drop(dropped)
        trace = [(sd.can_detect(obs, tgt), _latch(obs, tgt))]
        tgt.SetTranslateXYZ(180.0, 0.0, 0.0)           # the hysteresis band
        trace.append((sd.can_detect(obs, tgt), _latch(obs, tgt)))
        tgt.SetTranslateXYZ(400.0, 0.0, 0.0)           # clear space
        trace.append((sd.can_detect(obs, tgt), _latch(obs, tgt)))
        return trace

    trace = _both(scenario)
    assert trace == [(False, True), (False, True), (True, False)]
    assert answered["combat_can_detect"] == 0          # every call fell back
    assert not sd._broken                     # R7: the fallback used native


class _PlainProperty:
    """A property the mirror cannot name (not a TGModelProperty): the
    sensor's `_property` reads -2, so any query reaching its max condition
    falls back to the Python."""

    def GetMaxCondition(self):
        return 100.0


def _probe(pSet, owner_sensors, name, x, base_range=100.0):
    probe = ShipClass_Create("Probe")
    probe.SetTranslateXYZ(float(x), 0.0, 0.0)
    ps = SensorSubsystem("Sensor Array")
    ps._max_condition = 100.0
    ps._condition = 100.0
    ps.SetBaseSensorRange(base_range)
    probe.SetSensorSubsystem(ps)
    pSet.AddObjectToSet(probe, name)
    owner_sensors.AddProbe(probe.GetObjID())
    return probe


def test_a_python_probe_walk_stays_python(answered):
    """Ruling R8. The observer's own query falls back, so the PYTHON walks
    its probes. The probe's question must stay Python too: the kernel's own
    probe guard is not the Python's, and native would walk the probe's
    probes -- a second level the one-level rule forbids."""
    def scenario():
        s = _set()
        obs = _ship(s, "obs", 0.0, base_range=100.0)
        obs.GetSensorSubsystem().SetProperty(_PlainProperty())
        p1 = _probe(s, obs.GetSensorSubsystem(), "P1", 1000.0)
        _probe(s, p1.GetSensorSubsystem(), "P2", 2000.0)
        tgt = _bare(s, "tgt", 2050.0)
        return [sd.can_detect(obs, tgt), sd.in_reach(obs, tgt),
                sd.can_detect(p1, tgt), sd.in_reach(p1, tgt)]

    # The observer sees nothing; P1 itself (asked directly) reaches through
    # its own probe P2: that is one level, and native answers it.
    assert _both(scenario) == [False, False, True, True]
    assert answered["combat_can_detect"] == 1
    assert answered["combat_in_reach"] == 1


def test_reset_concealment_state_clears_native_latch():
    _fresh(ON)
    s = _set()
    _dense_nebula(s)
    obs = _ship(s, "obs", 0.0, 0.0, 1000.0)
    tgt = _bare(s, "tgt", 0.0)
    assert sd.can_detect(obs, tgt) is False
    assert _h.combat_latched(nc.slot(obs), nc.slot(tgt)) is True
    sd.reset_concealment_state()
    assert _h.combat_latched(nc.slot(obs), nc.slot(tgt)) is False


def test_python_latch_writes_reach_the_native_latch():
    """R7: _latched/_set_latched ARE the native latch for a registered pair,
    and stay Python's for an unregistered one."""
    _fresh(ON)
    s = _set()
    a, b = _ship(s, "A", 0.0), _bare(s, "B", 10.0)
    sd._set_latched(a, b, True)
    assert _h.combat_latched(nc.slot(a), nc.slot(b)) is True
    assert sd._latched(a, b) is True
    assert not sd._broken
    sd._set_latched(a, b, False)
    assert _h.combat_latched(nc.slot(a), nc.slot(b)) is False
    fake = _Fake(s, 0.0)
    sd._set_latched(a, fake, True)
    assert sd._latched(a, fake) is True
    assert fake in sd._broken[a]


def test_occlusion_begin_tick_and_reset_reach_native():
    _fresh(ON)
    s = _set()
    a, b = _ship(s, "A", 0.0), _ship(s, "B", 100.0)
    rock = make_major_rock(s, "Rock", at=(50.0, 0.0, 0.0), radius_gu=3.0)
    assert occ.blocked(a, b) is True
    rock.SetTranslateXYZ(50.0, 100.0, 0.0)
    assert occ.blocked(a, b) is True             # cached
    occ.begin_tick(3.0)
    assert occ.blocked(a, b) is False            # the tick time moved
    rock.SetTranslateXYZ(50.0, 0.0, 0.0)
    assert occ.blocked(a, b) is False            # cached
    occ.reset()
    assert occ.blocked(a, b) is True


def test_concealment_at_nan_profile_term(monkeypatch, answered):
    """A NaN profile term: Python's max(local, min(term, cap)) keeps `local`
    (min returns its NaN first argument; max keeps its first). std::min/max
    would answer the cap."""
    from engine.systems import frames, profile, region_hooks, resolve
    from engine.systems.profile import Profile, ProfileRow

    def scenario():
        s = App.SetClass_Create()
        s.SetName("Vesuvi4")
        region_hooks.mark_mapped(s)
        m = resolve.map_of(frames.frame_of(s).key[1])
        nan_profile = Profile(rows=[ProfileRow(0.0, sensors=0.5)],
                              full_concealment=float("nan"))
        monkeypatch.setattr(m, "profile", nan_profile)
        region_hooks.mark_mapped(s)          # the frame is re-pushed
        ship = _bare(s, "S", 0.0)
        out = []
        for x in (0.0, 1.0e4):
            ship.SetTranslateXYZ(x, 0.0, 0.0)
            assert profile.locate(ship)[0] is nan_profile   # term reached
            out.append(_hex(sd.concealment_at(ship)))
        return out

    trace = _both(scenario)
    assert not any(math.isnan(float.fromhex(v)) for v in trace)
    assert answered["combat_concealment_at"] == 2


# ── Audit ────────────────────────────────────────────────────────────────────

def test_audit_records_a_planted_difference(monkeypatch):
    _fresh(AUDIT)
    s = _set()
    a, b = _ship(s, "A", 0.0), _bare(s, "B", 100.0)
    real = _h.combat_can_detect
    monkeypatch.setattr(_h, "combat_can_detect",
                        lambda *args, **kw: not real(*args, **kw))
    assert sd.can_detect(a, b) is True                  # Python's answer
    names = [f[0] for f in nc.audit_failures()]
    assert "can_detect" in names


def test_audit_planted_latch_difference_leaves_the_python_latch(monkeypatch):
    """A native call that writes the latch wrongly is recorded, and the
    answer and latch end where the Python-only run leaves them. The target
    sits in the hysteresis band, where the latch decides the answer: a fresh
    pair detects, a latched one does not -- so the Python must run from the
    latch as it was BEFORE the native call."""
    _fresh(AUDIT)
    s = _set()
    _dense_nebula(s)
    a = _ship(s, "A", 0.0, 0.0, 1000.0)
    b = _bare(s, "B", 180.0)
    conceal = sd._py_concealment_at(b)
    assert sd.LOCK_BREAK_T - sd.HYSTERESIS <= conceal < sd.LOCK_BREAK_T
    real = _h.combat_can_detect

    def wrong(obs, tgt, *args, **kw):
        out = real(obs, tgt, *args, **kw)
        _h.combat_set_latched(obs, tgt, True)
        return out
    monkeypatch.setattr(_h, "combat_can_detect", wrong)
    assert sd.can_detect(a, b) is True
    assert _h.combat_latched(nc.slot(a), nc.slot(b)) is False
    assert [f[0] for f in nc.audit_failures()] == ["can_detect"]


# ── Fix round 1 ──────────────────────────────────────────────────────────────

def test_audit_restores_probe_pair_latches(monkeypatch):
    """A native run writes (probe, target) latches as well as the asked
    pair's. When the native walk differs from the Python's -- planted here as
    a probe-pair write the Python never makes -- every pair whose target is
    the asked target goes back where it was, so a probe in the hysteresis
    band answers later exactly as in a Python-only game."""
    plant = [True]
    real = _h.combat_can_detect

    def wrong(obs, tgt, *args, **kw):
        out = real(obs, tgt, *args, **kw)
        if plant[0]:
            plant[0] = False
            _h.combat_set_latched(probe_slot[0], tgt, True)
        return out
    monkeypatch.setattr(_h, "combat_can_detect", wrong)
    probe_slot = [None]

    def scenario():
        plant[0] = True
        s = _set()
        _dense_nebula(s)
        obs = _ship(s, "obs", 0.0, 0.0, 1000.0)
        probe = _probe(s, obs.GetSensorSubsystem(), "P", 0.0,
                       base_range=2000.0)
        probe.SetTranslateXYZ(0.0, 0.0, -1000.0)
        probe_slot[0] = nc.slot(probe)
        tgt = _bare(s, "tgt", 180.0)                  # the hysteresis band
        conceal = sd._py_concealment_at(tgt)
        assert sd.LOCK_BREAK_T - sd.HYSTERESIS <= conceal < sd.LOCK_BREAK_T
        return [sd.can_detect(obs, tgt), _latch(probe, tgt),
                sd.can_detect(probe, tgt), _latch(probe, tgt)]

    assert _both(scenario, envs=(OFF, AUDIT)) == [True, False, True, False]
    assert [f[0] for f in nc.audit_failures()] == ["can_detect"]


@pytest.mark.parametrize("side", ["observer", "target"])
def test_a_dropped_row_hands_its_latch_to_python(side, answered):
    """A row dropped mid-session (an unrepresentable value) moves the pair
    from the native latch to the Python's: a broken lock stays broken, so
    the hysteresis band answers as in a Python-only game. Asked inside a
    combat step too: the native memo entry goes with the row, and the Python
    recomputes the same answer from the carried latch."""
    def scenario():
        s = _set()
        _dense_nebula(s)
        obs = _ship(s, "obs", 0.0, 0.0, 1000.0)
        tgt = _bare(s, "tgt", 0.0)                    # the dense core
        trace = [sd.can_detect(obs, tgt), sd._latched(obs, tgt)]
        tgt.SetTranslateXYZ(180.0, 0.0, 0.0)          # the band
        with step_memo.combat_step():
            trace.append(sd.can_detect(obs, tgt))
            victim = obs if side == "observer" else tgt
            victim._radius = "not a float"            # drops its row (ON)
            trace.append(sd.can_detect(obs, tgt))
        trace += [sd.can_detect(obs, tgt), sd._latched(obs, tgt)]
        if nc.enabled():
            assert nc.slot(victim) is None
        return trace

    assert _both(scenario) == [False, True, False, False, False, True]
    assert answered["combat_can_detect"] == 2


# ── Dispatch counters (Task 7: the scene audit proves native ran) ────────────

def _sensor_counts():
    """The dispatched-query half of counts() (it also carries K1's)."""
    c = nc.counts()
    return {k: c[k] for k in ("native_calls", "fallbacks")}


def test_counts_native_answers_and_fallbacks():
    """`counts()` names the dispatched queries the kernel ANSWERED and the
    ones that fell back to the Python; `reset()` zeroes both, and the switch
    off counts nothing."""
    _fresh(OFF)
    s = _set()
    obs = _ship(s, "obs", 0.0)
    tgt = _ship(s, "tgt", 100.0)
    sd.can_detect(obs, tgt)
    assert _sensor_counts() == {"native_calls": 0, "fallbacks": 0}

    _fresh(ON)
    sd.can_detect(obs, tgt)
    sd.concealment_at(tgt)
    sd.effective_sensor_range(obs)
    sd.in_reach(obs, tgt)
    sd.is_hidden_by_cloak(tgt)
    sd.jammed(obs, tgt)
    occ.blocked(obs, tgt)
    assert _sensor_counts() == {"native_calls": 7, "fallbacks": 0}

    obs.GetSensorSubsystem().SetProperty(_PlainProperty())
    sd.effective_sensor_range(obs)               # the kernel cannot name it
    assert _sensor_counts() == {"native_calls": 7, "fallbacks": 1}

    _fresh(AUDIT)
    sd.is_hidden_by_cloak(tgt)
    occ.blocked(obs, tgt)
    sd.effective_sensor_range(obs)               # falls back under audit too
    assert _sensor_counts() == {"native_calls": 2, "fallbacks": 1}
    nc.reset()
    assert _sensor_counts() == {"native_calls": 0, "fallbacks": 0}
