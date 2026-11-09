from engine import dev_dial_groups
from engine.wings import dials

SPEC = {"leash_gu": 200.0, "leash_slack_gu": 100.0, "regroup_gather_gu": 100.0,
        "engage_gu": 350.0, "wing_popularity": -0.3, "stickiness": 0.25,
        "odds_ratio": 0.8, "desperate_hull": 0.4, "ram_chance": 0.3,
        "brain_period_s": 1.0}


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
