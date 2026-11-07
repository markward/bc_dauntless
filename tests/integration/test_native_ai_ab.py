"""Native stock preprocessors vs the SDK Python, same seeded scene, byte for
byte (phase 6 AI part 2). Harness: tests/helpers/native_ai_ab.py (each side in
its own subprocess, DAUNTLESS_NATIVE_AI=0 against unset).

No preprocessor is native yet (Task 1), so the two records are the same run
twice and the counters read zero. From Task 2 on each scene also asserts its
kind's ``native`` count is > 0 and its ``python`` count is 0 or explained."""
import pytest

from tests.helpers import native_ai_ab

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_k1_next"),
    reason="native K1 bindings not built")


def _same(scene):
    py, native, stats, py_stats = native_ai_ab.run_ab_full(scene)
    assert py == native, native_ai_ab.first_difference(py, native)
    # The DAUNTLESS_NATIVE_AI=0 side must never report a native call.
    native_ai_ab.assert_no_native(py_stats)
    return stats


# TODO(per task): each scene switches on `native_ai_ab.assert_native(stats,
# kind[, allowed_python])` as its kind goes native:
#   Task 2 (avoid):  combat_stress_gated, k1_gameloop_ai, fed_subsystems
#   Task 3 (select): combat_stress_gated (gate installed), k1_gameloop_ai
#                    (ungated), cloak_attack, fed_subsystems
#   Task 4/5 (fire): k1_gameloop_ai, sdk_dumb_fire, fed_subsystems,
#                    akira_torp_select, cloak_attack
# Until then every kind reads native == 0 and the records are one run twice.


def test_k1_gameloop_ai():
    _same("k1_gameloop_ai")


def test_combat_stress_gated():
    _same("combat_stress_gated")


def test_cloak_attack():
    _same("cloak_attack")


def test_fed_subsystems():
    _same("fed_subsystems")


def test_akira_torp_select():
    _same("akira_torp_select")


def test_sdk_dumb_fire():
    _same("sdk_dumb_fire")


def test_the_switch_off_side_reports_no_native_calls_and_assert_helpers_bite():
    _py, _nat, stats, py_stats = native_ai_ab.run_ab_full("akira_torp_select")
    native_ai_ab.assert_no_native(py_stats)
    with pytest.raises(AssertionError):
        native_ai_ab.assert_native(stats, "fire")      # nothing native yet
    forged = {k: {"native": 1, "python": 1, "reasons": {"not_stock": 1}}
              for k in stats}
    native_ai_ab.assert_native(forged, "fire", allowed_python=("not_stock",))
    with pytest.raises(AssertionError):
        native_ai_ab.assert_native(forged, "fire")
    with pytest.raises(AssertionError):
        native_ai_ab.assert_no_native(forged)
