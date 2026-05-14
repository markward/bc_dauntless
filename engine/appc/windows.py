"""TacticalControlWindow placeholder.

Real BC TCW is a full window with menus / layout / focus.  PR 2a only
needs the event-handler-object surface so TacticalInterfaceHandlers.
RegisterHandlers(pTCW) can install fire-event handlers on it.  Future
PRs will replace this with the real window when the menu system lands.
"""
from engine.appc.events import TGEventHandlerObject


class TacticalControlWindow(TGEventHandlerObject):
    _instance: "TacticalControlWindow | None" = None

    @classmethod
    def GetInstance(cls) -> "TacticalControlWindow":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def CallNextHandler(self, _evt) -> None:
        """SDK handlers call pObject.CallNextHandler(pEvent) for chain
        propagation.  Without a parent window chain we no-op."""
        return None
