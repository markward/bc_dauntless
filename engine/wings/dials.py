"""Wing tunables (spec 2026-11-09-wing-leaders-phase-a-design.md §7-§10).

Play-test values, not recovered BC numbers. Read at use; not persisted; tuned
live through / L O once Developer Options selects the "wings" dial group.
"""
DEFAULTS: dict = {
    "leash_gu": 200.0,
    "leash_slack_gu": 100.0,
    "regroup_gather_gu": 100.0,
    "engage_gu": 350.0,
    "wing_popularity": -0.3,
    "stickiness": 0.25,
    "odds_ratio": 0.8,
    "desperate_hull": 0.4,
    "ram_chance": 0.3,
    "brain_period_s": 1.0,
    "heavy_fire_window_s": 5.0,
    "heavy_fire_frac": 0.15,
    "heavy_fire_attackers": 3,
    "guard_count": 1,
    "interpose_gu": 40.0,
    "rotate_out_shield": 0.25,
    "rotate_in_shield": 0.6,
    "rotate_max_s": 30.0,
    "rotate_cap_frac": 0.34,
    "rotate_out_hull": 0.5,
    "withdraw_odds": 0.4,
    "withdraw_wing_frac": 0.5,
    "withdraw_step_gu": 300.0,
    "withdraw_clear_s": 10.0,
    "withdraw_max_s": 60.0,
    "withdraw_cooldown_s": 120.0,
    "attack_standoff_gu": 80.0,
    "attack_slots": 3,
    "face_weak": 0.3,
    "disable_threat": 1.5,
    "reserve_min_wing": 5,
    "reserve_gu": 150.0,
    "reserve_max_s": 90.0,
    "disable_max_s": 300.0,
    "attack_standoff_min_gu": 25.0,
    "protect_min_s": 10.0,
    "attack_min_s": 10.0,
    "protect_member_frac": 0.6,
    "reinforce_odds": 1.0,
    "reinforce_spare_odds": 2.5,
    "reinforce_range_gu": 1500.0,
    "reinforce_max_s": 90.0,
    "reinforce_cooldown_s": 60.0,
    "hold_spread_gu": 30.0,
    "screen_watch_gu": 700.0,
    "screen_gu": 150.0,
    "flank_gu": 250.0,
    "feint_range_gu": 800.0,
    "feint_stop_gu": 100.0,
    "feint_odds": 1.0,
    "feint_cooldown_s": 180.0,
    "feint_max_s": 45.0,
    "reinforce_close_odds": 1.5,
    "feint_max_odds": 1.25,
    "flank_max_s": 90.0,
    "flank_cooldown_s": 60.0,
}
DIAL_ORDER: tuple = tuple(DEFAULTS)
_STEP = {"leash_gu": 25.0, "leash_slack_gu": 25.0, "regroup_gather_gu": 25.0,
         "engage_gu": 25.0, "wing_popularity": 0.1, "stickiness": 0.05,
         "odds_ratio": 0.05, "desperate_hull": 0.05, "ram_chance": 0.05,
         "brain_period_s": 0.25, "heavy_fire_window_s": 0.5,
         "heavy_fire_frac": 0.05, "heavy_fire_attackers": 1, "guard_count": 1,
         "interpose_gu": 5.0, "rotate_out_shield": 0.05,
         "rotate_in_shield": 0.05, "rotate_max_s": 5.0,
         "rotate_cap_frac": 0.05, "rotate_out_hull": 0.05,
         "withdraw_odds": 0.05,
         "withdraw_wing_frac": 0.05, "withdraw_step_gu": 25.0,
         "withdraw_clear_s": 1.0, "withdraw_max_s": 5.0,
         "withdraw_cooldown_s": 10.0, "attack_standoff_gu": 10.0,
         "attack_slots": 1, "face_weak": 0.05, "disable_threat": 0.1,
         "reserve_min_wing": 1, "reserve_gu": 10.0, "reserve_max_s": 5.0,
         "disable_max_s": 10.0, "attack_standoff_min_gu": 5.0,
         "protect_min_s": 1.0, "attack_min_s": 1.0,
         "protect_member_frac": 0.05,
         "reinforce_odds": 0.1, "reinforce_spare_odds": 0.1,
         "reinforce_range_gu": 100.0, "reinforce_max_s": 5.0,
         "reinforce_cooldown_s": 5.0, "hold_spread_gu": 5.0,
         "screen_watch_gu": 50.0, "screen_gu": 10.0, "flank_gu": 25.0,
         "feint_range_gu": 50.0, "feint_stop_gu": 10.0, "feint_odds": 0.1,
         "feint_cooldown_s": 10.0, "feint_max_s": 5.0,
         "reinforce_close_odds": 0.1, "feint_max_odds": 0.05,
         "flank_max_s": 5.0, "flank_cooldown_s": 5.0}
_MIN = {"leash_gu": 25.0, "leash_slack_gu": 0.0, "regroup_gather_gu": 25.0,
        "engage_gu": 25.0, "wing_popularity": -2.0, "stickiness": 0.0,
        "odds_ratio": 0.1, "desperate_hull": 0.0, "ram_chance": 0.0,
        "brain_period_s": 0.25, "heavy_fire_window_s": 0.5,
        "heavy_fire_frac": 0.0, "heavy_fire_attackers": 1, "guard_count": 0,
        "interpose_gu": 0.0, "rotate_out_shield": 0.0,
        "rotate_in_shield": 0.0, "rotate_max_s": 1.0, "rotate_cap_frac": 0.0,
        "rotate_out_hull": 0.0,
        "withdraw_odds": 0.0, "withdraw_wing_frac": 0.0,
        "withdraw_step_gu": 25.0, "withdraw_clear_s": 0.0,
        "withdraw_max_s": 1.0, "withdraw_cooldown_s": 0.0,
        "attack_standoff_gu": 20.0, "attack_slots": 0, "face_weak": 0.0,
        "disable_threat": 1.0, "reserve_min_wing": 2, "reserve_gu": 25.0,
        "reserve_max_s": 5.0, "disable_max_s": 10.0,
        "attack_standoff_min_gu": 5.0, "protect_min_s": 0.0,
        "attack_min_s": 0.0, "protect_member_frac": 0.0,
        "reinforce_odds": 0.0, "reinforce_spare_odds": 1.0,
        "reinforce_range_gu": 100.0, "reinforce_max_s": 5.0,
        "reinforce_cooldown_s": 0.0, "hold_spread_gu": 5.0,
        "screen_watch_gu": 100.0, "screen_gu": 25.0, "flank_gu": 50.0,
        "feint_range_gu": 100.0, "feint_stop_gu": 25.0, "feint_odds": 0.1,
        "feint_cooldown_s": 0.0, "feint_max_s": 5.0,
        "reinforce_close_odds": 1.0, "feint_max_odds": 0.5,
        "flank_max_s": 5.0, "flank_cooldown_s": 0.0}
_MAX = {"wing_popularity": 2.0, "stickiness": 1.0, "odds_ratio": 3.0,
        "desperate_hull": 1.0, "ram_chance": 1.0,
        "heavy_fire_frac": 1.0, "rotate_out_shield": 1.0,
        "rotate_in_shield": 1.0, "rotate_cap_frac": 1.0, "rotate_out_hull": 1.0,
        "withdraw_odds": 3.0,
        "withdraw_wing_frac": 1.0, "face_weak": 1.0, "disable_threat": 5.0,
        "protect_member_frac": 1.0,
        "reinforce_odds": 5.0, "reinforce_spare_odds": 10.0,
        "feint_odds": 5.0, "reinforce_close_odds": 5.0,
        "feint_max_odds": 5.0}

_dials: dict = dict(DEFAULTS)


def reset() -> None:
    global _dials
    _dials = dict(DEFAULTS)


def get(name: str) -> float:
    return float(_dials[name])


def current() -> dict:
    return dict(_dials)


def step(dials: dict, name: str, direction: int) -> dict:
    """Pure: one additive step, clamped to [_MIN, _MAX]."""
    out = dict(dials)
    v = round(out[name] + (_STEP[name] if direction > 0 else -_STEP[name]), 4)
    v = max(_MIN[name], v)
    if name in _MAX:
        v = min(_MAX[name], v)
    # rotate_in_shield >= rotate_out_shield, or a ship between the two
    # returns and re-falls every tick: the stepped dial stops at the other.
    if name == "rotate_out_shield":
        v = min(v, out["rotate_in_shield"])
    elif name == "rotate_in_shield":
        v = max(v, out["rotate_out_shield"])
    out[name] = v
    return out


def _step(name: str, direction: int) -> None:
    global _dials
    _dials = step(_dials, name, direction)


def register() -> None:
    from engine import dev_dial_groups
    dev_dial_groups.register_group("wings", DIAL_ORDER, current, _step)
