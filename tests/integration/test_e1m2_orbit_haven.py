"""E1M2 "enter orbit" goal: clicking Haven in Helm -> Orbit Planet completes it.

Layer 4a end-to-end: the Haven button's stored (ET_ORBIT_PLANET, source=Haven,
dest=orbit menu) event runs the SDK HelmMenuHandlers.OrbitPlanet handler, which
puts the AI.Player.OrbitPlanet tree on the player and targets the planet. The
tree's first step fires ET_AI_ORBITTING at the planet, where E1M2's
OrbitingHaven instance handler (registered by SetupOrbitEvents at mission init,
gated on g_bMissionWinCalled) sets g_bPlayerInOrbit.
"""
import App
from engine import host_loop
from engine.core.loop import GameLoop
from tests.integration.test_sdk_bridge_load import _fresh_world


E1M2_MODULE = "Maelstrom.Episode1.E1M2.E1M2"


def _find_orbit_menu_and_haven_button(haven):
    """The real Helm -> Orbit Planet submenu and its Haven button, as built at
    mission load and populated from the player's set. Buttons are labelled with
    the planet's DISPLAY name ("Vesuvi 6 - Haven"), so match on the stored
    activation event's source planet instead. (Don't walk with GetFirstChild/
    GetNextChild — STMenu doesn't define them, and the truthy _Stub fallbacks
    make a `while child:` loop spin forever.)"""
    import Bridge.BridgeUtils as BridgeUtils
    helm = BridgeUtils.GetBridgeMenu("Helm")
    assert helm is not None
    orbit = helm.GetSubmenuW("Orbit Planet")
    assert orbit is not None, "Helm menu has no 'Orbit Planet' submenu"
    for button in orbit._buttons.values():
        evt = button._event
        if evt is not None and evt.GetSource() is haven:
            return orbit, button
    raise AssertionError("Orbit Planet menu has no button for Haven")


def test_click_haven_completes_enter_orbit_goal():
    _fresh_world()
    mission, episode, game, mod = host_loop._init_mission(E1M2_MODULE)

    import MissionLib
    player = MissionLib.GetPlayer()
    pSet = App.g_kSetManager.GetSet("Vesuvi6")
    haven = pSet.GetObject("Haven")
    assert haven is not None
    assert player.GetContainingSet() is pSet   # player starts in Vesuvi6

    # Park the player inside the orbit AI's activation range
    # (ConditionInRange threshold = 200 + planet radius).
    loc = haven.GetWorldLocation()
    player.SetTranslateXYZ(loc.x, loc.y + haven.GetRadius() + 100.0, loc.z)

    # Narrative gate: OrbitingHaven only acts after the mission-win beat.
    mod.g_bMissionWinCalled = 1
    assert mod.g_bPlayerInOrbit != 1

    orbit_menu, haven_button = _find_orbit_menu_and_haven_button(haven)
    # Dispatch the button's stored event exactly as SendActivationEvent does,
    # minus its exception swallow so a failure surfaces here instead of a
    # silent no-op.
    assert haven_button._event is not None
    App.g_kEventManager.AddEvent(haven_button._event)

    # OrbitPlanet ran: AI installed, planet targeted.
    ai = player.GetAI()
    assert ai is not None
    assert ai.GetName() == "OrbitAvoidObstacles"
    assert player.GetTarget() is haven

    # Tick the loop: StartingOrbit fires ET_AI_ORBITTING at Haven and E1M2's
    # OrbitingHaven flips the goal flag.
    GameLoop().advance(3)
    assert mod.g_bPlayerInOrbit == 1


def test_orbit_enter_and_leave_play_helm_dialogue(monkeypatch):
    """The helm officer announces orbit transitions (SDK chain:
    HelmMenuHandlers.SetPlayer builds g_pPlayerOrbitting —
    ConditionPlayerOrbitting tracks ET_AI_ORBITTING/ET_AI_DONE — and
    MissionLib.CallFunctionWhenConditionChanges redirects status flips to
    HelmMenuHandlers.Orbitting → AnnounceOrbit → helm SAY_LINE
    "EnteringOrbit" on enter, "KiskaLeaveOrbit" on leave)."""
    _fresh_world()
    mission, episode, game, mod = host_loop._init_mission(E1M2_MODULE)

    import MissionLib
    player = MissionLib.GetPlayer()
    pSet = App.g_kSetManager.GetSet("Vesuvi6")
    haven = pSet.GetObject("Haven")
    loc = haven.GetWorldLocation()
    player.SetTranslateXYZ(loc.x, loc.y + haven.GetRadius() + 100.0, loc.z)
    mod.g_bMissionWinCalled = 1

    spoken = []
    from engine.appc import crew_speech
    monkeypatch.setattr(
        crew_speech, "emit",
        lambda name, db, line, pri, *a, **k: (spoken.append(line), 0.0)[1])

    orbit_menu, haven_button = _find_orbit_menu_and_haven_button(haven)
    App.g_kEventManager.AddEvent(haven_button._event)

    # AnnounceOrbit runs via a TGSequence with a 0.5 s delay — tick past it.
    GameLoop().advance(120)
    assert "EnteringOrbit" in spoken, f"no enter-orbit line; spoken={spoken}"

    # Breaking orbit (order cleared — same path manual cancel takes) fires
    # ET_AI_DONE → condition drops → the leave line plays.
    player.ClearAI()
    GameLoop().advance(120)
    assert "KiskaLeaveOrbit" in spoken, f"no leave-orbit line; spoken={spoken}"
