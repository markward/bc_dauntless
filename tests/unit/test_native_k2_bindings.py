"""The K2 beam kernel's bindings (native combat phase 2, Task 4): the record
tuples, the context dict and the answer shapes of combat_k2_* on real ships
(k2_beams.h documents every layout). The walk itself is pinned by the gtests
(native/tests/combat/k2_beams_test.cc); the native-vs-Python differential is
Task 5's (tests/unit/test_native_k2_dispatch.py)."""
import importlib
import sys

import pytest

import App

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_k2_next"),
    reason="native K2 bindings not built")

from engine.appc import native_combat as nc  # noqa: E402
from engine.appc import passive_state  # noqa: E402

ON = {"DAUNTLESS_NATIVE_COMBAT": "1"}
DT = 1.0 / 60.0


@pytest.fixture(autouse=True)
def _switch():
    nc.reset()
    passive_state.reset()
    nc.configure(ON)
    assert nc.enabled()
    yield
    if _h.combat_k2_open():
        _h.combat_k2_abandon()
    nc.reset()
    passive_state.reset()
    App.g_kModelPropertyManager.ClearLocalTemplates()


def _ship(pset, name, hardpoint, at):
    ship = App.ShipClass_Create(name)
    mod_name = "ships.Hardpoints." + hardpoint
    App.g_kModelPropertyManager.ClearLocalTemplates()
    if mod_name in sys.modules:
        importlib.reload(sys.modules[mod_name])
    else:
        importlib.import_module(mod_name)
    sys.modules[mod_name].LoadPropertySet(ship.GetPropertySet())
    ship.SetupProperties()
    ship.SetTranslateXYZ(*at)
    pset.AddObjectToSet(ship, name)
    return ship


@pytest.fixture()
def scene():
    pset = App.SetClass_Create()
    App.g_kSetManager.AddSet(pset, "k2_bindings")
    a = _ship(pset, "A", "galaxy", (0.0, 0.0, 0.0))
    b = _ship(pset, "B", "galaxy", (0.0, 60.0, 0.0))
    sys_ = a.GetPhaserSystem()
    sys_.TurnOn()
    assert sys_.IsOn()
    yield pset, a, b, sys_
    App.g_kSetManager.DeleteSet("k2_bindings")


def _kinds():
    k = _h.combat_k2_kinds()
    assert list(k) == ["DONE", "SYSTEM_STOP", "BANK_STOP", "CONTACT",
                       "RUN_PYTHON", "ASK"]
    assert list(k.values()) == list(range(6))
    return k


def _sub(obj):
    """A Subsystem's row handle (nc.slot names Object rows only)."""
    return obj.__dict__["_nslot"]


def _bank_in_arc(sys_, ship, target):
    """A bank of `sys_` whose arc holds `target` (the arc gate passes)."""
    from engine.appc import weapon_subsystems as ws
    for i in range(sys_.GetNumWeapons()):
        bank = sys_.GetWeapon(i)
        if ws._emitter_in_arc(bank, ship,
                              ws._resolve_bank_aim_world(bank, target)):
            return bank
    raise AssertionError("no bank in arc")


def _set_handle(ship):
    return _h.combat_dump(nc.slot(ship))["_containing_set"]


def test_contact_record_layout(scene):
    pset, a, b, sys_ = scene
    k = _kinds()
    bank = _bank_in_arc(sys_, a, b)
    bank._firing = True
    bank._target = b
    bank._beam_on_countdown = 0.0
    bank._dwell = 0.125
    ctx = {"view_offsets": {_set_handle(a): None}, "trace": False}
    _h.combat_k2_begin([nc.slot(a)], DT, 100.0, True, 0.0, ctx)
    rec = _h.combat_k2_next()
    # Every other bank of A is idle at +0.0: no writes, no records.
    assert rec[0] == k["CONTACT"]
    (_, rbank, rtarget, rship, rsys, emitter, target_pos, dist, aim_unit,
     impact, normal, tier, bubble, shields, flush, writes) = rec
    assert (rbank, rtarget, rship, rsys) == (
        _sub(bank), nc.slot(b), nc.slot(a), _sub(sys_))
    assert writes == [(_sub(bank), "_dwell", 0.125 + DT)]
    # The geometry is the Task 2 ports' (no lock: the hull centre).
    pos, sub = _h.combat_test_phaser_aim_point(nc.slot(a), nc.slot(b), True)
    assert sub == -1 and target_pos == tuple(pos)
    assert emitter == tuple(_h.combat_test_strip_emit_position(
        _sub(bank), pos, True))
    assert isinstance(dist, float) and len(aim_unit) == 3
    # No instance in the table: the fallback point IS target_pos.
    assert tier == "fallback" and impact == target_pos and normal is None
    assert shields in (True, False) and flush == 0.0
    assert bubble is None
    rec = _h.combat_k2_next()
    assert rec == (k["DONE"], [])
    _h.combat_k2_end()
    assert not _h.combat_k2_open()
    # The kernel wrote the mirror; Python applies the log (Task 5).
    assert _h.combat_dump(_sub(bank))["_dwell"] == 0.125 + DT
    counts = _h.combat_k2_counts()
    assert set(counts) == {"k2_records", "k2_python_ships", "k2_asks",
                           "k2_python_reasons", "k2_ask_queries"}
    assert set(counts["k2_ask_queries"]) == {
        "is_dead", "can_detect", "aim_point", "shields_block", "bubble",
        "resolve_hit", "bank_step"}


def test_context_and_ask_answers(scene):
    pset, a, b, sys_ = scene
    k = _kinds()
    bank = _bank_in_arc(sys_, a, b)
    bank._firing = True
    bank._target = b
    bank._beam_on_countdown = 0.0
    # An instance but no view offset for the set: ASK resolve_hit. A value
    # that is not an InstanceId is accepted (the sphere tier).
    ctx = {"iids": {nc.slot(b): "not an id", nc.slot(a): None},
           "trace": False}
    _h.combat_k2_begin([nc.slot(a)], DT, 100.0, True, 0.0, ctx)
    rec = _h.combat_k2_next()
    assert rec[0] == k["ASK"] and rec[1] == "resolve_hit"
    target, emitter, direction, max_dist, fallback, writes = rec[2:]
    assert target == nc.slot(b) and len(emitter) == 3 and len(direction) == 3
    assert isinstance(max_dist, float) and len(fallback) == 3
    with pytest.raises(ValueError):
        _h.combat_k2_answer(((0.0, 1.0, 2.0), None, "nowhere"))
    _h.combat_k2_answer(((0.0, 1.0, 2.0), (0.0, -1.0, 0.0), "mesh"))
    rec = _h.combat_k2_next()
    assert rec[0] == k["CONTACT"]
    assert rec[9:12] == ((0.0, 1.0, 2.0), (0.0, -1.0, 0.0), "mesh")
    assert _h.combat_k2_next()[0] == k["DONE"]
    _h.combat_k2_end()

    # set_ctx replaces only the keys it is given: with the offset now known
    # the bad iid takes the sphere tier natively, and the cheat reads off.
    _h.combat_k2_begin([nc.slot(a)], DT, 100.0, True, 0.0, ctx)
    _h.combat_k2_set_ctx({"view_offsets": {_set_handle(a): None}})
    rec = _h.combat_k2_next()
    assert rec[0] == k["CONTACT"] and rec[11] in ("sphere", "fallback",
                                                  "origin")
    assert _h.combat_k2_next()[0] == k["DONE"]
    _h.combat_k2_end()
    assert _h.combat_k2_counts()["k2_ask_queries"]["resolve_hit"] >= 1


def test_protocol_errors_raise(scene):
    with pytest.raises(RuntimeError):
        _h.combat_k2_next()             # no session
    with pytest.raises(RuntimeError):
        _h.combat_k2_answer(True)       # no ASK
    _, a, _b, _sys = scene
    _h.combat_k2_begin([nc.slot(a)], DT, 100.0, True, 0.0, {})
    with pytest.raises(RuntimeError):
        _h.combat_k2_begin([nc.slot(a)], DT, 100.0, True, 0.0, {})
    _h.combat_k2_abandon()
    assert not _h.combat_k2_open()


def test_system_stop_and_run_python(scene):
    _, a, b, sys_ = scene
    k = _kinds()
    sys_.TurnOff()
    _h.combat_k2_begin([nc.slot(a), -1], DT, 100.0, True, 0.0,
                       {"python_ships": [nc.slot(b)]})
    assert _h.combat_k2_next() == (k["SYSTEM_STOP"], _sub(sys_), [])
    assert _h.combat_k2_next() == (k["RUN_PYTHON"], -1, 1, [])
    assert _h.combat_k2_next() == (k["DONE"], [])
    _h.combat_k2_end()
    _h.combat_k2_begin([nc.slot(b)], DT, 100.0, True, 0.0,
                       {"python_ships": [nc.slot(b)]})
    assert _h.combat_k2_next() == (k["RUN_PYTHON"], nc.slot(b), 0, [])
    _h.combat_k2_next()
    _h.combat_k2_end()
    reasons = _h.combat_k2_counts()["k2_python_reasons"]
    assert reasons["unslotted_ship"] >= 1 and reasons["overridden"] >= 1
