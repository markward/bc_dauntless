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

import weakref

from engine.appc.objects import ObjectClass
from engine.appc.actions import TGAction
from engine.appc.events import TGEvent
import engine.dev_mode as dev_mode


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


def _import_dotted(qualified: str):
    """`__import__('Conditions.ConditionInRange')` returns the top-level
    `Conditions` package. Walk the dotted path to get the leaf module."""
    mod = __import__(qualified)
    for part in qualified.split(".")[1:]:
        mod = getattr(mod, part)
    return mod


class ConditionScript(TGCondition):
    """Python-script-backed condition (sdk/.../Conditions/*).

    Eager-instantiation pattern: on construction, try to __import__ the
    named module, walk dotted parts, getattr the class, and instantiate
    it with (self, *args). Fall back to a data-bag if anything fails;
    SDK call sites guard with `if pCondition.IsActive():` so a quiet
    fallback is safe.
    """
    def __init__(self, module_name: str = "", class_name: str = "", *args):
        super().__init__()
        self._module_name = module_name
        self._class_name = class_name
        self._args = args
        self._instance = None
        self._init_error: tuple[str, str] | None = None
        if module_name and class_name:
            try:
                mod = _import_dotted(module_name)
                cls = getattr(mod, class_name)
                self._instance = cls(self, *args)
            except Exception as e:
                self._instance = None
                self._init_error = (type(e).__name__, str(e))

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
    # id -> AI registry for ArtificialIntelligence_GetAIByID. Weak refs so
    # AIs that go out of scope don't pin the registry; SDK look-ups against
    # a stale ID return None, matching Appc's "AI was destroyed" semantics.
    _registry: "dict[int, weakref.ref[ArtificialIntelligence]]" = {}

    def __init__(self, pShip=None, name: str = ""):
        self._ship = pShip
        self._name = name
        self._interruptable = True
        self._paused = False
        self._has_focus = False
        self._status = self.US_ACTIVE
        # External-function registry (SDK RegisterExternalFunction): every
        # Appc AI exposes this surface so preprocessors like FireScript can
        # do ``self.pCodeAI.RegisterExternalFunction("SetTarget", ...)``
        # against the PreprocessingAI wrapping them. PlainAI overrides
        # CallExternalFunction to actually dispatch; interior nodes inherit
        # the base no-op (see below) — registration storage lives here so
        # the call site doesn't care about node type.
        self._external_functions: dict = {}
        # Per-node update cadence (game seconds). The driver consults this to
        # decide whether a node's own Update runs this tick (see
        # ai_driver._tick_plain / _tick_preprocessing). Starts at 0.0 so the
        # very first driver tick (game_time >= 0) always runs. Lives on the
        # base so every node type — not just PlainAI — can be rescheduled by
        # ForceUpdate. Interior nodes that don't self-gate simply ignore it.
        self._next_update_time: float = 0.0
        type(self)._allocate_id(self)

    @classmethod
    def _allocate_id(cls, ai) -> None:
        ai._id = ArtificialIntelligence._next_id
        ArtificialIntelligence._next_id += 1
        ArtificialIntelligence._registry[ai._id] = weakref.ref(ai)

    # ── Identity ─────────────────────────────────────────────────────────────
    def GetID(self) -> int:               return self._id
    def GetName(self) -> str:             return self._name
    def GetShip(self):                    return self._ship
    def GetObject(self):                  return self._ship   # SDK alias

    # ── Tree walking ─────────────────────────────────────────────────────────
    def GetAllAIsInTree(self) -> list:
        """Return self followed by every AI reachable beneath this node.

        SDK pattern (AI/Preprocessors.py:1384 — SelectTarget.CallSetTargetFunctions):
        ``lAIs = self.pCodeAI.GetAllAIsInTree()[1:]`` then iterates calling
        ``CallExternalFunction`` on each leaf. The list-with-self ordering
        matches the C++ Appc semantics so that `[1:]` skips the caller.

        Subclasses with child AIs are handled here via duck-typed attribute
        probes — keeps the tree-walking logic in one place instead of an
        override per AI type. Order: PriorityListAI / SequenceAI children
        in insertion order, then ConditionalAI / PreprocessingAI contained
        AI.
        """
        out: list = [self]
        # PriorityListAI / SequenceAI / PlainAI: ._ais is a list of either
        # plain AIs (Sequence) or (priority, ai) tuples (PriorityList).
        children = getattr(self, "_ais", None)
        if isinstance(children, list):
            for child in children:
                ai = child[1] if isinstance(child, tuple) else child
                if ai is not None:
                    out.extend(ai.GetAllAIsInTree())
        # ConditionalAI / PreprocessingAI: ._contained_ai is a single AI.
        contained = getattr(self, "_contained_ai", None)
        if contained is not None:
            out.extend(contained.GetAllAIsInTree())
        return out

    # ── Status ───────────────────────────────────────────────────────────────
    def IsActive(self) -> int:            return 1 if self._status == self.US_ACTIVE else 0
    def HasFocus(self) -> int:            return 1 if self._has_focus else 0
    def Pause(self) -> None:              self._paused = True
    def Unpause(self) -> None:            self._paused = False
    def IsPaused(self) -> int:            return 1 if self._paused else 0
    def Reset(self) -> None:              self._status = self.US_ACTIVE
    def SetInterruptable(self, v) -> None: self._interruptable = bool(v)
    def IsInterruptable(self) -> int:     return 1 if self._interruptable else 0

    # ── External-function dispatch (base no-op) ─────────────────────────────
    # SDK SelectTarget.CallSetTargetFunctions iterates every AI in the tree
    # via GetAllAIsInTree() and unconditionally calls CallExternalFunction
    # (sdk/.../AI/Preprocessors.py:1407). Only PlainAI registers SetTarget
    # hooks, so interior nodes (PriorityListAI, SequenceAI, PreprocessingAI,
    # ConditionalAI) need a tolerant no-op so the dispatch loop doesn't
    # AttributeError on them.
    def CallExternalFunction(self, name: str, *args) -> None:
        pass

    def RegisterExternalFunction(self, name: str, mapping) -> None:
        """Record name -> mapping in the AI's external-function registry.

        SDK FireScript.CodeAISet (AI/Preprocessors.py:137-145) calls this
        on its wrapping ``pCodeAI`` (a PreprocessingAI) so SelectTarget's
        ``CallExternalFunction("SetTarget", name)`` dispatch can reach the
        FireScript preprocessor. PlainAI overrides ``CallExternalFunction``
        to actually invoke registered methods; interior nodes just keep the
        registration as data.
        """
        self._external_functions[name] = mapping

    def GetExternalFunctions(self) -> dict:
        return dict(self._external_functions)

    # ── Forced reschedule ────────────────────────────────────────────────────
    def ForceUpdate(self) -> None:
        """Re-run this AI on the next driver tick that reaches it, instead of
        waiting for its scheduled cadence.

        BC semantics (Appc.PreprocessingAI_ForceUpdate): a *reschedule*, NOT a
        synchronous re-tick. SelectTarget calls ``self.pCodeAI.ForceUpdate()``
        from its event handlers (TargetGone / ObjectDecloaked / OurShipEnteredSet
        / TargetEnteredSet / TargetListChanged, AI/Preprocessors.py:1277-1302) so
        the ship re-picks a target the instant its current one cloaks / leaves the
        set / dies, rather than after the 5s ``fNormalUpdateTime`` cadence.

        Resetting ``_next_update_time`` to 0.0 (<= every real game_time) is
        sufficient — no parent/root propagation is needed. The AI tree dispatches
        to contained/children every driver tick regardless of a node's own
        cadence, so a node on the active path is *reached* every tick; its own
        gate is all that stands between it and re-running. (Caveat: this cannot
        revive a node that has already latched US_DORMANT and is therefore
        skipped by its parent priority list — e.g. re-acquiring a *decloaking*
        target. The drop-on-cloak path is unaffected: the node is still US_ACTIVE
        at the moment it is forced.)
        """
        self._next_update_time = 0.0


# ── PlainAI ──────────────────────────────────────────────────────────────────

class PlainAI(ArtificialIntelligence):
    def __init__(self, pShip=None, name: str = ""):
        super().__init__(pShip, name)
        self._script_module: str = ""
        self._script_instance = None
        # _external_functions and _next_update_time inherited from the
        # ArtificialIntelligence base. _tick_plain gates on _next_update_time
        # (first Update fires at game_time >= 0.0) and reschedules it after each
        # Update() using the script's GetNextUpdateTime().

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

    # RegisterExternalFunction / GetExternalFunctions inherited from base.
    # PlainAI overrides CallExternalFunction below to actually dispatch the
    # registered mapping to a script-instance method.

    def CallExternalFunction(self, name: str, *args) -> None:
        """Invoke the script-instance method registered for `name`.

        SDK pattern: BaseAI.SetExternalFunctions stores ``{"Name": method}``;
        some scripts (e.g. ones built ad-hoc by mission code) use
        ``{"FunctionName": method}`` instead. Both keys are recognized.

        Called by SelectTarget.CallSetTargetFunctions to dispatch the
        chosen target name onto every leaf AI that registered a
        "SetTarget" hook. Silent no-op if the function isn't registered,
        the lookup key is missing, or the named method doesn't exist on
        the script instance — mirrors Appc's tolerant Python dispatch.
        """
        info = self._external_functions.get(name)
        if not info:
            return
        fn_name = info.get("FunctionName") or info.get("Name")
        if not fn_name:
            return
        inst = self.GetScriptInstance()
        if inst is None:
            return
        method = getattr(inst, fn_name, None)
        if method is None:
            return
        method(*args)

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


# ── RandomAI ─────────────────────────────────────────────────────────────────

class RandomAI(ArtificialIntelligence):
    """SDK App.py:5019 — sibling of PriorityListAI/SequenceAI.

    Picks one child at random and ticks it each frame; when that child
    reaches US_DONE it re-picks a new random child on the next tick
    (docs/original_game_reference/gameplay/ai-architecture.md, RandomAI
    section: "Picks one child at random; on completion, picks another").
    Typically wraps several maneuver children inside a forever-looping
    SequenceAI (sdk/.../AI/Compound/Parts/NoSensorsEvasive.py:47-52,
    sdk/.../QuickBattle/QuickBattleAI.py:51-58). Dispatch lives in
    ai_driver._tick_random."""

    def __init__(self, pShip=None, name: str = ""):
        super().__init__(pShip, name)
        self._ais: list = []
        # The child currently being ticked; re-picked when it reaches DONE.
        self._current_child = None

    def AddAI(self, ai) -> None:
        """SDK Appc.RandomAI_AddAI — append a child AI."""
        self._ais.append(ai)

    def GetAIs(self) -> list:
        """Return the child AI list (used by the AI inspector)."""
        return self._ais


def RandomAI_Create(pShip, name: str = "") -> RandomAI:
    """SDK App.py:Appc.RandomAI_Create — factory."""
    return RandomAI(pShip, name)


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
        # Set to True when the preprocessor's Update returns PS_DONE.
        # SDK semantics: "this preprocessor's job is finished" — stop
        # calling Update on it, but the wrapper PreprocessingAI is NOT
        # done; the contained_ai continues to dispatch normally. Without
        # this gate, an "Unused"-style preprocessor (e.g. ManagePower
        # which returns PS_DONE unconditionally) would kill the whole
        # subtree on the first tick.
        self._preprocess_done: bool = False
        # Last PS_* result from the preprocessor's Update, so cadence-skipped
        # ticks (game_time < _next_update_time) can reproduce its effect
        # instead of blindly dispatching the contained AI. See
        # ai_driver._tick_preprocessing.
        self._last_preprocess_status: int = PreprocessingAI.PS_NORMAL

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
            # SDK preprocessor classes (SelectTarget, FireScript) call
            # self.pCodeAI.GetShip()/GetAllAIsInTree() throughout their
            # Update bodies. The C++ optimized engine wires pCodeAI when
            # SetPreprocessingMethod runs; Phase 1 has no optimization,
            # so we wire it here. Slice B test fixtures set this
            # explicitly; NonFedAttack/FedAttack SDK CreateAI doesn't.
            try:
                args[0].pCodeAI = self
            except (AttributeError, TypeError):
                # Instance refuses attribute assignment (e.g. slotted
                # class); skip — caller is responsible.
                pass

    def GetPreprocessingInstance(self):
        if self._preprocessing_instance is None:
            self._preprocessing_instance = _AIScriptInstance(self)
        return self._preprocessing_instance

    # ForceUpdate inherited from ArtificialIntelligence (resets
    # _next_update_time so the next tick re-runs this node's preprocessor).
    # ForceDormantStatus / ForceStatusChange remain stubs — used only by
    # SelectTarget's bUpdatingTargetInfo work-spreading path, which we run
    # synchronously rather than across frames.
    def ForceDormantStatus(self, *args) -> None:    pass
    def ForceStatusChange(self, *args) -> None:     pass

    def CallExternalFunction(self, name: str, *args) -> None:
        """Dispatch a registered external function to the preprocessing
        instance — mirror of PlainAI.CallExternalFunction.

        SDK FireScript.CodeAISet (AI/Preprocessors.py:137-145) registers
        ``SetTarget`` on its wrapping ``pCodeAI`` (a PreprocessingAI), not
        on a child PlainAI. SelectTarget.CallSetTargetFunctions
        (AI/Preprocessors.py:1407) walks every AI in the tree and calls
        ``pAI.CallExternalFunction("SetTarget", name)`` unconditionally,
        so the wrapping PreprocessingAI must actually route the call to
        ``self._preprocessing_instance.<method>`` rather than no-op.

        Silent no-op if the function isn't registered, the lookup key is
        missing, the instance is unset, or the named method doesn't exist —
        mirrors PlainAI's tolerant dispatch.
        """
        info = self._external_functions.get(name)
        if not info:
            return
        fn_name = info.get("FunctionName") or info.get("Name")
        if not fn_name:
            return
        inst = self._preprocessing_instance
        if inst is None:
            return
        method = getattr(inst, fn_name, None)
        if method is None:
            return
        method(*args)


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
        # Observing a condition activates it: TGCondition.SetStatus only
        # notifies handlers while _active, and conditions default inactive.
        # Without this, MissionLib.CallFunctionWhenConditionChanges wiring
        # (e.g. HelmMenuHandlers' g_pPlayerOrbitting → the "entering/leaving
        # orbit" helm lines) records status flips but never fires the event.
        cond.SetActive()

    def RemoveCondition(self, cond: TGCondition) -> None:
        """Detach a previously-added condition. SDK DynamicMusic.RemoveConditions
        drops mission/player-scoped conditions when the mission or player changes
        (e.g. StandardCombatMusic.PlayerChanged re-runs on ET_SET_PLAYER). Mirror
        AddCondition: forget the condition and unhook this handler from it.
        Tolerant of a condition that was never added / already removed."""
        try:
            self._conditions.remove(cond)
        except ValueError:
            pass
        try:
            cond.RemoveHandler(self)
        except Exception as _e:
            dev_mode.log_swallowed("RemoveCondition detach", _e)

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
        except Exception as _e:
            dev_mode.log_swallowed("AI add activation event", _e)


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
        # Activation state — set by ai_driver._tick_builder on first tick.
        # Eager init, not getattr-fallback: TGObject.__getattr__ in
        # engine/core/ids.py returns a _Stub for missing attrs (not None),
        # so the usual `getattr(self, "_field", None) is None` idiom is
        # broken in this codebase.
        self._activated: bool = False
        self._activation_failed: bool = False
        self._activation_error: tuple[str, str] | None = None  # (exc_type, msg)

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

    def __init__(self, event_type: int = 0, event_handler=None):
        super().__init__()
        self._event_type = int(event_type)
        # SDK ConditionInRange calls ProximityCheck_Create(eEventType, pEventHandler).
        # The handler is the destination object for fired events — the
        # event-manager routes through it so the SDK condition's
        # TGPythonInstanceWrapper.ProcessEvent dispatches to the right
        # method ("ProximityEvent") on the wrapped Python instance.
        self._event_handler = event_handler
        self._proximity_radius: float = 0.0
        # Per-object inside/outside tag.  Stored as a list of
        # (obj, type) pairs because the same object can theoretically appear
        # with both trigger types (rare but the SDK doesn't forbid it).
        self._check_objects: list = []
        self._check_object_ids: list = []
        self._check_types: list = []
        self._ignore_object_size: bool = False
        self._trigger_type: int = self.TT_INSIDE
        # Anchor object — set by ObjectClass.AttachObject(prox); the
        # per-tick evaluator centers the radius on this object's
        # world location.
        self._anchor = None
        # Per-tick inside-set tracker.  Stored as ids so we don't pin objects
        # alive past their own lifecycle and so equality follows identity.
        # Eager init: TGObject.__getattr__ returns a truthy _Stub for missing
        # attrs (engine/core/ids.py:87), so `getattr(self, "_inside_set", None)`
        # would silently mis-resolve — see TGPythonInstanceWrapper notes in
        # engine/appc/events.py for the same hazard.
        self._inside_set: set = set()
        # Objects whose baseline inside/outside state has been sampled at
        # least once. Edge detection needs a prior sample to detect a
        # crossing, so the FIRST per-tick evaluation of an object only
        # records the baseline and never fires — otherwise an object that
        # is already in its trigger state when the check starts evaluating
        # (e.g. the player docked inside the starbase proximity at mission
        # load) would be mistaken for a fresh crossing.
        self._baselined: set = set()

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

    def SetTriggerType(self, *args) -> None:
        """Two forms:
            SetTriggerType(tt)        → default trigger type for newly-
                                        added objects (used by older SDK).
            SetTriggerType(obj, tt)   → per-object trigger type, used by
                                        SDK ConditionInRange.ProximityEvent
                                        to re-arm an object after a
                                        boundary-crossing event fires.
        """
        if len(args) == 1:
            self._trigger_type = int(args[0])
        elif len(args) == 2:
            obj, tt = args
            tt = int(tt)
            self._check_objects = [
                (o, tt) if o is obj else (o, t) for o, t in self._check_objects
            ]

    def GetTriggerType(self, obj=None) -> int:
        """Per-object trigger lookup when `obj` is given (used by SDK
        ConditionInRange.ProximityEvent / ExitedSet). With no argument,
        returns the default trigger type for the check."""
        if obj is None:
            return self._trigger_type
        for o, t in self._check_objects:
            if o is obj:
                return t
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

    def CheckProximity(self, obj) -> None:
        """Immediate, single-object proximity test against this check's
        anchor. SDK ConditionInRange.SetupProximitySphere calls this once
        per newly-registered watched object so initial-state transitions
        fire without waiting for the next tick. No-op if no anchor is
        attached yet."""
        if self._anchor is None:
            return
        # Force a fire if the watched object currently matches its
        # per-object trigger condition. Bypasses the edge-detection
        # bookkeeping so the SDK condition can re-arm via
        # SetTriggerType in its ProximityEvent handler and immediately
        # see a fresh event next CheckProximity call.
        self._evaluate_one(obj, force=True)

    def _evaluate_one(self, obj, force: bool = False) -> None:
        """Shared per-object logic for Evaluate() and CheckProximity().

        Fire when the watched object matches its trigger type:
          TT_INSIDE  → fire when inside the radius
          TT_OUTSIDE → fire when outside the radius

        Evaluate() is edge-triggered: only fires when the inside/outside
        state changes from the last tick (so a stationary inside object
        doesn't spam events every frame). CheckProximity() uses
        force=True for immediate firing on initial setup.
        """
        import App
        anchor_loc = (
            self._anchor.GetWorldLocation()
            if hasattr(self._anchor, "GetWorldLocation") else None
        )
        loc = obj.GetWorldLocation() if hasattr(obj, "GetWorldLocation") else None
        if anchor_loc is None or loc is None:
            return
        # Look up the per-object trigger type.
        trigger_type = None
        for o, t in self._check_objects:
            if o is obj:
                trigger_type = t
                break
        if trigger_type is None:
            return
        r2 = self._proximity_radius * self._proximity_radius
        dx = loc.x - anchor_loc.x
        dy = loc.y - anchor_loc.y
        dz = loc.z - anchor_loc.z
        is_inside = (dx * dx + dy * dy + dz * dz) <= r2
        matches = (
            (trigger_type == ProximityCheck.TT_INSIDE and is_inside) or
            (trigger_type == ProximityCheck.TT_OUTSIDE and not is_inside)
        )
        # Edge detection: only fire on transition into the matching
        # state, not every tick the object stays there. The
        # _inside_set tracker remembers which objects were inside on
        # the previous evaluation.
        was_inside = id(obj) in self._inside_set
        if is_inside:
            self._inside_set.add(id(obj))
        else:
            self._inside_set.discard(id(obj))
        # First per-tick sample only establishes the baseline; it never fires
        # (the force=True CheckProximity path bypasses this for explicit
        # immediate checks). This is what stops an already-inside object at
        # mission load from being read as a fresh crossing.
        first_eval = id(obj) not in self._baselined
        self._baselined.add(id(obj))
        if not matches:
            return
        if not force and (first_eval or is_inside == was_inside):
            return
        evt = ProximityEvent()
        evt.SetEventType(self._event_type)
        evt._proximity_check = self
        evt._object = obj
        # When a per-condition event handler is attached, route the
        # event through it (SDK ConditionInRange flow). Otherwise fall
        # back to the watched object as destination — matches the
        # original per-tick evaluator contract that fires events
        # addressed to the watched object itself.
        if self._event_handler is not None:
            evt.SetDestination(self._event_handler)
        else:
            evt.SetDestination(obj)
        App.g_kEventManager.AddEvent(evt)

    def Evaluate(self, anchor_obj=None) -> None:
        """Per-tick: for each watched object, test whether it's crossed
        its per-object trigger boundary against ``anchor_obj``.

        Two anchor-resolution paths:
          - ``evaluate_proximity_checks`` passes the anchor explicitly
            (the original per-tick-evaluator contract).
          - SDK condition flow records the anchor via
            ``ObjectClass.AttachObject(self)`` and stores it as
            ``self._anchor``; this method reads it when no arg is given.
        Either path resolves to the same anchor.

        Called by GameLoop.tick between tick_all_ai and tick_all_ship_motion.
        """
        if anchor_obj is not None:
            self._anchor = anchor_obj
        if self._anchor is None:
            return
        # Snapshot watched objects so trigger-type swaps inside ProximityEvent
        # handlers don't perturb iteration.
        for obj, _t in list(self._check_objects):
            self._evaluate_one(obj)

    def RemoveAndDelete(self) -> None:
        """SDK calls this when scrapping a no-longer-needed proximity
        sphere (ConditionInRange.__del__, .SetupProximitySphere). Clear
        the watch list and detach so the per-tick evaluator drops this
        check on its next pass."""
        self._check_objects = []
        self._check_object_ids = []
        self._check_types = []
        self._inside_set = set()
        self._baselined = set()
        # Drop ourselves from the anchor-set's proximity manager so
        # evaluate_proximity_checks stops walking us.
        anchor = self._anchor
        if anchor is not None and hasattr(anchor, "GetContainingSet"):
            pSet = anchor.GetContainingSet()
            if pSet is not None and hasattr(pSet, "GetProximityManager"):
                pm = pSet.GetProximityManager()
                if pm is not None:
                    pm.RemoveObject(self)
        self._anchor = None


class ProximityEvent(TGEvent):
    """Event fired when a watched object crosses a ProximityCheck
    boundary. SDK condition handlers read ``GetObject()`` / ``GetProximityCheck()``
    to identify the crossing object and the originating check."""
    def __init__(self):
        super().__init__()
        self._object = None
        self._proximity_check = None

    def GetObject(self):
        return self._object

    def GetProximityCheck(self):
        return self._proximity_check


def ProximityCheck_Create(event_type: int = 0, event_handler=None) -> ProximityCheck:
    """SDK signature: ``ProximityCheck_Create(eEventType[, pEventHandler])``.

    The optional ``event_handler`` is a TGPythonInstanceWrapper that
    becomes the destination for events the check fires — used by
    Conditions/ConditionInRange so the wrapper's ProcessEvent routes the
    proximity event to the right method on the wrapped Python instance.
    """
    return ProximityCheck(event_type, event_handler)


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
        # Spoken lines are skippable by default (Backspace →
        # TGActionManager_SkipEvents), matching BC where dialogue lines skip
        # without the SDK marking each CharacterAction explicitly.
        if self._action_type in (self.AT_SPEAK_LINE,
                                 self.AT_SPEAK_LINE_NO_FLAP_LIPS,
                                 self.AT_SAY_LINE,
                                 self.AT_SAY_LINE_AFTER_TURN):
            self._skippable = True

    def GetActionType(self) -> int:           return self._action_type
    def GetDetail(self):                      return self._detail
    def SetPriority(self, p) -> None:         self._priority = int(p)
    def GetPriority(self) -> int:             return self._priority
    def SetSubPriority(self, p) -> None:      self._sub_priority = int(p)
    def GetSubPriority(self) -> int:          return self._sub_priority
    def UseNameAndSetInsteadOfObject(self, v) -> None:
        self._use_name_and_set = bool(v)

    def Play(self) -> None:
        # Speak-types complete after the voice line's real duration so a
        # sequence step chained after the line advances when the line finishes.
        # Non-speak types (MOVE/TURN/GLANCE/...) complete inline as before.
        self._playing = True
        at = self._action_type
        if at == self.AT_MOVE:
            # Movement (walk-on / sit-down) completes when the walk clip settles:
            # the walk controller calls our Completed(). If it can't be queued
            # (headless / unresolved builder), complete inline so the mission
            # TGSequence never stalls.
            self._queue_move()
            return
        if at == self.AT_SET_LOCATION_NAME:
            if self._character is not None and self._detail is not None:
                try:
                    self._character.SetLocation(self._detail)
                except Exception:
                    pass
            self.Completed()
            return
        # AT_WATCH_ME / AT_STOP_WATCHING_ME set the watch-captain flag (visual
        # head-track is a follow-up; sequencing must still advance). Other
        # non-speak types remain inline no-ops.
        if at in (self.AT_WATCH_ME, self.AT_STOP_WATCHING_ME):
            self._set_watch(at == self.AT_WATCH_ME)
            self.Completed()
            return
        if at in (self.AT_TURN, self.AT_TURN_NOW,
                  self.AT_TURN_BACK, self.AT_TURN_BACK_NOW):
            self._queue_turn(
                back=at in (self.AT_TURN_BACK, self.AT_TURN_BACK_NOW),
                now=at in (self.AT_TURN_NOW, self.AT_TURN_BACK_NOW))
            return
        # Speak types (and the remaining no-op types) keep the prior flow.
        dur = self._do_play()
        self._complete_after(dur or 0.0)

    def _queue_move(self) -> None:
        # Best-effort: capture_move runs an SDK builder function that CAN
        # raise (production only), and any of the resolution steps below
        # can fail. Play() must never raise — a failure here should
        # complete the action inline so the mission TGSequence advances
        # instead of stalling.
        from engine.appc import bridge_placement
        from engine.appc.characters import CharacterClass_Cast
        from engine import bridge_character_walk
        try:
            cc = CharacterClass_Cast(self._character) if self._character is not None else None
            ctrl = bridge_character_walk.get_controller()
            move = bridge_placement.capture_move(cc, self._detail) if cc is not None else None
            if cc is None or ctrl is None or move is None:
                self.Completed()      # nothing to play → advance immediately
                return
            ctrl.request_move(cc, move["clip_nif"], move["end_location"],
                              on_complete=self.Completed)
        except Exception:
            self.Completed()

    def _queue_turn(self, *, back: bool, now: bool) -> None:
        # Turn (AT_TURN/AT_TURN_BACK, + _NOW). Non-`now` completes when the turn
        # controller settles (deferred, faithful to BC); `now` completes inline.
        # Best-effort: Play() must never raise — any failure completes inline so
        # the mission TGSequence advances instead of stalling.
        from engine.appc.characters import CharacterClass_Cast
        from engine import bridge_character_anim
        try:
            cc = CharacterClass_Cast(self._character) if self._character is not None else None
            ctrl = bridge_character_anim.get_controller()
            if cc is None or ctrl is None:
                self.Completed()
                return
            if back:
                detail = getattr(cc, "_last_turn_detail", None) or "Captain"
                try:
                    cc._last_turn_detail = None
                except Exception:
                    pass
            else:
                detail = str(self._detail) if self._detail is not None else "Captain"
                try:
                    cc._last_turn_detail = detail
                except Exception:
                    pass
            if now:
                ctrl.request_turn_to(cc, detail, back=back, now=True,
                                     on_complete=None)
                self.Completed()
            else:
                ctrl.request_turn_to(cc, detail, back=back, now=False,
                                     on_complete=self.Completed)
        except Exception:
            self.Completed()

    def _set_watch(self, watching: bool) -> None:
        cc = self._character
        if cc is None:
            return
        try:
            if watching:
                cc.SetStatus(cc.CS_TURNED)     # "watching the captain" state flag
            else:
                cc.ClearStatus(cc.CS_TURNED)
        except Exception:
            pass

    def _do_play(self):
        at = self._action_type
        if at not in (self.AT_SPEAK_LINE, self.AT_SPEAK_LINE_NO_FLAP_LIPS,
                      self.AT_SAY_LINE, self.AT_SAY_LINE_AFTER_TURN):
            return 0.0
        from engine.appc import crew_speech
        from engine.appc.characters import CharacterClass_Cast
        cc = CharacterClass_Cast(self._character) if self._character is not None else None
        if cc is not None:
            name = cc.GetCharacterName()
        elif isinstance(self._character, str):
            name = self._character
        else:
            name = ""
        db = self._database
        if db is None and cc is not None:
            # BC's SAY_LINE with no explicit database speaks from the
            # character's own assigned DB — SDK call sites rely on it
            # (HelmCharacterHandlers.OrbitPlanet/SetCourse pass db=None).
            # Without the fallback the line resolves to no text and no wav
            # and the bus stays silent.
            db = cc.GetDatabase()
        return crew_speech.emit(name, db, self._detail,
                                self._priority) or 0.0

    def Skip(self) -> None:
        # Our line is the one holding the crew-speech channel (single-channel
        # bus): cut its voice + subtitle before completing so the audio stops
        # with the action instead of playing out under the next line. Non-speak
        # action types complete inline and never own the channel — leave it be.
        if self._action_type in (self.AT_SPEAK_LINE,
                                 self.AT_SPEAK_LINE_NO_FLAP_LIPS,
                                 self.AT_SAY_LINE,
                                 self.AT_SAY_LINE_AFTER_TURN):
            from engine.appc import crew_speech
            crew_speech.bus().skip_current()
        super().Skip()


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
# Top-level App constants used in BridgeHandlers.py:650 and every SpeakLine
# call site. The SDK names are CSP_SPONTANEOUS/CSP_NORMAL/CSP_MISSION_CRITICAL;
# CSP_LOW/CSP_HIGH are dauntless-era aliases kept for back-compat.
CSP_SPONTANEOUS      = 0   # idle chatter (engineer reports, ge*)
CSP_NORMAL           = 1   # acknowledgements; default
CSP_MISSION_CRITICAL = 2   # scripted mission narration
CSP_LOW  = CSP_SPONTANEOUS      # back-compat alias
CSP_HIGH = CSP_MISSION_CRITICAL # back-compat alias


# ── Module-level helpers (SDK `App.*` surface) ───────────────────────────────
def ArtificialIntelligence_GetAIByID(ai_id: int):
    """Return the AI with the given integer ID, or None if absent.

    SDK pattern (AI/Preprocessors.py:1386 — SelectTarget.CallSetTargetFunctions
    + AI/Preprocessors.py:1405): an AI tree records leaf IDs via GetID() and
    later resolves them back through App.ArtificialIntelligence_GetAIByID for
    cross-tick dispatch (the tree may have been re-entrant-edited in
    between, so a stale ID must safely return None).
    """
    ref = ArtificialIntelligence._registry.get(int(ai_id))
    if ref is None:
        return None
    return ref()
