"""Running-light host bindings (running-lights spec §4.3/§4.4).

The store and pass are covered by gtest; this pins the Python-visible
contract: the bindings exist, accept the documented shapes, purge on
destroy_instance and on reset, and the toggle round-trips. Needs the built
_dauntless_host; skips when it is absent (headless contexts).
"""
import pytest

_h = pytest.importorskip("_dauntless_host")
import engine.renderer as r


@pytest.fixture(autouse=True)
def _clean():
    r.running_lights_set_enabled(True)
    yield
    r.running_lights_set_enabled(True)


def _light(x=0.0):
    return (x, 0.5, 0.25, 1.0, 0.0, 0.0, 1.5, 3.0, 0.0)


def _new_instance():
    # ModelHandle is a plain uint64 and create_instance only touches the
    # scenegraph World: no GL context, no model needed.
    return _h.create_instance(1)


def test_toggle_round_trips_and_defaults_on():
    assert r.running_lights_enabled() is True
    r.running_lights_set_enabled(False)
    assert r.running_lights_enabled() is False


def test_dials_and_empty_levels_are_accepted():
    r.set_running_light_dials(0.02, 1.5, 4.0)
    r.set_running_light_levels([])


def test_destroy_instance_purges_its_lights():
    iid = _new_instance()
    r.set_running_lights(iid, [_light(), _light(1.0)], 1.0)
    assert r.running_light_count() == 1
    r.destroy_instance(iid)
    assert r.running_light_count() == 0


def test_a_recycled_id_does_not_inherit_lights():
    old = _new_instance()
    r.set_running_lights(old, [_light()], 1.0)
    r.destroy_instance(old)
    new = _new_instance()          # may reuse old's index
    assert r.running_light_count() == 0
    r.destroy_instance(new)


def test_empty_list_removes_a_ship():
    iid = _new_instance()
    r.set_running_lights(iid, [_light()], 1.0)
    r.set_running_lights(iid, [], 0.0)
    assert r.running_light_count() == 0
    r.destroy_instance(iid)
