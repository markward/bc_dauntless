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
