from engine.appc import particles as P
from engine.appc.particles import SparkParticleController, AnimTSParticleController


def test_spark_constructor_maps_three_args():
    c = SparkParticleController(3.2, 1.0, 0.005)
    assert c._effect_life_time == 3.2     # total_life
    assert c._emit_frequency == 0.005     # emit_rate
    assert c._duration == 1.0             # duration


def test_spark_setters_round_trip():
    c = SparkParticleController(1.0, 1.0, 0.005)
    c.SetDamping(0.3); c.SetTailLength(0.2)
    c.SetEmitVelocity(2.5); c.AddColorKey(0.0, 1.0, 1.0, 0.8)
    assert c._damping == 0.3 and c._tail_length == 0.2
    assert c._emit_velocity == 2.5
    assert c._color_keys == [(0.0, 1.0, 1.0, 0.8)]


def test_descriptor_emits_damping_and_tail_for_spark():
    P.reset()
    c = SparkParticleController(2.0, 1.0, 0.005)
    c.SetDamping(0.3); c.SetTailLength(0.1)
    c.SetEmitPositionAndDirection((0.0, 0.0, 0.0), (0.0, 1.0, 0.0))
    c.CreateTarget("data/rough.tga"); c.AddSizeKey(0.0, 0.04)
    P.EffectAction_Create(c).Start()
    P.advance(0.1)
    d = P.snapshot_descriptors()[0]
    assert d["damping"] == 0.3
    assert d["tail_length"] == 0.1


def test_descriptor_zero_damping_tail_for_plain_controller():
    P.reset()
    c = AnimTSParticleController()
    c.SetEmitPositionAndDirection((0.0, 0.0, 0.0), (0.0, -1.0, 0.0))
    c.CreateTarget("data/Textures/Effects/ExplosionB.tga"); c.AddSizeKey(0.0, 1.0)
    P.EffectAction_Create(c).Start()
    P.advance(0.1)
    d = P.snapshot_descriptors()[0]
    assert d["damping"] == 0.0 and d["tail_length"] == 0.0


def test_duration_caps_emission_stop_age():
    c = SparkParticleController(5.0, 1.0, 0.005)
    c.SetEmitLife(0.5)
    c._effect_age = 2.0
    assert c._effective_stop_age() <= 1.0   # emission ceased by `duration`=1.0
