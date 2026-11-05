"""End-to-end: load Bridge.TacticalMenuHandlers.CreateTargetList,
populate a real ship with subsystems via the bridge set, and verify
the list row is flat and the target panel carries its subsystem families."""
import json
import App
from engine.appc.ships import ShipClass_Create
from engine.appc.sets import SetClass


def test_full_pipeline_real_sdk_real_ship_real_subsystems():
    from engine.core.game import Game, Episode, Mission, _set_current_game
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
    bridge = App.g_kSetManager.GetSet("bridge")
    if bridge is None:
        bridge = SetClass()
        App.g_kSetManager.AddSet(bridge, "bridge")
    try:
        # Spawn a real ship with default subsystems.
        kor = ShipClass_Create("Kor")
        kor.SetName("Kor")
        bridge.AddObjectToSet(kor, "Kor")

        # The menu's children are DERIVED from a pushed contact list, so
        # membership comes from the set explicitly rather than from an
        # add-event subscriber.
        menu = App.STTargetMenu_GetTargetMenu()
        menu.RebuildShipMenus(bridge)
        menu.ResetAffiliationColors()
        row = menu.GetObjectEntry(kor)
        assert row is not None
        assert row.GetAffiliation() == "ENEMY"
        assert len(row._children) > 0  # subsystems populated

        # The list is flat now: a row carries no subsystem tree. The ship's
        # subsystems are the target panel's `families`.
        view = TargetListView()
        state = json.loads(view.render_payload()[len("setTargetList("):-2])
        kor_row = next(r for r in state["rows"] if r["name"] == "Kor")
        assert kor_row["affiliation"] == "ENEMY"
        assert "subsystems" not in kor_row

        from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_TARGET
        player.SetTarget(kor)
        player.GetSensorSubsystem().AddKnownObject(kor)
        panel = ShipDisplayPanel(ROLE_TARGET)
        script = panel.render_payload()
        payload = json.loads(script[len('setShipDisplay("target", '):-2])
        assert payload["ship_name"] == "Kor"
        assert len(payload["families"]) > 0
        names = [f["name"] for f in payload["families"]]
        assert "Hull" not in names
        for fam in payload["families"]:
            assert isinstance(fam["name"], str) and fam["name"]
            assert fam["state"] in ("healthy", "damaged", "disabled",
                                    "destroyed")
            for m in fam["members"]:
                assert isinstance(m["name"], str) and m["name"]
    finally:
        _set_current_game(None)
