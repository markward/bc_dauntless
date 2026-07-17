"""Reload must not chamber a store round that is already sitting in another tube.

BC (weapon-firing-mechanics.md §2.2, ReloadTorpedo gate 2): reload is allowed iff
``AmmoCounts[currentType] > NumReady`` where NumReady (TorpedoSystem+0x118) is the
SYSTEM-WIDE count of rounds currently loaded in tubes.  In plain terms: is there a
round of this type in stores that is not ALREADY sitting in a tube?

Our model debits ammo at FIRE (not at reload), so GetAvailable() is the TOTAL
inventory of that type — it still counts a chambered-but-unfired round (exactly
BC's AmmoCounts).  The pre-fix gate ``_ammo_exhausted()`` only checks
``GetAvailable() <= 0`` (inventory empty), never comparing against how many rounds
are already loaded across the system's tubes.  So when the last inventory round is
already chambered in one tube, a second empty tube still reloads — chambering the
same physical round twice.  Firing both then launches more torpedoes than existed.

The invariant that must hold: rounds loaded across all tubes never exceeds the
type's total inventory.
"""
import pytest

import App
from engine.appc.subsystems import TorpedoSystem, TorpedoTube
from engine.appc.weapon_subsystems import TorpedoAmmoType


@pytest.fixture
def clock():
    App.g_kTimerManager._time = 0.0

    def _set(t: float) -> None:
        App.g_kTimerManager._time = float(t)

    yield _set
    App.g_kTimerManager._time = 0.0


def _tube(name: str) -> TorpedoTube:
    tube = TorpedoTube(name)
    tube._max_ready = 1
    tube._num_ready = 1
    tube._reload_delay = 40.0
    tube._resize_slots()
    return tube


def _system_loaded(system) -> int:
    """System-wide count of rounds currently chambered across all tubes."""
    return sum(c.GetNumReady() for c in system._children
               if isinstance(c, TorpedoTube))


def test_reload_does_not_re_chamber_a_round_already_in_another_tube(clock):
    system = TorpedoSystem("Torpedoes")
    system.TurnOn()
    ammo = TorpedoAmmoType("Photon", max_torpedoes=2)   # available == 2, finite
    system.AddAmmoType(ammo)

    tube_a = _tube("Forward Torpedo 1")
    tube_b = _tube("Forward Torpedo 2")
    system.AddChildSubsystem(tube_a)
    system.AddChildSubsystem(tube_b)

    # Fire tube B: debits one round (available 2 -> 1) and leaves B cooling.
    clock(100.0)
    tube_b.Fire()
    assert tube_b.GetNumReady() == 0
    assert ammo.GetAvailable() == 1

    # State now: 1 round left in inventory, and it is the round chambered in
    # tube A.  The invariant holds so far.
    assert _system_loaded(system) == 1
    assert _system_loaded(system) <= ammo.GetAvailable()

    # Tube B's cooldown elapses and it tries to reload.
    tube_b.ReloadTorpedo()

    loaded = _system_loaded(system)
    assert loaded <= ammo.GetAvailable(), (
        "tube B re-chambered the store round already loaded in tube A "
        "(%d loaded > %d in inventory) -- firing both would over-issue"
        % (loaded, ammo.GetAvailable())
    )
