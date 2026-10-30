"""Bridge AO look dials (engine/bridge_ao_dials.py)."""
import inspect

from engine import bridge_ao_dials, dev_dial_groups, renderer


def test_defaults_are_todays_look():
    # Must match renderer::BridgeAoTuning's defaults (bridge_ao_pass.h), which
    # bridge_ao_test.cc pins to kBridgeLighting: an untouched dial set changes
    # nothing.
    d = bridge_ao_dials.current()
    assert (d["radius"], d["strength"], d["bias"]) == (30.0, 1.8, 0.5)
    assert (d["bias_dist"], d["bias_facing"], d["min_len"]) == (0.01, 0.0, 0.1)
    assert d["detail_samples"] == 0


def test_step_pushes_the_whole_set_and_clamps():
    pushed = []
    dev_dial_groups.reset()
    bridge_ao_dials.register(pushed.append)
    assert dev_dial_groups.set_active("bridge ao")
    bridge_ao_dials._step("detail_samples", +1)
    assert pushed[-1]["detail_samples"] == 4
    assert isinstance(pushed[-1]["detail_samples"], int)
    assert set(pushed[-1]) == set(bridge_ao_dials.DIAL_ORDER)
    for _ in range(20):
        bridge_ao_dials._step("bias_facing", +1)
    assert bridge_ao_dials.current()["bias_facing"] == 1.0
    for _ in range(20):
        bridge_ao_dials._step("min_len", -1)
    assert bridge_ao_dials.current()["min_len"] == 0.01
    dev_dial_groups.reset()


def test_dials_match_the_renderer_wrapper_arguments():
    # host_loop pushes with set_bridge_ao_tuning(**dials): every dial must be
    # a parameter, in the binding's order.
    params = tuple(inspect.signature(renderer.set_bridge_ao_tuning).parameters)
    assert params == bridge_ao_dials.DIAL_ORDER
    assert "set_bridge_ao_tuning" in renderer._REQUIRED_BINDINGS
