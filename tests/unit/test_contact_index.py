"""ContactIndex buckets ShipClass objects by the set that contains them."""
from engine.appc import contact_index
from engine.appc.sets import SetClass
from engine.appc.ships import ShipClass


def _ship(name):
    s = ShipClass()
    s.SetName(name)
    return s


def test_added_ship_appears_in_its_set_bucket():
    contact_index.reset()
    pSet = SetClass()
    ship = _ship("Dauntless")

    contact_index.on_added(pSet, ship)

    assert contact_index.ships_in(pSet) == (ship,)


def test_removed_ship_leaves_the_bucket():
    contact_index.reset()
    pSet = SetClass()
    ship = _ship("Dauntless")
    contact_index.on_added(pSet, ship)

    contact_index.on_removed(pSet, ship)

    assert contact_index.ships_in(pSet) == ()


def test_buckets_are_independent():
    contact_index.reset()
    deep_space = SetClass()
    vesuvi = SetClass()
    a, b = _ship("A"), _ship("B")

    contact_index.on_added(deep_space, a)
    contact_index.on_added(vesuvi, b)

    assert contact_index.ships_in(deep_space) == (a,)
    assert contact_index.ships_in(vesuvi) == (b,)


def test_insertion_order_is_preserved():
    contact_index.reset()
    pSet = SetClass()
    a, b, c = _ship("A"), _ship("B"), _ship("C")

    for s in (a, b, c):
        contact_index.on_added(pSet, s)

    assert contact_index.ships_in(pSet) == (a, b, c)


def test_non_ships_never_enter_a_bucket():
    """Waypoints, grids, planets and the bridge-interior ObjectClass are not
    contacts. Filtering at insert means no read-time type test is needed."""
    from engine.appc.objects import ObjectClass
    contact_index.reset()
    pSet = SetClass()
    not_a_ship = ObjectClass()

    contact_index.on_added(pSet, not_a_ship)

    assert contact_index.ships_in(pSet) == ()


def test_unknown_set_reads_empty():
    contact_index.reset()
    assert contact_index.ships_in(SetClass()) == ()


def test_double_add_does_not_duplicate():
    """AddObjectToSet is called again when a mission re-registers a ship
    under the same identifier; the bucket must not grow a second entry."""
    contact_index.reset()
    pSet = SetClass()
    ship = _ship("Dauntless")

    contact_index.on_added(pSet, ship)
    contact_index.on_added(pSet, ship)

    assert contact_index.ships_in(pSet) == (ship,)


def test_remove_of_absent_ship_is_silent():
    contact_index.reset()
    pSet = SetClass()
    contact_index.on_removed(pSet, _ship("Ghost"))  # must not raise
    assert contact_index.ships_in(pSet) == ()


def test_reset_clears_every_bucket():
    contact_index.reset()
    pSet = SetClass()
    contact_index.on_added(pSet, _ship("Dauntless"))

    contact_index.reset()

    assert contact_index.ships_in(pSet) == ()
