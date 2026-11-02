"""K0 dispatch: charging and reloading run through the native charging kernel
when native combat is on (native weapon state, Task 5; spec
docs/superpowers/specs/2026-11-02-native-weapon-state-design.md §4.3, plan
docs/superpowers/plans/2026-11-02-native-weapon-state.md Review Focus 2-3).

`host_loop._advance_weapons` asks `native_combat.k0_weapons(ships, dt)`; K0
steps every weapon from the mirror (the per-tick model) and stops at each
thing only Python may do -- a depleted bank's StopFiring, a reloaded tube's
ET_TORPEDO_RELOAD, a pulse watcher with checks, a hand-back -- with the
writes before it already applied. Every scenario is run with native off and
on and compared tick by tick by float.hex() (tests/helpers/k0_fight.py).
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
    rec = _records(counts)
    assert rec["DEPLETE_STOP"] > 0 and rec["RELOADED"] > 0 \
        and rec["WATCH"] > 0, counts
    assert counts["k0_logged_writes"] > 0, counts
    # The magazine ran dry with a slot due: the reload gate denied it.
    vorcha_tubes = nat.weapons("Vorcha", TORPEDO)
    ammo = nat.ships["Vorcha"].GetTorpedoSystem().GetCurrentAmmoType()
    assert ammo.GetAvailable() <= sum(t.GetNumReady() for t in vorcha_tubes)
    assert any(t.GetNumReady() < t.GetMaxReady()
               and max(t._reload_timers) >= t._reload_delay
               for t in vorcha_tubes)


def test_deplete_stop_plays_loop_stop(monkeypatch):
    """A firing bank drained to 0 by K0: Python's StopFiring runs at the
    record, so the looped fire sound is stopped (and dropped) exactly once,
    in both arms, with `_depleted` latched before it."""
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
    assert _records(counts)["DEPLETE_STOP"] == 1, counts


def _galaxy_tubes_reload_together(w):
    _fast_tubes(w)
    for tube in w.weapons("Galaxy", TORPEDO):
        tube.SetNumReady(0)         # every slot cooling from the same clock


def test_reloaded_handler_starts_firing_same_ship(monkeypatch):
    """Review Focus 2. Each ET_TORPEDO_RELOAD of a Galaxy tube runs a handler
    that StartFirings the same ship's torpedoes and phasers (nested K1
    system sessions inside the K0 walk). The handler, and K1, must see the
    weapons already stepped this tick post-step and the later ones pre-step:
    the tubes reloading on the same tick fire one by one, between the
    reloads, exactly as the Python walk."""
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
    assert _records(counts)["RELOADED"] >= 2, counts
    assert counts["k1_records"] > 0, counts


def test_handler_sets_later_weapon_charge(monkeypatch):
    """Review Focus 3. A Galaxy reload's handler sets a Vor'cha phaser bank
    (a later ship: not yet stepped this tick) to a quarter charge with the
    SDK's SetChargeLevel. That bank must be stepped THIS tick from the new
    value (the wake and the mirror push), as the Python walk does."""
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
        assert nat.log[n - 1][i][1] != quarter, (n, nat.log[n - 1][i])
    assert _records(counts)["RELOADED"] > 0, counts


def _hold(w, ship_name):
    """Every tractor of the ship holding (its `_firing`, written as the
    beam's engage writes it: the K0 kernel reads the pushed value). A real
    engage needs a target within 120 GU with its shields down."""
    for beam in w.weapons(ship_name, TRACTOR):
        beam._firing = True


def test_tractor_handed_back(monkeypatch):
    """A HOLDING tractor beam runs in Python (its UpdateCharge stops a beam
    whose parent is off or starved, with a power program thaw K0 does not
    port): held, the parent turned off (Python's power-loss StopFiring),
    turned on again."""

    def script(w, t):
        tractors = w.ships["Galaxy"].GetTractorBeamSystem()
        if t == 0:
            tractors.TurnOn()
            _hold(w, "Galaxy")
        elif t == 40:
            tractors.TurnOff()
        elif t == 60:
            tractors.TurnOn()

    ref, nat, counts = run_both(monkeypatch.context, script, 90)
    beams = [nat.leaves.index(b) for b in nat.weapons("Galaxy", TRACTOR)]
    assert nat.log[39][beams[0]][2] == ("bool", True)
    assert nat.log[41][beams[0]][2] == ("bool", False)     # Python stopped it
    # Holding at ticks 1-41 (the TurnOff before tick 41's step: Python's
    # UpdateCharge then stops it), idle (native) otherwise.
    assert _reasons(counts).get("tractor", 0) == 41 * len(beams), counts
    assert counts["k0_steps"] > 0, counts


def test_idle_tractors_step_natively(monkeypatch):
    """Ruling W6: an idle tractor (`_firing` false) is TractorBeam's
    `super().UpdateCharge(dt)`, the mixin step K0 ports, so it recharges
    natively; only the ticks it holds are handed back."""

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
    assert _reasons(counts).get("tractor", 0) == 20 * len(beams), counts


def test_tractor_firing_is_mirrored(monkeypatch):
    """K0 reads a tractor's `_firing` (NativeThawParentWakeField) from the
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
    must not keep the old watcher's check count. A plain unowned
    FloatRangeWatcher is adopted (its checks push `_watch_checks`); any
    other watcher always runs `_update` in Python (WATCH)."""
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
    assert _records(counts)["WATCH"] > 0, counts


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
    """A record's handler re-entering the weapons step: no nested K0 session
    (reason `nested`); the caller runs Python."""
    answers = []
    with monkeypatch.context() as mp:
        w = World(mp, True, "k0_nested")
        try:
            _galaxy_tubes_reload_together(w)

            def hook(evt):
                if evt.GetEventType() == App.ET_TORPEDO_RELOAD:
                    answers.append(nc.k0_weapons([], DT))
            w.hooks.append(hook)
            for _ in range(40):
                w.tick()
        finally:
            w.close()
    assert answers and not any(answers)
    assert nc.counts()["k0_python_step_reasons"]["nested"] == len(answers)


def test_exception_in_a_record_abandons_the_session(monkeypatch):
    """A record's Python raises (a depleted bank's loop sound, here): the
    session is abandoned and the exception propagates; the mirror still
    equals the Python and the next tick runs."""
    class Boom(Exception):
        pass

    class Handle:
        def Stop(self):
            raise Boom()

    with monkeypatch.context() as mp:
        w = World(mp, True, "k0_boom")
        try:
            bank = w.weapons("Galaxy", PHASER)[0]
            bank._firing = True
            bank._beam_on_countdown = 0.0
            bank._charge_level = 0.01
            bank._loop_handle = Handle()
            with pytest.raises(Boom):
                w.tick()
            assert not _h.combat_k0_open()
            assert bank._depleted is True       # applied before the record
            nc.audit_mirror()
            assert nc.audit_failures() == []
            w.tick()                                # the next tick runs
            assert nc.counts()["k0_records"]["DONE"] == 1
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
    assert _records(counts)["DEPLETE_STOP"] == 1, counts


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
            # A later record (a Vor'cha cannon's WATCH) delivers it, so the
            # walk is not done: a re-entrant next() would step on.
            _watch(w, w.weapons("Vorcha", PULSE)[0])
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
                                    "WATCH", "RUN_PYTHON"}
    assert set(c["k0_python_reasons"]) == {
        "tractor", "no_row", "not_weapon_system", "stale_row", "slot_heal",
        "override", "audit", "power_level", "parent", "unrepresentable",
        "unknown_kind"}
    assert set(c["k0_python_step_reasons"]) == {"off", "nested", "audit"}
    assert c["k0_steps"] > 0 and c["k0_records"]["DONE"] == 1
    assert isinstance(c["k0_logged_writes"], int)
    nc.reset()
    c = nc.counts()
    assert c["k0_steps"] == 0 and c["k0_records"]["DONE"] == 0
    assert not any(c["k0_python_step_reasons"].values())


# ── Mirror: an INDEX push the row cannot hold (Task 3 review, Minor 1) ──────

def test_index_beyond_int64_drops_the_row():
    nc.configure(ON)
    system = ws.PhaserSystem("p")
    assert "_nslot" in system.__dict__
    system._power_level = 2 ** 64          # no exception: the row is dropped
    assert "_nslot" not in system.__dict__
    assert system._power_level == 2 ** 64
