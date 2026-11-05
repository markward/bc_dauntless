"""K0 dispatch: charging and reloading run through the native charging kernel
when native combat is on (native weapon state, Task 5; spec
docs/superpowers/specs/2026-11-02-native-weapon-state-design.md §4.3, plan
docs/superpowers/plans/2026-11-02-native-weapon-state.md Review Focus 2-3).

`host_loop._advance_weapons` asks `native_combat.k0_weapons(ships, dt)`; K0
steps every weapon from the mirror (the per-tick model) and stops only at a
hand-back (RUN_PYTHON), with the writes before it already applied. A
depleted bank's stop, a reload and a pulse watcher's line are logged writes
plus combat effect queue entries -- LOOP_STOP, TORPEDO_RELOAD, WATCH --
delivered at the scope's end (combat fire events Task 4, spec
2026-11-02-combat-fire-events §4.3). Every scenario is run with native off
and on and compared tick by tick by float.hex() (tests/helpers/k0_fight.py,
which opens the effect scope in both arms).
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

from engine import host_loop  # noqa: E402
from engine.appc import native_combat as nc  # noqa: E402
from engine.appc import passive_state  # noqa: E402
from engine.appc import weapon_subsystems as ws  # noqa: E402
from engine.appc.float_range_watcher import FloatRangeWatcher  # noqa: E402
from tests.helpers.k0_fight import (  # noqa: E402
    DT, GALAXY_VORCHA, ON, World, charge_toggle_type, run_both,
)

PHASER, PULSE, TRACTOR, TORPEDO = range(4)
RELOAD_DELAY_S = 0.5


@pytest.fixture(autouse=True)
def _switch():
    nc.reset()
    passive_state.reset()
    yield
    nc.reset()
    passive_state.reset()
    App.g_kModelPropertyManager.ClearLocalTemplates()


def _records(counts):
    return counts["k0_records"]


def _logged(counts):
    """The records K0 no longer returns, logged with their entries."""
    return counts["k0_logged"]


def _entries(counts):
    return counts["k0_entries"]


def _no_converted_records(counts):
    rec = _records(counts)
    assert rec["DEPLETE_STOP"] == rec["RELOADED"] == rec["WATCH"] == 0, rec


def _reasons(counts):
    return {k: v for k, v in counts["k0_python_reasons"].items() if v}


def _fast_tubes(w):
    for ship in w.order:
        torps = ship.GetTorpedoSystem()
        for i in range(torps.GetNumWeapons()):
            torps.GetWeapon(i)._reload_delay = RELOAD_DELAY_S


def _watch(w, cannon, fraction=0.6):
    evt = App.TGEvent_Create()
    evt.SetEventType(charge_toggle_type())
    evt.SetDestination(cannon)
    cannon.GetChargeWatcher().AddRangeCheck(
        fraction, App.FloatRangeWatcher.FRW_BOTH, evt)


# ── The per-tick differential ────────────────────────────────────────────────

@pytest.mark.parametrize("passive", [True, False],
                         ids=["passive_walk", "per_tick_walk"])
def test_k0_matches_python_per_tick(monkeypatch, passive):
    """A Galaxy and a Vor'cha trade fire: phaser banks drain, deplete and
    recharge (power level 0 discharge, a TurnOff, damage), one pulse cannon
    with watcher checks and one without, tubes reloading with a finite
    magazine that runs out. K0 must equal the Python walk every tick -- the
    passive walk (today's default) and the per-tick one -- events included,
    and must have run each native path."""

    def setup(w):
        _fast_tubes(w)
        cannons = w.weapons("Vorcha", PULSE)
        _watch(w, cannons[0])                       # cannons[1]: no checks
        ammo = w.ships["Vorcha"].GetTorpedoSystem().GetCurrentAmmoType()
        ammo._unlimited = False
        ammo._available = 3                         # runs out mid-fight

    def script(w, t):
        g, v = w.ships["Galaxy"], w.ships["Vorcha"]
        if t == 0:
            g.GetPhaserSystem().StartFiring(v)
            g.GetTorpedoSystem().StartFiring(v)
            v.GetPhaserSystem().StartFiring(g)
            v.GetPulseWeaponSystem().StartFiring(g)
            v.GetTorpedoSystem().StartFiring(g)
        elif t in (60, 380):
            # The lit banks run dry (and latch depleted) mid-burst.
            for bank in w.weapons("Galaxy", PHASER) + w.weapons("Vorcha",
                                                                PHASER):
                if bank.IsFiring():
                    bank.SetChargeLevel(0.2)
        elif t == 150:
            g.GetPhaserSystem().SetPowerLevel(0)
        elif t == 200:
            g.GetPhaserSystem().TurnOff()
        elif t == 230:
            g.GetPhaserSystem().TurnOn()
        elif t == 260:
            for bank in w.weapons("Galaxy", PHASER)[::2]:
                bank.SetCondition(bank.GetMaxCondition() * 0.5)
        elif t == 300:
            g.GetPhaserSystem().StopFiring()
            v.GetPulseWeaponSystem().StopFiring()
        elif t == 320:
            for cannon in w.weapons("Vorcha", PULSE):
                cannon.SetChargeLevel(0.0)

    ref, nat, counts = run_both(monkeypatch.context, script, 420, setup=setup,
                                passive=passive)
    kinds = {e[0] for e in ref.events}
    assert {"reload", "charge_toggle", "fired", "torpedo_fired"} <= kinds, kinds
    assert counts["k0_steps"] > 0, counts
    logged = _logged(counts)
    assert logged["deplete_stop"] > 0 and logged["reload"] > 0 \
        and logged["watch"] > 0, counts
    entries = _entries(counts)
    assert entries["LOOP_STOP"] > 0 and entries["WATCH"] > 0, entries
    assert entries["TORPEDO_RELOAD"] == logged["reload"], counts
    _no_converted_records(counts)
    assert counts["k0_logged_writes"] > 0, counts
    # The magazine ran dry with a slot due: the reload gate denied it.
    vorcha_tubes = nat.weapons("Vorcha", TORPEDO)
    ammo = nat.ships["Vorcha"].GetTorpedoSystem().GetCurrentAmmoType()
    assert ammo.GetAvailable() <= sum(t.GetNumReady() for t in vorcha_tubes)
    assert any(t.GetNumReady() < t.GetMaxReady()
               and max(t._reload_timers) >= t._reload_delay
               for t in vorcha_tubes)


def test_deplete_stop_plays_loop_stop(monkeypatch):
    """A firing bank drained to 0 by K0: its StopFiring is logged writes
    plus a LOOP_STOP entry, so the looped fire sound is stopped (and
    dropped) exactly once, at the scope's end, in both arms, with
    `_depleted` latched before it and no record returned."""
    stops = {}

    class Handle:
        def __init__(self, w, bank, log):
            self.w, self.bank, self.log = w, bank, log

        def Stop(self):
            # StopFiring reads the latch the kernel logged before the record.
            self.log.append((self.w.n, self.bank.__dict__["_depleted"]))

    def setup(w):
        bank = w.weapons("Galaxy", PHASER)[0]
        log = stops[w.native] = []
        bank._firing = True
        bank._beam_on_countdown = 0.0
        bank._charge_level = 0.01
        bank._loop_handle = Handle(w, bank, log)

    ref, nat, counts = run_both(monkeypatch.context, lambda w, t: None, 6,
                                setup=setup)
    assert stops[False] == stops[True] == [(1, True)], stops
    assert nat.weapons("Galaxy", PHASER)[0]._loop_handle is None
    assert _logged(counts)["deplete_stop"] == 1, counts
    assert _entries(counts)["LOOP_STOP"] == 1, counts
    _no_converted_records(counts)


def _galaxy_tubes_reload_together(w):
    _fast_tubes(w)
    for tube in w.weapons("Galaxy", TORPEDO):
        tube.SetNumReady(0)         # every slot cooling from the same clock


def test_reloaded_handler_starts_firing_same_ship(monkeypatch):
    """Review Focus 2, re-aimed (ruling F4: the reload is a queued
    TORPEDO_RELOAD since combat fire events Task 4, so its handler runs at
    the scope's end, not mid-walk, in both arms). Each ET_TORPEDO_RELOAD of
    a Galaxy tube runs a handler that StartFirings the same ship's
    torpedoes and phasers (K1 system sessions inside the delivery, each
    delivering its own entries at its end). The tubes reloading on the same
    tick fire one by one, between the reloads, exactly as the Python
    reference with the same scope."""
    seen = {}

    def setup(w):
        _galaxy_tubes_reload_together(w)
        log = seen[w.native] = []
        galaxy, vorcha = w.ships["Galaxy"], w.ships["Vorcha"]
        tubes = set(map(id, w.weapons("Galaxy", TORPEDO)))

        def hook(evt):
            if evt.GetEventType() != App.ET_TORPEDO_RELOAD \
                    or id(evt.GetDestination()) not in tubes:
                return
            log.append([w.state(x) for x in w.leaves])
            galaxy.GetTorpedoSystem().StartFiring(vorcha)
            galaxy.GetPhaserSystem().StartFiring(vorcha)
            log.append([w.state(x) for x in w.leaves])
        w.hooks.append(hook)

    ref, nat, counts = run_both(monkeypatch.context, lambda w, t: None, 90,
                                setup=setup)
    assert seen[False] and seen[True] == seen[False]
    # A torpedo launched between two reloads of the same tick.
    ev = [(e[0], e[3]) for e in ref.events
          if e[0] in ("reload", "torpedo_fired")]
    assert any(a == ("reload", n) and b[0] == "torpedo_fired" and b[1] == n
               and c == ("reload", n)
               for (a, b, c), n in ((ev[i:i + 3], ev[i][1])
                                    for i in range(len(ev) - 2))), ev
    assert _logged(counts)["reload"] >= 2, counts
    _no_converted_records(counts)
    assert counts["k1_records"] > 0, counts


def test_handler_sets_later_weapon_charge(monkeypatch):
    """Review Focus 3, re-aimed (ruling F4). A Galaxy reload's handler,
    delivered at the scope's end, sets a Vor'cha phaser bank to a quarter
    charge with the SDK's SetChargeLevel. That bank must be stepped NEXT
    tick from the new value (the wake and the mirror push), as the Python
    reference with the same scope does."""
    set_at = {}

    def setup(w):
        _galaxy_tubes_reload_together(w)
        w.ships["Vorcha"].GetPhaserSystem().TurnOn()
        bank = w.weapons("Vorcha", PHASER)[0]
        ticks = set_at[w.native] = []

        def hook(evt):
            if evt.GetEventType() != App.ET_TORPEDO_RELOAD:
                return
            if evt.GetDestination().GetParentShip() is not w.ships["Galaxy"]:
                return
            bank.SetChargeLevel(bank.GetMaxCharge() * 0.25)
            ticks.append(w.n)
        w.hooks.append(hook)

    ref, nat, counts = run_both(monkeypatch.context, lambda w, t: None, 60,
                                setup=setup)
    assert set_at[False] and set_at[True] == set_at[False]
    bank = nat.weapons("Vorcha", PHASER)[0]
    i = nat.leaves.index(bank)
    quarter = ("float", (bank.GetMaxCharge() * 0.25).hex())
    for n in set_at[True]:
        # Set after this tick's step (the tick ends with it), stepped from
        # it the next.
        assert nat.log[n - 1][i][1] == quarter, (n, nat.log[n - 1][i])
        if n < len(nat.log):
            assert nat.log[n][i][1] != quarter, (n, nat.log[n][i])
    assert _logged(counts)["reload"] > 0, counts


def _hold(w, ship_name):
    """Every tractor of the ship holding (its `_firing`, written as the
    beam's engage writes it: the K0 kernel reads the pushed value). A real
    engage needs a target within 120 GU with its shields down."""
    for beam in w.weapons(ship_name, TRACTOR):
        beam._firing = True


def test_k0_holding_tractor_power_loss_stops(monkeypatch):
    """A HOLDING tractor beam is K0's (fire control native only, M4; no
    hand-back): it holds with its charge untouched, and stops when its
    parent is turned off and again when the parent is starved
    (GetPowerPercentage() 0 while it wants power) -- each stop's `_firing`
    through the beam's thaw setter, then its LOOP_STOP -- exactly as
    TractorBeam.UpdateCharge's Python, every tick."""

    def script(w, t):
        tractors = w.ships["Galaxy"].GetTractorBeamSystem()
        if t == 0:
            tractors.TurnOn()
            _hold(w, "Galaxy")
        elif t == 40:
            tractors.TurnOff()
        elif t == 60:
            tractors.TurnOn()
            _hold(w, "Galaxy")
        elif t == 70:
            tractors._normal_power = 600.0
            tractors._efficiency = 0.0          # starved
        elif t == 80:
            tractors._efficiency = 0.5
            _hold(w, "Galaxy")

    ref, nat, counts = run_both(monkeypatch.context, script, 100)
    beams = [nat.leaves.index(b) for b in nat.weapons("Galaxy", TRACTOR)]
    i = beams[0]
    assert nat.log[39][i][2] == ("bool", True)
    assert nat.log[40][i][2] == ("bool", False)     # powered off: stopped
    assert nat.log[69][i][2] == ("bool", True)
    assert nat.log[70][i][2] == ("bool", False)     # starved: stopped
    assert nat.log[99][i][2] == ("bool", True)      # fed again: holds
    assert nat.log[1][i][1] == nat.log[39][i][1]    # holding: no discharge
    assert "tractor" not in counts["k0_python_reasons"]
    assert sum(counts["k0_python_reasons"].values()) == 0, counts
    assert counts["k0_logged"]["hold_stop"] == 2 * len(beams)
    assert counts["k0_entries"]["LOOP_STOP"] >= 2 * len(beams)


def test_idle_tractors_step_natively(monkeypatch):
    """Ruling W6: an idle tractor (`_firing` false) is TractorBeam's
    `super().UpdateCharge(dt)`, the mixin step K0 ports, so it recharges
    natively; and the ticks it holds are K0's too (fire control native
    only): nothing is handed back."""

    def setup(w):
        w.ships["Galaxy"].GetTractorBeamSystem().TurnOn()
        for beam in w.weapons("Galaxy", TRACTOR):
            beam.SetChargeLevel(0.0)

    def script(w, t):
        if t == 20:
            _hold(w, "Galaxy")
        elif t == 40:
            w.ships["Galaxy"].GetTractorBeamSystem().StopFiring()

    ref, nat, counts = run_both(monkeypatch.context, script, 70, setup=setup)
    beams = [nat.leaves.index(b) for b in nat.weapons("Galaxy", TRACTOR)]
    # Idle ticks recharged them; the hold kept the charge; idle again after.
    i = beams[0]
    assert nat.log[0][i][1] != nat.log[18][i][1]
    assert nat.log[25][i][1] == nat.log[30][i][1]
    assert nat.log[50][i][1] != nat.log[60][i][1]
    assert _reasons(counts) == {}, counts


def test_tractor_firing_is_mirrored(monkeypatch):
    """K0 reads a tractor's `_firing` (NativeWakeField) from the
    mirror: every write pushes it."""
    with monkeypatch.context() as mp:
        w = World(mp, True, "k0_tractor_mirror")
        try:
            beams = w.weapons("Galaxy", TRACTOR)

            def check():
                for b in beams:
                    row = _h.combat_dump(b.__dict__["_nslot"])
                    assert row["_firing"] == int(b.__dict__["_firing"]), (
                        b.GetName(), row["_firing"], b.__dict__["_firing"])
            w.ships["Galaxy"].GetTractorBeamSystem().TurnOn()
            _hold(w, "Galaxy")
            check()
            w.ships["Galaxy"].GetTractorBeamSystem().StopFiring()
            assert not any(b.__dict__["_firing"] for b in beams)
            check()
        finally:
            w.close()


def test_rowless_ship_runs_python(monkeypatch):
    """A ship with no mirror row is handed back whole and stepped by the
    passive walk's own Python for it."""

    def setup(w):
        nc._drop(w.ships["Vorcha"])     # both arms: harmless when off
        _fast_tubes(w)

    def script(w, t):
        if t == 0:
            w.ships["Vorcha"].GetTorpedoSystem().StartFiring(w.ships["Galaxy"])
            w.ships["Vorcha"].GetPhaserSystem().StartFiring(w.ships["Galaxy"])

    _ref, _nat, counts = run_both(monkeypatch.context, script, 80, setup=setup)
    assert _reasons(counts).get("no_row", 0) == 80, counts


def test_none_child_is_skipped(monkeypatch):
    """A None in a weapon system's children: the mirror names it -2, K0
    hands it back by position, and the driver skips it as the Python walk
    does (`if emitter is None: continue`)."""

    def setup(w):
        phasers = w.ships["Galaxy"].GetPhaserSystem()
        phasers._children.insert(1, None)
        nc.push_field(phasers, "_children")
        w.weapons("Galaxy", PHASER)[0]._charge_level = 0.5

    _ref, _nat, counts = run_both(monkeypatch.context, lambda w, t: None, 5,
                                  setup=setup)
    assert _reasons(counts).get("unrepresentable", 0) == 5, counts


# ── The pulse watcher guard ──────────────────────────────────────────────────

class _LoudWatcher(FloatRangeWatcher):
    """A watcher whose _update K0 cannot stand in for."""
    calls = 0

    def _update(self, new_value):
        _LoudWatcher.calls += 1
        FloatRangeWatcher._update(self, new_value)


@pytest.mark.parametrize("make", [
    lambda: FloatRangeWatcher(),
    lambda: _LoudWatcher(),
], ids=["fresh_watcher", "subclass_watcher"])
def test_replaced_watcher_keeps_k0_exact(monkeypatch, make):
    """A pulse cannon's `_charge_watcher` replaced after construction: K0
    must not keep the old watcher's check count or value. A plain unowned
    FloatRangeWatcher is adopted (its checks push `_watch_checks`, its
    value `_watch_value`) and K0 commits it, queueing WATCH; any other
    watcher runs its own `_update`: the cannon is Python's (reason
    `watcher`)."""
    calls = {}

    def setup(w):
        _LoudWatcher.calls = 0
        w.ships["Vorcha"].GetPulseWeaponSystem().TurnOn()
        cannon = w.weapons("Vorcha", PULSE)[0]
        cannon._charge_watcher = make()
        _watch(w, cannon)

    def script(w, t):
        cannon = w.weapons("Vorcha", PULSE)[0]
        if t == 0:      # its shots cross the threshold downward
            w.ships["Vorcha"].GetPulseWeaponSystem().StartFiring(
                w.ships["Galaxy"])
        elif t == 50:   # and back up
            w.ships["Vorcha"].GetPulseWeaponSystem().StopFiring()
            cannon.SetChargeLevel(cannon.GetMaxCharge())
        calls[w.native] = _LoudWatcher.calls

    # Per-tick reference: a subclass's _update is counted call for call.
    ref, _nat, counts = run_both(monkeypatch.context, script, 80, setup=setup,
                                 passive=False)
    assert any(e[0] == "charge_toggle" for e in ref.events), ref.events
    assert calls[True] == calls[False]
    _no_converted_records(counts)
    if calls[True]:                         # the subclass: Python's
        assert _reasons(counts).get("watcher", 0) > 0, counts
        assert _logged(counts)["watch"] == 0, counts
    else:
        assert _logged(counts)["watch"] > 0, counts
        assert _entries(counts)["WATCH"] == _logged(counts)["watch"]


def test_replacing_a_watcher_detaches_the_old_one():
    nc.configure(ON)
    cannon = ws.PulseWeapon("c")
    old = cannon.GetChargeWatcher()
    cannon._charge_watcher = FloatRangeWatcher()
    old.AddRangeCheck(0.5, FloatRangeWatcher.FRW_BOTH, App.TGEvent_Create())
    assert cannon._watch_checks == 0
    cannon.GetChargeWatcher().AddRangeCheck(
        0.5, FloatRangeWatcher.FRW_BOTH, App.TGEvent_Create())
    assert cannon._watch_checks == 1
    assert _h.combat_dump(cannon.__dict__["_nslot"])["_watch_checks"] == 1
    shared = ws.PulseWeapon("d")
    shared._charge_watcher = cannon.GetChargeWatcher()   # owned by `cannon`
    assert shared._watch_checks == -1                    # always Python
    nc.audit_mirror()
    assert nc.audit_failures() == []


def test_unadopted_watcher_owned_by_the_weapon_is_released():
    """A watcher the field does not adopt (a subclass) whose `_owner` is
    already the weapon (FloatRangeWatcher(owner=weapon)): its `_owner` is
    cleared, so its later AddRangeCheck / RemoveRangeCheck cannot overwrite
    WATCH_ALWAYS (a 0 there would have K0 store `_value` and skip the
    subclass's `_update`)."""
    nc.configure(ON)
    cannon = ws.PulseWeapon("c")
    loud = _LoudWatcher(owner=cannon)
    cannon._charge_watcher = loud
    assert cannon._watch_checks == nc.WATCH_ALWAYS
    assert loud._owner is None
    cid = loud.AddRangeCheck(0.5, FloatRangeWatcher.FRW_BOTH,
                             App.TGEvent_Create())
    loud.RemoveRangeCheck(cid)
    assert cannon._watch_checks == nc.WATCH_ALWAYS
    assert _h.combat_dump(cannon.__dict__["_nslot"])["_watch_checks"] \
        == nc.WATCH_ALWAYS
    # Owned by ANOTHER weapon: left alone (it pushes that weapon's count).
    other = ws.PulseWeapon("d")
    shared = _LoudWatcher(owner=other)
    cannon._charge_watcher = shared
    assert shared._owner is other
    nc.audit_mirror()
    assert nc.audit_failures() == []


# ── Stand-downs ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("which", ["native_audit", "passive_audit"])
def test_audit_stands_down(monkeypatch, which):
    """With either audit on, K0 does not run at all (reason `audit`): the
    audits compare Python against Python and the mirror."""
    with monkeypatch.context() as mp:
        w = World(mp, False, "k0_audit")
        try:
            if which == "native_audit":
                nc.configure({"DAUNTLESS_NATIVE_AUDIT": "1"})
            else:
                nc.configure(ON)
                passive_state.configure({"DAUNTLESS_PASSIVE_AUDIT": "1"})
            assert nc.enabled()
            bank = w.weapons("Galaxy", PHASER)[0]
            bank.SetChargeLevel(0.5)
            assert nc.k0_weapons(list(w.order), DT) is False
            host_loop._advance_weapons(list(w.order), DT)
            assert bank.GetChargeLevel() > 0.5          # Python stepped it
            c = nc.counts()
            assert c["k0_python_step_reasons"]["audit"] == 2, c
            assert c["k0_steps"] == 0, c
        finally:
            w.close()


def test_switch_off_never_enters_k0(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("K0 entered with native combat off")

    with monkeypatch.context() as mp:
        w = World(mp, False, "k0_off")
        try:
            mp.setattr(nc, "k0_weapons", boom)
            mp.setattr(_h, "combat_k0_begin", boom)
            bank = w.weapons("Galaxy", PHASER)[0]
            bank.SetChargeLevel(0.5)
            for _ in range(3):
                w.tick()
            assert bank.GetChargeLevel() > 0.5
        finally:
            w.close()


def test_nested_k0_runs_python(monkeypatch):
    """A record's Python re-entering the weapons step (a RUN_PYTHON weapon's
    patched UpdateCharge): no nested K0 session (reason `nested`); the
    caller runs Python. A queued reload's handler, delivered after the
    session ended, starts a session of its own."""
    answers, delivered = [], []
    with monkeypatch.context() as mp:
        w = World(mp, True, "k0_nested")
        try:
            _galaxy_tubes_reload_together(w)
            bank = w.weapons("Galaxy", PHASER)[0]
            # A weapon the mirror cannot name (its row dropped) is a
            # RUN_PYTHON record (unrepresentable): Python's own UpdateCharge
            # runs for it, the instance patch included (K0 has no override
            # guard: a patch alone hands nothing back, phase 6 A2).
            nc._drop(bank)
            real = bank.UpdateCharge

            def patched(dt):
                answers.append(nc.k0_weapons([], DT))
                real(dt)
            bank.UpdateCharge = patched

            def hook(evt):
                if evt.GetEventType() == App.ET_TORPEDO_RELOAD:
                    delivered.append(nc.k0_weapons([], DT))
            w.hooks.append(hook)
            for _ in range(40):
                w.tick()
        finally:
            w.close()
    assert len(answers) == 40 and not any(answers)
    assert delivered and all(delivered)
    assert nc.counts()["k0_python_step_reasons"]["nested"] == len(answers)


def test_exception_in_a_record_abandons_the_session(monkeypatch):
    """A record's Python raises (a RUN_PYTHON weapon -- its row dropped,
    unrepresentable -- with a patched UpdateCharge): the session is
    abandoned and the exception propagates;
    the entries queued before it (a depleted bank's LOOP_STOP) are still
    delivered (ruling F5), the mirror still equals the Python and the next
    tick runs."""
    class Boom(Exception):
        pass

    stops = []

    class Handle:
        def Stop(self):
            stops.append(w.n)

    with monkeypatch.context() as mp:
        w = World(mp, True, "k0_boom")
        try:
            bank = w.weapons("Galaxy", PHASER)[0]
            bank._firing = True
            bank._beam_on_countdown = 0.0
            bank._charge_level = 0.01
            bank._loop_handle = Handle()
            later = w.weapons("Vorcha", PHASER)[0]
            nc._drop(later)                 # RUN_PYTHON (unrepresentable)

            def boom(dt):
                raise Boom()
            later.UpdateCharge = boom
            with pytest.raises(Boom):
                w.tick()
            assert not _h.combat_k0_open()
            assert bank._depleted is True and bank._firing is False
            assert stops == [1] and bank._loop_handle is None
            nc.audit_mirror()
            assert nc.audit_failures() == []
            del later.UpdateCharge
            w.tick()                                # the next tick runs
            assert nc.counts()["k0_records"]["DONE"] == 1
        finally:
            w.close()


def test_a_raising_delivery_is_raised_after_the_session(monkeypatch):
    """A queued effect's delivery raises (the depleted bank's loop sound):
    the K0 session already ended normally (nothing abandoned), the scope's
    flush delivers the rest and raises it (decision 13 under tests), and
    the next tick runs."""
    class Boom(Exception):
        pass

    class Handle:
        def Stop(self):
            raise Boom()

    with monkeypatch.context() as mp:
        w = World(mp, True, "k0_boom_delivery")
        try:
            bank = w.weapons("Galaxy", PHASER)[0]
            bank._firing = True
            bank._beam_on_countdown = 0.0
            bank._charge_level = 0.01
            bank._loop_handle = Handle()
            with pytest.raises(Boom):
                w.tick()
            assert not _h.combat_k0_open()
            assert nc.counts()["k0_records"]["DONE"] == 1  # it ended
            assert bank._depleted is True and bank._firing is False
            nc.audit_mirror()
            assert nc.audit_failures() == []
            w.tick()
            assert nc.counts()["k0_records"]["DONE"] == 2
        finally:
            w.close()


def test_raise_before_the_first_record_abandons_the_session(monkeypatch):
    """run_k0's own setup (the record kinds, the walk) raises after
    k0_weapons opened the session: the exception propagates, the session is
    abandoned (not left open, which would stand every later tick down as
    `nested`), and the next tick runs K0 natively."""
    class Boom(Exception):
        pass

    real = nc._k0_kinds
    raised = []

    def kinds_once():
        if not raised:
            raised.append(1)
            raise Boom()
        return real()

    with monkeypatch.context() as mp:
        w = World(mp, True, "k0_setup_boom")
        try:
            mp.setattr(nc, "_k0_kinds", kinds_once)
            with pytest.raises(Boom):
                w.tick()
            assert raised
            assert not _h.combat_k0_open()
            done = nc.counts()["k0_records"]["DONE"]
            w.tick()                                # the next tick runs K0
            c = nc.counts()
            assert c["k0_records"]["DONE"] == done + 1, c
            assert c["k0_python_step_reasons"]["nested"] == 0, c
            assert not _h.combat_k0_open()
        finally:
            w.close()


def test_python_kind_k0_writes_call_the_setter_once(monkeypatch):
    """A `_quiet_setter` answering a Python setter for every field (a test's
    tracing wrapper) makes K0's scalar writes PYTHON kind: each one is
    applied by calling that setter exactly once, with Python's value and
    type (a bool stays a bool), and the run equals the Python walk. A lone
    Galaxy (no pulse cannon: no watcher writes; full tubes: no slot
    writes), its banks drained so they recharge, one lit so it depletes."""
    calls = []

    def setup(w):
        for bank in w.weapons("Galaxy", PHASER):
            bank.SetChargeLevel(0.0)
        lit = w.weapons("Galaxy", PHASER)[1]
        lit.SetChargeLevel(lit.GetMaxCharge() * 0.05)
        lit._firing = True
        lit._beam_on_countdown = 0.0
        if not w.native:
            return
        real = nc._quiet_setter

        def quiet(cls, name):
            setter, kind = real(cls, name)

            def traced(obj, value, _s=setter, _n=name):
                calls.append((_n, type(value).__name__))
                return _s(obj, value)
            return traced, kind
        w.mp.setattr(nc, "_quiet_setter", quiet)

    ref, nat, counts = run_both(monkeypatch.context, lambda w, t: None, 30,
                                ships=GALAXY_VORCHA[:1], setup=setup)
    assert counts["k0_logged_writes"] > 0, counts
    assert len(calls) == counts["k0_logged_writes"], (len(calls), counts)
    assert ("_charge_level", "float") in calls, calls[:10]
    assert ("_depleted", "bool") in calls, calls
    # The stop's writes (combat fire events Task 4), Python's types.
    assert ("_firing", "bool") in calls, calls
    assert ("_beam_on_countdown", "float") in calls, calls
    assert _logged(counts)["deplete_stop"] == 1, counts


def test_reentrant_next_during_delivery_fails_loudly(monkeypatch):
    """A record's writes are applied by the binding from a view of the
    session's log while Python runs (here passive_state.wake, called for a
    WAKE-kind `_charge_level` write on a weapon flagged asleep). A
    combat_k0_next from that Python would clear the log under the view: it
    must raise the session's protocol error instead, the session must be
    abandoned, and the next tick must run as normal."""
    seen = []
    with monkeypatch.context() as mp:
        w = World(mp, True, "k0_reenter")
        try:
            bank = w.weapons("Galaxy", PHASER)[0]
            bank.SetChargeLevel(0.0)        # recharging: K0 logs its charge
            # A later record (a Vor'cha tractor holding: RUN_PYTHON)
            # delivers it, so the walk is not done: a re-entrant next()
            # would step on.
            _hold(w, "Vorcha")
            wake = passive_state.wake

            def hook(obj):
                if obj is bank:
                    try:
                        _h.combat_k0_next()
                    except RuntimeError as e:
                        seen.append(str(e))
                        raise
                    seen.append("re-entered")
                return wake(obj)

            mp.setattr(passive_state, "wake", hook)
            bank.__dict__["_passive_asleep"] = True
            with pytest.raises(RuntimeError, match="deliver"):
                w.tick()
            assert len(seen) == 1 and "deliver" in seen[0], seen
            assert not _h.combat_k0_open()
            mp.setattr(passive_state, "wake", wake)
            bank.__dict__["_passive_asleep"] = False
            nc.audit_mirror()
            assert nc.audit_failures() == []
            done = nc.counts()["k0_records"]["DONE"]
            w.tick()                                # the next tick runs
            assert nc.counts()["k0_records"]["DONE"] == done + 1
            assert not _h.combat_k0_open()
        finally:
            w.close()


# ── Counters ─────────────────────────────────────────────────────────────────

def test_counts_keys_and_reset(monkeypatch):
    with monkeypatch.context() as mp:
        w = World(mp, True, "k0_counts")
        try:
            w.tick()
        finally:
            w.close()
    c = nc.counts()
    assert set(c["k0_records"]) == {"DONE", "DEPLETE_STOP", "RELOADED",
                                    "WATCH", "RUN_PYTHON", "HOLD_STOP"}
    # No "tractor": a holding tractor is K0's (fire control native only).
    assert set(c["k0_python_reasons"]) == {
        "no_row", "not_weapon_system", "stale_row", "slot_heal",
        "override", "audit", "power_level", "parent", "unrepresentable",
        "unknown_kind", "watcher"}
    assert set(c["k0_logged"]) == {"deplete_stop", "reload", "watch",
                                   "hold_stop"}
    assert set(c["k0_entries"]) == {"LOOP_STOP", "TORPEDO_RELOAD", "WATCH"}
    assert set(c["k0_python_step_reasons"]) == {"off", "nested", "audit"}
    assert c["k0_steps"] > 0 and c["k0_records"]["DONE"] == 1
    assert isinstance(c["k0_logged_writes"], int)
    nc.reset()
    c = nc.counts()
    assert c["k0_steps"] == 0 and c["k0_records"]["DONE"] == 0
    assert not any(c["k0_python_step_reasons"].values())
    assert not any(c["k0_logged"].values())
    assert not any(c["k0_entries"].values())


# ── Mirror: an INDEX push the row cannot hold (Task 3 review, Minor 1) ──────

def test_index_beyond_int64_drops_the_row():
    nc.configure(ON)
    system = ws.PhaserSystem("p")
    assert "_nslot" in system.__dict__
    system._power_level = 2 ** 64          # no exception: the row is dropped
    assert "_nslot" not in system.__dict__
    assert system._power_level == 2 ** 64


def test_reload_and_watcher_crossing_delivered_at_the_boundary(monkeypatch):
    """Combat fire events, Task 2: inside the tick's scope (native on) a
    tube's ET_TORPEDO_RELOAD and a pulse cannon's watcher crossing are
    queued and delivered when the scope closes, not mid-walk; a crossing's
    handler reads the watcher's new value, committed at production (E3)."""
    from engine.appc import effect_queue as eq
    toggle = charge_toggle_type()
    with monkeypatch.context() as mp:
        w = World(mp, True, "k0_eq")
        try:
            _galaxy_tubes_reload_together(w)
            cannon = w.weapons("Vorcha", PULSE)[0]
            _watch(w, cannon)
            cannon.SetChargeLevel(cannon.GetMaxCharge() * 0.5)
            watcher = cannon.GetChargeWatcher()
            seen = []
            w.hooks.append(lambda evt: seen.append((
                evt.GetEventType(), eq.deferring(), eq._draining,
                watcher.GetWatchedVariable())))
            for _ in range(120):
                with host_loop._combat_effect_scope():
                    w.tick()
            kinds = {k for k, *_ in seen}
            assert {App.ET_TORPEDO_RELOAD, toggle} <= kinds, kinds
            # Every one delivered by the flush, never inside the walk.
            assert all(not d and drain for _k, d, drain, _v in seen), seen
            # The upward crossing of 0.6: its handler sees the new value.
            ups = [v for k, _d, _dr, v in seen if k == toggle]
            assert ups and all(v >= 0.6 for v in ups), ups
            c = nc.counts()
            assert c["k0_logged"]["watch"] > 0 and c["k0_logged"]["reload"] > 0
            _no_converted_records(c)
        finally:
            w.close()


# ── Combat fire events, Task 4: the watcher's value, a dropped row ──────────

def test_watcher_value_is_mirrored_for_the_kernels_old_value(monkeypatch):
    """K0's WATCH carries old = the mirrored `_watch_value`, so every commit
    Python makes of an owned watcher's `_value` (a test or tool calling
    `_update`, a cannon run in Python) is pushed: a crossing from a value
    Python committed fires natively exactly as in the reference."""
    def setup(w):
        w.ships["Vorcha"].GetPulseWeaponSystem().TurnOn()
        _watch(w, w.weapons("Vorcha", PULSE)[0])    # full: 1.0 > 0.6

    def script(w, t):
        cannon = w.weapons("Vorcha", PULSE)[0]
        if t in (5, 20):
            # Below the check, by hand (outside any step): the next
            # tick's line, back at 1.0, crosses upward from it.
            cannon.GetChargeWatcher()._update(0.3)
            if w.native:
                h = cannon.__dict__["_nslot"]
                assert _h.combat_dump(h)["_watch_value"] == 0.3

    ref, nat, counts = run_both(monkeypatch.context, script, 30,
                                setup=setup, passive=False)
    toggles = [e[3] for e in ref.events if e[0] == "charge_toggle"]
    # Up at 1 (the watcher starts at 0.0), then down (by hand) and up again
    # (the line, from the value Python committed) at 6 and at 21.
    assert toggles == [1, 6, 6, 21, 21], ref.events
    assert _logged(counts)["watch"] > 0, counts


def test_watcher_adoption_pushes_its_value():
    """A plain watcher assigned to a cannon is adopted with its value."""
    nc.configure(ON)
    cannon = ws.PulseWeapon("c")
    fresh = FloatRangeWatcher(0.625)
    cannon._charge_watcher = fresh
    assert _h.combat_dump(cannon.__dict__["_nslot"])["_watch_value"] == 0.625
    nc.audit_mirror()
    assert nc.audit_failures() == []
    fresh._value = 0.125                    # behind the watcher's back
    nc.audit_mirror()
    assert ("PulseWeapon", "_watch_value") in nc.audit_failures()


def test_a_dropped_tubes_queued_reload_is_still_delivered(monkeypatch):
    """Task 3 review, Minor 3: K0 queues a tube's TORPEDO_RELOAD by handle;
    the tube's row is dropped (a value the mirror cannot hold) before the
    scope ends. The entry names the live object instead (native_combat
    ._drop rebinds it), so ET_TORPEDO_RELOAD is still posted, as the
    Python reference posts it."""
    from engine.appc import effect_queue as eq
    with monkeypatch.context() as mp:
        w = World(mp, True, "k0_drop")
        try:
            _galaxy_tubes_reload_together(w)
            tubes = w.weapons("Galaxy", TORPEDO)
            reloads = []
            w.hooks.append(lambda evt: reloads.append(evt.GetDestination())
                           if evt.GetEventType() == App.ET_TORPEDO_RELOAD
                           else None)
            for _ in range(120):
                w.n += 1
                w.clock[0] += DT
                with eq.scope():
                    host_loop._advance_weapons(list(w.order), DT)
                    queued = _h.combat_effect_size()
                    if queued and not reloads:
                        dropped = [t for t in tubes if "_nslot" in t.__dict__]
                        for t in dropped:
                            nc._drop(t)
                if reloads:
                    break
            assert reloads, "no reload in 120 ticks"
            assert set(map(id, reloads)) <= set(map(id, tubes))
            assert eq.counts()["skipped_gone"] == 0, eq.counts()
            assert nc.counts()["k0_logged"]["reload"] == len(reloads)
        finally:
            w.close()


def test_a_k0_session_outside_the_scope_delivers_at_its_end(monkeypatch):
    """Ruling F3 for K0: `_advance_weapons` run with no scope open (a tool,
    a test) opens the session's own deferral: its reloads, Python's and the
    kernel's alike, are delivered when the K0 session ends -- in order,
    nothing left queued for a later tick."""
    from engine.appc import effect_queue as eq
    with monkeypatch.context() as mp:
        w = World(mp, True, "k0_outside")
        try:
            _galaxy_tubes_reload_together(w)
            seen = []
            w.hooks.append(lambda evt: seen.append(
                (w.n, eq.deferring(), _h.combat_k0_open()))
                if evt.GetEventType() == App.ET_TORPEDO_RELOAD else None)
            for _ in range(120):
                w.n += 1
                w.clock[0] += DT
                host_loop._advance_weapons(list(w.order), DT)
                assert _h.combat_effect_size() == 0
                if seen:
                    break
            assert seen and all(not d and not k for _n, d, k in seen), seen
            assert nc.counts()["k0_logged"]["reload"] == len(seen)
        finally:
            w.close()
