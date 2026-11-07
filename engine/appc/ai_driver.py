"""AI tick driver -- the Python half of the native AI tree engine.

The tree is walked top-down each frame by C++ (native/src/host/aitree.{h,cc})
over the live node objects of ai.py; this module keeps what the walk calls back
into (the script-step guard, the dispatch table, the builder activation, the
engine glue) and the names the walk gates on. Mirrors the SDK
ArtificialIntelligence dispatch semantics (sdk/Build/scripts/App.py:4922-5232):

* PlainAI         -- call script_instance.Update() at GetNextUpdateTime() cadence
* PriorityListAI  -- run highest-priority non-DORMANT child (lower int == higher priority)
* SequenceAI      -- run current child; on US_DONE advance, loop per _loop_count
* ConditionalAI   -- if SetEvaluationFunction is wired, call it with each condition's
                     status; fall back to "any condition non-zero -> ACTIVE" for callers
                     that AddCondition without registering an EvalFunc
* PreprocessingAI -- invoke preprocess method, dispatch contained per PS_*

The driver is *not* TimeSliceProcess-based. PlainAI carries its own
_next_update_time field; the driver consults it each tick.

The Python walker itself is gone from the engine: it is frozen as the test
oracle tests/helpers/ai_walker_oracle.py (see the forwarders section below).
"""
import dis
import inspect
import os
import random
import time as _time

from engine.appc.ai import (
    ArtificialIntelligence, PlainAI, PriorityListAI, SequenceAI,
    ConditionalAI, PreprocessingAI, BuilderAI, RandomAI, TGCondition,
)
from engine.appc import sensor_media
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
#
# _pending_got_focus holds the nodes that ARRIVED on the active path this root
# tick, whose GotFocus() has not been dispatched yet. See
# _flush_pending_got_focus for why arrival is deferred to the end of the tick.
_focus_depth = 0
_reached_this_tick: list = []
_reached_this_tick_all: list = []
_reached_this_tick_all_ids: set = set()
_pending_got_focus: list = []


# AI cost breakdown, opt-in via DAUNTLESS_AI_BREAKDOWN=1. Attributes SELF time
# to the node's concrete class, so a parent that spends its tick in children
# shows the children's cost under the children, not under itself.
#
# KEEP -- decided deliberately, replacing an unqualified "TEMPORARY INSTRUMENT"
# label that carried no removal plan and so was never going to be acted on.
# This is the only tool that can say WHICH preprocessor a frame went into, and
# every AI performance question so far has needed exactly that. It is off unless
# the env var is set, and when off the entire cost is one `is not None` test per
# dispatch (the same shape as the dev_mode gates elsewhere in the engine), so
# there is nothing to reclaim by deleting it. Remove it only if the AI tick
# stops being a place performance work happens.
#
# With the native walker (aitree.cc) the breakdown costs a Python frame per
# node: when it is on, the native _dispatch_ai hands each handler to the
# Python _timed_dispatch below, which calls the handler's forwarder (which
# runs the native body). The walk's results are identical, and the self-times
# are those of the native handler bodies plus that forwarder frame, so read
# them as relative weights, never as the cost of the walk with the breakdown
# off (aitree.h says the same).
_AI_BREAKDOWN = {} if os.environ.get("DAUNTLESS_AI_BREAKDOWN") else None
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


_reported_script_errors: set = set()


def _run_script_step(ai, call):
    """Run one SDK script entry point (a leaf Update, a preprocessor method, or
    a GotFocus/LostFocus hook) under BC's policy: a Python exception is
    reported and the frame continues. Returns the call's result, or None on
    failure -- every caller already maps None to "no status change"
    (US_ACTIVE / PS_NORMAL) or simply ignores the return value (the focus
    hooks).

    The failure is recorded on the node for inspection (the AI inspector may
    surface it later) and reported UNCONDITIONALLY -- header line and
    traceback both to stderr, once per (node id, exception type). BC's
    embedded interpreter printed every script traceback to its own console;
    this matches events.py's `_log_broadcast_failure` policy for the same
    reason: a silently-swallowed script crash is worse than a noisy log.
    """
    try:
        return call()
    except Exception as exc:                     # noqa: BLE001 -- policy
        ai._last_script_error = (type(exc).__name__, str(exc))
        key = (ai.GetID(), type(exc).__name__)
        if key not in _reported_script_errors:
            _reported_script_errors.add(key)
            import sys
            import traceback
            ship = ai.GetShip()
            name = ship.GetName() if ship is not None and hasattr(ship, "GetName") else "?"
            print(f"[ai] {name} node '{ai.GetName()}' raised "
                  f"{type(exc).__name__}: {exc} — continuing", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
        return None


def reset_script_error_log() -> None:
    """Clear the per-(node id, exception type) dedup log for _run_script_step.

    node ids are recycled across missions (ArtificialIntelligence._next_id is
    process-lifetime but test/mission-scoped node objects are not), so a
    stale entry could suppress a genuinely new error's dev-mode print after a
    mission swap. Called from tests/conftest.py's autouse
    _reset_leakable_engine_globals."""
    _reported_script_errors.clear()


def ai_breakdown_report(ticks: int = 0) -> str:
    ticks = ticks or _AI_TICKS[0]
    if not _AI_BREAKDOWN:
        return ""
    rows = sorted(_AI_BREAKDOWN.items(), key=lambda kv: -kv[1][0])
    # Reaching into collision_avoidance's private _SCAN_COUNT, knowingly: it is
    # a raw [scans, overrides] counter pair with no public accessor, and the
    # avoidance scan is the single biggest non-AI consumer of the AI tick, so a
    # breakdown that omitted it would mis-attribute its cost. Deferred to call
    # time (not module scope) so the report cannot add an import edge to the
    # engine's startup path. If collision_avoidance ever grows a public counter,
    # switch to it -- this is the only reader.
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

# "Nothing stored for this type yet" -- distinct from the stored None that
# _resolve_dispatch returns for a type matching no handler. See _dispatch_ai.
_UNRESOLVED = object()


def _resolve_dispatch(node_type):
    """Run the ordered isinstance chain once for `node_type`.

    Returns the handler, or None for a node type that matches nothing (the
    caller stores that None and falls back to reading ai._status, as before).
    """
    for cls, handler in (
        (BuilderAI, _tick_builder),
        (PreprocessingAI, _tick_preprocessing),
        (ConditionalAI, _tick_conditional),
        (PriorityListAI, _tick_priority_list),
        (SequenceAI, _tick_sequence),
        (RandomAI, _tick_random),
        (PlainAI, _tick_plain),
    ):
        if issubclass(node_type, cls):
            return handler
    return None


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
    g = getattr(fn, "__globals__", None)
    if g is None:
        return False
    app = g.get("App")

    # Walk nested code objects too. A lambda or nested def inside the EvalFunc
    # compiles to its OWN code object stored in co_consts, so its LOAD_GLOBALs
    # never reach the outer co_names -- without this the gate would admit a
    # function that reads live module state through one level of indirection
    # and the memo would pin its first answer forever. No shipped SDK EvalFunc
    # nests a function today; the gate is the only thing standing between the
    # memo and a stall, so it should be as strong as its docstring claims.
    import types as _types
    pending = [code]
    while pending:
        c = pending.pop()
        if c.co_freevars:
            return False                 # closes over something live
        for name in c.co_names:
            if name in g and g[name] is not app:
                return False
        pending.extend(k for k in c.co_consts
                       if isinstance(k, _types.CodeType))
    return True


# Types a memo key may be built from. The key comparison below is the one `==`
# among the driver's caches (everything else compares with `is`), so what may
# enter a key has to be restricted to things whose `==` means what it says.
# _Stub.__eq__ (engine/core/ids.py) returns isinstance(o, _Stub), so ANY two
# stubs compare equal: a condition whose GetStatus fell through to a stub would
# make every later key equal to the cached one and freeze the node's status.
# ConditionScript always returns a real int today, so this is prevention, not a
# live bug -- but it is exactly the shape docs/stub_heatmap.md exists for, and
# the guard also shuts out any future object with a sloppy __eq__.
#
# `type(a) in`, not isinstance: a subclass may override __eq__, which is the
# whole hazard. Checked on the WRITE only -- a cached key therefore holds
# nothing but scalars, and comparing a scalar against an incoming stub is
# correctly False (int.__eq__ defers, _Stub.__eq__ answers isinstance -> False).
_MEMO_KEY_TYPES = (bool, int, float, str, type(None))


# ── The condition evaluation (native; GetStatus's stock shape) ──────────────
#
# The condition evaluation is native (native/src/host/aitree.cc:
# aitree_refresh_conditional, aitree_eval_conditional, aitree_condition_
# statuses, aitree_any_condition). The public names (_refresh_conditional_
# status, _eval_conditional, _condition_statuses, _any_condition) forward to
# those bindings, so a test patching one of them is honoured by the walk. The
# Python reference they were proven against is the frozen test oracle,
# tests/helpers/ai_walker_oracle.py.
#
# A stock condition's GetStatus is TGCondition's own `return self._status`.
# The native code reads `_status` directly, without the call, only when
# `c.GetStatus` resolves (by Python's own method lookup) to exactly this
# function with this code, taken at import, before anything can patch it;
# anything else (an override, an instance attribute, a patched class) is
# called.
#
# Self-validating: the capture checks that the code it takes really is
# `return self._status` (compared, instruction by instruction, against a
# reference body compiled here; see _same_body). A GetStatus patched BEFORE
# this module is imported is therefore not taken as stock: the capture falls
# back to (None, None), "no stock body", and every GetStatus is called.
def _stock_get_status_shape(self):
    return self._status


def _same_body(code, ref) -> bool:
    """Whether `code` is the body `ref` is: the same parameters, flags (bar
    CO_NESTED, which says only where the function was defined) and no
    closure, and the same instructions with the same resolved arguments
    (constants, by type and value, names, jump targets). A docstring and
    line numbers are not part of the comparison: a docstring is
    co_consts[0], which shifts every LOAD_CONST index without changing what
    is loaded."""
    if (code.co_argcount != ref.co_argcount
            or code.co_posonlyargcount != ref.co_posonlyargcount
            or code.co_kwonlyargcount != ref.co_kwonlyargcount
            or (code.co_flags | inspect.CO_NESTED)
            != (ref.co_flags | inspect.CO_NESTED)
            or code.co_freevars or code.co_cellvars):
        return False

    def body(c):
        return [(i.opname, type(i.argval), i.argval)
                for i in dis.get_instructions(c)]
    return body(code) == body(ref)


def _capture_stock(fn, shape):
    """(fn, its code) when `fn` is a function running `shape`'s body, else
    (None, None): no stock body, so the native side calls it every time."""
    code = getattr(fn, "__code__", None)
    if code is None or not _same_body(code, shape.__code__):
        return None, None
    return fn, code


def _capture_stock_get_status():
    return _capture_stock(TGCondition.__dict__["GetStatus"],
                          _stock_get_status_shape)


_STOCK_CONDITION_GETSTATUS = _capture_stock_get_status()


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

    # A cloaked target, or one inside an identity-hiding medium (an asteroid
    # field or moderate nebula — sensor_media.medium_unknown), is a fuzzy
    # sensor return, not a detailed scan: force hull-centre aim, mirroring
    # the player-side suppression in target_list_view (Contact.
    # subsystems_targetable). We do NOT reach for subsystems_targetable
    # itself here — that record is per-observer and is only ever pushed for
    # the player by perception.perceived_by, so calling contact_for from an
    # AI ship would hand back the PLAYER's answer, not this AI's. Cloak and
    # medium are both absolute state on the target (sensor_media.
    # subsystems_hidden is a plain IsCloaked() / field-strength / concealment
    # read, no observer involved), which is exactly why the same predicate is
    # correct for both sides — and it is what subsystems_targetable is itself
    # derived from.
    #
    # No ENHANCED_SENSOR_CONTEST gate needed: with that flag off, cloak is
    # absolute and can_detect() returns False for a cloaked target, so no AI
    # ever HAS a cloaked ship.GetTarget() to reach this branch at all. A
    # medium-hidden (uncloaked) target has no such gate and is not affected
    # by that flag either way.
    #
    # Re-fetch the target rather than reuse the `target` local above: that
    # local only exists when sub_id resolved to a live subsystem, so it can
    # be unbound here (e.g. idTargetedSubsystem is None) while the ship still
    # has a cloaked GetTarget().
    current_target = ship.GetTarget()
    if current_target is not None and sensor_media.subsystems_hidden(current_target):
        chosen = None

    # Only write on change — avoids churn and drives the dev log (below) on
    # transitions rather than every fire tick.
    if ship.GetTargetSubsystem() is not chosen:
        ship.SetTargetSubsystem(chosen)
        # NO dev log here. This used to print "[ai] <ship> -> targeting <sub>"
        # under --developer on every change, on the theory that a change-only
        # log is quiet. It is not: against a player ship every NPC re-picks a
        # subsystem constantly, and the line buried every other diagnostic in
        # the terminal. If you need this back, count transitions or sample it
        # rather than printing every one -- the AI Inspector already reports
        # target_subsystem per ship, which is the same information on demand.


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
    # Neither this registration nor the three below are ever removed on node
    # teardown (grep for RemoveBroadcastHandler in ai_driver.py/ai.py finds
    # no call site) -- a pre-existing gap this task does not close.

    # The native CodeAISet's other registrations (SDK Preprocessors.py:1094-
    # 1157, commented out there because the native node did this work). Each
    # handler just ForceUpdate()s so the next tick re-selects instead of
    # waiting out the 5 s cadence. GROUP_CHANGED is not registered: no engine
    # producer (see plan Task 11).
    group = getattr(inst, "pTargetGroup", None)
    if group is not None and callable(getattr(inst, "TargetEnteredSet", None)):
        group.SetEventFlag(App.ObjectGroup.ENTERED_SET)
        App.g_kEventManager.AddBroadcastPythonMethodHandler(
            App.ET_OBJECT_GROUP_OBJECT_ENTERED_SET, inst.pEventHandler, "TargetEnteredSet", group)
    if callable(getattr(inst, "OurShipEnteredSet", None)):
        App.g_kEventManager.AddBroadcastPythonMethodHandler(
            App.ET_ENTERED_SET, inst.pEventHandler, "OurShipEnteredSet", pShip)
    if callable(getattr(inst, "ObjectDecloaked", None)):
        # ObjectDecloaked filters on pTargetGroup.IsNameInGroup(destination
        # name) itself (Preprocessors.py:1291-1295), so the broadcast target
        # is None -- events.py:806-810 treats target=None as unfiltered.
        App.g_kEventManager.AddBroadcastPythonMethodHandler(
            App.ET_DECLOAK_BEGINNING, inst.pEventHandler, "ObjectDecloaked", None)

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


# ── Due-time tree walking ────────────────────────────────────────────────────
#
# MEASURED at 100 ships: 100 ship trees are walked per tick and 87% of them
# execute NOTHING -- every node dispatched, every ConditionalAI refreshed, ~772
# node visits, to rediscover that nothing was due. Only ~12 preprocessor
# Updates run per tick across the whole scene, because GetNextUpdateTime gates
# them hard (SelectTarget once per ship per ~3.5 s, AlertLevel once per 60 s).
#
# So a tree records, as it is walked, the EARLIEST _next_update_time it saw,
# and is not walked again until then. Skipping happens only when nothing was
# going to run anyway.
#
# A blanket every-N-ticks stride was tried first and REJECTED on measurement,
# not on taste. It was faster (gl.ai 95-100 -> 52-59 ms at N=4) but it also
# delayed nodes that WERE due -- PlainAI steering leaves run every tick by
# design -- so ships steered coarsely, flew straighter and landed more hits:
# projectiles in flight 146/169 -> 212/217 and hull-damaged ships 52 -> 67/78
# over identical simulated game time. A performance change that makes combat
# more lethal is a gameplay change wearing a disguise.
#
# THE SLEEP IS CAPPED, and that cap is the load-bearing part. A due time is
# only trustworthy for the nodes the walk REACHED; a condition on an inactive
# branch can change and make a lower-priority branch eligible without any
# reached node knowing. Normally _refresh_conditional_status polls for exactly
# that (see the M2Objects symptom in _tick_priority_list), and a sleeping tree
# does not poll. There is no wake signal to lean on instead: TGCondition.
# SetStatus notifies handlers only `if self._active`, and ConditionalAI
# activates its conditions from the node's tree-activation lifecycle, so an
# inactive branch's conditions are silent by design (ai-architecture.md Sec.6).
#
# Capping the sleep bounds that blindness to MAX_SLEEP_TICKS instead of
# eliminating it. At 4 ticks a missed branch switch surfaces within 66 ms,
# against BC's own 200 ms FireScript cadence -- an order of magnitude inside
# the envelope the game was designed around. Raising this cap trades latency
# for walks; removing it needs the wake signal built first.
#
# Set DAUNTLESS_AI_MAX_SLEEP=0 to restore per-tick walking exactly.


def _env_int(name: str, default: int) -> int:
    """Read an int from the environment, falling back on anything unparseable.

    Parsed at IMPORT time, which is why this is not a bare int(): a typo like
    DAUNTLESS_AI_MAX_SLEEP=4x would otherwise raise ValueError out of
    `import engine.appc.ai_driver` and take the whole engine down before a
    single line of logging exists — from a developer convenience knob.
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


AI_MAX_SLEEP_TICKS = max(0, _env_int("DAUNTLESS_AI_MAX_SLEEP", 4))

# Earliest _next_update_time seen during the CURRENT root walk. inf means the
# walk saw no cadence gate at all, which is capped like everything else.
#
# Kept as a local copy of GameLoop.TICK_DELTA because importing engine.core.loop
# here would cycle (loop imports tick_all_ai). Pinned equal to it by
# tests/unit/test_ai_scheduler_invariants.py so the copy cannot silently drift
# if the tick rate ever changes.
_TICK_SECONDS = 1.0 / 60.0

# The AI tree engine's native half (native/src/host/aitree.{h,cc}). A host
# module without one of its names is a STALE binary, and the contract for that
# (CLAUDE.md, Build layout) is an AttributeError naming it -- raised on use, so
# importing this module never fails on it.
try:
    import _dauntless_host as _host
except ImportError:  # pragma: no cover - the engine needs the host module
    _host = None


def _aitree(name):
    fn = getattr(_host, name, None)
    if fn is not None:
        return fn

    def stale(*_a, **_k):
        raise AttributeError(
            "module '_dauntless_host' has no attribute %r" % name)
    return stale


# _note_due(when): record a node's next-update time during the walk in
# progress, into the walk's min-due slot (`if when < slot: slot = when`; the
# slot holds the very object given, so an int due time stays an int). NATIVE
# since phase 6 AI part 4 task 2, so the native roster reads the slot directly;
# the Python walker reaches it through this name, looked up at each call, so a
# monkeypatched _note_due is still what the Python walk calls.
#
# Called from every site that gates on game_time >= _next_update_time and can
# still ACT on that gate, so the tree's sleep can never outlast the soonest
# thing it is waiting for. A site that gates WITHOUT calling this would let its
# node oversleep -- which is why this is a named function and not an inline
# min(), and why tests/unit/test_ai_scheduler_invariants.py fails the build if
# a new gate appears without one.
#
# Two deliberate non-calls, both because there is nothing to wait FOR:
#
#   * the non-interruptable bypass in _tick_preprocessing, where the
#     preprocessor's Update cannot run at all while the bypass holds;
#   * a PlainAI whose script instance has no Update method.
#
# In both cases the node's due time is frozen in the past, so recording it
# would pin the slot below game_time and force an every-tick walk for work that
# cannot happen. Each site carries the reasoning inline.
_note_due = _aitree("aitree_note_due")
# The slot's value, and its reset to float("inf") (once per root walk).
_walk_min_due_get = _aitree("aitree_walk_min_due")
_walk_min_due_reset = _aitree("aitree_walk_min_due_reset")
# The native roster (aitree_tick_all), looked up per call.
_aitree_tick_all = _aitree("aitree_tick_all")
# The native condition evaluation (see _STOCK_CONDITION_GETSTATUS).
_aitree_refresh_conditional = _aitree("aitree_refresh_conditional")
_aitree_eval_conditional = _aitree("aitree_eval_conditional")
_aitree_condition_statuses = _aitree("aitree_condition_statuses")
_aitree_any_condition = _aitree("aitree_any_condition")
# The native walk (aitree_tick): tick_ai, _dispatch_ai and every stock
# _tick_* handler. See _STOCK_WALK.
_aitree_tick = _aitree("aitree_tick")
_GLOBALS = globals()


def _note_due_ret(when: float) -> bool:
    """_note_due in expression position; always True so it can be AND-ed into
    an existing condition without changing it.

    Stays Python on purpose: it calls _note_due through the module global, so a
    monkeypatched _note_due is honoured at this site too (a native twin would
    have to re-check the global on every call to do the same)."""
    _note_due(when)
    return True


# ── The AI tree walker is native; these names forward to it ─────────────────
#
# The tree is walked in C++ (native/src/host/aitree.{h,cc}) over the live
# Python node objects in ai.py; Python stays the only authority for node
# state. The walk itself runs a driver function's body natively only while
# the module global of that name is the stock FORWARDER below, so the name
# stays what it always was: a patch point. A test or mod may wrap or replace
# any of them (the native walk then CALLS the replacement, at the point the
# old Python walker called it), and a wrapper calling the original lands in
# the forwarder, which runs the native body (aitree_run).
#
# The Python walker that used to stand behind these names is gone from the
# engine (Mark, 2026-11-07: ported code keeps no permanent Python copy). It
# is frozen as a test oracle, tests/helpers/ai_walker_oracle.py, which the
# differential harness (tests/helpers/ai_walk_diff.py) runs on its "Python
# side". Adding a node type or a hook to the walk means adding it to the
# native walker, or dispatching it to Python through _DISPATCH_BY_TYPE.
_aitree_run = _aitree("aitree_run")


def tick_all_ai(game_time: float) -> None:
    """Tick every ship's AI tree: the roster and its sleep scheduling, in C++
    (aitree_tick_all). Called once per frame from GameLoop.tick(). Q2 closed at
    AI-first within the tick so this fires before physics + render. Rocks are
    excluded -- a rock has no attached AI to tick (rock-class spec section 1).
    """
    _aitree_tick_all(game_time, _GLOBALS)


def tick_ai(ai, game_time: float) -> int:
    """Tick one AI subtree (the native walk). Every caller -- the rosters, the
    handlers, a script -- comes through this name, so a test patching
    ``tick_ai`` is honoured."""
    return _aitree_tick(ai, game_time, _GLOBALS)


def _dispatch_ai(ai, game_time: float) -> int:
    return _aitree_run("_dispatch_ai", _GLOBALS, ai, game_time)


def _tick_plain(ai, game_time: float) -> int:
    return _aitree_run("_tick_plain", _GLOBALS, ai, game_time)


def _tick_priority_list(ai, game_time: float) -> int:
    return _aitree_run("_tick_priority_list", _GLOBALS, ai, game_time)


def _tick_sequence(ai, game_time: float) -> int:
    return _aitree_run("_tick_sequence", _GLOBALS, ai, game_time)


def _tick_random(ai, game_time: float) -> int:
    return _aitree_run("_tick_random", _GLOBALS, ai, game_time)


def _tick_conditional(ai, game_time: float) -> int:
    return _aitree_run("_tick_conditional", _GLOBALS, ai, game_time)


def _tick_preprocessing(ai, game_time: float) -> int:
    return _aitree_run("_tick_preprocessing", _GLOBALS, ai, game_time)


def _tick_builder(ai, game_time: float) -> int:
    return _aitree_run("_tick_builder", _GLOBALS, ai, game_time)


def _dispatch_priority_child(child, game_time: float) -> int:
    return _aitree_run("_dispatch_priority_child", _GLOBALS, child, game_time)


def _queue_got_focus(node) -> None:
    return _aitree_run("_queue_got_focus", _GLOBALS, node)


def _focus_instance_of(node):
    """The Python script instance that carries a node's focus hooks
    (_script_instance of a PlainAI, _preprocessing_instance of a
    PreprocessingAI)."""
    return _aitree_run("_focus_instance_of", _GLOBALS, node)


def _retain_subtree_focus(ai) -> None:
    return _aitree_run("_retain_subtree_focus", _GLOBALS, ai)


def _dispatch_lost_focus(node) -> None:
    """Call the node's script instance's LostFocus() (if any) and clear the
    focus latches so a later re-entry re-fires GotFocus(). Also called by
    ships._deactivate_ai_tree."""
    return _aitree_run("_dispatch_lost_focus", _GLOBALS, node)


def _reconcile_focus(root_ai, reached) -> None:
    return _aitree_run("_reconcile_focus", _GLOBALS, root_ai, reached)


def _flush_pending_got_focus() -> None:
    return _aitree_run("_flush_pending_got_focus", _GLOBALS)


def _reconcile_active(root_ai, reached) -> None:
    return _aitree_run("_reconcile_active", _GLOBALS, root_ai, reached)


def _refresh_conditional_status(ai: ConditionalAI) -> None:
    _aitree_refresh_conditional(ai, _GLOBALS)


def _condition_statuses(ai: ConditionalAI) -> list:
    return _aitree_condition_statuses(ai, _GLOBALS)


def _any_condition(ai: ConditionalAI) -> bool:
    return _aitree_any_condition(ai, _GLOBALS)


def _eval_conditional(ai, eval_fn, args):
    return _aitree_eval_conditional(ai, eval_fn, args, _GLOBALS)


# The stock _eval_conditional: the native refresh evaluates inline only while
# the module's _eval_conditional is still this function, and calls whatever
# replaced it otherwise.
_STOCK_EVAL_CONDITIONAL = _eval_conditional


# ── The native walk's stock identities ──────────────────────────────────────
#
# The native walk (aitree_tick) runs a driver function's body natively only
# while the module global of that name is still the function defined above,
# with its own code, as captured here at import; anything else in its place
# (a monkeypatch, a wrapper, a reassigned __code__) is CALLED, at the point
# the Python walker would call it. Each global is read at the moment the
# Python walker reads it, so a patch made mid-walk is honoured too.
#
# _STOCK_WALK: global name -> (function, its code at import). The forwarders
# (tick_ai, the four condition-evaluation names, the reconcilers, ...) are
# inlined natively only while they are stock and, for the ones that name a
# separate binding, the binding they would call is still the native one;
# otherwise the forwarder itself is called.
#
# _STOCK_HANDLERS: a stock _tick_* handler -> (its native kind, its code). A
# handler found in _DISPATCH_BY_TYPE (or returned by _resolve_dispatch) runs
# natively only when it is one of these, unchanged. The kinds are the native
# walk's handler numbers (aitree.cc, `enum Kind`), in this order.
# _note_due_ret is the one stock name that is still a Python body (two
# statements, see its docstring); everything else here forwards to native.
def _stock(fn):
    return fn, fn.__code__


_STOCK_WALK = {
    fn.__name__: _stock(fn) for fn in (
        tick_ai, _dispatch_ai, _tick_preprocessing, _dispatch_priority_child,
        _queue_got_focus, _focus_instance_of, _retain_subtree_focus,
        _note_due_ret, _refresh_conditional_status, _condition_statuses,
        _any_condition, _eval_conditional, _reconcile_focus,
        _dispatch_lost_focus, _flush_pending_got_focus, _reconcile_active)
}
_STOCK_HANDLERS = {
    fn: (kind, fn.__code__) for kind, fn in enumerate((
        _tick_plain, _tick_priority_list, _tick_sequence, _tick_random,
        _tick_conditional, _tick_preprocessing, _tick_builder), start=1)
}


# The stock ArtificialIntelligence.SetActive / SetInactive, for the native
# _reconcile_active's one skip. Python calls `node.SetActive()` /
# `node.SetInactive()` on every node of the previous / reached lists; the
# native side makes the same method lookup and calls whatever it finds,
# EXCEPT that a call is skipped when all of these hold (aitree.h, "S3"):
#
#   * the lookup lands on exactly this function, with this code, unbound (no
#     instance attribute shadows it, no subclass overrides it, the class is
#     not patched);
#   * `_is_active_in_tree` reads without running Python (no descriptor of
#     that name on the type, so it comes from the instance dict);
#   * it is exactly True (SetActive) / exactly False (SetInactive).
#
# Then the body below does nothing but read that attribute and return None
# at its first statement, so the call is invisible. Self-validating like
# _STOCK_CONDITION_GETSTATUS: a body that is not the shape below is not taken
# as stock, (None, None), and every call is made.
def _stock_set_active_shape(self):
    if self._is_active_in_tree:
        return
    self._is_active_in_tree = True
    self._on_activated()


def _stock_set_inactive_shape(self):
    if not self._is_active_in_tree:
        return
    self._is_active_in_tree = False
    self._on_deactivated()


_STOCK_SET_ACTIVE = _capture_stock(ArtificialIntelligence.__dict__["SetActive"],
                                   _stock_set_active_shape)
_STOCK_SET_INACTIVE = _capture_stock(
    ArtificialIntelligence.__dict__["SetInactive"], _stock_set_inactive_shape)
