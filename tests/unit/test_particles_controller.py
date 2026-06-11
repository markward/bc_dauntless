# tests/unit/test_particles_controller.py
from engine.appc.particles import AnimTSParticleController


def test_setters_round_trip():
    c = AnimTSParticleController()
    c.AddColorKey(0.0, 1.0, 0.5, 0.25)
    c.AddAlphaKey(0.0, 0.6); c.AddAlphaKey(1.0, 0.0)
    c.AddSizeKey(0.0, 0.2); c.AddSizeKey(1.0, 2.0)
    c.SetEmitVelocity(3.0); c.SetAngleVariance(60.0)
    c.SetEmitLife(1.5); c.SetEmitLifeVariance(0.3)
    c.SetEmitFrequency(0.05); c.SetEffectLifeTime(10.0)
    c.SetInheritsVelocity(1); c.SetDrawOldToNew(0)
    c.CreateTarget("data/Textures/Effects/ExplosionB.tga")
    assert c._color_keys == [(0.0, 1.0, 0.5, 0.25)]
    assert c._alpha_keys == [(0.0, 0.6), (1.0, 0.0)]
    assert c._size_keys == [(0.0, 0.2), (1.0, 2.0)]
    assert c._emit_velocity == 3.0 and c._angle_variance == 60.0
    assert c._emit_life == 1.5 and c._emit_life_variance == 0.3
    assert c._emit_frequency == 0.05 and c._effect_life_time == 10.0
    assert c._inherit == 1.0 and c._draw_old_to_new == 0
    assert c._texture_path.endswith("ExplosionB.tga")


def test_inherits_velocity_zero_is_no_inherit():
    c = AnimTSParticleController()
    c.SetInheritsVelocity(0)
    assert c._inherit == 0.0


def test_unknown_setter_is_noop_not_crash():
    c = AnimTSParticleController()
    c.SetSomeFutureSDKKnob(1, 2, 3)   # must not raise
    c.AddMysteryKey(0.5)              # must not raise


def test_stop_and_has_live_particles_timeline():
    c = AnimTSParticleController()
    c.SetEmitLife(1.0); c.SetEmitLifeVariance(0.0); c.SetEffectLifeTime(100.0)
    c._effect_age = 5.0
    assert c.has_live_particles() is True      # never stopped
    c.stop_emitting()                          # stop_age = 5.0
    c._effect_age = 5.5
    assert c.has_live_particles() is True       # within max_life
    c._effect_age = 6.5                          # 5.0 + 1.0 = 6.0 < 6.5
    assert c.has_live_particles() is False


def test_effect_life_time_caps_emission_for_has_live():
    c = AnimTSParticleController()
    c.SetEmitLife(1.0); c.SetEffectLifeTime(2.0)   # emission auto-stops at 2.0
    c._effect_age = 2.5
    assert c.has_live_particles() is True            # 2.0 + 1.0 = 3.0 > 2.5
    c._effect_age = 3.5
    assert c.has_live_particles() is False
