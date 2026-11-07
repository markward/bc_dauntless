"""The frozen Python AI tree walker: a TEST ORACLE, not engine code.

Phase 6 AI part 4, Task 8. Until commit 1a9aa97af the AI tree was walked by
Python in engine/appc/ai_driver.py; the walker is now C++
(native/src/host/aitree.cc) and Mark's rule (2026-11-07) is that ported code
keeps no permanent Python copy in the engine. This file is that Python walker,
verbatim as of 1a9aa97af ("test(ai): awake differentials prove the trees
switch"), the last commit before its deletion: ``git show
1a9aa97af:engine/appc/ai_driver.py`` holds the functions as they were then.
It is the reference the native walk is proven against statement for statement.

EVOLUTION RULE: a future change to the native walk (native/src/host/aitree.cc)
changes this oracle in the same commit, so the two stay statement-for-
statement equal and the differential harness keeps meaning something. The
oracle is not frozen against the walk; it is frozen against drift.

It cannot be imported as a standalone module: the bodies read ai_driver's
module globals (``_DISPATCH_BY_TYPE``, ``_ooa_cache``, ``_reached_this_tick``,
``_note_due``, ``_run_script_step``, ``US_*``, ...) exactly as they did when
they lived there. :func:`install` rebinds each function onto
``ai_driver.__dict__`` (``types.FunctionType`` with ai_driver's globals), for
the length of a test, through the caller's ``MonkeyPatch``. That is the whole
trick: the walk state, the patch points and the callbacks are the very ones
the native walk uses, so the two walkers run against the same module.

What :func:`install` also does, in the helper rather than the engine: it sets
``ai_driver._native_walker = False``. The dispatchers kept below
(``tick_all_ai``, ``tick_ai``, ``_eval_conditional``, ``_refresh_conditional_
status``, ``_condition_statuses``, ``_any_condition``) are the ones that read
that flag, and the flag no longer exists in the engine; with it False they
take their Python arm, which is the walker. (Their native arm names
``_tick_all_ai_native``, which is gone; it is never reached.)
"""
# ruff: noqa
# flake8: noqa
from __future__ import annotations

import types

#: The walker's functions, in the order they stood in ai_driver.
WALKER_NAMES = (
    "tick_all_ai",
    "_tick_all_ai_python",
    "tick_ai",
    "_tick_ai_python",
    "_dispatch_ai",
    "_reconcile_focus",
    "_retain_subtree_focus",
    "_reconcile_active",
    "_focus_instance_of",
    "_dispatch_lost_focus",
    "_queue_got_focus",
    "_flush_pending_got_focus",
    "_tick_plain",
    "_dispatch_priority_child",
    "_tick_priority_list",
    "_eval_conditional",
    "_refresh_conditional_status",
    "_condition_statuses",
    "_any_condition",
    "_condition_statuses_python",
    "_any_condition_python",
    "_eval_conditional_python",
    "_refresh_conditional_status_python",
    "_tick_sequence",
    "_tick_random",
    "_tick_conditional",
    "_tick_preprocessing",
    "_tick_builder",
)

#: ai_driver's module globals the bodies below read that the engine itself no
#: longer defines. Set by :func:`install` (and undone with the MonkeyPatch).
_RESTORED_GLOBALS = {"_native_walker": False}

#: How many times the oracle's entry points have run, in this process: the
#: roster (``_tick_all_ai_python``), the walk (``_tick_ai_python``, once per
#: tick_ai) and the four condition-evaluation bodies. The differential harness
#: reads them around a side to prove which walker that side ran.
ENTRIES = {"roster": 0, "walk": 0, "s2": 0}
_COUNTED = {
    "_tick_all_ai_python": "roster",
    "_tick_ai_python": "walk",
    "_refresh_conditional_status_python": "s2",
    "_eval_conditional_python": "s2",
    "_condition_statuses_python": "s2",
    "_any_condition_python": "s2",
}


def clone(name):
    """The oracle function `name`, bound to ai_driver's module globals (its
    walk state, patch points and callees), not installed. The entry points in
    :data:`ENTRIES` count their calls."""
    from engine.appc import ai_driver
    fn = globals()[name]
    bound = types.FunctionType(fn.__code__, ai_driver.__dict__, name,
                               fn.__defaults__, fn.__closure__)
    bound.__kwdefaults__ = fn.__kwdefaults__
    bound.__annotations__ = dict(fn.__annotations__)
    bound.__doc__ = fn.__doc__
    kind = _COUNTED.get(name)
    if kind is None:
        return bound

    def counted(*args, **kwargs):
        ENTRIES[kind] += 1
        return bound(*args, **kwargs)
    counted.__name__ = name
    counted.__doc__ = fn.__doc__
    return counted


def install(mp):
    """Make ai_driver run the Python walker for the length of `mp`'s test.

    Every function in :data:`WALKER_NAMES` is rebound onto ai_driver (global
    scope = ai_driver's namespace) and ``_native_walker`` is set False for the
    dispatchers. Undone by ``mp.undo()``. Returns the dict name -> installed
    function."""
    from engine.appc import ai_driver
    installed = {}
    for key, value in _RESTORED_GLOBALS.items():
        mp.setattr(ai_driver, key, value, raising=False)
    for name in WALKER_NAMES:
        installed[name] = clone(name)
        mp.setattr(ai_driver, name, installed[name], raising=False)
    return installed


# -- the walker, verbatim from 1a9aa97af:engine/appc/ai_driver.py -----------

def tick_ai(ai, game_time: float) -> int:
    """Tick one AI subtree with the selected walker (``_native_walker``): the
    native walk (aitree_tick, native/src/host/aitree.cc) or
    ``_tick_ai_python``, the reference it reproduces statement for
    statement. Every caller -- the rosters, the handlers, a script -- comes
    through here, so a test patching ``tick_ai`` is honoured by both."""
    if _native_walker:
        return _aitree_tick(ai, game_time, _GLOBALS)
    return _tick_ai_python(ai, game_time)


def _tick_ai_python(ai, game_time: float) -> int:
    """Tick one AI subtree; reconcile preprocessor focus and tree-activation
    at the root call.

    The outermost tick_ai call (one per ship, from tick_all_ai) is the root: it
    collects which PreprocessingAI nodes were reached (== on the active path ==
    focused) this tick, then dispatches LostFocus() to any node that was focused
    last tick but not this one -- and, generally, calls SetActive()/
    SetInactive() on every node as it enters/leaves the active dispatch path.
    Recursive calls into children just dispatch."""
    global _focus_depth, _reached_this_tick, _reached_this_tick_all, _reached_this_tick_all_ids
    global _pending_got_focus
    is_root = _focus_depth == 0
    if is_root:
        # The out-of-action slot is scoped to one root tick: a new root means a
        # new ship, and a ship that died since the last root tick must be
        # re-asked.
        _ooa_cache[0] = None
        _reached_this_tick = []
        _reached_this_tick_all = []
        _reached_this_tick_all_ids = set()
        _pending_got_focus = []
    _focus_depth += 1
    try:
        status = _dispatch_ai(ai, game_time)
    finally:
        _focus_depth -= 1
    if is_root and ai is not None:
        # Departures first, arrivals second -- the two halves of one handover,
        # in BC's order. _flush_pending_got_focus carries the reasoning.
        _reconcile_focus(ai, _reached_this_tick)
        _flush_pending_got_focus()
        _reconcile_active(ai, _reached_this_tick_all)
    return status


def _dispatch_ai(ai, game_time: float) -> int:
    """Type-dispatch one AI node (the former body of tick_ai)."""
    if ai is None:
        return US_DONE
    # Inert-coast gate: a dying/dead ship issues no new orders.
    #
    # This was previously marked a MEASURED DEAD END on the grounds that
    # removing ~327,000 calls was unmeasurable on the wall clock. That
    # observation was correct; the inference from it was not. It rested on
    # "327k calls at ~30 ns is 0.03 ms/tick", and the per-call figure was the
    # weak link -- _out_of_action is two implements() plus two engine method
    # calls, not 30 ns of work.
    #
    # Measured directly, with the timer's own cost calibrated and subtracted:
    # 0.632 us per call, 772 node visits/tick at 100 ships = 0.488 ms/tick,
    # ~7.3 ms/frame, and 55% of _dispatch_ai's whole pre-handler preamble.
    # Sixteen times the figure the old note reasoned from.
    #
    # Why the wall clock could not see it, then or now: the number of catch-up
    # ticks per frame is derived from wall-clock frame time, so a momentarily
    # faster machine runs more ticks and evolves the battle differently.
    # combat_stress does not reproduce run to run, and its frame time carries
    # +/-40 ms of scene noise -- roughly six times this effect. "Unmeasurable
    # by that instrument" is a fact about the instrument.
    #
    # The cache is a single slot, not a dict: within one root tick every node
    # in the tree belongs to the SAME ship, so identity against the last ship
    # asked is both sufficient and cheaper than hashing. Reset at each root
    # tick (see tick_ai). Nothing inside tick_all_ai can kill a ship -- the AI
    # writes setpoints and queues fire; damage lands later in _advance_combat
    # -- and a mismatch merely recomputes, so the failure mode is a lost
    # saving, never a wrong answer.
    ship = ai.GetShip() if hasattr(ai, "GetShip") else None
    if ship is not None:
        if _ooa_cache[0] is ship:
            if _ooa_cache[1]:
                return US_DONE
        else:
            _dead = ship_death._out_of_action(ship)
            _ooa_cache[0] = ship
            _ooa_cache[1] = _dead
            if _dead:
                return US_DONE
    # Record every node type reached on the active dispatch path this root
    # tick -- the single funnel every _tick_* function passes through, so
    # this is the one place that needs to record (see _reconcile_active).
    # Identity-dedup: a node dispatched more than once in the same root tick
    # (e.g. re-entered via a looping SequenceAI) must only appear once, else
    # _reconcile_active's `reached` list — and the _active_nodes snapshot
    # derived from it — carries duplicates.
    node_id = id(ai)          # was computed twice per node visit
    if node_id not in _reached_this_tick_all_ids:
        _reached_this_tick_all_ids.add(node_id)
        _reached_this_tick_all.append(ai)

    # A SENTINEL for "not yet resolved", not None. _resolve_dispatch legitimately
    # answers None for a node type that matches nothing, and .get()'s None-for-
    # absent conflates the two: such a type re-ran the whole 7-step issubclass
    # chain on EVERY visit, which is the one case the cache exists to kill.
    node_type = type(ai)                  # was evaluated three times on a miss
    handler = _DISPATCH_BY_TYPE.get(node_type, _UNRESOLVED)
    if handler is _UNRESOLVED:
        handler = _DISPATCH_BY_TYPE[node_type] = _resolve_dispatch(node_type)
    if handler is None:
        return ai._status
    if _AI_BREAKDOWN is not None:
        return _timed_dispatch(handler, ai, game_time)
    return handler(ai, game_time)


def _reconcile_focus(root_ai, reached) -> None:
    """Dispatch LostFocus() to nodes focused last tick but not this one.

    Native with the native walker (aitree.cc, S3) while this global is the
    stock function; this body is the reference it reproduces, as are
    _dispatch_lost_focus, _flush_pending_got_focus and _reconcile_active.

    Identity-based: `reached` holds the PreprocessingAI and PlainAI nodes
    ticked this root tick (see _tick_preprocessing / _tick_plain). Any node in
    the root's previous focused set that is not among them has left the active
    dispatch path."""
    reached_ids = {id(n) for n in reached}
    for node in getattr(root_ai, "_focused_preprocessors", ()):
        if id(node) not in reached_ids:
            _dispatch_lost_focus(node)
    root_ai._focused_preprocessors = list(reached)


def _retain_subtree_focus(ai) -> None:
    """Carry a suppressed subtree's focus across a PS_SKIP_ACTIVE tick.

    PS_SKIP_ACTIVE means "I am handling this tick, do not run my child" —
    US_ACTIVE, child not run (PreprocessingAI::Update's switch at 0x48eab1).
    The child has NOT left the active dispatch path; its parent is momentarily
    driving instead. But the child is not ticked, so nothing records it in
    `_reached_this_tick`, and `_reconcile_focus` would read the absence as a
    departure and dispatch LostFocus down the whole subtree.

    That is not a cosmetic distinction. `AvoidObstacles` sits ABOVE the attack
    tree in BC's own QuickBattleAI and returns PS_SKIP_ACTIVE for as long as a
    ship is evading — measured, three of twelve ships in a fight evaded for
    250+ of 300 consecutive ticks. For those five seconds `AlertLevel.LostFocus`
    had restored the pre-combat alert level (shields down) and
    `FireScript.LostFocus` had called StopFiring(). Dodging would switch
    fighting off.

    Re-record exactly the nodes that already hold focus, so reconciliation sees
    no change at all: no LostFocus on the way in, and no second GotFocus on the
    way out (AlertLevel's GotFocus runs its combat-entry side effects).

    PS_SKIP_ACTIVE only. PS_SKIP_DORMANT says the node IS dormant — a
    targetless SelectTarget — and a dormant subtree really has left the path,
    which is what test_lost_focus_when_node_drops_off_active_path pins.

    Focus only, deliberately. Tree activation (_reconcile_active,
    SetActive/SetInactive) answers a different question — "did dispatch reach
    this node" — whose answer really is no; those calls are edge-guarded and
    re-arm when the skip ends.
    """
    node = ai._contained_ai
    if node is None:
        return
    stack = [node]
    while stack:
        n = stack.pop()
        if n.__dict__.get("_has_focus"):
            _reached_this_tick.append(n)
        child = n.__dict__.get("_contained_ai")
        if child is not None:
            stack.append(child)
        for c in (n.__dict__.get("_ais") or ()):
            stack.append(c[1] if isinstance(c, tuple) else c)


def _reconcile_active(root_ai, reached) -> None:
    """Dispatch SetActive()/SetInactive() to every AI node as it enters/leaves
    the active dispatch path this root tick.

    Identity-based, mirroring _reconcile_focus: `reached` holds every node
    _dispatch_ai actually ran this root tick (recorded there -- the single
    funnel every node type passes through). A node in the root's previous
    active set that is not among them has left the tree's active path and is
    deactivated; every reached node is (re)activated. SetActive/SetInactive
    are edge-guarded (ArtificialIntelligence._is_active_in_tree), so calling
    SetActive on a node that's already active is a safe no-op -- this is what
    lets a ConditionalAI picked back up by its PriorityListAI re-activate its
    conditions and re-arm a ConditionTimer.

    Every node `_dispatch_ai` can reach is a real ArtificialIntelligence
    subclass (production AI classes, or a test double that subclasses it --
    see tests/integration/test_defensive_cloak_cadence.py's _InertAI), so
    SetActive/SetInactive are called unconditionally here. (The native
    reconciliation skips only a stock call that would return at its first
    statement; see _STOCK_SET_ACTIVE.)"""
    reached_ids = {id(n) for n in reached}
    for node in getattr(root_ai, "_active_nodes", ()):
        if id(node) not in reached_ids:
            node.SetInactive()
    for node in reached:
        node.SetActive()
    root_ai._active_nodes = list(reached)


def _focus_instance_of(node):
    """The Python script instance that carries a node's focus hooks.

    PlainAI keeps it in _script_instance; PreprocessingAI in
    _preprocessing_instance. Read from __dict__ so TGObject.__getattr__ can't
    hand back a truthy _Stub for a node type that has neither.
    """
    d = getattr(node, "__dict__", {})
    script_inst = d.get("_script_instance")
    if script_inst is not None:
        return script_inst
    return d.get("_preprocessing_instance")


def _dispatch_lost_focus(node) -> None:
    """Call the node's script instance's LostFocus() (if any) and clear the
    focus latches so a later re-entry re-fires GotFocus()."""
    inst = _focus_instance_of(node)
    lost = getattr(inst, "LostFocus", None) if inst is not None else None
    if callable(lost):
        _run_script_step(node, lost)
    node._has_focus = False
    node.__dict__["_got_focus_called"] = False


def _queue_got_focus(node) -> None:
    """Record that `node` arrived on the active path, for GotFocus() at the end
    of the root tick.

    Deferred, not dispatched here, so that a handover fires the departing
    node's LostFocus() FIRST -- see _flush_pending_got_focus.

    The script instance is resolved HERE, not at flush time, and a node with
    none is dropped rather than queued. That keeps the "ticked before
    SetScriptModule() landed" rule intact: _tick_plain calls
    GetScriptInstance() further down, which MATERIALISES an _AIScriptInstance
    lambda-fallback as a side effect, so by flush time every PlainAI has an
    instance. Resolving late would fire GotFocus on that placeholder and latch
    it, and the real script's GotFocus would never run once its module landed
    (tests/unit/test_ai_driver_leaf_focus.py).
    """
    if node.__dict__.get("_got_focus_called", False):
        return
    inst = _focus_instance_of(node)
    if inst is None:
        return
    for queued, _inst in _pending_got_focus:
        if queued is node:
            return
    _pending_got_focus.append((node, inst))


def _flush_pending_got_focus() -> None:
    """Dispatch GotFocus() to every node that arrived this root tick, AFTER
    _reconcile_focus has dispatched LostFocus() to the departing ones.

    Why the order matters. The SDK's focus hooks are save/restore pairs:
    AlertLevel.GotFocus snapshots the ship's current alert level and raises
    it; AlertLevel.LostFocus puts the snapshot back
    (AI/Preprocessors.py:2047). BC changes focus at the container, so a
    handover is LostFocus-then-GotFocus by construction and the snapshots
    nest correctly.

    This driver instead discovers departures by set difference, which cannot
    be computed until the traversal has finished. Dispatching GotFocus during
    the traversal therefore inverted the pair on any handover, and the
    arriving node snapshotted a value the departing node was about to undo.

    Live case (AI-inspector export, Kessok Light in QuickBattle): both
    branches of the ship's top PriorityList carry AlertLevel(2). Branch 2 was
    on the path, holding eOldAlertLevel=0 with the ship at alert 2. Branch 1's
    gate opened; branch 1's GotFocus read alert 2, saw 2 == 2 and did nothing;
    branch 2's LostFocus then restored 0. The ship dropped its shields mid-
    combat and never raised them again -- AlertLevel.Update is a no-op
    returning PS_NORMAL, so the surviving node never re-asserts.

    Deferring GotFocus past the node's own Update is safe against the whole
    SDK: only three scripts define GotFocus, and two of them ARE their Update
    (CloakShip.GotFocus and CloakShip.Update both call CheckCloak();
    StarbaseAttack.GotFocus calls self.Update() outright). AlertLevel.Update
    is the no-op above. None reads state its own GotFocus establishes.

    Once per activation: the latch below is the same sentinel
    _dispatch_lost_focus clears, so a node that stays on the path does not
    re-fire. Nodes with no script instance never reach this queue at all --
    _queue_got_focus drops them, and carries the reason.
    """
    if not _pending_got_focus:
        return
    # Snapshot and clear first: a GotFocus body may tick AI of its own.
    pending = list(_pending_got_focus)
    del _pending_got_focus[:]
    for node, inst in pending:
        if node.__dict__.get("_got_focus_called", False):
            continue
        got = getattr(inst, "GotFocus", None)
        if callable(got):
            _run_script_step(node, got)
        node.__dict__["_got_focus_called"] = True


def _tick_plain(ai: PlainAI, game_time: float) -> int:
    if ai._status != US_ACTIVE:
        return ai._status

    # A PlainAI reached on the active dispatch path holds focus this tick — the
    # same surrogate the PreprocessingAI path uses. Four shipped leaf scripts
    # put real work in these hooks, and every LostFocus body is cleanup that
    # MUST run: Warp.py:217 re-enables the collisions it disabled (an
    # interrupted warp otherwise leaves the ship permanently non-collidable),
    # RunAction.py:50 aborts the running action, Intercept.py:70 stops the
    # in-system warp, StarbaseAttack.py:58 stops firing.
    ai._has_focus = True
    _reached_this_tick.append(ai)
    _queue_got_focus(ai)

    # Cadence gate. _note_due goes in the NOT-due arm only: on a tick the node
    # actually executes, its old due time is already in the past, and recording
    # a past time pinned the walk min-due slot below game_time -- so the ship's
    # sleep stamp landed in the past and the whole tree was walked again on the
    # very next tick to rediscover nothing was due. Measured 287 walks for 96 runs at
    # cap 4, where ~192 would do. The invariant is untouched: the not-due arm
    # records what it is waiting for, and the executing arm records the FRESH
    # due time below.
    if game_time < ai._next_update_time:
        _note_due(ai._next_update_time)
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
        # No _note_due here on purpose. This node has no Update to run at any
        # cadence, so there is nothing for the walk to wait on -- recording its
        # (already past) due time would force a walk every tick forever for a
        # node that can never do anything. A PlainAI still waiting for
        # SetScriptModule is the one transient case, and the cap picks it up
        # within AI_MAX_SLEEP_TICKS.
        return ai._status
    status = _run_script_step(ai, update_fn)
    if status is None:
        status = US_ACTIVE
    ai._status = int(status)
    # Reschedule from the script's reported interval. Appc's PlainAI::Update
    # bridge returns 0.0 when the Python call fails, which makes the AI run
    # every tick (ai-architecture.md sec.3: "There is no default interval in
    # C++") — matches PlainAI::GetNextUpdateTime (0x0048d320).
    next_update_fn = getattr(inst, "GetNextUpdateTime", None)
    next_update = next_update_fn() if callable(next_update_fn) else None
    interval = float(next_update) if next_update is not None else 0.0
    ai._next_update_time = game_time + interval
    _note_due(ai._next_update_time)
    return ai._status


def _dispatch_priority_child(child, game_time: float) -> int:
    """Dispatch one PriorityList child, guarding its focus bookkeeping.

    If the child does NOT end up US_ACTIVE, the focus/active records it appended
    this tick are rolled back and its own focus latches restored — so it does
    not count as "on the active path" and the root reconciliation deactivates it
    (firing its LostFocus if it was focused last tick). This mirrors BC's
    PriorityListAI::Update (0x00490340): a child whose Update returns
    US_DORMANT/US_DONE, or a dormant child re-probed and still dormant, never
    holds focus. Returns the child's post-dispatch status."""
    focus_n = len(_reached_this_tick)
    all_n = len(_reached_this_tick_all)
    # Arrivals queued while probing this child must roll back with the focus
    # records they belong to, or a child that is probed and rejected fires
    # GotFocus anyway -- an AlertLevel under a rejected branch would snapshot
    # and raise the alert level on every probe.
    pending_n = len(_pending_got_focus)
    had_focus = child._has_focus
    had_got = child.__dict__.get("_got_focus_called", False)
    tick_ai(child, game_time)
    if child._status != US_ACTIVE:
        del _reached_this_tick[focus_n:]
        del _reached_this_tick_all[all_n:]
        del _pending_got_focus[pending_n:]
        _reached_this_tick_all_ids.clear()
        _reached_this_tick_all_ids.update(id(n) for n in _reached_this_tick_all)
        child._has_focus = had_focus
        child.__dict__["_got_focus_called"] = had_got
    return child._status


def _tick_priority_list(ai: PriorityListAI, game_time: float) -> int:
    # ai._ais is sorted lowest priority-int first (highest priority).
    #
    # ✅ CONFIRMED 2026-08-10 against the clean-room reference plus SDK usage.
    # spec/PriorityListAI.md §1: the node "runs the highest-priority runnable
    # child" — but that phrasing does NOT fix the numeric direction, so it was
    # settled from the SDK. AI/Compound/NonFedAttack.py:444-447 builds
    #   AddAI(pEvadeTorps_2, 1) / (pFwdTorpsOrPulseReady, 2)
    #   / (pRearTorpsReady..., 3) / (pICOMoveAround, 4)
    # Dodging incoming torpedoes must outrank a generic move-around fallback,
    # so priority 1 is the MOST urgent: lower int = higher priority, exactly as
    # the sort assumes. Same pattern in Defend.py:102-103 (defendee-attacked 1,
    # idle circling 2). Do not "fix" this to descending.
    #
    # ⚠️ The reference cannot validate the run-tick itself: spec/PriorityListAI.md
    # records IsInterruptable, AddAI(priority), RemoveAIByPriority and the
    # run-tick virtuals (0x490310/0x490140/0x4901e0/0x490270/0x4902a0/0x490340/
    # 0x490560) as SEH-framed WALLS — catalogued but not reconstructed. The
    # decompiled reading below therefore remains our own evidence, unconfirmed
    # by the corpus. Only the ctor and ForEachChild (slot 18) are byte-exact;
    # AllChildrenDone (slot 17) is behaviour-verified at ~87%.
    #
    # Dormancy is NOT a parent-side latch. The decompiled
    # PriorityListAI::Update (0x00490340) keeps a per-entry "skip" byte
    # (entry+0x04) and sets it **only** when a child's Update returns US_DONE
    # (iVar4 == 1) — it never sets that byte for US_DORMANT, and never clears
    # it. So DONE is the only latch; a dormant child keeps its entry and is
    # re-probed every Update through the child's live IsDormant (vtable +0x38).
    # For a PreprocessingAI that predicate (0x0048ec20) re-derives — recursing
    # into the contained subtree — whenever a ForceUpdate is pending, which is
    # exactly what SelectTarget's set-entry / target-gone handlers trigger
    # (AI/Preprocessors.py:1277-1302, "This may change us from being Dormant to
    # being Active"). Treating US_DORMANT as a permanent skip (as this function
    # used to) made an NPC whose target died never re-engage reinforcements
    # that warped in: FedAttack/NonFedAttack/CloakAttack all add SelectTarget as
    # a DIRECT PriorityList child (FedAttack.py:1384), SelectTarget returns
    # PS_SKIP_DORMANT → US_DORMANT when it has no target (Preprocessors.py:1092),
    # and once dormant the node was never reached again, so ForceUpdate could
    # not help — its own cadence gate was never consulted.
    #
    # DONE stays a latch (skip below). A dormant PreprocessingAI child is the
    # one case that must be re-dispatched: its status can only change by running
    # its own Update, so it needs to be reached to leave dormancy. We gate that
    # re-dispatch on its cadence being due (game_time >= _next_update_time) —
    # ForceUpdate resets that to 0.0, and its natural cadence elapses anyway —
    # which is our faithful analog of BC re-probing IsDormant. Other node types
    # are re-evaluated WITHOUT a dispatch and stay skipped while dormant (so they
    # correctly fall off the active path → LostFocus / SetInactive): a
    # ConditionalAI is refreshed by _refresh_conditional_status above; a PlainAI
    # cannot self-leave dormancy (its Update runs only while US_ACTIVE).
    #
    # The established one-active-child-per-tick dispatch is otherwise unchanged:
    # the first eligible child that is dispatched holds the walk (we return),
    # exactly as before. The ONLY behavioural addition is that a due dormant
    # PreprocessingAI now gets a re-evaluation probe: if it reactivates it takes
    # the list; if it stays dormant we roll back its focus bookkeeping and keep
    # walking to lower-priority siblings, just as skipping it would have.
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
        if child._status == US_DONE:
            continue
        if child._status == US_DORMANT:
            # Only a dormant PreprocessingAI that is due gets a re-evaluation
            # probe; anything else stays skipped this tick (see block comment).
            # BuilderAI is a PreprocessingAI subclass — it builds once and is not
            # a dormant combat child, so this is harmless for it.
            if not (isinstance(child, PreprocessingAI)
                    and _note_due_ret(child._next_update_time)
                    and game_time >= child._next_update_time):
                continue
            # Probe it. If it reactivated it holds the list; if it stayed dormant
            # the focus guard already rolled it back, so keep walking (as a skip
            # would have) to lower-priority siblings.
            if _dispatch_priority_child(child, game_time) == US_ACTIVE:
                ai._status = US_ACTIVE
                return ai._status
            continue
        # Active child: dispatch it and hold the walk here — one active child
        # per tick, exactly as before. If its own Update turns it US_DORMANT/
        # US_DONE this tick, the focus guard rolls its focus back (BC clears the
        # focused child's focus when its Update returns dormant/done) and we
        # still stop here rather than walking into lower siblings — preserving
        # the prior one-child-per-tick dispatch.
        if _dispatch_priority_child(child, game_time) == US_ACTIVE:
            ai._status = US_ACTIVE
        return ai._status  # one child per tick (SDK semantics)
    # All children dormant/done or list empty. Preserve the historical tail:
    # only latch the list itself DONE when every child is DONE. (BC additionally
    # reports US_DORMANT for an all-dormant list, but changing this list's own
    # reported status alters how a *parent* list treats it as a nested child,
    # which is outside the scope of the dormant-child re-dispatch fix.)
    if ai._ais and all(c._status == US_DONE for _p, c in ai._ais):
        ai._status = US_DONE
    return ai._status


def _eval_conditional(ai, eval_fn, args):
    """_eval_conditional_python's answer, from the selected walker's code."""
    if _native_walker:
        return _aitree_eval_conditional(ai, eval_fn, args, _GLOBALS)
    return _eval_conditional_python(ai, eval_fn, args)


def _refresh_conditional_status(ai: ConditionalAI) -> None:
    """_refresh_conditional_status_python, run by the selected walker's code."""
    if _native_walker:
        _aitree_refresh_conditional(ai, _GLOBALS)
    else:
        _refresh_conditional_status_python(ai)


def _condition_statuses(ai: ConditionalAI) -> list:
    """`[c.GetStatus() for c in ai._conditions]` (_tick_conditional's read)."""
    if _native_walker:
        return _aitree_condition_statuses(ai, _GLOBALS)
    return _condition_statuses_python(ai)


def _any_condition(ai: ConditionalAI) -> bool:
    """`any(c.GetStatus() != 0 for c in ai._conditions)` (_tick_conditional's
    no-EvalFunc read)."""
    if _native_walker:
        return _aitree_any_condition(ai, _GLOBALS)
    return _any_condition_python(ai)


def _condition_statuses_python(ai: ConditionalAI) -> list:
    return [c.GetStatus() for c in ai._conditions]


def _any_condition_python(ai: ConditionalAI) -> bool:
    return any(c.GetStatus() != 0 for c in ai._conditions)


def _eval_conditional_python(ai, eval_fn, args):
    """Run (or reuse) `eval_fn` over `args`, returning the pre-fold status.

    Returns the PRE-FOLD status, deliberately. The contained-AI DONE fold is
    the caller's job and must not migrate in here: _contained_ai._status
    changes for reasons no condition reflects, so it is not in the key, and
    caching a folded value would hide a finished child for as long as the
    conditions hold steady. Both callers carry the same warning at the fold
    itself -- _refresh_conditional_status has the full version.
    """
    key = tuple(args)
    cache = ai.__dict__.get("_evalfn_cache")
    if cache is not None and cache[0] is eval_fn and cache[1] == key:
        return cache[2]
    raised = False
    try:
        status = eval_fn(*args)
    except Exception:
        raised = True
        status = US_DORMANT
    if status is None:
        status = US_DORMANT
    status = int(status)

    # The memoisable verdict is a property of the FUNCTION, so it is stored
    # WITH the function it was taken for. It used to be a bare bool re-checked
    # only when a live cache entry named a different function -- but a declined
    # function writes no cache entry, so after one decline the re-check could
    # never fire and a later, perfectly pure EvalFunc installed by
    # SetEvaluationFunction was never memoised again. Lost saving only, never a
    # wrong answer, which is why nothing noticed.
    verdict = ai.__dict__.get("_evalfn_memoisable")
    if verdict is None or verdict[0] is not eval_fn:
        verdict = (eval_fn, _memoisable_evalfunc(eval_fn))
        ai.__dict__["_evalfn_memoisable"] = verdict

    # An EXCEPTION is not a pure function of the arguments, so it is the one
    # answer that must not be cached. "Same arguments => same answer" holds for
    # what an EvalFunc RETURNS (None included -- that is a return value); it
    # does not hold for what it raises. Caching the US_DORMANT fallback pinned a
    # transiently-failing branch dormant for as long as the conditions held
    # steady, which is 99.9% of ticks; the pre-memo code retried every tick and
    # that behaviour is restored here. Covered by
    # test_a_raising_evalfunc_is_retried_rather_than_pinned_dormant.
    if verdict[1] and not raised and all(
            type(a) in _MEMO_KEY_TYPES for a in args):
        ai.__dict__["_evalfn_cache"] = (eval_fn, key, status)
    return status


def _refresh_conditional_status_python(ai: ConditionalAI) -> None:
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
        ai._status = _eval_conditional(ai, eval_fn, args)
        # Fold in the contained AI's completion (see _tick_conditional):
        # an EvalFunc that reports US_ACTIVE forever must not mask a
        # contained AI that has already finished.
        #
        # ⚠️ THIS FOLD MUST STAY OUTSIDE THE MEMO. _eval_conditional returns the
        # EvalFunc's own PRE-fold answer, and _contained_ai._status is not part
        # of its key -- it changes for reasons no condition reflects. Folding
        # inside the helper, or caching the folded value here, would freeze a
        # child's completion out of the answer for as long as the conditions
        # hold steady. That is 99.9% of ticks, so a finished child would go
        # permanently invisible and its parent PriorityList/Sequence would
        # never complete. Covered by test_the_contained_done_fold_is_not_cached.
        if (ai._status == US_ACTIVE and ai._contained_ai is not None
                and ai._contained_ai._status == US_DONE):
            ai._status = US_DONE
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
    idx = getattr(ai, "_current_index", 0)

    def _wrap_or_finish(i):
        """Index walked off the end: consume a loop, wrap + re-arm, else finish.

        Returns the new index to keep scanning from, or None if the sequence is
        finished (status already set to US_DONE). ai-architecture.md sec.2:
        wrapping decrements the remaining-loop counter; -1 = loop forever.
        """
        remaining = int(getattr(ai, "_loops_remaining", 1))
        if remaining > 0:
            remaining -= 1
            ai._loops_remaining = remaining
        if remaining == 0:
            ai._current_index = i
            ai._status = US_DONE
            return None
        # Forever (-1) or passes still owed: re-arm the children and wrap.
        for child in ai._ais:
            child._status = US_ACTIVE
        return 0

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
            if int(getattr(ai, "_skip_dormant", 0)):
                # SetSkipDormant(1): a dormant child is stepped over.
                idx += 1
                continue
            # SetSkipDormant(0) — what all nine E7 trees ask for
            # (Maelstrom/Episode7/E7M2/EnemyAI.py:63): a dormant child HOLDS the
            # sequence in place rather than being skipped.
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
    # Scan exhausted without an eligible child (all DONE). A forever/finite
    # loop with passes remaining re-runs from the top next tick; an exhausted
    # sequence is finished.
    ai._current_index = 0
    ai._status = US_ACTIVE if int(getattr(ai, "_loops_remaining", 1)) != 0 else US_DONE
    return ai._status


def _tick_random(ai: RandomAI, game_time: float) -> int:
    """Draw a child from the un-tried pool and tick it; re-draw when it finishes.

    Ground truth (ai-architecture.md sec.2, RandomAI::Update 0x004917f0): the node
    keeps a per-child "already tried" array and draws from the un-tried entries,
    clearing the flag and re-drawing on DORMANT/DONE. Drawing with replacement
    would let the same evasive maneuver repeat back-to-back.

    RandomAI is used as an infinite maneuver picker inside a forever-looping
    SequenceAI (AI/Compound/Parts/NoSensorsEvasive.py:47-52,
    QuickBattle/QuickBattleAI.py:51-58), so it stays US_ACTIVE while a child runs
    and does not terminate just because one child finished.

    An empty RandomAI has nothing to run and completes immediately.
    """
    if not ai._ais:
        ai._status = US_DONE
        return ai._status
    child = ai._current_child
    if child is None or child._status in (US_DONE, US_DORMANT):
        if not ai._untried:
            ai._untried = list(ai._ais)       # cycle exhausted: refill
        child = random.choice(ai._untried)
        ai._untried.remove(child)
        # Re-arm the freshly-drawn child so a previously-finished one runs again.
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
        args = _condition_statuses(ai)
        ai._status = _eval_conditional(ai, eval_fn, args)
        if ai._status == US_ACTIVE and ai._contained_ai is not None:
            tick_ai(ai._contained_ai, game_time)
            # Fold in the contained AI's completion. Some EvalFuncs (SDK
            # static one-shot flags in DockWithStarbase's PriorityList
            # children) report US_ACTIVE forever regardless of the
            # contained AI's progress; without this, the ConditionalAI
            # never reflects that its contained AI actually finished, so
            # the parent PriorityList/Sequence never completes.
            #
            # ⚠️ MUST STAY OUTSIDE THE MEMO -- and note it also has to stay
            # AFTER the tick_ai above, which is what moves the child to
            # US_DONE in the first place. _eval_conditional returns the
            # EvalFunc's PRE-fold answer; _contained_ai._status is not in its
            # key, so caching the folded value would hide a finished child for
            # as long as the conditions hold steady. Same invariant as in
            # _refresh_conditional_status, which carries the longer note.
            if ai._contained_ai._status == US_DONE:
                ai._status = US_DONE
        return ai._status
    active = _any_condition(ai) if ai._conditions else False
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

    # FireScript's own CodeAISet (AI/Preprocessors.py:137-145) registers the
    # SetTarget external function; ai.py's SetPreprocessingMethod now calls
    # it generically at bind time, so no driver-side hack is needed here.

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
    #
    # QUEUED, not dispatched: it fires at the end of the root tick, after the
    # departing nodes' LostFocus, so a handover cannot invert the SDK's
    # save/restore pair. See _flush_pending_got_focus.
    _queue_got_focus(ai)

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

    # Appc bypasses the preprocess switch entirely — running the child
    # unconditionally — when the child is ACTIVE and NOT interruptable
    # (IsInterruptable is BaseAI vtable +0x04, default 1; verified 2026-07-14).
    # A node that calls SetInterruptable(0) is asking not to be pre-empted
    # mid-action by its parent's preprocessor (AI/Compound/Defend.py,
    # AI/Compound/CallDamageAI.py). This must run before the cadence gate and
    # skip BOTH its live and cadence-skipped arms — including the lethal
    # PS_DONE/PS_INVALID mapping — since the whole switch is bypassed, not
    # just one branch of it.
    contained = ai._contained_ai
    if (contained is not None
            and contained._status == US_ACTIVE
            and not contained.IsInterruptable()):
        ai._status = US_ACTIVE
        # No _note_due for THIS node's due time — the one gating site that does
        # not record, deliberately, and _note_due's comment names the
        # exception. While the bypass holds, the preprocessor's Update never
        # runs, so _next_update_time is frozen (usually already in the past) and
        # recording it would pin the walk min-due slot below game_time and force
        # an every-tick walk for a decision that cannot be taken. The contained
        # subtree still records its own gates through the tick_ai below, so
        # nothing that CAN run gets slept through.
        tick_ai(contained, game_time)
        return ai._status

    # Cadence gate: run the preprocessor's own Update only when it is due
    # (game_time >= _next_update_time), mirroring _tick_plain and BC's C++
    # dispatcher, which honours every node's GetNextUpdateTime. The contained
    # AI still dispatches every tick (below) — only the preprocessor's own
    # decision-making is gated.
    #
    # ForceUpdate() resets _next_update_time to 0.0 so an asynchronous event
    # (e.g. a target cloaking) re-runs the preprocessor at its next reached
    # tick instead of after its full cadence. ⚠️ "Next reached tick" is NOT
    # "next tick": with the sleep scheduler (AI_MAX_SLEEP_TICKS) a tree whose
    # walk is asleep is not walked at all, and nothing wakes it — ForceUpdate
    # opens this gate but sends no signal to tick_all_ai. So the re-run lands
    # within the cap, up to ~66 ms later. That is an order of magnitude inside
    # BC's own 200 ms FireScript cadence and is accepted; the cloak-reaction
    # path (SelectTarget's ObjectDecloaked handler) leans on this sentence, so
    # do not restore the old "on the very next tick" claim without also
    # building the wake signal.
    #
    # _note_due sits in the not-due arm only — see the matching note in
    # _tick_plain for why recording an already-past due time cost a whole extra
    # walk of every tree after every execution.
    if game_time >= ai._next_update_time:
        bound = getattr(inst, method)
        if arity >= 1:
            result = _run_script_step(ai, lambda: bound(game_time + 1.0))
        else:
            result = _run_script_step(ai, bound)

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
        _note_due(ai._next_update_time)

        if result == PS_SKIP_ACTIVE:
            ai._status = US_ACTIVE
            _retain_subtree_focus(ai)
            return ai._status
        if result == PS_SKIP_DORMANT:
            ai._status = US_DORMANT
            return ai._status
        if result != PS_NORMAL:
            # PS_DONE (3) and PS_INVALID (4) both map to US_DONE — "this node is
            # finished" — and US_DONE is what tears an AI down (LostFocus ->
            # SetInactive -> unlink + delete). Verified in the binary 2026-07-14
            # (PreprocessingAI::Update switch at 0x48eab1: the default arm of the
            # PS_* switch is US_DONE).
            #
            # Three SDK preprocessors have a PS_DONE path (ManagePower's stub
            # body, FireScript with no target, AvoidObstacles with no ship). All
            # three are in the binary's native registry, so none of those Python
            # bodies runs in the shipped game — and engine/appc/ai_optimized.py
            # mirrors that registry at bind time (a replacement for ManagePower,
            # non-lethal wrappers for the other two). This arm is therefore
            # reached only by a preprocessor the shipped engine did NOT replace,
            # i.e. one whose PS_DONE really does mean "tear me down".
            ai._status = US_DONE
            return ai._status
        # PS_NORMAL falls through to contained_ai dispatch below.
    else:
        _note_due(ai._next_update_time)
        # Cadence-skipped tick: the preprocessor didn't run this tick, so
        # reproduce its last decision rather than blindly dispatching. A
        # targetless SelectTarget that reported PS_SKIP_DORMANT must stay
        # dormant (not run its combat list against a None target) until its
        # next scheduled update or a ForceUpdate. Same three-way mapping as the
        # live branch above — a node that reported PS_DONE stays done.
        last = ai._last_preprocess_status
        if last == PS_SKIP_ACTIVE:
            ai._status = US_ACTIVE
            _retain_subtree_focus(ai)
            return ai._status
        if last == PS_SKIP_DORMANT:
            ai._status = US_DORMANT
            return ai._status
        if last != PS_NORMAL:
            ai._status = US_DONE
            return ai._status
        # PS_NORMAL (or never-run) falls through to contained_ai dispatch.

    ai._status = US_ACTIVE
    if ai._contained_ai is not None:
        tick_ai(ai._contained_ai, game_time)
        # Fold in the contained AI's completion — the same fold
        # _tick_conditional does (see the comment there), and for the same
        # reason: a wrapper that reports US_ACTIVE unconditionally masks a
        # contained AI that has already finished, so the order never ends.
        #
        # This matters for EVERY player helm order, because they are all this
        # shape: AI/Player/InterceptTarget.py:24-29 wraps `Intercept` in an
        # `AvoidObstacles` PreprocessingAI, and OrbitPlanet/FollowObject/etc.
        # follow suit. Without the fold, US_DONE stopped at the leaf: no
        # ET_AI_DONE (so Helm never went back to "Waiting"), the AI was never
        # released, and _tick_plain early-returns for a finished leaf — no
        # further SetSpeed or TurnTowardLocation. The ship simply kept the last
        # commanded velocity and flew straight through its destination.
        #
        # PS_NORMAL only: the two skip branches above return before this point
        # deliberately, reproducing the preprocessor's last decision instead of
        # dispatching, so there is no fresh contained status to fold there.
        if ai._contained_ai._status == US_DONE:
            ai._status = US_DONE
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


def tick_all_ai(game_time: float) -> None:
    """Tick every ship's AI tree with the selected walker (``_native_walker``).

    The native arm runs the roster and its sleep scheduling in C++
    (aitree_tick_all), and each root walk natively too (aitree_tick, through
    a stock tick_ai). The differential harness (tests/helpers/ai_walk_diff.py)
    holds the two arms equal."""
    if _native_walker:
        _tick_all_ai_native(game_time)
    else:
        _tick_all_ai_python(game_time)


def _tick_all_ai_python(game_time: float) -> None:
    """Iterate every ship and tick its attached AI subtree.

    Called once per frame from GameLoop.tick(). Q2 closed at AI-first
    within the tick so this fires before physics + render. Rocks are
    excluded — a rock has no attached AI to tick (rock-class spec §1).
    """
    from engine.appc.ship_iter import iter_non_rock_ships
    from engine.appc import defensive_cloak
    if _AI_BREAKDOWN is not None:
        _AI_TICKS[0] += 1
    max_sleep = AI_MAX_SLEEP_TICKS
    for ship in iter_non_rock_ships():
        # A ship hiding-to-repair is owned by the defensive-cloak controller;
        # suppress its SDK AI so the two cloak drivers never conflict.
        if defensive_cloak.is_defensive(ship):
            continue
        if max_sleep:
            due = ship.__dict__.get("_ai_next_walk_due")
            # Bounded ABOVE as well as below. The stamp is an absolute game
            # time and game time is zeroed on every mission (re)load
            # (host_loop.reset_sdk_globals), so a ship object that survives a
            # reload carries a stamp from the old epoch that `game_time < due`
            # alone would honour forever -- the tree is never walked again and
            # the ship silently stops reacting. Clamping here rather than at
            # the write makes "no ship sleeps longer than the cap" an
            # invariant of the scheduler instead of a rule every future write
            # site has to remember.
            if due is not None and (
                    game_time < due <= game_time + max_sleep * _TICK_SECONDS):
                continue
        ai = ship.GetAI() if hasattr(ship, "GetAI") else None
        if ai is not None:
            _walk_min_due_reset()
            status = tick_ai(ai, game_time)
            if max_sleep:
                # Never sleep past the soonest gate this walk saw, and never
                # past the cap -- see AI_MAX_SLEEP_TICKS on why the cap is the
                # part holding this together.
                ship.__dict__["_ai_next_walk_due"] = min(
                    _walk_min_due_get(),
                    game_time + max_sleep * _TICK_SECONDS)
            # Root-tree completion: announce the end (SDK: so orbit/helm state
            # can react) AND release the conn.
            #
            # BC tears a finished AI down — US_DONE is what drives LostFocus ->
            # SetInactive -> unlink + delete (see the binary note in
            # _tick_preprocessing). ClearAI performs that teardown and announces
            # ET_AI_DONE itself, so it REPLACES the bare fire_ai_done here
            # rather than joining it; announcing twice would drop BC's Helm
            # officer to "Waiting" twice and re-run every id-keyed handler.
            #
            # Leaving a finished tree attached is what made the ship fly through
            # its destination: _PlayerControl.apply arbitrates ownership on
            # `if ai is not None:` with no status check, so a done-but-attached
            # AI kept the conn and the whole ship-motion path — throttle
            # included — was skipped, leaving the ship on the AI's last
            # SetSpeed indefinitely.
            if status == US_DONE and not getattr(ai, "_done_event_fired", False):
                ai._done_event_fired = True
                # Only release the tree if it is STILL the installed one. A
                # completion script may hand the ship its next orders as its
                # last act — AI/Compound/DockWithStarbase.FinishedUndocking
                # ends with MissionLib.SetPlayerAI(..., FlyForward...),
                # commented "replacing this AI" — so by the time the root
                # reports US_DONE the ship can already be carrying something
                # else. Clearing unconditionally destroyed that replacement.
                #
                # Nothing is left dangling in that case: ShipClass.SetAI has
                # already deactivated the outgoing tree and announced it
                # (ships.py:132-138), which is also why we must not announce
                # again here.
                get_ai = getattr(ship, "GetAI", None)
                still_installed = (get_ai() is ai) if callable(get_ai) else True
                if not still_installed:
                    continue
                clear = getattr(ship, "ClearAI", None)
                if callable(clear):
                    clear()
                else:
                    # Bare test doubles without the full ShipClass surface.
                    fire_ai_done(ship, ai)

