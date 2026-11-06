"""Kernel M drives the motion stage (native motion phase 2, Task 5).

``ship_motion.tick_all_ship_motion`` runs ``native_motion.step_all`` while
``native_motion.enabled()``: kernel M flies each set's ships in segments, a
warp row runs ``warp_flight.step`` in Python, a row the kernel hands back
runs ``_step_ship_motion`` (or ``_step_after_warp``, the resumed row), and the
kernel resumes at the next row, so every ship sees earlier ships moved and
later ones not, exactly as the Python loop does. Each test that compares
runs one scene twice, fresh: native (``DAUNTLESS_NATIVE_MOTION`` on) and
Python (``=0``), and compares every state by ``float.hex()``.

Review Focus (plan 2026-11-04-native-motion-phase2):
  1. a subclass, a base-class monkeypatch, a per-instance override or a
     patched module function of the motion surface still runs;
  3. an ET_IN_SYSTEM_WARP handler inside a Python-owned row deletes a later
     ship, retargets one, or changes the player: later rows see it;
  4. odd values (a string speed, frame "0", an int speed, an angular space
     of 0.5 or "0") take Python's path, branch and bits;
  5. the switch flipped between ticks is continuous; the audit stays clean.
"""
import math

import pytest

import App

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_register"),
    reason="native combat bindings not built")

from engine.appc import drift, native_combat as nc  # noqa: E402
from engine.appc import native_motion as nm  # noqa: E402
from engine.appc import ship_death, ship_motion, subsystems  # noqa: E402
from engine.appc import warp_flight, warp_state  # noqa: E402
from engine.appc.ship_iter import iter_non_rock_ships  # noqa: E402
from engine.appc.math import TGMatrix3, TGPoint3  # noqa: E402
from engine.appc.objects import PhysicsObjectClass  # noqa: E402
from engine.appc.ships import ShipClass  # noqa: E402
from engine.appc.subsystems import (  # noqa: E402
    ImpulseEngineSubsystem, ShipSubsystem, WarpEngineSubsystem,
)
from engine.core.game import _set_current_game  # noqa: E402

DT = 1.0 / 60.0
MODEL, WORLD = 0, 1
OFF = {"DAUNTLESS_NATIVE_MOTION": "0"}


@pytest.fixture(autouse=True)
def _clean():
    _set_current_game(None)
    App.g_kSetManager._sets.clear()
    nc.reset()
    nc.configure({})
    yield
    App.g_kSetManager._sets.clear()
    nc.reset()
    _set_current_game(None)


# ── The scenes ───────────────────────────────────────────────────────────────

def _set(name):
    pSet = App.SetClass_Create()
    pSet.SetName(name)
    App.g_kSetManager._sets[name] = pSet
    return pSet


def _rotate(ship, angle, axis):
    R = TGMatrix3()
    R.MakeRotation(angle, TGPoint3(*axis))
    ship.SetMatrixRotation(R)


def _engine(ship, ies_cls=ImpulseEngineSubsystem, pod_cls=ShipSubsystem,
            pods=3):
    ies = ies_cls("Impulse Engines")
    ship.SetImpulseEngineSubsystem(ies)
    ies._max_condition = 100.0
    ies._condition = 100.0
    ies.SetMaxSpeed(6.3)
    ies.SetMaxAccel(1.5)
    ies.SetMaxAngularVelocity(0.28)
    ies.SetMaxAngularAccel(0.12)
    ies.TurnOn()
    for i in range(pods):
        pod = pod_cls("pod%d" % i)
        pod.SetMaxCondition(2600.0)
        ies.AddChildSubsystem(pod)
    return ies


def _ship(name, pSet, pos, cls=ShipClass, ies_cls=ImpulseEngineSubsystem,
          pod_cls=ShipSubsystem, engine=True):
    ship = cls()
    ship.SetName(name)
    if engine:
        _engine(ship, ies_cls, pod_cls)
    ship.SetTranslateXYZ(*pos)
    _rotate(ship, 0.4 + 0.1 * len(name), (0.267, 0.534, 0.801))
    pSet.AddObjectToSet(ship, name)
    return ship


def _fly(ship, speed=3.0, spin=(0.05, -0.1, 0.2)):
    ship.SetSpeed(speed, TGPoint3(0.2, 1.0, -0.1), MODEL)
    ship.SetTargetAngularVelocityDirect(TGPoint3(*spin))


def _drifting(ship):
    ship.SetVelocity(TGPoint3(0.5, -0.25, 0.125))
    ship.SetAngularVelocity(TGPoint3(0.1, 0.05, 0.2), MODEL)


def _hx(v):
    return float(v).hex()


def _vec(p):
    if p is None:
        return None
    if isinstance(p, TGPoint3):
        return (type(p.x).__name__, _hx(p.x), _hx(p.y), _hx(p.z))
    return repr(p)


def _state(ship):
    d = ship.__dict__
    p = ship.GetTranslate()
    speed = d.get("_current_speed")
    return (ship.GetName(), (_hx(p.x), _hx(p.y), _hx(p.z)),
            tuple(_hx(v) for v in ship.GetWorldRotation().as_tuple()),
            (type(speed).__name__, repr(speed)),
            _vec(d.get("_current_angular_velocity")),
            _vec(d.get("_velocity")),
            "_drift_velocity" in d, _vec(d.get("_drift_velocity")),
            _floats(d.get("_motion_vel")), _floats(d.get("_acceleration")))


def _floats(t):
    if t is None or type(t) is not tuple:
        return repr(t)
    return tuple(_hx(v) for v in t)


def _arm(env):
    """Set the switch as configure() would from `env` (counts zeroed)."""
    nm.reset()
    nm.configure(env)


def _run(build, ticks, env, beat=None, dt=DT):
    """Build a scene fresh, run `ticks` motion stages under `env`, and
    return (every tick's states of every ship built, the counts)."""
    App.g_kSetManager._sets.clear()
    _set_current_game(None)
    ships = build()
    _arm(env)
    rows = []
    for t in range(ticks):
        if beat is not None:
            beat(t, ships)
        ship_motion.tick_all_ship_motion(dt)
        rows.append([_state(s) for s in ships])
    return rows, nm.counts()


def _both(build, ticks=5, beat=None, dt=DT):
    native, n_counts = _run(build, ticks, {}, beat, dt)
    python, p_counts = _run(build, ticks, OFF, beat, dt)
    assert p_counts["native_calls"] == 0
    for t, (a, b) in enumerate(zip(native, python)):
        assert a == b, "tick %d" % t
    return n_counts


# ── Segments around a warp row ───────────────────────────────────────────────

class _Flight:
    """A stand-in in-system warp flight (warp_flight.step is replaced)."""
    speed_policy = "fixed"
    ended_reason = None


def _warp_scene():
    pSet = _set("S")
    a = _ship("A", pSet, (0.01, 0.02, -0.005))
    w = _ship("W", pSet, (0.3, -0.1, 0.05))
    c = _ship("C", pSet, (-0.02, 0.01, 0.03))
    for s in (a, w, c):
        _fly(s)
    w._insystem_warp_transit = _Flight()
    return [a, w, c]


def _pose(ship):
    p = ship.GetTranslate()
    return (_hx(p.x), _hx(p.y), _hx(p.z))


def test_warp_row_sees_earlier_rows_moved_and_later_not(monkeypatch):
    seen = []

    def spy(ship, dt):
        ships = _scene[0]
        seen.append((ship.GetName(), _pose(ships[0]), _pose(ships[2])))
        return True

    monkeypatch.setattr(warp_flight, "step", spy)
    _scene = [None]
    starts = {}

    def build():
        ships = _warp_scene()
        _scene[0] = ships
        starts[len(starts)] = (_pose(ships[0]), _pose(ships[2]))
        return ships

    counts = _both(build, ticks=1)
    native_seen, python_seen = seen
    assert native_seen == python_seen
    name, a_pose, c_pose = native_seen
    assert name == "W"
    assert a_pose != starts[0][0]       # A, earlier: already moved
    assert c_pose == starts[0][1]       # C, later: not yet
    assert counts["warp_rows"] == 1
    assert counts["native_calls"] == 2
    assert counts["python_rows"] == {}


def test_warp_step_false_runs_the_row_natively_from_arriving(monkeypatch):
    """warp_flight.step False (an "ai" flight holding for its parts): the
    row's impulse orders fly, natively -- the kernel resumes AT the row,
    past its warp check, so it is never handed to Python."""
    calls = []

    def spy(ship, dt):
        calls.append(ship.GetName())
        return False

    monkeypatch.setattr(warp_flight, "step", spy)
    counts = _both(_warp_scene, ticks=6)
    assert calls == ["W"] * 12
    assert counts["warp_rows"] == 6
    assert counts["native_calls"] == 12
    assert counts["python_rows"] == {}


# ── Review Focus 1: the motion surface patched ───────────────────────────────

class _ModShip(ShipClass):
    def SetVelocity(self, v):
        _calls.append("mod SetVelocity")
        ShipClass.SetVelocity(self, v)


class _ModEngine(ImpulseEngineSubsystem):
    def IsOn(self):
        _calls.append("mod IsOn")
        return ImpulseEngineSubsystem.IsOn(self)


class _ModPod(ShipSubsystem):
    def GetConditionPercentage(self):
        _calls.append("mod GetConditionPercentage")
        return ShipSubsystem.GetConditionPercentage(self)


class _DyingShip(ShipClass):
    """A mod ship that reads dying: Python's _out_of_action asks IsDying, so
    its engines read offline and it drifts on inertia."""

    def IsDying(self):
        _calls.append("mod IsDying")
        return 1


class _LaterShip(ShipClass):
    """Stock until a test patches it, after its ships registered."""


_calls = []


def _wrap(owner, name, mp):
    orig = getattr(owner, name)
    is_class = isinstance(owner, type)

    def wrapper(*a, **kw):
        _calls.append(name)
        return orig(*a, **kw)
    if is_class:
        mp.setattr(owner, name, wrapper)
    else:
        mp.setattr(owner, name, wrapper)    # an instance attribute


def _surface_scene(cls=ShipClass, ies_cls=ImpulseEngineSubsystem,
                   pod_cls=ShipSubsystem):
    pSet = _set("S")
    ships = [_ship("Stock0", pSet, (0.01, 0.0, 0.0)),
             _ship("Odd", pSet, (0.0, 0.02, 0.0), cls=cls, ies_cls=ies_cls,
                   pod_cls=pod_cls),
             _ship("Stock1", pSet, (0.0, 0.0, 0.03))]
    for s in ships:
        _fly(s)
    return ships


def _odd(ships):
    return ships[1]


_PATCHES = {
    # (scene kwargs, patch(ships, mp) applied after the build, expected)
    "mod_ship_subclass": (dict(cls=_ModShip), None, "row"),
    "mod_engine_subclass": (dict(ies_cls=_ModEngine), None, "row"),
    "mod_pod_subclass": (dict(pod_cls=_ModPod), None, "row"),
    "mod_ship_subclass_IsDying": (dict(cls=_DyingShip), None, "row"),
    "base_ShipClass_IsDying": (
        {}, lambda s, mp: _wrap(ShipClass, "IsDying", mp), "stage"),
    "instance_ship_IsDead": (
        {}, lambda s, mp: _wrap(_odd(s), "IsDead", mp), "row"),
    "base_ShipClass_SetVelocity": (
        {}, lambda s, mp: _wrap(ShipClass, "SetVelocity", mp), "stage"),
    "base_PhysicsObjectClass_SetVelocity": (
        {}, lambda s, mp: _wrap(PhysicsObjectClass, "SetVelocity", mp),
        "stage"),
    "base_ShipClass_IsImmobile": (
        {}, lambda s, mp: _wrap(ShipClass, "IsImmobile", mp), "stage"),
    "base_engine_IsOn": (
        {}, lambda s, mp: _wrap(ImpulseEngineSubsystem, "IsOn", mp),
        "stage"),
    "base_pod_GetConditionPercentage": (
        {}, lambda s, mp: _wrap(ShipSubsystem, "GetConditionPercentage", mp),
        "stage"),
    "subclass_patched_after_registration": (
        dict(cls=_LaterShip),
        lambda s, mp: _wrap(_LaterShip, "SetVelocity", mp), "row"),
    "instance_ship_SetVelocity": (
        {}, lambda s, mp: _wrap(_odd(s), "SetVelocity", mp), "row"),
    "instance_ship_GetTranslate": (
        {}, lambda s, mp: _wrap(_odd(s), "GetTranslate", mp), "row"),
    "instance_engine_IsOn": (
        {}, lambda s, mp: _wrap(_odd(s).GetImpulseEngineSubsystem(), "IsOn",
                                mp), "row"),
    "instance_pod_GetConditionPercentage": (
        {}, lambda s, mp: _wrap(
            _odd(s).GetImpulseEngineSubsystem().GetChildSubsystem(1),
            "GetConditionPercentage", mp), "row"),
}


@pytest.mark.parametrize("case", sorted(_PATCHES))
def test_subclass_row_runs_python(monkeypatch, case):
    """Review Focus 1: whatever overrides or patches the motion surface
    still runs -- the row takes the Python path (the class flags, the
    per-instance scan) or the whole stage does (the stock snapshot) -- and
    the result is Python's, bit for bit. A class patched AFTER its ships
    registered is seen too (the class watch re-pushes their flags)."""
    kwargs, patch, expected = _PATCHES[case]
    results = {}
    for arm, env in (("native", {}), ("python", OFF)):
        with monkeypatch.context() as mp:
            App.g_kSetManager._sets.clear()
            ships = _surface_scene(**kwargs)
            _arm(env)
            # One tick before the patch: the class watch sees the class
            # stock, so a patch after it is a change it must notice.
            ship_motion.tick_all_ship_motion(DT)
            if patch is not None:
                patch(ships, mp)
            del _calls[:]
            c0 = nm.counts()
            rows = []
            for _ in range(4):
                ship_motion.tick_all_ship_motion(DT)
                rows.append([_state(s) for s in ships])
            c1 = nm.counts()
            if arm == "native":
                # The flags the watch pushed agree with the patched classes
                # (the audit recomputes them from the classes as they are).
                nc.audit_mirror()
                assert nc.audit_failures() == []
            delta = {
                "python_rows": sum(c1["python_rows"].values())
                - sum(c0["python_rows"].values()),
                "patched_stages": c1["patched_stages"]
                - c0["patched_stages"]}
            results[arm] = (rows, list(_calls), delta)
    (n_rows, n_calls, counts), (p_rows, p_calls, _p) = (results["native"],
                                                         results["python"])
    assert p_calls, "the patch is never called on the Python path"
    assert n_calls == p_calls
    assert n_rows == p_rows
    if expected == "row":
        assert counts["python_rows"] == 4, counts
        assert counts["patched_stages"] == 0, counts
    else:
        assert counts["patched_stages"] == 4, counts


class _HoldingWarp(WarpEngineSubsystem):
    """A mod warp engine that always reads as sliding in: Python's
    warp_state.is_arriving asks it, so the ship is passed over."""

    def is_dewarp_driving(self):
        _calls.append("mod is_dewarp_driving")
        return True


@pytest.mark.parametrize("how", ["subclass", "instance", "base_patch"])
def test_warp_engine_is_dewarp_driving_override_runs(monkeypatch, how):
    """The kernel answers warp_state.is_arriving from the row's `arriving`;
    a warp engine whose is_dewarp_driving is not the stock one (its class,
    an instance attribute, or a patch of WarpEngineSubsystem itself) sends
    the row, or the stage, to Python, where it is asked."""
    results = {}
    for arm, env in (("native", {}), ("python", OFF)):
        with monkeypatch.context() as mp:
            App.g_kSetManager._sets.clear()
            ships = _surface_scene()
            odd = _odd(ships)
            if how == "subclass":
                odd.SetWarpEngineSubsystem(_HoldingWarp("Warp Engines"))
            else:
                odd.SetWarpEngineSubsystem(WarpEngineSubsystem("Warp Engines"))
                we = odd.GetWarpEngineSubsystem()
                if how == "instance":
                    def holding():
                        _calls.append("instance is_dewarp_driving")
                        return True
                    mp.setattr(we, "is_dewarp_driving", holding)
                else:
                    def holding_all(self):
                        _calls.append("base is_dewarp_driving")
                        return self is we
                    mp.setattr(WarpEngineSubsystem, "is_dewarp_driving",
                               holding_all)
            _arm(env)
            del _calls[:]
            rows = []
            for _ in range(3):
                ship_motion.tick_all_ship_motion(DT)
                rows.append([_state(s) for s in ships])
            results[arm] = (rows, list(_calls), nm.counts())
    (n_rows, n_calls, counts), (p_rows, p_calls, _p) = (results["native"],
                                                         results["python"])
    assert p_calls and n_calls == p_calls
    assert n_rows == p_rows
    # The odd ship was passed over (arriving) in both arms.
    assert n_rows[0][1][1] == n_rows[-1][1][1]
    if how == "base_patch":
        assert counts["patched_stages"] == 3, counts
    else:
        assert counts["python_rows"] == {"Instance": 3}, counts


class _WatchA(ShipClass):
    pass


class _WatchC(ShipClass):
    pass


def test_class_watch_restarts_on_a_new_seen_generation(monkeypatch):
    """forget_rows clears native_combat._k2_seen and bumps its generation;
    the class watch then starts again, even when the rebuilt list has the
    same length and first class as before (here forced so), so a class
    first seen after the rebuild is watched and a later patch of it is
    obeyed."""
    pSet = _set("S")
    a = _ship("A", pSet, (0.01, 0.0, 0.0), cls=_WatchA)
    _fly(a)
    _arm({})
    ship_motion.tick_all_ship_motion(DT)
    seen = nc._k2_seen
    assert _WatchA in seen
    c = _ship("C", pSet, (0.0, 0.01, 0.0), cls=_WatchC)
    _fly(c)
    # The rebuilt list: the same length and first class, _WatchA's place
    # now _WatchC's (as after forget_rows and a different registration
    # order), and the generation forget_rows bumps.
    rebuilt = [_WatchC if k is _WatchA else k for k in seen
               if k is not _WatchC]
    assert len(rebuilt) == nm._watch_seen[0] and rebuilt[0] is seen[0]
    monkeypatch.setattr(nc, "_k2_seen", rebuilt)
    monkeypatch.setattr(nc, "_seen_gen", nc._seen_gen + 1)
    ship_motion.tick_all_ship_motion(DT)
    calls = []
    real = _WatchC.SetVelocity

    def spy(self, v):
        calls.append(self.GetName())
        return real(self, v)

    monkeypatch.setattr(_WatchC, "SetVelocity", spy)
    ship_motion.tick_all_ship_motion(DT)
    assert calls == ["C"]


_FUNCTIONS = (
    (drift, "step"), (ship_motion, "impulse_fractions"),
    (ship_motion, "_integrate_rotation"), (ship_motion, "_effective_motion"),
    (ship_motion, "_cap_keep"), (ship_motion, "_ramp_toward"),
    (ship_motion, "step_vector_velocity"),
    (ship_motion, "law_step_vector"), (ship_motion, "_no_thrust"),
    (ship_motion, "_step_after_warp"),
    (subsystems, "_is_offline"), (ship_death, "_out_of_action"),
    (warp_state, "is_arriving"),
)


@pytest.mark.parametrize("module,name", _FUNCTIONS,
                         ids=["%s.%s" % (m.__name__.rsplit(".", 1)[-1], n)
                              for m, n in _FUNCTIONS])
def test_patched_function_runs_the_stage_in_python(monkeypatch, module,
                                                   name):
    """A test's patch of a function the kernel stands in for (the stock
    snapshot): the whole stage runs Python, so the patch is called."""
    def build():
        pSet = _set("S")
        a = _ship("Flier", pSet, (0.01, 0.0, 0.0))
        _fly(a)
        b = _ship("Drifter", pSet, (0.0, 0.02, 0.0))
        _drifting(b)
        # No authored limits: its turn is _ramp_toward's, not the law's.
        c = _ship("Unlimited", pSet, (0.0, 0.0, 0.03), engine=False)
        _fly(c)
        return [a, b, c]

    ships = build()
    _arm({})
    orig = getattr(module, name)
    seen = []

    def wrapper(*a, **kw):
        seen.append(name)
        return orig(*a, **kw)

    monkeypatch.setattr(module, name, wrapper)
    for _ in range(3):
        ship_motion.tick_all_ship_motion(DT)
    assert seen
    counts = nm.counts()
    assert counts["patched_stages"] == 3, counts
    assert counts["native_calls"] == 0, counts


def test_constants_patched_run_the_stage_in_python(monkeypatch):
    _set("S")
    _arm({})
    monkeypatch.setattr(ship_motion, "FALLBACK_MAX_ACCEL", 5.0)
    assert not nm.enabled()
    monkeypatch.undo()
    assert nm.enabled()


# ── Review Focus 3: the roster changes mid-stage ─────────────────────────────

def _end_flight(ship, dt):
    """The stand-in flight arrives: the real end, ET_IN_SYSTEM_WARP and
    its handlers, inside the Python-owned row."""
    ship._end_in_system_warp("arrived")
    return True


_handler_actions = []


def _on_in_system_warp(_dest, event):
    if event.GetBool():
        return
    for action in _handler_actions:
        action()


_HANDLER = __name__ + "._on_in_system_warp"


@pytest.fixture
def _warp_handler(monkeypatch):
    del _handler_actions[:]
    monkeypatch.setattr(warp_flight, "step", _end_flight)
    App.g_kEventManager.AddBroadcastPythonFuncHandler(
        App.ET_IN_SYSTEM_WARP, App.g_kEventManager, _HANDLER)
    yield
    App.g_kEventManager.RemoveBroadcastHandler(
        App.ET_IN_SYSTEM_WARP, App.g_kEventManager, _HANDLER)
    del _handler_actions[:]


def test_handler_deletes_a_later_ship_mid_stage(_warp_handler):
    """The handler deletes a later ship of the same set (Python stepped its
    set's snapshot, so it still moves this tick), retargets another, and in
    a later set deletes one ship and creates one (Python takes that set's
    snapshot only when it gets there). The native stage does the same."""
    def build():
        s1, s2 = _set("S1"), _set("S2")
        a = _ship("A", s1, (0.01, 0.0, 0.0))
        w = _ship("W", s1, (0.0, 0.01, 0.0))
        l1 = _ship("L1", s1, (0.0, 0.0, 0.01))
        l2 = _ship("L2", s1, (0.02, 0.0, 0.0))
        m = _ship("M", s2, (0.0, 0.02, 0.0))
        n = _ship("N", s2, (0.0, 0.0, 0.02))
        for s in (a, w, l1, l2, m, n):
            _fly(s)
        w._insystem_warp_transit = _Flight()
        made = []

        def act():
            s1.DeleteObjectFromSet("L2")
            l1.SetSpeed(-4.0, TGPoint3(1.0, 0.0, 0.0), WORLD)
            s2.DeleteObjectFromSet("M")
            new = _ship("New", s2, (0.03, 0.0, 0.0))
            _fly(new, speed=2.0)
            made.append(new)
        del _handler_actions[:]
        _handler_actions.append(act)
        ships = [a, w, l1, l2, m, n]

        class _Roster(list):
            pass
        out = _Roster(ships)
        out.made = made
        return out

    def beat(t, ships):
        if t == 1:
            # The made ship, compared from the tick after it appeared.
            ships.extend(ships.made)

    counts = _both(build, ticks=4, beat=beat)
    assert counts["warp_rows"] == 1
    assert counts["python_rows"] == {}


def test_handler_changes_the_player_mid_stage(_warp_handler):
    """The handler makes a later setpoint-less ship the player: Python does
    not drift it this tick, and neither does the native stage (the player's
    handle is read before every kernel call)."""
    def build():
        pSet = _set("S")
        p0 = _ship("P0", pSet, (0.01, 0.0, 0.0))
        w = _ship("W", pSet, (0.0, 0.01, 0.0))
        d1 = _ship("D1", pSet, (0.0, 0.0, 0.01))
        d2 = _ship("D2", pSet, (0.02, 0.0, 0.0))
        for s in (p0, d1, d2):
            _drifting(s)
        _fly(w)
        w._insystem_warp_transit = _Flight()
        App.Game_SetCurrentPlayer(p0)
        del _handler_actions[:]
        _handler_actions.append(lambda: App.Game_SetCurrentPlayer(d1))
        return [p0, w, d1, d2]

    def beat(t, ships):
        assert App.Game_GetCurrentPlayer() is (ships[0] if t == 0
                                               else ships[2])

    counts = _both(build, ticks=3, beat=beat)
    assert counts["warp_rows"] == 1
    assert counts["native_calls"] == 4
    assert counts["python_rows"] == {}


def test_handler_patches_a_later_ship_mid_stage(_warp_handler):
    """The handler shadows a later ship's SetVelocity with an instance
    attribute: the Python loop calls it for that ship the same tick, so the
    native stage must re-read the rest of the set after a Python-owned row
    (its classes, handles and instance attributes), not use the set's first
    reading."""
    log = []

    def build():
        pSet = _set("S")
        a = _ship("A", pSet, (0.01, 0.0, 0.0))
        w = _ship("W", pSet, (0.0, 0.01, 0.0))
        later = _ship("Later", pSet, (0.0, 0.0, 0.01))
        for s in (a, w, later):
            _fly(s)
        w._insystem_warp_transit = _Flight()

        def shadow():
            real = later.SetVelocity

            def spy(v):
                log.append(("Later", len(log)))
                return real(v)
            later.SetVelocity = spy
        del _handler_actions[:]
        _handler_actions.append(shadow)
        return [a, w, later]

    counts = _both(build, ticks=3)
    # Each arm: the spy ran once a tick from the handler's tick on.
    assert len(log) == 6
    assert counts["python_rows"] == {"Instance": 3}, counts


def test_handler_patches_a_function_mid_stage(_warp_handler, monkeypatch):
    """The handler patches drift.step: the Python loop calls the patch for
    every later drifter of that tick (this set's and the next set's), so the
    native stage, seeing its snapshot differ after the Python-owned row,
    runs the rest of the stage in Python."""
    log = []
    real = drift.step

    def build():
        s1, s2 = _set("S1"), _set("S2")
        w = _ship("W", s1, (0.0, 0.01, 0.0))
        _fly(w)
        w._insystem_warp_transit = _Flight()
        d1 = _ship("D1", s1, (0.01, 0.0, 0.0))
        d2 = _ship("D2", s2, (0.0, 0.0, 0.01))
        for s in (d1, d2):
            _drifting(s)

        def spy(obj, dt):
            log.append(obj.GetName())
            return real(obj, dt)

        def patch():
            monkeypatch.setattr(drift, "step", spy)
        del _handler_actions[:]
        _handler_actions.append(patch)
        return [w, d1, d2]

    def beat(t, ships):
        if t == 0:
            monkeypatch.setattr(drift, "step", real)

    counts = _both(build, ticks=2, beat=beat)
    # Each arm: the tick the handler ran, both drifters through the patch;
    # the next tick (the patch still in place) the whole stage in Python.
    assert log == ["D1", "D2", "D1", "D2"] * 2
    assert counts["patched_stages"] == 2, counts


# ── Review Focus 4: odd values take Python's path ────────────────────────────

def _odd_scene(write):
    def build():
        pSet = _set("S")
        ships = [_ship("Before", pSet, (0.01, 0.0, 0.0)),
                 _ship("Odd", pSet, (0.0, 0.01, 0.0)),
                 _ship("After", pSet, (0.0, 0.0, 0.01))]
        for s in ships:
            _fly(s)
        write(ships[1])
        return ships
    return build


def _space(value):
    def write(ship):
        ship._speed_setpoint = None
        ship._target_angular_velocity_setpoint = None
        _drifting(ship)
        ship._angular_space = value
    return write


_ODD = {
    "frame_string_0": lambda s: setattr(
        s, "_speed_setpoint", (3.0, TGPoint3(0.2, 1.0, -0.1), "0")),
    "speed_int": lambda s: setattr(
        s, "_speed_setpoint", (3, TGPoint3(0.2, 1.0, -0.1), MODEL)),
    "speed_int_on_a_bare_ship": None,
    "speed_bool": lambda s: setattr(
        s, "_speed_setpoint", (True, TGPoint3(0.2, 1.0, -0.1), MODEL)),
    "angular_space_half": _space(0.5),
    "angular_space_string_0": _space("0"),
}


@pytest.mark.parametrize("case", sorted(_ODD))
def test_odd_values_take_pythons_path(case):
    """Review Focus 4 (Task 4's carry): values the mirror's encoders would
    convert (float() of a speed, int() of a frame or an angular space)
    where Python compares or keeps them as they are: such a row takes the
    Python path, so branch, bits AND value types are Python's."""
    write = _ODD[case]
    if case == "speed_int_on_a_bare_ship":
        def build():
            pSet = _set("S")
            ship = _ship("Odd", pSet, (0.0, 0.01, 0.0), engine=False)
            ship._speed_setpoint = (3, TGPoint3(0.0, 1.0, 0.0), MODEL)
            return [ship]
    else:
        build = _odd_scene(write)
    counts = _both(build, ticks=4)
    assert counts["python_rows"] == {"Unrepresentable": 4}, counts


def test_odd_value_encodings():
    """What the mirror holds: `_angular_space` is Python's own test's answer
    (0 model, 1 world) for an int or a bool, of any size (a huge int no
    longer drops the row), and 2 for anything else; a speed setpoint whose
    speed is not a float or whose frame is not a number is unrepresentable
    (six zeros). The audit agrees with each."""
    pSet = _set("S")
    ship = _ship("Enc", pSet, (0.0, 0.0, 0.0))

    def dump():
        return _h.combat_dump(ship.__dict__["_nslot"])

    for value, held in ((0, 0), (1, 1), (False, 0), (True, 1), (5, 1),
                        (-3, 1), (2 ** 70, 1), (0.0, 2), (0.5, 2), ("0", 2),
                        (None, 2)):
        ship._angular_space = value
        assert dump()["_angular_space"] == held, value
        assert "_nslot" in ship.__dict__
    d = TGPoint3(0.0, 1.0, 0.0)
    for sp, ok in (((1.5, d, 0), True), ((1.5, d, 1.0), True),
                   ((1.5, d, True), True), ((float("nan"), d, 0), True),
                   ((1, d, 0), False), ((True, d, 0), False),
                   (("1.5", d, 0), False), ((1.5, d, "0"), False),
                   ((1.5, d, None), False)):
        ship._speed_setpoint = sp
        got = dump()["_speed_setpoint"]
        assert (len(got) == 5) is ok, sp
    nc.audit_mirror()
    assert nc.audit_failures() == []


def test_a_string_speed_raises_as_python_does():
    """A string speed: Python raises in the ramp; so does the native stage
    (the row is handed back and raises there), and the rows before it moved
    in both."""
    results = {}
    for arm, env in (("native", {}), ("python", OFF)):
        App.g_kSetManager._sets.clear()
        ships = _odd_scene(lambda s: setattr(
            s, "_speed_setpoint", ("3", TGPoint3(0.0, 1.0, 0.0), MODEL)))()
        _arm(env)
        with pytest.raises(TypeError) as err:
            ship_motion.tick_all_ship_motion(DT)
        results[arm] = (str(err.value), [_state(s) for s in ships])
    assert results["native"] == results["python"]


def test_nan_speed_flies_natively_with_pythons_bits():
    def build():
        pSet = _set("S")
        ship = _ship("Nan", pSet, (0.01, 0.0, 0.0))
        ship.SetSpeed(float("nan"), TGPoint3(0.0, 1.0, 0.0), MODEL)
        ship.SetTargetAngularVelocityDirect(TGPoint3(float("nan"), 0.1, 0.0))
        return [ship]
    counts = _both(build, ticks=4)
    assert counts["python_rows"] == {}


# ── Review Focus 5: the switch ───────────────────────────────────────────────

def _mixed_scene():
    pSet = _set("S")
    ships = []
    for i, pos in enumerate(((0.01, 0.02, 0.0), (3000.0, -2000.0, 15.0),
                             (0.0, -0.03, 0.01), (-4500.0, 10.0, 800.0))):
        s = _ship("M%d" % i, pSet, pos)
        _fly(s, speed=2.0 + i, spin=(0.3 * i, -0.2, 0.1))
        ships.append(s)
    d = _ship("Drift", pSet, (0.0, 0.0, 0.02))
    _drifting(d)
    ships.append(d)
    return ships


def test_switch_off_is_todays_loop(monkeypatch):
    calls = []
    real = _h.combat_motion_step

    def spy(*a, **kw):
        calls.append(1)
        return real(*a, **kw)

    monkeypatch.setattr(_h, "combat_motion_step", spy)
    off, counts = _run(_mixed_scene, 5, OFF)
    assert not calls
    assert counts["native_calls"] == 0
    assert not nm.enabled()
    # Today's loop, by hand.
    App.g_kSetManager._sets.clear()
    ships = _mixed_scene()
    rows = []
    for _ in range(5):
        for s in list(iter_non_rock_ships()):
            ship_motion._step_ship_motion(s, DT)
        rows.append([_state(s) for s in ships])
    assert rows == off


def test_switch_toggled_between_ticks_is_continuous():
    """Native, Python, native (configure between ticks) equals all-Python,
    every tick by .hex(), and the mirror audits clean throughout."""
    python, _c = _run(_mixed_scene, 30, OFF)
    App.g_kSetManager._sets.clear()
    ships = _mixed_scene()
    rows = []
    for t in range(30):
        nm.configure(OFF if 10 <= t < 20 else {})
        assert nm.enabled() is not (10 <= t < 20)
        ship_motion.tick_all_ship_motion(DT)
        rows.append([_state(s) for s in ships])
        nc.audit_mirror()
        assert nc.audit_failures() == [], t
    assert rows == python
    assert nm.counts()["native_calls"] == 20


def test_audit_clean_with_native_motion(monkeypatch, tmp_path):
    """120 GameLoop ticks of combat_stress under DAUNTLESS_NATIVE_AUDIT=1
    (the mirror audited every tick), native motion on: clean, and the
    kernel flew the stage."""
    from tests.helpers import bc_assets, headless_mission
    bc_assets.require_game_dir("data/Models/Ships/Galaxy")
    monkeypatch.setenv("DAUNTLESS_MODS_DIR", str(tmp_path / "empty_mods"))
    monkeypatch.delenv("DAUNTLESS_NATIVE_COMBAT", raising=False)
    monkeypatch.delenv("DAUNTLESS_NATIVE_MOTION", raising=False)
    monkeypatch.setenv("DAUNTLESS_NATIVE_AUDIT", "1")
    monkeypatch.setenv("DAUNTLESS_COMBAT_SHIPS", "8")
    nc.reset()
    App.g_kTimerManager._time = 0.0
    import random
    random.seed(0)
    headless_mission.load("engine.dev_missions.combat_stress")
    from engine import host_loop
    from engine.core import step_memo
    from engine.core.loop import GameLoop
    host_loop._reset_sensor_state()
    step_memo.forget()
    loop = GameLoop()
    assert nc.audit_enabled()
    assert nm.enabled()
    for _ in range(120):
        loop.tick()
    assert nc.audit_failures() == [], nc.audit_failures()
    counts = nm.counts()
    assert counts["native_calls"] >= 120, counts
    assert counts["patched_stages"] == 0, counts


# ── A raise out of the kernel ────────────────────────────────────────────────

def test_a_compute_raise_resyncs_and_runs_nothing_more(monkeypatch):
    """Task 4's carry: a raise out of the kernel that is not its stop (the
    GIL probe's throw stands in for a bad_alloc) may lose the write log of
    rows it committed. The driver resyncs the stage's rows from Python,
    runs nothing more this tick (no row is run twice) and re-raises; the
    next tick flies on, the mirror audits clean."""
    flown = []

    def spy(ship, dt):
        flown.append(ship.GetName())
        return True

    monkeypatch.setattr(warp_flight, "step", spy)
    ships = _warp_scene()
    _arm({})
    ship_motion.tick_all_ship_motion(DT)
    before = [_state(s) for s in ships]
    # The second kernel call of the tick (after W's warp row) throws.
    real = _h.combat_motion_step
    n = [0]

    def arm_second(*a, **kw):
        n[0] += 1
        if n[0] == 2:
            _h.combat_gil_probe_arm(True, throw_site=5)
        return real(*a, **kw)

    monkeypatch.setattr(_h, "combat_motion_step", arm_second)
    try:
        with pytest.raises(RuntimeError, match="thrown in compute"):
            ship_motion.tick_all_ship_motion(DT)
    finally:
        _h.combat_gil_probe_arm(False)
        _h.combat_gil_probe_take()
    after = [_state(s) for s in ships]
    assert after[0] != before[0]        # A: flown in the first segment
    assert after[2] == before[2]        # C: never run, natively or not
    assert flown == ["W", "W"]
    assert nm.counts()["raised"] == 1
    nc.audit_mirror()
    assert nc.audit_failures() == []
    monkeypatch.setattr(_h, "combat_motion_step", real)
    ship_motion.tick_all_ship_motion(DT)
    assert [_state(s) for s in ships][2] != before[2]
    nc.audit_mirror()
    assert nc.audit_failures() == []


def test_kernel_time_is_recorded_as_motion_kernel_under_gl_motion():
    """The compute timer's kernel M (combat_compute_take(5)) is reported to
    the frame profiler as `motion.kernel`, a child of `gl.motion`, its calls
    the stage's kernel calls; the accumulator is empty after the stage."""
    from engine.core import frame_profiler as fp
    ships = _warp_scene()
    ships[1]._insystem_warp_transit = None
    _arm({})
    fp.set_enabled(True, native=False)
    try:
        for _ in range(3):
            fp.begin_frame()
            fp.mark("sim")
            with fp.scope("gl.motion"):
                ship_motion.tick_all_ship_motion(DT)
            fp.end_frame()
            assert fp.calls().get("motion.kernel") == 1, fp.calls()
            assert fp.parents()["motion.kernel"] == "gl.motion"
            assert _h.combat_compute_take(5) == (0.0, 0)
    finally:
        fp.set_enabled(False, native=False)
        fp.reset()
    assert nm.counts()["native_calls"] == 3


def test_roster_matches_iter_non_rock_ships():
    """The driver's own per-set roster is iter_non_rock_ships' order."""
    s1, s2 = _set("S1"), _set("S2")
    made = [_ship("A", s1, (0.0, 0.0, 0.0)), _ship("B", s2, (1.0, 0.0, 0.0)),
            _ship("C", s1, (2.0, 0.0, 0.0))]
    assert made
    roster = [s for pSet in nm._sets_now()
              for s in nm._ships_of(nm._set_objects(pSet))]
    assert roster == list(iter_non_rock_ships())


def test_stage_rows_split_the_driver_cost():
    """gl.motion's children name where the driver's time goes: the stock
    check, the prep walk, the binding (motion.step), the kernel's compute,
    the tractor step and the publish."""
    from engine.core import frame_profiler as fp
    _warp_scene()[1]._insystem_warp_transit = None
    _arm({})
    fp.set_enabled(True, native=False)
    try:
        fp.begin_frame()
        fp.mark("sim")
        with fp.scope("gl.motion"):
            ship_motion.tick_all_ship_motion(DT)
        fp.end_frame()
        parents = fp.parents()
    finally:
        fp.set_enabled(False, native=False)
        fp.reset()
    for row in ("motion.check", "motion.prep", "motion.step",
                "motion.kernel", "motion.tractors", "motion.publish"):
        assert parents.get(row) == "gl.motion", (row, parents)


def test_a_patched_stage_says_so_once(monkeypatch, capsys):
    """The first stage a patch sends to Python logs the patched name once;
    later stages stay quiet."""
    _mixed_scene()
    _arm({})
    orig = ship_motion._cap_keep
    monkeypatch.setattr(ship_motion, "_cap_keep",
                        lambda *a, **kw: orig(*a, **kw))
    capsys.readouterr()
    for _ in range(3):
        ship_motion.tick_all_ship_motion(DT)
    err = capsys.readouterr().err
    assert err.count("kernel M: engine.appc.ship_motion._cap_keep is patched") == 1, err
    assert nm.counts()["patched_stages"] == 3
