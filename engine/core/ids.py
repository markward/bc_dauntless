import itertools

_counter = itertools.count(1)
_registry: dict[int, "TGObject"] = {}


def get_object_by_id(obj_id: int) -> "TGObject | None":
    return _registry.get(obj_id)


class _Stub:
    """Recursive stub: attribute access and calls return another _Stub.

    Returned by TGObject.__getattr__ for unimplemented engine methods so SDK
    scripts can chain calls like pMission.GetFriendlyGroup().AddName(...).
    """
    def __getattr__(self, name: str) -> "_Stub":
        return _Stub()

    def __call__(self, *args, **kwargs) -> "_Stub":
        return _Stub()

    def __bool__(self) -> bool:
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


class TGObject:
    def __init__(self):
        self._obj_id = next(_counter)
        _registry[self._obj_id] = self

    def GetObjID(self) -> int:
        return self._obj_id

    def __getattr__(self, name: str) -> _Stub:
        return _Stub()
