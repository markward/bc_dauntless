import itertools

from engine.core import stub_telemetry

_counter = itertools.count(1)
_registry: dict[int, "TGObject"] = {}


def get_object_by_id(obj_id: int) -> "TGObject | None":
    return _registry.get(obj_id)


def unregister(obj_id: int) -> None:
    """Drop an object from the id registry so get_object_by_id() (and thus
    App.TGObject_GetTGObjectPtr) returns None for it.

    Mirrors the original engine destroying a finished TGObject: some SDK code
    (notably MissionLib.QueueActionToPlay) stores a TGSequence's id and relies
    on that id becoming invalid once the sequence completes, so the next lookup
    returns null and a fresh master sequence is started. See
    engine/appc/actions.py TGSequence for the sole current caller.
    """
    _registry.pop(obj_id, None)


def register(obj: "TGObject") -> None:
    """Re-add an object to the id registry (e.g. a completed sequence that is
    replayed). Idempotent."""
    _registry[obj.GetObjID()] = obj


class _Stub:
    """Recursive stub: attribute access and calls return another _Stub.

    Returned by TGObject.__getattr__ for unimplemented engine methods so SDK
    scripts can chain calls like pMission.GetFriendlyGroup().AddName(...).

    Carries its own (name, owner) identity purely so stub_telemetry can report
    *what* was accessed; this does not change any behavior when telemetry is
    disabled.
    """

    def __init__(self, name: str = "?", owner: str = "?") -> None:
        self._stub_name = name
        self._stub_owner = owner

    def __getattr__(self, name: str) -> "_Stub":
        if name in ("_stub_name", "_stub_owner"):
            # Break the recursion if these are accessed before __init__ ran
            # (e.g. during unpickling) — never build a stub for them.
            raise AttributeError(name)
        if stub_telemetry.ENABLED and not (name.startswith("__") and name.endswith("__")):
            stub_telemetry.record_attr(self._stub_owner, self._stub_name + "." + name)
        return _Stub(name, self._stub_owner)

    def __call__(self, *args, **kwargs) -> "_Stub":
        return _Stub(self._stub_name, self._stub_owner)

    def __bool__(self) -> bool:
        if stub_telemetry.ENABLED:
            stub_telemetry.record_bool(self._stub_owner)
        return True

    def __hash__(self) -> int:
        return id(self)

    def __len__(self) -> int:
        return 0

    def __iter__(self):
        return iter([])

    def __getitem__(self, key) -> "_Stub":
        return _Stub()

    def __setitem__(self, key, value) -> None:
        pass

    def __delitem__(self, key) -> None:
        pass

    def __int__(self) -> int: return 0
    def __float__(self) -> float: return 0.0
    def __index__(self) -> int: return 0
    def __add__(self, o): return o if isinstance(o, str) else 0
    def __radd__(self, o): return o if isinstance(o, str) else 0
    def __sub__(self, o): return 0
    def __rsub__(self, o): return 0
    def __mul__(self, o): return 0
    def __rmul__(self, o): return 0
    def __truediv__(self, o): return 0.0
    def __rtruediv__(self, o): return 0.0
    def __floordiv__(self, o): return 0
    def __rfloordiv__(self, o): return 0
    def __mod__(self, o): return 0
    def __rmod__(self, o): return 0
    def __neg__(self): return 0
    def __pos__(self): return 0
    def __abs__(self): return 0
    def __or__(self, o): return 0
    def __ror__(self, o): return 0
    def __and__(self, o): return 0
    def __rand__(self, o): return 0
    def __xor__(self, o): return 0
    def __rxor__(self, o): return 0
    def __lshift__(self, o): return 0
    def __rshift__(self, o): return 0
    def __invert__(self): return 0
    def __lt__(self, o): return False
    def __le__(self, o): return False
    def __gt__(self, o): return False
    def __ge__(self, o): return False
    def __eq__(self, o): return isinstance(o, type(self))
    def __ne__(self, o): return not isinstance(o, type(self))


def implements(obj, name: str) -> bool:
    """True iff `obj`'s class really defines `name` somewhere in its MRO.

    The hasattr()-safe way to ask "does this object support this call?".
    hasattr() cannot answer it on a TGObject: __getattr__ hands back a truthy
    _Stub for any unknown non-underscore name, so hasattr() is vacuously True
    for every engine method on every object (that is how TorpedoTube.UpdateCharge
    reached 4.9M no-op stub hits -- see docs/stub_heatmap.md).
    """
    # A plain loop, not any(... for ...). This is one of the hottest
    # primitives in the engine -- 254,400 calls in a 600-tick AI profile at 17
    # ships, plus 48,600 more from the motion path -- and at that volume the
    # generator expression is not free: it allocated a generator frame per
    # call and drove it through any(), which cProfile attributed as 763,200
    # <genexpr> calls and 254,400 any() calls, together roughly two thirds of
    # this function's total cost. The loop is identical in meaning, including
    # the short-circuit on the first match.
    #
    # ...and the loop itself is now cached per (class, name), because the
    # answer is a property of the CLASS and classes do not gain or lose methods
    # while the game runs. Measured at 100 ships: 2,400 calls/tick, ~36,000 per
    # frame, at only 2.2 MRO steps each -- a lot of calls through a very short
    # loop, which is why the win was worth benchmarking rather than assuming.
    # Micro-benchmarked before wiring it in: 315-430 ns walking vs ~127 ns
    # cached, so ~230 ns x 36,000 = ~8 ms/frame.
    #
    # Two-level (class -> {name: bool}) rather than a single dict keyed on the
    # tuple (class, name): building and hashing that tuple costs real time at
    # this volume, and the two-level form measured ~30 ns/call faster.
    #
    # STALENESS: the only way to invalidate this is to add or remove a method
    # on a class that has already been asked about. Nothing in the engine does
    # that -- ai_optimized builds NEW classes with type(), which get their own
    # entries -- but a test that monkey-patches a class would need
    # clear_implements_cache(). It is exported for exactly that.
    cls = type(obj)
    names = _IMPLEMENTS_CACHE.get(cls)
    if names is None:
        names = _IMPLEMENTS_CACHE[cls] = {}
    else:
        hit = names.get(name)
        if hit is not None:
            return hit
    hit = False
    for klass in cls.__mro__:
        if name in klass.__dict__:
            hit = True
            break
    names[name] = hit
    return hit


# class -> {method name -> bool}. See implements() for the staleness argument.
_IMPLEMENTS_CACHE: dict = {}


def clear_implements_cache() -> None:
    """Drop the implements() cache.

    Needed only if a class gains or loses a method after something has already
    asked implements() about it -- i.e. monkey-patching in a test. Production
    code never mutates a class in place, so this is not on any hot path.
    """
    _IMPLEMENTS_CACHE.clear()


class TGObject:
    def __init__(self):
        self._obj_id = next(_counter)
        _registry[self._obj_id] = self

    def GetObjID(self) -> int:
        return self._obj_id

    def __getattr__(self, name: str) -> _Stub:
        # A single-underscore name is never engine surface: zero of the 36,538
        # method rows in tools/probes/results/q13b_method_surface.txt (the live
        # dump of the real BC engine) start with one. So every `_foo` here is
        # one of OUR OWN Python internals, and handing back a truthy _Stub for
        # it made hasattr() vacuously true and getattr(obj, name, default)
        # never reach its default -- e.g. ship_motion's _drift_velocity
        # snapshot. Raise, as a normal Python object would.
        if name.startswith("_") and not (name.startswith("__") and name.endswith("__")):
            raise AttributeError(name)
        if stub_telemetry.ENABLED and not (name.startswith("__") and name.endswith("__")):
            stub_telemetry.record_attr(type(self).__name__, name)
        return _Stub(name, type(self).__name__)
