from engine.appc import particles as P
from engine.appc.particles import AnimTSParticleController


def test_explosion_setters_store_values():
    c = AnimTSParticleController()
    c.SetEmitRadius(0.25)
    c.SetUpRandomVelocity(120.0, 0.4)
    c.SetTargetAlphaBlendModes(0, 7)
    assert c._emit_radius == 0.25
    assert c._rv_cone == 120.0 and c._rv_speed == 0.4
    assert c._blend_mode == 1   # additive


def test_default_blend_is_alpha_and_zero_explosion_fields():
    c = AnimTSParticleController()
    assert c._blend_mode == 0
    assert c._emit_radius == 0.0 and c._rv_cone == 0.0 and c._rv_speed == 0.0


def test_descriptor_emits_explosion_fields():
    P.reset()
    c = AnimTSParticleController()
    c.SetEmitPositionAndDirection((0.0, 0.0, 0.0), (0.0, -1.0, 0.0))
    c.CreateTarget("data/Textures/Effects/ExplosionA.tga")
    c.AddSizeKey(0.0, 1.0)
    c.SetEmitRadius(0.5); c.SetUpRandomVelocity(90.0, 0.3); c.SetTargetAlphaBlendModes(0, 7)
    P.EffectAction_Create(c).Start()
    P.advance(0.1)
    d = P.snapshot_descriptors()[0]
    assert d["blend_mode"] == 1
    assert d["emit_radius"] == 0.5
    assert d["random_velocity_cone"] == 90.0
    assert d["random_velocity_speed"] == 0.3


def test_descriptor_defaults_keep_a1_behaviour():
    P.reset()
    c = AnimTSParticleController()
    c.SetEmitPositionAndDirection((0.0, 0.0, 0.0), (0.0, -1.0, 0.0))
    c.CreateTarget("data/Textures/Effects/ExplosionB.tga")
    c.AddSizeKey(0.0, 1.0)
    P.EffectAction_Create(c).Start()
    P.advance(0.1)
    d = P.snapshot_descriptors()[0]
    assert d["blend_mode"] == 0 and d["emit_radius"] == 0.0
    assert d["random_velocity_cone"] == 0.0 and d["random_velocity_speed"] == 0.0
