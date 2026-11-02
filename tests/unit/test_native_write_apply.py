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
    """What a system's _live_held_offset returns: a new object per call."""

    def __init__(self, idx):
        self.idx = idx


class Leaf:
    """Every apply kind the reference knows, on one class: NativeFields
    (plain), a ref, a ref list, a wake field, a Python-setter field (a
    FrozenField: its thaw runs Python) and a field with no quiet write."""

    _f = nc.NativeField(float)
    _i = nc.NativeField(int)
    _b = nc.NativeField(bool)
    _off = nc.NativeField(nc.OFFSET)
    _ref = nc.NativeRefField("Object")
    _target_list = nc.NativeRefList("Object")
    _wake = nc.NativeWakeField(bool)
    _frozen = nc.NativeFrozenField(float)
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

    def _live_held_offset(self):
        _EVENTS[self._arm].append(("offset", self._idx))
        if self.__dict__.get("_offset_boom"):
            raise _Boom("offset %d" % self._idx)
        return _Offset(self._idx)


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
        self.walk = nc._K1Walk()


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
        # _live_held_offset: AttributeError) or an unknown handle.
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
            py.walk, c.walk = nc._K1Walk(), nc._K1Walk()
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
    a phaser bank's `_firing` WAKE, a tractor's PYTHON (its thaw), a
    tube's PLAIN, a system's `_target` REF and `_target_list` REFS."""
    kinds = nc._applier_context(nc._K1Walk())[3]
    assert kinds[(ws.PhaserBank, "_firing")] == nc.APPLY_WAKE
    assert kinds[(ws.TractorBeam, "_firing")] == nc.APPLY_PYTHON
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
    FrozenField's: store, then the thaw) at its place in the log: it sees
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


def test_records_return_empty_writes(monkeypatch):
    """K1 records, and K2 records with no queued resting contact, come back
    with their writes already applied (the C counter moves inside next()):
    `writes` is []. A K2 record carrying queued contacts returns the count
    of writes still pending, applied by _k2_deliver. The Galaxy's phasers
    rest on the Vor'cha (queued contacts) until tick 30; the Vor'cha's own
    phasers are offline throughout (their stop is logged writes every tick,
    on a record with no queued contact once the Galaxy stops)."""
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
    assert k1 and all(rec[-1] == [] for rec, _n in k1)
    assert any(n > 0 for _rec, n in k1), "no K1 record carried writes"
    plain = [(rec, n) for rec, n in k2 if not rec[-2]]
    queued = [(rec, n) for rec, n in k2 if rec[-2]]
    assert plain and all(rec[-1] == [] for rec, _n in plain)
    assert any(n > 0 for _rec, n in plain), "no plain K2 record's writes"
    assert queued and all(type(rec[-1]) is int and n == 0
                          for rec, n in queued)
    assert any(rec[-1] > 0 for rec, _n in queued)


def test_k2_queued_contacts_interleave_with_c_applied_writes(monkeypatch):
    """Each queued resting contact runs after exactly the writes logged
    before its `at` and none after: at the k-th contact, the banks of the
    contacts before it (and its own) hold their new `_dwell`, the later
    ones the old; after the record, all hold the new."""
    checked = []
    state = {}
    with monkeypatch.context() as mp:
        w = _world(mp, "wa_interleave")
        try:
            real_next, real_contact = _h.combat_k2_next, nc._k2_run_contact
            real_deliver = nc._k2_deliver

            def dwell(h):
                return nc._registry[h].__dict__["_dwell"].hex()

            def spy_deliver(*args):
                result = real_deliver(*args)
                banks = state.pop("banks", None)
                if banks is not None:
                    # Before the record's own effect: every write applied.
                    assert [dwell(h) for h in banks] == state["new"]
                    assert state["k"] == len(banks)
                return result

            def spy_next():
                rec = real_next()
                banks = [q[1] for q in rec[-2]]
                ats = [q[0] for q in rec[-2]]
                # Contacts each after writes of their own (dwell moved).
                if len(banks) > 1 and ats[0] > 0 \
                        and ats == sorted(set(ats)):
                    state["banks"] = banks
                    state["old"] = [dwell(h) for h in banks]
                    state["new"] = [float(_h.combat_dump(h)["_dwell"]).hex()
                                    for h in banks]
                    assert all(o != n for o, n in zip(state["old"],
                                                      state["new"]))
                    state["k"] = 0
                return rec

            def spy_contact(c, walk, dt, si):
                banks = state.get("banks")
                if banks is not None:
                    k = state["k"]
                    assert c[0] == banks[k]
                    want = state["new"][:k + 1] + state["old"][k + 1:]
                    assert [dwell(h) for h in banks] == want
                    state["k"] = k + 1
                    checked.append(len(banks))
                return real_contact(c, walk, dt, si)
            mp.setattr(_h, "combat_k2_next", spy_next)
            mp.setattr(nc, "_k2_run_contact", spy_contact)
            mp.setattr(nc, "_k2_deliver", spy_deliver)
            g, v = w.ships["Galaxy"], w.ships["Vorcha"]
            g.GetPhaserSystem().SetSingleFire(0)
            g.GetPhaserSystem().StartFiring(v)
            for _ in range(60):
                w.tick()
            nc.audit_mirror()
            assert nc.audit_failures() == [], nc.audit_failures()
        finally:
            w.close()
    assert len(checked) > 4, checked
