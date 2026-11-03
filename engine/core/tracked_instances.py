"""A dict that counts its own mutations.

`session.ship_instances` (ship -> render InstanceId) is read by the native
beam kernel as a table it is handed once and re-sent only when it changed;
`version` is that "changed" signal. It is a real ``dict`` in every other way
(``isinstance(x, dict)``, ``dict(x)``, ``json``-style readers all work), so
every existing reader of the map is unaffected.

The version moves on every path that can change the mapping -- including an
overwrite with an equal value, because a renderer instance id is a handle:
the same number is not the same instance. A call that provably changes
nothing (``pop`` of a missing key with a default, ``setdefault`` of a present
key, ``clear`` of an empty dict) does not bump it.
"""

_MISSING = object()


class TrackedInstances(dict):
    # Unpickling (and copy / deepcopy) fills the dict through __setitem__
    # BEFORE it restores the instance __dict__: the bumps start from this,
    # then the pickled version replaces them. Either way an int.
    version = 0

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.version = 0

    def __setitem__(self, key, value) -> None:
        super().__setitem__(key, value)
        self.version += 1

    def __delitem__(self, key) -> None:
        super().__delitem__(key)
        self.version += 1

    def pop(self, key, default=_MISSING):
        if key in self:
            self.version += 1
            return super().pop(key)
        if default is _MISSING:
            raise KeyError(key)
        return default

    def popitem(self):
        item = super().popitem()
        self.version += 1
        return item

    def clear(self) -> None:
        if self:
            self.version += 1
        super().clear()

    def update(self, *args, **kwargs) -> None:
        super().update(*args, **kwargs)
        self.version += 1

    def setdefault(self, key, default=None):
        if key in self:
            return self[key]
        super().__setitem__(key, default)
        self.version += 1
        return default

    def __ior__(self, other):
        super().update(other)
        self.version += 1
        return self
