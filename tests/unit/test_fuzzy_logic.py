"""FuzzyLogic helpers used by SDK PlainAI scripts.

SDK callers (sdk/Build/scripts/AI/PlainAI/TorpedoRun.py:156,159,233,
FollowObject.py:54-62,110) use two forms:

  - FuzzyLogic_BreakIntoSets(value, thresholds) -> N floats
  - FuzzyLogic() class with rule-based inference

Both ported in this task."""
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

def test_fuzzy_logic_class_get_result_with_no_rules_is_zero():
    pFuzzy = App.FuzzyLogic()
    pFuzzy.SetMaxRules(4)
    assert pFuzzy.GetResultBySet(0) == 0.0


def test_fuzzy_logic_class_single_rule_passes_through_input_to_output():
    """AddRule(in, out) + SetPercentageInSet(in, 0.7) → GetResultBySet(out) >= 0.7."""
    pFuzzy = App.FuzzyLogic()
    pFuzzy.SetMaxRules(4)
    pFuzzy.AddRule(input_set_id=0, output_set_id=10)
    pFuzzy.SetPercentageInSet(0, 0.7)
    assert pFuzzy.GetResultBySet(10) == pytest.approx(0.7)


def test_fuzzy_logic_class_multiple_rules_to_same_output_max_combines():
    """Two rules contributing to the same output: result is max of their inputs."""
    pFuzzy = App.FuzzyLogic()
    pFuzzy.SetMaxRules(4)
    pFuzzy.AddRule(input_set_id=0, output_set_id=10)
    pFuzzy.AddRule(input_set_id=1, output_set_id=10)
    pFuzzy.SetPercentageInSet(0, 0.4)
    pFuzzy.SetPercentageInSet(1, 0.7)
    assert pFuzzy.GetResultBySet(10) == pytest.approx(0.7)


def test_fuzzy_logic_class_unmatched_output_returns_zero():
    """Output set not referenced by any rule → 0.0."""
    pFuzzy = App.FuzzyLogic()
    pFuzzy.AddRule(0, 10)
    pFuzzy.SetPercentageInSet(0, 0.9)
    assert pFuzzy.GetResultBySet(99) == 0.0
