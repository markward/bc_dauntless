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
        if not changed:
            return
        if self._active:
            for h in list(self._handlers):
                h.ConditionChanged(self)
        # Real Appc posts ET_AI_CONDITION_CHANGED from ConditionScript::SetStatus
        # so composite conditions can watch their children
        # (Conditions/ConditionCriticalSystemBelow.py). Fired unconditionally on
        # a real change — NOT gated on _active, which only governs the direct
        # handler list.
        #
        # NOT wrapped in try/except. Removing the swallow allows event construction
        # and dispatch infrastructure errors to surface. Handler body exceptions are
        # caught and logged by design (see events.py:501-506, the broadcast path guard),
        # matching original BC's behavior of printing tracebacks while the loop continues.
        # The benefit: event setup errors in never-before-run code now propagate instead of
        # vanishing. Matches ShipClass.SetTarget's AddEvent, which deliberately refuses
        # the same swallow.
        import App
        evt = App.TGIntEvent_Create()
        evt.SetEventType(App.ET_AI_CONDITION_CHANGED)
        evt.SetInt(new_status)
        evt.SetSource(self)
        evt.SetDestination(self)
        App.g_kEventManager.AddEvent(evt)

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

    # Real Appc's ConditionScript::SetActive / ::SetInactive forward to the
    # wrapped Python instance's optional Activate() / Deactivate(). Five shipped
    # conditions define Activate(); the load-bearing one is ConditionTimer
    # (65 SDK uses), whose Activate() re-arms the timer when bResetOnActivate is
    # set (Conditions/ConditionTimer.py:66-81). Without the forward it fires once
    # and latches true forever.
    def SetActive(self, *args) -> None:
        super().SetActive(*args)
        activate = getattr(self._instance, "Activate", None) if self._instance else None
        if callable(activate):
            try:
                activate()
            except Exception as _e:
                dev_mode.log_swallowed("condition Activate", _e)

    def SetInactive(self, *args) -> None:
        super().SetInactive(*args)
        deactivate = getattr(self._instance, "Deactivate", None) if self._instance else None
        if callable(deactivate):
            try:
                deactivate()
            except Exception as _e:
                dev_mode.log_swallowed("condition Deactivate", _e)


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
    # Values read from the binary's swig_const_info table (0x0090d9ac+), 2026-07-14.
    # ai-architecture.md sec.2 lists DORMANT/DONE swapped — the DOC is wrong, and
    # that error is what made its PreprocessingAI::Update switch look inverted.
    # Pinned by tests/unit/test_ai_reset_and_status_values.py.
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
        # Node-in-tree activation state (BaseAI vtable +0x20/+0x24 in
        # ai-architecture.md Sec.6) -- distinct from IsActive()/_status
        # (US_ACTIVE vs US_DORMANT/US_DONE, "is this node's own work
        # currently eligible"). This is "has the AI driver's dispatch
        # reached this node on the active path this tick", set/cleared by
        # SetActive()/SetInactive() below.
        self._is_active_in_tree: bool = False
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

    def GetFocusAIs(self) -> list:
        """The AIs on the current focus path, self first if self has focus.

        Appc hand-registers this on ArtificialIntelligence (0x00470f70;
        ai-architecture.md sec.4). AI/Preprocessors.py:2230
        (FelixReportStatus.Update) walks it and calls CallExternalFunction(
        "QueryAIStatus", lStatus) on each node, which is how the crew report
        what the AI is currently doing. Every AI/Player tree roots one of these.

        The focus latch is written by ai_driver for every node it reaches on the
        active dispatch path, so "reached this tick" == "has focus".
        """
        return [ai for ai in self.GetAllAIsInTree() if ai.HasFocus()]

    # ── Status ───────────────────────────────────────────────────────────────
    def IsActive(self) -> int:            return 1 if self._status == self.US_ACTIVE else 0
    def HasFocus(self) -> int:            return 1 if self._has_focus else 0
    def Pause(self) -> None:              self._paused = True
    def Unpause(self) -> None:            self._paused = False
    def IsPaused(self) -> int:            return 1 if self._paused else 0
    def Reset(self) -> None:
        """Re-arm this node: ACTIVE, due immediately, and tell the script.

        Appc's Reset zeroes nextUpdateTime so the node updates on the very next
        tick (ai-architecture.md sec.3). Four PlainAI scripts define a script-side
        Reset() — FollowWaypoints (rewinds the waypoint cursor), Warp,
        ManeuverLoop, IntelligentCircleObject — and
        AI/Compound/TractorDockTargets.py:20 calls it on its contained AI.
        """
        self._status = self.US_ACTIVE
        self._next_update_time = 0.0
        d = getattr(self, "__dict__", {})
        inst = d.get("_script_instance") or d.get("_preprocessing_instance")
        reset = getattr(inst, "Reset", None) if inst is not None else None
        if callable(reset):
            try:
                reset()
            except Exception as _e:
                dev_mode.log_swallowed("AI script Reset", _e)

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

    # ── Tree activation lifecycle ────────────────────────────────────────────
    # Mirrors BaseAI's SetActive/SetInactive (vtable +0x20/+0x24,
    # ai-architecture.md Sec.6): fired when a node becomes active/inactive IN
    # THE TREE (i.e. reached / not reached on the AI driver's active dispatch
    # path this tick), guarded so each fires exactly once per transition --
    # not every tick. This is a different question from IsActive()
    # (US_ACTIVE vs DORMANT/DONE) above; do not conflate the two.
    def SetActive(self) -> None:
        """Node became active in the tree. Appc guards this with a byte flag
        so it fires ONCE per activation, not every tick (BaseAI vtable
        +0x20)."""
        if self._is_active_in_tree:
            return
        self._is_active_in_tree = True
        self._on_activated()

    def SetInactive(self) -> None:
        """Node was deactivated (BaseAI vtable +0x24). Matching edge."""
        if not self._is_active_in_tree:
            return
        self._is_active_in_tree = False
        self._on_deactivated()

    def _on_activated(self) -> None:
        """Subclass hook. Base does nothing."""

    def _on_deactivated(self) -> None:
        """Subclass hook. Base does nothing."""

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
        sufficient — no parent/root propagation is needed. A node on the active
        path is *reached* every tick; its own gate is all that stands between it
        and re-running. A node that has gone US_DORMANT under a PriorityListAI is
        also revived by this: ``_tick_priority_list`` re-probes a dormant
        PreprocessingAI child once its cadence gate is due, and ForceUpdate opens
        that gate (this is what lets a ship re-acquire a decloaking target, or
        re-engage reinforcements after its target dies). NOTE the revival is
        specific to PriorityListAI children — a SequenceAI still *holds* on a
        dormant child by design, so ForceUpdate does not un-wedge a dormant
        sequence step.
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
        # Passes remaining. -1 = forever (ai-architecture.md sec.2: the C++ node
        # keeps the remaining-loop count at +0x34 and decrements it on wrap).
        self._loops_remaining: int = 1
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

    def SetLoopCount(self, n) -> None:
        self._loop_count = int(n)
        self._loops_remaining = int(n)

    def GetLoopCount(self) -> int:            return self._loop_count

    def SetResetIfInterrupted(self, v) -> None:
        # Stored-but-unused: no tree we currently run depends on this flag,
        # and its exact semantics are not established by the RE corpus
        # (ai-architecture.md sec.2 names the field but not its precise
        # effect). Do not invent behaviour for it.
        self._reset_if_interrupted = bool(v)

    def SetDoubleCheckAllDone(self, v) -> None:
        # Stored-but-unused — see SetResetIfInterrupted above; same
        # ai-architecture.md sec.2 caveat applies.
        self._double_check_all_done = bool(v)

    def SetSkipDormant(self, v) -> None:      self._skip_dormant = bool(v)


def SequenceAI_Create(pShip=None, name: str = "") -> SequenceAI:
    return SequenceAI(pShip, name)


# ── RandomAI ─────────────────────────────────────────────────────────────────

class RandomAI(ArtificialIntelligence):
    """SDK App.py:5019 — sibling of PriorityListAI/SequenceAI.

    Draws children WITHOUT replacement: the C++ node keeps a per-child
    "already tried" byte array (+0x2C) and draws a new child from the
    un-tried entries, clearing the flag and re-drawing on DORMANT/DONE
    (ai-architecture.md sec.1/sec.2). Once every child has been drawn, the
    pool refills and a new cycle begins — this is what stops the same
    evasive maneuver from repeating back-to-back.
    Typically wraps several maneuver children inside a forever-looping
    SequenceAI (sdk/.../AI/Compound/Parts/NoSensorsEvasive.py:47-52,
    sdk/.../QuickBattle/QuickBattleAI.py:51-58). Dispatch lives in
    ai_driver._tick_random."""

    def __init__(self, pShip=None, name: str = ""):
        super().__init__(pShip, name)
        self._ais: list = []
        # The child currently being ticked; re-picked when it reaches DONE.
        self._current_child = None
        # Children not yet drawn this cycle. The C++ node keeps this as an
        # "already tried" byte array (+0x2C) and draws only from the un-tried
        # entries, refilling when they run out — so every maneuver runs before any
        # repeats (ai-architecture.md sec.1/sec.2).
        self._untried: list = []

    def AddAI(self, ai) -> None:
        """SDK Appc.RandomAI_AddAI — append a child AI."""
        self._ais.append(ai)
        self._untried.append(ai)

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
            # GetPreprocessingInstance returns what they constructed…
            #
            # …unless the engine has an optimized version of it. Appc's
            # SetContainedAI runs the node through GetOptimizedVersion (vtable
            # +0x34) and stores what comes BACK, swapping Python preprocessors
            # for compiled C++ ones and deleting the Python-backed node. We do
            # the equivalent at bind time, by class name. Critically this
            # replaces the SDK's ManagePower, whose `# Unused. return PS_DONE`
            # body never runs in the shipped game and would otherwise delete the
            # ship's whole AI (PS_DONE -> US_DONE). See engine/appc/ai_optimized.py.
            from engine.appc.ai_optimized import optimized_version_of
            instance = optimized_version_of(args[0])
            self._preprocessing_instance = instance
            self._preprocessing_method = args[1]
            # SDK preprocessor classes (SelectTarget, FireScript) call
            # self.pCodeAI.GetShip()/GetAllAIsInTree() throughout their
            # Update bodies. The C++ optimized engine wires pCodeAI when
            # SetPreprocessingMethod runs; Phase 1 has no optimization,
            # so we wire it here. Slice B test fixtures set this
            # explicitly; NonFedAttack/FedAttack SDK CreateAI doesn't.
            # Bound onto the REPLACEMENT, never the discarded original.
            try:
                instance.pCodeAI = self
            except (AttributeError, TypeError):
                # Instance refuses attribute assignment (e.g. slotted
                # class); skip — caller is responsible.
                pass
            # Appc's SetPreprocessingMethod calls the instance's CodeAISet()
            # hook once pCodeAI is bound (ai-architecture.md sec.4,
            # 0x0048e400). Four shipped preprocessors define a real one:
            # FireScript (registers the SetTarget external function),
            # UpdateAIStatus (registers QueryAIStatus), UseShipTarget
            # (installs the target-changed handler) and the
            # ChainFollowThroughWarp / TractorDockTargets compounds.
            # SelectTarget's is commented out in the SDK because the native
            # OptimizedSelectTarget ctor did that work — ai_driver's
            # _ensure_select_target_initialized still stands in for the C++
            # class.
            #
            # NOT wrapped in try/except. This call IS the whole payoff of the
            # CodeAISet wiring — UpdateAIStatus, TractorDockTargets,
            # ChainFollowThroughWarp and UseShipTarget all run their engine-side
            # registration here for the FIRST TIME. A swallow would let the
            # feature silently do nothing while the suite stayed green
            # (dev_mode.log_swallowed is a no-op without --developer, which is
            # never on under pytest). Same call as ShipClass.SetTarget's AddEvent:
            # let it propagate.
            code_ai_set = getattr(instance, "CodeAISet", None)
            if callable(code_ai_set):
                code_ai_set()

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
        # Appc's ConditionalAI drives SetActive/SetInactive across its
        # condition list from the NODE's own tree-activation lifecycle (see
        # _on_activated/_on_deactivated below), not at wiring time. A
        # condition added to a node that isn't active in the tree yet must
        # stay inactive until the node itself activates; a condition added
        # to an already-active node (late add on a live branch) activates
        # immediately so it isn't left stranded.
        if self._is_active_in_tree:
            cond.SetActive()

    def GetConditions(self) -> list:
        return list(self._conditions)

    # ── Tree activation lifecycle (drives the condition list) ──────────────
    # ai-architecture.md Sec.6: ConditionalAI's only confirmed C++ overrides
    # are SetActive/SetInactive/LostFocus, "all of which register/unregister
    # against the condition list". SetActive is what reaches
    # ConditionTimer.Activate() and re-arms it -- but only when the AI
    # driver actually calls it on node (re)activation (see ai_driver.py
    # _reconcile_active), not once at AddCondition time.
    def _on_activated(self) -> None:
        for cond in self._conditions:
            cond.SetActive()

    def _on_deactivated(self) -> None:
        for cond in self._conditions:
            cond.SetInactive()


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
        # Skip (Backspace) bookkeeping — see _queue_say_line / Skip.
        self._skipped: bool = False
        self._turn_owed = None      # detail of a turn-back this action still owes
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
        # Camera framing (AT_WATCH_ME / AT_LOOK_AT_ME[_NOW]) aims the captain's-eye
        # bridge camera AT this character; AT_STOP_WATCHING_ME releases it. All
        # complete inline — the camera eases underneath while the scene proceeds.
        if at in (self.AT_WATCH_ME, self.AT_LOOK_AT_ME, self.AT_LOOK_AT_ME_NOW):
            self._set_camera_watch(snap=(at == self.AT_LOOK_AT_ME_NOW))
            self.Completed()
            return
        if at == self.AT_STOP_WATCHING_ME:
            self._clear_camera_watch()
            self.Completed()
            return
        if at in (self.AT_TURN, self.AT_TURN_NOW,
                  self.AT_TURN_BACK, self.AT_TURN_BACK_NOW):
            self._queue_turn(
                back=at in (self.AT_TURN_BACK, self.AT_TURN_BACK_NOW),
                now=at in (self.AT_TURN_NOW, self.AT_TURN_BACK_NOW))
            return
        if at in (self.AT_GLANCE_AT, self.AT_GLANCE_AWAY):
            self._queue_glance()
            return
        if at in (self.AT_MENU_UP, self.AT_MENU_DOWN):
            self._menu_action(up=(at == self.AT_MENU_UP))
            return
        if at in (self.AT_PLAY_ANIMATION, self.AT_PLAY_ANIMATION_FILE):
            self._queue_play_animation(from_file=(at == self.AT_PLAY_ANIMATION_FILE))
            return
        if at in (self.AT_DEFAULT, self.AT_BREATHE, self.AT_FORCE_BREATHE):
            self._queue_default()
            return
        if at in (self.AT_SAY_LINE, self.AT_SAY_LINE_AFTER_TURN):
            self._queue_say_line()
            return
        # Speak types (and the remaining no-op types) keep the prior flow.
        dur = self._do_play()
        self._complete_after(dur or 0.0)

    def _queue_move(self) -> None:
        """Play the SDK's registered move builder, exactly as BC does.

        The builder's TGSequence carries everything: the walk clip, the
        LiftDoorAction at its scheduled offset (with the door sound), the trailing
        AT_SET_LOCATION_NAME, and the CS_STANDING / CS_SEATED / CS_HIDDEN completion
        event. Mining a single clip out of it — the old capture_move path — dropped
        the door, the sound and the events on the floor.

        Best-effort throughout: an unresolved builder, a missing controller (headless)
        or any exception completes the action inline, so a mission TGSequence can
        never stall on a move.
        """
        from engine.appc import bridge_placement
        from engine.appc.characters import CharacterClass_Cast
        try:
            cc = CharacterClass_Cast(self._character) if self._character is not None else None
            seq = (bridge_placement._resolve_builder_sequence(cc, "To" + str(self._detail))
                   if cc is not None else None)
            if seq is None:
                self.Completed()          # nothing registered → advance immediately
                return

            walk = bridge_placement.walk_action_of(seq)
            if walk is not None:
                walk._walk_move = True    # the ONE action that plays as a body clip

            # Defer our completion to the sequence's, via the SDK's own route:
            # TGActionManager.ProcessEvent calls owner.Completed() for an
            # ET_ACTION_COMPLETED whose ObjPtr is the owner (actions.py:730) —
            # the same mechanism ViewscreenOn and PlayDialog use.
            import App
            ev = App.TGObjPtrEvent_Create()
            ev.SetEventType(App.ET_ACTION_COMPLETED)
            ev.SetDestination(App.g_kTGActionManager)
            ev.SetObjPtr(self)
            seq.AddCompletedEvent(ev)

            seq.Play()
        except Exception:
            self.Completed()

    def _queue_turn(self, *, back: bool, now: bool) -> None:
        # Turn (AT_TURN/AT_TURN_BACK, + _NOW) — routes through the
        # CharacterClass door (TurnTowards/TurnBack), which owns the
        # AnimRec queue and the completion guarantee: self.Completed fires
        # exactly once, either via the record when it plays/settles or drops,
        # or inline on TurnTowards's Captain-only no-op path. Best-effort:
        # Play() must never raise — any failure completes inline so the
        # mission TGSequence advances instead of stalling.
        from engine.appc.characters import CharacterClass_Cast
        try:
            cc = CharacterClass_Cast(self._character) if self._character is not None else None
            if cc is None:
                self.Completed()
                return
            if back:
                cc.TurnBack(now=now, on_complete=self.Completed)
            else:
                detail = str(self._detail) if self._detail is not None else "Captain"
                cc.TurnTowards(detail, now=now, on_complete=self.Completed)
        except Exception:
            self.Completed()

    def _queue_say_line(self) -> None:
        """AT_SAY_LINE / AT_SAY_LINE_AFTER_TURN — the SDK's workhorse (3977 sites).

        Args 4 and 5 are turnTo / turnBack: ("Captain", 1) means turn to the
        captain, speak, and turn back — with the chair swivelling under the
        officer, because the SDK's turn builder animates the body clip and the
        chair clip as parallel siblings of one sequence. (None, 0) speaks with no
        turn at all.

        GROUND TRUTH (Ghidra, retail stbc.exe 1.1 — docs/gameplay/
        bridge-character-system.md §8.3). Both verbs route CharacterAction::Play
        -> CharacterClass::SayLine -> a builder that assembles an inner
        TGSequence of prerequisite-chained sub-actions, EVERY DELAY 0:

            TURN(turnTo) -> SPEAK_LINE(lineID) -> TURN_BACK (if the flag is set)

        The two dispatch cases are byte-identical except one immediate — the
        opening turn's sub-type:

          AT_SAY_LINE (12)            opening turn = AT_TURN_NOW: starts the
                                      animated turn and SELF-COMPLETES at once,
                                      so the line begins while the officer is
                                      still visibly turning (overlap, not a snap).
          AT_SAY_LINE_AFTER_TURN (13) opening turn = AT_TURN: awaited; the line
                                      starts when the turn animation settles.

        The turn-back is chained on the SPEAK action's completion (sound-done),
        and is itself fire-and-forget: it self-completes as soon as it STARTS the
        swivel. So this CharacterAction completes at END-OF-LINE for BOTH verbs,
        and the next action in the outer TGSequence begins with the turn-back
        playing out underneath it. (We previously serialised turn -> speak ->
        awaited turn-back, adding both animation durations to ~1600 turned
        lines — dialogue dragged.)

        The line still BLOCKS the sequence for its real duration (BC does), via
        the existing _do_play/_complete_after path.

        Skip (Backspace) interlock: `_turn_owed` records the turn-back this
        action still owes the officer, so Skip() can perform it even though it
        cancels the deferred timer that would otherwise have run _turn_back_now.
        `_skipped` makes a deferred _speak a no-op if the controller settles an
        AFTER_TURN forward turn after the skip — the player skipped this line, so
        it must not belatedly speak or complete a second time.
        """
        from engine.appc.characters import CharacterClass_Cast
        from engine import bridge_character_anim

        turn_to = self._set_name
        turn_back = self._flag > 0
        after_turn = self._action_type == self.AT_SAY_LINE_AFTER_TURN
        self._turn_owed = str(turn_to) if (turn_to and turn_back) else None
        spoke = []                       # one-shot latch: _speak runs exactly once

        def _speak():
            if self._skipped or spoke:
                return                   # skipped mid-turn: never speak it now
            spoke.append(True)
            dur = 0.0
            try:
                dur = self._do_play() or 0.0
            except Exception:
                dur = 0.0
            try:
                if not (turn_to and turn_back):
                    self._complete_after(dur)
                    return

                def _turn_back_now():
                    # End of line: START the turn-back and complete NOW. BC's
                    # TurnBack sub-action self-completes on starting the swivel —
                    # the sequence must not wait for it.
                    self._turn_owed = None       # this path is discharging it
                    self._issue_turn_back(turn_to)
                    self.Completed()
                self._complete_after(dur, on_elapsed=_turn_back_now)
            except Exception:
                # `spoke` is already latched above, so this except is the
                # ONLY remaining path to Completed() if _complete_after (or,
                # for dur<=0, the on_elapsed it runs inline) raises -- e.g.
                # the realtime timer manager was torn down mid mission-swap.
                # Without this, the action is left _playing with no timer
                # scheduled and the owning TGSequence stalls forever. Guard
                # on _playing so we never double-fire Completed() if it had
                # already run (and set _playing False) before raising partway
                # through its own completed-event dispatch.
                if self._playing:
                    self.Completed()

        if not turn_to:
            _speak()
            return
        try:
            cc = CharacterClass_Cast(self._character) if self._character is not None else None
            ctrl = bridge_character_anim.get_controller()
            if cc is None or ctrl is None:
                _speak()                     # headless: speak without turning
                return
            if after_turn:
                # AT_TURN: awaited — the line waits for the turn to settle.
                ctrl.request_turn_to(cc, str(turn_to), back=False, now=False,
                                     on_complete=_speak)
            else:
                # AT_TURN_NOW: the turn animates, but is not awaited — the line
                # starts essentially at turn start.
                ctrl.request_turn_to(cc, str(turn_to), back=False, now=True,
                                     on_complete=None)
                _speak()
        except Exception:
            _speak()

    def _queue_glance(self) -> None:
        # Quick glance (AT_GLANCE_AT/AWAY) — routes through the CharacterClass
        # door (GlanceAt/GlanceAway), which owns the AnimRec queue and the
        # completion guarantee: self.Completed fires exactly once, either via
        # the record when it plays/settles/is retired by the queue drain, or
        # inline on the no-op path. Best-effort: Play() must never raise — any
        # failure completes inline so the mission TGSequence advances instead
        # of stalling.
        from engine.appc.characters import CharacterClass_Cast
        try:
            cc = CharacterClass_Cast(self._character) if self._character is not None else None
            if cc is None:
                self.Completed()
                return
            if self._action_type == self.AT_GLANCE_AT:
                detail = str(self._detail)
                if not cc.GlanceAt(detail, on_complete=self.Completed):
                    self.Completed()
            else:
                if not cc.GlanceAway(on_complete=self.Completed):
                    self.Completed()
        except Exception:
            self.Completed()

    def _queue_play_animation(self, *, from_file: bool) -> None:
        """AT_PLAY_ANIMATION / AT_PLAY_ANIMATION_FILE — routes through the
        CharacterClass door (PlayAnimation/PlayAnimationFile), which owns clip
        resolution, the AnimRec queue, and the completion guarantee:
        self.Completed fires exactly once, either via the record when it
        plays/settles/is retired by the queue drain, or inline on the no-op
        path (unresolved key/clip, no character). Best-effort: Play() must
        never raise — any failure completes inline so the mission TGSequence
        advances instead of stalling.
        """
        from engine.appc.characters import CharacterClass_Cast
        try:
            cc = CharacterClass_Cast(self._character) if self._character is not None else None
            if cc is None:
                self.Completed()
                return
            if self._detail is None:
                self.Completed()   # BC no-ops an unresolved gesture
                return
            name = str(self._detail)
            if from_file:
                ok = cc.PlayAnimationFile(name, self._flag, on_complete=self.Completed)
            else:
                ok = cc.PlayAnimation(name, self._flag, on_complete=self.Completed)
            if not ok:
                # No-op path (unresolved key/clip): PlayAnimation[File] returns
                # 0 WITHOUT firing on_complete, so complete inline. When it
                # returns 1 the record carries on_complete and fires exactly
                # once via the queue drain — do not also complete inline here
                # (that would double-fire).
                self.Completed()
        except Exception:
            self.Completed()

    def _queue_default(self) -> None:
        """AT_DEFAULT / AT_BREATHE / AT_FORCE_BREATHE — return the officer to rest,
        re-pointed (SP2 P4) through the CharacterClass door. The three verbs no
        longer share one uniform path:

        - AT_BREATHE routes through the idle-gated `cc.Breathe(on_complete=
          self.Completed)` door: BC appends AT_BREATHE at the END of gesture
          sequences (LargeAnimations/SmallAnimations/MediumAnimations) to return
          an ALREADY-IDLE officer to the breathing idle. Breathe() enqueues a
          CAT_BREATHE record whose on_complete fires exactly once via the queue
          drain when it returns 1; on its no-op path (officer still animating /
          has a pending move or glance target) it returns 0 WITHOUT firing
          on_complete, so we complete inline ourselves.

        - AT_DEFAULT / AT_FORCE_BREATHE are grouped as "force the officer back
          to rest": drain the interruptable queue via `cc.ClearExtraAnimations()`,
          then restore the rest pose via the clip-player seam
          (`ctrl.request_default(cc)`), then complete INLINE — restoring a pose
          is instant, and sequences supply their own delays. AT_FORCE_BREATHE is
          grouped here rather than with the idle-gated Breathe() because "force"
          must act even when the officer is mid-gesture (Breathe would no-op).

        Ordering note (re-entrancy, AT_DEFAULT/AT_FORCE_BREATHE path only):
        request_default() fires a dropped controller _Action's on_complete
        SYNCHRONOUSLY (see BridgeCharacterAnimController.request_default), and
        event dispatch is synchronous, so that callback can advance the owning
        TGSequence and submit a brand-new gesture on this SAME officer —
        including a fresh cc.SetCurrentAnimation() call — before
        request_default() returns. We therefore call ClearExtraAnimations()
        BEFORE request_default(), not after: clearing first means any
        re-entrant enqueue lands on a clean queue and is never wiped by a clear
        that runs afterward.

        Best-effort throughout: Play() must never raise. `cc is None` completes
        inline; any exception completes inline. self.Completed() fires exactly
        once on every path.
        """
        from engine.appc.characters import CharacterClass_Cast
        from engine import bridge_character_anim
        try:
            cc = CharacterClass_Cast(self._character) if self._character is not None else None
            if cc is None:
                self.Completed()
                return
            if self._action_type == self.AT_BREATHE:
                if not cc.Breathe(on_complete=self.Completed):
                    self.Completed()
                return
            # AT_DEFAULT / AT_FORCE_BREATHE: force-to-rest.
            cc.ClearExtraAnimations()
            ctrl = bridge_character_anim.get_controller()
            if ctrl is not None:
                ctrl.request_default(cc)
            self.Completed()
        except Exception:
            self.Completed()

    def _menu_action(self, *, up: bool) -> None:
        # AT_MENU_UP/AT_MENU_DOWN are the sequenceable wrappers around BC's
        # CharacterClass.MenuUp()/MenuDown() (E1M1 crew-intro raises Brex's menu
        # then points the tutorial cursor at its buttons; E8M2 raises Liu's).
        # Completes INLINE — raising/lowering a menu is instant; sequences supply
        # their own delays. No acknowledgement: BC plays "Yes sir" in
        # CharacterInteraction on the CLICK path only, so a scripted menu-up must
        # stay silent. Best-effort: Play() must never raise.
        from engine.appc.characters import CharacterClass_Cast
        try:
            cc = CharacterClass_Cast(self._character) if self._character is not None else None
            if cc is not None:
                if up:
                    cc.MenuUp()
                else:
                    cc.MenuDown()
        except Exception:
            pass
        self.Completed()

    def _set_camera_watch(self, *, snap: bool) -> None:
        # Frame this character with the captain's-eye camera (AT_WATCH_ME /
        # AT_LOOK_AT_ME[_NOW]). Best-effort: never raises out of Play().
        from engine.appc.characters import CharacterClass_Cast
        from engine import bridge_camera_watch
        try:
            cc = CharacterClass_Cast(self._character) if self._character is not None else None
            ctrl = bridge_camera_watch.get_controller()
            if cc is not None and ctrl is not None:
                ctrl.watch(cc, snap=snap)
        except Exception:
            pass

    def _clear_camera_watch(self) -> None:
        from engine import bridge_camera_watch
        try:
            ctrl = bridge_camera_watch.get_controller()
            if ctrl is not None:
                ctrl.clear()
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
        # Skipping a turned AT_SAY_LINE must still turn the officer back.
        # TGAction.Skip cancels the deferred timer, and with it the pending
        # _turn_back_now — the forward turn was hold=True, so the officer AND
        # his chair would otherwise stay swivelled at the captain for the rest
        # of the scene. Issue the turn-back HERE (fire-and-forget: no
        # on_complete, because Skip must complete this action NOW so dependents
        # advance immediately — that is TGAction::Skip's contract).
        #
        # Order matters: set _skipped BEFORE requesting the turn. A skip that
        # lands while the FORWARD turn is still in flight evicts it inside
        # _process_turn, which synchronously rescues and fires its on_complete
        # (_speak, installed as AT_SAY_LINE_AFTER_TURN's awaited on_complete) —
        # and that callback checks _skipped so the skipped line neither speaks
        # nor completes a second time.
        self._skipped = True
        turn_to, self._turn_owed = self._turn_owed, None
        if turn_to:
            self._issue_turn_back(turn_to)
        super().Skip()

    def _issue_turn_back(self, detail) -> None:
        """BC's TurnBack sub-action: START the reverse swivel and do not await it
        (it self-completes on starting the animation), so the caller owns — and
        may immediately fire — this action's completion. Used both at end-of-line
        and on Skip(). Best-effort; never raises (Skip() must not throw into the
        action manager, and Play() must never stall a mission TGSequence)."""
        from engine.appc.characters import CharacterClass_Cast
        from engine import bridge_character_anim
        try:
            cc = CharacterClass_Cast(self._character) if self._character is not None else None
            ctrl = bridge_character_anim.get_controller()
            if cc is not None and ctrl is not None:
                ctrl.request_turn_to(cc, str(detail), back=True, now=True,
                                     on_complete=None)
        except Exception:
            pass


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


def CharacterAction_Cast(obj) -> "CharacterAction | None":
    """SDK pattern: ``App.CharacterAction_Cast(pAction)`` — RTTI test-and-cast
    (stbc.exe 0x0066f890).  Returns obj if it's a CharacterAction, else None.
    MissionLib.GetVoiceLinesFromSequence walks sequences with exactly this
    idiom (cast, then GetActionType/GetDetail)."""
    return obj if isinstance(obj, CharacterAction) else None


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
