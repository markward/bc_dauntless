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
    return Contact(ship=ship, surface_gu=surface_gu,
                   perceivable=perceivable, targetable=targetable)


def test_perceivable_contact_row_is_visible():
    menu = _menu()
    ship = _ship("Galor")
    menu.set_contacts([_contact(ship)])
    assert menu.GetObjectEntry(ship).IsVisible() == 1


def test_a_row_left_not_visible_comes_back_on_the_next_push():
    """THE reason set_contacts re-asserts SetVisible() on every push.

    Rows are cached per ship in `_row_cache` and REUSED across frames, so a row
    carries whatever visibility state the last caller left on it. `SetNotVisible`
    is real SDK surface on STMenu/STSubsystemMenu and is driven directly against
    a target-list row today (tests/integration/test_target_list_sdk_integration.py
    ::test_sdk_cycle_target_skips_invisible), and SDK CycleTarget
    (TacticalInterfaceHandlers.py:701-730) skips any row whose IsVisible() == 0.
    Without the re-assert, one such call would make a live, perceivable contact
    permanently unselectable — the row is never rebuilt, so nothing would ever
    clear it. Deleting the SetVisible() line must fail HERE.
    """
    menu = _menu()
    ship = _ship("Galor")
    menu.set_contacts([_contact(ship)])

    menu.GetObjectEntry(ship).SetNotVisible()
    assert menu.GetObjectEntry(ship).IsVisible() == 0

    menu.set_contacts([_contact(ship)])  # next frame's push, same cached row

    assert menu.GetObjectEntry(ship).IsVisible() == 1


def test_non_targetable_contact_gets_no_row():
    menu = _menu()
    ship = _ship("Kessok")
    menu.set_contacts([_contact(ship, targetable=False)])
    assert menu.GetNumChildren() == 0


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
