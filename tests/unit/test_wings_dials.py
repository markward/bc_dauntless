from engine import dev_dial_groups
from engine.wings import dials

SPEC = {"leash_gu": 200.0, "leash_slack_gu": 100.0, "regroup_gather_gu": 100.0,
        "engage_gu": 350.0, "wing_popularity": -0.3, "stickiness": 0.25,
        "odds_ratio": 0.8, "desperate_hull": 0.4, "ram_chance": 0.3,
        "brain_period_s": 1.0, "heavy_fire_window_s": 5.0,
        "heavy_fire_frac": 0.15, "heavy_fire_attackers": 3,
        "guard_count": 1, "interpose_gu": 40.0, "rotate_out_shield": 0.25,
        "rotate_in_shield": 0.6, "rotate_max_s": 30.0,
        "rotate_cap_frac": 0.34, "withdraw_odds": 0.4,
        "withdraw_wing_frac": 0.5, "withdraw_step_gu": 300.0,
        "withdraw_clear_s": 10.0, "withdraw_max_s": 60.0,
        "withdraw_cooldown_s": 120.0}


def test_defaults_match_spec():
    assert dials.DEFAULTS == SPEC
    assert set(dials.DIAL_ORDER) == set(SPEC)


def test_get_reads_current_after_step():
    dials.reset()
    try:
        dials._step("leash_gu", 1)
        assert dials.get("leash_gu") > 200.0
        dials.reset()
        assert dials.get("leash_gu") == 200.0
    finally:
        dials.reset()


def test_register_adds_group():
    dials.register()
    assert "wings" in dev_dial_groups._groups
