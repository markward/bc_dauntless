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


def TGSequence_Cast(obj) -> "TGSequence | None":
    """SDK pattern: ``App.TGSequence_Cast(pAction)`` to test+cast.  Returns
    obj if it's a TGSequence, else None.  Used in MissionLib for sequence
    flattening — checking whether an inner action is itself a sub-sequence."""
    return obj if isinstance(obj, TGSequence) else None


class TGTimedAction(TGAction):
    def __init__(self):
        super().__init__()
        self._duration: float = 0.0

    def SetDuration(self, duration: float) -> None:
        self._duration = duration

    def GetDuration(self) -> float:
        return self._duration


class TGSoundAction(TGTimedAction):
    def __init__(self, sound_name: str = "") -> None:
        super().__init__()
        self._sound_name = sound_name

    def SetName(self, name: str) -> None:
        self._sound_name = name

    def GetName(self) -> str:
        return self._sound_name

    def Play(self) -> None:
        # Late import: tg_sound pulls in the native audio extension; keep this
        # module light at startup since actions is loaded very early via App.py.
        from engine.audio.tg_sound import TGSoundManager
        TGSoundManager.instance().PlaySound(self._sound_name)


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
    """Named-action registry.

    SDK call sites (MissionLib.py:3972, 4015, 4102, 4107) register actions
    under a string name so they can be re-fetched and cancelled later — the
    "FriendlyFireWarning" and "FriendlyFireGameOver" patterns post deferred
    actions and cancel any prior pending one before posting a new one.
    """
    def __init__(self):
        super().__init__()
        self._registered: dict = {}  # name -> action (most-recent under each key)

    def RegisterAction(self, action, name: str) -> None:
        self._registered[str(name)] = action

    def UnregisterAction(self, name: str) -> None:
        self._registered.pop(str(name), None)

    def FindAction(self, name: str):
        return self._registered.get(str(name))

    def IsRegistered(self, name: str) -> int:
        return 1 if str(name) in self._registered else 0


def TGActionManager_RegisterAction(action, name: str) -> None:
    """Module-level convenience wrapper used by SDK MissionLib.

    Routes to the global g_kTGActionManager singleton in App.py.  Late-bind
    via importlib so this module doesn't depend on App at load time.
    """
    import App
    App.g_kTGActionManager.RegisterAction(action, name)


def TGActionManager_UnregisterAction(name: str) -> None:
    import App
    App.g_kTGActionManager.UnregisterAction(name)


def TGActionManager_FindAction(name: str):
    import App
    return App.g_kTGActionManager.FindAction(name)


# ── TGCreditAction ──────────────────────────────────────────────────────────
# Credit-roll text overlay used by mission-summary screens (MissionLib.py:5416)
# and the friendly-fire / game-over banners.  Phase 1 stores the text+layout
# args; rendering is Phase 2.

class TGCreditAction(TGTimedAction):
    JUSTIFY_LEFT   = 0
    JUSTIFY_RIGHT  = 1
    JUSTIFY_TOP    = 2
    JUSTIFY_BOTTOM = 3
    JUSTIFY_CENTER = 4

    def __init__(self, *args):
        super().__init__()
        # SDK constructor is variadic — common forms:
        #   (text, subtitle_window, x, y, time, fade_in, fade_out, font_size)
        #   (text, subtitle_window) — for short banners
        # Stash everything for round-trip + Phase 2 rendering.
        self._args = args
        self._text = args[0] if args else ""
        self._subtitle = args[1] if len(args) > 1 else None
        self._color = _credit_default_color  # tuple (r, g, b, a)

    def SetColor(self, r: float, g: float, b: float, a: float = 1.0) -> None:
        self._color = (float(r), float(g), float(b), float(a))


def TGCreditAction_Create(*args) -> TGCreditAction:
    return TGCreditAction(*args)


# Module-level default color set via TGCreditAction_SetDefaultColor.
# Banners created without an explicit SetColor inherit this — matches Appc
# behaviour where SetDefaultColor pokes a process-global.
_credit_default_color: tuple = (1.0, 1.0, 1.0, 1.0)


def TGCreditAction_SetDefaultColor(r, g, b, a=1.0) -> None:
    global _credit_default_color
    _credit_default_color = (float(r), float(g), float(b), float(a))


def TGCreditAction_GetDefaultColor() -> tuple:
    return _credit_default_color


# ── TGConditionAction ───────────────────────────────────────────────────────
# Action that completes when its conditions transition.  Mission scripts use
# it as a sequence-step gate — `pSequence.AppendAction(pConditionAction)` then
# `pSequence.AddAction(pNextAction, pConditionAction)` makes pNextAction wait
# for the condition to flip before it plays.

class TGConditionAction(TGAction):
    TGCA_WAIT      = 0   # action is pending — sequence stalls here
    TGCA_COMPLETED = 1   # condition fired — sequence advances

    def __init__(self):
        super().__init__()
        self._conditions: list = []
        self._state = self.TGCA_WAIT

    def AddCondition(self, condition) -> None:
        self._conditions.append(condition)
        # Subscribe so ConditionChanged is invoked when the underlying
        # TGCondition transitions; the AI ConditionScript and ConditionInRange
        # primitives both push their handler pattern through TGCondition.AddHandler.
        if hasattr(condition, "AddHandler"):
            condition.AddHandler(self)

    def GetConditions(self) -> list:
        return list(self._conditions)

    def ConditionChanged(self, cond) -> None:
        # Any condition flipping moves us to COMPLETED + invokes the
        # TGAction Completed() flow so dependent actions run.
        self._state = self.TGCA_COMPLETED
        self.Completed()

    def GetState(self) -> int:
        return self._state

    def _do_play(self) -> None:
        # Phase 1: synchronously evaluate conditions; if any has truthy
        # status already, complete immediately.  Otherwise the wait is
        # pending until ConditionChanged fires (Phase 2 simulation loop).
        for cond in self._conditions:
            if hasattr(cond, "GetStatus") and cond.GetStatus():
                self._state = self.TGCA_COMPLETED
                return


def TGConditionAction_Create() -> TGConditionAction:
    return TGConditionAction()


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
