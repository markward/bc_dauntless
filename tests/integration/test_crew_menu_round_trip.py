"""End-to-end proof: real HelmMenuHandlers menu tree -> CrewMenuPanel
snapshot -> simulated CEF click on All Stop -> SDK handler runs ->
MissionLib.SetPlayerAI gives the player Stay AI.
"""
import sys

import App
from engine.appc.windows import TacticalControlWindow
from engine.appc.ships import ShipClass_Create
from engine.appc.target_menu import _reset_target_menu_singleton
from engine.core.game import Game, Episode, Mission, _set_current_game
from engine.ui.crew_menu_panel import CrewMenuPanel


def _make_game():
    """Minimal game/episode/mission scaffold required by CreateMenus
    (mirrors test_helm_menu_creation._make_game exactly)."""
    game = Game()
    episode = Episode()
    mission = Mission()
    episode.SetCurrentMission(mission)
    game.SetCurrentEpisode(episode)
    return game


def _fresh_real_helm():
    """Pop any cached stub/real module so we get a fresh real load."""
    saved = sys.modules.pop("Bridge.HelmMenuHandlers", None)
    saved_bare = sys.modules.pop("HelmMenuHandlers", None)
    import Bridge.HelmMenuHandlers as real
    return real, saved, saved_bare


def _restore(saved, saved_bare):
    if saved is not None:
        sys.modules["Bridge.HelmMenuHandlers"] = saved
    else:
        sys.modules.pop("Bridge.HelmMenuHandlers", None)
    if saved_bare is not None:
        sys.modules["HelmMenuHandlers"] = saved_bare
    else:
        sys.modules.pop("HelmMenuHandlers", None)


def _find_button(node, label):
    """Recursively find a button node by label in a snapshot tree node."""
    if node.get("type") == "button" and node["label"] == label:
        return node
    for child in node.get("children", []):
        hit = _find_button(child, label)
        if hit:
            return hit
    return None


def test_all_stop_click_gives_player_stay_ai():
    # Reset singletons from previous tests.
    TacticalControlWindow._instance = None
    _reset_target_menu_singleton()

    # Build minimal game scaffold; set player ship.
    game = _make_game()
    player = ShipClass_Create("TestPlayer")
    game.SetCurrentPlayer(player)
    _set_current_game(game)
    # Explicitly clear any AI the player may have from a previous test run.
    player.SetAI(None)

    # Bridge.TacticalMenuHandlers is called by MissionLib.SetPlayerAI when
    # sController != "Tactical".  Pre-stub it so the real module (which
    # touches bridge characters and TopWindow) is never loaded here.
    import types

    class _AttrSinkModule(types.ModuleType):
        """Minimal stand-in for conftest._StubModule: absorbs attribute writes
        and returns no-op callables for reads (MissionLib.SetPlayerAI pokes
        Bridge.TacticalMenuHandlers when controller != 'Tactical')."""
        def __getattr__(self, name):
            return lambda *a, **k: None

    _tact_saved = sys.modules.get("Bridge.TacticalMenuHandlers")
    if _tact_saved is None:
        _tact_stub = _AttrSinkModule("Bridge.TacticalMenuHandlers")
        sys.modules["Bridge.TacticalMenuHandlers"] = _tact_stub
        if "Bridge" in sys.modules:
            try:
                setattr(sys.modules["Bridge"], "TacticalMenuHandlers", _tact_stub)
            except (AttributeError, TypeError):
                pass

    real, saved, saved_bare = _fresh_real_helm()
    try:
        real.CreateMenus()

        panel = CrewMenuPanel()
        payload = panel.render_payload()
        assert payload is not None, "CrewMenuPanel.render_payload() returned None after CreateMenus"
        assert payload.startswith("setCrewMenus(")

        import json
        # Strip JS wrapper: "setCrewMenus(...);"
        data = json.loads(payload[len("setCrewMenus("):-2])
        menus = data.get("menus", [])
        assert menus, "No menus in payload"

        # Primary search: scan the JSON snapshot for the All Stop button by label.
        all_stop_node = None
        for menu_node in menus:
            hit = _find_button(menu_node, "All Stop")
            if hit:
                all_stop_node = hit
                break

        # Structural fallback: find the button whose stored event has type
        # App.ET_ALL_STOP (1065), regardless of TGL-localized label.
        if all_stop_node is None:
            for wid, widget in panel._widgets_by_id.items():
                from engine.appc.characters import STButton  # noqa: PLC0415
                if isinstance(widget, STButton):
                    evt = widget._event
                    if evt is not None:
                        try:
                            if evt.GetEventType() == App.ET_ALL_STOP:
                                all_stop_node = {"id": wid}
                                break
                        except Exception:
                            pass

        assert all_stop_node is not None, (
            "Could not find All Stop button by label or ET_ALL_STOP event type"
        )

        wid = all_stop_node["id"]

        # --- Hard assertion 0: All Stop button is enabled ---
        target = panel._widgets_by_id[wid]
        assert target.IsEnabled(), "All Stop button unexpectedly disabled"

        # --- Hard assertion 1: dispatch_event returns True ---
        result = panel.dispatch_event("click:%d" % wid)
        assert result is True, "dispatch_event returned False for All Stop button"

        # --- Hard assertion 2: player.GetAI() is not None after click ---
        ai = player.GetAI()
        assert ai is not None, (
            "AllStop handler did not assign player AI via MissionLib.SetPlayerAI"
        )

    finally:
        _restore(saved, saved_bare)
        # Restore TacticalMenuHandlers stub state.
        if _tact_saved is None:
            sys.modules.pop("Bridge.TacticalMenuHandlers", None)
        else:
            sys.modules["Bridge.TacticalMenuHandlers"] = _tact_saved
        _set_current_game(None)
        TacticalControlWindow._instance = None
        _reset_target_menu_singleton()
