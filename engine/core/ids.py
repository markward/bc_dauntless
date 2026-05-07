import itertools

_counter = itertools.count(1)
_registry: dict[int, "TGObject"] = {}


def get_object_by_id(obj_id: int) -> "TGObject | None":
    return _registry.get(obj_id)


class TGObject:
    def __init__(self):
        self._obj_id = next(_counter)
        _registry[self._obj_id] = self

    def GetObjID(self) -> int:
        return self._obj_id
