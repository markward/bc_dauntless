"""
Action and sequence system for Phase 1 headless engine.

Phase 1 execution model: all actions complete synchronously when Play() is
called. Sequence dependencies and delays are recorded but not enforced — every
action in a sequence plays immediately in insertion order.  This is correct for
validating mission logic flow without needing a real-time event loop.
"""
import sys
from engine.appc.events import TGEventHandlerObject, TGEvent
from engine.core.ids import get_object_by_id


class TGAction(TGEventHandlerObject):
    def __init__(self):
        super().__init__()
        self._completed_events: list[TGEvent] = []
        self._playing: bool = False

    def IsPlaying(self) -> bool:
        return self._playing

    def AddCompletedEvent(self, event: TGEvent) -> None:
        self._completed_events.append(event)

    def Completed(self) -> None:
        self._playing = False
        import App
        events = list(self._completed_events)
        self._completed_events.clear()
        for ev in events:
            App.g_kEventManager.AddEvent(ev)

    def Play(self) -> None:
        self._playing = True
        self._do_play()
        self.Completed()

    def _do_play(self) -> None:
        pass

    def Abort(self) -> None:
        self._playing = False

    def Skip(self) -> None:
        self.Completed()

    def GetSequence(self) -> "TGSequence | None":
        return None

    def IsPartOfSequence(self) -> bool:
        return False

    def SetSkippable(self, skippable: bool) -> None:
        pass

    def IsSkippable(self) -> bool:
        return True

    def SetUseRealTime(self, use_real_time: bool) -> None:
        pass

    def IsUseRealTime(self) -> bool:
        return False

    def SetSurviveGlobalAbort(self, survive: bool) -> None:
        pass

    def IsGlobalAbortSurvivor(self) -> bool:
        return False

    def Restart(self) -> None:
        self.Play()


class TGNullAction(TGAction):
    pass


def TGAction_CreateNull() -> TGNullAction:
    return TGNullAction()


def TGAction_Cast(obj) -> "TGAction | None":
    if isinstance(obj, TGAction):
        return obj
    return None


# Track call depth per (module, func) to prevent infinite recursion when a
# delayed sequence action re-enters the same function synchronously in Phase 1.
_script_action_depth: dict[tuple[str, str], int] = {}
_SCRIPT_ACTION_MAX_DEPTH = 2


class TGScriptAction(TGAction):
    def __init__(self, module_name: str, func_name: str, *args):
        super().__init__()
        self._module_name = module_name
        self._func_name = func_name
        self._args = args

    def _do_play(self) -> None:
        key = (self._module_name, self._func_name)
        if _script_action_depth.get(key, 0) >= _SCRIPT_ACTION_MAX_DEPTH:
            return
        _script_action_depth[key] = _script_action_depth.get(key, 0) + 1
        try:
            mod = sys.modules.get(self._module_name)
            if mod is None:
                try:
                    import importlib
                    mod = importlib.import_module(self._module_name)
                except (ImportError, ModuleNotFoundError):
                    return
            fn = getattr(mod, self._func_name, None)
            if fn is not None:
                fn(self, *self._args)
        finally:
            _script_action_depth[key] -= 1


def TGScriptAction_Create(module_name: str, func_name: str, *args) -> TGScriptAction:
    return TGScriptAction(module_name, func_name, *args)


class TGSequence(TGAction):
    def __init__(self):
        super().__init__()
        self._actions: list[TGAction] = []

    def AddAction(self, action: TGAction, *extra) -> None:
        """Add action to the sequence. Dependency/delay args (extra) ignored in Phase 1."""
        self._actions.append(action)

    def AppendAction(self, action: TGAction, *extra) -> None:
        self._actions.append(action)

    def GetNumActions(self) -> int:
        return len(self._actions)

    def GetAction(self, index: int) -> "TGAction | None":
        if 0 <= index < len(self._actions):
            return self._actions[index]
        return None

    def _do_play(self) -> None:
        for action in list(self._actions):
            action.Play()


def TGSequence_Create() -> TGSequence:
    return TGSequence()


class TGTimedAction(TGAction):
    def __init__(self):
        super().__init__()
        self._duration: float = 0.0

    def SetDuration(self, duration: float) -> None:
        self._duration = duration

    def GetDuration(self) -> float:
        return self._duration


class TGSoundAction(TGTimedAction):
    def __init__(self, sound_name: str = ""):
        super().__init__()
        self._sound_name = sound_name


def TGSoundAction_Create(*args) -> TGSoundAction:
    """Accept (sound_name,) or (sound_name, flags, ...) — extra args are renderer hints ignored in Phase 1."""
    sound_name = args[0] if args and isinstance(args[0], str) else ""
    return TGSoundAction(sound_name)


class TGAnimAction(TGAction):
    pass


def TGAnimAction_Create(*args) -> TGAnimAction:
    return TGAnimAction()


class SubtitleAction(TGTimedAction):
    def __init__(self, database=None, string_id: str = ""):
        super().__init__()
        self._database = database
        self._string_id = string_id

    def GetObjID(self) -> int:
        return super().GetObjID()


def SubtitleAction_Create(database=None, string_id: str = "") -> SubtitleAction:
    return SubtitleAction(database, string_id)


class TGActionManager(TGEventHandlerObject):
    pass


class TGObjPtrEvent(TGEvent):
    def __init__(self):
        super().__init__()
        self._obj_ptr = None

    def SetObjPtr(self, obj) -> None:
        self._obj_ptr = obj

    def GetObjPtr(self):
        return self._obj_ptr


def TGObjPtrEvent_Create() -> TGObjPtrEvent:
    return TGObjPtrEvent()


def TGObject_GetTGObjectPtr(obj_id: int):
    """Look up a TGObject by its integer ID."""
    return get_object_by_id(obj_id)
