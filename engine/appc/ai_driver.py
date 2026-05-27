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

from engine.appc.ai import (
    ArtificialIntelligence, PlainAI, PriorityListAI, SequenceAI,
    ConditionalAI, PreprocessingAI, BuilderAI,
)

US_ACTIVE = ArtificialIntelligence.US_ACTIVE
US_DONE = ArtificialIntelligence.US_DONE
US_DORMANT = ArtificialIntelligence.US_DORMANT
PS_NORMAL = PreprocessingAI.PS_NORMAL
PS_SKIP_ACTIVE = PreprocessingAI.PS_SKIP_ACTIVE
PS_SKIP_DORMANT = PreprocessingAI.PS_SKIP_DORMANT
PS_DONE = PreprocessingAI.PS_DONE


def tick_ai(ai, game_time: float) -> int:
    """Tick one AI subtree at the given game time. Returns the resulting status."""
    if ai is None:
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
    if isinstance(ai, PlainAI):
        return _tick_plain(ai, game_time)
    return ai._status


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
        if child._status == US_DORMANT or child._status == US_DONE:
            continue
        tick_ai(child, game_time)
        return ai._status  # one child per tick (SDK semantics)
    # All children dormant/done or list empty.
    if ai._ais and all(c._status == US_DONE for _p, c in ai._ais):
        ai._status = US_DONE
    return ai._status


def _tick_sequence(ai: SequenceAI, game_time: float) -> int:
    """Tick the current child; on DONE, advance index inline.

    If the index walks off the end, set the sequence DONE on the same tick
    (loop_count handling is deliberately out of scope for this slice —
    SetLoopCount works as a data getter/setter, but no looping in the
    driver yet; revisit when Compound.BasicAttack arrives).
    """
    if not ai._ais:
        ai._status = US_DONE
        return ai._status
    idx = getattr(ai, "_current_index", 0)
    if idx >= len(ai._ais):
        ai._status = US_DONE
        return ai._status
    child = ai._ais[idx]
    tick_ai(child, game_time)
    if child._status == US_DONE:
        idx += 1
        ai._current_index = idx
        if idx >= len(ai._ais):
            ai._status = US_DONE
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
    # Skip calling the preprocessor's Update once it has reported PS_DONE.
    # SDK semantics: PS_DONE means "this preprocessor's job is finished",
    # not "the whole subtree is done". An "Unused"-style preprocessor like
    # ManagePower returns PS_DONE unconditionally (AI/Preprocessors.py:2148)
    # and would otherwise kill the wrapper subtree on tick 1.
    if not ai._preprocess_done:
        bound = getattr(inst, method)
        if arity >= 1:
            result = bound(game_time + 1.0)
        else:
            result = bound()

        if result is None:
            result = PS_NORMAL
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


def tick_all_ai(game_time: float) -> None:
    """Iterate every ship and tick its attached AI subtree.

    Called once per frame from GameLoop.tick(). Q2 closed at AI-first
    within the tick so this fires before physics + render.
    """
    from engine.appc.ship_iter import iter_ships
    for ship in iter_ships():
        ai = ship.GetAI() if hasattr(ship, "GetAI") else None
        if ai is not None:
            tick_ai(ai, game_time)
