"""SensorsPanel snapshot + payload tests. The projection itself is
already covered by tests/unit/test_radar_projection.py — these tests
exercise the panel's read-from-game-state, filter, emit pipeline."""
import json
import App
from engine.appc.ships import ShipClass
from engine.appc.math import TGPoint3


def _setup_game():
    from engine.core.game import Game, Episode, Mission, _set_current_game
    mission = Mission()
    episode = Episode(); episode.SetCurrentMission(mission)
    game = Game(); game.SetCurrentEpisode(episode)
    player = ShipClass(); player.SetName("Player")
    game.SetPlayer(player)
    _set_current_game(game)
    return game, player, mission


def _make_ship(name, x=0.0, y=0.0, z=0.0):
    s = ShipClass()
    s.SetName(name)
    s.SetTranslate(TGPoint3(x, y, z))
    return s


def test_payload_lists_visible_contacts_with_affiliations():
    from engine.ui.sensors_panel import SensorsPanel
    from engine.appc.sets import SetClass

    App._reset_target_menu_singleton()
    menu = App.STTargetMenu_CreateW("Targets")
    game, player, mission = _setup_game()
    try:
        mission.GetFriendlyGroup().AddName("Ally")
        mission.GetEnemyGroup().AddName("Foe")

        ally = _make_ship("Ally", x=0.0, y=2000.0, z=0.0)
        foe  = _make_ship("Foe",  x=3000.0, y=0.0, z=500.0)
        far  = _make_ship("Far",  x=0.0, y=99999.0, z=0.0)  # off-disc

        spatial = SetClass()
        App.g_kSetManager.AddSet(spatial, "test_set")
        spatial.AddObjectToSet(ally, "Ally")
        spatial.AddObjectToSet(foe, "Foe")
        spatial.AddObjectToSet(far, "Far")
        player._containing_set = spatial

        for s in (ally, foe, far):
            menu.RebuildShipMenu(s)
        menu.ResetAffiliationColors()
        # All three rows visible (sensor visibility runs separately).
        for child in menu._children:
            child.SetVisible()

        panel = SensorsPanel()
        script = panel.render_payload()
        assert script is not None
        assert script.startswith("setRadar(")
        body = script[len("setRadar("):-2]
        state = json.loads(body)

        assert state["visible"] is True
        names = sorted(c["name"] for c in state["contacts"])
        # "Far" is outside disc range → filtered out
        assert names == ["Ally", "Foe"]
        by_name = {c["name"]: c for c in state["contacts"]}
        assert by_name["Ally"]["affiliation"] == "FRIENDLY"
        assert by_name["Foe"]["affiliation"] == "ENEMY"
    finally:
        App.g_kSetManager.DeleteSet("test_set")
        from engine.core.game import _set_current_game
        _set_current_game(None)


def test_payload_is_idempotent_until_state_changes():
    from engine.ui.sensors_panel import SensorsPanel
    from engine.appc.sets import SetClass

    App._reset_target_menu_singleton()
    menu = App.STTargetMenu_CreateW("Targets")
    game, player, mission = _setup_game()
    try:
        ship = _make_ship("X", x=0.0, y=1000.0, z=0.0)
        spatial = SetClass()
        App.g_kSetManager.AddSet(spatial, "test_set")
        spatial.AddObjectToSet(ship, "X")
        player._containing_set = spatial
        menu.RebuildShipMenu(ship)
        menu._children[0].SetVisible()

        panel = SensorsPanel()
        first = panel.render_payload()
        assert first is not None
        # Nothing changed → None on the next tick.
        assert panel.render_payload() is None

        # Ship moves → next call re-emits.
        ship.SetTranslate(TGPoint3(0.0, 2000.0, 0.0))
        assert panel.render_payload() is not None
    finally:
        App.g_kSetManager.DeleteSet("test_set")
        from engine.core.game import _set_current_game
        _set_current_game(None)


def test_payload_marks_targeted_contact():
    from engine.ui.sensors_panel import SensorsPanel
    from engine.appc.sets import SetClass

    App._reset_target_menu_singleton()
    menu = App.STTargetMenu_CreateW("Targets")
    game, player, mission = _setup_game()
    try:
        ship = _make_ship("Galaxy", x=0.0, y=1500.0, z=0.0)
        spatial = SetClass()
        App.g_kSetManager.AddSet(spatial, "test_set")
        spatial.AddObjectToSet(ship, "Galaxy")
        player._containing_set = spatial
        menu.RebuildShipMenu(ship)
        menu._children[0].SetVisible()
        # Add to bridge set so player.SetTarget("Galaxy") resolves.
        bridge = App.g_kSetManager.GetSet("bridge")
        if bridge is None:
            bridge = SetClass()
            App.g_kSetManager.AddSet(bridge, "bridge")
        bridge.AddObjectToSet(ship, "Galaxy")
        player.SetTarget("Galaxy")

        panel = SensorsPanel()
        script = panel.render_payload()
        body = script[len("setRadar("):-2]
        state = json.loads(body)
        assert len(state["contacts"]) == 1
        assert state["contacts"][0]["targeted"] is True
    finally:
        App.g_kSetManager.DeleteSet("test_set")
        App.g_kSetManager.DeleteSet("bridge")
        from engine.core.game import _set_current_game
        _set_current_game(None)


def test_payload_skips_invisible_rows():
    from engine.ui.sensors_panel import SensorsPanel
    from engine.appc.sets import SetClass

    App._reset_target_menu_singleton()
    menu = App.STTargetMenu_CreateW("Targets")
    game, player, mission = _setup_game()
    try:
        ship = _make_ship("Cloaked", x=0.0, y=1000.0, z=0.0)
        spatial = SetClass()
        App.g_kSetManager.AddSet(spatial, "test_set")
        spatial.AddObjectToSet(ship, "Cloaked")
        player._containing_set = spatial
        menu.RebuildShipMenu(ship)
        menu._children[0].SetNotVisible()  # not picked up by sensors

        panel = SensorsPanel()
        script = panel.render_payload()
        body = script[len("setRadar("):-2]
        state = json.loads(body)
        assert state["contacts"] == []
    finally:
        App.g_kSetManager.DeleteSet("test_set")
        from engine.core.game import _set_current_game
        _set_current_game(None)


def test_hidden_panel_emits_visible_false():
    from engine.ui.sensors_panel import SensorsPanel

    _setup_game()
    try:
        panel = SensorsPanel()
        panel.visible = False
        script = panel.render_payload()
        body = script[len("setRadar("):-2]
        state = json.loads(body)
        assert state["visible"] is False
        # No need to enumerate contacts when the panel is hidden.
        assert state.get("contacts", []) == []
    finally:
        from engine.core.game import _set_current_game
        _set_current_game(None)
