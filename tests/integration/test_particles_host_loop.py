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


def test_spec_b_plume_renders_through_particle_backend():
    from engine.appc import subsystem_emitters as se
    from engine.appc import particles as P
    from tests.unit.test_subsystem_emitters_registry import FakeSub, FakeShip
    se.reset_registry()
    se.reset_manager()
    P.reset()
    se.set_backend(P.ParticleBackend())
    sub = FakeSub("WarpEngineSubsystem", state="disabled")
    ship = FakeShip(subs=[sub])
    se.pump([ship], camera_pos=None, dt=0.1)
    assert P.active_count() == 1
    assert P._active[0]._texture_path.endswith("ExplosionB.tga")
