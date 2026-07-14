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
  PS_DONE return into PS_SKIP_DORMANT.

  *** KNOWN DIVERGENCE — READ THIS BEFORE TRUSTING IT. ***
  We do NOT know what the native FireScript / AvoidObstacles return when they
  have no target / no ship. That is an OPEN QUESTION for the RE project. The one
  thing we know for certain is that it is NOT lethal: a Federation ship in the
  shipped game that loses its target does not lose its AI — it re-acquires and
  keeps fighting. PS_SKIP_DORMANT ("nothing to do this tick; don't run the
  child") is our choice, not an observed value. The nearest evidence for it is
  that the SDK's own SelectTarget reports its no-target state as
  PS_SKIP_DORMANT (``eNoTargetPreprocessStatus``). This is a guess constrained by
  one hard fact — do not read it as faithfulness.

* ``SelectTarget`` is deliberately NOT registered, even though the binary
  replaces it. Its Python body cannot return PS_DONE at all (its no-target path
  returns PS_SKIP_DORMANT), so running it cannot kill a node — it needs no
  protection. Pinned by
  ``tests/unit/test_preprocess_done_is_lethal.py::test_select_targets_sdk_body_cannot_return_ps_done``.

``AlertLevel`` is deliberately absent from both registries — it is not in the
binary's either, which is exactly why *its* Python body correctly returns
PS_NORMAL.
"""

import functools

import App


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


def _replace_manage_power(instance):
    """Swap the SDK's ManagePower stub for the engine-side class above."""
    # Carry the ctor arg across the swap, as the native ctor does by reading
    # bConservePower off the Python instance. __dict__ lookup, not getattr:
    # TGObject.__getattr__ hands back a truthy _Stub for missing attrs, so
    # getattr's default would never fire on an engine-backed instance.
    params = getattr(instance, "__dict__", {})
    return ManagePower(params.get("bConservePower", 0))


_NON_LETHAL_CLASSES: dict = {}


def _non_lethal_class(base: type) -> type:
    """Build (once per SDK class) a subclass whose only difference is that a
    PS_DONE return from the SDK's ``Update`` becomes PS_SKIP_DORMANT.

    A subclass, not a delegating proxy, because the driver and the SDK bodies
    duck-type all over the instance (``inst.__dict__["idTargetedSubsystem"]``,
    ``lWeapons``, ``pCodeAI``, ``DamageEvent``, ``GotFocus``/``LostFocus``,
    ``CodeAISet``…). Inheritance forwards every one of them to the real SDK code
    with zero surface to keep in sync.
    """
    cached = _NON_LETHAL_CLASSES.get(base)
    if cached is not None:
        return cached

    # functools.wraps, so the driver's inspect.signature() arity probe
    # (ai_driver._tick_preprocessing) still sees the SDK's (self, dEndTime) and
    # passes the end time through.
    @functools.wraps(base.Update)
    def Update(self, *args, **kwargs):
        result = base.Update(self, *args, **kwargs)
        if result == App.PreprocessingAI.PS_DONE:
            # *** THE DIVERGENCE. *** The shipped engine never ran this Python
            # body — it ran a native class whose no-target/no-ship return value
            # we do NOT know (open question for the RE project). We know only
            # that it was NOT lethal: BC ships that lose a target keep their AI
            # and re-acquire. PS_DONE -> US_DONE is unrecoverable in our driver,
            # so we translate to PS_SKIP_DORMANT ("nothing to do this tick; do
            # not run the child"), which is also how the SDK's own SelectTarget
            # reports a no-target state. A constrained guess, not faithfulness.
            return App.PreprocessingAI.PS_SKIP_DORMANT
        return result

    cls = type(
        base.__name__ + "_NonLethal",
        (base,),
        {
            "Update": Update,
            "__doc__": (
                "SDK %s with its lethal PS_DONE return translated to "
                "PS_SKIP_DORMANT. See engine/appc/ai_optimized.py." % base.__name__
            ),
        },
    )
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


# Python preprocessor class NAME -> factory(original_instance) -> the object the
# engine actually stores. Mirrors the binary's DAT_00982A1C name registry; see
# the module docstring for why three of its four entries are here and what kind
# of object each one yields.
OPTIMIZED_PREPROCESSORS: dict = {
    "ManagePower": _replace_manage_power,     # real replacement (SDK body is a stub)
    "FireScript": _wrap_non_lethal,           # SDK body, PS_DONE de-fanged
    "AvoidObstacles": _wrap_non_lethal,       # SDK body, PS_DONE de-fanged
}


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
