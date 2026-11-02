"""The K0 override guard (native weapon state, Task 5; spec
docs/superpowers/specs/2026-11-02-native-weapon-state-design.md §4.3,
docs/reference/engine/native-combat/weapon-state-map.md §7(a) A6).

K0 computes, from the mirror, what the charging walk's Python methods would
do. A test, tool or mod that replaces one must still be obeyed:

  - on the CLASS: a class whose MRO resolves any of A6's methods (plus the
    walk's own GetNumWeapons / GetWeapon / the ship's group getters) to
    anything but the stock class of its role had when the engine defined it
    -> a weapon class: that weapon runs in Python; a weapon system or ship
    class: the whole ship runs in Python. Rechecked at every session, so a
    patch made between ticks is seen at the next one;
  - on the INSTANCE: an instance attribute shadowing one of the cheap
    subset tests, tools and SWIG patch (native_combat._K0_*_PATCHES: a
    weapon's UpdateCharge / UpdateReload / ReloadTorpedo -> that weapon; a
    system's IsOn / GetNormalPowerPercentage / GetPowerLevel or a ship's
    group getters -> the whole ship).
A torpedo tube's reload gate reads its siblings' GetNumReady and the
magazine's GetAvailable, so one overridden tube or magazine hands every tube
of that system back.
"""
import pathlib
import re

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
from engine.appc.ships import ShipClass  # noqa: E402
from tests.helpers.k0_fight import groups, run_both  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
WSM = ROOT / "docs" / "reference" / "engine" / "native-combat" \
    / "weapon-state-map.md"
PHASER, PULSE, TRACTOR, TORPEDO = range(4)


@pytest.fixture(autouse=True)
def _switch():
    nc.reset()
    passive_state.reset()
    yield
    nc.reset()
    passive_state.reset()
    App.g_kModelPropertyManager.ClearLocalTemplates()


def _override(counts):
    return counts["k0_python_reasons"]["override"]


def _swap_class(obj, cls):
    obj.__class__ = cls
    nc.reclassify(obj)          # the row's class flags (both arms)


class _CountingBank(ws.PhaserBank):
    calls = []

    def UpdateCharge(self, dt):
        _CountingBank.calls.append(self.GetName())
        ws.PhaserBank.UpdateCharge(self, dt)


def _drain_and_recharge(w, t):
    g, v = w.ships["Galaxy"], w.ships["Vorcha"]
    if t == 0:
        g.GetPhaserSystem().StartFiring(v)
    elif t == 100:
        g.GetPhaserSystem().StopFiring()


def test_class_override_of_update_charge_runs_python(monkeypatch):
    """A bank whose CLASS overrides UpdateCharge: that bank runs in Python
    (reason override), the override called exactly as often as without K0;
    the ship's other weapons stay native."""
    calls = {}

    def setup(w):
        _CountingBank.calls = []
        _swap_class(w.weapons("Galaxy", PHASER)[0], _CountingBank)

    def script(w, t):
        _drain_and_recharge(w, t)
        calls[w.native] = list(_CountingBank.calls)

    _ref, _nat, counts = run_both(monkeypatch.context, script, 160,
                                  setup=setup, passive=False)
    assert calls[False] and calls[True] == calls[False]
    assert _override(counts) == 160, counts
    assert counts["k0_steps"] > 0, counts


def test_instance_attribute_update_charge_runs_python(monkeypatch):
    """`bank.UpdateCharge = ...` on one instance: that bank runs in Python
    and the patch is called, ON == OFF."""
    calls = {}

    def setup(w):
        bank = w.weapons("Galaxy", PHASER)[1]
        log = calls[w.native] = []
        real = bank.UpdateCharge

        def patched(dt):
            log.append(w.n)
            real(dt)
        bank.UpdateCharge = patched

    _ref, _nat, counts = run_both(monkeypatch.context, _drain_and_recharge,
                                  160, setup=setup, passive=False)
    assert calls[False] and calls[True] == calls[False]
    assert _override(counts) == 160, counts


def test_stock_class_patch_between_ticks_is_seen(monkeypatch):
    """A patch on the stock TorpedoTube.UpdateReload made between ticks is
    seen from the next session on: every tube runs in Python and the patch
    is called, ON == OFF."""
    calls = {}

    def script(w, t):
        if t == 0:
            for tube in w.weapons("Galaxy", TORPEDO):
                tube._reload_delay = 0.4
            w.ships["Galaxy"].GetTorpedoSystem().StartFiring(
                w.ships["Vorcha"])
        if t == 20:
            log = calls[w.native] = []
            real = ws.TorpedoTube.UpdateReload

            def patched(self, dt=0.0):
                log.append((w.n, self.GetName()))
                real(self, dt)
            # The arm's own monkeypatch: undone when the arm ends.
            w.mp.setattr(ws.TorpedoTube, "UpdateReload", patched)

    _ref, _nat, counts = run_both(monkeypatch.context, script, 60,
                                  passive=False)
    assert calls[False] and calls[True] == calls[False]
    assert _override(counts) > 0, counts


def test_class_patched_stop_firing_is_called_by_deplete_stop(monkeypatch):
    """A class patch of PhaserBank.StopFiring is NOT a reason to hand the
    ship back: K0's DEPLETE_STOP record calls `bank.StopFiring()` in
    Python, so the patch is called -- on the same tick, for the same bank,
    as without K0 -- while the walk stays native (no override)."""
    calls = {}

    def setup(w):
        bank = w.weapons("Galaxy", PHASER)[0]
        bank._firing = True
        bank._beam_on_countdown = 0.0
        bank._charge_level = 0.01
        log = calls[w.native] = []
        real = ws.PhaserBank.StopFiring

        def patched(self):
            log.append((w.n, self.GetName()))
            real(self)
        w.mp.setattr(ws.PhaserBank, "StopFiring", patched)

    _ref, _nat, counts = run_both(monkeypatch.context, lambda w, t: None, 6,
                                  setup=setup, passive=False)
    assert calls[False] and calls[True] == calls[False], calls
    assert counts["k0_records"]["DEPLETE_STOP"] == 1, counts
    assert _override(counts) == 0, counts


def test_class_patched_broadcast_reload_is_called_by_reloaded(monkeypatch):
    """Likewise TorpedoTube._broadcast_reload: K0's RELOADED record calls it
    in Python, so a class patch is called exactly as without K0 and the
    tubes stay native."""
    calls = {}

    def setup(w):
        for tube in w.weapons("Galaxy", TORPEDO):
            tube._reload_delay = 0.4
            tube.SetNumReady(0)
        log = calls[w.native] = []
        real = ws.TorpedoTube._broadcast_reload

        def patched(self):
            log.append((w.n, self.GetName()))
            real(self)
        w.mp.setattr(ws.TorpedoTube, "_broadcast_reload", patched)

    _ref, _nat, counts = run_both(monkeypatch.context, lambda w, t: None, 60,
                                  setup=setup, passive=False)
    assert calls[False] and calls[True] == calls[False], calls
    assert counts["k0_records"]["RELOADED"] == len(calls[True]), counts
    assert _override(counts) == 0, counts


class _AlwaysOnPhasers(ws.PhaserSystem):
    def IsOn(self):
        return 1


def test_system_class_override_hands_the_ship_back(monkeypatch):
    """A phaser SYSTEM class overriding IsOn (read by its banks' recharge):
    the whole ship runs in Python, the patched IsOn obeyed (the banks
    recharge while the system is off)."""

    def setup(w):
        _swap_class(w.ships["Galaxy"].GetPhaserSystem(), _AlwaysOnPhasers)

    def script(w, t):
        if t == 0:
            w.ships["Galaxy"].GetPhaserSystem().TurnOff()
            for bank in w.weapons("Galaxy", PHASER):
                bank.SetChargeLevel(0.0)

    ref, _nat, counts = run_both(monkeypatch.context, script, 30, setup=setup)
    assert _override(counts) == 30, counts      # one whole-ship hand-back
    bank = ref.weapons("Galaxy", PHASER)[0]
    assert bank.GetChargeLevel() > 0.0


def test_system_instance_patch_hands_the_ship_back(monkeypatch):
    """`system.IsOn = lambda: True` (as several tests do): the ship runs in
    Python and the patch is obeyed."""

    def setup(w):
        w.ships["Galaxy"].GetPhaserSystem().IsOn = lambda: True

    def script(w, t):
        if t == 0:
            w.ships["Galaxy"].GetPhaserSystem().TurnOff()
            for bank in w.weapons("Galaxy", PHASER):
                bank.SetChargeLevel(0.0)

    ref, _nat, counts = run_both(monkeypatch.context, script, 30, setup=setup)
    assert _override(counts) == 30, counts
    assert ref.weapons("Galaxy", PHASER)[0].GetChargeLevel() > 0.0


class _NoPhasersShip(ShipClass):
    def GetPhaserSystem(self):
        return None


def test_ship_class_group_getter_override_hands_the_ship_back(monkeypatch):
    """A ship class whose GetPhaserSystem answers None: the passive walk
    never steps its phasers; K0 hands the ship back and so does not
    either."""

    def setup(w):
        w.ships["Galaxy"].GetPhaserSystem().TurnOn()
        _swap_class(w.ships["Galaxy"], _NoPhasersShip)
        for bank in w.weapons("Galaxy", PHASER):
            bank.SetChargeLevel(0.0)

    ref, nat, counts = run_both(monkeypatch.context, lambda w, t: None, 10,
                                setup=setup)
    assert _override(counts) == 10, counts
    for world in (ref, nat):
        assert world.weapons("Galaxy", PHASER)[0].GetChargeLevel() == 0.0


class _CountingTube(ws.TorpedoTube):
    def GetNumReady(self):
        return ws.TorpedoTube.GetNumReady(self)


def test_one_overridden_tube_hands_back_its_siblings(monkeypatch):
    """One tube class overriding GetNumReady (which every sibling's reload
    gate sums): every tube of that system runs in Python."""

    def setup(w):
        _swap_class(w.weapons("Galaxy", TORPEDO)[0], _CountingTube)

    _ref, _nat, counts = run_both(monkeypatch.context, lambda w, t: None, 5,
                                  setup=setup)
    tubes = len(groups(_nat.ships["Galaxy"])[-1]._children)
    assert _override(counts) == 5 * tubes, counts


class _CountedAmmo(ws.TorpedoAmmoType):
    def GetAvailable(self):
        return ws.TorpedoAmmoType.GetAvailable(self)


def test_magazine_class_override_hands_back_its_tubes(monkeypatch):
    def setup(w):
        torps = w.ships["Vorcha"].GetTorpedoSystem()
        _swap_class(torps.GetCurrentAmmoType(), _CountedAmmo)

    _ref, nat, counts = run_both(monkeypatch.context, lambda w, t: None, 5,
                                 setup=setup)
    tubes = len(nat.weapons("Vorcha", TORPEDO))
    assert _override(counts) == 5 * tubes, counts


def test_stock_classes_are_not_flagged():
    nc.configure({"DAUNTLESS_NATIVE_COMBAT": "1"})
    assert nc.enabled()
    for cls in (ws.PhaserSystem, ws.PulseWeaponSystem, ws.TractorBeamSystem,
                ws.TorpedoSystem, ws.PhaserBank, ws.PulseWeapon,
                ws.TractorBeam, ws.TorpedoTube, ws.TorpedoAmmoType,
                ShipClass):
        assert nc._k0_flag(cls) == 0, cls
    for cls in (_CountingBank, _AlwaysOnPhasers, _NoPhasersShip,
                _CountingTube, _CountedAmmo):
        assert nc._k0_flag(cls) == 1, cls


def test_method_list_covers_wsm_a6():
    """Every method WSM §7(a) A6 lists is in the guard's class list, but
    the ones K0's records call in Python (_K0_CALLED_IN_PYTHON), which are
    not in it."""
    text = WSM.read_text()
    row = next(line for line in text.splitlines() if line.startswith("| A6 "))
    cell = row.split("|")[2]
    cell = cell.split("Tests class-patch")[0]
    names = set()
    for tok in re.findall(r"`([^`]+)`", cell):
        if tok.startswith("GetCurrentAmmoType/"):
            names.update(("GetCurrentAmmoType", "GetCurrentAmmoSlot"))
        else:
            names.add(tok)
    assert names, row
    exempt = set(nc._K0_CALLED_IN_PYTHON)
    assert exempt == {"StopFiring", "_broadcast_reload"} and exempt <= names
    assert not exempt & set(nc._K0_METHODS)
    assert names - exempt <= set(nc._K0_METHODS), \
        names - exempt - set(nc._K0_METHODS)


# ── Between two sessions (ruling W6: the binding caches the verdicts) ────────

def _phaser_banks(w):
    return [b for name in w.ships for b in w.weapons(name, PHASER)]


def test_class_patch_between_two_sessions_is_seen(monkeypatch):
    """The class verdicts are cached in the binding by CPython's type version
    tag: a patch on the stock PhaserBank made between two sessions flips
    every bank to Python at the next session, and undoing it flips them
    back."""
    from tests.helpers.k0_fight import World
    calls = []
    with monkeypatch.context() as mp:
        w = World(mp, True, "k0_between")
        try:
            w.tick()
            w.tick()                            # verdicts cached
            assert _override(nc.counts()) == 0
            assert _h.combat_k0_cache_sizes()[0] > 0
            banks = len(_phaser_banks(w))
            real = ws.PhaserBank.UpdateCharge
            with monkeypatch.context() as patch:
                def spy(self, dt):
                    calls.append(self.GetName())
                    real(self, dt)
                patch.setattr(ws.PhaserBank, "UpdateCharge", spy)
                w.tick()
                assert _override(nc.counts()) == banks
                assert len(calls) == banks
            w.tick()                            # the patch is gone again
            assert _override(nc.counts()) == banks
            assert len(calls) == banks
        finally:
            w.close()


def test_instance_attribute_between_two_sessions_is_seen(monkeypatch):
    """An instance attribute added between two sessions (a weapon's, then a
    weapon system's) is seen at the next one, and its removal too."""
    from tests.helpers.k0_fight import World
    with monkeypatch.context() as mp:
        w = World(mp, True, "k0_between_inst")
        try:
            w.tick()
            w.tick()
            bank = w.weapons("Galaxy", PHASER)[2]
            calls = []
            real = bank.UpdateCharge

            def patched(dt):
                calls.append(dt)
                real(dt)
            bank.UpdateCharge = patched
            w.tick()
            assert (_override(nc.counts()), len(calls)) == (1, 1)
            del bank.UpdateCharge
            w.tick()
            assert (_override(nc.counts()), len(calls)) == (1, 1)
            phasers = w.ships["Galaxy"].GetPhaserSystem()
            phasers.IsOn = lambda: True
            w.tick()                            # the whole ship
            assert _override(nc.counts()) == 2
            del phasers.IsOn
            w.tick()
            assert _override(nc.counts()) == 2
        finally:
            w.close()


def test_class_swap_between_two_sessions_is_seen(monkeypatch):
    """`weapon.__class__ = Sub` changes the type, not the dict: the cached
    answer is keyed on the type too."""
    from tests.helpers.k0_fight import World
    with monkeypatch.context() as mp:
        w = World(mp, True, "k0_between_swap")
        try:
            w.tick()
            w.tick()
            bank = w.weapons("Galaxy", PHASER)[3]
            _CountingBank.calls = []
            _swap_class(bank, _CountingBank)
            w.tick()
            assert _override(nc.counts()) == 1
            assert _CountingBank.calls == [bank.GetName()]
            _swap_class(bank, ws.PhaserBank)
            w.tick()
            assert _override(nc.counts()) == 1
        finally:
            w.close()


# ── Review fix round 2 ───────────────────────────────────────────────────────

def test_mixin_patch_reached_through_super_runs_python(monkeypatch):
    """A patch of `_EnergyWeaponFireMixin.UpdateCharge` is reached by
    PulseWeapon.UpdateCharge and an idle TractorBeam.UpdateCharge through
    `super()`, though neither's MRO-first UpdateCharge changed: every pulse
    cannon and idle tractor (and every phaser bank) runs in Python (reason
    override), the patch called exactly as often as without K0."""
    calls = {}

    def setup(w):
        w.ships["Galaxy"].GetTractorBeamSystem().TurnOn()
        for beam in w.weapons("Galaxy", TRACTOR):
            beam.SetChargeLevel(0.0)            # idle, recharging
        for cannon in w.weapons("Vorcha", PULSE):
            cannon.SetChargeLevel(0.0)

    def script(w, t):
        if t != 2:
            return
        log = calls[w.native] = []
        real = ws._EnergyWeaponFireMixin.UpdateCharge

        def patched(self, dt):
            log.append((w.n, w.label(self)))
            real(self, dt)
        # The arm's own monkeypatch: undone when the arm ends.
        w.mp.setattr(ws._EnergyWeaponFireMixin, "UpdateCharge", patched)

    ticks = 8
    _ref, nat, counts = run_both(monkeypatch.context, script, ticks,
                                 setup=setup, passive=False)
    pulses = len(nat.weapons("Vorcha", PULSE))
    tractors = sum(len(nat.weapons(s, TRACTOR)) for s in nat.ships)
    banks = sum(len(nat.weapons(s, PHASER)) for s in nat.ships)
    assert pulses and tractors and banks
    # The patch is reached by the pulse cannons and the idle tractors.
    labels = {lbl for _n, lbl in calls[False]}
    for x in nat.weapons("Vorcha", PULSE) + nat.weapons("Galaxy", TRACTOR):
        assert nat.label(x) in labels, nat.label(x)
    assert calls[True] == calls[False]
    # From the patch on (the session of tick 3): every energy weapon.
    assert _override(counts) == (ticks - 2) * (pulses + tractors + banks), \
        counts


def test_mixin_patch_flags_the_pulse_and_tractor_classes(monkeypatch):
    """_k0_flag compares every MRO class's own entries, not only the first
    one each name resolves to."""
    nc.configure({"DAUNTLESS_NATIVE_COMBAT": "1"})
    for cls in (ws.PulseWeapon, ws.TractorBeam, ws.PhaserBank):
        assert nc._k0_flag(cls) == 0, cls
    real = ws._EnergyWeaponFireMixin.UpdateCharge
    monkeypatch.setattr(ws._EnergyWeaponFireMixin, "UpdateCharge",
                        lambda self, dt: real(self, dt))
    for cls in (ws.PulseWeapon, ws.TractorBeam, ws.PhaserBank):
        assert nc._k0_flag(cls) == 1, cls


def test_verdict_cache_owns_its_types(monkeypatch):
    """The binding's class verdict cache re-validates every type it keeps
    by reading the type, every scan: it must hold a REFERENCE to each, so a
    test-local subclass it has seen cannot be freed under it (other engine
    caches keyed by class hold it too, so "freed" cannot be staged here;
    the reference count is what pins it). Released by
    combat_k0_clear_caches (reset); sessions after it run correctly."""
    import sys
    from tests.helpers.k0_fight import World

    class _Local(ws.PhaserBank):
        pass

    with monkeypatch.context() as mp:
        w = World(mp, True, "k0_typeref")
        try:
            bank = w.weapons("Galaxy", PHASER)[0]
            _swap_class(bank, _Local)
            w.tick()
            w.tick()
            _swap_class(bank, ws.PhaserBank)
            w.tick()
            held = sys.getrefcount(_Local)
            _h.combat_k0_clear_caches()
            assert sys.getrefcount(_Local) == held - 1
            w.tick()                    # the cache refills without _Local
            assert sys.getrefcount(_Local) == held - 1
            for _ in range(3):
                w.tick()
            assert _override(nc.counts()) == 0
            nc.audit_mirror()
            assert nc.audit_failures() == []
        finally:
            w.close()


def test_object_cache_is_gated_to_verified_pythons(monkeypatch):
    """The per-object answer cache keys on the dict's PEP 509
    ma_version_tag, verified on CPython 3.11 only: other versions take the
    uncached path. On the running version, an instance attribute set on a
    weapon whose dict is materialized -- by setattr, and by a direct
    __dict__ store -- drops the cached answer at the next session."""
    import sys
    from tests.helpers.k0_fight import World
    enabled = _h.combat_k0_object_cache()
    assert enabled == (sys.version_info[:2] == (3, 11))
    with monkeypatch.context() as mp:
        w = World(mp, True, "k0_objcache")
        try:
            w.tick()
            w.tick()
            if enabled:
                assert _h.combat_k0_cache_sizes()[3] > 0
            bank = w.weapons("Galaxy", PHASER)[1]
            d = bank.__dict__                   # materialized
            calls = []
            real = bank.UpdateCharge

            def patched(dt):
                calls.append(dt)
                real(dt)
            bank.UpdateCharge = patched
            w.tick()
            assert (_override(nc.counts()), len(calls)) == (1, 1)
            del d["UpdateCharge"]
            w.tick()
            assert (_override(nc.counts()), len(calls)) == (1, 1)
            d["UpdateCharge"] = patched
            w.tick()
            assert (_override(nc.counts()), len(calls)) == (2, 2)
        finally:
            w.close()
