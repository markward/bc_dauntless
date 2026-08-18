from engine.appc.ships import ShipClass_Create
from engine.appc.properties import (
    WeaponSystemProperty, PhaserProperty, EngineProperty,
)
from engine.appc.target_menu import STTargetMenu
from engine.appc.perception import Contact


def _listed(*ships):
    """Contact records for ships the player can see and target — what
    perceived_by returns for an in-range, uncloaked, living contact.

    set_contacts takes perception.Contact records rather than bare ships: the
    record carries the frame's verdict, and the menu derives the listing from
    `targetable`. Row IsVisible is NOT derived from `perceivable` — set_contacts
    asserts SetVisible() on every listed row, so that flag answers nothing about
    detectability; readers that need it read `perceivable` off the record.
    The distance is 0.0 because nothing in this file reads it.
    """
    return [Contact(ship=s, surface_gu=0.0,
                    perceivable=True, targetable=True) for s in ships]




def _build_ship():
    ship = ShipClass_Create("X")
    ps = ship.GetPropertySet()
    phasers = WeaponSystemProperty("Phasers")
    phasers.SetWeaponSystemType(WeaponSystemProperty.WST_PHASER)
    ps.AddToSet("Scene Root", phasers)
    ps.AddToSet("Scene Root", PhaserProperty("Dorsal Phaser 1"))
    ps.AddToSet("Scene Root", PhaserProperty("Dorsal Phaser 2"))
    imp = EngineProperty("Port Impulse")
    imp.SetEngineType(EngineProperty.EP_IMPULSE)
    ps.AddToSet("Scene Root", imp)
    ship.SetupProperties()
    return ship


def test_phaser_row_has_two_child_rows():
    menu = STTargetMenu("targets")
    ship = _build_ship()
    menu.set_contacts(_listed(ship))
    row = menu.GetObjectEntry(ship)        # the per-ship STSubsystemMenu
    labels = [c.GetLabel() for c in row._children]
    assert "Phasers" in labels
    phaser_row = next(c for c in row._children if c.GetLabel() == "Phasers")
    child_labels = sorted(gc.GetLabel() for gc in phaser_row._children)
    assert child_labels == ["Dorsal Phaser 1", "Dorsal Phaser 2"]


# ── Non-targetable aggregators are GROUP HEADERS, not deletions ───────────────
#
# Every aggregator in BC's hardpoints is SetTargetable(0) — "Warp Engines",
# "Phasers", "Torpedoes", "Impulse Engines", "Tractors" (49/52 WeaponSystem,
# 23/24 WarpEngine, 28/29 ImpulseEngine across the 52 hardpoint files). The
# flag means "the player cannot LOCK this", not "do not display it": the
# leaves under it are individually targetable and BC listed them grouped.
#
# The test above passes without this rule only because its synthetic
# WeaponSystemProperty keeps the default targetable=1, which no real
# hardpoint does.

def _build_ship_bc_faithful():
    """Same ship, but with the aggregator flagged the way every real
    hardpoint flags it: SetTargetable(0) on the group, 1 on the leaves."""
    ship = ShipClass_Create("X")
    ps = ship.GetPropertySet()
    phasers = WeaponSystemProperty("Phasers")
    phasers.SetWeaponSystemType(WeaponSystemProperty.WST_PHASER)
    phasers.SetTargetable(0)                      # ← as galaxy.py does
    ps.AddToSet("Scene Root", phasers)
    for nm in ("Dorsal Phaser 1", "Dorsal Phaser 2"):
        leaf = PhaserProperty(nm)
        leaf.SetTargetable(1)
        ps.AddToSet("Scene Root", leaf)
    ship.SetupProperties()
    return ship


def test_non_targetable_aggregator_still_groups_its_targetable_children():
    menu = STTargetMenu("targets")
    ship = _build_ship_bc_faithful()
    menu.set_contacts(_listed(ship))
    row = menu.GetObjectEntry(ship)
    labels = [c.GetLabel() for c in row._children]
    # The group header survives...
    assert "Phasers" in labels
    # ...and the leaves are nested UNDER it, not promoted to the top level.
    assert "Dorsal Phaser 1" not in labels
    phaser_row = next(c for c in row._children if c.GetLabel() == "Phasers")
    assert sorted(gc.GetLabel() for gc in phaser_row._children) == [
        "Dorsal Phaser 1", "Dorsal Phaser 2",
    ]


def test_non_targetable_leaf_with_no_targetable_descendant_is_dropped():
    """The asteroid rule still holds: a non-targetable subsystem with nothing
    targetable beneath it is not a group header, it is simply absent."""
    ship = ShipClass_Create("Y")
    ps = ship.GetPropertySet()
    dead = WeaponSystemProperty("Tractors")
    dead.SetWeaponSystemType(WeaponSystemProperty.WST_TRACTOR)
    dead.SetTargetable(0)                         # no children at all
    ps.AddToSet("Scene Root", dead)
    ship.SetupProperties()

    menu = STTargetMenu("targets")
    menu.set_contacts(_listed(ship))
    row = menu.GetObjectEntry(ship)
    assert "Tractors" not in [c.GetLabel() for c in row._children]
