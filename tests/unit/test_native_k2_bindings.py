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
    # A damage pulse (the dwell past the flush): a CONTACT record.
    bank._dwell = 0.6
    ctx = {"view_offsets": {_set_handle(a): None}, "trace": False}
    _h.combat_k2_begin([nc.slot(a)], DT, 100.0, True, 0.0, ctx)
    rec = _h.combat_k2_next()
    # Every other bank of A is idle at +0.0: no writes, no records.
    assert rec[0] == k["CONTACT"]
    assert len(rec) == 16 and rec[14] == 0.6 + DT
    assert rec[-1] == [(_sub(bank), "_dwell", 0.0)]
    assert _h.combat_k2_next() == (k["DONE"], [])
    assert _h.combat_k2_drain() == []
    _h.combat_k2_end()
    # A resting contact: no record of its own; DONE carries the writes and
    # the drain (after DONE, before end) hands it over as CONTACT's fields
    # plus the values taken at contact time (level, iid, view offset).
    bank._dwell = 0.125
    sys_.SetPowerLevel(sys_.PP_LOW)
    _h.combat_k2_begin([nc.slot(a)], DT, 100.0, True, 0.0, ctx)
    rec = _h.combat_k2_next()
    assert rec[0] == k["DONE"] and len(rec) == 2
    writes = rec[1]
    entries = _h.combat_k2_drain()
    assert len(entries) == 1
    (rbank, rtarget, rship, rsys, emitter, target_pos, dist, aim_unit,
     impact, normal, tier, bubble, shields, flush, level, iid,
     view_offset) = entries[0]
    assert _h.combat_k2_drain() == []           # the drain empties it
    assert level == sys_.PP_LOW and type(level) is int
    assert iid is None and view_offset is None  # no instance; no shift
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
    from engine.appc import combat
    assert shields is bool(combat.shields_block(b)) and flush == 0.0
    assert bubble is None
    _h.combat_k2_end()
    assert not _h.combat_k2_open()
    # The kernel wrote the mirror; Python applies the log (Task 5).
    assert _h.combat_dump(_sub(bank))["_dwell"] == 0.125 + DT
    counts = _h.combat_k2_counts()
    assert set(counts) == {"k2_records", "k2_python_ships", "k2_asks",
                           "k2_python_reasons", "k2_ask_queries", "k2_posed",
                           "k2_batched_contacts", "k2_logged_system_stop",
                           "k2_logged_firing_system_stop",
                           "k2_logged_bank_stop", "k2_entries",
                           "k2_present_native", "k2_native_pulses",
                           "k2_pulse_python", "k2_pulse_python_reasons"}
    # No pulse context sent: a damage pulse is a CONTACT record (THE DAMAGE
    # PULSE, native damage Task 4), counted not_ok.
    assert set(counts["k2_pulse_python_reasons"]) == {
        "not_ok", "unscanned", "level", "fallback", "python"}
    assert counts["k2_native_pulses"] == 0, counts
    # K1Effect's names (K2 appends only LOOP_STOP; SPAWN and AMMO_CONSUMED
    # are K1's launch entries, launch deferral; TRACTOR_STARTED / _STOPPED
    # its tractor walk's, fire control native only R8).
    assert set(counts["k2_entries"]) == {
        "FIRE_SOUND", "LOOP_STOP", "WEAPON_FIRED", "WEAPON_FIRE_FAILED",
        "SPAWN", "AMMO_CONSUMED", "TRACTOR_STARTED", "TRACTOR_STOPPED"}
    assert counts["k2_batched_contacts"] == 1, counts
    # No applier context (and no constants sent): the drain presented none.
    assert counts["k2_present_native"] == 0, counts
    assert counts["k2_posed"] == {"banks": 0, "lock_aims": 0}
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
    # A resting contact: drained after DONE, the answer in its fields; the
    # value that is not an InstanceId is no iid, and the set has no offset.
    rec = _h.combat_k2_next()
    assert rec[0] == k["DONE"]
    (entry,) = _h.combat_k2_drain()
    assert entry[8:11] == ((0.0, 1.0, 2.0), (0.0, -1.0, 0.0), "mesh")
    assert entry[15:] == (None, None)
    _h.combat_k2_end()

    # set_ctx replaces only the keys it is given: with the offset now known
    # the bad iid takes the sphere tier natively, and the cheat reads off.
    _h.combat_k2_begin([nc.slot(a)], DT, 100.0, True, 0.0, ctx)
    _h.combat_k2_set_ctx({"view_offsets": {_set_handle(a): None}})
    rec = _h.combat_k2_next()
    assert rec[0] == k["DONE"]
    assert _h.combat_k2_drain()[0][10] in ("sphere", "fallback", "origin")
    _h.combat_k2_end()

    # An InstanceId and a shifted set: both ride the entry, as they were.
    iid = _h.InstanceId()
    _h.combat_k2_begin([nc.slot(a)], DT, 100.0, True, 0.0,
                       {"iids": {nc.slot(b): iid},
                        "view_offsets": {_set_handle(a): (1.0, 2.0, 3.0)},
                        "trace": False})
    assert _h.combat_k2_next()[0] == k["DONE"]
    (entry,) = _h.combat_k2_drain()
    got = entry[15]
    assert isinstance(got, _h.InstanceId)
    assert (got.index, got.generation) == (iid.index, iid.generation)
    assert entry[16] == (1.0, 2.0, 3.0)
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
    with pytest.raises(RuntimeError):
        _h.combat_k2_drain()            # before DONE
    _h.combat_k2_abandon()
    assert not _h.combat_k2_open()
    assert _h.combat_k2_drain() == []   # no session: nothing queued


def test_system_stop_and_run_python(scene):
    _, a, b, sys_ = scene
    k = _kinds()
    sys_.TurnOff()
    # A bank firing: logged too, its loop sound's LOOP_STOP queued after its
    # writes (combat fire events Task 4); the record that carries them (the
    # rowless ship's RUN_PYTHON) appends it to the effect queue.
    sys_.GetWeapon(0)._firing = True
    _h.combat_effect_clear()
    _h.combat_k2_begin([nc.slot(a), -1], DT, 100.0, True, 0.0,
                       {"python_ships": [nc.slot(b)]})
    rec = _h.combat_k2_next()
    assert rec[:3] == (k["RUN_PYTHON"], -1, 1)
    assert rec[3][5:7] == [(_sub(sys_.GetWeapon(0)), "_firing", False),
                           (_sub(sys_.GetWeapon(0)), "_beam_on_countdown",
                            0.0)]
    kinds = _h.combat_effect_kinds()
    assert _h.combat_effect_take() == [
        (kinds["LOOP_STOP"], True, (_sub(sys_.GetWeapon(0)),))]
    assert _h.combat_k2_next() == (k["DONE"], [])
    _h.combat_k2_end()
    assert _h.combat_k2_counts()["k2_logged_firing_system_stop"] == 1
    # Every bank idle: the stop is logged writes in the value encoding
    # (round trips Task 3), the system's five then each bank's two.
    sys_.GetWeapon(0)._firing = False
    _h.combat_k2_begin([nc.slot(a)], DT, 100.0, True, 0.0, {})
    rec = _h.combat_k2_next()
    assert rec[0] == k["DONE"] and len(rec) == 2
    h = _sub(sys_)
    assert rec[1][:5] == [(h, "_fire_held", False), (h, "_held_target", -1),
                          (h, "_held_offset", None), (h, "_target_list", []),
                          (h, "_last_group_fired", -1)]
    banks = [_sub(sys_.GetWeapon(i)) for i in range(sys_.GetNumWeapons())]
    assert rec[1][5:] == [w for bh in banks for w in (
        (bh, "_firing", False), (bh, "_beam_on_countdown", 0.0))]
    assert type(rec[1][0][2]) is bool and type(rec[1][4][2]) is int
    _h.combat_k2_end()
    assert _h.combat_k2_counts()["k2_logged_system_stop"] == 2
    _h.combat_k2_begin([nc.slot(b)], DT, 100.0, True, 0.0,
                       {"python_ships": [nc.slot(b)]})
    assert _h.combat_k2_next() == (k["RUN_PYTHON"], nc.slot(b), 0, [])
    _h.combat_k2_next()
    _h.combat_k2_end()
    reasons = _h.combat_k2_counts()["k2_python_reasons"]
    assert reasons["unslotted_ship"] >= 1 and reasons["overridden"] >= 1
