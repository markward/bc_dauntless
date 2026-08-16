"""The target list tracks the player's current system, both directions.

Reported live 2026-08-16: ships loaded in QuickBattle after warping to another
system appeared in the target list despite being spawned into the set the
player had left.
"""
import App
from engine.appc import contact_index
from engine.appc.perception import contacts_for
from engine.appc.sets import SetClass
from engine.appc.ships import ShipClass


def _ship(name):
    s = ShipClass()
    s.SetName(name)
    return s


def _menu():
    App._reset_target_menu_singleton()
    return App.STTargetMenu_CreateW("Targets")


def _pump(menu, player):
    """One frame of the host loop's contact push."""
    menu.set_contacts(contacts_for(player))


def test_ships_spawned_into_the_departed_system_do_not_appear():
    contact_index.reset()
    menu = _menu()
    deep_space, vesuvi = SetClass(), SetClass()
    player = _ship("player")

    deep_space.AddObjectToSet(player, "player")
    _pump(menu, player)

    # Warp: the player moves to Vesuvi.
    deep_space.RemoveObjectFromSet("player")
    vesuvi.AddObjectToSet(player, "player")
    _pump(menu, player)

    # QuickBattle spawns into g_pSet, still pointing at Deep Space.
    deep_space.AddObjectToSet(_ship("Galor"), "Galor")
    _pump(menu, player)

    assert menu.GetNumChildren() == 0


def test_ships_already_in_the_destination_system_do_appear():
    """The other half of the same fault: the old subscription stayed bound to
    the departed set, so arriving contacts got no rows at all."""
    contact_index.reset()
    menu = _menu()
    deep_space, vesuvi = SetClass(), SetClass()
    player = _ship("player")
    resident = _ship("Sovereign")

    deep_space.AddObjectToSet(player, "player")
    vesuvi.AddObjectToSet(resident, "Sovereign")
    _pump(menu, player)
    assert menu.GetNumChildren() == 0

    deep_space.RemoveObjectFromSet("player")
    vesuvi.AddObjectToSet(player, "player")
    _pump(menu, player)

    assert menu.GetNumChildren() == 1
    assert menu.GetFirstChild().GetShip() is resident


def test_ship_spawned_into_the_players_current_system_appears():
    """The positive half of the bug: membership is re-read every frame, so a
    mid-mission spawn into the player's own set is listed on the next push
    with no subscription and no rebuild."""
    contact_index.reset()
    menu = _menu()
    pSet = SetClass()
    player = _ship("player")
    pSet.AddObjectToSet(player, "player")
    _pump(menu, player)
    assert menu.GetNumChildren() == 0

    pSet.AddObjectToSet(_ship("Galor"), "Galor")
    _pump(menu, player)

    assert menu.GetNumChildren() == 1
    assert menu.GetFirstChild().GetShip().GetName() == "Galor"


def test_warp_transit_empties_the_list_with_no_explicit_clear():
    """Mid-warp the player is alone in _WarpTransit, so the list empties
    itself — this is the test of whether the derived model is right."""
    from engine.appc.warp import _WARP_TRANSIT_SET_NAME
    contact_index.reset()
    menu = _menu()
    deep_space = SetClass()
    transit = SetClass()
    transit.SetName(_WARP_TRANSIT_SET_NAME)
    player = _ship("player")

    deep_space.AddObjectToSet(player, "player")
    deep_space.AddObjectToSet(_ship("Galor"), "Galor")
    _pump(menu, player)
    assert menu.GetNumChildren() == 1

    deep_space.RemoveObjectFromSet("player")
    transit.AddObjectToSet(player, "player")
    _pump(menu, player)

    assert menu.GetNumChildren() == 0
