"""Leak guard for Developer Options -> "Hull damage" (Task 8 fix round 1).

The rows mutate module-level state (hull_wear knobs, death_cascade's tier
table, plating_dials' defaults and dials, the tuning module's near mirror).
tests/conftest.py's autouse _reset_leakable_engine_globals must restore all
of it between tests, without reaching the native host. No local fixture
here on purpose: only the conftest reset runs between these tests.
"""
from engine import dev_hull_damage_tuning as tuning
from engine import renderer
from engine.appc import death_cascade, hull_wear, plating_dials

# The two tests below run in file order: the first leaves every knob mutated
# WITHOUT cleaning up, the second proves the autouse conftest reset restored
# them. reset_python_state itself must never reach the native host.

def _mutate_everything():
    hull_wear.PHASER_RATE = 9.0
    hull_wear.COLLISION_MIN_HULL_DAMAGE = 9.0
    death_cascade.set_big_tier_chance(0.2)
    tuning._near_gu = 99.0
    plating_dials._defaults = dict(plating_dials.DEFAULTS, soot=0.1)
    plating_dials._dials = dict(plating_dials.DEFAULTS, soot=0.2,
                                breach_wear=9.0)


def _assert_all_default():
    assert hull_wear.PHASER_RATE == hull_wear.DEFAULT_PHASER_RATE
    assert (hull_wear.COLLISION_MIN_HULL_DAMAGE
            == hull_wear.DEFAULT_COLLISION_MIN_HULL_DAMAGE)
    assert death_cascade.BLAST_SIZE_TIERS == death_cascade.DEFAULT_BLAST_SIZE_TIERS
    assert tuning._near_gu == tuning.DEFAULT_NEAR_GU
    assert plating_dials._defaults == plating_dials.DEFAULTS
    assert plating_dials.current() == plating_dials.DEFAULTS


def test_leak_guard_1_mutates_every_knob_and_does_not_clean_up():
    _mutate_everything()


def test_leak_guard_2_the_autouse_reset_restored_them():
    _assert_all_default()


def test_reset_python_state_never_touches_native(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("reset_python_state reached native")
    monkeypatch.setattr(plating_dials, "push", _boom)
    for name in ("set_plating_params", "set_interior_near_gu",
                 "interior_near_gu", "interior_near_gu_default",
                 "plating_param_defaults"):
        monkeypatch.setattr(renderer, name, _boom, raising=False)
    _mutate_everything()
    tuning.reset_python_state()
    _assert_all_default()
