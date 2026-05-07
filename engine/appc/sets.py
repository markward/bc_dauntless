from engine.appc.events import TGEventHandlerObject


class _RendererStub:
    """Returned by SetClass for renderer-only methods not needed in Phase 1.

    Chainable: pSet.GetLight("x").AddIlluminatedObject(y) succeeds silently.
    Truthy: SDK guards like `if pCamera:` don't short-circuit.
    """
    def __getattr__(self, name: str):
        return self
    def __call__(self, *args, **kwargs):
        return _RendererStub()
    def __bool__(self):
        return True
    def __repr__(self):
        return "<_RendererStub>"


class SetClass(TGEventHandlerObject):
    def __init__(self):
        super().__init__()
        self._name: str = ""
        self._objects: dict[str, object] = {}

    def __getattr__(self, name: str):
        """Return a chainable stub for renderer-specific methods not needed in Phase 1
        (CreateAmbientLight, SetBackgroundModel, AddCameraToSet, GetLight, etc.)."""
        if name.startswith("_"):
            raise AttributeError(name)
        return lambda *args, **kwargs: _RendererStub()

    def GetName(self) -> str:
        return self._name

    def SetName(self, name: str) -> None:
        self._name = name

    def SetRegionModule(self, module_name: str) -> None:
        pass

    def SetProximityManagerActive(self, active: int) -> None:
        pass

    def AddObjectToSet(self, obj, identifier: str) -> bool:
        if hasattr(obj, "SetName"):
            obj.SetName(identifier)
        if hasattr(obj, "_containing_set"):
            obj._containing_set = self
        self._objects[identifier] = obj
        return True

    def GetObject(self, name: str):
        return self._objects.get(name)

    def RemoveObjectFromSet(self, name: str):
        return self._objects.pop(name, None)

    def DeleteObjectFromSet(self, name: str) -> None:
        self._objects.pop(name, None)

    def IsLocationEmptyTG(self, point, radius: float, flag: int = 1) -> int:
        """Phase 1 stub — always reports the location as empty."""
        return 1


class SetManager:
    def __init__(self):
        self._sets: dict[str, SetClass] = {}

    def AddSet(self, pSet: SetClass, name: str) -> None:
        pSet.SetName(name)
        self._sets[name] = pSet

    def GetSet(self, name: str) -> "SetClass | None":
        return self._sets.get(name)

    def RemoveSet(self, name: str) -> None:
        self._sets.pop(name, None)

    def DeleteSet(self, name: str) -> None:
        self._sets.pop(name, None)

    def DeleteAllSets(self) -> None:
        self._sets.clear()

    def GetNumSets(self) -> int:
        return len(self._sets)

    def GetRenderedSet(self) -> "SetClass | None":
        return None


class _NullSet(SetClass):
    """Searches all registered sets when GetObject is called.

    Mirrors the real engine's SetClass_GetNull() behaviour — the null set
    is a global search handle, not a real set with objects in it.
    """
    def GetObject(self, name: str):
        from engine.appc.sets import _get_set_manager
        sm = _get_set_manager()
        if sm is None:
            return None
        for pSet in sm._sets.values():
            obj = pSet._objects.get(name)
            if obj is not None:
                return obj
        return None


def _get_set_manager():
    """Late-binding accessor so sets.py doesn't import App at module load time."""
    try:
        import App
        return App.g_kSetManager
    except ImportError:
        return None


_null_set = _NullSet()


def SetClass_GetNull() -> "_NullSet":
    return _null_set


def SetClass_Create() -> SetClass:
    return SetClass()
