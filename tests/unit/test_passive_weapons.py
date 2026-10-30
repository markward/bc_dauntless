"""Sleeping weapons: a full idle bank or a loaded tube is not stepped until a
field its update reads is written (spec
docs/superpowers/specs/2026-10-30-passive-subsystem-state-design.md §6.1,
§6.3). Real ships from combat_stress, driven through the host's own
_advance_weapons, with no GameLoop tick (no AI, so nothing else moves).
"""
import App
import pytest

from engine import host_loop
from engine.appc import passive_state
from engine.appc.ship_iter import iter_ships
from engine.appc.weapon_subsystems import (
    PhaserBank, PhaserSystem, PulseWeapon, TorpedoTube, TractorBeam,
)
from engine.core import loop as game_loop
from engine.core.loop import TICK_DELTA
from tests.helpers import headless_mission


@pytest.fixture
def ships(monkeypatch):
    monkeypatch.delenv("DAUNTLESS_PASSIVE_STATE", raising=False)
    monkeypatch.delenv("DAUNTLESS_PASSIVE_AUDIT", raising=False)
    monkeypatch.setenv("DAUNTLESS_COMBAT_SHIPS", "4")
    App.g_kTimerManager._time = 0.0
    headless_mission.load("engine.dev_missions.combat_stress")
    return list(iter_ships())


def _advance(ships):
    host_loop._advance_weapons(ships, TICK_DELTA)


def _weapons(ships, cls):
    """Every weapon of type `cls`, in the walk's order."""
    out = []
    for ship in ships:
        for group in (ship.GetPhaserSystem(), ship.GetPulseWeaponSystem(),
                      ship.GetTractorBeamSystem(), ship.GetTorpedoSystem()):
            if group is None:
                continue
            for i in range(group.GetNumWeapons()):
                w = group.GetWeapon(i)
                if isinstance(w, cls):
                    out.append(w)
    return out


def _spy(monkeypatch, cls, name):
    """Record (by identity) every object `cls.<name>` is called on."""
    calls = []
    orig = getattr(cls, name)

    def spy(self, *args):
        calls.append(id(self))
        return orig(self, *args)

    monkeypatch.setattr(cls, name, spy)
    return calls


def _sleeping(ws):
    return [w for w in ws if passive_state.is_asleep(w)]


def test_a_full_idle_bank_is_not_stepped(ships, monkeypatch):
    _advance(ships)
    banks = _weapons(ships, PhaserBank)
    full = [b for b in banks
            if not b.IsFiring() and b.GetChargeLevel() >= b.GetMaxCharge()]
    assert full
    assert all(passive_state.is_asleep(b) for b in full)
    calls = _spy(monkeypatch, PhaserBank, "UpdateCharge")
    _advance(ships)
    assert not {id(b) for b in full} & set(calls)


def test_set_charge_level_wakes_a_sleeping_bank(ships, monkeypatch):
    _advance(ships)
    bank = _sleeping(_weapons(ships, PhaserBank))[0]
    bank.SetChargeLevel(0.0)
    assert not passive_state.is_asleep(bank)
    calls = _spy(monkeypatch, PhaserBank, "UpdateCharge")
    _advance(ships)
    assert id(bank) in calls


def _a_bank_that_fires(ships):
    """A sleeping bank and another ship inside its arc (ships sit on a ring,
    so some bank covers some ship)."""
    for bank in _sleeping(_weapons(ships, PhaserBank)):
        own = bank.GetParentShip()
        for target in ships:
            if target is not own and bank._aim_in_arc(target):
                return bank, target
    raise AssertionError("no bank has a ship in arc")


def test_fire_wakes_and_the_bank_drains(ships, monkeypatch):
    _advance(ships)
    bank, target = _a_bank_that_fires(ships)
    assert bank.Fire(target)
    assert not passive_state.is_asleep(bank)
    calls = _spy(monkeypatch, PhaserBank, "UpdateCharge")
    for _ in range(60):
        del calls[:]
        _advance(ships)
        assert id(bank) in calls
    assert bank.IsFiring()
    assert bank.GetChargeLevel() < bank.GetMaxCharge()


def test_a_launch_wakes_the_tube(ships, monkeypatch):
    _advance(ships)
    tubes = _sleeping(_weapons(ships, TorpedoTube))
    assert len(tubes) >= 2
    calls = _spy(monkeypatch, TorpedoTube, "UpdateReload")
    tubes[0].DecNumReady()
    assert not passive_state.is_asleep(tubes[0])
    tubes[1].SetNumReady(0)
    assert not passive_state.is_asleep(tubes[1])
    _advance(ships)
    assert id(tubes[0]) in calls and id(tubes[1]) in calls


def test_replacing_a_system_rebuilds_the_registry(ships, monkeypatch):
    ship = ships[0]
    _advance(ships)
    psys = ship.GetPhaserSystem()
    old_banks = [psys.GetWeapon(i) for i in range(psys.GetNumWeapons())]
    assert passive_state.is_asleep(old_banks[0])

    extra = PhaserBank("Extra Phaser")
    extra._max_charge = 5.0               # charge stays 0: it has work to do
    psys.AddChildSubsystem(extra)
    calls = _spy(monkeypatch, PhaserBank, "UpdateCharge")
    _advance(ships)
    assert id(extra) in calls

    ship.SetPhaserSystem(PhaserSystem("Replacement Phasers"))
    for bank in old_banks + [extra]:
        bank.SetChargeLevel(0.0)          # wakes them; they must stay unwalked
    del calls[:]
    _advance(ships)
    _advance(ships)
    assert not {id(b) for b in old_banks + [extra]} & set(calls)


def test_pulse_weapon_sleeps_only_after_cooldown(ships):
    _advance(ships)
    pulse = _sleeping(_weapons(ships, PulseWeapon))[0]
    assert pulse.GetChargeLevel() >= pulse.GetMaxCharge()
    pulse._cooldown_remaining = 0.05
    assert not passive_state.is_asleep(pulse)
    for _ in range(20):
        _advance(ships)
        if pulse._cooldown_remaining > 0.0:
            assert not passive_state.is_asleep(pulse)
        else:
            break
    assert pulse._cooldown_remaining == 0.0
    assert passive_state.is_asleep(pulse)


def test_tractor_sleeps_only_when_released_and_full(ships):
    _advance(ships)
    tractor = _sleeping(_weapons(ships, TractorBeam))[0]
    tractor._firing = True                # engaged, holding a target
    for _ in range(5):
        game_loop._update_ship_subsystems()
        _advance(ships)
        assert tractor.IsFiring()
        assert not passive_state.is_asleep(tractor)
    tractor.StopFiring()
    _advance(ships)
    assert passive_state.is_asleep(tractor)


def _record_order(monkeypatch):
    """Patch every weapon update to log (ship id, weapon id) in call order."""
    order = []
    for cls, name in ((PhaserBank, "UpdateCharge"), (PulseWeapon, "UpdateCharge"),
                      (TractorBeam, "UpdateCharge"), (TorpedoTube, "UpdateReload")):
        orig = getattr(cls, name)

        def rec(self, *args, _orig=orig):
            order.append((id(self.GetParentShip()), id(self)))
            return _orig(self, *args)

        monkeypatch.setattr(cls, name, rec)
    return order


def _wake_a_mix(ships):
    """Wake some of every kind, leaving the rest asleep."""
    _sleeping(_weapons(ships, PhaserBank))[1].SetChargeLevel(0.0)
    _sleeping(_weapons(ships, PhaserBank))[-1].SetChargeLevel(1.0)
    _sleeping(_weapons(ships, PulseWeapon))[0].SetChargeLevel(0.0)
    _sleeping(_weapons(ships, TractorBeam))[-1].SetChargeLevel(0.5)
    _sleeping(_weapons(ships, TorpedoTube))[2].DecNumReady()


def test_awake_weapons_step_in_todays_order(ships, monkeypatch):
    _advance(ships)
    _wake_a_mix(ships)
    every = (_weapons(ships, PhaserBank) + _weapons(ships, PulseWeapon)
             + _weapons(ships, TractorBeam) + _weapons(ships, TorpedoTube))
    asleep = {id(w) for w in every if passive_state.is_asleep(w)}
    assert asleep and len(asleep) < len(every)

    order = _record_order(monkeypatch)
    passive_state.configure({"DAUNTLESS_PASSIVE_STATE": "0"})
    _advance(ships)
    per_tick = list(order)
    del order[:]
    passive_state.configure({})
    _advance(ships)
    assert order == [o for o in per_tick if o[1] not in asleep]


def _two_on_one_ship(ships):
    """(bank, tube) on the same ship: the bank walks before the tube."""
    for ship in ships:
        banks = [b for b in _weapons([ship], PhaserBank)
                 if passive_state.is_asleep(b)]
        tubes = [t for t in _weapons([ship], TorpedoTube)
                 if passive_state.is_asleep(t)]
        if banks and tubes:
            return banks[0], tubes[0]
    raise AssertionError("no ship has a sleeping bank and tube")


def test_a_wake_during_the_walk_lands_at_its_turn(ships, monkeypatch):
    """Spec §6.3: woken before its turn in this tick's walk, a weapon is
    stepped in this tick; woken after its turn, from the next tick -- the
    per-tick model already stepped it, as a no-op, before the write. A wake
    can come from inside the walk: an update posts an event (ET_TORPEDO_RELOAD,
    the pulse charge watcher), and its handlers run synchronously."""
    _advance(ships)
    bank, tube = _two_on_one_ship(ships)
    bank.SetChargeLevel(0.0)              # awake, walks first
    wakes = {"bank_turn": lambda: tube.SetNumReady(0)}
    calls = []
    orig_charge, orig_reload = PhaserBank.UpdateCharge, TorpedoTube.UpdateReload

    def charge(self, dt):
        calls.append(id(self))
        orig_charge(self, dt)
        if self is bank and "bank_turn" in wakes:
            wakes.pop("bank_turn")()

    def reload(self, dt=0.0):
        calls.append(id(self))
        orig_reload(self, dt)

    monkeypatch.setattr(PhaserBank, "UpdateCharge", charge)
    monkeypatch.setattr(TorpedoTube, "UpdateReload", reload)
    _advance(ships)
    assert id(tube) in calls              # woken before its turn: stepped now

    # The other way round: a tube's step wakes a bank that walked earlier.
    _advance(ships)
    other = [b for b in _weapons([bank.GetParentShip()], PhaserBank)
             if passive_state.is_asleep(b)][0]
    tube2 = tube

    def reload_waking(self, dt=0.0):
        calls.append(id(self))
        orig_reload(self, dt)
        if self is tube2:
            other.SetChargeLevel(0.0)

    monkeypatch.setattr(TorpedoTube, "UpdateReload", reload_waking)
    del calls[:]
    _advance(ships)
    assert id(other) not in calls         # its turn had passed
    monkeypatch.setattr(TorpedoTube, "UpdateReload", reload)
    del calls[:]
    _advance(ships)
    assert id(other) in calls
