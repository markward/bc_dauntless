"""Science's "Scan Object" buttons must not leak an unidentified contact's
real name.

Bridge/ScienceMenuHandlers.CreateScanButton labels a button with
pObject.GetDisplayName() -- on BOTH ET_TARGET_LIST_OBJECT_ADDED (a contact
becoming targetable, independent of sensor identification) and
ET_SENSORS_SHIP_IDENTIFIED. Without engine.appc.science_scan_labels wrapping
CreateScanButton/ExitedSet, the FIRST of those shows an unidentified ship's
true name the moment it's targetable -- the leak sensor-tiers spec Sec6 closes.

Drives the real SDK handlers (via LoadBridge.Load -> CreateMenus), exactly
as tests/integration/test_science_scan_menu_removal.py does, so this proves
the wrap reaches live event dispatch rather than re-implementing the SDK's
own logic.
"""
import sys

import pytest

import App
import LoadBridge
from engine.appc.windows import TacticalControlWindow
from engine.appc.target_menu import _reset_target_menu_singleton
from engine.appc.tg_ui import st_widgets
from engine.appc.ships import ShipClass_Create
from engine.appc import science_scan_labels, sensor_contacts, unknown_labels
from engine.core.game import Game, Episode, Mission, _set_current_game


SCAN_MENU = "Scan Object"


@pytest.fixture
def world():
    """The live Science -> Scan Object submenu plus a player with a sensor
    subsystem, wrapped by science_scan_labels.install(). Mirrors
    test_science_scan_menu_removal.py's scan_menu fixture."""
    TacticalControlWindow._instance = None
    _reset_target_menu_singleton()
    st_widgets._reset_module_state()
    App.g_kSetManager._sets.clear()
    App.g_kEventManager._broadcast_handlers.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()
    unknown_labels.reset()
    sensor_contacts.reset()
    game, ep, mission = Game(), Episode(), Mission()
    ep.SetCurrentMission(mission)
    game.SetCurrentEpisode(ep)
    _set_current_game(game)
    for name in list(sys.modules):
        if name.startswith("Bridge.") and "StubModule" in type(sys.modules[name]).__name__:
            sys.modules.pop(name)
    try:
        LoadBridge.Load("GalaxyBridge")
        # A player DISTINCT from the scanned object, with a real sensor
        # subsystem (ShipClass_Create furnishes one; a bare ShipClass() does
        # not) -- player_knows()/AddKnownObject/ForceObjectIdentified all
        # need it.
        player = ShipClass_Create("Dauntless")
        player.SetName("Dauntless")
        game.SetPlayer(player)
        science_scan_labels.install()
        db = App.g_kLocalizationManager.Load("data/TGL/Bridge Menus.tgl")
        science = TacticalControlWindow.GetInstance().FindMenu(db.GetString("Science"))
        menu = science.GetSubmenuW(db.GetString(SCAN_MENU))
        App.g_kLocalizationManager.Unload(db)
        assert menu is not None, "Science -> Scan Object submenu was not built"
        pSet = App.SetClass_Create()
        App.g_kSetManager.AddSet(pSet, "TestSet")
        pSet.AddObjectToSet(player, "player")
        yield player, pSet, menu
    finally:
        _set_current_game(None)
        unknown_labels.reset()
        sensor_contacts.reset()


def _labels(menu):
    return [c.GetLabel() for c in menu._children]


def _unknown_ship(name):
    ship = ShipClass_Create(name)
    ship.SetName(name)
    return ship


def _post_target_list_added(obj):
    """Mirror engine.appc.target_menu._post_membership: a contact becoming
    targetable posts ET_TARGET_LIST_OBJECT_ADDED with destination=obj,
    independent of whether sensors have identified it."""
    evt = App.TGEvent_Create()
    evt.SetEventType(App.ET_TARGET_LIST_OBJECT_ADDED)
    evt.SetDestination(obj)
    App.g_kEventManager.AddEvent(evt)


def test_unknown_contact_gets_a_placeholder_scan_button(world):
    player, pSet, menu = world
    bird = _unknown_ship("Vagabond")
    pSet.AddObjectToSet(bird, "Vagabond")

    assert sensor_contacts.player_knows(bird) is False
    _post_target_list_added(bird)

    assert menu.GetButtonW("Unknown 1") is not None
    assert menu.GetButtonW(bird.GetDisplayName()) is None
    assert _labels(menu) == ["Unknown 1"]


def test_identification_renames_the_button_without_a_duplicate(world):
    player, pSet, menu = world
    bird = _unknown_ship("Vagabond")
    pSet.AddObjectToSet(bird, "Vagabond")
    _post_target_list_added(bird)
    assert _labels(menu) == ["Unknown 1"]

    sensors = player.GetSensorSubsystem()
    sensors.ForceObjectIdentified(bird)

    assert _labels(menu) == ["Vagabond"]
    assert menu.GetButtonW("Vagabond") is not None
    assert menu.GetButtonW("Unknown 1") is None


def test_exit_set_removes_the_placeholder_button(world):
    player, pSet, menu = world
    bird = _unknown_ship("Vagabond")
    pSet.AddObjectToSet(bird, "Vagabond")
    _post_target_list_added(bird)
    assert menu.GetButtonW("Unknown 1") is not None

    pSet.RemoveObjectFromSet("Vagabond")

    assert menu.GetButtonW("Unknown 1") is None
    assert _labels(menu) == []


def test_two_unknowns_get_two_buttons(world):
    player, pSet, menu = world
    birdA = _unknown_ship("Drone")
    birdB = _unknown_ship("Drone")
    # Distinct set identifiers (AddObjectToSet keys _objects by identifier),
    # but the SAME display name -- SetName above overwrote it to the
    # identifier, so restore it to prove the two placeholders are keyed by
    # the OBJECT, not its (shared) name.
    pSet.AddObjectToSet(birdA, "DroneA")
    birdA.SetDisplayName("Drone")
    pSet.AddObjectToSet(birdB, "DroneB")
    birdB.SetDisplayName("Drone")

    _post_target_list_added(birdA)
    _post_target_list_added(birdB)

    assert _labels(menu) == ["Unknown 1", "Unknown 2"]
    assert menu.GetButtonW("Drone") is None


def test_known_contact_uses_its_real_name(world):
    player, pSet, menu = world
    bird = _unknown_ship("Vagabond")
    pSet.AddObjectToSet(bird, "Vagabond")

    sensors = player.GetSensorSubsystem()
    sensors.AddKnownObject(bird)
    assert sensor_contacts.player_knows(bird) is True

    _post_target_list_added(bird)

    assert _labels(menu) == ["Vagabond"]
    assert menu.GetButtonW("Vagabond") is not None
    assert menu.GetButtonW("Unknown 1") is None


def test_install_is_wired_after_mission_load():
    """engine.host_loop._init_mission must leave Bridge.ScienceMenuHandlers
    wrapped -- the wrap lives at _bootstrap_firing_pipeline (process boot) and
    the end of _reset_sensor_state (every mission (re)load), covering both a
    cold process and a later swap that re-imports the SDK module."""
    from engine import host_loop
    from tests.integration.test_sdk_bridge_load import _fresh_world

    _fresh_world()
    host_loop._init_mission("Maelstrom.Episode1.E1M2.E1M2")

    import Bridge.ScienceMenuHandlers as smh
    assert getattr(smh.CreateScanButton, "_unknown_labelled", False) is True
    assert getattr(smh.ExitedSet, "_unknown_labelled", False) is True
