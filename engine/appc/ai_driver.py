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
from engine.appc.sensor_detection import is_hidden_by_cloak
# Module level, not deferred inside _dispatch_ai. ship_death imports nothing
# from here, so there is no cycle to break -- and _dispatch_ai runs ~12.5 times
# per ship per tick, so the deferred form was 127,200 importlib._handle_fromlist
# calls in a 600-tick profile at 17 ships.
from engine.appc import ship_death

US_ACTIVE = ArtificialIntelligence.US_ACTIVE
US_DONE = ArtificialIntelligence.US_DONE
US_DORMANT = ArtificialIntelligence.US_DORMANT
PS_NORMAL = PreprocessingAI.PS_NORMAL
PS_SKIP_ACTIVE = PreprocessingAI.PS_SKIP_ACTIVE
PS_SKIP_DORMANT = PreprocessingAI.PS_SKIP_DORMANT
PS_DONE = PreprocessingAI.PS_DONE


# Focus-loss lifecycle state. tick_ai is single-threaded (one ship at a time),
# so module-level scratch is safe. _reached_this_tick collects the
# PreprocessingAI and PlainAI nodes reached (== focused) during the current
# root tick. _reached_this_tick_all collects EVERY node type reached (==
# active in the tree, ai-architecture.md Sec.6 BaseAI SetActive/SetInactive)
# -- the driver for Task 4's ConditionScript.SetActive forwarding.
#
# Unlike _reached_this_tick_all (identity-deduped below, see _dispatch_ai),
# _reached_this_tick has no dedup. This is not an oversight: every container
# that appends to it (_tick_priority_list, _tick_sequence, _tick_conditional,
# _tick_preprocessing, _tick_random, _tick_builder) dispatches AT MOST ONE
# child per root tick, so a PreprocessingAI/PlainAI leaf cannot be reached
# twice in the same root tick and a duplicate can't be constructed.
_focus_depth = 0
_reached_this_tick: list = []
_reached_this_tick_all: list = []
_reached_this_tick_all_ids: set = set()


def tick_ai(ai, game_time: float) -> int:
    """Tick one AI subtree; reconcile preprocessor focus and tree-activation
    at the root call.

    The outermost tick_ai call (one per ship, from tick_all_ai) is the root: it
    collects which PreprocessingAI nodes were reached (== on the active path ==
    focused) this tick, then dispatches LostFocus() to any node that was focused
    last tick but not this one -- and, generally, calls SetActive()/
    SetInactive() on every node as it enters/leaves the active dispatch path.
    Recursive calls into children just dispatch."""
    global _focus_depth, _reached_this_tick, _reached_this_tick_all, _reached_this_tick_all_ids
    is_root = _focus_depth == 0
    if is_root:
        # The out-of-action slot is scoped to one root tick: a new root means a
        # new ship, and a ship that died since the last root tick must be
        # re-asked.
        _ooa_cache[0] = None
        _reached_this_tick = []
        _reached_this_tick_all = []
        _reached_this_tick_all_ids = set()
    _focus_depth += 1
    try:
        status = _dispatch_ai(ai, game_time)
    finally:
        _focus_depth -= 1
    if is_root and ai is not None:
        _reconcile_focus(ai, _reached_this_tick)
        _reconcile_active(ai, _reached_this_tick_all)
    return status


def _dispatch_ai(ai, game_time: float) -> int:
    """Type-dispatch one AI node (the former body of tick_ai)."""
    if ai is None:
        return US_DONE
    # Inert-coast gate: a dying/dead ship issues no new orders.
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

    handler = _DISPATCH_BY_TYPE.get(type(ai))
    if handler is None:
        handler = _resolve_dispatch(type(ai))
        _DISPATCH_BY_TYPE[type(ai)] = handler
    if handler is None:
        return ai._status
    if _AI_BREAKDOWN is not None:
        return _timed_dispatch(handler, ai, game_time)
    return handler(ai, game_time)


# TEMPORARY INSTRUMENT (DAUNTLESS_AI_BREAKDOWN=1). Attributes SELF time to the
# node's concrete class, so a parent that spends its tick in children shows the
# children's cost under the children, not under itself.
import os as _os
import time as _time
_AI_BREAKDOWN = {} if _os.environ.get("DAUNTLESS_AI_BREAKDOWN") else None
_AI_CHILD_TIME = [0.0]
_AI_TICKS = [0]


def _timed_dispatch(handler, ai, game_time):
    outer_child = _AI_CHILD_TIME[0]
    _AI_CHILD_TIME[0] = 0.0
    t0 = _time.perf_counter()
    try:
        return handler(ai, game_time)
    finally:
        total = _time.perf_counter() - t0
        self_time = total - _AI_CHILD_TIME[0]
        key = type(ai).__name__
        _inst = ai.__dict__.get("_preprocessing_instance")
        if _inst is not None:
            key = "pp:" + type(_inst).__name__
        rec = _AI_BREAKDOWN.get(key)
        if rec is None:
            _AI_BREAKDOWN[key] = [self_time, 1]
        else:
            rec[0] += self_time
            rec[1] += 1
        _AI_CHILD_TIME[0] = outer_child + total


def ai_breakdown_report(ticks: int = 0) -> str:
    ticks = ticks or _AI_TICKS[0]
    if not _AI_BREAKDOWN:
        return ""
    rows = sorted(_AI_BREAKDOWN.items(), key=lambda kv: -kv[1][0])
    from engine.appc.collision_avoidance import _SCAN_COUNT
    out = ["  avoidance scans/tick %.1f  (of which overriding %.1f)"
           % (_SCAN_COUNT[0] / max(ticks, 1), _SCAN_COUNT[1] / max(ticks, 1)),
           "  ai node self-time         ms/tick    visits/tick"]
    for name, (secs, calls) in rows:
        out.append("    %-24s %7.3f %10.1f"
                   % (name[:24], secs * 1000.0 / max(ticks, 1), calls / max(ticks, 1)))
    return chr(10).join(out)


# Resolved handler per EXACT node type. The isinstance chain below runs once
# per distinct class and is then a dict lookup -- it averaged 3.25 isinstance
# calls per dispatch, 414,000 in a 600-tick profile at 17 ships.
#
# Keyed on the exact type, so inheritance is still honoured: the chain (which
# is ORDER-SENSITIVE -- a class that is both a BuilderAI and a PreprocessingAI
# must resolve to builder, as it did before) is what populates the cache, so
# whatever it would have chosen is what gets stored.
# [ship, is_out_of_action] for the CURRENT root tick only; see _dispatch_ai.
_ooa_cache: list = [None, False]


_DISPATCH_BY_TYPE: dict = {}


def _resolve_dispatch(node_type):
    """Run the ordered isinstance chain once for `node_type`.

    Returns the handler, or None for a node type that matches nothing (the
    caller then falls back to reading ai._status, as before).
    """
    probe = node_type
    for cls, handler in (
        (BuilderAI, _tick_builder),
        (PreprocessingAI, _tick_preprocessing),
        (ConditionalAI, _tick_conditional),
        (PriorityListAI, _tick_priority_list),
        (SequenceAI, _tick_sequence),
        (RandomAI, _tick_random),
        (PlainAI, _tick_plain),
    ):
        if issubclass(probe, cls):
            return handler
    return None


def _reconcile_focus(root_ai, reached) -> None:
    """Dispatch LostFocus() to nodes focused last tick but not this one.

    Identity-based: `reached` holds the PreprocessingAI and PlainAI nodes
    ticked this root tick (see _tick_preprocessing / _tick_plain). Any node in
    the root's previous focused set that is not among them has left the active
    dispatch path."""
    reached_ids = {id(n) for n in reached}
    for node in getattr(root_ai, "_focused_preprocessors", ()):
        if id(node) not in reached_ids:
            _dispatch_lost_focus(node)
    root_ai._focused_preprocessors = list(reached)


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
    SetActive/SetInactive are called unconditionally here."""
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
        lost()
    node._has_focus = False
    node.__dict__["_got_focus_called"] = False


def _dispatch_got_focus(node) -> None:
    """Call the node's script instance's GotFocus() once per activation.

    SDK leaves put real work here: StarbaseAttack.GotFocus starts firing
    (AI/PlainAI/StarbaseAttack.py:54). Guarded by a sentinel in __dict__ so
    repeat ticks don't re-fire; _dispatch_lost_focus clears it.

    A PlainAI ticked before SetScriptModule() lands has no instance yet
    (inst is None) -- the latch must NOT be set on that tick, or the real
    script's GotFocus would never fire once the module does land.
    """
    if node.__dict__.get("_got_focus_called", False):
        return
    inst = _focus_instance_of(node)
    if inst is None:
        return
    got = getattr(inst, "GotFocus", None)
    if callable(got):
        got()
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
    _dispatch_got_focus(ai)

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
    # Reschedule from the script's reported interval. Appc's PlainAI::Update
    # bridge returns 0.0 when the Python call fails, which makes the AI run
    # every tick (ai-architecture.md sec.3: "There is no default interval in
    # C++") — matches PlainAI::GetNextUpdateTime (0x0048d320).
    next_update_fn = getattr(inst, "GetNextUpdateTime", None)
    next_update = next_update_fn() if callable(next_update_fn) else None
    interval = float(next_update) if next_update is not None else 0.0
    ai._next_update_time = game_time + interval
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
    had_focus = child._has_focus
    had_got = child.__dict__.get("_got_focus_called", False)
    tick_ai(child, game_time)
    if child._status != US_ACTIVE:
        del _reached_this_tick[focus_n:]
        del _reached_this_tick_all[all_n:]
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


# ── ConditionalAI evaluation memo ────────────────────────────────────────────
#
# A priority list picks its winner by refreshing every ConditionalAI child it
# scans, for each list on the active path, every tick. At 100 ships that is
# ~350-400 refreshes per tick, ~5,500 per frame -- and MEASURED, 99.9% of them
# are handed condition statuses identical to the previous tick, producing a
# different status 0.01% of the time. The conditions are event-driven
# (proximity sweeps, timers, damage), so between events there is nothing to
# recompute.
#
# The statuses are still READ every time -- that is how we know nothing changed,
# and no memo can skip it. What this removes is the EvalFunc call behind them.
#
# HONEST SIZING -- read this before quoting the change either way.
#
# In-game hit rate is 99.9% with 0.0% declined, so it does what it says. The
# wall-clock effect, six ALTERNATING paired runs at 100 ships (gl.ai, memo on
# minus memo off, in ms):
#
#     +1.70  -7.49  -0.62  -14.03  +3.05  -10.61     mean -4.7
#
# Four of six favour it, but the paired standard deviation is ~7 ms against a
# 4.7 ms effect (t ~ 1.6, p ~ 0.16). So: NOT a regression -- that much is
# settled -- and probably a small gain, but not one this sample can claim.
# Do not cite it as a measured win. Do not let a future profile blame it for a
# loss either. If you need the real number, it needs ~20 pairs, and the whole
# refresh path is only ~13 ms of a ~330 ms frame, so it is unlikely to be worth
# the machine time.
#
# The reason the ceiling is low: the EvalFuncs are three-line boolean
# combinators, so building the key costs about what calling one costs. The
# memo is kept for being simpler and provably equivalent, not for speed.
#
# The read itself could only be skipped with a dirty flag, and that is BLOCKED,
# not merely unbuilt: TGCondition.SetStatus already pushes ConditionChanged to
# its handlers, but the push is gated on `if self._active`, so an inactive
# condition changes status silently -- the exact drift this polling refresh
# exists to fix (the M2Objects symptom in _tick_priority_list). Solve the
# inactive case before attempting it.
#
# Soundness rests on the EvalFunc being a pure function of its arguments. That
# was checked across the corpus rather than assumed: 458 evaluation functions
# in sdk/ and engine/, of which 450 read only their parameters and App
# constants. The 8 exceptions are all AI/Compound/ChainFollow.py, whose
# EvalFuncs read a MODULE-LEVEL GLOBAL `iIndex` that CreateAI assigns
# (`global iIndex; iIndex = kShips.index(...)`). It is stable within a tick but
# moves whenever another ChainFollow AI is built, which would strand a memo.
#
# So the memo is gated per function, not taken on trust.


def _memoisable_evalfunc(fn) -> bool:
    """True when `fn` provably depends only on its arguments (and App).

    co_names holds global reads AND attribute names indistinguishably, so the
    test asks a narrower question that is decidable: does the name resolve to
    something in the function's own module globals, and if so, is it App? An
    attribute name like US_ACTIVE is not a module global, so it is ignored;
    ChainFollow's `iIndex` IS one, so it is caught. Erring toward declining is
    the safe direction -- a declined function just keeps the old behaviour.

    Conservative in one way worth knowing: a function reading a US_* constant
    imported directly into its module is declined too. Real SDK EvalFuncs reach
    those through App.ArtificialIntelligence, an attribute chain, which is why
    450 of 458 pass.
    """
    code = getattr(fn, "__code__", None)
    if code is None:
        return False                     # builtin / callable object: decline
    if code.co_freevars:
        return False                     # closes over something live
    g = getattr(fn, "__globals__", None)
    if g is None:
        return False
    app = g.get("App")
    for name in code.co_names:
        if name in g and g[name] is not app:
            return False
    return True


def _eval_conditional(ai, eval_fn, args):
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
    try:
        status = eval_fn(*args)
    except Exception:
        status = US_DORMANT
    if status is None:
        status = US_DORMANT
    status = int(status)
    memoisable = ai.__dict__.get("_evalfn_memoisable")
    if memoisable is None or (cache is not None and cache[0] is not eval_fn):
        memoisable = _memoisable_evalfunc(eval_fn)
        ai.__dict__["_evalfn_memoisable"] = memoisable
    if memoisable:
        ai.__dict__["_evalfn_cache"] = (eval_fn, key, status)
    return status


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
        args = [c.GetStatus() for c in ai._conditions]
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
    # Gate: FireScript instances only. lWeapons is the FireScript marker;
    # idTargetedSubsystem is set in FireScript.__init__ so it lives in
    # __dict__ (bypass the _Stub __getattr__ that would otherwise mask a
    # missing attr).
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

    # A cloaked target is a fuzzy sensor return, not a detailed scan: force
    # hull-centre aim, mirroring the player-side suppression in
    # target_list_view (Contact.subsystems_targetable). We do NOT reach for
    # subsystems_targetable itself here — that record is per-observer and is
    # only ever pushed for the player by perception.perceived_by, so calling
    # contact_for from an AI ship would hand back the PLAYER's answer, not
    # this AI's. Cloak is absolute state on the target (is_hidden_by_cloak is
    # a plain IsCloaked() check), which is exactly why the same predicate is
    # correct for both sides — and it is what subsystems_targetable is itself
    # derived from.
    #
    # No ENHANCED_SENSOR_CONTEST gate needed: with that flag off, cloak is
    # absolute and can_detect() returns False for a cloaked target, so no AI
    # ever HAS a cloaked ship.GetTarget() to reach this branch at all.
    #
    # Re-fetch the target rather than reuse the `target` local above: that
    # local only exists when sub_id resolved to a live subsystem, so it can
    # be unbound here (e.g. idTargetedSubsystem is None) while the ship still
    # has a cloaked GetTarget().
    current_target = ship.GetTarget()
    if current_target is not None and is_hidden_by_cloak(current_target):
        chosen = None

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
    _dispatch_got_focus(ai)

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
        tick_ai(contained, game_time)
        return ai._status

    # Cadence gate: run the preprocessor's own Update only when it is due
    # (game_time >= _next_update_time), mirroring _tick_plain and BC's C++
    # dispatcher, which honours every node's GetNextUpdateTime. The contained
    # AI still dispatches every tick (below) — only the preprocessor's own
    # decision-making is gated. ForceUpdate() resets _next_update_time to 0.0
    # so an asynchronous event (e.g. a target cloaking) re-runs the
    # preprocessor on the very next tick instead of after its full cadence.
    if game_time >= ai._next_update_time:
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

        if result == PS_SKIP_ACTIVE:
            ai._status = US_ACTIVE
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
        # Cadence-skipped tick: the preprocessor didn't run this tick, so
        # reproduce its last decision rather than blindly dispatching. A
        # targetless SelectTarget that reported PS_SKIP_DORMANT must stay
        # dormant (not run its combat list against a None target) until its
        # next scheduled update or a ForceUpdate. Same three-way mapping as the
        # live branch above — a node that reported PS_DONE stays done.
        last = ai._last_preprocess_status
        if last == PS_SKIP_ACTIVE:
            ai._status = US_ACTIVE
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
    if _AI_BREAKDOWN is not None:
        _AI_TICKS[0] += 1
    for ship in iter_ships():
        # A ship hiding-to-repair is owned by the defensive-cloak controller;
        # suppress its SDK AI so the two cloak drivers never conflict.
        if defensive_cloak.is_defensive(ship):
            continue
        ai = ship.GetAI() if hasattr(ship, "GetAI") else None
        if ai is not None:
            status = tick_ai(ai, game_time)
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
