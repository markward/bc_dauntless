"""K0 has no override guard (phase 6 A2; spec
docs/superpowers/specs/2026-11-05-phase6-engine-stages-native-design.md §3,
Part A: a stage never falls back to Python because an App method was
patched).

K0 steps every weapon from the mirror. A test, tool or mod that replaces
one of the charging walk's methods -- on the class, on an instance, on a
base reached through super(), FloatRangeWatcher._update, a weapon system's
IsOn, a ship's group getter, a magazine's GetAvailable -- is NOT called by
the native stage: the Python reference (DAUNTLESS_NATIVE_COMBAT=0) calls it,
K0 does not, and with a patch that only delegates the two arms still agree
bit for bit. A patch that changes what the method answers is simply not
seen by K0 (the native arm matches the unpatched native arm).

This file replaces test_native_k0_override_guard.py, whose tests asserted
the opposite (the guard's hand-backs, its class-verdict and object caches).
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
from engine.appc import weapon_subsystems as ws  # noqa: E402
from engine.appc.float_range_watcher import FloatRangeWatcher  # noqa: E402
from engine.appc.ships import ShipClass  # noqa: E402
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


def _swap_class(obj, cls):
    obj.__class__ = cls
    nc.reclassify(obj)          # the row's class flags (both arms)


# Each spy records (tick, label) into the arm's own log and delegates, so
# the two arms must still agree; only the call counts differ.
_LOG = []


def _spied(real):
    def f(self, *args):
        _LOG[-1].append(type(self).__name__)
        return real(self, *args)
    return f


class _SpyBank(ws.PhaserBank):
    UpdateCharge = _spied(ws.PhaserBank.UpdateCharge)


class _SpyShip(ShipClass):
    GetPhaserSystem = _spied(ShipClass.GetPhaserSystem)


class _SpyAmmo(ws.TorpedoAmmoType):
    GetAvailable = _spied(ws.TorpedoAmmoType.GetAvailable)


def _drain_banks(w):
    """Galaxy's first bank firing nearly dry: it depletes (its StopFiring)
    and then recharges (UpdateCharge, the system's IsOn)."""
    bank = w.weapons("Galaxy", PHASER)[0]
    bank._firing = True
    bank._beam_on_countdown = 0.0
    bank._charge_level = 0.01
    for b in w.weapons("Galaxy", PHASER)[1:]:
        b.SetChargeLevel(0.0)


def _reloading_tubes(w):
    for tube in w.weapons("Galaxy", TORPEDO):
        tube._reload_delay = 0.4
        tube.SetNumReady(0)


def _class_update_charge(w):
    _drain_banks(w)
    _swap_class(w.weapons("Galaxy", PHASER)[1], _SpyBank)


def _instance_update_charge(w):
    _drain_banks(w)
    bank = w.weapons("Galaxy", PHASER)[1]
    real = bank.UpdateCharge

    def patched(dt):
        _LOG[-1].append("instance")
        real(dt)
    bank.UpdateCharge = patched


def _stock_update_reload(w):
    _reloading_tubes(w)
    w.mp.setattr(ws.TorpedoTube, "UpdateReload",
                 _spied(ws.TorpedoTube.UpdateReload))


def _class_stop_firing(w):
    _drain_banks(w)
    w.mp.setattr(ws.PhaserBank, "StopFiring",
                 _spied(ws.PhaserBank.StopFiring))


def _class_broadcast_reload(w):
    _reloading_tubes(w)
    w.mp.setattr(ws.TorpedoTube, "_broadcast_reload",
                 _spied(ws.TorpedoTube._broadcast_reload))


def _instance_broadcast_reload(w):
    _reloading_tubes(w)
    tube = w.weapons("Galaxy", TORPEDO)[0]
    real = tube._broadcast_reload

    def patched():
        _LOG[-1].append("instance")
        real()
    tube._broadcast_reload = patched


def _watcher_update(w):
    w.ships["Vorcha"].GetPulseWeaponSystem().TurnOn()
    for cannon in w.weapons("Vorcha", PULSE):
        cannon.SetChargeLevel(0.0)
    real = FloatRangeWatcher._update

    def patched(self, value):
        if isinstance(self.__dict__.get("_owner"), ws.PulseWeapon):
            _LOG[-1].append("watcher")
        real(self, value)
    w.mp.setattr(FloatRangeWatcher, "_update", patched)


def _mixin_update_charge(w):
    w.ships["Vorcha"].GetPulseWeaponSystem().TurnOn()
    for cannon in w.weapons("Vorcha", PULSE):
        cannon.SetChargeLevel(0.0)
    w.mp.setattr(ws._EnergyWeaponFireMixin, "UpdateCharge",
                 _spied(ws._EnergyWeaponFireMixin.UpdateCharge))


def _system_instance_is_on(w):
    _drain_banks(w)
    system = w.ships["Galaxy"].GetPhaserSystem()
    real = system.IsOn

    def patched():
        _LOG[-1].append("IsOn")
        return real()
    system.IsOn = patched


def _ship_class_getter(w):
    _drain_banks(w)
    _swap_class(w.ships["Galaxy"], _SpyShip)


def _magazine_get_available(w):
    torps = w.ships["Vorcha"].GetTorpedoSystem()
    for tube in w.weapons("Vorcha", TORPEDO):
        tube._reload_delay = 0.4
        tube.SetNumReady(0)
    _swap_class(torps.GetCurrentAmmoType(), _SpyAmmo)


PATCHES = {
    "class_update_charge": _class_update_charge,
    "instance_update_charge": _instance_update_charge,
    "stock_update_reload": _stock_update_reload,
    "class_stop_firing": _class_stop_firing,
    "watcher_update": _watcher_update,
    "mixin_update_charge": _mixin_update_charge,
    "system_instance_is_on": _system_instance_is_on,
    "ship_class_getter": _ship_class_getter,
    "magazine_get_available": _magazine_get_available,
}

# Half K0's: Python's ReloadTorpedo calls `_broadcast_reload` (which, inside
# the effect scope, queues TORPEDO_RELOAD), and the queue's delivery calls
# it again to post the event (effect_queue.py). K0 stands in for the first
# call -- not honoured -- while the delivery, the same in both arms, still
# calls the patch.
DELIVERED = {
    "class_broadcast_reload": _class_broadcast_reload,
    "instance_broadcast_reload": _instance_broadcast_reload,
}


def _run(monkeypatch, patch_setup):
    calls = {}

    def setup(w):
        _LOG.append([])
        calls[w.native] = _LOG[-1]
        patch_setup(w)

    try:
        _ref, _nat, counts = run_both(monkeypatch.context,
                                      lambda w, t: None, 60, setup=setup,
                                      passive=False)
    finally:
        _LOG.clear()
    assert calls[False], "the Python reference never called the patch"
    assert counts["k0_python_reasons"]["override"] == 0, counts
    assert not any(counts["k0_python_reasons"].values()), counts
    assert counts["k0_steps"] > 0, counts
    return calls


@pytest.mark.parametrize("patch", sorted(PATCHES))
def test_a_patched_k0_method_is_not_honoured(monkeypatch, patch):
    """The Python reference calls the patch; K0 never does (no override
    hand-back); a delegating patch leaves both arms bit-identical."""
    calls = _run(monkeypatch, PATCHES[patch])
    assert calls[True] == [], calls[True][:5]


@pytest.mark.parametrize("patch", sorted(DELIVERED))
def test_a_patched_reload_broadcast_is_called_at_delivery(monkeypatch,
                                                         patch):
    calls = _run(monkeypatch, DELIVERED[patch])
    assert calls[True] and 2 * len(calls[True]) == len(calls[False]), calls


class _AlwaysOnPhasers(ws.PhaserSystem):
    def IsOn(self):
        return 1


def _native_log(mp_factory, setup, script, ticks):
    with mp_factory() as mp:
        w = World(mp, True, "k0_patched")
        try:
            setup(w)
            for t in range(ticks):
                w.tick(before=lambda w, t=t: script(w, t))
            nc.audit_mirror()
            assert nc.audit_failures() == []
            banks = {w.label(b) for b in w.weapons("Galaxy", PHASER)}
            return w.log, nc.counts(), banks
        finally:
            w.close()


def test_a_patch_that_changes_an_answer_is_not_seen(monkeypatch):
    """A phaser SYSTEM class whose IsOn always answers 1, the system turned
    off: Python recharges the banks (it obeys the patch); K0 reads the
    mirror's `_is_on` and does not -- the native run equals the unpatched
    native run, tick for tick."""

    def script(w, t):
        if t == 0:
            w.ships["Galaxy"].GetPhaserSystem().TurnOff()
            for bank in w.weapons("Galaxy", PHASER):
                bank.SetChargeLevel(0.0)

    def patched(w):
        _swap_class(w.ships["Galaxy"].GetPhaserSystem(), _AlwaysOnPhasers)

    plain, _c, _b = _native_log(monkeypatch.context, lambda w: None, script,
                                30)
    nc.reset()
    with_patch, counts, banks = _native_log(monkeypatch.context, patched,
                                            script, 30)
    assert with_patch == plain
    assert counts["k0_python_reasons"]["override"] == 0, counts
    # The banks stayed empty natively (the system is off in the mirror).
    rows = [row for row in with_patch[-1] if row[0] in banks]
    assert rows and all(row[1] == ("float", (0.0).hex()) for row in rows)
