"""AI tick driver — walks an AI tree top-down each frame.

Mirrors the SDK ArtificialIntelligence dispatch semantics
(sdk/Build/scripts/App.py:4922-5232):

* PlainAI         — call script_instance.Update() at GetNextUpdateTime() cadence
* PriorityListAI  — run highest-priority non-DORMANT child (lower int == higher priority)
* SequenceAI      — run current child; on US_DONE advance, loop per _loop_count
* ConditionalAI   — if SetEvaluationFunction is wired, call it with each condition's
                    status; fall back to "any condition non-zero -> ACTIVE" for callers
                    that AddCondition without registering an EvalFunc
* PreprocessingAI — invoke preprocess method, dispatch contained per PS_*

The driver is *not* TimeSliceProcess-based. PlainAI carries its own
_next_update_time field; the driver consults it each tick. This keeps
Step 3 testable independently of the TimeSliceProcess scheduler (Step 2).
"""
import inspect
import random

from engine import dev_mode
from engine.appc.ai import (
    ArtificialIntelligence, PlainAI, PriorityListAI, SequenceAI,
    ConditionalAI, PreprocessingAI, BuilderAI, RandomAI,
)

US_ACTIVE = ArtificialIntelligence.US_ACTIVE
US_DONE = ArtificialIntelligence.US_DONE
US_DORMANT = ArtificialIntelligence.US_DORMANT
PS_NORMAL = PreprocessingAI.PS_NORMAL
PS_SKIP_ACTIVE = PreprocessingAI.PS_SKIP_ACTIVE
PS_SKIP_DORMANT = PreprocessingAI.PS_SKIP_DORMANT
PS_DONE = PreprocessingAI.PS_DONE


# Focus-loss lifecycle state. tick_ai is single-threaded (one ship at a time),
# so module-level scratch is safe. _reached_this_tick collects the
# PreprocessingAI nodes reached (== focused) during the current root tick.
_focus_depth = 0
_reached_this_tick: list = []


def tick_ai(ai, game_time: float) -> int:
    """Tick one AI subtree; reconcile preprocessor focus at the root call.

    The outermost tick_ai call (one per ship, from tick_all_ai) is the root: it
    collects which PreprocessingAI nodes were reached (== on the active path ==
    focused) this tick, then dispatches LostFocus() to any node that was focused
    last tick but not this one. Recursive calls into children just dispatch."""
    global _focus_depth, _reached_this_tick
    is_root = _focus_depth == 0
    if is_root:
        _reached_this_tick = []
    _focus_depth += 1
    try:
        status = _dispatch_ai(ai, game_time)
    finally:
        _focus_depth -= 1
    if is_root and ai is not None:
        _reconcile_focus(ai, _reached_this_tick)
    return status


def _dispatch_ai(ai, game_time: float) -> int:
    """Type-dispatch one AI node (the former body of tick_ai)."""
    if ai is None:
        return US_DONE
    # Inert-coast gate: a dying/dead ship issues no new orders.
    from engine.appc import ship_death
    ship = ai.GetShip() if hasattr(ai, "GetShip") else None
    if ship is not None and ship_death._out_of_action(ship):
        return US_DONE
    if isinstance(ai, BuilderAI):
        return _tick_builder(ai, game_time)
    if isinstance(ai, PreprocessingAI):
        return _tick_preprocessing(ai, game_time)
    if isinstance(ai, ConditionalAI):
        return _tick_conditional(ai, game_time)
    if isinstance(ai, PriorityListAI):
        return _tick_priority_list(ai, game_time)
    if isinstance(ai, SequenceAI):
        return _tick_sequence(ai, game_time)
    if isinstance(ai, RandomAI):
        return _tick_random(ai, game_time)
    if isinstance(ai, PlainAI):
        return _tick_plain(ai, game_time)
    return ai._status


def _reconcile_focus(root_ai, reached) -> None:
    """Dispatch LostFocus() to preprocessors focused last tick but not this one.

    Identity-based: `reached` holds the PreprocessingAI nodes ticked this root
    tick. Any node in the root's previous focused set that is not among them has
    left the active dispatch path."""
    reached_ids = {id(n) for n in reached}
    for node in getattr(root_ai, "_focused_preprocessors", ()):
        if id(node) not in reached_ids:
            _dispatch_lost_focus(node)
    root_ai._focused_preprocessors = list(reached)


def _dispatch_lost_focus(node) -> None:
    """Call the preprocessor instance's LostFocus() (if any) and clear the
    node's focus latches so a later re-entry re-fires GotFocus()."""
    inst = getattr(node, "_preprocessing_instance", None)
    lost = getattr(inst, "LostFocus", None) if inst is not None else None
    if callable(lost):
        lost()
    node._has_focus = False
    node.__dict__["_got_focus_called"] = False


def _tick_plain(ai: PlainAI, game_time: float) -> int:
    if ai._status != US_ACTIVE:
        return ai._status
    if game_time < ai._next_update_time:
        return ai._status
    inst = ai.GetScriptInstance()
    # Script-instance Update is the per-AI heartbeat. Leaves registered
    # purely for external-function dispatch (SetTarget callbacks under a
    # SelectTarget preprocessor, e.g.) may legitimately omit it; treat a
    # missing Update as "no work this tick" so the dispatch tree still
    # ticks past them without error. Matches _AIScriptInstance's
    # everything-is-a-lambda fallback.
    update_fn = getattr(inst, "Update", None)
    if update_fn is None or not callable(update_fn):
        return ai._status
    status = update_fn()
    if status is None:
        status = US_ACTIVE
    ai._status = int(status)
    # Reschedule based on the script's reported interval. Fallback
    # _AIScriptInstance returns None for unknown Get*; treat as 1 sec.
    next_update_fn = getattr(inst, "GetNextUpdateTime", None)
    next_update = next_update_fn() if callable(next_update_fn) else None
    interval = float(next_update) if next_update is not None else 1.0
    ai._next_update_time = game_time + interval
    return ai._status


def _tick_priority_list(ai: PriorityListAI, game_time: float) -> int:
    # ai._ais is sorted lowest priority-int first (highest priority).
    # Skip both DORMANT and DONE children: DORMANT means "not eligible
    # right now" and DONE means "already finished" — neither should
    # gate lower-priority entries. Without the DONE skip, a high-prio
    # child that latches DONE on tick 1 (e.g. NonFedAttack's
    # CheckWarpBeforeDeath / WarpOutBeforeDeath, which reports DONE when
    # the ship is healthy) starves the SelectTarget combat subtree.
    for _prio, child in ai._ais:
        # Re-evaluate each ConditionalAI child's status against its
        # current condition values *before* deciding eligibility.
        # Condition scripts (ConditionInRange, etc.) update their own
        # status asynchronously from events fired by
        # evaluate_proximity_checks(); without this refresh the
        # ConditionalAI's cached _status drifts out of sync with the
        # condition, and a high-priority branch that "should now be
        # active" stays starved by a lower-priority sibling that
        # latched ACTIVE earlier. Live-game symptom: M2Objects enemy
        # entered MidRange but kept ticking LongRange, so FireAll2
        # never dispatched and no phasers fired.
        if isinstance(child, ConditionalAI):
            _refresh_conditional_status(child)
        if child._status == US_DORMANT or child._status == US_DONE:
            continue
        tick_ai(child, game_time)
        return ai._status  # one child per tick (SDK semantics)
    # All children dormant/done or list empty.
    if ai._ais and all(c._status == US_DONE for _p, c in ai._ais):
        ai._status = US_DONE
    return ai._status


def _refresh_conditional_status(ai: ConditionalAI) -> None:
    """Re-run a ConditionalAI's EvalFunc against its conditions and
    cache the result on ``ai._status`` without dispatching contained
    AI. Used by ``_tick_priority_list`` to keep conditional status
    in sync with asynchronously-updated condition values.

    Mirrors the status-derivation logic in ``_tick_conditional`` but
    stops short of recursing into the contained subtree — that recursion
    is the priority list's job once the eligible child has been picked.
    """
    eval_fn = ai._evaluation_function
    if eval_fn is not None:
        args = [c.GetStatus() for c in ai._conditions]
        try:
            status = eval_fn(*args)
        except Exception:
            status = US_DORMANT
        if status is None:
            status = US_DORMANT
        ai._status = int(status)
        return
    if not ai._conditions:
        return
    ai._status = US_ACTIVE if any(c.GetStatus() != 0 for c in ai._conditions) else US_DORMANT


def _tick_sequence(ai: SequenceAI, game_time: float) -> int:
    """Run the sequence's first eligible child, advancing past finished ones.

    Each tick: starting at the current index, refresh any ConditionalAI child's
    status (mirroring _tick_priority_list — condition scripts update
    asynchronously from proximity/timer events, so a stale cached status would
    wedge the sequence), skip US_DONE children to reach the first eligible one,
    and tick it. A US_DORMANT child *holds* the sequence in place: the SDK
    sequences in Compound.CloakAttack use SetSkipDormant(0), so a dormant
    child blocks rather than being skipped.

    Looping: SetLoopCount(-1) marks a forever-loop (Compound.CloakAttack's
    OuterSequence/Sequence, the QuickBattle maneuver loops). When the index
    walks off the end of a forever-loop we wrap to 0 and re-arm the children to
    US_ACTIVE so the sub-sequence re-runs (this is what lets the cloak/decloak
    cadence repeat rather than stalling with every child latched DONE). A
    non-looping sequence latches US_DONE when it walks off the end, as before.
    """
    if not ai._ais:
        ai._status = US_DONE
        return ai._status
    n = len(ai._ais)
    looping = int(getattr(ai, "_loop_count", 1)) < 0
    idx = getattr(ai, "_current_index", 0)

    def _wrap_or_finish(i):
        """Index walked off the end: wrap+re-arm a forever-loop, else finish.

        Returns the new index to keep scanning from, or None if the sequence
        is finished (status already set to US_DONE)."""
        if looping:
            for child in ai._ais:
                child._status = US_ACTIVE
            return 0
        ai._current_index = i
        ai._status = US_DONE
        return None

    # Bound the scan so a list of all-DONE children can't spin forever.
    for _ in range(n + 1):
        if idx >= n:
            idx = _wrap_or_finish(idx)
            if idx is None:
                return ai._status
        child = ai._ais[idx]
        if isinstance(child, ConditionalAI):
            _refresh_conditional_status(child)
        if child._status == US_DORMANT:
            ai._current_index = idx
            ai._status = US_ACTIVE
            return ai._status
        if child._status == US_DONE:
            idx += 1
            continue
        tick_ai(child, game_time)
        if child._status == US_DONE:
            idx += 1
            if idx >= n:
                idx = _wrap_or_finish(idx)
                if idx is None:
                    return ai._status
        ai._current_index = idx
        ai._status = US_ACTIVE
        return ai._status
    # Scan exhausted without an eligible child (all DONE). A forever-loop
    # re-runs from the top next tick; a finite sequence is finished.
    ai._current_index = 0
    ai._status = US_ACTIVE if looping else US_DONE
    return ai._status


def _tick_random(ai: RandomAI, game_time: float) -> int:
    """Pick one child at random and tick it; re-pick when it finishes.

    SDK semantics (docs/.../ai-architecture.md, RandomAI): "Picks one child
    at random; on completion, picks another." RandomAI is used as an
    infinite maneuver picker inside a forever-looping SequenceAI
    (sdk/.../QuickBattle/QuickBattleAI.py:51-58,
    sdk/.../AI/Compound/Parts/NoSensorsEvasive.py:47-52), so the RandomAI
    itself stays US_ACTIVE while a child runs and does NOT terminate just
    because one child reached US_DONE — it re-picks on the next tick.

    An empty RandomAI has nothing to run and completes immediately.
    """
    if not ai._ais:
        ai._status = US_DONE
        return ai._status
    child = ai._current_child
    if child is None or child._status == US_DONE:
        child = random.choice(ai._ais)
        # Reset the freshly-picked child to ACTIVE so a previously-DONE
        # child runs again (mirrors how the SDK re-arms a re-selected child).
        child._status = US_ACTIVE
        ai._current_child = child
    tick_ai(child, game_time)
    ai._status = US_ACTIVE
    return ai._status


def _tick_conditional(ai: ConditionalAI, game_time: float) -> int:
    # SDK semantics: if an EvaluationFunction is set, the conditions act as
    # arguments to it and the function returns the desired US_* status.
    # SDK Parts/*.py defines EvalFunc(bCond0, bCond1, ...) → ACTIVE/DORMANT/
    # DONE. Without an EvalFunc, fall back to "any condition non-zero ⇒
    # ACTIVE" as a coarse default (kept for synthetic tests that wire
    # AddCondition without SetEvaluationFunction).
    eval_fn = ai._evaluation_function
    if eval_fn is not None:
        args = [c.GetStatus() for c in ai._conditions]
        try:
            status = eval_fn(*args)
        except Exception:
            status = US_DORMANT
        if status is None:
            status = US_DORMANT
        ai._status = int(status)
        if ai._status == US_ACTIVE and ai._contained_ai is not None:
            tick_ai(ai._contained_ai, game_time)
        return ai._status
    active = any(c.GetStatus() != 0 for c in ai._conditions) if ai._conditions else False
    if not active:
        ai._status = US_DORMANT
        return ai._status
    ai._status = US_ACTIVE
    if ai._contained_ai is not None:
        tick_ai(ai._contained_ai, game_time)
    return ai._status


def _subsystem_belongs_to(subsystem, target) -> bool:
    """True if `subsystem` sits on `target`'s ship. In production, attached
    subsystems know their owning ship (directly via GetParentShip, or by
    climbing the parent-subsystem chain for children like torpedo tubes). A
    membership fallback covers top-level subsystems assigned without a
    parent-ship back-link."""
    owner = subsystem.GetParentShip()
    if owner is None:
        climb = getattr(subsystem, "_climb_to_ship", None)
        if callable(climb):
            owner = climb()
    if owner is target:
        return True
    try:
        return subsystem in target.GetSubsystems()
    except Exception:
        return False


def _sync_fire_script_target_subsystem(inst) -> None:
    """Mirror a FireScript preprocessor's chosen target subsystem onto its
    firing ship so the aim sites (host_loop phaser tick, weapon_subsystems
    torpedo launch) that read ship.GetTargetSubsystem() honor the AI's choice.

    No-op for any preprocessor that is not a FireScript (gated on the
    lWeapons + idTargetedSubsystem markers). Only the AI driver calls this,
    and only for AI-driven FireScript nodes, so the player is unaffected.
    See docs/superpowers/specs/2026-07-07-npc-subsystem-targeting-design.md.
    """
    # Gate: FireScript instances only. lWeapons is the FireScript marker
    # (also used by _ensure_fire_script_initialized); idTargetedSubsystem is
    # set in FireScript.__init__ so it lives in __dict__ (bypass the _Stub
    # __getattr__ that would otherwise mask a missing attr).
    if not hasattr(inst, "lWeapons"):
        return
    if "idTargetedSubsystem" not in getattr(inst, "__dict__", {}):
        return

    code_ai = getattr(inst, "pCodeAI", None)
    if code_ai is None:
        return
    ship = code_ai.GetShip()
    if ship is None or not hasattr(ship, "SetTargetSubsystem"):
        return

    import App

    chosen = None
    sub_id = inst.idTargetedSubsystem
    if sub_id is not None:
        resolved = App.ShipSubsystem_Cast(App.TGObject_GetTGObjectPtr(sub_id))
        # Accept only a live subsystem that belongs to the ship's current
        # target; a stale id (old/other target) or dead id clears back to
        # centre-of-hull aim.
        if resolved is not None:
            target = ship.GetTarget()
            if target is not None and _subsystem_belongs_to(resolved, target):
                chosen = resolved

    # Only write on change — avoids churn and drives the dev log (below) on
    # transitions rather than every fire tick.
    if ship.GetTargetSubsystem() is not chosen:
        ship.SetTargetSubsystem(chosen)
        if dev_mode.is_enabled():
            ship_name = ship.GetName() if hasattr(ship, "GetName") else "<ship>"
            sub_name = chosen.GetName() if chosen is not None else "hull centre"
            # print(), not logging: the host configures no logging handler, so
            # logging.info is swallowed and never reaches the terminal. Matches
            # the [viewscreen]/[host_loop] dev-diagnostic convention.
            print(f"[ai] {ship_name} -> targeting {sub_name}")


def _tick_preprocessing(ai: PreprocessingAI, game_time: float) -> int:
    inst = ai._preprocessing_instance
    method = ai._preprocessing_method
    if inst is None or not method:
        # No preprocessor configured — fall through to contained AI.
        if ai._contained_ai is not None:
            tick_ai(ai._contained_ai, game_time)
        return ai._status

    # First-tick CodeAISet analog: SDK SelectTarget defers its
    # dDamageReceived dict + ET_WEAPON_HIT broadcast-handler wiring
    # to a CodeAISet method that the C++-optimized engine calls when
    # pCodeAI is bound (see AI/Preprocessors.py:1133-1148 comment).
    # Phase-1 has no C++ optimization, so the driver does it here on
    # first tick.
    #
    # SelectTarget init (Slice B Task 9): instances with callable
    # DamageEvent + pCodeAI; SelectTarget has no lWeapons.
    if callable(getattr(inst, "DamageEvent", None)) and getattr(inst, "pCodeAI", None) is not None:
        _ensure_select_target_initialized(inst)

    # FireScript init (Slice C Task 5): instances with lWeapons +
    # pCodeAI; FireScript has no DamageEvent. The two gates are
    # independent — no SDK preprocessor has both markers.
    if hasattr(inst, "lWeapons") and getattr(inst, "pCodeAI", None) is not None:
        _ensure_fire_script_initialized(inst)

    # Focus model surrogate — a PreprocessingAI reached on the active
    # dispatch path holds focus this tick. SelectTarget gates the
    # ship's target lock on `self.pCodeAI.HasFocus()`
    # (AI/Preprocessors.py:1257): without focus it never calls
    # pOurShip.SetTarget, so the AI ship's GetTarget() stays None and
    # every torpedo dumbfires forward instead of homing. `inst.pCodeAI`
    # is this PreprocessingAI node (ai.py SetPreprocessingMethod binds
    # `args[0].pCodeAI = self`), so setting it here is exactly what
    # HasFocus() reads. ArtificialIntelligence.HasFocus is the *only*
    # AI-side consumer in the whole SDK (the other HasFocus hits are
    # unrelated UI windows), so this is safe and well-scoped. Set
    # before the preprocessor's Update runs below, since SelectTarget
    # queries HasFocus mid-Update.
    ai._has_focus = True

    # Focus-loss lifecycle: record that this preprocessor was reached (focused)
    # this tick, so the root reconciliation (see tick_ai / _reconcile_focus) can
    # LostFocus() any node that drops off the active path next tick.
    _reached_this_tick.append(ai)

    # GotFocus dispatch — SDK preprocessors put side-effecting init in
    # GotFocus (sdk/.../AI/Preprocessors.py:2047 AlertLevel,
    # CloakShip, Defensive, …) rather than Update. The optimized
    # C++ engine calls it when an AI gains focus in the tree
    # dispatcher; Phase 1's driver has no focus model, so the
    # closest faithful surrogate is "once, the first time this
    # PreprocessingAI ticks". Guarded by a sentinel so subsequent
    # ticks don't re-fire. Duck-typed — no-op for preprocessors
    # without GotFocus.
    if not ai.__dict__.get("_got_focus_called", False):
        got_focus = getattr(inst, "GotFocus", None)
        if callable(got_focus):
            got_focus()
        ai._got_focus_called = True

    # Introspect once per PreprocessingAI instance whether the method
    # takes a positional dEndTime arg (SDK SelectTarget/FireScript) or
    # is 0-arg (synthetic test fixtures and simpler preprocessors).
    # Use __dict__.get to bypass TGObject.__getattr__ returning a _Stub
    # for missing attrs.
    cache = ai.__dict__.get("_preprocess_arity_cache")
    if cache is None or cache[0] is not inst or cache[1] != method:
        bound = getattr(inst, method)
        try:
            sig = inspect.signature(bound)
            arity = sum(
                1 for p in sig.parameters.values()
                if p.kind in (
                    inspect.Parameter.POSITIONAL_ONLY,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                )
            )
        except (TypeError, ValueError):
            # Builtin / no inspectable signature → assume 0-arg.
            arity = 0
        ai._preprocess_arity_cache = (inst, method, arity)
        cache = ai._preprocess_arity_cache

    arity = cache[2]
    # Cadence gate: run the preprocessor's own Update only when it is due
    # (game_time >= _next_update_time), mirroring _tick_plain and BC's C++
    # dispatcher, which honours every node's GetNextUpdateTime. The contained
    # AI still dispatches every tick (below) — only the preprocessor's own
    # decision-making is gated. ForceUpdate() resets _next_update_time to 0.0
    # so an asynchronous event (e.g. a target cloaking) re-runs the
    # preprocessor on the very next tick instead of after its full cadence.
    #
    # Skip calling Update once the preprocessor has reported PS_DONE. SDK
    # semantics: PS_DONE means "this preprocessor's job is finished", not "the
    # whole subtree is done". An "Unused"-style preprocessor like ManagePower
    # returns PS_DONE unconditionally (AI/Preprocessors.py:2148) and would
    # otherwise kill the wrapper subtree on tick 1.
    if not ai._preprocess_done and game_time >= ai._next_update_time:
        bound = getattr(inst, method)
        if arity >= 1:
            result = bound(game_time + 1.0)
        else:
            result = bound()

        if result is None:
            result = PS_NORMAL
        ai._last_preprocess_status = result

        # Bridge FireScript's chosen subsystem to the firing ship so the aim
        # sites honor it (spec 2026-07-07-npc-subsystem-targeting). No-op for
        # non-FireScript preprocessors.
        _sync_fire_script_target_subsystem(inst)

        # Reschedule from the preprocessor's own cadence. Default 0.0 (every
        # tick) when GetNextUpdateTime is absent — synthetic test fixtures and
        # simple preprocessors keep their historical every-tick behaviour, so
        # only real SDK preprocessors (SelectTarget 5s, FireScript 0.2s,
        # AlertLevel 60s, ManagePower 3s) actually gate.
        next_update_fn = getattr(inst, "GetNextUpdateTime", None)
        nxt = next_update_fn() if callable(next_update_fn) else None
        interval = float(nxt) if nxt is not None else 0.0
        ai._next_update_time = game_time + interval

        if result == PS_DONE:
            # Remember not to call Update again; do NOT mark the wrapper
            # US_DONE. Fall through to contained_ai dispatch.
            ai._preprocess_done = True
        elif result == PS_SKIP_DORMANT:
            ai._status = US_DORMANT
            return ai._status
        elif result == PS_SKIP_ACTIVE:
            ai._status = US_ACTIVE
            return ai._status
        # PS_NORMAL falls through to contained_ai dispatch below.
    elif not ai._preprocess_done:
        # Cadence-skipped tick: the preprocessor didn't run this tick, so
        # reproduce its last decision rather than blindly dispatching. A
        # targetless SelectTarget that reported PS_SKIP_DORMANT must stay
        # dormant (not run its combat list against a None target) until its
        # next scheduled update or a ForceUpdate.
        last = ai._last_preprocess_status
        if last == PS_SKIP_DORMANT:
            ai._status = US_DORMANT
            return ai._status
        if last == PS_SKIP_ACTIVE:
            ai._status = US_ACTIVE
            return ai._status
        # PS_NORMAL (or never-run) falls through to contained_ai dispatch.

    ai._status = US_ACTIVE
    if ai._contained_ai is not None:
        tick_ai(ai._contained_ai, game_time)
    return ai._status


def _ensure_select_target_initialized(inst) -> None:
    """Phase-1 substitute for the C++ CodeAISet path on SelectTarget.

    The SDK's SelectTarget.__init__ leaves three pieces of state to be
    set up by the engine after pCodeAI is bound: a TGPythonInstanceWrapper
    to receive events, the dDamageReceived accounting dict, and a broadcast
    handler for ET_WEAPON_HIT routed to its DamageEvent method (see the
    block comment in AI/Preprocessors.py:1133-1148).

    Duck-typed on having a DamageEvent method + a bound pCodeAI so we
    don't accidentally instrument unrelated preprocessors. Guarded by a
    sentinel attribute so re-ticks are no-ops.
    """
    if getattr(inst, "_dauntless_codeaiset_done", False):
        return
    if not callable(getattr(inst, "DamageEvent", None)):
        return
    pCodeAI = getattr(inst, "pCodeAI", None)
    if pCodeAI is None:
        return
    pShip = pCodeAI.GetShip() if hasattr(pCodeAI, "GetShip") else None
    if pShip is None:
        return

    import App
    if not hasattr(inst, "pEventHandler") or inst.pEventHandler is None:
        wrapper = App.TGPythonInstanceWrapper()
        wrapper.SetPyWrapper(inst)
        inst.pEventHandler = wrapper
    if not hasattr(inst, "dDamageReceived") or inst.dDamageReceived is None:
        inst.dDamageReceived = {}
    App.g_kEventManager.AddBroadcastPythonMethodHandler(
        App.ET_WEAPON_HIT, inst.pEventHandler, "DamageEvent", pShip,
    )

    # Initial ship-target push. NonFedAttack/FedAttack build SelectTarget
    # with ForceCurrentTargetString(sInitialTarget), which presets
    # sCurrentTarget *without* calling pShip.SetTarget — the on-change
    # branch in SelectTarget.Update (Preprocessors.py:1255) then sees no
    # change and skips it forever. In stock BC the C++-optimized CodeAISet
    # performed this initial push (the Python CodeAISet is a dead `return`
    # stub, lines 1136-1157). Without it the AI ship's GetTarget() stays
    # None and every torpedo dumbfires forward (subsystems.py:1700). Mirror
    # SelectTarget.Update's `pOurShip.SetTarget(self.sCurrentTarget)`
    # (line 1260); mid-combat target *changes* are handled by the same
    # call once HasFocus() is true.
    if getattr(inst, "bSetShipTarget", 0) and getattr(inst, "sCurrentTarget", None):
        pShip.SetTarget(inst.sCurrentTarget)

    inst._dauntless_codeaiset_done = True


def _ensure_fire_script_initialized(inst) -> None:
    """First-tick CodeAISet analog for FireScript instances.

    SDK Preprocessors.py:137-145 — FireScript.CodeAISet registers the
    SetTarget external function on its pCodeAI so SelectTarget's
    `CallExternalFunction("SetTarget", name)` dispatch reaches us.

    Duck-typed gate: instance must have an lWeapons attribute (the
    FireScript-specific marker — SelectTarget has neither lWeapons
    nor needs SetTarget registered). FireScript does NOT define
    DamageEvent, unlike SelectTarget — keep the two init paths
    independent.

    Idempotent via _dauntless_fs_init_done sentinel on the instance.
    """
    if getattr(inst, "_dauntless_fs_init_done", False):
        return
    code_ai = getattr(inst, "pCodeAI", None)
    if code_ai is None:
        return
    code_ai.RegisterExternalFunction("SetTarget", {"Name": "SetTarget"})
    inst._dauntless_fs_init_done = True


def _tick_builder(ai: BuilderAI, game_time: float) -> int:
    """First-tick activation: topologically sort the block graph, call
    BuilderCreateN functions in dependency order, set the last block's
    result as _contained_ai. Subsequent ticks delegate to standard
    PreprocessingAI dispatch."""
    if ai._activation_failed:
        return US_DONE
    if not ai._activated:
        _activate_builder(ai)
        if ai._activation_failed:
            return US_DONE
    return _tick_preprocessing(ai, game_time)


def _activate_builder(ai: BuilderAI) -> None:
    """Kahn's-algorithm topological sort + dependency-injected build."""
    import sys

    try:
        # Build adjacency lists. blocks: {name: (builder_func_name, [dep_names])}.
        block_names = list(ai._blocks.keys())
        builder_funcs = dict(ai._blocks)  # name → func_name (str)

        deps_by_block: dict[str, list[str]] = {n: [] for n in block_names}
        for child, parent in ai._dependencies:
            # ai._dependencies stores (block_name, dep_block_name). The
            # block depends on dep_block_name being built first.
            deps_by_block.setdefault(child, []).append(parent)

        dep_objects_by_block: dict[str, dict] = {n: {} for n in block_names}
        for block, attr, value in ai._dep_objects:
            dep_objects_by_block.setdefault(block, {})[attr] = value

        # Topological sort (Kahn).
        in_degree = {n: len(deps_by_block[n]) for n in block_names}
        queue = [n for n in block_names if in_degree[n] == 0]
        sorted_names: list[str] = []
        while queue:
            n = queue.pop(0)
            sorted_names.append(n)
            for child in block_names:
                if n in deps_by_block.get(child, ()):
                    in_degree[child] -= 1
                    if in_degree[child] == 0:
                        queue.append(child)
        if len(sorted_names) != len(block_names):
            unresolved = [n for n in block_names if n not in sorted_names]
            raise RuntimeError(f"cyclic dependency in BuilderAI: {unresolved}")

        # Resolve the owning module.
        mod = sys.modules.get(ai._module_name)
        if mod is None:
            mod = __import__(ai._module_name)

        # Build each block.
        results: dict[str, object] = {}
        for name in sorted_names:
            func_name = builder_funcs[name]
            fn = getattr(mod, func_name, None)
            if fn is None:
                raise AttributeError(f"module {ai._module_name!r} has no function {func_name!r}")
            dep_args = [results[d] for d in deps_by_block[name]]
            kwargs = dep_objects_by_block.get(name, {})
            results[name] = fn(ai._ship, *dep_args, **kwargs)

        # Last block in topological order becomes the contained AI.
        last = sorted_names[-1] if sorted_names else None
        last_result = results.get(last) if last else None
        if last_result is None:
            raise RuntimeError(f"BuilderAI root block {last!r} returned None")
        ai._contained_ai = last_result
        ai._activated = True
    except Exception as e:
        ai._activation_failed = True
        ai._activation_error = (type(e).__name__, str(e))
        ai._status = US_DONE


def fire_ai_done(ship, ai) -> None:
    """Broadcast ET_AI_DONE for an AI that just ended on `ship`.

    BC fires this when a ship's AI is destroyed/replaced or completes;
    listeners key on GetInt() == the ended AI's id with the ship as the
    event destination (Conditions/ConditionPlayerOrbitting.OrbitDone
    registers a method-broadcast handler with target=pPlayer, and
    Bridge/HelmCharacterHandlers.AIDone is an instance handler on the
    player). Skips AIs without a GetID (bare test doubles)."""
    get_id = getattr(ai, "GetID", None)
    if not callable(get_id):
        return
    try:
        import App
        evt = App.TGIntEvent_Create()
        evt.SetEventType(App.ET_AI_DONE)
        evt.SetInt(int(get_id()))
        evt.SetSource(ship)
        evt.SetDestination(ship)
        App.g_kEventManager.AddEvent(evt)
    except Exception as _e:
        from engine import dev_mode
        dev_mode.log_swallowed("fire ET_AI_DONE", _e)


def tick_all_ai(game_time: float) -> None:
    """Iterate every ship and tick its attached AI subtree.

    Called once per frame from GameLoop.tick(). Q2 closed at AI-first
    within the tick so this fires before physics + render.
    """
    from engine.appc.ship_iter import iter_ships
    from engine.appc import defensive_cloak
    for ship in iter_ships():
        # A ship hiding-to-repair is owned by the defensive-cloak controller;
        # suppress its SDK AI so the two cloak drivers never conflict.
        if defensive_cloak.is_defensive(ship):
            continue
        ai = ship.GetAI() if hasattr(ship, "GetAI") else None
        if ai is not None:
            status = tick_ai(ai, game_time)
            # Root-tree completion fires ET_AI_DONE once (SDK: the engine
            # announces an AI's end so orbit/helm state can react).
            if status == US_DONE and not getattr(ai, "_done_event_fired", False):
                ai._done_event_fired = True
                fire_ai_done(ship, ai)
