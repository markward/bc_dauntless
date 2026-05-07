from engine.appc.events import TGEventHandlerObject


class SetClass(TGEventHandlerObject):
    def __init__(self):
        super().__init__()
        self._name: str = ""
        self._objects: dict[str, object] = {}

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


def SetClass_Create() -> SetClass:
    return SetClass()
