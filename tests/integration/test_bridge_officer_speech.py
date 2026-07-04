"""Bridge officers speak their SDK acknowledgement lines (Helm increment).

engine/bridge_officers.configure_bridge_officers runs each SDK
Bridge/Characters/<name>.ConfigureForShip (individually guarded), whose
AttachMenuTo<station> registers the officer acknowledgement handlers on the
real menus LoadBridge.Load built. The CEF crew-menu panel clicks rows via
STButton.SendActivationEvent (engine/ui/crew_menu_panel.py), so these tests
click the same way. Speech is asserted at crew_speech.emit — the single
funnel every CharacterAction speak type routes through (engine/appc/ai.py).
"""
import re
import sys

import pytest

import App
import LoadBridge
from engine.appc import crew_speech
from engine.appc.planet import Planet_Create
from engine.appc.sets import SetClass
from engine.appc.ships import ShipClass_Create
from engine.appc.target_menu import _reset_target_menu_singleton
from engine.appc.tg_ui import st_widgets
from engine.appc.windows import TacticalControlWindow
from engine.bridge_officers import configure_bridge_officers, announce_course_set
from engine.core.game import Game, Episode, Mission, _set_current_game
from engine.sdk_ui.widgets.ship_display import (
    _reset_create_count as _reset_ship_display,
)

_HELM_HANDLERS = "Bridge.HelmCharacterHandlers"


def _fresh_world():
    # Mirrors tests/integration/test_bridge_menu_activation.py::_fresh_world.
    TacticalControlWindow._instance = None
    _reset_target_menu_singleton()
    st_widgets._reset_module_state()
    _reset_ship_display()
    App.g_kSetManager._sets.clear()
    App.g_kEventManager._broadcast_handlers.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()
    game = Game()
    episode = Episode()
    mission = Mission()
    episode.SetCurrentMission(mission)
    game.SetCurrentEpisode(episode)
    _set_current_game(game)
    for name in list(sys.modules):
        mod = sys.modules[name]
        if name.startswith("Bridge.") and "StubModule" in type(mod).__name__:
            sys.modules.pop(name)
    return game


def _loaded_world(monkeypatch):
    """Fresh world with the real SDK bridge + menus loaded, no player yet."""
    game = _fresh_world()
    # MissionLib.SetPlayerAI -> TacticalMenuHandlers.UpdateOrders reads orders-
    # display globals only created by the full TacticalControlWindow build;
    # stub the same seam tests/unit/test_helm_orbit_menu.py stubs.
    import Bridge.TacticalMenuHandlers as T
    monkeypatch.setattr(T, "UpdateOrders", lambda *a, **k: None)
    LoadBridge.Load("GalaxyBridge")
    return game


def _make_player_world():
    """A player ship (healthy sensors/engines) in a set with planet Haven."""
    s = SetClass()
    player = ShipClass_Create("Galaxy")
    for sub in (player.GetSensorSubsystem(),
                player.GetImpulseEngineSubsystem(),
                player.GetWarpEngineSubsystem()):
        sub._condition = 100.0
        sub._max_condition = 100.0
    s.AddObjectToSet(player, "player")
    haven = Planet_Create(200.0, "colony.nif")
    haven.SetName("Haven")
    haven.SetDisplayName("Haven")
    s.AddObjectToSet(haven, "Haven")
    return s, player, haven


@pytest.fixture
def bridge_world(monkeypatch):
    """Real SDK bridge + menus + a player (with a planet) — mission-load order:
    LoadBridge.Load first, then the player appears and ET_SET_PLAYER populates
    the orbit menu, then (in the tests) configure_bridge_officers."""
    game = _loaded_world(monkeypatch)
    s, player, haven = _make_player_world()
    game.SetPlayer(player)   # ET_SET_PLAYER -> orbit menu populates
    try:
        yield game, player, haven
    finally:
        App.g_kSetManager._sets.clear()
        _set_current_game(None)


def _helm_menu():
    menu = TacticalControlWindow.GetInstance().FindMenu("Helm")
    assert menu is not None
    return menu


def _button(menu, label):
    for child in menu._children:
        if getattr(child, "GetLabel", lambda: None)() == label:
            return child
    raise AssertionError(
        "no %r in %r" % (label, [c.GetLabel() for c in menu._children]))


def _capture_speech(monkeypatch):
    calls = []
    monkeypatch.setattr(
        crew_speech, "emit",
        lambda speaker, db, line, priority, *a, **k:
            calls.append((speaker, str(line), db)) or 1.0)
    return calls


def _spoke(calls, speaker, line):
    """True when the line was emitted WITH a database that resolves it —
    emit() with db=None (or a db missing the key) produces no text and no
    wav, i.e. live silence, so a bare emit call is not enough."""
    return any(s == speaker and l == line
               and db is not None and db.HasString(line)
               for s, l, db in calls)


def test_et_report_is_real_and_unique():
    assert type(App.ET_REPORT) is int
    clashes = [n for n, v in vars(App).items()
               if n.startswith("ET_") and n != "ET_REPORT"
               and isinstance(v, int) and v == App.ET_REPORT]
    assert clashes == []


def test_configure_registers_helm_handlers(bridge_world):
    game, player, haven = bridge_world
    bridge = App.g_kSetManager.GetSet("bridge")

    results = configure_bridge_officers(bridge, player)
    assert results["Kiska"] is None, results["Kiska"]

    helm = _helm_menu()
    for et, fn in ((App.ET_REPORT, ".Report"),
                   (App.ET_SET_COURSE, ".SetCourse"),
                   (App.ET_DOCK, ".HelmDock"),
                   (App.ET_ALL_STOP, ".AllStop")):
        assert helm._handlers.get(et, []).count(_HELM_HANDLERS + fn) == 1
    orbit = helm.GetSubmenuW("Orbit Planet")
    assert orbit._handlers.get(App.ET_ORBIT_PLANET, []).count(
        _HELM_HANDLERS + ".OrbitPlanet") == 1

    # Once per load: a second configure (AttachMenuToHelm self-detaches, and
    # the Communicate shim remove-then-adds) must not double-register.
    configure_bridge_officers(bridge, player)
    assert helm._handlers.get(App.ET_ALL_STOP, []).count(
        _HELM_HANDLERS + ".AllStop") == 1
    assert helm._handlers.get(App.ET_COMMUNICATE, []).count(
        "engine.bridge_officers.CommunicateToReport") == 1


def test_all_stop_click_speaks_kiska_yes(bridge_world, monkeypatch):
    game, player, haven = bridge_world
    configure_bridge_officers(App.g_kSetManager.GetSet("bridge"), player)
    calls = _capture_speech(monkeypatch)

    _button(_helm_menu(), "All Stop").SendActivationEvent()

    assert any(s == "Kiska" and re.fullmatch(r"KiskaYes[1-4]", l)
               and db is not None and db.HasString(l)
               for s, l, db in calls), calls


def test_report_click_speaks_engine_status(bridge_world, monkeypatch):
    """The Helm "Report" row is the SDK Communicate button (ET_COMMUNICATE at
    the menu); the CommunicateToReport shim re-dispatches it as ET_REPORT so
    HelmCharacterHandlers.Report speaks — replacing, not preceding, the
    NothingToAdd fallback."""
    game, player, haven = bridge_world
    configure_bridge_officers(App.g_kSetManager.GetSet("bridge"), player)
    calls = _capture_speech(monkeypatch)

    _button(_helm_menu(), "Report").SendActivationEvent()

    # The report sequence's later lines play after the first line's duration;
    # asserting the first (impulse status) proves the whole chain fired.
    assert _spoke(calls, "Kiska", "ImpulseEnginesFunctional"), calls
    assert not any(l == "KiskaNothingToAdd" for _, l, _db in calls), calls


def test_orbit_click_installs_ai_and_speaks_standard_orbit(bridge_world,
                                                           monkeypatch):
    """Both LIFO handlers fire on a planet click: HelmCharacterHandlers.
    OrbitPlanet (registered later, runs first, speaks "StandardOrbit") chains
    via CallNextHandler into HelmMenuHandlers.OrbitPlanet (installs the orbit
    AI and targets the planet)."""
    game, player, haven = bridge_world
    configure_bridge_officers(App.g_kSetManager.GetSet("bridge"), player)
    calls = _capture_speech(monkeypatch)
    orbit = _helm_menu().GetSubmenuW("Orbit Planet")
    assert player.GetAI() is None

    _button(orbit, "Haven").SendActivationEvent()

    ai = player.GetAI()
    assert ai is not None
    assert ai.GetName() == "OrbitAvoidObstacles"
    assert player.GetTarget() is haven
    assert _spoke(calls, "Kiska", "StandardOrbit"), calls


def test_course_set_announcement_speaks_ready_to_warp(bridge_world,
                                                      monkeypatch):
    """The CEF Set Course modal dispatches no SDK event, so the host fires
    ET_SET_COURSE (non-intercept) at the Helm menu via announce_course_set —
    Kiska acks with gh075 (the SDK "ready to warp" line)."""
    game, player, haven = bridge_world
    configure_bridge_officers(App.g_kSetManager.GetSet("bridge"), player)
    calls = _capture_speech(monkeypatch)

    announce_course_set()

    assert _spoke(calls, "Kiska", "gh075"), calls


def test_quickbattle_late_player_wires_officers_via_set_player(monkeypatch):
    """The LIVE boot path: QuickBattle creates the player AFTER mission load
    (StartSimulation2 -> RecreatePlayer -> CreatePlayerShip -> SetPlayer) and
    recreates it on every battle restart. The post-load hook therefore can't
    configure directly (no player yet) — it registers OnSetPlayer on the
    ET_SET_PLAYER broadcast, exactly as replicated here."""
    game = _loaded_world(monkeypatch)
    try:
        # What host_loop's post-load hook does when GetPlayer() is None: only
        # the broadcast registration. Unconditional import mirrors the hook —
        # _resolve_handler finds handlers via sys.modules, it never imports.
        import engine.bridge_officers  # noqa: F401
        App.g_kEventManager.AddBroadcastPythonFuncHandler(
            App.ET_SET_PLAYER, None, "engine.bridge_officers.OnSetPlayer")
        helm = _helm_menu()
        assert helm._handlers.get(App.ET_ALL_STOP, []).count(
            _HELM_HANDLERS + ".AllStop") == 0   # nothing wired at load

        s, player, haven = _make_player_world()
        game.SetPlayer(player)                  # battle start

        assert helm._handlers.get(App.ET_ALL_STOP, []).count(
            _HELM_HANDLERS + ".AllStop") == 1

        # Battle restart: a NEW player ship, SetPlayer again — officers
        # re-wire to it without double registration.
        s2, player2, _ = _make_player_world()
        game.SetPlayer(player2)
        assert helm._handlers.get(App.ET_ALL_STOP, []).count(
            _HELM_HANDLERS + ".AllStop") == 1
        assert helm._handlers.get(App.ET_COMMUNICATE, []).count(
            "engine.bridge_officers.CommunicateToReport") == 1

        calls = _capture_speech(monkeypatch)
        _button(helm, "All Stop").SendActivationEvent()
        assert any(s == "Kiska" and re.fullmatch(r"KiskaYes[1-4]", l)
                   and db is not None and db.HasString(l)
                   for s, l, db in calls), calls
    finally:
        App.g_kSetManager._sets.clear()
        _set_current_game(None)


def test_one_station_raising_does_not_silence_the_others(bridge_world,
                                                         monkeypatch):
    game, player, haven = bridge_world
    import Bridge.Characters.Felix as Felix

    def _boom(*a, **k):
        raise RuntimeError("unimplemented Appc surface")

    monkeypatch.setattr(Felix, "ConfigureForShip", _boom)
    results = configure_bridge_officers(
        App.g_kSetManager.GetSet("bridge"), player)

    assert isinstance(results["Felix"], RuntimeError)
    assert results["Kiska"] is None, results["Kiska"]
    helm = _helm_menu()
    assert helm._handlers.get(App.ET_ALL_STOP, []).count(
        _HELM_HANDLERS + ".AllStop") == 1
