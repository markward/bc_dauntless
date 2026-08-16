"""SetClass keeps the ContactIndex in step with real set membership."""
from engine.appc import contact_index
from engine.appc.sets import SetClass
from engine.appc.ships import ShipClass


def _ship(name):
    s = ShipClass()
    s.SetName(name)
    return s


def test_add_object_to_set_indexes_the_ship():
    contact_index.reset()
    pSet = SetClass()
    ship = _ship("Dauntless")

    pSet.AddObjectToSet(ship, "Dauntless")

    assert contact_index.ships_in(pSet) == (ship,)


def test_remove_object_from_set_deindexes_the_ship():
    contact_index.reset()
    pSet = SetClass()
    ship = _ship("Dauntless")
    pSet.AddObjectToSet(ship, "Dauntless")

    pSet.RemoveObjectFromSet("Dauntless")

    assert contact_index.ships_in(pSet) == ()


def test_delete_object_from_set_deindexes_the_ship():
    contact_index.reset()
    pSet = SetClass()
    ship = _ship("Dauntless")
    pSet.AddObjectToSet(ship, "Dauntless")

    pSet.DeleteObjectFromSet("Dauntless")

    assert contact_index.ships_in(pSet) == ()


def test_moving_a_ship_between_sets_moves_its_bucket_entry():
    """The warp path removes from the source set then adds to the
    destination (warp.py:344). The index must follow."""
    contact_index.reset()
    deep_space = SetClass()
    vesuvi = SetClass()
    ship = _ship("Dauntless")
    deep_space.AddObjectToSet(ship, "Dauntless")

    deep_space.RemoveObjectFromSet("Dauntless")
    vesuvi.AddObjectToSet(ship, "Dauntless")

    assert contact_index.ships_in(deep_space) == ()
    assert contact_index.ships_in(vesuvi) == (ship,)


def test_non_ship_set_members_are_not_indexed():
    from engine.appc.objects import ObjectClass
    contact_index.reset()
    pSet = SetClass()

    pSet.AddObjectToSet(ObjectClass(), "waypoint1")

    assert contact_index.ships_in(pSet) == ()
