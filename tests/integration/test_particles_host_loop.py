from engine.appc import particles as P
from engine.appc.particles import AnimTSParticleController


def test_build_particle_render_data_snapshots_active():
    import engine.host_loop as hl
    P.reset()
    c = AnimTSParticleController()
    c.SetEmitPositionAndDirection((1.0, 0.0, 0.0), (0.0, -1.0, 0.0))
    c.CreateTarget("data/Textures/Effects/ExplosionB.tga")
    c.AddSizeKey(0.0, 1.0)
    P.EffectAction_Create(c).Start()
    P.advance(0.1)
    data = hl._build_particle_render_data()
    assert len(data) == 1
    assert data[0]["emit_pos"] == (1.0, 0.0, 0.0)
    assert data[0]["texture_path"].endswith("ExplosionB.tga")
