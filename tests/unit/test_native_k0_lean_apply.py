"""K0's lean write-back (phase 6 A2; native/src/host/combat_write_apply.h,
THE LEAN K0 APPLY).

The binding applies each K0 record's write log itself: one registry lookup
per run of writes to one weapon, a store straight into its instance dict
(no pins dict, no per-write kind lookup), the WAKE fields' wake check kept
(K0 never sleeps a weapon, but one put to sleep by the Python walk may still
be asleep), and a scalar or slot write that would store the float the
Python object already holds -- an exact float, the same bits -- skipped.
Python's value is the reference there, not the mirror: an int that equals
the float is still replaced by the float, as Python's own arithmetic does.
The kernel itself drops a pulse cannon's identical watcher line
(k0_identical_writes).
"""
import pytest

import App

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_register"),
    reason="native combat bindings not built")

from engine.appc import native_combat as nc  # noqa: E402
from engine.appc import passive_state  # noqa: E402
from tests.helpers.k0_fight import World, run_both  # noqa: E402

PHASER, PULSE, TRACTOR, TORPEDO = range(4)


@pytest.fixture(autouse=True)
def _switch():
    nc.reset()
    passive_state.reset()
    yield
    nc.reset()
    passive_state.reset()
    App.g_kModelPropertyManager.ClearLocalTemplates()


def _stats():
    return _h.combat_k0_apply_stats()


def _unpowered(w, ship="Galaxy"):
    """Galaxy's phasers on but receiving no power: a recharging bank adds
    exactly 0.0 (`want` = rate * 0.0 * condition * dt), so K0 logs a write
    of the value the bank already holds."""
    w.ships[ship].GetPhaserSystem()._power_factor = 0.0


def test_an_identical_float_write_is_not_stored(monkeypatch):
    with monkeypatch.context() as mp:
        w = World(mp, True, "k0_lean_same")
        try:
            _unpowered(w)
            bank = w.weapons("Galaxy", PHASER)[0]
            bank.SetChargeLevel(0.5)
            before = bank.__dict__["_charge_level"]
            _h.combat_k0_reset_counts()
            w.tick()
            after = bank.__dict__["_charge_level"]
            assert after == 0.5 and type(after) is float
            assert after is before          # the store was skipped
            s = _stats()
            assert s["identical"] >= 1, s
            nc.audit_mirror()
            assert nc.audit_failures() == []
        finally:
            w.close()


def test_an_int_equal_to_the_float_still_becomes_the_float(monkeypatch):
    """`_charge_level = 2` stores the int 2 (only SetChargeLevel coerces;
    `self._charge_level = self._max_charge` keeps a hardpoint's int too);
    Python's `+= 0.0` makes it the float 2.0, and so must K0's write-back,
    though the mirror already holds 2.0 (the differential compares the
    type too)."""

    def setup(w):
        _unpowered(w)
        for bank in w.weapons("Galaxy", PHASER):
            bank._charge_level = 2
            assert type(bank.__dict__["_charge_level"]) is int

    ref, nat, _counts = run_both(monkeypatch.context, lambda w, t: None, 3,
                                 setup=setup, passive=False)
    for bank in nat.weapons("Galaxy", PHASER):
        assert type(bank.__dict__["_charge_level"]) is float
        assert bank.__dict__["_charge_level"] == 2.0


def test_an_identical_wake_write_still_wakes_a_sleeping_weapon(monkeypatch):
    """`_charge_level` is a WakeField: every write, even of an equal value,
    wakes a sleeping owner (WakeField.__set__). The skipped store keeps the
    wake."""
    with monkeypatch.context() as mp:
        w = World(mp, True, "k0_lean_wake")
        try:
            _unpowered(w)
            bank = w.weapons("Galaxy", PHASER)[0]
            bank.SetChargeLevel(0.5)
            before = bank.__dict__["_charge_level"]
            bank.__dict__["_passive_asleep"] = True
            woken = []
            wake = passive_state.wake

            def spy(obj):
                woken.append(obj)
                wake(obj)
            mp.setattr(passive_state, "wake", spy)
            _h.combat_k0_reset_counts()
            w.tick()
            assert bank.__dict__["_charge_level"] is before
            assert woken.count(bank) == 1, woken
            assert not passive_state.is_asleep(bank)
            assert _stats()["identical"] >= 1
        finally:
            w.close()


def test_a_run_of_writes_to_one_weapon_stores_every_field(monkeypatch):
    """A pulse cannon cooling down and recharging writes its cooldown, its
    charge and its watcher's value in one run: one registry lookup for the
    run, every field stored (the differential checks each one's bits and
    type)."""

    def setup(w):
        w.ships["Vorcha"].GetPulseWeaponSystem().TurnOn()
        for cannon in w.weapons("Vorcha", PULSE):
            cannon.SetChargeLevel(cannon.GetMaxCharge() * 0.25)
            cannon._cooldown_remaining = 0.5
        if w.native:
            _h.combat_k0_reset_counts()

    _ref, nat, counts = run_both(monkeypatch.context, lambda w, t: None, 5,
                                 setup=setup, passive=False)
    s = _stats()
    cannons = len(nat.weapons("Vorcha", PULSE))
    assert cannons
    assert s["writes"] >= 3 * cannons * 5, s
    # One lookup per run of same-weapon writes, not per write.
    assert s["runs"] < s["writes"], s
    # Every logged write went through the lean apply (none general here).
    assert counts["k0_logged_writes"] == s["writes"], (counts, s)
    assert s["general"] == 0, s


def test_an_idle_cannons_watcher_line_is_not_logged(monkeypatch):
    """A full, idle pulse cannon: from its second tick on, the watcher line
    commits the value the watcher already holds -- the kernel drops it
    (k0_identical_writes), the watcher's float is untouched."""
    with monkeypatch.context() as mp:
        w = World(mp, True, "k0_lean_watch")
        try:
            w.ships["Vorcha"].GetPulseWeaponSystem().TurnOn()
            cannons = w.weapons("Vorcha", PULSE)
            for c in cannons:
                c.SetChargeLevel(c.GetMaxCharge())
            w.tick()
            values = [c.GetChargeWatcher().__dict__["_value"] for c in cannons]
            _h.combat_k0_reset_counts()
            w.tick()
            c = nc.counts()
            assert c["k0_identical_writes"] >= len(cannons), c
            for cannon, v in zip(cannons, values):
                assert cannon.GetChargeWatcher().__dict__["_value"] is v
            nc.audit_mirror()
            assert nc.audit_failures() == []
        finally:
            w.close()


def test_apply_stats_reset_with_the_counts(monkeypatch):
    with monkeypatch.context() as mp:
        w = World(mp, True, "k0_lean_reset")
        try:
            w.weapons("Galaxy", PHASER)[0].SetChargeLevel(0.0)
            w.tick()
            assert _stats()["writes"] > 0
            nc.reset()
            assert _stats() == {"writes": 0, "runs": 0, "identical": 0,
                                "general": 0}
        finally:
            w.close()
