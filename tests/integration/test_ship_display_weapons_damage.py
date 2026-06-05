"""End-to-end: damage a PhaserBank on a Galaxy, confirm the
ShipDisplay panel's damage descriptor list surfaces the per-bank
Phaser row with the right state.

In BC the parent PhaserSystem AND each individual bank can carry a
Position2D. The Galaxy hardpoint sets a Position2D on both
``Phasers`` (the parent system, at 64,94) and every individual bank
(DorsalPhaser1..4, VentralPhaser1..4). So the panel renders:

    * one icon_num=2 (Phaser) row per individual PhaserBank child,
      at each bank's own hardpoint coord, and
    * one icon_num=6 (System fallback) row for the parent
      PhaserSystem at (64, 94) — the parent is not in the icon
      class table so it falls through to "System".

Damaging a single bank flips that bank's row to "damaged" and the
parent system's IsDamaged() predicate true. Disabling/destroying
every bank flips every bank row AND the parent row to
"disabled" / "destroyed".

Spec: docs/superpowers/plans/2026-06-05-ship-display-damage-hardpoint.md
"""
import App
import loadspacehelper

from engine.ui.ship_display_panel import _damage_icon_descriptors

PHASER_ICON_NUM = 2   # DamageIcons enum: Phaser (individual bank)
SYSTEM_ICON_NUM = 6   # DamageIcons enum: System (PhaserSystem parent fallback)


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


def _phaser_rows(ship):
    return [r for r in _damage_icon_descriptors(ship)
            if r["icon_num"] == PHASER_ICON_NUM]


def _parent_phaser_row(ship):
    """Locate the parent PhaserSystem row by matching the Galaxy
    hardpoint's Position2D for ``Phasers`` (64, 94). Returns None if
    no such row is present."""
    for r in _damage_icon_descriptors(ship):
        if r["icon_num"] == SYSTEM_ICON_NUM and r["x_px"] == 64.0 and r["y_px"] == 94.0:
            return r
    return None


def test_damaging_one_phaser_bank_surfaces_damaged_phaser_row():
    ship = _build_galaxy()
    banks = _phaser_banks(ship)
    target_bank = banks[0]
    # Pin the disabled-percentage to the current (default) value. The
    # Galaxy hardpoint script (sdk/.../Hardpoints/galaxy.py) calls
    # SetDisabledPercentage(0.75) on every phaser bank property, but
    # engine/appc/ships.py Pass 4 doesn't copy that field through to
    # the child PhaserBank — so bank.GetDisabledPercentage() returns
    # the ShipSubsystem default 0.25 here. If/when that propagation
    # gap is closed, this assertion fails loudly and the seed value
    # below needs to be revisited (max_condition * 0.5 would land
    # below a 0.75 threshold, flipping IsDisabled() to 1).
    assert target_bank.GetDisabledPercentage() == 0.25
    # Drop the bank into the damaged band: half of MaxCondition,
    # comfortably above the disabled threshold (default
    # DisabledPercentage 0.25).
    seed = target_bank.GetMaxCondition() * 0.5
    ship.DamageSystem(target_bank, seed)

    rows = _phaser_rows(ship)
    damaged = [r for r in rows if r["state"] == "damaged"]
    assert len(damaged) >= 1, (
        "Damaging a bank must surface at least one damaged Phaser row"
    )

    # Parent PhaserSystem row reflects aggregate IsDamaged().
    parent = ship.GetPhaserSystem()
    assert parent.IsDamaged() == 1
    assert parent.IsDisabled() == 0
    assert parent.IsDestroyed() == 0
    parent_row = _parent_phaser_row(ship)
    assert parent_row is not None, (
        "Galaxy hardpoint sets Phasers.SetPosition2D(64, 94); "
        "parent row must surface"
    )
    assert parent_row["state"] == "damaged"


def test_disabling_all_phaser_banks_surfaces_disabled_phaser_rows():
    ship = _build_galaxy()
    banks = _phaser_banks(ship)
    # Drive every bank below its disabled threshold.
    for bank in banks:
        threshold = bank.GetMaxCondition() * bank.GetDisabledPercentage()
        # Push to half the disabled threshold so we're firmly below it.
        # Floor above zero so the bank doesn't tip into IsDestroyed.
        target_condition = max(0.1, threshold * 0.5)
        damage = bank.GetCondition() - target_condition
        ship.DamageSystem(bank, damage)

    rows = _phaser_rows(ship)
    assert rows, "Galaxy must surface per-bank Phaser rows"
    assert all(r["state"] == "disabled" for r in rows), (
        "Every Phaser row must be disabled when every bank is below threshold"
    )

    # Parent PhaserSystem row reflects aggregate IsDisabled().
    parent = ship.GetPhaserSystem()
    assert parent.IsDisabled() == 1
    assert parent.IsDestroyed() == 0
    parent_row = _parent_phaser_row(ship)
    assert parent_row is not None
    assert parent_row["state"] == "disabled"


def test_destroying_all_phaser_banks_surfaces_destroyed_phaser_rows():
    ship = _build_galaxy()
    banks = _phaser_banks(ship)
    for bank in banks:
        ship.DamageSystem(bank, bank.GetCondition())

    rows = _phaser_rows(ship)
    assert rows
    assert all(r["state"] == "destroyed" for r in rows)

    # Parent PhaserSystem row reflects aggregate IsDestroyed().
    parent = ship.GetPhaserSystem()
    assert parent.IsDestroyed() == 1
    assert parent.IsDisabled() == 1   # destroyed children are also disabled
    assert parent.IsDamaged() == 1    # destroyed children also mark damaged
    parent_row = _parent_phaser_row(ship)
    assert parent_row is not None
    assert parent_row["state"] == "destroyed"
