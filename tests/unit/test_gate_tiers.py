"""The gate tiers' deep lists have not rotted (spec docs/superpowers/specs/
2026-11-06-two-tier-test-gate-design.md). Merge tier, by the protection rule.

Everything is merge-tier unless tests/gate_tiers/deep_pytest.txt or
deep_gtest.txt lists it; both are GENERATED (tools/gate_tiers.py generate).
These checks are static and cheap: every entry still names something real,
nothing protected was demoted, every area keeps merge-tier coverage, and the
files are in the generator's own order.
"""
import glob
import os
import re

from tests.helpers import gate_tiers as gt

ROOT = gt.ROOT


def _gtest_binaries():
    pat = re.compile(r"gtest_discover_tests\(\s*(\w+)")
    found = set()
    for f in glob.glob(os.path.join(ROOT, "native", "**", "CMakeLists.txt"), recursive=True):
        with open(f, encoding="utf-8") as fh:
            found |= set(pat.findall(fh.read()))
    return found


def test_every_deep_pytest_entry_names_a_real_test():
    stale = [e for e in gt.load_deep_pytest() if not gt.pytest_entry_exists(e)]
    assert not stale, ("deep_pytest.txt names tests that no longer exist -- "
                       "regenerate (tools/gate_tiers.py generate): %s" % stale)


def test_every_deep_gtest_entry_names_a_real_test():
    known, binaries = gt.cpp_tests(), _gtest_binaries()
    stale = [(b, n) for b, names in gt.load_deep_gtest().items() for n in names
             if b not in binaries or gt.split_gtest(n) not in known]
    assert not stale, ("deep_gtest.txt names tests that no longer exist -- "
                       "regenerate: %s" % stale[:20])


def test_no_protected_guard_is_demoted():
    demoted = [e for e in gt.load_deep_pytest()
               if gt.is_protected(e.split("::", 1)[0])]
    assert not demoted, demoted


def test_the_protection_rule_names_real_guards():
    for f in gt.PROTECTED_FILES:
        assert os.path.isfile(os.path.join(ROOT, f)), f
    drift = [f for f in gt.all_test_files() if gt.is_protected(f) and "drift" in f]
    assert len(drift) >= 6, drift


def test_every_area_keeps_merge_tier_coverage():
    """Every tests/<dir> keeps a merge-tier file, and every engine package or
    top-level module some test imports is imported by a merge-tier file."""
    assert gt.coverage_gaps(gt.load_deep_pytest()) == []


def test_coverage_gaps_sees_a_demoted_area():
    """The check above can fail: demote every file of tests/missions and
    every file importing engine.planets, and both are named."""
    missions = [f for f in gt.all_test_files() if f.startswith("tests/missions/")]
    planets = [f for f in gt.all_test_files()
               if "planets" in gt.engine_imports(os.path.join(ROOT, f), gt.engine_areas())]
    gaps = gt.coverage_gaps(missions + planets)
    assert "tests/missions" in gaps and "engine/planets" in gaps, gaps


def test_the_lists_are_in_generator_order():
    py = gt.load_deep_pytest()
    assert py == sorted(py), "deep_pytest.txt was hand-edited; regenerate it"
    with open(gt.DEEP_GTEST, encoding="utf-8") as fh:
        rows = [l.strip() for l in fh if l.strip() and not l.startswith("#")]
    assert rows == sorted(rows), "deep_gtest.txt was hand-edited; regenerate it"


def test_a_new_test_is_merge_tier_by_rule():
    is_deep = gt.deep_matcher(gt.load_deep_pytest())
    assert not is_deep("tests/unit/test_some_file_added_tomorrow.py::test_x")
    assert not is_deep("tests/unit/test_gate_tiers.py::"
                       "test_a_new_test_is_merge_tier_by_rule")
