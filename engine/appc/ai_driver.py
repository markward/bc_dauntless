"""AI tick driver — walks an AI tree top-down each frame.

Mirrors the SDK ArtificialIntelligence dispatch semantics
(sdk/Build/scripts/App.py:4922-5232):

* PlainAI         — call script_instance.Update() at GetNextUpdateTime() cadence
* PriorityListAI  — run highest-priority non-DORMANT child (lower int == higher priority)
* SequenceAI      — run current child; on US_DONE advance, loop per _loop_count
* ConditionalAI   — if any condition is non-zero, run contained AI; else US_DORMANT
* PreprocessingAI — invoke preprocess method, dispatch contained per PS_*

The driver is *not* TimeSliceProcess-based. PlainAI carries its own
_next_update_time field; the driver consults it each tick. This keeps
Step 3 testable independently of the TimeSliceProcess scheduler (Step 2).
"""
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
    status = inst.Update()
    if status is None:
        status = US_ACTIVE
    ai._status = int(status)
    # Reschedule based on the script's reported interval. Fallback
    # _AIScriptInstance returns None for unknown Get*; treat as 1 sec.
    next_update = inst.GetNextUpdateTime()
    interval = float(next_update) if next_update is not None else 1.0
    ai._next_update_time = game_time + interval
    return ai._status


def _tick_priority_list(ai: PriorityListAI, game_time: float) -> int:
    # ai._ais is sorted lowest priority-int first (highest priority).
    for _prio, child in ai._ais:
        if child._status == US_DORMANT:
            continue
        tick_ai(child, game_time)
        return ai._status  # one child per tick (SDK semantics)
    # All children dormant or list empty.
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
    result = getattr(inst, method)()
    if result is None:
        result = PS_NORMAL
    if result == PS_DONE:
        ai._status = US_DONE
        return ai._status
    if result == PS_SKIP_DORMANT:
        ai._status = US_DORMANT
        return ai._status
    if result == PS_SKIP_ACTIVE:
        ai._status = US_ACTIVE
        return ai._status
    # PS_NORMAL
    ai._status = US_ACTIVE
    if ai._contained_ai is not None:
        tick_ai(ai._contained_ai, game_time)
    return ai._status


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
