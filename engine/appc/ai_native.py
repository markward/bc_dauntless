"""The stock gate, the build switch and the counters for the native stock
preprocessors (phase 6 AI part 2; spec 2026-11-05-phase6-engine-stages-native-
design.md section 5).

A native AvoidObstacles / SelectTarget / FireScript path replaces the SDK
Python body only for an instance the SDK would have run UNCHANGED. "Stock"
(the Global Constraints of the plan) means, and this module decides:

* the SDK class of the instance is the SDK's class from the stock
  ``AI/Preprocessors.py`` (``paths.sdk_scripts()``, resolved at use);
* each method the native code replaces or would call is a function defined in
  that file (``__code__.co_filename`` and ``__qualname__``), or one of our own
  wrappers of such a function (``_dauntless_wraps``: the sensor gate's);
* neither the class chain nor the instance ``__dict__`` shadows one;
* each App method the native code replaces a call to is the engine's own
  function (``object_surface_is_stock``, a snapshot taken at import).

Anything else runs the SDK Python for that call. That fallback is permanent: it
is the mod path.

Two rules the checks keep:

* A patch made after the first native call is seen on the NEXT one. The cache
  holds the verdict AND the tuple of functions it was decided from, and every
  call re-resolves that tuple (as ``native_motion._stock_holds`` compares its
  snapshot); an equal tuple means nothing moved.
* An engine subclass's override of a hot method (marked
  ``_dauntless_native_entry = True``) is never accepted by itself. It shadows
  the SDK method, so the check looks the name up on the SDK BASE class instead:
  a mod patching ``AI.Preprocessors.AvoidObstacles.TestCourseOverride`` must not
  be hidden by it.

Cost: ``preprocessor_is_stock`` is a dict hit, one list of ``getattr``s on the
type and a list compare.
"""

import os
import sys
import types

from engine import paths

KINDS = ("avoid", "select", "fire")

_SWITCH_ENV = "DAUNTLESS_NATIVE_AI"


# ── The build switch ─────────────────────────────────────────────────────────

_switch_cache = [None, frozenset(KINDS)]    # [raw string, kinds it enables]


def _parse_switch(raw):
    if raw is None:
        return frozenset(KINDS)
    raw = raw.strip()
    if raw in ("", "1"):
        return frozenset(KINDS)
    if raw == "0":
        return frozenset()
    return frozenset(t for t in (p.strip() for p in raw.split(","))
                     if t in KINDS)


def enabled(kind: str) -> bool:
    """Whether native `kind` is switched on: ``DAUNTLESS_NATIVE_AI`` unset or
    ``1`` = all, ``0`` = none, else a comma list of kinds (an unknown word
    enables nothing). Read at use. The switch exists for the A/B test and the
    measurement; the SDK fallback for a non-stock instance does not depend on it."""
    raw = os.environ.get(_SWITCH_ENV)
    cache = _switch_cache
    if cache[0] != raw:
        cache[0] = raw
        cache[1] = _parse_switch(raw)
    return kind in cache[1]


# ── The stock SDK file ───────────────────────────────────────────────────────

_GONE = object()
_MAX_UNWRAP = 8

#: [sdk_scripts() value it was resolved from, the Preprocessors.py path]
_sdk_file_cache = [None, None]
#: co_filename -> whether it is the stock file (cleared when the root moves)
_filename_verdicts: dict = {}


def _stock_file() -> str:
    root = str(paths.sdk_scripts())
    if _sdk_file_cache[0] != root:
        _sdk_file_cache[0] = root
        _sdk_file_cache[1] = os.path.normcase(os.path.realpath(
            os.path.join(root, "AI", "Preprocessors.py")))
        _filename_verdicts.clear()
    return _sdk_file_cache[1]


def _is_stock_file(co_filename: str) -> bool:
    stock = _stock_file()
    verdict = _filename_verdicts.get(co_filename)
    if verdict is None:
        verdict = os.path.normcase(os.path.realpath(co_filename)) == stock
        _filename_verdicts[co_filename] = verdict
    return verdict


def _unwrap(fn):
    """`fn` with every ``_dauntless_wraps`` link followed (our own wrappers
    name the function they wrap). Bounded, so a cycle ends as not-a-function."""
    for _ in range(_MAX_UNWRAP):
        inner = getattr(fn, "_dauntless_wraps", None)
        if inner is None:
            return fn
        fn = inner
    return None


def is_stock_sdk_function(fn, qualname: str) -> bool:
    """`fn`, after unwrapping ``_dauntless_wraps`` chains, is a function of the
    stock SDK ``AI/Preprocessors.py`` named `qualname`."""
    fn = _unwrap(fn)
    if not isinstance(fn, types.FunctionType):
        return False
    return fn.__qualname__ == qualname and _is_stock_file(
        fn.__code__.co_filename)


# ── preprocessor_is_stock ────────────────────────────────────────────────────

def _sdk_base(cls, sdk_class_name):
    """The SDK class in `cls`'s MRO called `sdk_class_name`, or None."""
    for klass in cls.__mro__:
        if klass.__name__ == sdk_class_name:
            return klass
    return None


#: (type, sdk_class_name, methods) -> [base, resolved, verdict]
_pp_cache: dict = {}


def _resolve_pp(cls, base, methods):
    """The functions the verdict is decided from, in order: each method as the
    type resolves it, then (only where that is a marked engine override) as
    the SDK base does."""
    return [getattr(cls, n, _GONE) for n in methods] + \
           [getattr(base, n, _GONE) for n in methods]


def _decide_pp(cls, base, methods, resolved) -> bool:
    n = len(methods)
    for i, name in enumerate(methods):
        fn = resolved[i]
        if getattr(fn, "_dauntless_native_entry", False):
            fn = resolved[n + i]            # the SDK method it shadows
        if fn is _GONE:
            return False
        if not is_stock_sdk_function(fn, "%s.%s" % (base.__name__, name)):
            return False
    return True


def preprocessor_is_stock(inst, sdk_class_name: str,
                          methods: tuple) -> bool:
    """`inst` is the SDK's `sdk_class_name` running unchanged for each of
    `methods` (the module docstring)."""
    cls = type(inst)
    key = (cls, sdk_class_name, methods)
    entry = _pp_cache.get(key)
    if entry is None:
        base = _sdk_base(cls, sdk_class_name)
        if base is None:
            entry = [None, None, False]
        else:
            resolved = _resolve_pp(cls, base, methods)
            entry = [base, resolved, _decide_pp(cls, base, methods, resolved)]
        _pp_cache[key] = entry
    elif entry[0] is not None:
        resolved = _resolve_pp(cls, entry[0], methods)
        if resolved != entry[1]:            # something moved: decide again
            entry[1] = resolved
            entry[2] = _decide_pp(cls, entry[0], methods, resolved)
    if not entry[2]:
        return False
    return inst.__dict__.keys().isdisjoint(methods)


# ── object_surface_is_stock ──────────────────────────────────────────────────

def _function_table(cls) -> dict:
    return {n: v for n, v in cls.__dict__.items()
            if isinstance(v, types.FunctionType)}


def _take_surface_snapshot() -> dict:
    """{class: {name: function}} for the engine classes whose methods the
    native code stands in for, taken at import, before any test, tool or mod
    can replace a name."""
    from engine.appc import projectiles
    from engine.appc.debris_chunk import DebrisChunk
    from engine.appc.objects import (DamageableObject, ObjectClass,
                                     PhysicsObjectClass)
    from engine.appc.ships import ShipClass
    classes = [ObjectClass, PhysicsObjectClass, DamageableObject, ShipClass,
               projectiles.Torpedo, DebrisChunk]
    try:
        from engine.rocks.rock import RockClass
        classes.append(RockClass)
    except ImportError:
        pass
    return {cls: _function_table(cls) for cls in classes}


_SURFACE_SNAPSHOT = _take_surface_snapshot()


def _snapshot_function(cls, name):
    """What the import-time snapshot holds for `name` on the nearest engine
    class of `cls`'s MRO that had it then (`_GONE` if none did). A class that
    only re-sets that same function is therefore still stock."""
    for klass in cls.__mro__:
        table = _SURFACE_SNAPSHOT.get(klass)
        if table is not None and name in table:
            return table[name]
    return _GONE


#: (type, names) -> [resolved functions, verdict]
_surface_cache: dict = {}


def _decide_surface(cls, names, resolved) -> bool:
    for name, fn in zip(names, resolved):
        want = _snapshot_function(cls, name)
        if fn is _GONE or fn is not want:
            return False
    return True


def object_surface_is_stock(obj, names: tuple) -> bool:
    """Each of `names` resolves on ``type(obj)`` to the function the import-time
    snapshot holds for the engine class defining it, and `obj` shadows none."""
    cls = type(obj)
    key = (cls, names)
    entry = _surface_cache.get(key)
    resolved = [getattr(cls, n, _GONE) for n in names]
    if entry is None or entry[0] != resolved:
        entry = [resolved, _decide_surface(cls, names, resolved)]
        _surface_cache[key] = entry
    if not entry[1]:
        return False
    return obj.__dict__.keys().isdisjoint(names)


# ── Counters ─────────────────────────────────────────────────────────────────

REASONS = ("switch", "not_stock", "surface", "no_mirror")

_counts: dict = {}


def reset_stats() -> None:
    _counts.clear()
    for kind in KINDS:
        _counts[kind] = {"native": 0, "python": 0, "reasons": {}}


reset_stats()


def note(kind: str, path: str, reason: str = "") -> None:
    """Count one call of `kind` that ran `path` ("native" or "python"); a
    python call names why (REASONS)."""
    c = _counts[kind]
    c[path] += 1
    if reason:
        r = c["reasons"]
        r[reason] = r.get(reason, 0) + 1


def stats() -> dict:
    """{kind: {"native": n, "python": n, "reasons": {reason: n}}} since the
    last reset (a copy)."""
    return {k: {"native": c["native"], "python": c["python"],
                "reasons": dict(c["reasons"])} for k, c in _counts.items()}
