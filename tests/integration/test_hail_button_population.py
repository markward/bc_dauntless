"""Faithful check that the REAL Bridge/HelmMenuHandlers hail-button path,
run against the engine's Appc surface, only builds buttons for genuinely
hailable contacts — not asteroids, moons, or other non-hailable objects.

Regression: identifying every set object made the Hail submenu list lights,
markers, asteroids and moons. Only objects whose IsHailable()==1 must produce
a hail button (SDK CreateHailButton gate).
"""
import sys

import pytest

import App
from engine.appc.windows import TacticalControlWindow
from engine.appc.target_menu import _reset_target_menu_singleton
from engine.appc.ships import ShipClass_Create
from engine.appc.planet import Planet_Create
from engine.appc.sets import SetClass
from engine.appc import display_names
from engine.core.game import Game, Episode, Mission, _set_current_game


def _make_game():
    game = Game()
    episode = Episode()
    mission = Mission()
    episode.SetCurrentMission(mission)
    game.SetCurrentEpisode(episode)
    return game


def _fresh_real_helm():
    saved = sys.modules.pop("Bridge.HelmMenuHandlers", None)
    saved_bare = sys.modules.pop("HelmMenuHandlers", None)
    import Bridge.HelmMenuHandlers as real
    return real, saved, saved_bare


def _restore(saved, saved_bare):
    if saved is not None:
        sys.modules["Bridge.HelmMenuHandlers"] = saved
    if saved_bare is not None:
        sys.modules["HelmMenuHandlers"] = saved_bare


def test_create_hail_button_gates_on_hailable():
    """SDK CreateHailButton returns None for a non-hailable object (asteroid,
    moon) and a real button for a hailable one (the colony)."""
    TacticalControlWindow._instance = None
    _reset_target_menu_singleton()
    game = _make_game()
    _set_current_game(game)
    real, saved, saved_bare = _fresh_real_helm()
    try:
        real.CreateMenus()

        # Asteroid/debris are ships (default hailable) that E1M2 explicitly
        # SetHailable(FALSE) to hide -> no button after suppression.
        asteroid = ShipClass_Create("Asteroid")
        asteroid.SetName("Debris1")
        assert asteroid.IsHailable() == 1        # ship default
        asteroid.SetHailable(0)                   # E1M2 hides debris
        assert asteroid.IsHailable() == 0
        assert real.CreateHailButton(asteroid) is None

        # Non-hailable planet (a moon) -> no button.
        moon = Planet_Create(40.0, "moon.nif")
        moon.SetName("Moon 1")
        assert moon.IsHailable() == 0
        assert real.CreateHailButton(moon) is None

        # Hailable colony -> a real button labelled with its display name.
        haven = Planet_Create(90.0, "colony.nif")
        haven.SetName("Haven")
        haven.SetDisplayName("Vesuvi 6 - Haven")
        haven.SetHailable(1)
        assert haven.IsHailable() == 1
        button = real.CreateHailButton(haven)
        assert button is not None
        assert button.GetLabel() == "Vesuvi 6 - Haven"
    finally:
        _restore(saved, saved_bare)
        _set_current_game(None)


def test_ship_defaults_hailable_planet_does_not():
    """Ships default hailable (so E1M2's Facility appears without an explicit
    SetHailable); planets/objects default not hailable (Haven opts in)."""
    assert ShipClass_Create("FedOutpost").IsHailable() == 1
    assert Planet_Create(90.0, "colony.nif").IsHailable() == 0


def test_e1m2_hailing_haven_runs_missionhandler_and_advances():
    """End-to-end: dispatching ET_HAIL for the E1M2 colony through the real
    engine runs E1M2.HailHandler FIRST (LIFO chain), which advances the mission
    (g_bHavenSecondHail 0->1) and short-circuits the generic 'no response'.
    Regressions this guards: handler-chain order, HailHandler not crashing on
    the real load path, and the whole dispatch reaching the mission handler."""
    from tests.integration.test_sdk_bridge_load import _fresh_world
    from engine import host_loop

    _fresh_world()
    try:
        mission, episode, game, mod = host_loop._init_mission(
            "Maelstrom.Episode1.E1M2.E1M2")
    except Exception:
        pytest.skip("E1M2 could not be loaded headless (BC game data absent)")
    try:
        db = App.g_kLocalizationManager.Load("data/TGL/Bridge Menus.tgl")
        helm = App.TacticalControlWindow_GetTacticalControlWindow().FindMenu(
            str(db.GetString("Helm")))
        haven = None
        for pSet in App.g_kSetManager.GetAllSets():
            o = pSet.GetObject("Haven")
            if o is not None:
                haven = o
                break
        if haven is None or helm is None:
            pytest.skip("E1M2 Haven/Helm not present headless")

        mod.g_bDebrisCleared = 1          # simulate the asteroids destroyed
        assert mod.g_bHavenSecondHail == 0

        evt = App.TGObjPtrEvent_Create()
        evt.SetSource(haven)
        evt.SetObjPtr(haven)
        evt.SetDestination(helm)
        evt.SetEventType(App.ET_HAIL)
        App.g_kEventManager.AddEvent(evt)

        # SecondHavenHail ran -> mission advanced (not the generic "no response").
        assert mod.g_bHavenSecondHail == 1
    finally:
        App.g_kSetManager._sets.clear()
        _set_current_game(None)


def test_non_cloaking_ship_reports_not_cloaked():
    """HelmMenuHandlers.ShipIdentified builds a ship's hail button only when
    `not pShip.IsCloaked()`. A non-cloaking ship/station (Facility) must report
    a real 0 — a truthy __getattr__ stub suppressed its Hail button entirely."""
    ship = ShipClass_Create("FedOutpost")
    assert ship.IsCloaked() == 0
    assert ship.IsTryingToCloak() == 0


def test_apply_display_names_from_real_tgls():
    """The global display-name pass resolves E1M2's objects to their localized
    names using the real campaign (Maelstrom.tgl) + mission (E1M2.tgl) TGLs:
    Haven -> 'Vesuvi 6 - Haven', Facility -> 'Haven Facility',
    Debris1 -> 'Debris 1'. Skips if the BC game data isn't installed."""
    campaign_db = App.g_kLocalizationManager.Load("data/TGL/Maelstrom/Maelstrom.tgl")
    mission_db = App.g_kLocalizationManager.Load(
        "data/TGL/Maelstrom/Episode 1/E1M2.tgl")
    if campaign_db is None or not campaign_db.HasString("Haven"):
        pytest.skip("BC game data (Maelstrom.tgl) not installed")

    game = _make_game()
    game.SetDatabase(campaign_db)
    game.GetCurrentEpisode().GetCurrentMission().SetDatabase(mission_db)
    _set_current_game(game)
    try:
        pSet = SetClass()
        App.g_kSetManager.AddSet(pSet, "Vesuvi6")
        pSet.AddObjectToSet(Planet_Create(90.0, "colony.nif"), "Haven")
        pSet.AddObjectToSet(ShipClass_Create("FedOutpost"), "Facility")
        pSet.AddObjectToSet(ShipClass_Create("Asteroid"), "Debris1")

        display_names.apply_display_names()

        assert pSet.GetObject("Haven").GetDisplayName() == "Vesuvi 6 - Haven"
        assert pSet.GetObject("Facility").GetDisplayName() == "Haven Facility"
        assert pSet.GetObject("Debris1").GetDisplayName() == "Debris 1"
        # CRITICAL: the display-name pass must NOT change internal names — those
        # key set membership / group allegiance / target selection / mission
        # GetName() checks. Conflating them turned every contact neutral and
        # unselectable.
        assert pSet.GetObject("Haven").GetName() == "Haven"
        assert pSet.GetObject("Facility").GetName() == "Facility"
        assert pSet.GetObject("Debris1").GetName() == "Debris1"
    finally:
        App.g_kSetManager.DeleteSet("Vesuvi6")
        _set_current_game(None)


def test_identification_localizes_display_name():
    """A contact created after mission load still gets its localized name: the
    sensor-identification pass applies it just before the Hail/target row."""
    from engine.appc.subsystems import SensorSubsystem
    from engine.appc import sensor_identification

    campaign_db = App.g_kLocalizationManager.Load("data/TGL/Maelstrom/Maelstrom.tgl")
    if campaign_db is None or not campaign_db.HasString("Haven"):
        pytest.skip("BC game data (Maelstrom.tgl) not installed")

    game = _make_game()
    game.SetDatabase(campaign_db)
    _set_current_game(game)
    try:
        pSet = SetClass()
        App.g_kSetManager.AddSet(pSet, "Vesuvi6")
        player = ShipClass_Create("Galaxy")
        sensors = SensorSubsystem("Sensors")
        sensors._max_condition = 100.0
        sensors._condition = 100.0
        sensors.SetBaseSensorRange(30000.0)
        player.SetSensorSubsystem(sensors)
        pSet.AddObjectToSet(player, "player")
        haven = Planet_Create(90.0, "colony.nif")
        haven.SetTranslateXYZ(1000.0, 0.0, 0.0)
        pSet.AddObjectToSet(haven, "Haven")

        sensor_identification.identify_contacts(player)

        assert sensors.IsObjectKnown(haven) == 1
        assert haven.GetDisplayName() == "Vesuvi 6 - Haven"
    finally:
        App.g_kSetManager.DeleteSet("Vesuvi6")
        _set_current_game(None)
