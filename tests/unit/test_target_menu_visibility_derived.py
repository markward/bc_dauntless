"""Row visibility is derived from the pushed Contact records, not written
by a separate pass.

The menu also RETAINS the records: Stage-3's later readers (range readouts,
radar) need `surface_gu` for a listed contact, and recomputing it would
reintroduce the duplicate distance pass this stage exists to delete.
"""
import App
from engine.appc.perception import Contact
from engine.appc.ships import ShipClass


def _ship(name):
    s = ShipClass()
    s.SetName(name)
    return s


def _menu():
    App._reset_target_menu_singleton()
    return App.STTargetMenu_CreateW("Targets")


def _contact(ship, perceivable=True, targetable=True, surface_gu=10.0):
    return Contact(ship=ship, dist_sq_gu=100.0, surface_gu=surface_gu,
                   perceivable=perceivable, targetable=targetable)


def test_perceivable_contact_row_is_visible():
    menu = _menu()
    ship = _ship("Galor")
    menu.set_contacts([_contact(ship)])
    assert menu.GetObjectEntry(ship).IsVisible() == 1


def test_unperceivable_contact_row_is_not_visible():
    """SDK CycleTarget skips rows where IsVisible() is 0, so an out-of-range
    contact must not be Tab-selectable."""
    menu = _menu()
    ship = _ship("Faraway")
    menu.set_contacts([_contact(ship, perceivable=False)])
    row = menu.GetObjectEntry(ship)
    assert row is not None
    assert row.IsVisible() == 0


def test_non_targetable_contact_gets_no_row():
    menu = _menu()
    ship = _ship("Kessok")
    menu.set_contacts([_contact(ship, targetable=False)])
    assert menu.GetNumChildren() == 0


def test_visibility_follows_a_later_push():
    menu = _menu()
    ship = _ship("Galor")
    menu.set_contacts([_contact(ship, perceivable=True)])
    assert menu.GetObjectEntry(ship).IsVisible() == 1

    menu.set_contacts([_contact(ship, perceivable=False)])

    assert menu.GetObjectEntry(ship).IsVisible() == 0


# ── Record retention ─────────────────────────────────────────────────────────

def test_contact_for_returns_the_pushed_record():
    """Readers migrating off their own distance maths need the record that was
    pushed, not a second perception query."""
    menu = _menu()
    ship = _ship("Galor")
    menu.set_contacts([_contact(ship, surface_gu=42.5)])

    got = menu.contact_for(ship)

    assert isinstance(got, Contact)
    assert got.ship is ship
    assert got.surface_gu == 42.5


def test_contact_for_is_none_for_a_ship_outside_the_contact_list():
    menu = _menu()
    ship = _ship("Galor")
    menu.set_contacts([_contact(ship)])
    menu.set_contacts([])

    assert menu.contact_for(ship) is None


def test_contact_for_serves_a_listed_but_unperceivable_contact():
    """A row that exists but is not drawable still has a record — the
    unperceivable case is exactly where a reader must not fall back to its own
    arithmetic."""
    menu = _menu()
    ship = _ship("Faraway")
    menu.set_contacts([_contact(ship, perceivable=False, surface_gu=9000.0)])

    assert menu.contact_for(ship).surface_gu == 9000.0


def test_object_entry_is_none_for_a_ship_outside_the_contact_list():
    """GetObjectEntry now scans records, not ships; its old semantics must
    survive that — a listed ship returns its row, anything else None."""
    menu = _menu()
    listed, stranger = _ship("Galor"), _ship("Keldon")
    menu.set_contacts([_contact(listed)])

    assert menu.GetObjectEntry(listed) is not None
    assert menu.GetObjectEntry(stranger) is None
