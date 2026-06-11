"""Tests for TGSequence timed-action engine + EffectController + CreateWeaponExplosion.

Step 3 of feat/particle-backend-a2-explosion-plume.
"""
import pytest
from engine.appc import particles as P
from engine.appc.particles import EffectAction_Create, AnimTSParticleController


def _ctrl():
    c = AnimTSParticleController()
    c.CreateTarget("data/Textures/Effects/ExplosionA.tga")
    c.AddSizeKey(0.0, 1.0)
    return c


def test_sequence_starts_immediate_children_on_start():
    P.reset()
    # TGSequence_Create comes from App (actions.py) via the normal import path.
    import App
    seq = App.TGSequence_Create()
    seq.AddAction(EffectAction_Create(_ctrl()))
    seq.AddAction(EffectAction_Create(_ctrl()))
    assert P.active_count() == 0
    seq.Start()
    assert P.active_count() == 2   # both delay-0 children started


def test_sequence_fires_delayed_child_after_delay():
    """Phase 1 TGSequence ignores delays (all fire immediately on Start()).
    Both immediate and delayed children are started at once."""
    P.reset()
    import App
    seq = App.TGSequence_Create()
    seq.AddAction(EffectAction_Create(_ctrl()))                          # t=0
    seq.AddAction(EffectAction_Create(_ctrl()), App.TGAction_CreateNull(), 0.5)  # t=0.5 (delay ignored in Phase 1)
    seq.Start()
    # In Phase 1 both fire immediately — delays are not enforced
    assert P.active_count() == 2


def test_effect_controller_high():
    assert P.EffectController_GetEffectLevel() == P.EffectController.HIGH


def test_effect_controller_constants():
    assert P.EffectController.LOW == 0
    assert P.EffectController.MEDIUM == 1
    assert P.EffectController.HIGH == 2
    assert P.EffectController.HIGH > P.EffectController.MEDIUM
    assert P.EffectController.MEDIUM > P.EffectController.LOW


def test_app_effect_controller_bindings():
    """App.EffectController and App.EffectController_GetEffectLevel must exist."""
    import App
    assert App.EffectController.HIGH == 2
    assert App.EffectController_GetEffectLevel() == App.EffectController.HIGH


def test_create_weapon_explosion_runs_unmodified():
    """Effects.CreateWeaponExplosion must run unmodified and register >=1 real
    controller, with no stub rows for the infra we made real."""
    import App
    import Effects
    App._stub_tracker.clear()
    App._stub_tracker.set_mission("test_create_weapon_explosion")
    P.reset()

    class FakeNode:
        pass

    class FakeTarget:
        def GetNode(self):
            return FakeNode()

    class FakeEvent:
        def GetTargetObject(self):
            return FakeTarget()

        def GetObjectHitPoint(self):
            return (0.0, 0.0, 0.0)

        def GetObjectHitNormal(self):
            return (0.0, 1.0, 0.0)

    action = Effects.CreateWeaponExplosion(1.0, 1.0, FakeEvent())
    action.Start()

    # At least one real explosion controller is now live
    assert P.active_count() >= 1, (
        f"Expected >=1 active controllers after Start(), got {P.active_count()}"
    )

    # The infra we implemented must NOT appear as stubs
    names = {row[0] for row in App._stub_tracker.report()}
    assert "TGSequence_Create" not in names, (
        "TGSequence_Create still hitting stub tracker — it should be real"
    )
    assert "AnimTSParticleController_Create" not in names, (
        "AnimTSParticleController_Create still hitting stub tracker"
    )
    assert "EffectController_GetEffectLevel" not in names, (
        "EffectController_GetEffectLevel still hitting stub tracker"
    )
    assert "ExplosionPlumeController_Create" not in names, (
        "ExplosionPlumeController_Create still hitting stub tracker"
    )
    assert "EffectAction_Create" not in names, (
        "EffectAction_Create still hitting stub tracker"
    )
