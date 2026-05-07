from engine.appc.events import TGEventHandlerObject


class ObjectClass(TGEventHandlerObject):
    def __init__(self):
        super().__init__()
        self._name: str = ""
        self._script: str = ""

    def GetName(self) -> str:
        return self._name

    def SetName(self, name: str) -> None:
        self._name = name

    def GetScript(self) -> str:
        return self._script

    def SetScript(self, script: str) -> None:
        self._script = script

    def GetRadius(self) -> float:
        return 0.0

    def PlaceObjectByName(self, name: str) -> None:
        pass

    def UpdateNodeOnly(self) -> None:
        pass


class PhysicsObjectClass(ObjectClass):
    pass


class DamageableObject(PhysicsObjectClass):
    pass


class ObjectGroup(TGEventHandlerObject):
    GROUP_CHANGED = 1
    ENTERED_SET = 2
    EXITED_SET = 3
    DESTROYED = 4

    def __init__(self):
        super().__init__()
        self._names: list[str] = []

    def AddName(self, name: str) -> None:
        if name not in self._names:
            self._names.append(name)

    def RemoveName(self, name: str) -> None:
        if name in self._names:
            self._names.remove(name)

    def RemoveAllNames(self) -> None:
        self._names.clear()

    def IsNameInGroup(self, name: str) -> bool:
        return name in self._names

    def GetNumActiveObjects(self) -> int:
        return len(self._names)
