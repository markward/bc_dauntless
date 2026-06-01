"""End-to-end: damage a PhaserBank on a Galaxy, confirm the ShipDisplay
panel's _damage_states tuple includes the Weapons row.

Uses direct DamageSystem calls to seed the bank's condition rather than
running _advance_combat ticks. This isolates the project's actual
change (parent aggregation + picker) from shield-charge tuning and
weapon-timing variance. Visual confirmation of the full firing pipeline
is a manual smoke step documented in the spec.
"""
import App
import loadspacehelper

from engine.ui.ship_display_panel import _damage_states


def _build_galaxy():
    App.g_kSetManager._sets.clear()
    ship = loadspacehelper.CreateShip("Galaxy", None, "player", None, 0, 0)
    assert ship is not None
    return ship


def _phaser_banks(ship):
    parent = ship.GetPhaserSystem()
    assert parent is not None, "Galaxy must have a phaser system"
    banks = list(parent._children)
    assert banks, "Galaxy must have at least one mounted phaser bank"
    return banks


def test_damaging_one_phaser_bank_surfaces_weapons_damaged_row():
    ship = _build_galaxy()
    banks = _phaser_banks(ship)
    target_bank = banks[0]
    # Drop the bank into the damaged band: half of MaxCondition, comfortably
    # above the disabled threshold (default DisabledPercentage 0.25).
    seed = target_bank.GetMaxCondition() * 0.5
    ship.DamageSystem(target_bank, seed)

    phasers = ship.GetPhaserSystem()
    assert phasers.IsDamaged() == 1
    assert phasers.IsDisabled() == 0
    assert phasers.IsDestroyed() == 0

    rows = _damage_states(ship)
    assert ("Weapons", "damaged") in rows


def test_disabling_all_phaser_banks_surfaces_weapons_disabled_row():
    ship = _build_galaxy()
    banks = _phaser_banks(ship)
    # Drive every bank below its disabled threshold.
    for bank in banks:
        threshold = bank.GetMaxCondition() * bank.GetDisabledPercentage()
        # Push to half the disabled threshold so we're firmly below it.
        target_condition = max(0.1, threshold * 0.5)
        damage = bank.GetCondition() - target_condition
        ship.DamageSystem(bank, damage)

    phasers = ship.GetPhaserSystem()
    assert phasers.IsDisabled() == 1
    assert phasers.IsDestroyed() == 0

    rows = _damage_states(ship)
    assert ("Weapons", "disabled") in rows


def test_destroying_all_phaser_banks_surfaces_weapons_destroyed_row():
    ship = _build_galaxy()
    banks = _phaser_banks(ship)
    for bank in banks:
        ship.DamageSystem(bank, bank.GetCondition())

    phasers = ship.GetPhaserSystem()
    assert phasers.IsDestroyed() == 1

    rows = _damage_states(ship)
    assert ("Weapons", "destroyed") in rows
