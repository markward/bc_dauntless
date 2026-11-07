"""The stock verdict's native memo (phase 6 AI part 2, Task 4 fix round 1;
engine/appc/ai_native.py's preprocessor_is_stock, native/src/host/
host_bindings.cc's `stockmemo`).

preprocessor_is_stock is the only place the stock rule is written. Its
verdict for a class is decided in Python once per class VERSION: the host
remembers it keyed by the type's version tag, which CPython renews whenever an
attribute of the type or of any base is set or deleted. The instance-dict
half (no gated name shadowed on the instance) is checked natively on every
call. Pinned here for each of the three native kinds (AvoidObstacles,
SelectTarget, FireScript), as the engine binds them: a second call is a memo
hit (the Python decision does not run); a class-level patch after the verdict
was cached is seen on the next call, and so is putting it back; an
instance-dict override is seen; a subclass created later is decided fresh; a
type under another metaclass always asks Python."""
import sys

import pytest

import App
import AI.Preprocessors as pp

from engine.appc import ai_native
from engine.appc import ai_optimized
from engine.appc.ai import PreprocessingAI_Create

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

pytestmark = pytest.mark.skipif(_h is None, reason="native host not built")


def _bound(sdk_instance):
    """The SDK instance as the engine stores it (ai_optimized's alias)."""
    node = PreprocessingAI_Create(None, "Memo")
    node.SetPreprocessingMethod(sdk_instance, "Update")
    return node.GetPreprocessingInstance()


#: kind -> (make the SDK instance, SDK class name, the gated methods, one of
#: them to patch)
_KINDS = {
    "avoid": (lambda: pp.AvoidObstacles(), "AvoidObstacles",
              ai_optimized._AVOID_METHODS, "NeedToAvoid"),
    "select": (lambda: pp.SelectTarget(App.ObjectGroup()), "SelectTarget",
               ai_optimized._SELECT_METHODS, "GetTargetRating"),
    "fire": (lambda: pp.FireScript("Target"), "FireScript",
             ai_optimized._FIRE_METHODS, "FireSystemAtTarget"),
}


@pytest.fixture
def decisions(monkeypatch):
    """How many times the Python decision ran (it resolves the class's
    methods each time it runs; a memo hit resolves nothing)."""
    count = [0]
    real = ai_native._resolve_pp

    def counting(*args, **kw):
        count[0] += 1
        return real(*args, **kw)
    monkeypatch.setattr(ai_native, "_resolve_pp", counting)
    return count


@pytest.mark.parametrize("kind", sorted(_KINDS))
def test_a_second_call_is_a_memo_hit(kind, decisions):
    make, name, methods, _patch = _KINDS[kind]
    inst = _bound(make())
    assert ai_native.preprocessor_is_stock(inst, name, methods)
    before = decisions[0]
    for _ in range(3):
        assert ai_native.preprocessor_is_stock(inst, name, methods)
    assert decisions[0] == before


@pytest.mark.parametrize("kind", sorted(_KINDS))
def test_a_class_patch_after_a_cached_verdict_is_seen_on_the_next_call(
        kind, monkeypatch, decisions):
    make, name, methods, patched_name = _KINDS[kind]
    inst = _bound(make())
    assert ai_native.preprocessor_is_stock(inst, name, methods)
    assert ai_native.preprocessor_is_stock(inst, name, methods)   # cached
    sdk_class = getattr(pp, name)
    original = sdk_class.__dict__[patched_name]

    def patched(self, *args):
        return original(self, *args)
    # On the SDK class: a base of the engine subclass, so its tag goes too.
    monkeypatch.setattr(sdk_class, patched_name, patched)
    assert not ai_native.preprocessor_is_stock(inst, name, methods)
    assert not ai_native.preprocessor_is_stock(inst, name, methods)
    monkeypatch.setattr(sdk_class, patched_name, original)
    assert ai_native.preprocessor_is_stock(inst, name, methods)
    # And on the engine subclass itself.
    monkeypatch.setattr(type(inst), patched_name, patched, raising=False)
    assert not ai_native.preprocessor_is_stock(inst, name, methods)
    monkeypatch.delattr(type(inst), patched_name)
    assert ai_native.preprocessor_is_stock(inst, name, methods)


@pytest.mark.parametrize("kind", sorted(_KINDS))
def test_an_instance_dict_override_is_seen(kind):
    make, name, methods, patched_name = _KINDS[kind]
    inst = _bound(make())
    assert ai_native.preprocessor_is_stock(inst, name, methods)
    assert ai_native.preprocessor_is_stock(inst, name, methods)   # cached
    other = _bound(make())
    setattr(inst, patched_name, lambda *a: None)
    assert not ai_native.preprocessor_is_stock(inst, name, methods)
    # Only that instance: another of the same class is still stock.
    assert ai_native.preprocessor_is_stock(other, name, methods)
    del inst.__dict__[patched_name]
    assert ai_native.preprocessor_is_stock(inst, name, methods)


@pytest.mark.parametrize("kind", sorted(_KINDS))
def test_a_subclass_created_later_is_decided_fresh(kind, decisions):
    make, name, methods, patched_name = _KINDS[kind]
    inst = _bound(make())
    assert ai_native.preprocessor_is_stock(inst, name, methods)
    plain = type("Later", (type(inst),), {})
    a = plain.__new__(plain)
    a.__dict__ = inst.__dict__
    before = decisions[0]
    assert ai_native.preprocessor_is_stock(a, name, methods)
    assert decisions[0] > before
    mod = type("LaterMod", (type(inst),), {patched_name: lambda self, *a: 0})
    b = mod.__new__(mod)
    b.__dict__ = dict(inst.__dict__)
    assert not ai_native.preprocessor_is_stock(b, name, methods)
    assert ai_native.preprocessor_is_stock(inst, name, methods)


def test_a_type_under_another_metaclass_always_asks_python(decisions):
    meta = type("Meta", (type,), {})
    inst = _bound(pp.SelectTarget(App.ObjectGroup()))
    cls = meta("Metered", (type(inst),), {})
    obj = cls.__new__(cls)
    obj.__dict__ = inst.__dict__
    methods = ai_optimized._SELECT_METHODS
    assert ai_native.preprocessor_is_stock(obj, "SelectTarget", methods)
    before = decisions[0]
    assert ai_native.preprocessor_is_stock(obj, "SelectTarget", methods)
    assert decisions[0] == before + 1


def test_the_memo_answers_only_what_python_decided():
    """The host returns None (ask Python) for a type it was never told
    about, and a stored verdict needs the tag it was decided under."""
    inst = _bound(pp.FireScript("Target"))
    cls = type("Fresh", (type(inst),), {})
    obj = cls.__new__(cls)
    obj.__dict__ = inst.__dict__
    methods = ai_optimized._FIRE_METHODS
    assert _h.ai_stock_check(obj, "FireScript", methods) is None
    tag = _h.ai_stock_tag(cls)
    assert tag != 0
    cls.extra = 1                          # the type moves while "deciding"
    _h.ai_stock_remember(cls, "FireScript", methods, True, tag)
    assert _h.ai_stock_check(obj, "FireScript", methods) is None
    _h.ai_stock_remember(cls, "FireScript", methods, True, _h.ai_stock_tag(cls))
    assert _h.ai_stock_check(obj, "FireScript", methods) is True
    _h.ai_stock_remember(cls, "FireScript", methods, False, _h.ai_stock_tag(cls))
    assert _h.ai_stock_check(obj, "FireScript", methods) is False


# ── FireScript's module surface (Task 5: ai_optimized._fire_surface_globals) ─
#
# The surface decision (the engine's App, CPython's builtins, the engine
# TGPoint3 / TGMatrix3 and the module globals the mirrored readers and
# GetChildTargets rest on) is Python's; the host remembers its answer under
# the version tag of every dict and type it read and answers while they all
# hold.

@pytest.fixture
def surface_decisions(monkeypatch):
    count = [0]
    real = ai_optimized._decide_fire_surface

    def counting(*args, **kw):
        count[0] += 1
        return real(*args, **kw)
    monkeypatch.setattr(ai_optimized, "_decide_fire_surface", counting)
    return count


def test_the_fire_surface_is_a_memo_hit_while_nothing_moves(surface_decisions):
    g = ai_optimized._fire_surface_globals(pp.FireScript)
    assert g is pp.__dict__
    before = surface_decisions[0]
    for _ in range(5):
        assert ai_optimized._fire_surface_globals(pp.FireScript) is g
    assert surface_decisions[0] == before, "the host memo never answered"


def _surface_patches():
    from engine.appc import math as engine_math
    from engine.appc import objects
    from engine.appc.math import TGMatrix3, TGPoint3
    real_cast = App.PhysicsObjectClass_Cast
    return {
        "point method": lambda mp: mp.setattr(TGPoint3, "Dot",
                                              lambda s, o: 0.0),
        "matrix method": lambda mp: mp.setattr(TGMatrix3, "Transpose",
                                               lambda s: s),
        "objects TGPoint3": lambda mp: mp.setattr(
            objects, "TGPoint3", type("P", (TGPoint3,), {})),
        "math sqrt": lambda mp: mp.setattr(__import__("math"), "sqrt",
                                           lambda x: x),
        "engine math module": lambda mp: mp.setattr(engine_math, "_math",
                                                    None),
        "App cast": lambda mp: mp.setattr(App, "PhysicsObjectClass_Cast",
                                          lambda o: real_cast(o)),
        "SDK module builtin": lambda mp: mp.setattr(pp, "len", len,
                                                    raising=False),
        "SDK module App": lambda mp: mp.setattr(pp, "App", object()),
        "builtins": lambda mp: mp.setattr(__import__("builtins"), "range",
                                          lambda *a, _r=range: _r(*a)),
        "child recursion": lambda mp: mp.setattr(
            ai_optimized, "GetChildTargets", lambda s, x: []),
        "Update wrapped": lambda mp: mp.setattr(
            pp.FireScript.Update, "_dauntless_wraps", pp.FireScript.Update,
            raising=False),
        "Update replaced": lambda mp: mp.setattr(
            pp.FireScript, "Update", lambda self, d: 0),
    }


@pytest.mark.parametrize("name", sorted(_surface_patches()))
def test_a_surface_change_after_a_memo_hit_is_seen(name, monkeypatch):
    """Everything the decision reads, changed after the answer was stored:
    the next call is not stock; undone, stock again."""
    g = ai_optimized._fire_surface_globals(pp.FireScript)
    assert ai_optimized._fire_surface_globals(pp.FireScript) is g
    with monkeypatch.context() as mp:
        _surface_patches()[name](mp)
        for _ in range(2):
            got = ai_optimized._fire_surface_globals(pp.FireScript)
            # A replaced Update is answered from ITS globals (rejecting it is
            # preprocessor_is_stock's job); never the stored SDK answer.
            assert got is not g
            if name != "Update replaced":
                assert got is None
    assert ai_optimized._fire_surface_globals(pp.FireScript) is g


def test_the_surface_memo_stores_nothing_decided_under_moved_tags():
    from engine.appc.math import TGPoint3
    watched = (pp.FireScript, pp.__dict__, TGPoint3)
    tags = _h.ai_memo_tags(watched)
    assert isinstance(tags, tuple) and len(tags) == 3
    miss = object()
    key = object()
    pp.__dict__["_memo_probe"] = 1               # the module dict moves
    try:
        _h.ai_memo_put(key, watched, tags, "answer")
        assert _h.ai_memo_get(key, miss) is miss
        _h.ai_memo_put(key, watched, _h.ai_memo_tags(watched), "answer")
        assert _h.ai_memo_get(key, miss) == "answer"
    finally:
        del pp.__dict__["_memo_probe"]
    assert _h.ai_memo_get(key, miss) is miss     # and moved back: not held
    # Something that is neither a dict nor a type cannot be tagged.
    assert _h.ai_memo_tags((object(),)) is None


# ── The memos' Python-version guard and self-test (final fix) ──────────────
#
# The memos read CPython 3.11 internals (a dict's ma_version_tag, a type's
# tp_version_tag, _PyDict_HasOnlyStringKeys). Compiled for any other Python
# they are off: every query answers "ask Python" (None / not cached), never a
# stale yes. On 3.11 a self-test runs once, at the first query, and turns
# them off if a dict mutation or a class setattr does not move the tag the
# memo keys on. DAUNTLESS_AI_MEMOS=0 (read once, at that first query) and
# ai_memo_force_off force the off mode, which must leave every native path
# exact (the test_native_* exactness tests run both ways; the A/B too).

def test_the_memo_self_test_passes_and_the_memos_are_on_here():
    status = _h.ai_memo_status()
    on_311 = sys.version_info[:2] == (3, 11)
    assert status["compiled"] is on_311, status
    assert status["self_test"] is on_311, status
    assert status["forced_off"] is False, status
    assert status["enabled"] is on_311, status


@pytest.fixture
def memos_off():
    _h.ai_memo_force_off(True)
    try:
        yield
    finally:
        _h.ai_memo_force_off(False)


def test_forced_off_memos_answer_ask_python(decisions, memos_off):
    assert _h.ai_memo_status()["enabled"] is False
    assert _h.ai_memo_status()["forced_off"] is True
    inst = _bound(pp.FireScript("Target"))
    methods = ai_optimized._FIRE_METHODS
    assert _h.ai_stock_tag(type(inst)) == 0
    assert _h.ai_stock_check(inst, "FireScript", methods) is None
    before = decisions[0]
    for _ in range(3):
        assert ai_native.preprocessor_is_stock(inst, "FireScript", methods)
    assert decisions[0] == before + 3          # Python decided every call
    watched = (pp.FireScript, pp.__dict__)
    assert _h.ai_memo_tags(watched) is None
    miss = object()
    assert _h.ai_memo_get(pp.FireScript, miss) is miss


def test_a_verdict_stored_while_on_is_not_answered_when_forced_off():
    inst = _bound(pp.FireScript("Target"))
    methods = ai_optimized._FIRE_METHODS
    assert ai_native.preprocessor_is_stock(inst, "FireScript", methods)
    assert _h.ai_stock_check(inst, "FireScript", methods) is True
    key, miss = object(), object()
    watched = (pp.__dict__,)
    _h.ai_memo_put(key, watched, _h.ai_memo_tags(watched), "answer")
    assert _h.ai_memo_get(key, miss) == "answer"
    _h.ai_memo_force_off(True)
    try:
        assert _h.ai_stock_check(inst, "FireScript", methods) is None
        assert _h.ai_memo_get(key, miss) is miss
    finally:
        _h.ai_memo_force_off(False)


# ── One gate-cost model: avoid's and select's surfaces, and the store ──────
#
# Like FireScript's (_fire_surface_globals above), each is decided in Python
# and remembered by the host under the version tags of everything the
# decision read; any change to one of them is seen on the next call.

def _counting(monkeypatch, name):
    count = [0]
    real = getattr(ai_optimized, name)

    def counting(*args, **kw):
        count[0] += 1
        return real(*args, **kw)
    monkeypatch.setattr(ai_optimized, name, counting)
    return count


def _avoid_node():
    return _bound(pp.AvoidObstacles())


def test_the_avoid_and_select_surfaces_are_memo_hits(monkeypatch):
    avoid = _counting(monkeypatch, "_decide_avoid_surface")
    select = _counting(monkeypatch, "_decide_select_surface")
    node = _avoid_node()
    assert ai_optimized._avoid_surface_is_stock(node) is True
    assert ai_optimized._select_surface_app(pp.SelectTarget) is App
    before = (avoid[0], select[0])
    for _ in range(5):
        assert ai_optimized._avoid_surface_is_stock(node) is True
        assert ai_optimized._select_surface_app(pp.SelectTarget) is App
    assert (avoid[0], select[0]) == before, "the host memo never answered"


def _avoid_surface_patches():
    import math
    import types
    from engine.appc.math import TGPoint3
    real_cast = App.PhysicsObjectClass_Cast
    need = pp.AvoidObstacles.__dict__["NeedToAvoid"]
    return {
        "point method": lambda mp: mp.setattr(TGPoint3, "Dot",
                                              lambda s, o: 0.0),
        "App cast": lambda mp: mp.setattr(App, "PhysicsObjectClass_Cast",
                                          lambda o: real_cast(o)),
        "App TGPoint3": lambda mp: mp.setattr(
            App, "TGPoint3", type("P", (TGPoint3,), {})),
        "math sqrt": lambda mp: mp.setattr(math, "sqrt", lambda x: x),
        "SDK module App": lambda mp: mp.setattr(pp, "App", object()),
        "SDK module math": lambda mp: mp.setattr(
            pp, "math", types.ModuleType("math")),
        "NeedToAvoid wrapped": lambda mp: mp.setattr(
            need, "_dauntless_wraps", need, raising=False),
        "NeedToAvoid replaced": lambda mp: mp.setattr(
            pp.AvoidObstacles, "NeedToAvoid", lambda self, *a: 0),
    }


@pytest.mark.parametrize("name", sorted(_avoid_surface_patches()))
def test_an_avoid_surface_change_after_a_memo_hit_is_seen(name, monkeypatch):
    decided = _counting(monkeypatch, "_decide_avoid_surface")
    node = _avoid_node()
    assert ai_optimized._avoid_surface_is_stock(node) is True
    assert ai_optimized._avoid_surface_is_stock(node) is True
    with monkeypatch.context() as mp:
        _avoid_surface_patches()[name](mp)
        before = decided[0]
        got = ai_optimized._avoid_surface_is_stock(node)
        assert decided[0] == before + 1, "a stale memo answered"
        # A replaced NeedToAvoid is decided from ITS globals (rejecting it is
        # preprocessor_is_stock's job); everything else is not stock.
        if name != "NeedToAvoid replaced":
            assert got is False
            assert ai_optimized._avoid_surface_is_stock(node) is False
    assert ai_optimized._avoid_surface_is_stock(node) is True


def _select_surface_patches():
    import math
    import types
    from engine.appc import math as engine_math
    from engine.appc import object_types
    from engine.appc import objects
    from engine.appc import set_index
    from engine.appc import ships
    from engine.appc.math import TGPoint3
    rating = pp.SelectTarget.__dict__["GetTargetRating"]
    return {
        "SDK module App": lambda mp: mp.setattr(pp, "App", object()),
        "math acos": lambda mp: mp.setattr(math, "acos", lambda x: x),
        "math pi": lambda mp: mp.setattr(math, "pi", 3.0),
        "objects TGPoint3": lambda mp: mp.setattr(
            objects, "TGPoint3", type("P", (TGPoint3,), {})),
        "point method": lambda mp: mp.setattr(TGPoint3, "Length",
                                              lambda s: 0.0),
        "engine math module": lambda mp: mp.setattr(engine_math, "_math",
                                                    None),
        "resolve_class": lambda mp: mp.setattr(object_types, "resolve_class",
                                               lambda v: None),
        "registry": lambda mp: mp.setitem(object_types._BY_TAG, App.CT_SHIP,
                                          type("NotAShip", (), {})),
        "App CT_SHIP": lambda mp: mp.setattr(App, "CT_SHIP", 987654321),
        "ships ShipClass": lambda mp: mp.setattr(
            ships, "ShipClass", type("S", (ships.ShipClass,), {})),
        "ships module": lambda mp: mp.setitem(
            sys.modules, "engine.appc.ships",
            types.ModuleType("engine.appc.ships")),
        "set index ShipClass": lambda mp: mp.setattr(
            set_index, "_ShipClass", type("S", (ships.ShipClass,), {})),
        "GetTargetRating wrapped": lambda mp: mp.setattr(
            rating, "_dauntless_wraps", rating, raising=False),
        "GetTargetRating replaced": lambda mp: mp.setattr(
            pp.SelectTarget, "GetTargetRating", lambda self, t: 0.0),
    }


@pytest.mark.parametrize("name", sorted(_select_surface_patches()))
def test_a_select_surface_change_after_a_memo_hit_is_seen(name, monkeypatch):
    decided = _counting(monkeypatch, "_decide_select_surface")
    base = pp.SelectTarget
    assert ai_optimized._select_surface_app(base) is App
    assert ai_optimized._select_surface_app(base) is App
    with monkeypatch.context() as mp:
        _select_surface_patches()[name](mp)
        before = decided[0]
        got = ai_optimized._select_surface_app(base)
        assert decided[0] == before + 1, "a stale memo answered"
        if name != "GetTargetRating replaced":
            assert got is None
            assert ai_optimized._select_surface_app(base) is None
    assert ai_optimized._select_surface_app(base) is App


_STORE_FNS = {"avoid": "_native_store_ok", "select": "_select_store_ok",
              "fire": "_fire_store_ok"}


def _store_patches():
    from engine.appc import objects
    from engine.appc import transform_store as ts
    real_get_store = objects.get_store
    store = ts.NativeTransformStore

    def wrap(name):
        real = store.__dict__[name]
        return lambda mp: mp.setattr(store, name,
                                     lambda self, *a: real(self, *a))
    return {
        "get_store replaced": (lambda mp: mp.setattr(
            objects, "get_store", lambda: real_get_store()), set(_STORE_FNS)),
        "store swapped": (lambda mp: mp.setattr(ts, "_STORE", object()),
                          set(_STORE_FNS)),
        "get_position": (wrap("get_position"), set(_STORE_FNS)),
        "get_rotation": (wrap("get_rotation"), {"fire"}),
        "get_rotation_col": (wrap("get_rotation_col"), {"select"}),
    }


@pytest.mark.parametrize("name", sorted(_store_patches()))
def test_a_store_change_after_a_memo_hit_is_seen(name, monkeypatch):
    decided = _counting(monkeypatch, "_decide_store")
    fns = {k: getattr(ai_optimized, v) for k, v in _STORE_FNS.items()}
    for _ in range(2):
        assert all(fn() is True for fn in fns.values())
    before = decided[0]
    assert all(fn() is True for fn in fns.values())
    assert decided[0] == before, "the host memo never answered"
    patch, hit = _store_patches()[name]
    with monkeypatch.context() as mp:
        patch(mp)
        for _ in range(2):
            got = {k: fn() for k, fn in fns.items()}
            assert got == {k: k not in hit for k in fns}, got
    assert all(fn() is True for fn in fns.values())


# ── Overflowing a memo, and the host's own references (subprocesses) ──────

def _child(name):
    import os
    import subprocess
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    env = dict(os.environ, AI_MEMO_CHILD="1")
    proc = subprocess.run(
        [sys.executable, "-m", "pytest",
         "tests/helpers/ai_memo_child.py::" + name, "-q", "-x",
         "-p", "no:cacheprovider"],
        cwd=str(root), env=env, capture_output=True, text=True)
    assert proc.returncode == 0, (proc.returncode, proc.stdout[-3000:],
                                  proc.stderr[-2000:])
    assert " passed" in proc.stdout, proc.stdout[-2000:]


def test_a_memo_overflow_survives_reentrant_puts_from_dying_keys():
    """A bounded memo that is full is emptied by swapping its entries out
    and only then releasing them: a key's release can run a weakref
    callback that stores into the same memo, which must find it whole."""
    _child("test_child_reentrant_surface_memo_overflow")


@pytest.mark.skipif(sys.version_info >= (3, 12),
                    reason="interned strings are immortal from 3.12")
def test_the_hosts_hold_one_reference_per_string_they_keep():
    _child("test_child_host_init_holds_one_reference_per_kept_string")
