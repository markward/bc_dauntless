"""FuzzyLogic helpers used by SDK PlainAI scripts.

SDK callers (sdk/Build/scripts/AI/PlainAI/TorpedoRun.py:156,159,233,
FollowObject.py:54-62,110) use two forms:

  - FuzzyLogic_BreakIntoSets(value, thresholds) -> N floats
  - FuzzyLogic() class with rule-based inference

FuzzyLogic_BreakIntoSets already matches ground truth exactly (untouched).

FuzzyLogic.GetResultBySet is an unnormalized SUM of confidence x percentage.
Ground truth: STBC-Reverse-Engineering-1/docs/gameplay/ai-architecture.md
sec.12 (impl 0x0047d0b0) — "returns the unnormalized weighted sum of
confidence x percentage over every edge targeting that output set. There is
no defuzzification, no centroid, no normalization and no clamping."

We previously returned a MAX and ignored confidence, which breaks every
multi-antecedent caller: AI/PlainAI/FollowObject.py:54-59 maps 4 input sets
onto one output set and AI/PlainAI/FollowWaypoints.py:97-108 maps 5 onto one,
then blend speeds against sums that are supposed to form a partition of
unity.
"""
import pytest

import App


# ── FuzzyLogic_BreakIntoSets ──────────────────────────────────────────────────

def test_break_into_sets_value_below_first_threshold_is_all_first_band():
    """value <= lo → (1.0, 0.0, 0.0) for 3-threshold form."""
    result = App.FuzzyLogic_BreakIntoSets(0.0, (10.0, 20.0, 30.0))
    assert result == (1.0, 0.0, 0.0)


def test_break_into_sets_value_above_last_threshold_is_all_last_band():
    """value >= hi → (0.0, 0.0, 1.0) for 3-threshold form."""
    result = App.FuzzyLogic_BreakIntoSets(100.0, (10.0, 20.0, 30.0))
    assert result == (0.0, 0.0, 1.0)


def test_break_into_sets_value_at_mid_threshold_is_all_mid():
    """value exactly at the middle threshold → (0.0, 1.0, 0.0)."""
    result = App.FuzzyLogic_BreakIntoSets(20.0, (10.0, 20.0, 30.0))
    assert result == (0.0, 1.0, 0.0)


def test_break_into_sets_value_halfway_low_to_mid():
    """value at midpoint of (lo, mid) → (0.5, 0.5, 0.0) by linear interp."""
    result = App.FuzzyLogic_BreakIntoSets(15.0, (10.0, 20.0, 30.0))
    assert result[0] == pytest.approx(0.5)
    assert result[1] == pytest.approx(0.5)
    assert result[2] == pytest.approx(0.0)


def test_break_into_sets_returns_floats_summing_to_one():
    """For any value, the membership floats sum to 1.0."""
    for v in (-5.0, 0.0, 12.5, 17.5, 25.0, 50.0):
        result = App.FuzzyLogic_BreakIntoSets(v, (10.0, 20.0, 30.0))
        assert sum(result) == pytest.approx(1.0)


def test_break_into_sets_4_threshold_form_returns_4_floats():
    """4 thresholds → 4 bands (TorpedoRun perpendicular-velocity usage)."""
    result = App.FuzzyLogic_BreakIntoSets(0.5, (0.0, 0.2, 0.4, 0.6))
    assert len(result) == 4
    assert sum(result) == pytest.approx(1.0)


# ── FuzzyLogic class ──────────────────────────────────────────────────────────

def test_multiple_rules_onto_one_output_set_sum():
    f = App.FuzzyLogic()
    f.SetMaxRules(4)
    f.AddRule(0, 10)     # in 0 -> out 10
    f.AddRule(1, 10)     # in 1 -> out 10
    f.SetPercentageInSet(0, 0.25)
    f.SetPercentageInSet(1, 0.75)
    # sum, not max: 0.25 + 0.75 == 1.0 (max would give 0.75)
    assert f.GetResultBySet(10) == 1.0


def test_confidence_weights_the_contribution():
    f = App.FuzzyLogic()
    f.SetMaxRules(2)
    f.AddRule(0, 10, 0.5)
    f.SetPercentageInSet(0, 0.4)
    assert f.GetResultBySet(10) == 0.2


def test_add_rule_defaults_confidence_to_one_and_returns_the_index():
    f = App.FuzzyLogic()
    f.SetMaxRules(2)
    assert f.AddRule(0, 10) == 0
    assert f.AddRule(1, 10) == 1
    assert f.AddRule(2, 10) == -1, "at capacity -> -1"
    assert f.GetMaxRules() == 2
    assert f.GetRule(0) == (0, 10, 1.0)


def test_unmatched_output_set_is_zero():
    f = App.FuzzyLogic()
    f.SetMaxRules(1)
    f.AddRule(0, 10)
    f.SetPercentageInSet(0, 1.0)
    assert f.GetResultBySet(99) == 0.0


def test_remove_rule_is_a_swap_remove():
    f = App.FuzzyLogic()
    f.SetMaxRules(3)
    f.AddRule(0, 10)
    f.AddRule(1, 11)
    f.AddRule(2, 12)
    f.RemoveRule(0)
    # The LAST rule is copied over index 0 — indices are not stable.
    assert f.GetRule(0) == (2, 12, 1.0)
    assert f.GetRule(1) == (1, 11, 1.0)


def test_set_rule_confidence():
    f = App.FuzzyLogic()
    f.SetMaxRules(1)
    f.AddRule(0, 10)
    f.SetRuleConfidence(0, 0.25)
    f.SetPercentageInSet(0, 1.0)
    assert f.GetResultBySet(10) == 0.25


def test_follow_object_partition_of_unity():
    """The real shape: FollowObject maps 4 inputs onto FS_STOP_AND_TURN_TOWARD
    and 2 onto FS_FAST_AND_TURN_TOWARD, with memberships that sum to 1.0 across
    all inputs. The two results must therefore also sum to 1.0."""
    NEAR_F, NEAR_L, MID_F, MID_L, FAR_F, FAR_L = range(6)
    STOP, FAST = 100, 101
    f = App.FuzzyLogic()
    f.SetMaxRules(6)
    f.AddRule(NEAR_F, STOP)
    f.AddRule(NEAR_L, STOP)
    f.AddRule(MID_F, FAST)
    f.AddRule(MID_L, STOP)
    f.AddRule(FAR_F, FAST)
    f.AddRule(FAR_L, STOP)

    near, mid, far = 0.0, 0.4, 0.6         # a distance partition
    facing, leaving = 0.75, 0.25           # a facing partition
    f.SetPercentageInSet(NEAR_F, near * facing)
    f.SetPercentageInSet(NEAR_L, near * leaving)
    f.SetPercentageInSet(MID_F, mid * facing)
    f.SetPercentageInSet(MID_L, mid * leaving)
    f.SetPercentageInSet(FAR_F, far * facing)
    f.SetPercentageInSet(FAR_L, far * leaving)

    stop = f.GetResultBySet(STOP)
    fast = f.GetResultBySet(FAST)
    assert abs(stop + fast - 1.0) < 1e-9, "the blend must preserve total mass"
    assert abs(fast - 0.75) < 1e-9
    assert abs(stop - 0.25) < 1e-9
