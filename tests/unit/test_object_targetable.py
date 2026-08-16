"""Object-level targetable — missions hide a contact until a reveal beat."""
from engine.appc import contact_index
from engine.appc.objects import ObjectClass
from engine.appc.perception import contacts_for
from engine.appc.sets import SetClass
from engine.appc.ships import ShipClass


def _ship(name):
    s = ShipClass()
    s.SetName(name)
    return s


def test_objects_are_targetable_by_default():
    """The vast majority of SDK ships never touch the flag, so the default
    must be the one that makes targeting work without opting in — the same
    reasoning that settled _scannable."""
    assert ObjectClass().IsTargetable() == 1


def test_ships_are_targetable_by_default():
    assert _ship("Galor").IsTargetable() == 1


def test_set_targetable_zero_clears_the_flag():
    ship = _ship("Kessok")
    ship.SetTargetable(0)
    assert ship.IsTargetable() == 0


def test_set_targetable_round_trips():
    ship = _ship("Kessok")
    ship.SetTargetable(0)
    ship.SetTargetable(1)
    assert ship.IsTargetable() == 1


def test_sdk_false_constant_is_accepted():
    """E3M1.py:1695 passes FALSE, E6M4.py:1932 passes 0 — both must work."""
    ship = _ship("Amagon")
    ship.SetTargetable(False)
    assert ship.IsTargetable() == 0


def test_non_targetable_ship_is_not_a_contact():
    contact_index.reset()
    pSet = SetClass()
    player, hidden = _ship("player"), _ship("Kessok")
    pSet.AddObjectToSet(player, "player")
    pSet.AddObjectToSet(hidden, "Kessok")
    hidden.SetTargetable(0)

    assert contacts_for(player) == ()


def test_revealing_a_ship_makes_it_a_contact_again():
    """E6M4.py:2094 flips it back on the reveal beat. Because membership is
    derived, the next query picks it up with no rebuild and no event."""
    contact_index.reset()
    pSet = SetClass()
    player, hidden = _ship("player"), _ship("Kessok")
    pSet.AddObjectToSet(player, "player")
    pSet.AddObjectToSet(hidden, "Kessok")
    hidden.SetTargetable(0)
    assert contacts_for(player) == ()

    hidden.SetTargetable(1)

    assert contacts_for(player) == (hidden,)
