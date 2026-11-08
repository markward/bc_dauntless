"""Native stock preprocessors vs the SDK Python, same seeded scene, byte for
byte (phase 6 AI part 2). Harness: tests/helpers/native_ai_ab.py (each side in
its own subprocess, ai_native._force_python set against clear).

Each scene also asserts, for every kind native so far, that its ``native``
count is > 0 and its ``python`` count is 0 or explained. Native so far:
``avoid`` (Task 2, AvoidObstacles' obstacle scan), ``select`` (Task 3,
SelectTarget's GetTargetRating) and ``fire`` (Task 4, FireScript's Update;
Task 5 made its ChooseTargetSubsystem and ChooseTorpType native too, counted
``subsystem_choice``, ``torp_choice`` and ``torp_rated`` -- a choice between
two or more ammo types)."""
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
    # The forced-Python side must never report a native call.
    native_ai_ab.assert_no_native(py_stats)
    return stats


def _assert_choices(stats, *keys):
    counts = stats["fire"]["counts"]
    for key in keys:
        assert counts.get(key, 0) > 0, ("native %s never ran" % key, counts)


def test_k1_gameloop_ai():
    stats = _same("k1_gameloop_ai")
    native_ai_ab.assert_native(stats, "avoid")
    native_ai_ab.assert_native(stats, "select")        # ungated
    native_ai_ab.assert_native(stats, "fire")
    _assert_choices(stats, "subsystem_choice", "torp_choice", "torp_rated")


def test_combat_stress_gated():
    stats = _same("combat_stress_gated")
    native_ai_ab.assert_native(stats, "avoid")
    native_ai_ab.assert_native(stats, "select")        # sensor gate installed
    native_ai_ab.assert_native(stats, "fire")


def test_k1_gameloop_ai_with_the_memos_off():
    """The host memos forced off (DAUNTLESS_AI_MEMOS=0: what a Python other
    than 3.11, or a failed memo self-test, runs): every gate decided in
    Python every call, and the fight still byte-identical."""
    py, native, stats, py_stats, memos = native_ai_ab.run_ab_env(
        "k1_gameloop_ai", {"DAUNTLESS_AI_MEMOS": "0"})
    assert memos["enabled"] is False and memos["forced_off"] is True, memos
    assert py == native, native_ai_ab.first_difference(py, native)
    native_ai_ab.assert_no_native(py_stats)
    native_ai_ab.assert_native(stats, "avoid")
    native_ai_ab.assert_native(stats, "select")
    native_ai_ab.assert_native(stats, "fire")
    _assert_choices(stats, "subsystem_choice", "torp_choice", "torp_rated")


def test_cloak_attack():
    # No `select` assertion: the scene has ONE target, and FindGoodTarget
    # returns a lone candidate unrated (AI/Preprocessors.py:1462-1464), so
    # GetTargetRating is never called on either side. The rating is covered
    # by the scenes above and tests/unit/test_native_target_rating.py.
    stats = _same("cloak_attack")
    native_ai_ab.assert_native(stats, "fire")


def test_fed_subsystems():
    # The child also asserts the subsystem-rating RNG drew, and from the
    # native ChooseTargetSubsystem on this side (tests/helpers/native_ai_ab.py).
    stats = _same("fed_subsystems")
    native_ai_ab.assert_native(stats, "avoid")
    native_ai_ab.assert_native(stats, "select")
    native_ai_ab.assert_native(stats, "fire")
    _assert_choices(stats, "subsystem_choice", "torp_choice", "torp_rated")


def test_akira_torp_select():
    # No `fire` assertion: the scene calls the SDK's ChooseTorpType directly,
    # never Update, so it never reaches the native one. The native choice
    # (Update -> ConfigureWeaponSystem -> ChooseTorpType) is asserted in
    # k1_gameloop_ai and fed_subsystems (`torp_rated`), and pinned call by
    # call in tests/unit/test_native_fire_script.py (torp_choice,
    # torp_bad_script).
    _same("akira_torp_select")


def test_sdk_dumb_fire():
    stats = _same("sdk_dumb_fire")
    native_ai_ab.assert_native(stats, "avoid")
    native_ai_ab.assert_native(stats, "select")
    native_ai_ab.assert_native(stats, "fire")


def test_pursuers_converge():
    """The one scene where avoidance really fires (the fights above never put
    an obstacle on a collision course): records byte-identical, and the native
    scans returned objects to avoid."""
    stats = _same("pursuers_converge")
    native_ai_ab.assert_native(stats, "avoid")
    native_ai_ab.assert_native(stats, "fire")          # the Keldons' FireScripts
    assert stats["avoid"]["counts"].get("avoided", 0) > 0, stats


def test_the_forced_python_side_reports_no_native_calls_and_assert_helpers_bite():
    _py, _nat, stats, py_stats = native_ai_ab.run_ab_full("akira_torp_select")
    native_ai_ab.assert_no_native(py_stats)
    with pytest.raises(AssertionError):
        # The scene never calls an Update: nothing ran native.
        native_ai_ab.assert_native(stats, "fire")
    forged = {k: {"native": 1, "python": 1, "reasons": {"not_stock": 1}}
              for k in stats}
    native_ai_ab.assert_native(forged, "fire", allowed_python=("not_stock",))
    with pytest.raises(AssertionError):
        native_ai_ab.assert_native(forged, "fire")
    with pytest.raises(AssertionError):
        native_ai_ab.assert_no_native(forged)
    # Empty or partial counters prove nothing: every kind must be reported.
    with pytest.raises(AssertionError):
        native_ai_ab.assert_no_native({})
    with pytest.raises(AssertionError):
        native_ai_ab.assert_no_native({"avoid": py_stats["avoid"]})
