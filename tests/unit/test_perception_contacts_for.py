"""contacts_for answers 'which ships are in this observer's system'."""
from engine.appc import contact_index
from engine.appc.perception import contacts_for
from engine.appc.sets import SetClass
from engine.appc.ships import ShipClass


def _ship(name):
    s = ShipClass()
    s.SetName(name)
    return s


def test_lists_ships_sharing_the_observers_set():
    contact_index.reset()
    pSet = SetClass()
    player, other = _ship("player"), _ship("Galor")
    pSet.AddObjectToSet(player, "player")
    pSet.AddObjectToSet(other, "Galor")

    assert contacts_for(player) == (other,)


def test_excludes_the_observer_itself():
    contact_index.reset()
    pSet = SetClass()
    player = _ship("player")
    pSet.AddObjectToSet(player, "player")

    assert contacts_for(player) == ()


def test_excludes_ships_in_other_systems():
    """The reported bug: QuickBattle spawns into the set the player left."""
    contact_index.reset()
    deep_space, vesuvi = SetClass(), SetClass()
    player, phantom = _ship("player"), _ship("Galor")
    vesuvi.AddObjectToSet(player, "player")
    deep_space.AddObjectToSet(phantom, "Galor")

    assert contacts_for(player) == ()


def test_follows_the_observer_across_a_set_change():
    contact_index.reset()
    deep_space, vesuvi = SetClass(), SetClass()
    player = _ship("player")
    local = _ship("Sovereign")
    deep_space.AddObjectToSet(player, "player")
    vesuvi.AddObjectToSet(local, "Sovereign")

    deep_space.RemoveObjectFromSet("player")
    vesuvi.AddObjectToSet(player, "player")

    assert contacts_for(player) == (local,)


def test_observer_with_no_set_reads_empty():
    contact_index.reset()
    assert contacts_for(_ship("Adrift")) == ()


def test_none_observer_reads_empty():
    contact_index.reset()
    assert contacts_for(None) == ()
