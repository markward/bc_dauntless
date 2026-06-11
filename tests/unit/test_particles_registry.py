# tests/unit/test_particles_registry.py
from engine.appc import particles as P
from engine.appc.particles import AnimTSParticleController


def _smoke(life=1.0, freq=0.05, eff=100.0):
    c = AnimTSParticleController()
    c.SetEmitLife(life); c.SetEmitFrequency(freq); c.SetEffectLifeTime(eff)
    c.CreateTarget("data/Textures/Effects/ExplosionB.tga")
    c.AddSizeKey(0.0, 1.0); c.AddAlphaKey(0.0, 0.5)
    return c


def test_effect_action_start_registers_stop_deregisters():
    P.reset()
    c = _smoke()
    action = P.EffectAction_Create(c)
    assert P.active_count() == 0
    action.Start()
    assert P.active_count() == 1
    action.Stop()
    assert P.active_count() == 0


def test_advance_ages_and_prunes_after_lifetime_and_death():
    P.reset()
    c = _smoke(life=1.0, eff=2.0)
    P.EffectAction_Create(c).Start()
    P.advance(1.0)
    assert P.active_count() == 1 and c._effect_age == 1.0
    P.advance(1.5)   # age 2.5 > EffectLifeTime 2.0 but particles live to 3.0
    assert P.active_count() == 1
    P.advance(1.0)   # age 3.5 > 3.0 => pruned
    assert P.active_count() == 0


def test_snapshot_unattached_emits_world_descriptor():
    P.reset()
    c = _smoke()
    c.SetEmitPositionAndDirection((1.0, 2.0, 3.0), (0.0, -1.0, 0.0))
    P.EffectAction_Create(c).Start()
    P.advance(0.1)
    descs = P.snapshot_descriptors()
    assert len(descs) == 1
    d = descs[0]
    assert d["instance_id"] is None
    assert d["emit_pos"] == (1.0, 2.0, 3.0)
    assert d["emit_vel_world"] == (0.0, 0.0, 0.0)
    assert d["texture_path"].endswith("ExplosionB.tga")
    assert d["size_keys"] == [(0.0, 1.0)]
    assert d["effect_age"] == 0.1


def test_snapshot_attached_uses_resolver():
    P.reset()
    c = _smoke()
    ship = object()
    c.SetEmitFromObject(ship)
    c.SetEmitPositionAndDirection((0.0, 1.0, 0.0), (0.0, -1.0, 0.0))
    P.EffectAction_Create(c).Start()
    P.advance(0.1)
    def resolve(emit_from):
        assert emit_from is ship
        return {"instance_id": (7, 1), "velocity": (5.0, 0.0, 0.0)}
    d = P.snapshot_descriptors(resolve_attach=resolve)[0]
    assert d["instance_id"] == (7, 1)
    assert d["emit_vel_world"] == (5.0, 0.0, 0.0)
    assert d["emit_pos"] == (0.0, 1.0, 0.0)   # body-frame, resolved in the pass


def test_reset_clears_active():
    P.reset()
    P.EffectAction_Create(_smoke()).Start()
    assert P.active_count() == 1
    P.reset()
    assert P.active_count() == 0
