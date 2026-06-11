# tests/unit/test_particles_sdk_unmodified.py
"""The SDK Effects.py smoke factories must run UNMODIFIED against our real
controller and register a controller with the SDK's exact recipe."""
import App
from engine.appc import particles as P


def test_create_smoke_high_builds_real_controller():
    import Effects
    P.reset()
    pEmitFrom = object()
    # fLife arg is accepted but CreateSmokeHigh sets emit life internally
    action = Effects.CreateSmokeHigh(2.0, 1.5, 0.6, pEmitFrom, None, None, object())
    action.Start()
    assert P.active_count() == 1
    from engine.appc.particles import AnimTSParticleController
    ctrl = P._active[0]
    assert isinstance(ctrl, AnimTSParticleController)
    assert ctrl._emit_velocity == 2.0
    assert ctrl._texture_path.endswith("ExplosionB.tga")
    assert len(ctrl._alpha_keys) == 3   # CreateSmokeHigh adds exactly 3 alpha keys
    assert len(ctrl._size_keys) == 3    # and exactly 3 size keys


def test_no_stub_rows_for_controller_methods():
    import Effects
    App._stub_tracker.clear()          # don't inherit rows from earlier tests
    App._stub_tracker.set_mission("particles-a1")
    try:
        Effects.CreateSmokeHigh(2.0, 1.5, 0.6, object(), None, None, object())
        report = App._stub_tracker.report()
    finally:
        App._stub_tracker.reset_mission()
    # report() returns [(name, num_missions, total_count), ...]
    stub_names = {row[0] for row in report}
    assert "AnimTSParticleController_Create" not in stub_names
    assert "EffectAction_Create" not in stub_names
