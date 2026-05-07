"""
Placement objects for Phase 1 headless engine.

PlacementObject — an ObjectClass with static/nav-point flags (parent of Waypoint)
Waypoint        — named position/orientation marker used by PlaceObjectByName
Waypoint_Create — factory that registers the waypoint in the global name registry

PlaceObjectByName resolves names through _waypoint_registry, a module-level dict
keyed by the waypoint identifier string.  All waypoints created via Waypoint_Create
are automatically registered here.
"""

from engine.appc.objects import ObjectClass


_waypoint_registry: dict[str, "Waypoint"] = {}


class PlacementObject(ObjectClass):
    def __init__(self):
        super().__init__()
        self._is_static: bool = False
        self._is_nav_point: bool = False

    def SetStatic(self, static) -> None:
        self._is_static = bool(static)

    def IsStatic(self) -> bool:
        return self._is_static

    def SetNavPoint(self, nav) -> None:
        self._is_nav_point = bool(nav)

    def IsNavPoint(self) -> bool:
        return self._is_nav_point

    def FindContainingSet(self):
        return self._containing_set

    def SetModel(self, *args) -> None:
        pass

    def GetModelName(self) -> str:
        return ""

    def SaveObject(self, *args) -> None:
        pass

    def SaveObjectSecondPass(self, *args) -> None:
        pass


class Waypoint(PlacementObject):
    def __init__(self):
        super().__init__()
        self._speed: float = 0.0
        self._next: "Waypoint | None" = None
        self._prev: "Waypoint | None" = None

    def SetSpeed(self, speed: float) -> None:
        self._speed = float(speed)

    def GetSpeed(self) -> float:
        return self._speed

    def GetNext(self) -> "Waypoint | None":
        return self._next

    def GetPrev(self) -> "Waypoint | None":
        return self._prev

    def InsertAfterObj(self, other: "Waypoint") -> None:
        pass


def Waypoint_Create(name: str, set_name: str, parent=None) -> Waypoint:
    """Create and register a waypoint.  Mirrors App.Waypoint_Create(name, set, parent)."""
    wp = Waypoint()
    wp.SetName(name)
    _waypoint_registry[name] = wp

    # Also add to the named set if it exists.
    import App
    s = App.g_kSetManager.GetSet(set_name)
    if s is not None:
        s.AddObjectToSet(wp, name)

    return wp
