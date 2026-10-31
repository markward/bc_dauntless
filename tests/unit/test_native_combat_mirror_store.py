"""The native combat mirror store's Python surface (native/src/combat/mirror.cc).

Rows are registered and written from Python, read back with combat_dump, and
a stale handle is a ValueError.
"""
import pytest

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_register"),
    reason="native combat bindings not built")

OBJECT, SUBSYSTEM, PROPERTY, SET, PROFILE = range(5)


@pytest.fixture(autouse=True)
def _clean():
    _h.combat_clear()
    yield
    _h.combat_clear()


def test_field_names_round_trip():
    names = _h.combat_field_names()
    assert names
    assert len(set(names.values())) == len(names)
    assert all(isinstance(v, int) for v in names.values())
    for k in ("_dead", "_known_objects", "MaxCondition_set", "ships", "rows"):
        assert k in names


def test_dump_reflects_setters():
    f = _h.combat_field_names()
    o = _h.combat_register(OBJECT, 3, 4, 99)
    s = _h.combat_register(SUBSYSTEM)
    st = _h.combat_register(SET)
    _h.combat_set_f(o, f["_life_time"], 1.5)
    _h.combat_set_i(o, f["_dead"], 1)
    _h.combat_set_ref(o, f["_sensor_subsystem"], s)
    _h.combat_set_fv(o, f["_seed"], [1.0, 2.0, 3.0])
    _h.combat_set_spheres(o, [(0.0, 1.0, 2.0, 3.0)])
    _h.combat_set_ids(s, f["_known_objects"], [9, 3, 9])
    _h.combat_set_ids(s, f["_probe_ids"], [7, 1])
    _h.combat_set_ids(st, f["ships"], [o])
    d = _h.combat_dump(o)
    assert d["_life_time"] == 1.5
    assert d["_dead"] == 1
    assert d["obj_id"] == 99 and d["xform_index"] == 3 and d["xform_gen"] == 4
    assert d["_sensor_subsystem"] == s
    assert d["_cloaking_subsystem"] == -1
    assert d["_seed"] == (1.0, 2.0, 3.0)
    assert d["_fbm"] is None
    assert d["spheres"] == [(0.0, 1.0, 2.0, 3.0)]
    sd = _h.combat_dump(s)
    assert sd["_known_objects"] == [3, 9]
    assert sd["_probe_ids"] == [7, 1]
    assert _h.combat_dump(st)["ships"] == [o]
    assert _h.combat_find_by_obj_id(99) == o
    pr = _h.combat_register(PROFILE)
    _h.combat_set_profile_rows(pr, [(10.0, 0.5), (20.0, 1.0)], 0.25)
    pd = _h.combat_dump(pr)
    assert pd["rows"] == [(10.0, 0.5), (20.0, 1.0)]
    assert pd["full_concealment"] == 0.25


def test_epoch_rises():
    e = _h.combat_epoch()
    s = _h.combat_register(SUBSYSTEM)
    _h.combat_set_f(s, _h.combat_field_names()["_condition"], 1.0)
    assert _h.combat_epoch() > e


def test_unregister_then_stale_handle_raises_value_error():
    f = _h.combat_field_names()
    s = _h.combat_register(SUBSYSTEM)
    _h.combat_unregister(s)
    with pytest.raises(ValueError):
        _h.combat_set_f(s, f["_condition"], 1.0)
    with pytest.raises(ValueError):
        _h.combat_dump(s)
    assert _h.combat_find_by_obj_id(12345) == -1


def test_wrong_kind_field_raises_value_error():
    f = _h.combat_field_names()
    p = _h.combat_register(PROPERTY)
    with pytest.raises(ValueError):
        _h.combat_set_f(p, f["_life_time"], 1.0)
