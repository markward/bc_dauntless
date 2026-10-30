"""The power draw program is bit-identical to pumping every consumer every
tick (spec docs/superpowers/specs/2026-10-30-passive-subsystem-state-design.md
§4, §7, §8 "Phase 2 as planned").

Two fresh loads of combat_stress, one per-tick and one passive (with the audit
on, which also runs the full pump beside every program tick and compares bit
for bit), get the same seeded stream of power operations and are compared
after every tick with float.hex equality: every SDK power getter of every
plant and consumer, plus both battery watchers.

Deterministic by construction: no GameLoop tick (AI draws on the unseeded
module `random`), the game clock and the module `random` reset before each
load, and the op stream comes from its own seeded Random.
"""
import random

import App
import pytest

from engine.appc import passive_power, passive_state
from engine.appc.ship_iter import iter_ships
from engine.appc.subsystems import SensorSubsystem
from engine.core import loop as game_loop
from engine.core.loop import TICK_DELTA
from tests.helpers import headless_mission

SHIPS = "6"
TICKS = 600
SEED = 20261030
OP_CHANCE = 0.08
KINDS = ("slider", "turn_off", "turn_on", "set_power_wanted", "steal",
         "drain", "cloak", "add_consumer")


def _hex(v):
    return float(v).hex()


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
        self.cloaked = [s for s in self.ships
                        if s.GetCloakingSubsystem() is not None]
        self.log = []
        self.added = 0

    def op(self, rng):
        kind = rng.choice(KINDS)
        ship = self.ships[rng.randrange(len(self.ships))]
        consumers = ship._powered_consumers
        consumer = consumers[rng.randrange(len(consumers))]
        plant = ship.GetPowerSubsystem()
        if kind == "slider":
            consumer.SetPowerPercentageWanted(rng.choice((0.0, 0.5, 1.25)))
        elif kind == "turn_off":
            consumer.TurnOff()
        elif kind == "turn_on":
            consumer.TurnOn()
        elif kind == "set_power_wanted":
            consumer.SetPowerWanted(rng.random() * 10.0)
        elif kind == "steal":
            plant.StealPower(plant.GetMainBatteryPower() * 0.5)
        elif kind == "drain":
            plant.SetMainBatteryPower(0.0)
        elif kind == "cloak":
            if self.cloaked:
                self.cloaked[rng.randrange(len(self.cloaked))] \
                    .GetCloakingSubsystem().StartCloaking()
        elif kind == "add_consumer":
            self.added += 1
            extra = SensorSubsystem("Extra Sensors %d" % self.added)
            extra.SetNormalPowerPerSecond(rng.choice((0.0, 40.0, 400.0)))
            extra.TurnOn()
            ship.AddPoweredConsumer(extra)
        else:
            raise AssertionError(kind)

    def record(self):
        row = []
        for ship in self.ships:
            plant = ship.GetPowerSubsystem()
            if plant is None:
                continue
            row += [_hex(plant.GetMainBatteryPower()),
                    _hex(plant.GetBackupBatteryPower()),
                    _hex(plant.GetPowerDispensed()),
                    _hex(plant.GetPowerWanted()),
                    _hex(plant.GetAvailablePower()),
                    _hex(plant.GetMainBatteryWatcher().GetWatchedVariable()),
                    _hex(plant.GetBackupBatteryWatcher().GetWatchedVariable())]
            for c in ship._powered_consumers:
                row += [_hex(c.GetPowerWanted()), _hex(c.GetPowerReceived()),
                        _hex(c.GetPowerPercentage()),
                        _hex(c.GetNormalPowerPercentage())]
        self.log.append(row)

    def run(self, ticks_per_frame):
        rng = random.Random(SEED)
        tick = 0
        while tick < TICKS:
            # Ops only between frames (bursts of ticks_per_frame ticks), at
            # the same per-tick rate whatever the burst length.
            if rng.random() < OP_CHANCE * ticks_per_frame:
                self.op(rng)
            for _ in range(ticks_per_frame):
                tick += 1
                App.g_kTimerManager._time += TICK_DELTA
                game_loop._update_ship_subsystems()
                self.record()
        return self.log


def _both(monkeypatch, ticks_per_frame, audit=True):
    with monkeypatch.context() as mp:
        reference = _Scene(mp, passive=False).run(ticks_per_frame)
    assert passive_power.counts()["program_ticks"] == 0
    with monkeypatch.context() as mp:
        passive = _Scene(mp, passive=True, audit=audit).run(ticks_per_frame)
    return reference, passive


def _assert_identical(reference, passive, audit=True):
    assert len(passive) == len(reference) == TICKS
    for tick, (row, ref_row) in enumerate(zip(passive, reference), start=1):
        assert row == ref_row, "power state differs at tick %d" % tick
    if audit:
        assert passive_state.audit_failures() == []
    counts = passive_power.counts()
    assert counts["program_ticks"] > 0
    assert counts["thawed"] > 0


def test_power_matches_per_tick(monkeypatch):
    _assert_identical(*_both(monkeypatch, 1))


def test_power_matches_per_tick_six_ticks_per_frame(monkeypatch):
    _assert_identical(*_both(monkeypatch, 6))


def test_power_matches_per_tick_without_the_audit(monkeypatch):
    """Production shape: no full pump runs beside the program."""
    _assert_identical(*_both(monkeypatch, 1, audit=False), audit=False)
