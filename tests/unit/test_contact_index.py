"""ContactIndex buckets ShipClass objects by the set that contains them."""
from engine.appc import contact_index
from engine.appc.sets import SetClass
from engine.appc.ships import ShipClass


def _ship(name):
    s = ShipClass()
    s.SetName(name)
    return s


def _add(pSet, ship):
    """What _add(pSet, ship) used to be: the one door in."""
    pSet.AddObjectToSet(ship, ship.GetName())


def test_added_ship_appears_in_its_set_bucket():
    contact_index.reset()
    pSet = SetClass()
    ship = _ship("Dauntless")

    _add(pSet, ship)

    assert contact_index.ships_in(pSet) == (ship,)


def test_removed_ship_leaves_the_bucket():
    contact_index.reset()
    pSet = SetClass()
    ship = _ship("Dauntless")
    _add(pSet, ship)

    pSet.RemoveObjectFromSet("Dauntless")

    assert contact_index.ships_in(pSet) == ()


def test_buckets_are_independent():
    contact_index.reset()
    deep_space = SetClass()
    vesuvi = SetClass()
    a, b = _ship("A"), _ship("B")

    _add(deep_space, a)
    _add(vesuvi, b)

    assert contact_index.ships_in(deep_space) == (a,)
    assert contact_index.ships_in(vesuvi) == (b,)


def test_insertion_order_is_preserved():
    contact_index.reset()
    pSet = SetClass()
    a, b, c = _ship("A"), _ship("B"), _ship("C")

    for s in (a, b, c):
        _add(pSet, s)

    assert contact_index.ships_in(pSet) == (a, b, c)


def test_non_ships_never_enter_a_bucket():
    """Waypoints, grids, planets and the bridge-interior ObjectClass are not
    contacts. Filtering at insert means no read-time type test is needed."""
    from engine.appc.objects import ObjectClass
    contact_index.reset()
    pSet = SetClass()
    not_a_ship = ObjectClass()

    pSet.AddObjectToSet(not_a_ship, "Waypoint")

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

    _add(pSet, ship)
    _add(pSet, ship)

    assert contact_index.ships_in(pSet) == (ship,)


def test_remove_of_absent_ship_is_silent():
    contact_index.reset()
    pSet = SetClass()
    pSet.RemoveObjectFromSet("Ghost")  # must not raise
    assert contact_index.ships_in(pSet) == ()


def test_reset_clears_every_bucket():
    contact_index.reset()
    pSet = SetClass()
    _add(pSet, _ship("Dauntless"))

    contact_index.reset()

    assert contact_index.ships_in(pSet) == ()


def test_ship_positions_in_matches_individual_reads_in_order():
    contact_index.reset()
    pSet = SetClass()
    a, b, c = _ship("A"), _ship("B"), _ship("C")
    a.SetTranslateXYZ(1.0, 2.0, 3.0)
    b.SetTranslateXYZ(-4.0, 0.0, 8.5)
    c.SetTranslateXYZ(0.0, 0.0, 0.0)
    for s in (a, b, c):
        _add(pSet, s)

    result = contact_index.ship_positions_in(pSet)

    assert tuple(ship for ship, _ in result) == (a, b, c)
    for ship, pos in result:
        got = ship.GetTranslate()
        assert pos == (got.x, got.y, got.z)


def test_ship_positions_in_empty_set_is_empty():
    contact_index.reset()
    assert contact_index.ship_positions_in(SetClass()) == ()


def test_ship_positions_in_is_one_native_call_with_unchanged_values(monkeypatch):
    from engine.appc.transform_store import get_store
    contact_index.reset()
    pSet = SetClass()
    ships = [_ship(n) for n in ("A", "B", "C")]
    for i, s in enumerate(ships):
        s.SetTranslateXYZ(i + 0.1, -2.5 * i, 7.0 / 3.0)
        _add(pSet, s)
    pSet.AddObjectToSet(ships[0], "AAgain")  # a duplicate entry

    store = get_store()
    reference = tuple(zip(ships, store.get_positions([s._xform for s in ships])))

    def boom(self, handles):
        raise AssertionError("the Python get_positions was called")

    monkeypatch.setattr(type(store), "get_positions", boom)
    got = contact_index.ship_positions_in(pSet)

    assert got == reference
    assert all(type(p) is tuple and all(type(v) is float for v in p)
               for _, p in got)


def test_ship_positions_in_stale_handle_raises_like_get_positions():
    from engine.appc.transform_store import StaleHandleError, get_store
    contact_index.reset()
    pSet = SetClass()
    s = _ship("Stale")
    _add(pSet, s)
    get_store().free(*s._xform)
    import pytest
    with pytest.raises(StaleHandleError):
        contact_index.ship_positions_in(pSet)
