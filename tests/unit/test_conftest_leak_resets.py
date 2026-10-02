"""The autouse `_reset_leakable_engine_globals` (tests/conftest.py) clears
module state a test can leave behind. Each pair here is ORDERED: the first
test leaves state, the second (run after it, in file order) must not see it.
"""


def test_a_leaves_an_explosion_light_glowing():
    from engine.appc import explosion_lights
    explosion_lights.register_at((0.0, 0.0, 0.0), None, size_gu=1.0, life_s=5.0)
    assert explosion_lights._active


def test_b_the_explosion_light_did_not_leak():
    from engine.appc import explosion_lights
    assert explosion_lights._active == []
    assert explosion_lights._sequences == []


def test_c_quickbattle_spawn_provider_leaks():
    from engine.quickbattle import spawn
    spawn.set_provider(lambda: "leaked-plan")
    assert spawn.current_plan() == "leaked-plan"


def test_d_the_quickbattle_spawn_provider_did_not_leak():
    from engine.quickbattle import spawn
    assert spawn.current_plan() is None
