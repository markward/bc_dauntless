"""End-to-end: load Bridge.TacticalMenuHandlers.CreateTargetList,
populate a real ship with subsystems via the bridge set, and verify
the rendered payload contains nested subsystems + health bars."""
import json
import App
from engine.appc.ships import ShipClass_Create
from engine.appc.sets import SetClass


def test_full_pipeline_real_sdk_real_ship_real_subsystems():
    from engine.core.game import Game, Episode, Mission, _set_current_game
    from engine.appc.target_menu import wire_to_bridge_set
    from engine.ui.target_list_view import TargetListView

    App._reset_target_menu_singleton()

    # Construct the menu via the real SDK call.
    import Bridge.TacticalMenuHandlers as TMH
    pTacticalWindow = App.TacticalControlWindow_GetTacticalControlWindow()
    TMH.CreateTargetList(pTacticalWindow)

    # Set up game + bridge set.
    mission = Mission()
    mission.GetEnemyGroup().AddName("Kor")
    episode = Episode(); episode.SetCurrentMission(mission)
    game = Game(); game.SetCurrentEpisode(episode)
    player = ShipClass_Create("Galaxy")
    player.SetName("Player")
    game.SetPlayer(player)
    _set_current_game(game)
    try:
        bridge = App.g_kSetManager.GetSet("bridge")
        if bridge is None:
            bridge = SetClass()
            App.g_kSetManager.AddSet(bridge, "bridge")
        wire_to_bridge_set(bridge)

        # Spawn a real ship with default subsystems.
        kor = ShipClass_Create("Kor")
        kor.SetName("Kor")
        bridge.AddObjectToSet(kor, "Kor")  # fires the subscriber → RebuildShipMenu

        # Verify the row landed in the singleton with subsystems.
        menu = App.STTargetMenu_GetTargetMenu()
        row = menu.GetObjectEntry(kor)
        assert row is not None
        assert row.GetAffiliation() == "ENEMY"
        assert len(row._children) > 0  # subsystems populated

        # Render the view payload and verify the shape.
        view = TargetListView()
        script = view.render_payload()
        body = script[len("setTargetList("):-2]
        state = json.loads(body)
        kor_row = next(r for r in state["rows"] if r["name"] == "Kor")
        assert kor_row["affiliation"] == "ENEMY"
        assert "hull" in kor_row and 0 <= kor_row["hull"] <= 100
        assert "shields" in kor_row and 0 <= kor_row["shields"] <= 100
        assert isinstance(kor_row["subsystems"], list)
        assert len(kor_row["subsystems"]) > 0
        subsystem_names = [s["name"] for s in kor_row["subsystems"]]
        # All names are non-empty strings.
        for n in subsystem_names:
            assert isinstance(n, str) and n
    finally:
        _set_current_game(None)
