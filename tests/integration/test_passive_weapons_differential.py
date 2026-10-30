"""Sleeping weapons are bit-identical to stepping every weapon every tick
(spec docs/superpowers/specs/2026-10-30-passive-subsystem-state-design.md §2.3,
§7 "Seeded unit differentials").

Two fresh loads of combat_stress, one per-tick and one passive with the sleep
audit on, get the same seeded stream of operations and are compared tick by
tick with `==`: every weapon's charge, firing state, depletion latch, pulse
cooldown, ready count and reload slots, plus the reload / fired / charge-toggle
events in order.

Deterministic by construction: no GameLoop tick (AI draws on the unseeded
module `random`), the game clock and the module `random` reset before each
load, and frames run in the host's order -- ops, N subsystem ticks, ops, N
weapon steps -- with a few ops between weapon steps where the host's combat
step would fire. That puts wakes both before and after the weapons walk.
"""
import random
import sys

import App
import pytest

from engine import host_loop
from engine.appc import passive_state
from engine.appc.ship_iter import iter_ships
from engine.appc.weapon_subsystems import (
    PulseWeapon, TorpedoTube, _EnergyWeaponFireMixin,
)
from engine.core import loop as game_loop
from engine.core.loop import TICK_DELTA
from tests.helpers import headless_mission

SHIPS = "6"
TICKS = 360
# Stock ReloadDelay is tens of seconds, longer than the run; shortened the same
# way in both runs so reloads complete (and post ET_TORPEDO_RELOAD) inside it.
RELOAD_DELAY_S = 0.6
# A range check on every pulse watcher, the way Conditions/ConditionPulseReady
# registers one, so the watcher's ET_CHARGE_TOGGLE is exercised.
CHARGE_TOGGLE_FRACTION = 0.6


def _walk(ships):
    """Every weapon in the walk's order."""
    out = []
    for ship in ships:
        for group in (ship.GetPhaserSystem(), ship.GetPulseWeaponSystem(),
                      ship.GetTractorBeamSystem(), ship.GetTorpedoSystem()):
            if group is None:
                continue
            for i in range(group.GetNumWeapons()):
                out.append(group.GetWeapon(i))
    return out


class _Scene:
    def __init__(self, monkeypatch, passive, audit=True):
        monkeypatch.delenv("DAUNTLESS_PASSIVE_STATE", raising=False)
        monkeypatch.delenv("DAUNTLESS_PASSIVE_AUDIT", raising=False)
        monkeypatch.setenv("DAUNTLESS_COMBAT_SHIPS", SHIPS)
        App.g_kTimerManager._time = 0.0
        random.seed(0)
        headless_mission.load("engine.dev_missions.combat_stress")
        # After the load: constructing a GameLoop re-reads the environment.
        passive_state.configure(
            ({"DAUNTLESS_PASSIVE_AUDIT": "1"} if audit else {}) if passive
            else {"DAUNTLESS_PASSIVE_STATE": "0"})
        self.ships = list(iter_ships())
        self.weapons = _walk(self.ships)
        self.banks = [w for w in self.weapons
                      if isinstance(w, _EnergyWeaponFireMixin)]
        self.tubes = [w for w in self.weapons if isinstance(w, TorpedoTube)]
        self.systems = [g for s in self.ships
                        for g in (s.GetPhaserSystem(), s.GetPulseWeaponSystem(),
                                  s.GetTractorBeamSystem(), s.GetTorpedoSystem())
                        if g is not None]
        self.tick = 0
        self.log = []
        self.events = []
        self._toggle = self._charge_toggle_type()
        for tube in self.tubes:
            tube._reload_delay = RELOAD_DELAY_S
        for w in self.weapons:
            if isinstance(w, PulseWeapon):
                evt = App.TGEvent_Create()
                evt.SetEventType(self._toggle)
                evt.SetDestination(w)
                w.GetChargeWatcher().AddRangeCheck(
                    CHARGE_TOGGLE_FRACTION, App.FloatRangeWatcher.FRW_BOTH, evt)
        names = {App.ET_TORPEDO_RELOAD: "reload",
                 App.ET_WEAPON_FIRED: "fired",
                 self._toggle: "charge_toggle"}
        orig = App.g_kEventManager.AddEvent

        def add_event(evt, _orig=orig):
            kind = names.get(evt.GetEventType())
            if kind is not None:
                dest = evt.GetDestination()
                self.events.append((kind, dest.GetName() if dest else None,
                                    self.tick))
            return _orig(evt)

        monkeypatch.setattr(App.g_kEventManager, "AddEvent", add_event)

    @staticmethod
    def _charge_toggle_type():
        import Conditions.ConditionPulseReady as cpr
        return cpr.ET_CHARGE_TOGGLE

    def _enemy_of(self, rng, weapon):
        own = weapon.GetParentShip()
        side = own.GetName().startswith("Enemy")
        foes = [s for s in self.ships if s.GetName().startswith("Enemy") != side]
        return rng.choice(foes)

    def op(self, rng, kinds):
        kind = rng.choice(kinds)
        if kind == "fire":
            # Untargeted half the time: pulse cannons' arcs rarely hold a ring
            # neighbour, and a no-target shot goes straight out the cannon.
            bank = rng.choice(self.banks)
            bank.Fire(self._enemy_of(rng, bank) if rng.random() < 0.5 else None)
        elif kind == "stop":
            rng.choice(self.banks).StopFiring()
        elif kind == "charge":
            bank = rng.choice(self.banks)
            bank.SetChargeLevel(rng.random() * bank.GetMaxCharge())
        elif kind == "drain":
            rng.choice(self.banks).SetChargeLevel(0.0)
        elif kind == "recharge_all":
            # Actions/ShipScriptActions.py:362,369
            for bank in self.banks:
                bank.SetChargeLevel(bank.GetMaxCharge())
        elif kind == "tube_fire":
            tube = rng.choice(self.tubes)
            tube.Fire(self._enemy_of(rng, tube) if rng.random() < 0.5 else None)
        elif kind == "tube_dec":
            rng.choice(self.tubes).DecNumReady()
        elif kind == "tube_set":
            tube = rng.choice(self.tubes)
            tube.SetNumReady(rng.randint(0, tube.GetMaxReady()))
        elif kind == "condition":
            sub = rng.choice(self.systems + self.banks)
            sub.SetCondition(sub.GetMaxCondition() * (0.05 + 0.95 * rng.random()))
        elif kind == "power":
            rng.choice(self.systems).SetPowerPercentageWanted(
                rng.choice((0.0, 0.5, 1.0, 1.25)))
        elif kind == "off":
            rng.choice(self.systems).TurnOff()
        elif kind == "on":
            rng.choice(self.systems).TurnOn()
        else:
            raise AssertionError(kind)

    def ops(self, rng, kinds, n):
        for _ in range(n):
            self.op(rng, kinds)

    def record(self):
        row = []
        for w in self.weapons:
            if isinstance(w, TorpedoTube):
                row.append((w.GetNumReady(), tuple(w._reload_timers)))
            else:
                row.append((w.GetChargeLevel(), w.IsFiring(), w._depleted,
                            getattr(w, "_cooldown_remaining", None)))
        self.log.append(row)

    def run(self, seed, ticks_per_frame, kinds):
        rng = random.Random(seed)
        while self.tick < TICKS:
            self.ops(rng, kinds, rng.randint(0, 2))
            for _ in range(ticks_per_frame):
                App.g_kTimerManager._time += TICK_DELTA
                game_loop._update_ship_subsystems()
            self.ops(rng, kinds, rng.randint(0, 2))
            for _ in range(ticks_per_frame):
                self.tick += 1
                host_loop._advance_weapons(self.ships, TICK_DELTA)
                self.record()
                # Where the host's combat step would fire, after the walk.
                if rng.random() < 0.3:
                    self.op(rng, kinds)
        return self.log, self.events


ALL_OPS = ("fire", "fire", "stop", "charge", "drain", "recharge_all",
           "tube_fire", "tube_dec", "tube_set", "condition", "power",
           "off", "on")


def _both(monkeypatch, seed, ticks_per_frame, kinds, audit=True):
    with monkeypatch.context() as mp:
        reference = _Scene(mp, passive=False).run(seed, ticks_per_frame, kinds)
    with monkeypatch.context() as mp:
        passive = _Scene(mp, passive=True, audit=audit).run(seed, ticks_per_frame, kinds)
    return reference, passive


def _assert_identical(reference, passive, audit=True):
    ref_log, ref_events = reference
    log, events = passive
    assert len(log) == len(ref_log) == TICKS
    for tick, (row, ref_row) in enumerate(zip(log, ref_log), start=1):
        assert row == ref_row, "weapon state differs at tick %d" % tick
    assert events == ref_events
    if audit:
        assert passive_state.audit_failures() == []
    counts = passive_state.counts()
    assert counts["slept"] > 0 and counts["woke"] > 0


@pytest.mark.parametrize("ticks_per_frame", (1, 6))
@pytest.mark.parametrize("seed", range(6))
def test_weapons_match_per_tick(monkeypatch, seed, ticks_per_frame):
    reference, passive = _both(monkeypatch, seed, ticks_per_frame, ALL_OPS)
    assert reference[1], "the op stream produced no events to compare"
    _assert_identical(reference, passive)


def test_weapons_match_per_tick_without_the_audit(monkeypatch):
    """Production shape: the passive side runs with the audit off, so nothing
    steps a sleeper behind the model's back."""
    reference, passive = _both(monkeypatch, 3, 6, ALL_OPS, audit=False)
    assert reference[1], "the op stream produced no events to compare"
    _assert_identical(reference, passive, audit=False)


def test_script_recharge_all_matches_per_tick(monkeypatch):
    """Review focus 1: a mission refilling every bank (a same-value write on
    the full ones) wakes them harmlessly; a drained bank recharges on the same
    ticks as the per-tick model."""
    kinds = ("drain", "drain", "drain", "recharge_all")
    reference, passive = _both(monkeypatch, 7, 6, kinds)
    _assert_identical(reference, passive)
