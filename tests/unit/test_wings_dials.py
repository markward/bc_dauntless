from engine import dev_dial_groups
from engine.wings import dials

SPEC = {"leash_gu": 200.0, "leash_slack_gu": 100.0, "regroup_gather_gu": 100.0,
        "engage_gu": 350.0, "wing_popularity": -0.3, "stickiness": 0.25,
        "odds_ratio": 0.8, "desperate_hull": 0.4, "ram_chance": 0.3,
        "brain_period_s": 1.0, "heavy_fire_window_s": 5.0,
        "heavy_fire_frac": 0.15, "heavy_fire_attackers": 3,
        "guard_count": 1, "interpose_gu": 40.0, "rotate_out_shield": 0.25,
        "rotate_in_shield": 0.6, "rotate_max_s": 30.0,
        "rotate_cap_frac": 0.34, "rotate_out_hull": 0.5,
        "withdraw_odds": 0.4,
        "withdraw_wing_frac": 0.5, "withdraw_step_gu": 300.0,
        "withdraw_clear_s": 10.0, "withdraw_max_s": 60.0,
        "withdraw_cooldown_s": 120.0, "attack_standoff_gu": 80.0,
        "attack_slots": 3, "face_weak": 0.3, "disable_threat": 1.5,
        "reserve_min_wing": 5, "reserve_gu": 150.0, "reserve_max_s": 90.0,
        "disable_max_s": 300.0, "attack_standoff_min_gu": 25.0,
        "protect_min_s": 10.0, "attack_min_s": 10.0,
        "protect_member_frac": 0.6}


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


def test_rotate_dials_stay_ordered_when_stepped():
    """Review M6: rotate_in_shield never steps below rotate_out_shield
    (a ship between the two would return and re-fall every tick)."""
    d = dict(dials.DEFAULTS, rotate_out_shield=0.55, rotate_in_shield=0.6)
    up = dials.step(d, "rotate_out_shield", 1)
    up = dials.step(up, "rotate_out_shield", 1)
    assert up["rotate_out_shield"] <= up["rotate_in_shield"] == 0.6
    down = dials.step(d, "rotate_in_shield", -1)
    down = dials.step(down, "rotate_in_shield", -1)
    assert down["rotate_in_shield"] >= down["rotate_out_shield"] == 0.55
    assert dials.step(d, "rotate_in_shield", 1)["rotate_in_shield"] == 0.65


def test_disable_max_s_steps_by_ten_floor_ten():
    d = dict(dials.DEFAULTS)
    assert dials.step(d, "disable_max_s", 1)["disable_max_s"] == 310.0
    d["disable_max_s"] = 10.0
    assert dials.step(d, "disable_max_s", -1)["disable_max_s"] == 10.0


def test_attack_standoff_dials_step_and_floor():
    d = dict(dials.DEFAULTS)
    assert dials.step(d, "attack_standoff_gu", 1)["attack_standoff_gu"] == 90.0
    assert dials.step(d, "attack_standoff_min_gu", 1)[
        "attack_standoff_min_gu"] == 30.0
    d["attack_standoff_min_gu"] = 5.0
    assert dials.step(d, "attack_standoff_min_gu", -1)[
        "attack_standoff_min_gu"] == 5.0
    d["attack_standoff_gu"] = 20.0
    assert dials.step(d, "attack_standoff_gu", -1)["attack_standoff_gu"] == 20.0
