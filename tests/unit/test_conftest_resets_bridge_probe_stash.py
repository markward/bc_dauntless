"""The per-test reset must restore the native bridge probe stash.

The stash (origin + per-state scales, renderer/bridge_probe) is process-
lifetime C++ state. Any test that boots a bridge mission through
host_loop.run() -- tests/host/test_host_loop_lighting.py::
test_verbose_mode_logs_lighting_on_tick0 boots E1M1 -- leaves it at the
bridge camera eye with scales 0, and test_bridge_editor_bindings.py::
test_probe_stash_is_at_defaults failed whenever it ran after one
(2026-10-18). Two tests, ordered by name, stand in for that pair here."""
import pytest

h = pytest.importorskip("_dauntless_host")


def test_a_leaves_the_stash_where_a_bridge_boot_would():
    h.set_bridge_probe_origin((0.68, 86.98, 50.0))
    h.set_bridge_probe_scales((0.0,) * 5)


def test_b_sees_the_stash_at_defaults_again():
    st = h.bridge_probe_stash()
    assert st["origin"] == pytest.approx((0.0, 0.0, 0.0)), (
        "conftest._reset_leakable_engine_globals does not restore the bridge "
        "probe origin between tests")
    assert st["scales"] == pytest.approx((1.0,) * 5)
