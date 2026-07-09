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

    def InsertAfterObj(self, other: "Waypoint | None") -> None:
        """Splice ``other`` into the waypoint chain immediately after ``self``,
        i.e. after the call ``self.GetNext() is other``.

        This is the SDK convention (ground truth): ``self.InsertAfterObj(other)``
        attaches ``other`` after ``self``. See
        AI/Compound/DockWithStarbase.py:296-299, which calls
        ``pWaypointStart.InsertAfterObj(pWaypointEnd)`` and then guards on
        ``pWaypointStart.GetNext() == pWaypointEnd``; the auto-generated
        ``*_Placements.py`` cutscene chains use the same convention
        ("Attaching object <arg> after <self>").

        Doubly-linked list mutation. If ``other`` is None (or is ``self``),
        this is a no-op — ``self``'s own chain is left untouched. Otherwise
        ``other`` is first detached from whatever chain it's currently part
        of, then spliced in directly after ``self``.
        """
        if other is None or other is self:
            return

        # Detach `other` from any current chain to avoid corrupted links if
        # the caller is re-arranging existing nodes.
        if other._prev is not None:
            other._prev._next = other._next
        if other._next is not None:
            other._next._prev = other._prev

        # Splice `other` immediately after `self`.
        other._prev = self
        other._next = self._next
        if self._next is not None:
            self._next._prev = other
        self._next = other


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


def PlacementObject_Create(name: str, set_name: str, parent=None) -> PlacementObject:
    """Create a generic PlacementObject and register it in the named set.

    Mirrors ``App.PlacementObject_Create(name, set_name, parent)``.  SDK callers
    (WarpSequence.py, Maelstrom placement scripts) build placement nodes that
    aren't full waypoints — they have position + orientation but no
    next/prev chain.  Same global-registry behaviour as Waypoint_Create so
    PlaceObjectByName lookups find them.
    """
    p = PlacementObject()
    p.SetName(name)
    _waypoint_registry[name] = p

    import App
    s = App.g_kSetManager.GetSet(set_name)
    if s is not None:
        s.AddObjectToSet(p, name)

    return p


def Waypoint_Cast(obj) -> "Waypoint | None":
    """Return ``obj`` if it's a Waypoint, else None.  Mirrors Appc.Waypoint_Cast."""
    return obj if isinstance(obj, Waypoint) else None


def PlacementObject_Cast(obj) -> "PlacementObject | None":
    return obj if isinstance(obj, PlacementObject) else None


def PlacementObject_GetObjectBySetName(set_name: str, placement_name: str):
    """Look up a placement by name within the named set.

    Mirrors sdk/.../App.py:PlacementObject_GetObjectBySetName.  E7M2 placement
    scripts use this together with Waypoint_Cast to walk per-set cutscene
    waypoint chains.  Returns None if the set doesn't exist or the placement
    isn't in it.  Falls back to the global waypoint registry when the set
    isn't found, since a few mission scripts run waypoint setup before the
    target set has been added to the SetManager.
    """
    import App
    s = App.g_kSetManager.GetSet(set_name)
    if s is not None:
        obj = s.GetObject(placement_name)
        if obj is not None:
            return obj
    return _waypoint_registry.get(placement_name)


def PlacementObject_GetObject(pSet, name: str):
    """Look up a placement by name within a SetClass.

    SDK signature: ``App.PlacementObject_GetObject(pSet, name)``.  Used by
    MissionLib for nav-point/initial-waypoint lookups, by Camera.py for
    object-of-interest tracking, by WarpSequence.py for warp endpoints.
    Returns None if the placement isn't in the set.  Falls back to the
    global waypoint registry as a safety net.
    """
    if pSet is not None and hasattr(pSet, "GetObject"):
        obj = pSet.GetObject(name)
        if obj is not None:
            return obj
    return _waypoint_registry.get(name)
