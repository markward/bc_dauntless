"""Helm "Orbit Planet" submenu population (Layer 2).

Exercises the real SDK Bridge/HelmMenuHandlers population path end-to-end:

  - SetupOrbitMenuFromSet iterates GetClassObjectList(CT_PLANET) (planets AND
    suns, since Sun(Planet)) and filters suns with pPlanet.IsTypeOf(CT_SUN) —
    so a planet gets a button, a sun does not. Without ObjectClass.IsTypeOf the
    check hit a truthy _Stub and every planet was skipped (empty menu).
  - Game.SetPlayer fires ET_SET_PLAYER, which the SDK's OrbitMenuPlayerChanged
    broadcast handler uses to repopulate from the player's set. At mission load
    the player does not exist when the menu handlers are registered, so this is
    the event that actually fills the menu.
"""
import App
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import SensorSubsystem
from engine.appc.sets import SetClass
from engine.appc.planet import Planet_Create, Sun_Create
from engine.core.game import Game, _set_current_game
import Bridge.HelmMenuHandlers as H


def _player_and_set():
    """A player ship with sensors, set as current player, whose containing set
    holds a planet "Haven" and a sun "Vesuvi"."""
    s = SetClass()
    player = ShipClass_Create("Galaxy")
    sensors = SensorSubsystem("Sensors")
    sensors._condition = 100.0
    sensors._max_condition = 100.0
    sensors.SetBaseSensorRange(5000.0)
    player.SetSensorSubsystem(sensors)
    s.AddObjectToSet(player, "player")

    haven = Planet_Create(200.0, "colony.nif")
    haven.SetName("Haven")
    haven.SetDisplayName("Haven")
    s.AddObjectToSet(haven, "Haven")

    sun = Sun_Create(2000.0, 2000, 500)
    sun.SetName("Vesuvi")
    sun.SetDisplayName("Vesuvi")
    s.AddObjectToSet(sun, "Vesuvi")

    game = Game()
    game.SetPlayer(player)
    _set_current_game(game)
    return s, player, sensors, haven, sun


def test_setup_orbit_menu_adds_planet_excludes_sun():
    s, player, sensors, haven, sun = _player_and_set()
    orbit = App.STMenu_CreateW("Orbit Planet")

    H.SetupOrbitMenuFromSet(orbit, s)

    # Exactly one button, for the planet — the sun is filtered by IsTypeOf(CT_SUN).
    assert len(orbit._children) == 1
    assert orbit._children[0].GetLabel() == "Haven"
    assert orbit.IsOpenable() == 1
    assert orbit.IsEnabled() == 1
    # The planet is force-identified so the player can target it.
    assert sensors.IsObjectKnown(haven) == 1


def test_setup_orbit_menu_empty_set_is_not_openable():
    """No planets -> menu closes (SetNotOpenable/SetDisabled)."""
    s = SetClass()
    player = ShipClass_Create("Galaxy")
    player.SetSensorSubsystem(SensorSubsystem("Sensors"))
    s.AddObjectToSet(player, "player")
    game = Game()
    game.SetPlayer(player)
    _set_current_game(game)

    orbit = App.STMenu_CreateW("Orbit Planet")
    H.SetupOrbitMenuFromSet(orbit, s)

    assert len(orbit._children) == 0
    assert orbit.IsOpenable() == 0
    assert orbit.IsEnabled() == 0


def test_click_haven_button_runs_orbit_planet_handler(monkeypatch):
    """Clicking the Haven button (SendActivationEvent) dispatches the button's
    stored (type=ET_ORBIT_PLANET, source=planet, dest=orbit menu) event to the
    menu's registered SDK OrbitPlanet handler, which gives the player the
    AI.Player.OrbitPlanet tree and targets the planet (Layer 4a)."""
    # MissionLib.SetPlayerAI calls Bridge.TacticalMenuHandlers.UpdateOrders(0),
    # which reads UI globals only defined once the TacticalControlWindow builds
    # CreateOrdersStatusDisplay (TacticalControlWindow.py:184) — present at real
    # mission load, absent in this bare fixture. Stub the seam MissionLib uses.
    import Bridge.TacticalMenuHandlers as T
    monkeypatch.setattr(T, "UpdateOrders", lambda *a, **k: None)

    s = SetClass()
    player = ShipClass_Create("Galaxy")
    sensors = SensorSubsystem("Sensors")
    sensors._condition = 100.0
    sensors._max_condition = 100.0
    player.SetSensorSubsystem(sensors)
    s.AddObjectToSet(player, "player")
    haven = Planet_Create(200.0, "colony.nif")
    haven.SetName("Haven")
    haven.SetDisplayName("Haven")
    s.AddObjectToSet(haven, "Haven")
    game = Game()
    _set_current_game(game)

    # Register the real SDK handlers before the player exists (mission-load
    # ordering), then let ET_SET_PLAYER populate the orbit menu.
    H.ET_SET_NAVPOINT_TARGET = App.Game_GetNextEventType()
    orbit = App.STMenu_CreateW("Orbit Planet")
    nav = App.STMenu_CreateW("Nav Points")
    H.SetupOrbitAndNavMenuHandlers(orbit, nav)
    game.SetPlayer(player)

    assert len(orbit._children) == 1
    button = orbit._children[0]
    assert button.GetLabel() == "Haven"
    assert player.GetAI() is None

    button.SendActivationEvent()

    ai = player.GetAI()
    assert ai is not None
    assert ai.GetName() == "OrbitAvoidObstacles"   # CreateAI's root PreprocessingAI
    assert player.GetTarget() is haven


def test_set_player_event_repopulates_orbit_menu():
    """Game.SetPlayer fires ET_SET_PLAYER -> OrbitMenuPlayerChanged repopulates
    the orbit menu from the player's set (the real mission-load trigger)."""
    s = SetClass()
    player = ShipClass_Create("Galaxy")
    sensors = SensorSubsystem("Sensors")
    sensors._condition = 100.0
    sensors._max_condition = 100.0
    player.SetSensorSubsystem(sensors)
    s.AddObjectToSet(player, "player")
    haven = Planet_Create(200.0, "colony.nif")
    haven.SetName("Haven")
    haven.SetDisplayName("Haven")
    s.AddObjectToSet(haven, "Haven")

    game = Game()
    _set_current_game(game)

    # Register the real SDK handlers (as CreateMenus does at bridge load), while
    # no player exists yet — mirroring the actual mission-load ordering.
    # CreateMenus assigns this file-local event type before wiring the nav menu;
    # replicate it since we call the sub-function directly (HelmMenuHandlers.py:144).
    H.ET_SET_NAVPOINT_TARGET = App.Game_GetNextEventType()
    orbit = App.STMenu_CreateW("Orbit Planet")
    nav = App.STMenu_CreateW("Nav Points")
    H.SetupOrbitAndNavMenuHandlers(orbit, nav)
    assert len(orbit._children) == 0   # nothing to populate yet (no player)

    # Player assigned (already in its set, as MissionLib.CreatePlayerShip does).
    game.SetPlayer(player)

    assert len(orbit._children) == 1
    assert orbit._children[0].GetLabel() == "Haven"
    assert orbit.IsOpenable() == 1
    assert orbit.IsEnabled() == 1


# ── Helm "Nav Points" submenu ────────────────────────────────────────────────
# The sibling of the orbit menu, populated by the same handlers, and dead for
# the same class of reason: SetupNavPointsMenuFromSet:1096 reads
# pSet.GetNavPoints(), which was a hardcoded `return []` from the era when the
# headless model carried no nav-point objects. Zero entries -> SetNotOpenable()
# + SetDisabled(), so the row stayed greyed and un-openable for the whole game.
# Live symptom: at the end of E1M1 the mission tells you to approach Starbase 12
# via a nav point and the menu will not open.
#
# Unlike the orbit menu, SetupNavPointsMenuFromSet takes no menu argument — it
# re-finds the menu through TacticalControlWindow.FindMenu(<Helm>) and then
# GetSubmenuW(<Nav Points>). So these tests wire the real TCW lookup path too;
# a fix to GetNavPoints alone is not enough if that lookup returns None (the
# function silently returns early).


def _helm_menu_with_nav_submenu():
    """A Helm menu registered on the TacticalControlWindow, holding an empty
    "Nav Points" submenu — the shape HelmMenuHandlers.CreateMenus:215 builds."""
    tcw = App.TacticalControlWindow_GetTacticalControlWindow()
    db = App.g_kLocalizationManager.Load("data/TGL/Bridge Menus.tgl")
    helm = App.STMenu_CreateW(db.GetString("Helm"))
    nav = App.STMenu_CreateW(db.GetString("Nav Points"))
    helm.AddChild(nav)
    tcw.AddMenuToList(helm)
    App.g_kLocalizationManager.Unload(db)
    return helm, nav


def _set_with_starbase_nav():
    """E1M1's Starbase12 set in miniature: E1M1_Starbase12_P.LoadPlacements
    creates five waypoints, four SetNavPoint(0) and one SetNavPoint(1)."""
    from engine.appc.placement import Waypoint

    s = SetClass()
    player = ShipClass_Create("Galaxy")
    sensors = SensorSubsystem("Sensors")
    sensors._condition = 100.0
    sensors._max_condition = 100.0
    player.SetSensorSubsystem(sensors)
    s.AddObjectToSet(player, "player")

    cam = Waypoint()
    cam.SetNavPoint(0)
    s.AddObjectToSet(cam, "DockingCam")

    nav_point = Waypoint()
    nav_point.SetNavPoint(1)
    s.AddObjectToSet(nav_point, "Starbase Nav")

    game = Game()
    game.SetPlayer(player)
    _set_current_game(game)
    return s, player, sensors, nav_point


def test_setup_nav_points_menu_enables_and_populates_the_row():
    """THE E1M1 repro, through the real SDK function."""
    helm, nav = _helm_menu_with_nav_submenu()
    s, player, sensors, nav_point = _set_with_starbase_nav()

    H.SetupNavPointsMenuFromSet(s)

    # One button, for the flagged waypoint only — the DockingCam mark has
    # SetNavPoint(0) and must not reach the player's Helm menu.
    assert len(nav._children) == 1
    assert nav._children[0].GetLabel() == "Starbase Nav"
    # The two calls that decide whether the row can be clicked at all.
    assert nav.IsOpenable() == 1
    assert nav.IsEnabled() == 1
    # SetupNavPointsMenuFromSet:1117 identifies each nav point to the player.
    assert sensors.IsObjectKnown(nav_point) == 1


def test_setup_nav_points_menu_disables_the_row_when_the_set_has_none():
    """The other half of the same branch — a set with no flagged placement
    must still close the row, not open an empty menu."""
    helm, nav = _helm_menu_with_nav_submenu()
    s = SetClass()
    player = ShipClass_Create("Galaxy")
    player.SetSensorSubsystem(SensorSubsystem("Sensors"))
    s.AddObjectToSet(player, "player")
    game = Game()
    game.SetPlayer(player)
    _set_current_game(game)

    H.SetupNavPointsMenuFromSet(s)

    assert len(nav._children) == 0
    assert nav.IsOpenable() == 0
    assert nav.IsEnabled() == 0


def test_flagging_a_nav_point_at_runtime_rebuilds_the_menu():
    """MissionLib.AddNavPoints flips the flag mid-mission; SetNavPoint's
    ET_NAV_POINT_CHANGED broadcast must reach the SDK's NavPointChanged and
    rebuild the row. Without a real event constant the registration landed on
    a dead int()==0 slot and the open menu never noticed (E6M2:2221, E7M2)."""
    from engine.appc.placement import Waypoint

    helm, nav = _helm_menu_with_nav_submenu()
    s = SetClass()
    s.SetName("Starbase12")
    player = ShipClass_Create("Galaxy")
    sensors = SensorSubsystem("Sensors")
    sensors._condition = 100.0
    sensors._max_condition = 100.0
    player.SetSensorSubsystem(sensors)
    s.AddObjectToSet(player, "player")
    later = Waypoint()
    s.AddObjectToSet(later, "Starbase Nav")

    game = Game()
    _set_current_game(game)
    H.ET_SET_NAVPOINT_TARGET = App.Game_GetNextEventType()
    orbit = App.STMenu_CreateW("Orbit Planet")
    H.SetupOrbitAndNavMenuHandlers(orbit, nav)
    game.SetPlayer(player)

    assert nav.IsEnabled() == 0   # nothing flagged yet

    later.SetNavPoint(1)          # what MissionLib.AddNavPoints does

    assert len(nav._children) == 1
    assert nav._children[0].GetLabel() == "Starbase Nav"
    assert nav.IsOpenable() == 1
    assert nav.IsEnabled() == 1
