"""Engine-side replacements for the Python preprocessors the original engine
compiled into C++ ("CodeAI"), and the registry that swaps them in.

Mechanism, from the binary (2026-07-14): ``PreprocessingAI::SetContainedAI``
(0x0048E570) does not store the AI it is handed — it calls
``newAI->GetOptimizedVersion()`` (vtable +0x34) and stores the RETURNED object.
``PreprocessingAI`` overrides that slot (0x0048EB20): it reads the bound Python
preprocessor's class name, looks it up in a native registry (DAT_00982A1C), and
on a hit allocates a native node, steals the contained subtree, and deletes the
Python-backed node outright. The BaseAI default (0x00470750) is
``MOV EAX,ECX; RET`` — return ``this``, i.e. "I have no optimized version,
use me".

Four classes are registered in the binary: ``AvoidObstacles``, ``FireScript``,
``ManagePower``, ``SelectTarget``. In the shipped game all four Python ``Update``
bodies are DEAD CODE — the native nodes replace them at bind time. We have no
native versions, so we run those Python bodies. Three of the four therefore need
an entry here, for two different reasons:

* ``ManagePower`` gets a REPLACEMENT (the class below). Its SDK Python body
  (``AI/Preprocessors.py:2148``) is ``# Unused.  return PS_DONE`` — an explicit
  stub. PS_DONE maps to US_DONE, which DESTROYS the AI node. It sits in the live
  FedAttack / NonFedAttack / CloakAttack chain (AlertLevel -> PowerManagement ->
  FleeAttackOrFollow), so running the Python body would delete every Federation
  ship's AI within one 3-second cadence. The ``SetInterruptable(1)`` bypass
  cannot save it: ``FleeAttackOrFollow`` sets that flag itself.
* ``FireScript`` and ``AvoidObstacles`` get NON-LETHAL WRAPPERS. Their SDK Python
  bodies are full working implementations that we NEED and run verbatim — but
  each has one edge that returns PS_DONE:

      FireScript.Update (:284)     `pTarget = self.GetTarget()`
                                   `if not pTarget: return PS_DONE`
      AvoidObstacles.Update (:1688) `if pShip == None: return PS_DONE`

  Those edges are reachable from live doctrine (every Attack doctrine builds a
  FireScript node; targets die and leave sets), and US_DONE is unrecoverable in
  our driver — ``_tick_priority_list`` skips US_DONE children forever. So the
  wrapper delegates every call to the real SDK body and translates ONLY a
  PS_DONE return into PS_NORMAL.

  *** KNOWN DIVERGENCE — READ THIS BEFORE TRUSTING IT. ***
  We do NOT know what the native FireScript / AvoidObstacles return when they
  have no target / no ship. That remains an OPEN QUESTION for the RE project.
  The one thing we know for certain is that it is NOT lethal: a Federation ship
  in the shipped game that loses its target does not lose its AI — it re-acquires
  and keeps fighting.

  THE CHOSEN VALUE IS PS_NORMAL ("run the contained AI"), for two reasons:

  1. It is exactly what shipped before this branch. The old driver mapped PS_DONE
     to "stop calling the preprocessor, fall through and dispatch the child", so
     the node stayed US_ACTIVE and its subtree kept running. PS_NORMAL reproduces
     that behaviour and adds nothing — it is the minimum change that removes the
     lethality. (It is even strictly better: the old mapping *latched* the
     preprocessor off forever, so a FireScript that once lost its target never
     fired again; PS_NORMAL lets it re-run on its next cadence and re-acquire.)
  2. PS_SKIP_DORMANT (the earlier guess) maps to US_DORMANT, and US_DORMANT is a
     ONE-WAY TRAP in our driver: ``_tick_priority_list`` skips US_DORMANT children
     forever (they are never re-dispatched, so they can never leave dormancy), and
     a ``SequenceAI`` with ``skip_dormant = 0`` HOLDS on a dormant child. An
     ``AvoidObstacles`` node is a direct ``SequenceAI`` child in 7+ shipped trees
     (AI/Compound/TractorDockTargets.py:213, Maelstrom/Episode1/E1M1/UndockAI.py:63,
     E1M1_AI_Devore.py:47, E2M0_AI_Warbird.py:260, E2M1_AI_WarbirdTow.py:94,
     E4M6/CenterFieldAI.py:43), so a momentary no-ship tick would permanently wedge
     the sequence. Trading one unrecoverable state for another is no fix.

  The nearest evidence FOR a dormant return is that the SDK's own SelectTarget
  reports its no-target state as PS_SKIP_DORMANT (``eNoTargetPreprocessStatus``) —
  but that is a different class, and it is not worth buying a new wedge with. Read
  PS_NORMAL as "the pre-branch behaviour, minus the lethality", not as faithfulness.

* ``SelectTarget`` needs no protection: its Python body cannot return PS_DONE
  at all (its no-target path returns PS_SKIP_DORMANT), so running it cannot
  kill a node. Pinned by
  ``tests/unit/test_preprocess_done_is_lethal.py::test_select_targets_sdk_body_cannot_return_ps_done``.
  It IS registered (phase 6 AI part 2, Task 3), for speed only: a subclass
  whose one method, ``GetTargetRating``, is native for a stock instance (see
  _native_select_class). ``Update`` and everything else stay the SDK's.

``AlertLevel`` is deliberately absent from both registries — it is not in the
binary's either, which is exactly why *its* Python body correctly returns
PS_NORMAL.
"""

import functools
import math
import os
import sys
import types

import App

from engine.appc import ai_native
from engine.appc import transform_store as _ts
from engine.core import frame_profiler


class ManagePower:
    """Mirror of the native ManagePower CodeAI (ctor 0x00486FA0).

    The native node drives the ship's power subsystem on a 3.0 s cadence
    ([0x0088BEBC] = 3.0f, byte-for-byte the SDK's ``ManagePower.GetNextUpdateTime``),
    reads ``bConservePower`` off the Python instance it replaces, and returns
    PS_NORMAL so the wrapped combat subtree keeps running.

    TODO (follow-up, deliberately not this task): the native node also *writes*
    to the ship's power subsystem (``ship+0x2B0``; ours is
    ``engine/appc/subsystems.py:PowerSubsystem``, reached via
    ``ShipClass.GetPowerSubsystem``) to redistribute power under
    ``bConservePower``. That behaviour is additive and belongs in its own task.
    This class's job is to stop the AI deleting itself, which returning
    PS_NORMAL on the native cadence does exactly.
    """

    def __init__(self, bConservePower=0):
        self.bConservePower = bConservePower

    def GetNextUpdateTime(self):
        return 3.0

    def Update(self, dEndTime):
        # PS_NORMAL: run the contained AI. NEVER PS_DONE — that is lethal.
        return App.PreprocessingAI.PS_NORMAL


# Re-scan cadence for a ship that is ACTIVELY EVADING.
#
# AvoidObstacles.__init__ ships:
#     self.fMinimumUpdateDelay = 0.0  # 0.25
#     self.fMaximumUpdateDelay = 0.25 # 1.25
# The commented values are BC's earlier, slower tuning; the live ones are what
# they turned it down to. They could afford it -- AvoidObstacles is one of the
# four preprocessors GetOptimizedVersion swaps for a NATIVE node, so in the
# shipped game a 60 Hz re-scan is C++. Ours is the Python scan, and at 100
# ships in a 65 km sphere ~44 of them are evading at any moment, each
# re-scanning every tick: 6.5 ms of an 18.5 ms tick, 36% of the whole
# gameloop, spent recomputing an answer that changes negligibly in 16 ms.
#
# Restoring their commented 0.25 is safe because a cadence-skipped tick does
# NOT drop the evasion: _tick_preprocessing's else-branch reproduces the last
# PS_SKIP_ACTIVE, so the contained AI stays suppressed and the ship holds the
# TurnTowardDirection / SetImpulse setpoints already issued. The ship keeps
# evading on the committed heading; only the re-decision waits. Against a 15 s
# fPredictionTime lookahead, a 0.25 s stale decision is 1.7% of the horizon.
#
# Set to 0.0 to restore the SDK's every-tick behaviour exactly.
AVOID_EVADING_UPDATE_DELAY_S = float(
    os.environ.get("DAUNTLESS_AVOID_EVADE_DELAY_S", "0.25"))

# ── First-schedule phase spread (the thundering herd) ───────────────────────
#
# With fMinimumUpdateDelay == fMaximumUpdateDelay == 0.25 and the driver
# rescheduling as `game_time + interval` (ai_driver._tick_preprocessing), the
# cadence is a pure PERIOD with no phase: two nodes that are ever due on the
# same tick are due on the same tick for the rest of the mission, and ships
# spawned in the same frame start that way. Measured at 8 ships, scans per tick
# was [8,0,0,...,0,8,0,...] -- the MEAN dropped 15x but the per-tick PEAK did
# not move, so the frame-time spike the cadence was meant to flatten survived.
#
# One offset applied to the FIRST reschedule breaks the lock permanently: after
# it the node runs at exactly BC's rate, merely out of step with its
# neighbours. It is a phase shift, not a rate change.
#
# Deterministic by construction -- NO `random` in sim code. The offset is a
# function of the ship's object id, so the same ship gets the same phase on
# every run and across a save/restore. See _phase_factor for why the id is
# avalanche-mixed rather than taken modulo directly.
#
# The offset only ever SHORTENS the first interval (factor in (0, 1]), so no
# re-decision is ever pushed past BC's own fMaximumUpdateDelay. Avoidance is a
# safety system; the acceptable direction to err in is "scans sooner".
#
# 16 buckets: the interval is 0.25 s and a tick is 1/60 s, so the schedule has
# 15 distinguishable tick phases. More buckets than that buys nothing (two
# offsets under a tick apart land on the same tick); fewer wastes phases.
_PHASE_BUCKETS = 16
_PHASE_ATTR = "_avoid_phase_applied"

# Fallback ordinal for a node whose ship is not resolvable yet (pCodeAI is
# bound after construction, and the driver can reach GetNextUpdateTime first).
# Deterministic given deterministic construction order, which is what a mission
# script provides.
_PHASE_FALLBACK = [0]


def _phase_key(node) -> int:
    """A stable small integer identifying `node`'s ship, for phase bucketing."""
    # __dict__, not getattr: an engine-backed node inherits TGObject.__getattr__
    # and would hand back a truthy _Stub for a missing pCodeAI.
    ai = node.__dict__.get("pCodeAI")
    get_ship = getattr(ai, "GetShip", None) if ai is not None else None
    if callable(get_ship):
        try:
            ship = get_ship()
        except Exception:
            ship = None
        if ship is not None:
            try:
                obj_id = ship.GetObjID()
            except Exception:
                obj_id = None
            # A _Stub floats/ints to 0 and would put every ship in one bucket,
            # which is the state this exists to leave. Demand a real integer.
            if isinstance(obj_id, int) and not isinstance(obj_id, bool):
                return abs(obj_id)
    _PHASE_FALLBACK[0] += 1
    return _PHASE_FALLBACK[0]


def _phase_factor(node) -> float:
    """Fraction of the nominal interval this node's FIRST reschedule waits.

    In ``(0, 1]`` -- never longer than the cadence it is offsetting.

    A bare ``obj_id % _PHASE_BUCKETS`` is NOT sufficient and was the first
    version of this. Object ids come off one global counter shared with every
    subsystem, hardpoint and property a ship allocates, so consecutive SHIPS
    are strided, not consecutive -- and any stride that is a multiple of the
    bucket count (which a fixed per-ship allocation count easily is) maps every
    ship to the same bucket, restoring the exact herd this removes.

    So the id goes through a full avalanche (multiply / xor-shift / multiply /
    xor-shift) before the modulo, and NOT through "one multiply, then read some
    hand-picked bit window" -- which was the second version and was worse than
    useless: bits 20-23 of ``id * 2654435761`` barely move across small strided
    ids, so an 8-ship crowd collapsed onto 3 tick phases and the measured peak
    went UP. Avalanche first, then take the low bits; measured 5-8 distinct
    phases out of 8 ships at every stride tried (1, 8, 16, 37, 40, 64, 128,
    256).
    """
    h = (_phase_key(node) * 2654435761) & 0xFFFFFFFF
    h ^= h >> 15
    h = (h * 2246822519) & 0xFFFFFFFF
    h ^= h >> 13
    return float((h % _PHASE_BUCKETS) + 1) / _PHASE_BUCKETS


_ENGINE_AVOIDANCE_CLASSES: dict = {}


def _engine_avoidance_class(base: type) -> type:
    """Subclass of the non-lethal wrapper whose ``TestCourseOverride`` is ours.

    A subclass of the NON-LETHAL class, not of the SDK class directly, so the
    PS_DONE de-fanging still applies -- AvoidObstacles.Update returns PS_DONE
    when it has no ship, and US_DONE is unrecoverable in our driver.

    TWO methods are ours and no more: ``TestCourseOverride`` (the world scan --
    the only slow part) and ``GetNextUpdateTime``, which adds the one-off
    first-schedule phase offset described above and is otherwise the SDK value.
    Everything else about the node stays SDK code operating on SDK state: the
    PS_SKIP_ACTIVE return, TurnTowardDirection / SetImpulse, the ``fUpdateDelay``
    the SDK ``Update`` writes, and the pickle hooks. The alias shares the
    original's ``__dict__``, so every parameter the SDK ctor set stays live.

    ⚠️ WHAT IS *NOT* PRESERVED -- the engine scan reads MODULE CONSTANTS, not
    this node's fields. ``course_override_for`` passes only the node (for its
    ship and its ``vOverrideDirection``); the scan then uses
    ``collision_avoidance``'s ``AVOID_PREDICTION_TIME_S``,
    ``AVOID_MINIMUM_RADIUS_GU``, ``AVOID_PERSONAL_SPACE_MULT`` and the
    module-level ``_dont_avoid_types()`` in place of this instance's
    ``fPredictionTime``, ``fMinimumRadius``, ``fPersonalSpace`` and
    ``lDontAvoidTypes``. The fields are still there and still read by the SDK
    ``Update``; they simply no longer steer the scan.

    That is INERT for shipped content -- no stock SDK script customises any of
    the four, and ``tests/unit/test_avoid_obstacles_engine_node.py`` pins each
    against the real ``AI.Preprocessors.AvoidObstacles`` defaults -- but it is a
    real divergence, and a mod that varied any of them per-doctrine would be
    silently ignored. Closing it means threading the four off the node in
    ``course_override_for``; see docs/reference/engine/avoidance-duplication.md.
    """
    cached = _ENGINE_AVOIDANCE_CLASSES.get(base)
    if cached is not None:
        return cached

    def TestCourseOverride(self):
        from engine.appc.collision_avoidance import course_override_for
        return course_override_for(self)

    cls = type("Engine" + base.__name__, (_phased_avoidance_class(base),),
               {"TestCourseOverride": TestCourseOverride})
    _ENGINE_AVOIDANCE_CLASSES[base] = cls
    globals()[cls.__name__] = cls
    return cls


# ── AvoidObstacles: the obstacle scan, native for a stock instance ─────────
#
# Phase 6 AI part 2, Task 2. NeedToAvoid was 19% of AI time at 128 ships
# (SIG-205). The engine TestCourseOverride below is the SDK's
# (AI/Preprocessors.py:1713-1767) with ONE change: the while loop over the
# near objects is one ``combat_ai_avoid_scan`` call, which returns the SDK
# loop's ``lAvoidObjects``, identical by object and order
# (native/src/host/host_bindings.cc, the ``avoid`` namespace;
# native/src/combat/include/dauntless/combat/ai_avoid.h). Every App call
# before the loop, the GetNearObjects / EndObjectIteration pair and
# AvoidObjects (whose random unit vectors stay on their Python stream) are
# the SDK's, in its order. It runs only for an instance the SDK would run
# unchanged (ai_native.preprocessor_is_stock on the three methods below) whose
# NeedToAvoid still sees the engine's App / math surface; anything else runs
# the SDK method itself.

#: The preprocessor methods the native path replaces or calls.
_AVOID_METHODS = ("TestCourseOverride", "NeedToAvoid", "AvoidObjects")


# ── One gate-cost model for the three native kinds ───────────────────────────
#
# Each gate is two halves. The INSTANCE half (preprocessor_is_stock) is
# ai_native's, its class verdict remembered by the host per type version
# (`stockmemo`). The MODULE-SURFACE half -- what an SDK body's globals, the
# engine classes the mirrored readers build and the transform store resolve
# to -- is decided here, in Python, by a _decide_* function that reads only
# dicts and types; the host (`surfacememo`) remembers its answer under the
# version tags of every one of them, read BEFORE deciding, and gives it back
# while all hold. Any insert, replace or delete in one of those dicts, or any
# change to one of those types, and Python decides again on the next call.
# A decision that reads something no tag covers (an SDK function with a
# `_dauntless_wraps` link, a module global bound to a non-module) is decided
# every call. On a Python where the host memos are off (any but 3.11, or a
# failed self-test; native/src/host/host_bindings.cc, `aimemo`) every call
# decides: slower, still exact.

#: The host's surface memo (host_bindings.cc, `surfacememo`): (tags, get,
#: put), () without the host; looked up on first use.
_SURFACE_MEMO = [None]
_SURFACE_MISS = object()


def _surface_memo():
    memo = _SURFACE_MEMO[0]
    if memo is None:
        try:
            import _dauntless_host as h
            memo = (h.ai_memo_tags, h.ai_memo_get, h.ai_memo_put)
        except (ImportError, AttributeError):
            memo = ()
        _SURFACE_MEMO[0] = memo
    return memo


def _memo_answer(key, decide, watched_of, arg):
    """``decide(arg)``, remembered by the host under `key` while every dict
    and type ``watched_of(arg)`` lists (taken before deciding) keeps its
    version tag. ``watched_of`` returns None for a decision no tag covers:
    decided every call. `decide` and `watched_of` are passed by the caller as
    module globals, so a test can count the decisions."""
    memo = _SURFACE_MEMO[0]
    if memo is None:
        memo = _surface_memo()
    if not memo:
        return decide(arg)
    hit = memo[1](key, _SURFACE_MISS)
    if hit is not _SURFACE_MISS:
        return hit
    watched = watched_of(arg)
    tags = memo[0](watched) if watched is not None else None
    answer = decide(arg)
    if tags is not None:
        memo[2](key, watched, tags, answer)
    return answer


def _module_dicts(g, names):
    """The dicts behind `g[name]` for each of `names` a decision reads an
    attribute of: a plain module's ``__dict__``; nothing for a missing name
    (getattr(None, ...) reads nothing). None when one is bound to anything
    else (its attribute lookup is not a dict's: decided every call)."""
    out = ()
    for name in names:
        m = g.get(name)
        if m is None:
            continue
        if type(m) is not types.ModuleType:
            return None
        out += (m.__dict__,)
    return out


def _sdk_function(cls, name):
    """`cls`'s `name` with our wrappers unwrapped, and whether it is the raw
    function (no `_dauntless_wraps` link to follow, so its own dict and
    globals are all a decision about it reads)."""
    raw = getattr(cls, name, None)
    fn = ai_native._unwrap(raw)
    return fn, fn is not None and fn is raw


def _surface_snapshot():
    from engine.appc import objects as _objects
    from engine.appc import planet as _planet
    from engine.appc import transform_store as _ts
    from engine.appc.math import TGPoint3
    point = {n: TGPoint3.__dict__[n] for n in
             ("__init__", "Set", "SetXYZ", "Subtract", "Length",
              "SqrLength", "Dot")}
    return {
        "cast": _objects.PhysicsObjectClass_Cast,
        "point_cls": TGPoint3,
        "point": point,
        "sqrt": math.sqrt,
        # ObjectClass.GetWorldLocation calls engine.appc.objects' get_store.
        "objects": _objects,
        "get_store": _objects.get_store,
        "store_cls": _ts.NativeTransformStore,
        "get_position": _ts.NativeTransformStore.get_position,
        "iteration": _planet._ProximityIteration,
        "next_object": _planet._ProximityIteration.next_object,
        "get_next": _planet.ProximityManager.GetNextObject,
    }


#: What NeedToAvoid's arithmetic and the scan's reads rest on, taken at import
#: (as ai_native's surface snapshot): a later replacement is not stock.
_AVOID_SURFACE = _surface_snapshot()


def _avoid_surface_is_stock(node) -> bool:
    """NeedToAvoid's module still calls the engine's App.PhysicsObjectClass_Cast,
    App.TGPoint3 (its methods unpatched) and math.sqrt, and is the App this
    module calls. Decided per node type (_decide_avoid_surface), remembered
    by the host (_memo_answer)."""
    cls = type(node)
    return _memo_answer(cls, _decide_avoid_surface, _avoid_watched, cls)


def _avoid_watched(cls):
    """What _decide_avoid_surface reads: the node type (its NeedToAvoid,
    through the MRO), that function's dict and globals, App's dict, the
    engine TGPoint3 and the module NeedToAvoid calls math from."""
    fn, raw = _sdk_function(cls, "NeedToAvoid")
    if not raw:
        return None
    g = fn.__globals__
    tail = _module_dicts(g, ("math",))
    if tail is None:
        return None
    return (cls, fn.__dict__, g, App.__dict__,
            _AVOID_SURFACE["point_cls"]) + tail


def _decide_avoid_surface(cls) -> bool:
    fn = ai_native._unwrap(getattr(cls, "NeedToAvoid", None))
    if fn is None:
        return False
    g = fn.__globals__
    app = g.get("App")
    snap = _AVOID_SURFACE
    if app is not App or getattr(app, "PhysicsObjectClass_Cast", None) \
            is not snap["cast"]:
        return False
    point_cls = snap["point_cls"]
    if getattr(app, "TGPoint3", None) is not point_cls:
        return False
    table = point_cls.__dict__
    for name, want in snap["point"].items():
        if table.get(name) is not want:
            return False
    return getattr(g.get("math"), "sqrt", None) is snap["sqrt"]


def _native_store_ok() -> bool:
    """GetWorldLocation reads the native transform store the scan reads:
    the get_store it calls (engine.appc.objects' global) is the boot one and
    hands back the native store (_decide_store, remembered by the host)."""
    return _memo_answer(_STORE_KEYS["avoid"], _decide_store, _store_watched,
                        "avoid")


#: One memo key per kind's store check.
_STORE_KEYS = {"avoid": object(), "select": object(), "fire": object()}


def _store_watched(_kind):
    """What _decide_store reads: engine.appc.objects' and transform_store's
    dicts (get_store, the store singleton, NativeTransformStore) and the
    native store class (its readers)."""
    return (_AVOID_SURFACE["objects"].__dict__, _ts.__dict__,
            _AVOID_SURFACE["store_cls"])


def _decide_store(kind) -> bool:
    """The store `kind`'s mirrored reads read is the native one, its readers
    unpatched: get_position for all; get_rotation_col for select's forward,
    get_rotation for fire's rotations."""
    snap = _AVOID_SURFACE
    get_store = snap["objects"].__dict__.get("get_store")
    if not (get_store is snap["get_store"]
            and type(get_store()) is snap["store_cls"]
            and snap["store_cls"].get_position is snap["get_position"]):
        return False
    if kind == "select":
        return (_ts.NativeTransformStore.get_rotation_col
                is _SELECT_SURFACE["get_rotation_col"])
    if kind == "fire":
        return (_ts.NativeTransformStore.get_rotation
                is _FIRE_SURFACE["get_rotation"])
    return True


def _native_scan_applies(manager, handle) -> bool:
    """The handle is ours and walking it is the engine's GetNextObject."""
    snap = _AVOID_SURFACE
    return (type(handle) is snap["iteration"]
            and getattr(type(manager), "GetNextObject", None) is snap["get_next"]
            and snap["iteration"].next_object is snap["next_object"]
            and "GetNextObject" not in getattr(manager, "__dict__", ()))


#: The host's bindings, looked up on the first native call (the host module
#: is not importable when this module is): [avoid scan, target rating, fire].
_BINDINGS = [None]


def _bindings():
    b = _BINDINGS[0]
    if b is None:
        import _dauntless_host as h
        b = _BINDINGS[0] = (h.combat_ai_avoid_scan, h.combat_ai_target_rating,
                            h.combat_ai_fire_update)
    return b


def _native_test_course_override(self):
    """AvoidObstacles.TestCourseOverride (AI/Preprocessors.py:1713-1767),
    statement for statement, with the loop native."""
    # Get our ship...
    pShip = self.pCodeAI.GetShip()
    if (pShip == None):                              # noqa: E711 (SDK spelling)
        return (None, None)

    pSet = pShip.GetContainingSet()
    if (pSet == None):                               # noqa: E711
        return (None, None)

    # Predict our location in the near future...
    vPredictedLocation = pShip.GetPredictedPosition(
        pShip.GetWorldLocation(),
        pShip.GetVelocityTG(),
        pShip.GetAccelerationTG(),
        self.fPredictionTime)

    # Figure out how far that is from us...
    vDiff = App.TGPoint3()
    vDiff.Set( vPredictedLocation )
    vDiff.Subtract( pShip.GetWorldLocation() )
    fDistance = vDiff.Length()

    fPersonalSpaceRadius = pShip.GetRadius() * self.fPersonalSpace
    fCheckRadius = fDistance + fPersonalSpaceRadius
    if fCheckRadius < self.fMinimumRadius:
        fCheckRadius = self.fMinimumRadius

    pProxManager = pSet.GetProximityManager()
    lAvoidObjects = []
    if (pProxManager != None):                       # noqa: E711
        pObjectIter = pProxManager.GetNearObjects( vPredictedLocation, fCheckRadius )
        found = None
        if _native_scan_applies(pProxManager, pObjectIter):
            # None, with nothing walked, when the ship or this node's
            # parameters are not native reads.
            scan = (_BINDINGS[0] or _bindings())[0]
            found = scan(self, pShip, fPersonalSpaceRadius, pObjectIter)
        if found is not None:
            ai_native.note("avoid", "native")
            lAvoidObjects = found
            ai_native.count("avoid", "avoided", len(lAvoidObjects))
        else:
            # A manager or handle that is not the engine's, or a ship or
            # parameters the scan cannot read: the SDK loop.
            ai_native.note("avoid", "python", "no_mirror")
            pObject = pProxManager.GetNextObject( pObjectIter )
            while (pObject != None):                 # noqa: E711
                if pObject.GetObjID() != pShip.GetObjID():
                    if self.NeedToAvoid( pShip, fPersonalSpaceRadius, pObject ):
                        lAvoidObjects.append( pObject )
                pObject = pProxManager.GetNextObject( pObjectIter )
        pProxManager.EndObjectIteration( pObjectIter )

    return self.AvoidObjects( pShip, lAvoidObjects )


_PHASED_AVOIDANCE_CLASSES: dict = {}


def _phased_avoidance_class(base: type) -> type:
    """Non-lethal `base` plus the one-off first-schedule phase offset, and
    the native obstacle scan for a stock instance (``TestCourseOverride``,
    marked ``_dauntless_native_entry``; see _native_test_course_override).

    Split out of _engine_avoidance_class so the SDK scan gets it too. The
    offset and the evading cadence below were only ever applied to the ENGINE
    scan, which is opt-in — so on the path that actually runs, every ship
    re-scanned in lock-step and an evading ship re-scanned every tick. That went
    unnoticed only because the scan was inert (ProximityManager.GetNextObject
    was a hardcoded `return None`), so no ship ever reached the evading branch.
    """
    cached = _PHASED_AVOIDANCE_CLASSES.get(base)
    if cached is not None:
        return cached

    base_next_update = getattr(base, "GetNextUpdateTime", None)

    def GetNextUpdateTime(self):
        delay = base_next_update(self) if base_next_update is not None else 0.0
        state = self.__dict__
        if state.get(_PHASE_ATTR):
            return delay                       # SDK cadence, untouched
        state[_PHASE_ATTR] = True
        return delay * _phase_factor(self)

    non_lethal = _non_lethal_class(base)

    # Timed as `ai.avoid` (native motion + proximity phase 0): the whole SDK
    # scan, so phase 1's saving reads off a row. functools.wraps keeps the
    # SDK's (self, dEndTime) for ai_driver's arity probe.
    @functools.wraps(base.Update)
    def Update(self, *args, **kwargs):
        with frame_profiler.scope("ai.avoid"):
            return non_lethal.Update(self, *args, **kwargs)

    def TestCourseOverride(self):
        """The SDK's TestCourseOverride with its obstacle loop native, for a
        stock instance (_native_test_course_override); otherwise the SDK's
        own, resolved at call time so a patch is seen."""
        if not ai_native.enabled("avoid"):
            ai_native.note("avoid", "python", "switch")
            return non_lethal.TestCourseOverride(self)
        if not (ai_native.preprocessor_is_stock(self, "AvoidObstacles",
                                                _AVOID_METHODS)
                and _avoid_surface_is_stock(self)):
            ai_native.note("avoid", "python", "not_stock")
            return non_lethal.TestCourseOverride(self)
        if not _native_store_ok():
            ai_native.note("avoid", "python", "no_mirror")
            return non_lethal.TestCourseOverride(self)
        # Counts itself: native only where the scan runs (early returns
        # count nothing).
        return _native_test_course_override(self)
    TestCourseOverride._dauntless_native_entry = True

    cls = type("Phased" + base.__name__, (non_lethal,),
               {"GetNextUpdateTime": GetNextUpdateTime, "Update": Update,
                "TestCourseOverride": TestCourseOverride})
    _PHASED_AVOIDANCE_CLASSES[base] = cls
    globals()[cls.__name__] = cls
    return cls


def _apply_evading_cadence(alias):
    """Restore BC's own commented-out `fMinimumUpdateDelay` (0.25).

    `AI/Preprocessors.py:1624` reads `self.fMinimumUpdateDelay = 0.0 # 0.25`.
    At 0.0 a ship that is evading re-runs the whole world scan EVERY tick, and
    in a crowded fight most ships are evading most of the time: measured at 32
    ships, ~14 scans per tick against the ~8 the 4 Hz cadence predicts, for
    +3.4 ms of sim per tick. A cadence-skipped tick does not drop the evasion —
    ai_driver._tick_preprocessing reproduces the last PS_SKIP_ACTIVE — so the
    ship holds its committed heading and only the re-decision waits.
    """
    if AVOID_EVADING_UPDATE_DELAY_S > 0.0:
        alias.__dict__["fMinimumUpdateDelay"] = AVOID_EVADING_UPDATE_DELAY_S
    return alias


def _wrap_avoid_obstacles(instance):
    """The DEFAULT AvoidObstacles binding: SDK scan, PS_DONE de-fanged, plus
    the phase offset and evading cadence."""
    cls = _phased_avoidance_class(type(instance))
    alias = cls.__new__(cls)
    alias.__dict__ = instance.__dict__
    return _apply_evading_cadence(alias)


def _replace_avoid_obstacles(instance):
    """Swap the SDK's AvoidObstacles scan for the engine-side one.

    Shares the original's ``__dict__`` (as _wrap_non_lethal does), so every
    parameter the SDK ctor set -- fPredictionTime, fMinimumRadius,
    fPersonalSpace, the manoeuvre angles, lDontAvoidTypes -- and every field
    Update mutates stay visible and live.

    "Visible and live" is not "consulted by the scan": see
    _engine_avoidance_class for which of them the engine scan ignores.
    """
    cls = _engine_avoidance_class(type(instance))
    alias = cls.__new__(cls)
    alias.__dict__ = instance.__dict__
    return _apply_evading_cadence(alias)


def _replace_manage_power(instance):
    """Swap the SDK's ManagePower stub for the engine-side class above."""
    # Carry the ctor arg across the swap, as the native ctor does by reading
    # bConservePower off the Python instance. __dict__ lookup, not getattr:
    # TGObject.__getattr__ hands back a truthy _Stub for missing attrs, so
    # getattr's default would never fire on an engine-backed instance.
    params = getattr(instance, "__dict__", {})
    return ManagePower(params.get("bConservePower", 0))


# ── FireScript: the firing cycle, native for a stock instance ────────────
#
# Phase 6 AI part 2, Task 4. FireScript was 11.1% of AI time at 128 ships
# (SIG-205). Its Update -- and every FireScript method it reaches -- runs as
# one ``combat_ai_fire_update`` call (native/src/host/host_bindings.cc, the
# ``fire`` namespace; the arithmetic in native/src/combat/include/dauntless/
# combat/ai_fire.h), statement for statement: every call the SDK makes, its
# side effects above all, is the same Python call in the same order, and the
# instance's attributes are read and written where the SDK reads and writes
# them. Only the mirrored engine reads (positions, rotations, velocities,
# subsystem positions, tube directions) and the vector arithmetic on them are
# native. TargetVisible (the sensor gate's) and StopFiring are called back as
# methods. Task 5 made ChooseTargetSubsystem (with GetTargetableSubsystems,
# RateSubsystemForTargeting, PickTargetSubsystemFromList and our
# GetChildTargets) and ChooseTorpType native the same way: their control flow
# and sums, a subsystem's GetObjID; the RNG draws, the fuzzy logic and the
# torpedo scripts stay the SDK's Python calls, in its order. The PS_DONE ->
# PS_NORMAL mapping (_non_lethal_class) stays around it.

def GetChildTargets(self, pSubsystem):
    """Targetable, still-alive descendants of a non-targetable subsystem.

    Called from the SDK's ChooseTargetSubsystem (Preprocessors.py:832)
    and defined nowhere in the SDK — it belonged to BC's NATIVE
    FireScript, which is unreconstructed. Stated assumption: the only
    reading under which the SDK loop makes sense. Every stock hardpoint
    marks its aggregator systems SetTargetable(0) and their banks/tubes
    targetable (galaxy.py:774-995), so this branch is the common case for
    any explicit TargetSubsystems list (Fleet/DisableTarget, Player/
    Disable*). Without it: AttributeError out of the AI tick.

    FireScript's engine class carries this one function (_non_lethal_class);
    the native Update runs its statements itself for an instance whose type
    resolves GetChildTargets to it, unshadowed (_fire_update), and this
    module's GetChildTargets, int, range and hasattr unchanged (the fire
    surface): change one, change the binding (host_bindings.cc,
    fire::child_targets).
    """
    out = []
    n = int(pSubsystem.GetNumChildSubsystems()) if hasattr(pSubsystem, "GetNumChildSubsystems") else 0
    for i in range(n):
        child = pSubsystem.GetChildSubsystem(i)
        if child is None:
            continue
        if child.IsTargetable() and child.GetCondition() > 0:
            out.append(child)
        else:
            out.extend(GetChildTargets(self, child))
    return out


#: The GetChildTargets the native Update mirrors, taken at import.
_GET_CHILD_TARGETS = GetChildTargets


#: Every FireScript method the native Update replaces or calls (Task 5 made
#: ChooseTargetSubsystem, the helpers it reaches and ChooseTorpType native).
#: A mod overriding any of them runs the SDK Update. Our GetChildTargets is
#: not an SDK function; its own gate is _fire_helpers_stock.
_FIRE_METHODS = (
    "Update", "GetTarget", "TargetInRange", "TargetVisible", "StopFiring",
    "ChooseTargetSubsystem", "GetTargetableSubsystems",
    "RateSubsystemForTargeting", "PickTargetSubsystemFromList",
    "FireSystemAtTarget", "ConfigureWeaponSystem", "WeaponTooDangerous",
    "ChooseTorpType", "CheckGoodShot", "GetWeaponInfo",
    "PredictTargetLocation",
)

#: The builtins the SDK bodies call (len, range, float, the loader's
#: `list(d.keys())` and its __import__ lambda's isinstance / str): the native
#: code uses CPython's own.
_FIRE_BUILTINS = ("len", "range", "isinstance", "str", "float", "list")

#: The builtins our GetChildTargets calls, and its own recursion.
_CHILD_GLOBALS = ("int", "range", "hasattr", "GetChildTargets")


def _fire_surface_snapshot():
    import builtins
    import operator
    from engine.appc import math as _engine_math
    from engine.appc import objects as _objects
    from engine.appc import ships as _ships
    from engine.appc import subsystems as _subsystems
    from engine.appc import transform_store as _ts
    from engine.appc.math import TGMatrix3, TGPoint3
    point_names = ("__init__", "Set", "SetXYZ", "Subtract", "Length",
                   "SqrLength", "Dot", "Add", "Unitize", "MultMatrixLeft")
    matrix_names = ("__init__", "Transpose", "set_from_tuple")
    # (namespace, keys): each key must still hold exactly what it held at
    # import. The modules whose bodies the readers mirror build the engine
    # TGPoint3 / TGMatrix3, whose methods (and math.sqrt behind Length) the
    # arithmetic reproduces.
    tables = (
        (_engine_math.__dict__, ("TGPoint3", "TGMatrix3", "_math")),
        (math.__dict__, ("sqrt",)),
        (_objects.__dict__, ("TGPoint3", "TGMatrix3")),
        (_ships.__dict__, ("TGPoint3",)),
        (_subsystems.__dict__, ("TGPoint3",)),
        (TGPoint3.__dict__, point_names),
        (TGMatrix3.__dict__, matrix_names),
        # PredictTargetLocation's reads run ahead of this cast: the engine's
        # pure isinstance test only (Task 5).
        (App.__dict__, ("PhysicsObjectClass_Cast",)),
        # GetChildTargets' globals: this module's own (unshadowed builtins,
        # its recursion), then the builtins themselves.
        (globals(), _CHILD_GLOBALS),
        (builtins.__dict__, _CHILD_GLOBALS[:3]),
    )
    # Flat, so one C-level pass checks them all (_fire_surface_globals):
    # each table's own live `get` (a class's is its mappingproxy's), its key,
    # and what that key held.
    gets = tuple(d.get for d, keys in tables for _k in keys)
    keys = tuple(k for _d, ks in tables for k in ks)
    # What the host memo watches (_fire_surface_globals): each table's own
    # dict, a class by its type (whose version tag covers its __dict__).
    watched = [d for d, _keys in tables if isinstance(d, dict)]
    watched += [TGPoint3, TGMatrix3]
    return {
        "watched": tuple(watched),
        "gets": gets,
        "keys": keys,
        "values": tuple(map(operator.call, gets, keys)),
        "call": operator.call,
        "builtin_names": _FIRE_BUILTINS,
        "builtins": tuple(getattr(builtins, n) for n in _FIRE_BUILTINS),
        "is_": operator.is_,
        "get_rotation": _ts.NativeTransformStore.get_rotation,
    }


#: What FireScript's native arithmetic rests on, taken at import (as
#: _AVOID_SURFACE): a later replacement is not stock.
_FIRE_SURFACE = _fire_surface_snapshot()


def _fire_helpers_stock(inst) -> bool:
    """The instance runs our GetChildTargets: its type resolves the name to
    that very function and its own dict does not shadow it."""
    return (getattr(type(inst), "GetChildTargets", None) is _GET_CHILD_TARGETS
            and "GetChildTargets" not in inst.__dict__)


def _decide_fire_surface(g):
    """`g` (an SDK FireScript's globals) if they are stock: the engine's App,
    CPython's builtins (len, range, float, and the loader's `list(...)` and
    __import__ lambda's isinstance / str), and underneath, the engine TGPoint3
    / TGMatrix3 its mirrored readers build (methods unpatched, math.sqrt
    behind Length), the engine's pure App.PhysicsObjectClass_Cast and
    GetChildTargets' own globals. None otherwise."""
    if g.get("App") is not App or not g.keys().isdisjoint(_FIRE_BUILTINS):
        return None
    snap = _FIRE_SURFACE
    is_ = snap["is_"]
    b = g.get("__builtins__")
    table = b if isinstance(b, dict) else getattr(b, "__dict__", None)
    if table is None:
        return None
    # Identity, never ==; a deleted name reads None, which nothing was.
    get = table.get
    if (all(map(is_, map(get, snap["builtin_names"]), snap["builtins"]))
            and all(map(is_, map(snap["call"], snap["gets"], snap["keys"]),
                        snap["values"]))):
        return g
    return None


def _fire_surface_globals(base):
    """The globals the SDK FireScript (`base`) runs on -- its Update's
    __globals__, which the binding loads App and the builtins from -- if they
    are stock (_decide_fire_surface), else None. Remembered by the host
    (_memo_answer) under the tags of `base` (its Update), that function's own
    __dict__ (a `_dauntless_wraps` link), its globals and their builtins, and
    the snapshot's tables; an Update with a `_dauntless_wraps` link is
    decided every call."""
    return _memo_answer(base, _decide_fire_globals, _fire_watched, base)


def _fire_watched(base):
    fn, raw = _sdk_function(base, "Update")
    if not raw:
        return None
    g = fn.__globals__
    b = g.get("__builtins__")
    table = b if isinstance(b, dict) else getattr(b, "__dict__", None)
    if type(table) is not dict:
        return None
    return (base, fn.__dict__, g, table) + _FIRE_SURFACE["watched"]


def _decide_fire_globals(base):
    fn = ai_native._unwrap(getattr(base, "Update", None))
    if fn is None:
        return None
    return _decide_fire_surface(fn.__globals__)


def _fire_store_ok() -> bool:
    """GetWorldLocation and GetWorldRotation read the native store the
    binding reads (_decide_store, remembered by the host)."""
    return _memo_answer(_STORE_KEYS["fire"], _decide_store, _store_watched,
                        "fire")


def _fire_update(self, base, args, kwargs):
    """FireScript.Update, native for a stock instance; otherwise the SDK's,
    resolved at call time so a patch is seen. A call shape other than the
    SDK's (self, dEndTime) runs the SDK's too, which raises its own
    TypeError."""
    if not ai_native.enabled("fire"):
        ai_native.note("fire", "python", "switch")
        return base.Update(self, *args, **kwargs)
    if len(args) == 1 and not kwargs:
        end_time = args[0]
    elif not args and len(kwargs) == 1 and "dEndTime" in kwargs:
        end_time = kwargs["dEndTime"]
    else:
        ai_native.note("fire", "python", "no_mirror")
        return base.Update(self, *args, **kwargs)
    sdk_globals = None
    if ai_native.preprocessor_is_stock(self, "FireScript", _FIRE_METHODS) \
            and _fire_helpers_stock(self):
        sdk_globals = _fire_surface_globals(base)
    if sdk_globals is None:
        ai_native.note("fire", "python", "not_stock")
        return base.Update(self, *args, **kwargs)
    if not _fire_store_ok():
        ai_native.note("fire", "python", "no_mirror")
        return base.Update(self, *args, **kwargs)
    ai_native.note("fire", "native")
    fire = (_BINDINGS[0] or _bindings())[2]
    return fire(self, end_time, sdk_globals)


_NON_LETHAL_CLASSES: dict = {}


def _non_lethal_class(base: type) -> type:
    """Build (once per SDK class) a subclass whose only difference is that a
    PS_DONE return from the SDK's ``Update`` becomes PS_NORMAL.

    A subclass, not a delegating proxy, because the driver and the SDK bodies
    duck-type all over the instance (``inst.__dict__["idTargetedSubsystem"]``,
    ``lWeapons``, ``pCodeAI``, ``DamageEvent``, ``GotFocus``/``LostFocus``,
    ``CodeAISet``…). Inheritance forwards every one of them to the real SDK code
    with zero surface to keep in sync.
    """
    cached = _NON_LETHAL_CLASSES.get(base)
    if cached is not None:
        return cached

    # FireScript's Update is native for a stock instance (_fire_update); every
    # other class runs the SDK's.
    run_update = _fire_update if base.__name__ == "FireScript" else None

    # functools.wraps, so the driver's inspect.signature() arity probe
    # (ai_driver._tick_preprocessing) still sees the SDK's (self, dEndTime) and
    # passes the end time through.
    @functools.wraps(base.Update)
    def Update(self, *args, **kwargs):
        if run_update is not None:
            result = run_update(self, base, args, kwargs)
        else:
            result = base.Update(self, *args, **kwargs)
        if result == App.PreprocessingAI.PS_DONE:
            # *** THE DIVERGENCE. *** The shipped engine never ran this Python
            # body — it ran a native class whose no-target/no-ship return value
            # we do NOT know (still an open question for the RE project). We know
            # only that it was NOT lethal: BC ships that lose a target keep their
            # AI and re-acquire.
            #
            # PS_NORMAL = "run the contained AI". That is EXACTLY what the driver
            # did with PS_DONE before this branch, so this reproduces the
            # shipping behaviour minus the lethality and introduces no new state.
            # PS_SKIP_DORMANT was considered and rejected: US_DORMANT is a one-way
            # trap in our driver (_tick_priority_list skips dormant children
            # forever; a skip_dormant=0 SequenceAI — which is how 7+ shipped trees
            # parent AvoidObstacles — HOLDS on one). See the module docstring.
            return App.PreprocessingAI.PS_NORMAL
        return result

    if run_update is not None:
        Update._dauntless_native_entry = True

    members = {
        "Update": Update,
        "__doc__": (
            "SDK %s with its lethal PS_DONE return translated to "
            "PS_NORMAL. See engine/appc/ai_optimized.py." % base.__name__
        ),
    }
    if base.__name__ == "FireScript":
        members["GetChildTargets"] = GetChildTargets
    bases = (base,)
    if base.__name__ == "FireScript":
        # BC's binary swaps FireScript for its native OptimizedFireScript
        # (App.py:5186, a PreprocessingAI subclass carrying the control
        # surface). TacticalMenuHandlers.GetPlayerFiringAIScripts:1861 finds
        # the player's fire nodes by isinstance against that class — so the
        # wrapper must BE one. The SDK FireScript already defines every
        # method the binding lists (Preprocessors.py:172-230).
        from engine.appc.ai import OptimizedFireScript
        bases = (base, OptimizedFireScript)
    cls = type(base.__name__ + "_NonLethal", bases, members)
    _NON_LETHAL_CLASSES[base] = cls
    # Register the dynamic class in the module globals so pickle can find it at
    # unpickle time via attribute lookup. Repeated calls are idempotent due to
    # the cache check above (we only create one class per base type).
    globals()[cls.__name__] = cls
    return cls


def _wrap_non_lethal(instance):
    """Return a non-lethal alias of ``instance``.

    The alias shares the original's ``__dict__`` (same state object, no copy),
    so post-bind mutation by SDK callers — ``AddWeaponSystem``, ``SetTarget``,
    the subsystem-choice bookkeeping — is visible through both, and the driver's
    ``inst.__dict__`` probes keep working. The original is then discarded, as the
    shipped engine discards the Python-backed node it replaces.
    """
    cls = _non_lethal_class(type(instance))
    alias = cls.__new__(cls)
    alias.__dict__ = instance.__dict__
    return alias


# ── SelectTarget: candidate ratings, native for a stock instance ─────────
#
# Phase 6 AI part 2, Task 3. GetTargetRating was 20.7% of AI time at 128 ships
# (SIG-205), mostly its popularity loop over every ship in the set. The engine
# subclass overrides that one method: for an instance the SDK would run
# unchanged it is one ``combat_ai_target_rating`` call (native/src/host/
# host_bindings.cc, the ``rating`` namespace; the sum in native/src/combat/
# include/dauntless/combat/ai_rating.h), bit-identical to the SDK body, with
# popularity from the native set index. FindGoodTarget -- the candidate step,
# the sensor gate's wrapper and its fallback, which all call
# self.GetTargetRating -- stays the SDK's. Anything the native call cannot
# answer exactly runs the SDK body for that call.

#: The preprocessor methods the native path replaces or calls.
_SELECT_METHODS = ("GetTargetRating",)


def _select_surface_snapshot():
    from engine.appc import math as _engine_math
    from engine.appc import object_types as _object_types
    from engine.appc import objects as _objects
    from engine.appc import transform_store as _ts
    from engine.appc.properties import ShipProperty
    from engine.appc.ships import ShipClass
    return {
        "acos": math.acos,
        "pi": math.pi,
        "engine_math": _engine_math,
        "objects": _objects,
        "object_types": _object_types,
        "resolve_class": _object_types.resolve_class,
        "ship_property": ShipProperty,
        "ship_class": ShipClass,
        "get_rotation_col": _ts.NativeTransformStore.get_rotation_col,
    }


#: What GetTargetRating's arithmetic rests on, taken at import (as
#: _AVOID_SURFACE): a later replacement is not stock.
_SELECT_SURFACE = _select_surface_snapshot()


def _select_surface_app(base):
    """The App the SDK GetTargetRating (on `base`, the SDK class) reads --
    its __globals__["App"], which the binding is handed -- if its surface is
    stock (_decide_select_surface), else None. Remembered by the host
    (_memo_answer)."""
    return _memo_answer(base, _decide_select_surface, _select_watched, base)


def _select_watched(base):
    """What _decide_select_surface reads: `base` (its GetTargetRating), that
    function's dict and globals, the math module it calls, App's dict, the
    engine TGPoint3 and the modules behind GetWorldLocation's arithmetic,
    and everything GetClassObjectList(App.CT_SHIP) resolves through:
    object_types and its registry, sys.modules' engine.appc.ships and the
    set index module."""
    fn, raw = _sdk_function(base, "GetTargetRating")
    if not raw:
        return None
    g = fn.__globals__
    snap = _SELECT_SURFACE
    tail = _module_dicts(g, ("math",))
    sqrt_mod = _module_dicts(snap["engine_math"].__dict__, ("_math",))
    ot = snap["object_types"]
    by_tag = ot.__dict__.get("_BY_TAG")
    ships = sys.modules.get("engine.appc.ships")
    if tail is None or sqrt_mod is None or type(by_tag) is not dict \
            or type(ships) is not types.ModuleType:
        return None
    from engine.appc import set_index as _set_index
    return (base, fn.__dict__, g, App.__dict__, snap["objects"].__dict__,
            _AVOID_SURFACE["point_cls"], snap["engine_math"].__dict__,
            ot.__dict__, by_tag, sys.modules, ships.__dict__,
            _set_index.__dict__) + tail + sqrt_mod


def _decide_select_surface(base):
    """The SDK GetTargetRating still sees the engine's App, math.acos /
    math.pi, the TGPoint3 GetWorldLocation and GetWorldForwardTG build
    (methods unpatched, math.sqrt behind Length), and an App.CT_SHIP that
    GetClassObjectList resolves to the ShipClass the set index buckets: its
    App, else None."""
    fn = ai_native._unwrap(getattr(base, "GetTargetRating", None))
    if fn is None:
        return None
    g = fn.__globals__
    snap = _SELECT_SURFACE
    app = g.get("App")
    if app is not App:
        return None
    m = g.get("math")
    if getattr(m, "acos", None) is not snap["acos"] \
            or getattr(m, "pi", None) is not snap["pi"]:
        return None
    avoid = _AVOID_SURFACE
    point_cls = avoid["point_cls"]
    if snap["objects"].__dict__.get("TGPoint3") is not point_cls:
        return None
    table = point_cls.__dict__
    for name, want in avoid["point"].items():
        if table.get(name) is not want:
            return None
    sqrt_mod = snap["engine_math"].__dict__.get("_math")
    if getattr(sqrt_mod, "sqrt", None) is not avoid["sqrt"]:
        return None
    # GetClassObjectList(App.CT_SHIP): resolve_class, ShipProperty -> ShipClass.
    ot = snap["object_types"]
    if ot.__dict__.get("resolve_class") is not snap["resolve_class"]:
        return None
    cls = ot.resolve_class(App.CT_SHIP)
    if cls is snap["ship_property"]:
        ships = sys.modules.get("engine.appc.ships")
        cls = getattr(ships, "__dict__", {}).get("ShipClass")
    if cls is not snap["ship_class"]:
        return None
    # The class GetClassObjectList's set index buckets as ships (imported on
    # first use, as sets.py imports it).
    from engine.appc import set_index as _set_index
    if _set_index.__dict__.get("_ShipClass") is not cls:
        return None
    return app


def _select_store_ok() -> bool:
    """GetWorldLocation and GetWorldForwardTG read the native store the
    rating reads (_decide_store, remembered by the host)."""
    return _memo_answer(_STORE_KEYS["select"], _decide_store, _store_watched,
                        "select")


_NATIVE_SELECT_CLASSES: dict = {}


def _native_select_class(base: type) -> type:
    """Build (once per SDK class) a subclass of `base` whose ONLY method is
    ``GetTargetRating`` (marked ``_dauntless_native_entry``): native for a
    stock instance, else `base`'s, resolved at call time so a patch is seen.

    A subclass sharing the SDK instance's ``__dict__`` (as _wrap_non_lethal),
    so the driver's duck-typed _ensure_select_target_initialized
    (``DamageEvent``, ``dDamageReceived``, the event handlers), every SDK
    method, ``isinstance(inst, SelectTarget)`` and the sensor gate's patch of
    the SDK class's FindGoodTarget all see the SDK's class and state."""
    cached = _NATIVE_SELECT_CLASSES.get(base)
    if cached is not None:
        return cached

    def GetTargetRating(self, pTarget):
        """The SDK's GetTargetRating, native for a stock instance."""
        if not ai_native.enabled("select"):
            ai_native.note("select", "python", "switch")
            return base.GetTargetRating(self, pTarget)
        app = None
        if ai_native.preprocessor_is_stock(self, "SelectTarget",
                                           _SELECT_METHODS):
            app = _select_surface_app(base)
        if app is None:
            ai_native.note("select", "python", "not_stock")
            return base.GetTargetRating(self, pTarget)
        if not _select_store_ok():
            ai_native.note("select", "python", "no_mirror")
            return base.GetTargetRating(self, pTarget)
        rating = (_BINDINGS[0] or _bindings())[1](self, pTarget, app)
        if type(rating) is float:
            ai_native.note("select", "native")
            return rating
        if type(rating) is int:            # the SDK's -1: no ship (uncounted)
            return rating
        # A call the native path cannot answer exactly: the SDK's, whole.
        ai_native.note("select", "python", rating)
        return base.GetTargetRating(self, pTarget)
    GetTargetRating._dauntless_native_entry = True

    cls = type(base.__name__ + "_Native", (base,), {
        "GetTargetRating": GetTargetRating,
        "__doc__": ("SDK %s with GetTargetRating native for a stock "
                    "instance. See engine/appc/ai_optimized.py."
                    % base.__name__),
    })
    _NATIVE_SELECT_CLASSES[base] = cls
    # Picklable by name, as _non_lethal_class's classes.
    globals()[cls.__name__] = cls
    return cls


def _wrap_select_target(instance):
    """The SelectTarget binding: the SDK instance's state under the engine
    subclass (_native_select_class)."""
    cls = _native_select_class(type(instance))
    alias = cls.__new__(cls)
    alias.__dict__ = instance.__dict__
    return alias


# Python preprocessor class NAME -> factory(original_instance) -> the object the
# engine actually stores. Mirrors the binary's DAT_00982A1C name registry; see
# the module docstring for why three of its four entries are here and what kind
# of object each one yields.
OPTIMIZED_PREPROCESSORS: dict = {
    "ManagePower": _replace_manage_power,     # real replacement (SDK body is a stub)
    # PS_DONE de-fanged; the Update native for a stock instance (_fire_update).
    "FireScript": _wrap_non_lethal,
    # SDK scan, PS_DONE de-fanged, plus the phase offset and evading cadence.
    # This entry has always done TWO jobs and only one of them was the problem:
    # the engine scan (removed below, opt-in) and protection against
    # AvoidObstacles' lethal PS_DONE path, which a shipless node hits. Dropping
    # the whole entry would have taken the protection with it --
    # test_preprocess_done_is_lethal caught exactly that.
    "AvoidObstacles": _wrap_avoid_obstacles,
    # SDK body throughout, GetTargetRating native for a stock instance.
    "SelectTarget": _wrap_select_target,
}

# ── AvoidObstacles: OFF by default, and why ────────────────────────────────
#
# The engine-side scan is opt-in via DAUNTLESS_ENGINE_AVOIDANCE=1. Default is
# the SDK's own AvoidObstacles.
#
# It shipped enabled and caused a live gameplay regression: 3 Keldons vs the
# player in QuickBattle flew around, fired an opening volley, then stopped
# engaging, with shields visibly dropping and raising. The chain:
#
#   our scan calls "evading" far more often than the SDK's -- 47.7% of pairs
#   pass the convergence gate while 1.48% are genuinely converging
#     -> Update returns PS_SKIP_ACTIVE
#     -> _tick_preprocessing honours that by returning WITHOUT ticking the
#        contained AI, so the whole attack subtree goes unreached
#     -> _reconcile_focus dispatches LostFocus across it
#     -> AlertLevel.LostFocus restores the pre-combat alert level (SHIELDS DOWN)
#        and FireScript.LostFocus calls StopFiring() (FIRING STOPS)
#
# Measured, 100 ships, combat_stress, median tick:
#
#   engine scan, as shipped        2.78 ms   <- attack subtree suppressed
#   engine scan, not suppressing   4.13 ms
#   SDK AvoidObstacles             2.91 ms
#
# So essentially the whole measured win was the suppression, not a cheaper
# scan: stop it switching combat off and the engine scan is ~40% SLOWER than
# the SDK's. Reverting costs ~5% of a median tick, and that 5% is the price of
# ships actually fighting -- payable under any correct fix.
#
# The code is kept, not deleted, because the *idea* is sound and the follow-up
# is well-defined: make the scan genuinely cheaper, and measure it against a
# NON-SUPPRESSING baseline (the 4.13 ms row) rather than against the shipped
# number, which measures the bug.
#
# tests/integration/test_avoidance_does_not_suppress_combat.py holds the line.
if os.environ.get("DAUNTLESS_ENGINE_AVOIDANCE") == "1":
    # Swaps the non-lethal wrapper above for the engine scan, which is itself
    # non-lethal (_engine_avoidance_class maps PS_DONE -> PS_NORMAL too).
    OPTIMIZED_PREPROCESSORS["AvoidObstacles"] = _replace_avoid_obstacles


def optimized_version_of(instance):
    """Appc's ``GetOptimizedVersion``, dispatched by class name.

    Returns the engine-side object on a registry hit, or the original instance
    unchanged otherwise — matching the C++ default, which returns ``this``.
    """
    if instance is None:
        return instance
    factory = OPTIMIZED_PREPROCESSORS.get(type(instance).__name__)
    if factory is None:
        return instance
    return factory(instance)
