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
    py, native, stats = native_ai_ab.run_ab(scene)
    assert py == native, native_ai_ab.first_difference(py, native)
    return stats


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
