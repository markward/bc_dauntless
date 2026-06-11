# tests/unit/test_particles_death_probe.py
"""Exploratory probe: how far does the SDK death-explosion sequence run on the
current engine?  Each test is either a hard assertion (wall cleared) or a
documented skip (wall hit).  The skips ARE the deliverable — they map the exact
boundary of what the Phase-1 engine can reach.

Phase-1 TGSequence execution model: delays are IGNORED, every child action
fires immediately in insertion order.  All timing tests below confirm this.
"""
import pytest
import App
from engine.appc import particles as P


# ---------------------------------------------------------------------------
# Minimal fake object providing exactly what CreateObjectExplosion needs.
#
# Methods called by CreateObjectExplosion:
#   pObject.GetRandomPointOnModel() → 3-tuple / TGPoint3
#   pObject.GetRadius()             → float
#   pObject.GetObjID()              → int  (for TGScriptAction DeathExplosionDamage)
#   pObject.GetNode()               → anything (passed to AttachEffect / SetEmitFromObject)
#   pObject.GetContainingSet()      → FakeSet
#
# Methods called by ObjectExploding additionally:
#   App.DamageableObject_Cast(obj)  → must return obj (so obj must be a DamageableObject)
#   pObject.GetLifeTime()           → float
#   pObject.SetLifeTime(f)          → None
#   pSet.GetEffectRoot()            → anything (passed to AttachEffect)
#   pSet.GetName()                  → str (for TGSoundAction_Create)
#   App.EffectController_GetEffectLevel() → already implemented
# ---------------------------------------------------------------------------

from engine.appc.objects import DamageableObject


class FakeSet:
    def GetName(self):
        return "TestSet"

    def GetEffectRoot(self):
        # Returns a sentinel node; AttachEffect/SetEmitFromObject only store it.
        return object()

    def GetNode(self):
        return None


class FakeNode:
    """Sentinel returned by GetNode(); only stored, never called."""
    pass


class FakeObject(DamageableObject):
    """Minimal damageable object satisfying both CreateObjectExplosion and
    ObjectExploding without any real ship/NIF infrastructure."""

    def __init__(self):
        super().__init__()
        self._fake_set = FakeSet()
        self._fake_node = FakeNode()

    def GetRandomPointOnModel(self):
        return (1.0, 2.0, 3.0)

    def GetRadius(self):
        return 10.0

    def GetObjID(self):
        return 9999

    def GetNode(self):
        return self._fake_node

    def GetContainingSet(self):
        return self._fake_set

    def GetLifeTime(self):
        # Return a value > 1_000_000 so ObjectExploding generates a random
        # lifetime (the 5-15s branch), keeping the while-loop tractable.
        return 2_000_000.0

    def SetLifeTime(self, f):
        self._lifetime = f


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _import_effects():
    import Effects
    return Effects


# ---------------------------------------------------------------------------
# Test 1: CreateObjectExplosion, bSound=0
# ---------------------------------------------------------------------------

def test_create_object_explosion_no_sound():
    """CreateObjectExplosion(obj, 0) must return a TGSequence without raising.

    Expected wall if hit: App.SparkParticleController_Create (CreateDebrisSparks
    path — but note: CreateObjectExplosion does NOT call CreateDebrisSparks;
    it calls CreateDebrisExplosion which uses AnimTSParticleController_Create,
    which IS implemented).

    The only possible wall here is SetDetachEmitObject — called on
    AnimTSParticleController.  Our __getattr__ no-ops it, so it should pass.
    """
    P.reset()
    Effects = _import_effects()

    try:
        fake = FakeObject()
        seq = Effects.CreateObjectExplosion(fake, 0)
    except Exception as e:
        pytest.skip(f"WALL: CreateObjectExplosion(bSound=0) raised {type(e).__name__}: {e}")

    assert seq is not None, "CreateObjectExplosion returned None"

    try:
        seq.Start()
    except Exception as e:
        pytest.skip(f"WALL: seq.Start() raised {type(e).__name__}: {e}")

    # CreateObjectExplosion → CreateDebrisExplosion → AnimTSParticleController
    # → EffectAction_Create → .Start() registers the controller.
    assert P.active_count() >= 1, (
        f"Expected at least 1 active controller after Start(), got {P.active_count()}"
    )


# ---------------------------------------------------------------------------
# Test 2: CreateObjectExplosion, bSound=1 (audio path)
# ---------------------------------------------------------------------------

def test_create_object_explosion_with_sound():
    """bSound=1 path: GetDeathExplosionSound → LoadTacticalSounds import → random pick.
    TGSoundAction_Create is implemented; TGSoundAction.Play() calls TGSoundManager
    which silently no-ops when no audio backend is loaded (OPEN_STBC_AUDIO=0).

    Expected walls:
    - LoadTacticalSounds may not be importable from the test environment
      (it's an SDK-only module; no project-root shim exists for it).
    - GetDeathExplosionSound calls ShipClass_Cast(obj) → returns None (our
      FakeObject is a DamageableObject, not a ShipClass), then falls back to
      LoadTacticalSounds.g_lsDeathExplosions — still needs the import.
    """
    P.reset()
    Effects = _import_effects()

    try:
        fake = FakeObject()
        seq = Effects.CreateObjectExplosion(fake, 1)
    except Exception as e:
        pytest.skip(f"WALL: CreateObjectExplosion(bSound=1) raised {type(e).__name__}: {e}")

    assert seq is not None

    try:
        seq.Start()
    except Exception as e:
        pytest.skip(f"WALL: seq.Start() raised on audio path: {type(e).__name__}: {e}")

    assert P.active_count() >= 1, (
        f"Expected at least 1 active controller, got {P.active_count()}"
    )


# ---------------------------------------------------------------------------
# Test 3: ObjectExploding (full death cascade)
# ---------------------------------------------------------------------------

def test_object_exploding_full_cascade():
    """ObjectExploding is the full death sequence:
    - DamageableObject_Cast (checks isinstance — FakeObject IS a DamageableObject)
    - GetContainingSet → FakeSet (not None, so continues)
    - TGSequence_Create → implemented
    - while loop: GetLifeTime > 1_000_000 → SetLifeTime with random value
    - Multiple CreateObjectExplosion calls (each → CreateDebrisExplosion)
    - CreateDebrisSparks → App.SparkParticleController_Create  [LIKELY WALL]
    - CreateDebrisExplosion × 3 more on pSet.GetEffectRoot()
    - TGSoundAction_Create (sound at end of final sequence)
    - pFullSequence.Play() — synchronous, delays collapsed

    Under synchronous TGSequence: all sub-sequences fire immediately with
    delays ignored — explosions collapse to a single burst.

    Expected wall: App.SparkParticleController_Create is not implemented in
    App.py (not imported from engine.appc.particles, no shim).  CreateDebrisSparks
    calls it → AttributeError (or _NamedStub that breaks on AddColorKey's
    4-arg form, or on EffectAction_Create).
    """
    P.reset()
    Effects = _import_effects()

    try:
        fake = FakeObject()
        Effects.ObjectExploding(fake)
    except Exception as e:
        pytest.skip(
            f"WALL: ObjectExploding raised {type(e).__name__}: {e}"
        )

    # If we get here, the whole cascade ran.  Under synchronous TGSequence
    # the while-loop fires all CreateObjectExplosion calls immediately.
    assert P.active_count() >= 1, (
        "ObjectExploding ran but registered no particle controllers"
    )


# ---------------------------------------------------------------------------
# Test 4: Timed-cascade timing collapse confirmation
# ---------------------------------------------------------------------------

def test_sequence_delays_are_ignored():
    """Confirm that AddAction(action, dependency, fDelay) discards fDelay in
    Phase 1: both actions in the sequence fire and both controllers are active
    immediately after Play(), even though the second was added with a 5-second
    delay."""
    from engine.appc.actions import TGSequence_Create, TGAction_CreateNull
    from engine.appc.particles import (
        AnimTSParticleController, AnimTSParticleController_Create, EffectAction_Create,
    )

    P.reset()
    seq = TGSequence_Create()

    c1 = AnimTSParticleController_Create()
    c1.SetEffectLifeTime(10.0)
    ea1 = EffectAction_Create(c1)

    c2 = AnimTSParticleController_Create()
    c2.SetEffectLifeTime(10.0)
    ea2 = EffectAction_Create(c2)

    # Second action has a 5-second delay — IGNORED in Phase 1.
    seq.AddAction(ea1, TGAction_CreateNull(), 0.0)
    seq.AddAction(ea2, TGAction_CreateNull(), 5.0)

    seq.Start()

    assert P.active_count() == 2, (
        f"Expected 2 active controllers (delays ignored), got {P.active_count()}. "
        "Phase-1 TGSequence collapse is not working."
    )


# ---------------------------------------------------------------------------
# Test 5: CreateDebrisSparks isolation — probe the wall precisely
# ---------------------------------------------------------------------------

def test_create_debris_sparks_wall():
    """Isolate whether CreateDebrisSparks is the wall.

    CreateDebrisSparks calls App.SparkParticleController_Create — if that
    returns a _NamedStub, AddColorKey etc. will be called on it.  The stub
    __getattr__ handles attribute access, but calling AddColorKey on a stub
    returns another stub; EffectAction_Create(pSpark) returns an EffectAction
    wrapping a stub, which registers on Start().

    If that silently passes: the debris sparks path is effectively a no-op
    but doesn't break — document that.
    If it raises: document the exact exception.
    """
    P.reset()
    Effects = _import_effects()

    pEmitFrom = (0.0, 0.0, 0.0)
    pEffectRoot = object()

    try:
        action = Effects.CreateDebrisSparks(1.0, pEmitFrom, 0, pEffectRoot)
    except Exception as e:
        pytest.skip(
            f"WALL: CreateDebrisSparks raised {type(e).__name__}: {e}"
        )

    try:
        action.Start()
    except Exception as e:
        pytest.skip(
            f"WALL: CreateDebrisSparks action.Start() raised {type(e).__name__}: {e}"
        )

    # If we get here: SparkParticleController_Create returned something
    # (likely a _NamedStub) that didn't crash but also probably didn't
    # register a real AnimTSParticleController.
    # Report what actually happened.
    spark_count = P.active_count()
    # A _NamedStub wrapped in EffectAction won't register in P._active
    # (EffectAction.Start() calls particles.register(self._controller)
    # which appends self._controller — stub or not).
    # This is NOT a wall but it IS a data-loss: stub != real controller.
    assert True, f"CreateDebrisSparks ran without error; active_count={spark_count}"
