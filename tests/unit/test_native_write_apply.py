"""C-applied write logs (native weapon state, Task 1; spec
docs/superpowers/specs/2026-11-02-native-weapon-state-design.md §4.1).

The bindings apply a K1/K2 record's write log themselves
(native/src/host/combat_write_apply.h), in order, before returning the
record; Python's native_combat.apply_writes stays the reference. Most tests
here drive the C path through combat_apply_log (a Python-encoded log, the
same C path the records take) against apply_writes on twin objects; the
last ones run real K1/K2 sessions.
"""
import random

import pytest

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_k1_next"),
    reason="native K1 bindings not built")

import App  # noqa: E402

from engine.appc import native_combat as nc  # noqa: E402
from engine.appc import passive_state  # noqa: E402
from engine.appc import weapon_subsystems as ws  # noqa: E402
from engine.appc.float_range_watcher import FloatRangeWatcher  # noqa: E402

DT = 1.0 / 60.0


@pytest.fixture(autouse=True)
def _switch():
    nc.reset()
    passive_state.reset()
    yield
    if _h.combat_k2_open():
        _h.combat_k2_abandon()
    nc.reset()
    passive_state.reset()
    App.g_kModelPropertyManager.ClearLocalTemplates()


# ── Twin objects ─────────────────────────────────────────────────────────────

_EVENTS = {"py": [], "c": []}


class _Boom(Exception):
    pass


class _Offset:
    """What a fixture system's walk_offset_object returns: a new object per
    call."""

    def __init__(self, idx):
        self.idx = idx


class _Thawing:
    """A plain store, then Python: the shape the deleted passive-power
    FrozenField had (its thaw), kept here as the Python-setter apply kind's
    fixture -- a write whose setter runs Python at its place in the log."""

    def __set_name__(self, owner, name) -> None:
        self._name = name

    def __set__(self, obj, value) -> None:
        obj.__dict__[self._name] = value
        if obj.__dict__.get("_power_frozen"):
            obj._passive_power_thaw()


class _PySetField(nc.NativeWrapped, _Thawing):
    """_Thawing's store and Python, then the push (NativeWrapped)."""

    def __init__(self, type_=float, key=None) -> None:
        self._init_native(type_, key)

    def __set__(self, obj, value) -> None:
        _Thawing.__set__(self, obj, value)
        self._after_set(obj, value)


class Leaf:
    """Every apply kind the reference knows, on one class: NativeFields
    (plain), a ref, a ref list, a wake field, a Python-setter field
    (_PySetField: its setter runs Python) and a field with no quiet write."""

    _f = nc.NativeField(float)
    _i = nc.NativeField(int)
    _b = nc.NativeField(bool)
    _off = nc.NativeField(nc.OFFSET)
    _ref = nc.NativeRefField("Object")
    _target_list = nc.NativeRefList("Object")
    _wake = nc.NativeWakeField(bool)
    _frozen = _PySetField(float)
    _slots = nc.NativeSlotMap()

    def __init__(self, arm, idx, h):
        d = self.__dict__
        d["_arm"], d["_idx"], d["_nslot"] = arm, idx, h

    def _passive_on_wake(self):
        _EVENTS[self._arm].append(("wake", self._idx))

    def _passive_power_thaw(self):
        d = self.__dict__
        _EVENTS[self._arm].append(("thaw", self._idx,
                                   _canon_scalar(d.get("_f")),
                                   _canon_scalar(d.get("_frozen"))))
        if d.get("_thaw_boom"):
            raise _Boom("thaw %d" % self._idx)


class System(Leaf):
    """A walked system: materialise pins it and fetches its offset."""

    def walk_offset_object(self):
        _EVENTS[self._arm].append(("offset", self._idx))
        if self.__dict__.get("_offset_boom"):
            raise _Boom("offset %d" % self._idx)
        return _Offset(self._idx)


class _Walk(nc._K1Walk):
    """The engine's walk, its offset objects made by the fixture systems:
    the engine's materialise asks the open K1 session for what the kernel
    recorded (THE WALK OFFSET, M8.8), and none is open here. Both arms use
    it, so the twin compares the appliers, not the offsets."""

    __slots__ = ()

    def materialise(self, n, h):
        if self.walk == n:
            return self.offset
        system = self.obj(h)
        self.pin_system(system)
        self.offset = system.walk_offset_object()
        self.walk = n
        self.walked = system
        return self.offset


_BASE = 3 << 60
_UNKNOWN = _BASE + 999


def _handle(i):
    return _BASE + i


class _Arm:
    """One side of the twin: objects, a weak registry, a walk."""

    def __init__(self, arm, n_leaves=4, n_systems=2):
        import weakref
        self.arm = arm
        self.objs = [Leaf(arm, i, _handle(i)) for i in range(n_leaves)]
        self.objs += [System(arm, n_leaves + i, _handle(n_leaves + i))
                      for i in range(n_systems)]
        self.registry = weakref.WeakValueDictionary()
        for o in self.objs:
            self.registry[o.__dict__["_nslot"]] = o
        self.walk = _Walk()


def _canon_scalar(v):
    if isinstance(v, float):
        return ("float", v.hex())
    if v is None or isinstance(v, (bool, int, str)):
        return (type(v).__name__, v)
    return ("other", type(v).__name__)


class _Canon:
    """Values in an identity-SHAPE: objects of the arm by index, lists and
    offset objects by first-seen order (so a new list each write and the
    same offset object shared by a walk's writes compare equal across arms),
    floats by .hex(), every scalar with its type."""

    def __init__(self):
        self.ids = {}

    def seq(self, o):
        return self.ids.setdefault(id(o), len(self.ids))

    def __call__(self, v):
        if isinstance(v, Leaf):
            return ("obj", v.__dict__["_idx"])
        if isinstance(v, list):
            return ("list", self.seq(v), tuple(self(x) for x in v))
        if isinstance(v, _Offset):
            return ("offset", v.idx, self.seq(v))
        return _canon_scalar(v)


def _state(arm, woke):
    c = _Canon()
    objs = []
    for o in arm.objs:
        objs.append(tuple((k, c(v)) for k, v in sorted(o.__dict__.items())
                          if k != "_arm"))
    w = arm.walk
    pins = tuple((h, c(o)) for h, o in sorted(w.pins.items()))
    return (tuple(objs), pins, w.walk, c(w.offset), c(w.walked),
            tuple(_EVENTS[arm.arm]), woke)


def _exc(e):
    if e is None:
        return None
    ctx = e.__context__
    return (type(e).__name__, str(e), tuple(getattr(e, "__notes__", ())),
            None if ctx is None else (type(ctx).__name__, str(ctx)))


def _apply_py(arm, log, mp):
    mp.setattr(nc, "_registry", arm.registry)
    woke = passive_state.counts()["woke"]
    try:
        nc.apply_writes(log, arm.walk)
        err = None
    except BaseException as e:      # noqa: BLE001 - compared below
        err = e
    return err, passive_state.counts()["woke"] - woke


def _apply_c(arm, log, mp):
    # The arm's registry: the context's, and materialise's (walk.obj).
    mp.setattr(nc, "_registry", arm.registry)
    woke = passive_state.counts()["woke"]
    prev = _h.combat_set_applier(nc._applier_context(arm.walk))
    try:
        _h.combat_apply_log(log)
        err = None
    except BaseException as e:      # noqa: BLE001 - compared below
        err = e
    finally:
        _h.combat_set_applier(prev)
    return err, passive_state.counts()["woke"] - woke


def _both(log, py, c, mp):
    with mp.context() as m:
        perr, pwoke = _apply_py(py, log, m)
    with mp.context() as m:
        cerr, cwoke = _apply_c(c, log, m)
    assert _exc(cerr) == _exc(perr), log
    assert type(cerr) is type(perr)
    assert _state(c, cwoke) == _state(py, pwoke), log
    return perr, cerr


def _twins():
    for k in _EVENTS:
        del _EVENTS[k][:]
    return _Arm("py"), _Arm("c")


# ── The random-log equivalence ───────────────────────────────────────────────

_FIELDS = ("_f", "_i", "_b", "_off", "_ref", "_target_list", "_wake",
           "_frozen", "_plain", "_passive_asleep", "_power_frozen",
           "_thaw_boom", "_offset_boom", "_slots")


def _rand_float(rng):
    return rng.choice((0.0, -0.0, 1.5, rng.uniform(-1e3, 1e3),
                       rng.random() * 1e-300))


def _rand_handle(rng, n):
    r = rng.random()
    if r < 0.06:
        return -1
    if r < 0.09:
        return _UNKNOWN
    return _handle(rng.randrange(n))


def _rand_value(rng, field, n, systems):
    if field == "_ref":
        if rng.random() < 0.02:
            return 1.5
        return _rand_handle(rng, n)
    if field == "_target_list":
        return [_rand_handle(rng, n) for _ in range(rng.randrange(4))]
    if field == "_off" or (field == "_plain" and rng.random() < 0.2):
        if rng.random() < 0.2:
            return None
        # Mostly a system's walk; now and then a leaf (no
        # walk_offset_object: AttributeError) or an unknown handle.
        r = rng.random()
        h = (rng.choice(systems) if r < 0.85
             else _UNKNOWN if r < 0.9 else _handle(0))
        return ("walk_offset", rng.randrange(3), h)
    if field in ("_thaw_boom", "_offset_boom"):
        return rng.random() < 0.15
    if field in ("_f", "_frozen"):
        return _rand_float(rng)
    if field == "_i":
        return rng.randrange(-5, 5)
    return rng.choice((True, False, 0, 1, 0.0, None, 2.5))


def _rand_log(rng, n, systems):
    log = []
    for _ in range(rng.randrange(1, 12)):
        field = rng.choice(_FIELDS)
        if field == "_slots" and rng.random() < 0.7:
            field = "_f"
        if field == "_offset_boom":
            h = rng.choice(systems)
        else:
            h = _rand_handle(rng, n) if rng.random() < 0.1 \
                else _handle(rng.randrange(n))
        log.append((h, field, _rand_value(rng, field, n, systems)))
    return log


def test_c_apply_equals_python_apply_random_logs(monkeypatch):
    """2,000 seeded logs over every kind the reference knows (plain, ref,
    ref list, wake, Python setter, the walk-offset marker), bad handles,
    a field with no quiet write, raising materialises and setters: the C
    path leaves every object's dict, the walk (pins, offset, walked), the
    wake count and the hook order equal to apply_writes', and raises the
    same exception (type, message, notes, context)."""
    rng = random.Random(20261102)
    py, c = _twins()
    n = len(py.objs)
    systems = [_handle(i) for i in range(n - 2, n)]
    raised = notes = 0
    for i in range(2000):
        if rng.random() < 0.3:
            py.walk, c.walk = _Walk(), _Walk()
        if rng.random() < 0.02:
            py, c = _twins()
        perr, _cerr = _both(_rand_log(rng, n, systems), py, c, monkeypatch)
        if perr is not None:
            raised += 1
            notes += bool(getattr(perr, "__notes__", ()))
    # The generator really reaches the exception paths.
    assert raised > 100 and notes > 5, (raised, notes)


def test_ref_list_write_is_new_list_each_time(monkeypatch):
    """A ref-list write binds a NEW list of objects every time (Python's
    _prune_targets / StopFiring build one), never the previous one."""
    py, c = _twins()
    h0, h1 = _handle(0), _handle(1)
    log = [(h0, "_target_list", [h1, -1]), (h0, "_target_list", [h1, -1])]
    _both(log, py, c, monkeypatch)
    first = c.objs[0].__dict__["_target_list"]
    assert first == [c.objs[1], None]
    _apply_c(c, log, monkeypatch)
    second = c.objs[0].__dict__["_target_list"]
    assert second == first and second is not first


def test_wake_kind_wakes_sleeping_bank(monkeypatch):
    """A WakeField write (a bank's `_firing`) stores, then wakes a sleeping
    owner through passive_state.wake (its hook runs); an awake one is only
    stored. The real bank classes classify as the reference writes them:
    a phaser bank's `_firing` WAKE, a tractor's WAKE too (the mixin's wake
    field: its parent power thaw went with the power draw program, phase 6
    Task 8), a tube's PLAIN, a system's `_target` REF and `_target_list`
    REFS."""
    kinds = nc._applier_context(nc._K1Walk())[3]
    assert kinds[(ws.PhaserBank, "_firing")] == nc.APPLY_WAKE
    assert kinds[(ws.TractorBeam, "_firing")] == nc.APPLY_WAKE
    assert kinds[(ws.TorpedoTube, "_firing")] == nc.APPLY_PLAIN
    assert kinds[(ws.PhaserSystem, "_target")] == nc.APPLY_REF
    assert kinds[(ws.PhaserSystem, "_target_list")] == nc.APPLY_REFS
    py, c = _twins()
    h0, h1 = _handle(0), _handle(1)
    for arm in (py, c):
        passive_state.put_to_sleep(arm.objs[0])
    log = [(h0, "_wake", True), (h1, "_wake", False)]
    _both(log, py, c, monkeypatch)
    assert not passive_state.is_asleep(c.objs[0])
    assert c.objs[0].__dict__["_wake"] is True
    assert c.objs[1].__dict__["_wake"] is False
    assert _EVENTS["c"] == [("wake", 0)]


def test_bool_values_stay_bool(monkeypatch):
    """True/False are stored as bools, never 1/0 (WSM B8); ints stay ints,
    floats keep their sign of zero."""
    py, c = _twins()
    h0 = _handle(0)
    log = [(h0, "_b", True), (h0, "_wake", False), (h0, "_i", 1),
           (h0, "_plain", 0), (h0, "_f", -0.0)]
    _both(log, py, c, monkeypatch)
    d = c.objs[0].__dict__
    assert d["_b"] is True and d["_wake"] is False
    assert type(d["_i"]) is int and type(d["_plain"]) is int
    assert d["_f"].hex() == "-0x0.0p+0"


def test_materialise_raise_applies_rest_then_reraises(monkeypatch):
    """Review Focus 1: a walk-offset marker whose materialise raises mid-log.
    Every later write is still applied, in order; a later marker of the
    failed walk is skipped (the bank keeps its previous offset); another
    walk's is fetched; a third walk's raise is a note. The same exception
    is re-raised, with the same notes, as apply_writes'."""
    py, c = _twins()
    s_bad, s_ok, s_bad2 = _handle(4), _handle(5), _handle(4)
    for arm in (py, c):
        arm.objs[4].__dict__["_offset_boom"] = True
        arm.objs[0].__dict__["_off"] = "before"
    h0, h1, h2 = _handle(0), _handle(1), _handle(2)
    log = [(h0, "_f", 1.0),
           (h0, "_off", ("walk_offset", 1, s_bad)),
           (h1, "_f", 2.0),
           (h0, "_off", ("walk_offset", 1, s_bad)),
           (h2, "_off", ("walk_offset", 2, s_ok)),
           (h1, "_off", ("walk_offset", 3, s_bad2)),
           (h2, "_i", 7)]
    perr, cerr = _both(log, py, c, monkeypatch)
    assert type(cerr) is _Boom and str(cerr) == "offset 4"
    assert cerr.__notes__ == [
        "combat K1: walk 3's offset also raised _Boom('offset 4')"]
    d0, d1, d2 = (o.__dict__ for o in c.objs[:3])
    assert d0["_f"] == 1.0 and d0["_off"] == "before"
    assert d1["_f"] == 2.0 and "_off" not in d1
    assert isinstance(d2["_off"], _Offset) and d2["_off"].idx == 5
    assert d2["_i"] == 7
    # A plain write's raise (a setter) after the marker: the rest still
    # applied, the setter's exception re-raised.
    py, c = _twins()
    for arm in (py, c):
        d = arm.objs[0].__dict__
        d["_power_frozen"] = True
        d["_thaw_boom"] = True
    log = [(h0, "_frozen", 0.5), (h1, "_off", ("walk_offset", 0, s_ok)),
           (h1, "_i", 3)]
    perr, cerr = _both(log, py, c, monkeypatch)
    assert type(cerr) is _Boom and str(cerr) == "thaw 0"
    assert c.objs[1].__dict__["_i"] == 3


def test_python_kind_setter_called_in_order(monkeypatch):
    """A PYTHON-kind write calls the reference's quiet setter (here a
    _PySetField's: store, then the thaw) at its place in the log: it sees
    the writes before it and none after."""
    py, c = _twins()
    h0 = _handle(0)
    for arm in (py, c):
        arm.objs[0].__dict__["_power_frozen"] = True
    log = [(h0, "_f", 1.0), (h0, "_frozen", 2.0), (h0, "_f", 3.0),
           (h0, "_frozen", 4.0), (h0, "_f", 5.0)]
    _both(log, py, c, monkeypatch)
    assert _EVENTS["c"] == [
        ("thaw", 0, ("float", (1.0).hex()), ("float", (2.0).hex())),
        ("thaw", 0, ("float", (3.0).hex()), ("float", (4.0).hex()))]
    # A patched _quiet_setter is honoured: its setter is the one called.
    seen = []
    real = nc._quiet_setter

    def quiet(cls, name):
        setter, kind = real(cls, name)

        def traced(obj, value, _s=setter, _n=name):
            seen.append((_n, _canon_scalar(value) if kind is nc._RAW
                         else _Canon()(value)))
            return _s(obj, value)
        return traced, kind
    monkeypatch.setattr(nc, "_quiet_setter", quiet)
    _apply_c(c, [(h0, "_f", 6.0), (h0, "_ref", _handle(1))], monkeypatch)
    assert seen == [("_f", ("float", (6.0).hex())), ("_ref", ("obj", 1))]
    assert c.objs[0].__dict__["_ref"] is c.objs[1]


def test_slot_and_watcher_writes(monkeypatch):
    """K0's two kinds (Task 5): a SLOT write sets one element of the
    object's EXISTING list in place (same list object, value type kept); a
    WATCHER write stores `_value` on the object's `_charge_watcher` (no
    crossing check). A raise in either still applies the rest."""
    _py, c = _twins()
    h0, h1 = _handle(0), _handle(1)
    timers = [1.0, 2.0, 3.0]
    flags = [False, False]
    watcher = FloatRangeWatcher(0.25)
    d = c.objs[0].__dict__
    d["_reload_timers"], d["_flags"] = timers, flags
    d["_charge_watcher"] = watcher
    _apply_c(c, [(h0, "_reload_timers", ("slot", 1, 0.5)),
                 (h0, "_flags", ("slot", 0, True)),
                 (h0, "_charge_watcher", ("watcher", 0.75))], monkeypatch)
    assert d["_reload_timers"] is timers and timers == [1.0, 0.5, 3.0]
    assert type(timers[1]) is float
    assert d["_flags"] is flags and flags[0] is True
    assert d["_charge_watcher"] is watcher and watcher._value == 0.75
    err, _ = _apply_c(c, [(h0, "_reload_timers", ("slot", 9, 0.0)),
                          (h1, "_i", 4)], monkeypatch)
    assert type(err) is IndexError
    assert c.objs[1].__dict__["_i"] == 4
    kinds = _h.combat_apply_kinds()
    assert kinds == {"PLAIN": nc.APPLY_PLAIN, "REF": nc.APPLY_REF,
                     "REFS": nc.APPLY_REFS, "WAKE": nc.APPLY_WAKE,
                     "PYTHON": nc.APPLY_PYTHON, "SLOT": nc.APPLY_SLOT,
                     "WATCHER": nc.APPLY_WATCHER}


def test_c_applied_counter(monkeypatch):
    """counts()["c_applied_writes"]: every write the C path applied, since
    the last reset()."""
    _py, c = _twins()
    h0 = _handle(0)
    assert nc.counts()["c_applied_writes"] == 0
    _apply_c(c, [(h0, "_f", 1.0), (h0, "_i", 2), (h0, "_b", True)],
             monkeypatch)
    assert nc.counts()["c_applied_writes"] == 3
    nc.reset()
    assert nc.counts()["c_applied_writes"] == 0


# ── Real sessions ────────────────────────────────────────────────────────────

def _world(mp, tag):
    from tests.unit.test_native_k2_dispatch import GALAXY_VORCHA, World
    return World(mp, True, GALAXY_VORCHA, tag)


def test_reset_clears_a_leaked_applier_context():
    """native_combat.reset() removes an applier context a driver left
    installed (its walk's pins and registry must not outlive the reset)."""
    nc.configure({"DAUNTLESS_NATIVE_COMBAT": "1"})
    _h.combat_set_applier(nc._applier_context(nc._K2Walk()))
    nc.reset()
    assert _h.combat_set_applier(None) is None


def test_reset_abandons_a_leaked_k2_session_and_its_queue(monkeypatch):
    """A K2 session left open with resting contacts queued for its drain
    (here its abandon swallowed once, after a raise at a DONE): reset()
    abandons it and drops the queue unpresented, so the next session
    begins and runs to DONE."""
    class _Leak(Exception):
        pass

    leaked = []
    with monkeypatch.context() as mp:
        w = _world(mp, "wa_reset_k2")
        try:
            real_next, real_abandon = _h.combat_k2_next, _h.combat_k2_abandon
            kinds = _h.combat_k2_kinds()

            def next_():
                rec = real_next()
                if rec[0] == kinds["DONE"] and not leaked \
                        and _h.combat_k2_counts()["k2_batched_contacts"]:
                    leaked.append(w.n)
                    raise _Leak()
                return rec

            def abandon():
                if len(leaked) == 1:
                    leaked.append("swallowed")
                    return None
                return real_abandon()
            mp.setattr(_h, "combat_k2_next", next_)
            mp.setattr(_h, "combat_k2_abandon", abandon)
            g, v = w.ships["Galaxy"], w.ships["Vorcha"]
            g.GetPhaserSystem().SetSingleFire(0)
            g.GetPhaserSystem().StartFiring(v)
            with pytest.raises(_Leak):
                for _ in range(60):
                    w.tick()
            assert leaked[1] == "swallowed", leaked
            assert _h.combat_k2_open()
            contacts = sum(1 for c in w.calls if c[0] == "beam_contact")
            nc.reset()
            assert not _h.combat_k2_open()
            assert _h.combat_k2_drain() == []
            nc.configure({"DAUNTLESS_NATIVE_COMBAT": "1"})
            before = nc.counts()["k2_records"]
            w.tick()                        # begins, and next() may run
            assert nc.counts()["k2_records"] > before
            assert not _h.combat_k2_open()
            # Only the new step's own contacts were presented.
            assert sum(1 for c in w.calls if c[0] == "beam_contact") \
                - contacts == nc.counts()["k2_batched_contacts"] > 0
            nc.audit_mirror()
            assert nc.audit_failures() == [], nc.audit_failures()
        finally:
            w.close()


def test_records_return_empty_writes(monkeypatch):
    """K1 and K2 records come back with their writes already applied (the C
    counter moves inside next()): `writes` is []. The Galaxy's phasers rest
    on the Vor'cha (resting contacts queued for the drain) until tick 30;
    the Vor'cha's own phasers are offline throughout (their stop is logged
    writes every tick)."""
    k1, k2 = [], []
    with monkeypatch.context() as mp:
        w = _world(mp, "wa_empty")
        try:
            real1, real2 = _h.combat_k1_next, _h.combat_k2_next

            def applied():
                return _h.combat_apply_counts()["c_applied_writes"]

            def spy(real, log):
                def next_():
                    before = applied()
                    rec = real()
                    log.append((rec, applied() - before))
                    return rec
                return next_
            mp.setattr(_h, "combat_k1_next", spy(real1, k1))
            mp.setattr(_h, "combat_k2_next", spy(real2, k2))
            g, v = w.ships["Galaxy"], w.ships["Vorcha"]
            g.GetPhaserSystem().SetSingleFire(0)
            g.GetPhaserSystem().StartFiring(v)
            v.GetPulseWeaponSystem().StartFiring(g)
            v.GetPhaserSystem().TurnOff()
            for t in range(60):
                if t == 30:
                    g.GetPhaserSystem().StopFiring()
                w.tick()
            nc.audit_mirror()
            assert nc.audit_failures() == [], nc.audit_failures()
        finally:
            w.close()
    # A K1 record is (DONE, writes, no_fire_new): one a session.
    assert k1 and all(rec[1] == [] for rec, _n in k1)
    assert any(n > 0 for _rec, n in k1), "no K1 record carried writes"
    assert k2 and all(rec[-1] == [] for rec, _n in k2)
    assert any(n > 0 for _rec, n in k2), "no K2 record carried writes"
    assert nc.counts()["k2_batched_contacts"] > 0


def test_k2_drained_contacts_run_after_every_write(monkeypatch):
    """The drain runs after DONE: when each resting contact is presented,
    every write of the step is applied -- every Galaxy bank's `_dwell`
    equals the mirror's -- and the contact carries its level."""
    checked = []
    with monkeypatch.context() as mp:
        w = _world(mp, "wa_drain")
        try:
            real_contact = nc._k2_run_contact
            g, v = w.ships["Galaxy"], w.ships["Vorcha"]
            sys_ = g.GetPhaserSystem()
            banks = [sys_.GetWeapon(i) for i in range(sys_.GetNumWeapons())]

            def spy_contact(c, walk, dt, si, level=None):
                if level is not None:
                    assert [b.__dict__["_dwell"].hex() for b in banks] == [
                        float(_h.combat_dump(b.__dict__["_nslot"])[
                            "_dwell"]).hex() for b in banks]
                    checked.append(level)
                return real_contact(c, walk, dt, si, level=level)
            mp.setattr(nc, "_k2_run_contact", spy_contact)
            sys_.SetSingleFire(0)
            sys_.StartFiring(v)
            for _ in range(60):
                w.tick()
            nc.audit_mirror()
            assert nc.audit_failures() == [], nc.audit_failures()
        finally:
            w.close()
    assert len(checked) > 4 and set(checked) == {sys_.GetPowerLevel()}, \
        checked


# ── Fix round 2: names and the registry read in C ────────────────────────────

def test_field_names_built_at_run_time(monkeypatch):
    """A parsed log's names are pooled views and the applier caches each
    name's str by address (checked by content): 300 distinct names built at
    run time (more than the address cache holds), each written twice in
    interleaved logs, land exactly where apply_writes puts them."""
    py, c = _twins()
    names = ["".join(("_dyn", str(i))) for i in range(300)]
    for rnd in range(2):
        for i in range(0, 300, 30):
            log = [(_handle(j % 4), names[j], float(j * 10 + rnd))
                   for j in range(i, i + 30)]
            _both(log, py, c, monkeypatch)
    assert py.objs[0].__dict__["_dyn296"] == 2961.0


def _kill_in_both(py, c, i):
    """Object i's registry entry turned into a DEAD KeyedRef that stays in
    the registry's `data` (as during an iteration: the removal is
    deferred), in both arms."""
    import gc
    import weakref
    for arm in (py, c):
        guard = weakref._IterationGuard(arm.registry)
        guard.__enter__()
        arm.__dict__.setdefault("guards", []).append(guard)
        h = arm.objs[i].__dict__["_nslot"]
        del arm.objs[i]
        gc.collect()
        assert h in arm.registry.data and arm.registry.data[h]() is None
        assert arm.registry._pending_removals == [h]
    return h


def _release(py, c):
    for arm in (py, c):
        for g in arm.__dict__.pop("guards", []):
            g.__exit__(None, None, None)


def test_registry_dead_ref_answers_none(monkeypatch):
    """A handle whose registry entry is a dead KeyedRef still in `data`:
    `.get` answers None, so walk.obj raises its RuntimeError; the C read of
    `data` must answer the same (no write lands, the same exception), and a
    live handle in the same log is still written."""
    py, c = _twins()
    h = _kill_in_both(py, c, 1)
    try:
        log = [(h, "_f", 1.5), (_handle(0), "_f", 2.5)]
        perr, _cerr = _both(log, py, c, monkeypatch)
        assert isinstance(perr, RuntimeError), perr
        assert py.objs[0].__dict__["_f"] == 2.5
    finally:
        _release(py, c)


class _CountingRegistry(__import__("weakref").WeakValueDictionary):
    """A registry subclass: the C read stands down and asks its `.get`."""

    def get(self, key, default=None):
        self.asked = getattr(self, "asked", 0) + 1
        return super().get(key, default)


def test_registry_subclass_is_asked_through_get(monkeypatch):
    py, c = _twins()
    for arm in (py, c):
        reg = _CountingRegistry()
        for o in arm.objs:
            reg[o.__dict__["_nslot"]] = o
        arm.registry = reg
    log = [(_handle(i), "_f", float(i)) for i in range(4)]
    _both(log, py, c, monkeypatch)
    assert c.registry.asked == py.registry.asked == 4


def test_registry_data_holding_a_non_weakref(monkeypatch):
    """An entry of `data` that is not a weakref: the C read stands down and
    `.get` raises what it raises (calling it)."""
    py, c = _twins()
    for arm in (py, c):
        arm.registry.data[_UNKNOWN] = 7         # not callable
    _both([(_UNKNOWN, "_f", 1.0), (_handle(0), "_f", 2.0)], py, c,
          monkeypatch)


_SWAP = {}


class _SwapLeaf(Leaf):
    """Its wake hook re-pins its handle to another object of the arm (Python
    run between two writes on the same handle)."""

    def _passive_on_wake(self):
        Leaf._passive_on_wake(self)
        walk, h, other = _SWAP[self._arm]
        walk.pins[h] = other


def test_handle_re_resolved_after_python_changes_the_pins(monkeypatch):
    """Consecutive writes on one handle reuse the object walk.obj found only
    while the pins dict is unchanged: a wake hook that re-pins the handle
    between them sends the next write to the new object, as apply_writes
    (walk.obj per write) does."""
    py, c = _twins()
    h = _handle(0)
    for arm in (py, c):
        o = arm.objs[0]
        o.__class__ = _SwapLeaf
        o.__dict__["_passive_asleep"] = True
        _SWAP[arm.arm] = (arm.walk, h, arm.objs[1])
    try:
        log = [(h, "_f", 1.0), (h, "_wake", True), (h, "_f", 2.0),
               (h, "_i", 3)]
        _both(log, py, c, monkeypatch)
        assert py.objs[0].__dict__["_f"] == 1.0
        assert py.objs[1].__dict__["_f"] == 2.0
        assert ("wake", 0) in _EVENTS["c"]
    finally:
        _SWAP.clear()


def test_k0_write_field_bounds():
    """A K0 write names its attribute by Field id (the watcher by its type):
    every id in range is its field's name, the watcher write is
    "_charge_watcher", and a non-watcher id at or past Field::kCount is a
    SystemError (a kernel bug), never the watcher's name."""
    ids = _h.combat_field_names()
    n = len(ids)
    for name, fid in ids.items():
        # Two Python names two kinds share are keyed by kind.
        expect = (name.split(".", 1)[1]
                  if name in ("Subsystem._radius", "Object._invincible")
                  else name)
        assert _h.combat_k0_field_name(fid, False) == expect
    assert _h.combat_k0_field_name(0, True) == "_charge_watcher"
    for bad in (n, n + 1, 10 ** 6):
        with pytest.raises(SystemError):
            _h.combat_k0_field_name(bad, False)
