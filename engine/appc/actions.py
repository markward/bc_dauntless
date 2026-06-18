"""
Action and sequence system for the headless engine.

Execution model: event-driven.  An action completes inline when its Play()
returns (instantaneous actions) or later (TGConditionAction waits for a
condition to flip).  TGSequence honors per-step delays and completion
dependencies: a step fires when its dependency completes, plus its declared
delay measured via the game-time g_kTimerManager.  Because the event bus
(g_kEventManager.AddEvent) dispatches inline, zero-delay dependency chains
still resolve fully synchronously within the launching Play() call; only real
delays or deferred completions span frames.  See
docs/superpowers/specs/2026-06-11-action-sequence-timing-design.md.
"""
import sys
from engine.appc.events import TGEventHandlerObject, TGEvent
from engine.core.ids import get_object_by_id

# Private event types used only by the TGSequence scheduler. They are delivered
# directly to the owning sequence via event destination routing and never reach
# the SDK broadcast bus, so the values only need to be unique within a sequence's
# ProcessEvent. Kept well outside the SDK's ET_* ranges (100s/200s).
_ET_SEQ_STEP_COMPLETED = 0x5E01   # a tracked action finished -> advance dependents
_ET_SEQ_TIMER_FIRED    = 0x5E02   # a delay timer elapsed -> launch the pending step
_ET_ACTION_DEFERRED_COMPLETE = 0x5E03  # realtime timer elapsed -> self.Completed()


class TGAction(TGEventHandlerObject):
    def __init__(self):
        super().__init__()
        self._completed_events: list[TGEvent] = []
        self._playing: bool = False
        self._deferred_timer = None   # (manager, TGTimer) while a deferral is pending

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

    def _complete_after(self, duration_real_s) -> None:
        """Complete this action after duration_real_s wall-clock seconds via
        g_kRealtimeTimerManager. duration <= 0 (or None) completes inline,
        preserving synchronous behavior when there is no audio to wait on."""
        if not duration_real_s or duration_real_s <= 0:
            self.Completed()
            return
        import App
        mgr = App.g_kRealtimeTimerManager
        timer = App.TGTimer_Create()
        timer.SetTimerStart(mgr.get_time() + float(duration_real_s))
        timer.SetDelay(-1.0)            # one-shot
        ev = App.TGEvent_Create()
        ev.SetEventType(_ET_ACTION_DEFERRED_COMPLETE)
        ev.SetDestination(self)
        timer.SetEvent(ev)
        mgr.AddTimer(timer)
        self._deferred_timer = (mgr, timer)

    def _cancel_deferred_timer(self) -> None:
        rec = self._deferred_timer
        if rec is not None:
            mgr, timer = rec
            mgr.RemoveTimer(timer)
            self._deferred_timer = None

    def Play(self) -> None:
        self._playing = True
        self._do_play()
        self.Completed()

    def _do_play(self) -> None:
        pass

    def ProcessEvent(self, event) -> None:
        if event.GetEventType() == _ET_ACTION_DEFERRED_COMPLETE:
            self._deferred_timer = None
            self.Completed()
            return
        super().ProcessEvent(event)

    def Abort(self) -> None:
        self._playing = False
        self._cancel_deferred_timer()

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
        self._deferred = False

    def Play(self) -> None:
        self._playing = True
        self._deferred = False
        self._do_play()
        if not self._deferred:
            self.Completed()

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
                # SDK convention: a script-action function returns falsy/None
                # ("Return: 0 - Action completed") => auto-complete; truthy
                # (e.g. ViewscreenOn/PlayDialog return 1) => the function wired
                # a deferred completion, so we must NOT auto-complete here.
                ret = fn(self, *self._args)
                if ret:
                    self._deferred = True
        finally:
            _script_action_depth[key] -= 1


def TGScriptAction_Create(module_name: str, func_name: str, *args) -> TGScriptAction:
    return TGScriptAction(module_name, func_name, *args)


class _Step:
    """One scheduled action within a TGSequence.

    `dependency` None means the step is a root (fires at sequence start).
    `delay` is seconds measured from the dependency's completion.
    """
    __slots__ = ("action", "dependency", "delay", "started")

    def __init__(self, action, dependency, delay):
        self.action = action
        self.dependency = dependency
        self.delay = float(delay)
        self.started = False


def _parse_extra(extra):
    """Resolve TGSequence AddAction/AppendAction *extra args by type:
    a TGAction is the dependency; a number is the delay (seconds).
    Returns (dependency_or_None, delay_float)."""
    dependency = None
    delay = 0.0
    for arg in extra:
        if isinstance(arg, TGAction):
            dependency = arg
        elif isinstance(arg, (int, float)):
            delay = float(arg)
    return dependency, delay


class TGSequence(TGAction):
    def __init__(self):
        super().__init__()
        self._steps: list[_Step] = []
        self._verb: str = "Play"
        self._completed_actions: set[int] = set()
        self._pending_timers: list = []   # (manager, _Step, TGTimer)

    def AddAction(self, action: TGAction, *extra) -> None:
        """Add a parallel/explicit-dependency step. With no extra args the
        action is a root (fires at sequence start)."""
        dependency, delay = _parse_extra(extra)
        self._steps.append(_Step(action, dependency, delay))

    def AppendAction(self, action: TGAction, *extra) -> None:
        """Append a step chained to the previously added action. An explicit
        dependency arg overrides the implicit chain; a numeric arg is the delay."""
        dependency, delay = _parse_extra(extra)
        if dependency is None and self._steps:
            dependency = self._steps[-1].action
        self._steps.append(_Step(action, dependency, delay))

    def GetNumActions(self) -> int:
        return len(self._steps)

    def GetAction(self, index: int) -> "TGAction | None":
        if 0 <= index < len(self._steps):
            return self._steps[index].action
        return None

    # ── launch ──────────────────────────────────────────────────────────────
    def Play(self) -> None:
        self._launch("Play")

    def Start(self) -> None:
        """Particle-effect entry point: launch children with Start() where
        available (plain actions and sub-sequences fall back to Play())."""
        self._launch("Start")

    def _launch(self, verb: str) -> None:
        self._playing = True
        self._verb = verb
        self._completed_actions = set()
        self._pending_timers = []
        for step in self._steps:
            step.started = False

        # Subscribe to completion of every member action and every dependency
        # (including the throwaway-null idiom used to anchor a delay at t=0).
        tracked = {}
        for step in self._steps:
            tracked[id(step.action)] = step.action
            if step.dependency is not None:
                tracked[id(step.dependency)] = step.dependency
        for action in tracked.values():
            self._subscribe_completion(action)

        # Play non-member dependencies now so they complete at sequence start
        # and anchor their dependents' delays at t=0.
        member_ids = {id(s.action) for s in self._steps}
        for action in list(tracked.values()):
            if id(action) not in member_ids:
                self._fire(action)

        # Fire all root steps (no dependency) immediately.
        for step in self._steps:
            if step.dependency is None:
                self._begin_step(step)

        self._maybe_complete()

    def _subscribe_completion(self, action) -> None:
        # Fire-and-forget actions (e.g. the headless EffectAction) have no
        # completion-event support; they are treated as completing on launch
        # (see _fire), so there is nothing to subscribe to here.
        if not hasattr(action, "AddCompletedEvent"):
            return
        ev = TGObjPtrEvent()
        ev.SetEventType(_ET_SEQ_STEP_COMPLETED)
        ev.SetDestination(self)
        ev.SetObjPtr(action)
        action.AddCompletedEvent(ev)

    @staticmethod
    def _has_real_start(action) -> bool:
        """Return True if the action has a genuine Start() method (not a
        TGObject.__getattr__ _Stub).  We must check via the MRO rather than
        hasattr() because TGObject.__getattr__ returns a _Stub for every
        attribute name, so hasattr always returns True regardless of whether
        Start is actually implemented."""
        for cls in type(action).__mro__:
            if "Start" in cls.__dict__:
                return True
        return False

    def _fire(self, action) -> None:
        """Launch an action using the sequence's verb, mirroring the legacy
        Start() routing (Start for non-sequence actions that support it)."""
        if (self._verb == "Start" and self._has_real_start(action)
                and not isinstance(action, TGSequence)):
            action.Start()
        else:
            action.Play()
        # Actions without completion-event support never post
        # _ET_SEQ_STEP_COMPLETED, so treat them as completing the instant they
        # launch — otherwise dependents and the sequence's own completion would
        # hang waiting on an event that never arrives.
        if not hasattr(action, "AddCompletedEvent"):
            self._on_dependency_complete(action)

    def _begin_step(self, step: "_Step") -> None:
        if step.started:
            return
        step.started = True
        if step.delay <= 0:
            self._fire(step.action)
        else:
            self._schedule_timer(step)

    # ── event routing ───────────────────────────────────────────────────────
    def ProcessEvent(self, event) -> None:
        et = event.GetEventType()
        if et == _ET_SEQ_STEP_COMPLETED:
            self._on_dependency_complete(event.GetObjPtr())
            return
        if et == _ET_SEQ_TIMER_FIRED:
            self._on_timer_fired(event.GetObjPtr())
            return
        super().ProcessEvent(event)

    def _on_dependency_complete(self, action) -> None:
        self._completed_actions.add(id(action))
        for step in self._steps:
            if (not step.started and step.dependency is not None
                    and step.dependency is action):
                self._begin_step(step)
        self._maybe_complete()

    def _on_timer_fired(self, step) -> None:
        self._pending_timers = [
            rec for rec in self._pending_timers if rec[1] is not step
        ]
        self._fire(step.action)
        self._maybe_complete()

    # ── completion ──────────────────────────────────────────────────────────
    def _maybe_complete(self) -> None:
        if not self._playing:
            return
        if self._pending_timers:
            return
        if any(not s.started for s in self._steps):
            return
        member_ids = {id(s.action) for s in self._steps}
        if not member_ids.issubset(self._completed_actions):
            return
        self.Completed()

    def _schedule_timer(self, step: "_Step") -> None:
        import App
        use_real = bool(getattr(step.action, "IsUseRealTime",
                                lambda: False)())
        mgr = App.g_kRealtimeTimerManager if use_real else App.g_kTimerManager
        timer = App.TGTimer_Create()
        timer.SetTimerStart(mgr.get_time() + step.delay)
        timer.SetDelay(-1.0)   # one-shot: fires once, then marks itself done
        ev = TGObjPtrEvent()
        ev.SetEventType(_ET_SEQ_TIMER_FIRED)
        ev.SetDestination(self)
        ev.SetObjPtr(step)     # timer events carry the _Step, not the action
        timer.SetEvent(ev)
        mgr.AddTimer(timer)
        self._pending_timers.append((mgr, step, timer))

    def Abort(self) -> None:
        for mgr, _step, timer in self._pending_timers:
            mgr.RemoveTimer(timer)
        self._pending_timers = []
        self._playing = False

    def Stop(self) -> None:
        for mgr, _step, timer in self._pending_timers:
            mgr.RemoveTimer(timer)
        self._pending_timers = []
        for step in self._steps:
            action = step.action
            if hasattr(action, "Stop") and not isinstance(action, TGSequence):
                action.Stop()
            else:
                action.Abort()
        self._playing = False


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
        # Override (not _do_play) so completion is gated on the sound's real
        # wall-clock length: a sequence step chained after this action advances
        # only when the audio actually finishes. Zero duration (no backend /
        # unloaded) completes inline, preserving synchronous behavior.
        self._playing = True
        self._do_play()
        from engine.audio.tg_sound import TGSoundManager
        dur = TGSoundManager.instance().duration_for(self._sound_name)
        self._complete_after(dur)

    def _do_play(self) -> None:
        # Late import: tg_sound pulls in the native audio extension; keep this
        # module light at startup since actions is loaded very early via App.py.
        # Overriding _do_play (not Play) means the base TGAction.Play() runs the
        # standard lifecycle and calls Completed() — so a sequence step chained
        # after this sound action advances instead of hanging forever.
        from engine.audio.tg_sound import TGSoundManager
        TGSoundManager.instance().PlaySound(self._sound_name)


def TGSoundAction_Create(*args) -> TGSoundAction:
    """Accept (sound_name,) or (sound_name, flags, ...) — extra args are renderer hints ignored in Phase 1."""
    sound_name = args[0] if args and isinstance(args[0], str) else ""
    return TGSoundAction(sound_name)


class TGAnimAction(TGAction):
    """Plays a named clip on a target's anim node.

    Camera (kind="camera") and bridge-object (kind="object") anim nodes route
    to the BridgeCutsceneController, which drives playback host-side and
    completes the action when the clip ends (deferred). Every other target
    (character gesture clips via a _NodeStub node, or no controller
    registered) keeps the Phase-1 instant-complete behaviour.
    """
    def __init__(self, anim_node=None, clip_name=""):
        super().__init__()
        self._anim_node = anim_node
        self._clip = str(clip_name)
        self._deferred = False

    def Play(self) -> None:
        self._playing = True
        self._deferred = False
        self._do_play()
        if not self._deferred:
            self.Completed()

    def _do_play(self) -> None:
        kind = getattr(self._anim_node, "kind", None)
        if kind not in ("camera", "object"):
            return
        from engine.bridge_cutscene import get_controller
        ctrl = get_controller()
        if ctrl is None:
            return
        if kind == "camera":
            ctrl.request_camera_path(self, self._anim_node, self._clip)
        else:
            ctrl.request_object_anim(self, self._anim_node, self._clip)
        self._deferred = True


def TGAnimAction_Create(*args) -> TGAnimAction:
    # SDK call shape: App.TGAnimAction_Create(pAnimNode, "ClipName", flags...).
    anim_node = args[0] if len(args) >= 1 else None
    clip_name = args[1] if len(args) >= 2 and isinstance(args[1], str) else ""
    return TGAnimAction(anim_node, clip_name)


class TGAnimPosition(TGAction):
    """Placement action created by Bridge.Characters.CommonAnimations.SetPosition.

    The SDK builds these via App.TGAnimPosition_Create(animNode, clipName) and
    appends them to a TGSequence to move a character's anim node to the position
    baked into the named clip's keyframes. Headless we never play it — we only
    record the clip NAME so the host can resolve it to a NIF path via
    g_kAnimationManager.path_for and feed it to the skinned renderer.
    """
    def __init__(self, name: str = ""):
        super().__init__()
        self.name = str(name)


def TGAnimPosition_Create(anim_node=None, name: str = "") -> TGAnimPosition:
    # SDK call shape: App.TGAnimPosition_Create(pAnimNode, "db_stand_t_l").
    # The anim node is irrelevant headless; keep only the clip name.
    return TGAnimPosition(name)


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

    def ProcessEvent(self, event) -> None:
        # SDK manager-ObjPtr deferred-completion pattern: ViewscreenOn /
        # ViewscreenOff / PlayDialog wire a leaf action's completion to post
        # ET_ACTION_COMPLETED here with the OWNER action as the ObjPtr. Route it
        # to the owner so the sequence step gated on the owner advances.
        import App
        if event.GetEventType() == App.ET_ACTION_COMPLETED:
            owner = event.GetObjPtr() if isinstance(event, TGObjPtrEvent) else None
            if owner is not None and hasattr(owner, "Completed"):
                owner.Completed()
                return
        super().ProcessEvent(event)


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

    _DEFAULT_DURATION_S = 3.0  # matches MissionLib.TextBanner default (fDuration=3.0)

    def __init__(self, *args):
        super().__init__()
        # SDK constructor is variadic — common forms:
        #   (text, subtitle_window, x, y, duration, fade_in, fade_out, font_size, jx, jy)
        #   (text, subtitle_window) — for short banners
        self._args = args
        self._text = args[0] if args else ""
        self._subtitle = args[1] if len(args) > 1 else None
        self._duration_s = float(args[4]) if len(args) > 4 else self._DEFAULT_DURATION_S
        self._color = _credit_default_color
        self._played = False

    def SetColor(self, r: float, g: float, b: float, a: float = 1.0) -> None:
        self._color = (float(r), float(g), float(b), float(a))

    def _do_play(self) -> None:
        # Overriding _do_play (not Play) lets the base TGAction.Play() call
        # Completed(), so a sequence step chained after this credit action
        # advances. The _played guard keeps the *visible* text idempotent when a
        # sequence re-fires Play on the same action; Completed() itself is
        # idempotent (it clears _completed_events after the first dispatch).
        if self._played: return
        self._played = True
        host = self._subtitle
        adder = getattr(host, "_add_text", None)
        if adder is None: return
        adder(self._text, self._duration_s)

    def Restart(self) -> None:
        # TGSequence.Restart() re-fires Play on every child. Reset the
        # idempotency flag so the credit action delivers its text again.
        self._played = False
        super().Restart()


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

    def Play(self) -> None:
        # Unlike the base TGAction, a condition action does NOT auto-complete:
        # it completes only when a condition is already satisfied at Play time,
        # otherwise it stays pending until ConditionChanged() flips it on a
        # later frame. This is what lets a sequence step gate on it across
        # frames (the base class's unconditional Completed() masked the gate).
        self._playing = True
        self._do_play()
        if self._state == self.TGCA_COMPLETED:
            self.Completed()


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
