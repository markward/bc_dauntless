"""ArtificialIntelligence hierarchy + AI primitive factories.

Mirrors sdk/Build/scripts/App.py:4922-5240 — the AI primitives that mission
scripts wire together to create per-ship behaviour graphs.

Phase 1 model: AI primitives are *data containers* with the right method
surface and observable state.  They don't actually drive ship motion or
decision-making — that lives in Phase 2's AI executor.  But:

* SDK call sites round-trip values through the setters (mission scripts
  often read back AI state to gate other branches).
* Conditions notify their handlers when status changes — this powers
  ConditionalAI gating + ConditionEventCreator's event firing, which IS
  exercised during mission init.
* PlainAI's GetScriptInstance() must accept arbitrary Set*/Get* calls
  because each PlainAI script (CircleObject, Flee, FollowObject, ...)
  defines its own setter surface.

Class hierarchy (mirrors SDK):

    ArtificialIntelligence
    ├── PlainAI                         (script-driven leaf AI)
    ├── PriorityListAI                  (multiple AIs ordered by priority)
    ├── SequenceAI                      (ordered sequence of AIs)
    └── PreprocessingAI                 (wraps a contained AI with preprocessing)
        └── BuilderAI                   (constructs other AI graphs lazily)

    TGCondition
    └── ConditionScript                 (Python-script-backed condition)

    ConditionEventCreator               (handler that emits events on change)

    ProximityCheck                      (radius proximity trigger; ObjectClass)
    CharacterAction                     (TGAction subclass for crew animations)
"""

from engine.appc.objects import ObjectClass
from engine.appc.actions import TGAction


# ── Condition system ──────────────────────────────────────────────────────────

class TGCondition:
    """Status-bearing object that fires handlers when status changes.

    SDK callers (ConditionalAI, ConditionEventCreator, DynamicMusic) wire
    a TGCondition to one or more handlers via AddHandler; when SetStatus
    flips the value, every handler's ConditionChanged is invoked.  The
    SDK uses int status (typically 0/1) but the comparison is value-based.
    """
    def __init__(self):
        self._status: int = 0
        self._handlers: list = []
        self._active: bool = False

    def GetStatus(self) -> int:
        return self._status

    def SetStatus(self, status) -> None:
        new_status = int(status)
        changed = (new_status != self._status)
        self._status = new_status
        if changed and self._active:
            for h in list(self._handlers):
                h.ConditionChanged(self)

    def AddHandler(self, handler) -> None:
        if handler not in self._handlers:
            self._handlers.append(handler)

    def RemoveHandler(self, handler) -> None:
        if handler in self._handlers:
            self._handlers.remove(handler)

    def SetActive(self, *args) -> None:
        # SDK signature: SetActive() with no args toggles to active.
        self._active = True

    def SetInactive(self, *args) -> None:
        self._active = False

    def IsActive(self) -> int:
        return 1 if self._active else 0


class TGConditionHandler:
    """Mixin for objects that subscribe to TGCondition status changes."""
    def ConditionChanged(self, cond: TGCondition) -> None:
        pass


class ConditionScript(TGCondition):
    """Python-script-backed condition (sdk/.../Conditions/*).

    SDK pattern: ``ConditionScript_Create("Conditions.ConditionInRange",
    "ConditionInRange", *args)`` loads the named module, instantiates the
    named class with ``*args``, and uses the resulting object's evaluate
    method to drive SetStatus.  Phase 1 stores the spec for reflection but
    doesn't drive evaluation — mission scripts wire conditions during init,
    they're evaluated against ship state in the Phase 2 simulation loop.
    """
    def __init__(self, module_name: str = "", class_name: str = "", *args):
        super().__init__()
        self._module_name = module_name
        self._class_name = class_name
        self._args = args
        self._instance = None

    def GetModuleName(self) -> str:
        return self._module_name

    def GetClassName(self) -> str:
        return self._class_name

    def GetArguments(self) -> tuple:
        return self._args


def ConditionScript_Create(module_name: str, class_name: str, *args) -> ConditionScript:
    return ConditionScript(module_name, class_name, *args)


def ConditionScript_Cast(obj):
    return obj if isinstance(obj, ConditionScript) else None


# ── AI script-instance data bag ───────────────────────────────────────────────

class _AIScriptInstance:
    """Returned by PlainAI.GetScriptInstance / PreprocessingAI.GetPreprocessingInstance.

    Each PlainAI script (sdk/.../AI/PlainAI/CircleObject.py, Flee.py,
    FollowObject.py, ...) defines a different class with its own setters
    (SetCircleSpeed, SetFleeFromGroup, SetFollowObjectName, SetTargets,
    etc.).  The SDK pattern is:

        pAI = App.PlainAI_Create(pShip, "ChaseEnemy")
        pAI.SetScriptModule("FollowObject")
        pScript = pAI.GetScriptInstance()
        pScript.SetFollowObjectName("Enterprise")

    Headless Phase 1 doesn't load the scripts (each wraps Appc-only state),
    so GetScriptInstance returns this data-bag.  Set*/Get* round-trip through
    a dict; everything else absorbs as a no-op.
    """
    def __init__(self, ai):
        self._ai = ai
        self._data: dict = {}

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        data = self._data
        if name.startswith("Set"):
            field = name[3:]
            def setter(*args, **kwargs):
                # Mission scripts occasionally pass kwargs (e.g.
                # `Difficulty = 0.7` flowed through wrappers) — preserve the
                # full call so introspection captures everything.
                if kwargs:
                    data[field] = (args, kwargs)
                else:
                    data[field] = args[0] if len(args) == 1 else args
            return setter
        if name.startswith("Get"):
            field = name[3:]
            return lambda *args, **kwargs: data.get(field)
        if name.startswith("Is"):
            field = name[2:]
            return lambda *args, **kwargs: bool(data.get(field))
        # Methods like WarpBlindly, PrepareToWarp, etc. — recorded as no-op calls.
        return lambda *args, **kwargs: None


# ── ArtificialIntelligence ────────────────────────────────────────────────────

class ArtificialIntelligence:
    US_ACTIVE = 0
    US_DONE = 1
    US_DORMANT = 2
    US_INVALID = 3
    US_NUM_STATUSES = 4

    _next_id = 1

    def __init__(self, pShip=None, name: str = ""):
        self._ship = pShip
        self._name = name
        self._interruptable = True
        self._paused = False
        self._has_focus = False
        self._status = self.US_ACTIVE
        type(self)._allocate_id(self)

    @classmethod
    def _allocate_id(cls, ai) -> None:
        ai._id = ArtificialIntelligence._next_id
        ArtificialIntelligence._next_id += 1

    # ── Identity ─────────────────────────────────────────────────────────────
    def GetID(self) -> int:               return self._id
    def GetName(self) -> str:             return self._name
    def GetShip(self):                    return self._ship
    def GetObject(self):                  return self._ship   # SDK alias

    # ── Status ───────────────────────────────────────────────────────────────
    def IsActive(self) -> int:            return 1 if self._status == self.US_ACTIVE else 0
    def HasFocus(self) -> int:            return 1 if self._has_focus else 0
    def Pause(self) -> None:              self._paused = True
    def Unpause(self) -> None:            self._paused = False
    def IsPaused(self) -> int:            return 1 if self._paused else 0
    def Reset(self) -> None:              self._status = self.US_ACTIVE
    def SetInterruptable(self, v) -> None: self._interruptable = bool(v)
    def IsInterruptable(self) -> int:     return 1 if self._interruptable else 0


# ── PlainAI ──────────────────────────────────────────────────────────────────

class PlainAI(ArtificialIntelligence):
    def __init__(self, pShip=None, name: str = ""):
        super().__init__(pShip, name)
        self._script_module: str = ""
        self._script_instance = None
        self._external_functions: dict = {}
        # Driver bookkeeping — first Update fires when game_time >= 0.0,
        # i.e. on the very first AI tick. Updated by ai_driver after each
        # Update() call using the script's GetNextUpdateTime().
        self._next_update_time: float = 0.0

    def SetScriptModule(self, module_name: str) -> None:
        """Import AI.PlainAI.<module_name> and instantiate <module_name>(pCodeAI=self).

        SDK pattern (BaseAI.py:14): the loaded class's __init__ takes pCodeAI
        as a positional arg and stores it on self. The script reaches back
        through self.pCodeAI.GetShip() for all motion + weapon calls.

        Falls back to the _AIScriptInstance data-bag if the module can't be
        imported or doesn't define the expected class — keeps Phase-1 mission
        init working for scripts we haven't validated yet.
        """
        self._script_module = module_name
        try:
            mod = __import__("AI.PlainAI." + module_name, None, None, [module_name])
            cls = getattr(mod, module_name, None)
            if cls is not None:
                self._script_instance = cls(self)
                return
        except (ImportError, AttributeError):
            pass
        # Fallback: data-bag for unimplemented scripts.
        self._script_instance = _AIScriptInstance(self)

    def GetScriptModule(self) -> str:
        return self._script_module

    def GetScriptInstance(self):
        if self._script_instance is None:
            self._script_instance = _AIScriptInstance(self)
        return self._script_instance

    def RegisterExternalFunction(self, name: str, mapping) -> None:
        """Record an externally-registered function name -> info dict.

        Called by BaseAI.SetExternalFunctions (sdk/.../AI/PlainAI/BaseAI.py:54)
        and by various Conditions/Preprocessors that want to expose a method
        to the AI driver. The mapping is opaque metadata — we store it
        verbatim so future reflection (target selection, weapon firing) can
        pull values back out.
        """
        self._external_functions[name] = mapping

    def GetExternalFunctions(self) -> dict:
        return dict(self._external_functions)

    def StopCallingActivate(self) -> None:
        pass


def PlainAI_Create(pShip=None, name: str = "") -> PlainAI:
    return PlainAI(pShip, name)


# ── PriorityListAI ───────────────────────────────────────────────────────────

class PriorityListAI(ArtificialIntelligence):
    def __init__(self, pShip=None, name: str = ""):
        super().__init__(pShip, name)
        # Sorted list of (priority, ai) tuples — lowest priority first.
        # Mission code adds AIs at differing priorities; SDK invokes them
        # in priority order during the AI tick.
        self._ais: list = []

    def AddAI(self, ai, priority: int = 0) -> None:
        self._ais.append((int(priority), ai))
        self._ais.sort(key=lambda pair: pair[0])

    def RemoveAI(self, ai) -> None:
        self._ais = [(p, a) for p, a in self._ais if a is not ai]

    def RemoveAIByPriority(self, priority) -> None:
        self._ais = [(p, a) for p, a in self._ais if p != int(priority)]

    def GetAIs(self) -> list:
        return [a for _p, a in self._ais]


def PriorityListAI_Create(pShip=None, name: str = "") -> PriorityListAI:
    return PriorityListAI(pShip, name)


# ── SequenceAI ───────────────────────────────────────────────────────────────

class SequenceAI(ArtificialIntelligence):
    LOOP_INFINITE = -1

    def __init__(self, pShip=None, name: str = ""):
        super().__init__(pShip, name)
        self._ais: list = []
        self._loop_count: int = 1
        self._reset_if_interrupted: bool = False
        self._double_check_all_done: bool = False
        self._skip_dormant: bool = False

    def AddAI(self, ai) -> None:
        self._ais.append(ai)

    def RemoveAI(self, ai) -> None:
        if ai in self._ais:
            self._ais.remove(ai)

    def RemoveAIByIndex(self, index: int) -> None:
        if 0 <= int(index) < len(self._ais):
            self._ais.pop(int(index))

    def GetAI(self, index: int):
        if 0 <= int(index) < len(self._ais):
            return self._ais[int(index)]
        return None

    def SetLoopCount(self, n) -> None:        self._loop_count = int(n)
    def GetLoopCount(self) -> int:            return self._loop_count
    def SetResetIfInterrupted(self, v) -> None: self._reset_if_interrupted = bool(v)
    def SetDoubleCheckAllDone(self, v) -> None: self._double_check_all_done = bool(v)
    def SetSkipDormant(self, v) -> None:      self._skip_dormant = bool(v)


def SequenceAI_Create(pShip=None, name: str = "") -> SequenceAI:
    return SequenceAI(pShip, name)


# ── PreprocessingAI ──────────────────────────────────────────────────────────

class PreprocessingAI(ArtificialIntelligence):
    PS_NORMAL = 0
    PS_SKIP_ACTIVE = 1
    PS_SKIP_DORMANT = 2
    PS_DONE = 3
    PS_INVALID = 4
    PS_NUM_STATUSES = 5
    FDS_NORMAL = 0
    FDS_TRUE = 1
    FDS_FALSE = 2

    def __init__(self, pShip=None, name: str = ""):
        super().__init__(pShip, name)
        self._contained_ai = None
        self._preprocessing_method: str = ""
        self._preprocessing_instance: "_AIScriptInstance | None" = None

    def SetContainedAI(self, ai) -> None:
        self._contained_ai = ai

    def GetContainedAI(self):
        return self._contained_ai

    def SetPreprocessingMethod(self, *args) -> None:
        """Two SDK call signatures:

        * ``SetPreprocessingMethod(method_name)`` — older single-arg form.
        * ``SetPreprocessingMethod(script_instance, method_name)`` — modern
          two-arg form used by E7M2/E7M3 AI builders, where the caller has
          already constructed a Python script object and wants to install
          a specific method as the per-tick update hook.

        We accept both; the script instance (if given) becomes the
        preprocessing instance so subsequent GetPreprocessingInstance
        calls hand back the caller's object.
        """
        if len(args) == 1:
            self._preprocessing_method = args[0]
            self._preprocessing_instance = _AIScriptInstance(self)
        elif len(args) >= 2:
            # (script_instance, method_name) — keep the caller's object so
            # GetPreprocessingInstance returns what they constructed.
            self._preprocessing_instance = args[0]
            self._preprocessing_method = args[1]

    def GetPreprocessingInstance(self):
        if self._preprocessing_instance is None:
            self._preprocessing_instance = _AIScriptInstance(self)
        return self._preprocessing_instance

    def ForceUpdate(self) -> None:                  pass
    def ForceDormantStatus(self, *args) -> None:    pass
    def ForceStatusChange(self, *args) -> None:     pass


def PreprocessingAI_Create(pShip=None, name: str = "") -> PreprocessingAI:
    return PreprocessingAI(pShip, name)


def PreprocessingAI_Cast(obj):
    return obj if isinstance(obj, PreprocessingAI) else None


# ── ConditionalAI ────────────────────────────────────────────────────────────

class ConditionalAI(ArtificialIntelligence, TGConditionHandler):
    def __init__(self, pShip=None, name: str = ""):
        ArtificialIntelligence.__init__(self, pShip, name)
        self._contained_ai = None
        self._evaluation_function = None
        self._conditions: list = []

    def SetContainedAI(self, ai) -> None:
        self._contained_ai = ai

    def GetContainedAI(self):
        return self._contained_ai

    def SetEvaluationFunction(self, fn) -> None:
        self._evaluation_function = fn

    def GetEvaluationFunction(self):
        return self._evaluation_function

    def AddCondition(self, cond: TGCondition) -> None:
        self._conditions.append(cond)
        cond.AddHandler(self)

    def GetConditions(self) -> list:
        return list(self._conditions)


def ConditionalAI_Create(pShip=None, name: str = "") -> ConditionalAI:
    return ConditionalAI(pShip, name)


# ── ConditionEventCreator ────────────────────────────────────────────────────

class ConditionEventCreator(TGConditionHandler):
    """Fires a stored event whenever its conditions transition.

    SDK pattern: build a ConditionEventCreator, AddCondition(...) one or
    more TGCondition objects, SetEvent(...) the event to emit, and the
    ConditionChanged callback fires the event into g_kEventManager when
    the condition status flips.  Phase 1 records the wiring so mission
    scripts get a real handle back; the actual firing requires the AI
    executor + event evaluation that lives in Phase 2.
    """
    def __init__(self):
        self._conditions: list = []
        self._event = None

    def AddCondition(self, cond: TGCondition) -> None:
        self._conditions.append(cond)
        cond.AddHandler(self)

    def GetConditions(self) -> list:
        return list(self._conditions)

    def SetEvent(self, event) -> None:
        self._event = event

    def GetEvent(self):
        return self._event

    def ConditionChanged(self, cond: TGCondition) -> None:
        # Re-fire the stored event to its destination.  Headless: enqueue
        # via the global event manager so handlers wired during mission
        # init see it.  Self-contained — no external dispatcher needed.
        if self._event is None:
            return
        try:
            import App
            App.g_kEventManager.AddEvent(self._event)
        except Exception:
            pass


# ── BuilderAI ────────────────────────────────────────────────────────────────

class BuilderAI(PreprocessingAI):
    """AI that lazily builds other AI graphs based on dependency satisfaction.

    SDK pattern (CallDamageAI.py): mission code calls AddAIBlock(name, ai)
    for each AI in the graph, AddDependencyObject(name, attr, value) to
    declare a dependency on a Python-side object, and AddDependency(name,
    dep_name) to chain block-on-block.  Block becomes activate-eligible
    once all its dependencies are satisfied.

    Phase 1 captures the dependency graph; activation is Phase 2 work.
    """
    def __init__(self, pShip=None, name: str = "", module_name: str = ""):
        super().__init__(pShip, name)
        self._module_name = module_name
        self._blocks: dict = {}                # name -> AI
        self._dependencies: list = []          # (block_name, dep_block_name)
        self._dep_objects: list = []           # (block_name, attr, value)

    def GetModuleName(self) -> str:
        return self._module_name

    def AddAIBlock(self, name: str, ai) -> None:
        self._blocks[name] = ai

    def GetAIBlock(self, name: str):
        return self._blocks.get(name)

    def AddDependency(self, block_name: str, dep_block_name: str) -> None:
        self._dependencies.append((block_name, dep_block_name))

    def AddDependencyObject(self, block_name: str, attr: str, value) -> None:
        self._dep_objects.append((block_name, attr, value))

    def GetDependencies(self) -> list:
        return list(self._dependencies)

    def GetDependencyObjects(self) -> list:
        return list(self._dep_objects)


def BuilderAI_Create(pShip=None, name: str = "", module_name: str = "") -> BuilderAI:
    """SDK signature is ``BuilderAI_Create(pShip, name, module_name)``.

    The third argument is the calling module's ``__name__`` — used to
    resolve block-creation functions at activation time.  Example:
    ``CallDamageAI.py:18`` passes ``__name__`` so the BuilderAI can later
    look up ``BuilderCreate1`` etc. inside that module.
    """
    return BuilderAI(pShip, name, module_name)


# ── ProximityCheck ───────────────────────────────────────────────────────────

class ProximityCheck(ObjectClass):
    """Radius-based trigger that fires an event when watched objects enter.

    SDK pattern (MissionLib.py:200): ``App.ProximityCheck_Create(eEventType)``
    creates the trigger, then ``AddObjectToCheckList(obj)`` etc. populates
    the watch list.  The check is evaluated each AI tick in Phase 2; Phase 1
    captures the configuration so mission init can wire it up.
    """
    # Trigger-type constants from sdk/.../App.py:6140-6141.  Mission scripts
    # tag each watched object as "trigger when inside" or "trigger when
    # outside" the radius — the SDK lets the same ProximityCheck mix both.
    TT_INSIDE  = 0
    TT_OUTSIDE = 1

    def __init__(self, event_type: int = 0):
        super().__init__()
        self._event_type = int(event_type)
        self._proximity_radius: float = 0.0
        # Per-object inside/outside tag.  Stored as a list of
        # (obj, type) pairs because the same object can theoretically appear
        # with both trigger types (rare but the SDK doesn't forbid it).
        self._check_objects: list = []
        self._check_object_ids: list = []
        self._check_types: list = []
        self._ignore_object_size: bool = False
        self._trigger_type: int = self.TT_INSIDE

    def GetEventType(self) -> int:
        return self._event_type

    def SetRadius(self, r) -> None:
        # Distinct from ObjectClass.SetRadius (visual radius) — proximity
        # radius is the trigger range.  SDK uses the same setter name; we
        # store under a different attribute to avoid clobbering ObjectClass.
        self._proximity_radius = float(r)

    def GetRadius(self) -> float:
        return self._proximity_radius

    def SetIgnoreObjectSize(self, v) -> None:
        self._ignore_object_size = bool(v)

    def GetIgnoreObjectSize(self) -> int:
        return 1 if self._ignore_object_size else 0

    def SetTriggerType(self, t) -> None:
        self._trigger_type = int(t)

    def GetTriggerType(self) -> int:
        return self._trigger_type

    def AddObjectToCheckList(self, obj, trigger_type=None) -> None:
        # Optional trigger_type arg (TT_INSIDE/TT_OUTSIDE) — recent SDK calls
        # use the two-arg form (E6M5/E6M4/E6M3, ConditionInRange).  Older
        # call sites use the single-arg form which falls through to whatever
        # trigger type is currently set on the check.
        tt = self._trigger_type if trigger_type is None else int(trigger_type)
        self._check_objects.append((obj, tt))

    def AddObjectToCheckListByID(self, obj_id, trigger_type=None) -> None:
        tt = self._trigger_type if trigger_type is None else int(trigger_type)
        self._check_object_ids.append((int(obj_id), tt))

    def AddObjectListToCheckList(self, lst, trigger_type=None) -> None:
        tt = self._trigger_type if trigger_type is None else int(trigger_type)
        for obj in lst:
            self._check_objects.append((obj, tt))

    def AddObjectTypeToCheckList(self, type_id, trigger_type=None) -> None:
        tt = self._trigger_type if trigger_type is None else int(trigger_type)
        self._check_types.append((int(type_id), tt))

    def IsObjectInCheckList(self, obj) -> int:
        return 1 if any(o is obj for o, _t in self._check_objects) else 0

    def RemoveObjectFromCheckList(self, obj) -> None:
        self._check_objects = [(o, t) for o, t in self._check_objects if o is not obj]

    def RemoveObjectFromCheckListByID(self, obj_id) -> None:
        oid = int(obj_id)
        self._check_object_ids = [(i, t) for i, t in self._check_object_ids if i != oid]

    def RemoveObjectTypeFromCheckList(self, type_id) -> None:
        tid = int(type_id)
        self._check_types = [(i, t) for i, t in self._check_types if i != tid]


def ProximityCheck_Create(event_type: int = 0) -> ProximityCheck:
    return ProximityCheck(event_type)


def ProximityCheck_CreateWithEvent(event) -> ProximityCheck:
    pc = ProximityCheck()
    pc._event = event
    return pc


# ── CharacterAction ──────────────────────────────────────────────────────────

class CharacterAction(TGAction):
    """Crew animation/audio action — the per-character primitive used by
    Bridge dialog scripts (MissionLib.py:647-660, BridgeHandlers.py:650).

    SDK call signature:
        CharacterAction_Create(pCharacter, action_type, detail, set_name,
                               flag, pDatabase, priority=NORMAL)

    Phase 1 stores the configuration; the actual character animation lives
    in Phase 2 (model + audio mixing).  Play() inherits TGAction's
    synchronous-completion flow so action sequences advance correctly.
    """
    # Action-type constants from sdk/.../App.py:4562-4600.  Values are stable
    # SDK-internal enum positions used by mission scripts via class-attr access.
    AT_SET_LOCATION             = 0
    AT_SET_LOCATION_NAME        = 1
    AT_MOVE                     = 2
    AT_TURN                     = 3
    AT_TURN_NOW                 = 4
    AT_TURN_BACK                = 5
    AT_TURN_BACK_NOW            = 6
    AT_DEFAULT                  = 7
    AT_BREATHE                  = 8
    AT_FORCE_BREATHE            = 9
    AT_SPEAK_LINE               = 10
    AT_SPEAK_LINE_NO_FLAP_LIPS  = 11
    AT_SAY_LINE                 = 12
    AT_SAY_LINE_AFTER_TURN      = 13
    AT_PLAY_ANIMATION           = 14
    AT_PLAY_ANIMATION_FILE      = 15
    AT_LOOK_AT_ME               = 16
    AT_LOOK_AT_ME_NOW           = 17
    AT_WATCH_ME                 = 18
    AT_STOP_WATCHING_ME         = 19
    AT_MENU_UP                  = 20
    AT_MENU_DOWN                = 21
    AT_SET_AUDIO_MODE           = 22
    AT_ENABLE_RANDOM_ANIMATIONS = 23
    AT_DISABLE_RANDOM_ANIMATIONS = 24
    AT_GLANCE_AT                = 25
    AT_GLANCE_AWAY              = 26
    AT_BECOME_ACTIVE            = 27
    AT_BECOME_INACTIVE          = 28
    AT_ENABLE_MENU              = 29
    AT_DISABLE_MENU             = 30
    AT_ENABLE_INITIATIVE        = 31
    AT_DISABLE_INITIATIVE       = 32
    AT_SET_STATUS               = 33

    def __init__(
        self,
        character=None,
        action_type: int = 0,
        detail=None,
        set_name=None,
        flag: int = 0,
        database=None,
        priority: int = 0,
    ):
        super().__init__()
        self._character = character
        self._action_type = int(action_type)
        self._detail = detail
        self._set_name = set_name
        self._flag = int(flag)
        self._database = database
        self._priority = int(priority)
        self._sub_priority: int = 0
        self._use_name_and_set: bool = False

    def GetActionType(self) -> int:           return self._action_type
    def GetDetail(self):                      return self._detail
    def SetPriority(self, p) -> None:         self._priority = int(p)
    def GetPriority(self) -> int:             return self._priority
    def SetSubPriority(self, p) -> None:      self._sub_priority = int(p)
    def GetSubPriority(self) -> int:          return self._sub_priority
    def UseNameAndSetInsteadOfObject(self, v) -> None:
        self._use_name_and_set = bool(v)


def CharacterAction_Create(
    character=None,
    action_type: int = 0,
    detail=None,
    set_name=None,
    flag: int = 0,
    database=None,
    priority: int = 0,
) -> CharacterAction:
    return CharacterAction(character, action_type, detail, set_name, flag, database, priority)


def CharacterAction_CreateByName(name: str, *args) -> CharacterAction:
    """Variant used when the caller has only a character name, not the object."""
    action = CharacterAction(*args)
    action._character_name = name
    action._use_name_and_set = True
    return action


# ── Character action priority constants ──────────────────────────────────────
# Top-level App constants used in BridgeHandlers.py:650 etc.
CSP_LOW    = 0
CSP_NORMAL = 1
CSP_HIGH   = 2
