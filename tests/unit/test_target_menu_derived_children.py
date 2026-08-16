"""STTargetMenu children are a projection of the row cache over pushed contacts."""
import App
from engine.appc.ships import ShipClass
from engine.appc.perception import Contact


def _listed(*ships):
    """Contact records for ships the player can see and target — what
    perceived_by returns for an in-range, uncloaked, living contact.

    set_contacts takes perception.Contact records rather than bare ships: the
    record carries the frame's verdict, and the menu derives both the listing
    (`targetable`) and each row's IsVisible (`perceivable`) from it. Distances
    are 0.0 because nothing in this file reads them.
    """
    return [Contact(ship=s, dist_sq_gu=0.0, surface_gu=0.0,
                    perceivable=True, targetable=True) for s in ships]




def _ship(name):
    s = ShipClass()
    s.SetName(name)
    return s


def _menu():
    App._reset_target_menu_singleton()
    return App.STTargetMenu_CreateW("Targets")


def test_pushed_contacts_become_children():
    menu = _menu()
    a, b = _ship("Galor"), _ship("Keldon")

    menu.set_contacts(_listed(a, b))

    assert menu.GetNumChildren() == 2
    assert menu.GetFirstChild().GetShip() is a
    assert menu.GetLastChild().GetShip() is b


def test_children_follow_a_new_push_without_any_clear():
    """The whole point: changing system is a change of answer, not a rebuild."""
    menu = _menu()
    old, new = _ship("Galor"), _ship("Sovereign")
    menu.set_contacts(_listed(old))

    menu.set_contacts(_listed(new))

    assert menu.GetNumChildren() == 1
    assert menu.GetFirstChild().GetShip() is new


def test_row_identity_is_stable_across_pushes():
    """CycleTarget resolves a row then walks siblings from it; a row object
    that changed between calls would break sibling traversal."""
    menu = _menu()
    ship = _ship("Galor")
    menu.set_contacts(_listed(ship))
    first = menu.GetObjectEntry(ship)

    menu.set_contacts(_listed(ship))

    assert menu.GetObjectEntry(ship) is first


def test_row_survives_leaving_and_re_entering_the_contact_list():
    """A warp round-trip must not pay to rebuild subsystem trees."""
    menu = _menu()
    ship = _ship("Galor")
    menu.set_contacts(_listed(ship))
    original = menu.GetObjectEntry(ship)

    menu.set_contacts([])
    menu.set_contacts(_listed(ship))

    assert menu.GetObjectEntry(ship) is original


def test_object_entry_is_none_for_a_ship_outside_the_contact_list():
    """GetObjectEntry must agree with the listing, or CycleTarget could
    select a contact the panel refuses to draw."""
    menu = _menu()
    ship = _ship("Galor")
    menu.set_contacts(_listed(ship))
    menu.set_contacts([])

    assert menu.GetObjectEntry(ship) is None


def test_sibling_traversal_walks_the_projection():
    menu = _menu()
    a, b, c = _ship("A"), _ship("B"), _ship("C")
    menu.set_contacts(_listed(a, b, c))

    first = menu.GetFirstChild()
    second = menu.GetNextChild(first)
    third = menu.GetNextChild(second)

    assert (first.GetShip(), second.GetShip(), third.GetShip()) == (a, b, c)
    assert menu.GetNextChild(third) is None
    assert menu.GetPrevChild(second) is first


def test_rebuild_ship_menu_populates_subsystem_rows():
    """RebuildShipMenu still refreshes a row's subsystem tree — it is real
    SDK surface (MissionLib.HideSubsystems), it just no longer adds a child.

    Asserting on the SUBSYSTEM rows, not merely that the ship row exists:
    set_contacts already guarantees the latter, so a no-op RebuildShipMenu
    would pass that. ShipClass_Create installs the default subsystem set.
    """
    from engine.appc.ships import ShipClass_Create
    menu = _menu()
    ship = ShipClass_Create("Test")
    ship.SetName("Galor")
    menu.set_contacts(_listed(ship))
    row = menu.GetObjectEntry(ship)
    row.KillChildren()
    assert row._children == []

    menu.RebuildShipMenu(ship)

    assert len(row._children) > 0


def test_get_submenu_w_resolves_a_row_by_display_name():
    """SDK: E2M0.py:3692 points a tutorial arrow at a Warbird's target-list row
    by looking it up with GetSubmenuW(<localized display name>)."""
    menu = _menu()
    ship = _ship("Romulan_Warbird1")
    ship.SetDisplayName("Warbird")
    menu.set_contacts(_listed(ship))

    row = menu.GetSubmenuW("Warbird")

    assert row is menu.GetObjectEntry(ship)


def test_get_submenu_w_is_none_for_a_ship_outside_the_contact_list():
    """Must agree with GetObjectEntry: a cached row for a departed ship is
    not a listed row."""
    menu = _menu()
    ship = _ship("Romulan_Warbird1")
    ship.SetDisplayName("Warbird")
    menu.set_contacts(_listed(ship))
    menu.set_contacts([])

    assert menu.GetSubmenuW("Warbird") is None


def test_get_submenu_narrow_variant_resolves_the_same_row():
    """SDK: E1M2.py:6685/6697 use the non-W spelling. STMenu.GetSubmenu
    delegates to GetSubmenuW, so the override must serve both."""
    menu = _menu()
    ship = _ship("Facility")
    menu.set_contacts(_listed(ship))

    assert menu.GetSubmenu("Facility") is menu.GetObjectEntry(ship)
    assert menu.GetSubmenu("NoSuchShip") is None


def test_rebuild_ship_menu_for_a_non_contact_does_not_list_it():
    """MissionLib may refresh a ship in another set; that must not list it."""
    menu = _menu()
    elsewhere = _ship("Faraway")

    menu.RebuildShipMenu(elsewhere)

    assert menu.GetNumChildren() == 0


def test_non_ships_are_ignored():
    from engine.appc.objects import ObjectClass
    menu = _menu()
    menu.set_contacts(_listed(ObjectClass()))
    assert menu.GetNumChildren() == 0


def test_children_attribute_reflects_the_projection():
    """Nothing may bypass the projection by reading _children directly."""
    menu = _menu()
    ship = _ship("Galor")
    menu.set_contacts(_listed(ship))

    assert [c.GetShip() for c in menu._children] == [ship]
