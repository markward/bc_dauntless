import json
import App
from engine.appc.ships import ShipClass


def _setup_game_with_player():
    from engine.core.game import Game, Episode, Mission, _set_current_game
    mission = Mission()
    episode = Episode(); episode.SetCurrentMission(mission)
    game = Game(); game.SetCurrentEpisode(episode)
    player = ShipClass(); player.SetName("Player")
    game.SetPlayer(player)
    _set_current_game(game)
    return game, player, mission


def test_view_payload_lists_rows_with_affiliations():
    from engine.ui.target_list_view import TargetListView
    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    game, player, mission = _setup_game_with_player()
    try:
        mission.GetFriendlyGroup().AddName("Dauntless")
        mission.GetEnemyGroup().AddName("Kor")

        a = ShipClass(); a.SetName("Dauntless")
        b = ShipClass(); b.SetName("Kor")
        target_menu.RebuildShipMenu(a)
        target_menu.RebuildShipMenu(b)
        target_menu.ResetAffiliationColors()

        view = TargetListView()
        script = view.render_payload()
        assert script is not None
        assert script.startswith("setTargetList(")
        body = script[len("setTargetList("):-2]
        state = json.loads(body)
        assert state["visible"] is True
        names = [r["name"] for r in state["rows"]]
        assert names == ["Dauntless", "Kor"]
        affiliations = [r["affiliation"] for r in state["rows"]]
        assert affiliations == ["FRIENDLY", "ENEMY"]
        assert state["selected"] is None
    finally:
        from engine.core.game import _set_current_game
        _set_current_game(None)


def test_view_payload_is_idempotent_until_state_changes():
    from engine.ui.target_list_view import TargetListView
    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    _setup_game_with_player()
    try:
        view = TargetListView()
        first = view.render_payload()
        assert first is not None
        # Nothing changed — must return None.
        assert view.render_payload() is None

        # A row added → next call re-emits.
        a = ShipClass(); a.SetName("X")
        target_menu.RebuildShipMenu(a)
        assert view.render_payload() is not None
    finally:
        from engine.core.game import _set_current_game
        _set_current_game(None)


def test_view_dispatch_event_sets_player_target():
    from engine.ui.target_list_view import TargetListView
    from engine.appc.sets import SetClass
    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    game, player, mission = _setup_game_with_player()
    bridge_set = SetClass()
    App.g_kSetManager.AddSet(bridge_set, "bridge")
    try:
        a = ShipClass(); a.SetName("Dauntless")
        target_menu.RebuildShipMenu(a)
        bridge = App.g_kSetManager.GetSet("bridge")
        bridge.AddObjectToSet(a, "Dauntless")

        view = TargetListView()
        handled = view.dispatch_event("Dauntless")
        assert handled is True
        assert player.GetTarget() is a
    finally:
        App.g_kSetManager.DeleteSet("bridge")
        from engine.core.game import _set_current_game
        _set_current_game(None)


def test_view_payload_includes_subsystems_and_health():
    """Each row carries hull%, shield%, and a flat list of subsystem
    names. selected_subsystem mirrors player.GetTargetSubsystem()."""
    import json
    from engine.ui.target_list_view import TargetListView
    from engine.appc.ships import ShipClass_Create

    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    game, player, mission = _setup_game_with_player()
    try:
        ship = ShipClass_Create("Galaxy")
        ship.SetName("USS Galaxy")
        target_menu.RebuildShipMenu(ship)
        bridge = App.g_kSetManager.GetSet("bridge")
        if bridge is None:
            from engine.appc.sets import SetClass
            bridge = SetClass()
            App.g_kSetManager.AddSet(bridge, "bridge")
        bridge.AddObjectToSet(ship, "USS Galaxy")
        player.SetTarget("USS Galaxy")
        # Pick the first subsystem as the targeted subsystem.
        first_sub = ship.StartGetSubsystemMatch(App.CT_SHIP_SUBSYSTEM)
        first_sub_obj = ship.GetNextSubsystemMatch(first_sub)
        ship.EndGetSubsystemMatch(first_sub)
        player.SetTargetSubsystem(first_sub_obj)

        view = TargetListView()
        script = view.render_payload()
        body = script[len("setTargetList("):-2]
        state = json.loads(body)

        assert state["selected"] == "USS Galaxy"
        assert state["selected_subsystem"] == first_sub_obj.GetName()
        row = state["rows"][0]
        assert "hull" in row and 0 <= row["hull"] <= 100
        assert "shields" in row and 0 <= row["shields"] <= 100
        assert isinstance(row["subsystems"], list)
        assert len(row["subsystems"]) > 0
        assert row["subsystems"][0]["name"]  # non-empty string
    finally:
        from engine.core.game import _set_current_game
        _set_current_game(None)


def test_dispatch_event_subsystem_click_sets_both_target_and_subsystem():
    from engine.ui.target_list_view import TargetListView
    from engine.appc.ships import ShipClass_Create

    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    game, player, mission = _setup_game_with_player()
    try:
        ship = ShipClass_Create("Galaxy")
        ship.SetName("USS Galaxy")
        target_menu.RebuildShipMenu(ship)
        bridge = App.g_kSetManager.GetSet("bridge")
        if bridge is None:
            from engine.appc.sets import SetClass
            bridge = SetClass()
            App.g_kSetManager.AddSet(bridge, "bridge")
        bridge.AddObjectToSet(ship, "USS Galaxy")
        # Find a real subsystem name to click.
        it = ship.StartGetSubsystemMatch(App.CT_SHIP_SUBSYSTEM)
        sub = ship.GetNextSubsystemMatch(it)
        ship.EndGetSubsystemMatch(it)
        assert sub is not None
        sub_name = sub.GetName()

        view = TargetListView()
        handled = view.dispatch_event(f"USS Galaxy/{sub_name}")

        assert handled is True
        assert player.GetTarget() is ship
        assert player.GetTargetSubsystem() is sub
    finally:
        from engine.core.game import _set_current_game
        _set_current_game(None)


def test_dispatch_event_ship_only_click_clears_subsystem():
    """Clicking the ship row (no subsystem) sets the target ship and
    clears any previously selected subsystem."""
    from engine.ui.target_list_view import TargetListView
    from engine.appc.ships import ShipClass_Create

    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    game, player, mission = _setup_game_with_player()
    try:
        ship = ShipClass_Create("Galaxy")
        ship.SetName("USS Galaxy")
        target_menu.RebuildShipMenu(ship)
        bridge = App.g_kSetManager.GetSet("bridge")
        if bridge is None:
            from engine.appc.sets import SetClass
            bridge = SetClass()
            App.g_kSetManager.AddSet(bridge, "bridge")
        bridge.AddObjectToSet(ship, "USS Galaxy")
        it = ship.StartGetSubsystemMatch(App.CT_SHIP_SUBSYSTEM)
        sub = ship.GetNextSubsystemMatch(it)
        ship.EndGetSubsystemMatch(it)
        player.SetTargetSubsystem(sub)
        assert player.GetTargetSubsystem() is sub

        view = TargetListView()
        view.dispatch_event("USS Galaxy")

        assert player.GetTarget() is ship
        assert player.GetTargetSubsystem() is None
    finally:
        from engine.core.game import _set_current_game
        _set_current_game(None)


# ── Player exclusion ─────────────────────────────────────────────────────────

def test_view_payload_excludes_player_ship():
    """The player's own ship must not appear in the target list — it
    doesn't make sense to target yourself."""
    from engine.ui.target_list_view import TargetListView
    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    game, player, mission = _setup_game_with_player()
    try:
        # Add both the player and an enemy to the menu.
        target_menu.AddChild(App.STSubsystemMenu(player, "Player"))
        enemy = ShipClass(); enemy.SetName("Kor")
        target_menu.AddChild(App.STSubsystemMenu(enemy, "Kor"))

        view = TargetListView()
        script = view.render_payload()
        body = script[len("setTargetList("):-2]
        state = json.loads(body)

        names = [r["name"] for r in state["rows"]]
        assert "Player" not in names
        assert "Kor" in names
    finally:
        from engine.core.game import _set_current_game
        _set_current_game(None)


# ── Accordion expansion ──────────────────────────────────────────────────────

def test_view_payload_rows_collapsed_by_default():
    """Fresh ship rows default to expanded=False so the panel renders
    compactly — the user opens the accordion explicitly."""
    from engine.ui.target_list_view import TargetListView
    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    game, player, mission = _setup_game_with_player()
    try:
        kor = ShipClass(); kor.SetName("Kor")
        target_menu.AddChild(App.STSubsystemMenu(kor, "Kor"))

        view = TargetListView()
        script = view.render_payload()
        body = script[len("setTargetList("):-2]
        state = json.loads(body)

        assert state["rows"][0]["expanded"] is False
    finally:
        from engine.core.game import _set_current_game
        _set_current_game(None)


def test_dispatch_event_toggle_expands_row():
    """The __toggle__ pseudo-subsystem flips a row's expansion state."""
    from engine.ui.target_list_view import TargetListView
    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    game, player, mission = _setup_game_with_player()
    try:
        kor = ShipClass(); kor.SetName("Kor")
        target_menu.AddChild(App.STSubsystemMenu(kor, "Kor"))

        view = TargetListView()
        # First emit captures the collapsed state in the snapshot cache.
        view.render_payload()

        # Toggle the row.
        handled = view.dispatch_event("Kor/__toggle__")
        assert handled is True

        # Next render shows the row expanded.
        script = view.render_payload()
        body = script[len("setTargetList("):-2]
        state = json.loads(body)
        assert state["rows"][0]["expanded"] is True

        # Toggle again to collapse.
        view.dispatch_event("Kor/__toggle__")
        script = view.render_payload()
        body = script[len("setTargetList("):-2]
        state = json.loads(body)
        assert state["rows"][0]["expanded"] is False
    finally:
        from engine.core.game import _set_current_game
        _set_current_game(None)


def test_dispatch_event_toggle_does_not_change_player_target():
    """A caret-click toggle is pure UI state — it must NOT set the
    target ship (that's the row-body click's job)."""
    from engine.ui.target_list_view import TargetListView
    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    game, player, mission = _setup_game_with_player()
    try:
        kor = ShipClass(); kor.SetName("Kor")
        target_menu.AddChild(App.STSubsystemMenu(kor, "Kor"))

        view = TargetListView()
        assert player.GetTarget() is None

        view.dispatch_event("Kor/__toggle__")

        # Target unchanged by the toggle action.
        assert player.GetTarget() is None
    finally:
        from engine.core.game import _set_current_game
        _set_current_game(None)


# ── Health-bar percent encoding (Issue 1) ────────────────────────────────────

def _make_targeted_ship(name="USS Galaxy"):
    """Build a ShipClass via ShipClass_Create and register it in the
    bridge set so `SetTarget(name)` can resolve it. Caller must still
    add the ship to the target menu (e.g., via
    `target_menu.RebuildShipMenu(ship)`) for it to appear in render
    output. Caller is responsible for game + bridge-set teardown."""
    from engine.appc.ships import ShipClass_Create
    from engine.appc.sets import SetClass
    ship = ShipClass_Create("Galaxy")
    ship.SetName(name)
    bridge = App.g_kSetManager.GetSet("bridge")
    if bridge is None:
        bridge = SetClass()
        App.g_kSetManager.AddSet(bridge, "bridge")
    bridge.AddObjectToSet(ship, name)
    return ship


def test_view_payload_hull_pct_is_integer_percent_not_ratio():
    """A hull at 50% condition must report hull == 50 (not 0 or 1).
    Regression test for the missing * 100 — GetConditionPercentage
    returns [0.0, 1.0]."""
    from engine.ui.target_list_view import TargetListView
    from engine.appc.subsystems import HullSubsystem

    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    game, player, mission = _setup_game_with_player()
    try:
        ship = _make_targeted_ship("Half-hull")
        hull = HullSubsystem("Hull")
        hull.SetMaxCondition(1000.0)
        hull.SetCondition(500.0)
        ship.SetHull(hull)
        target_menu.RebuildShipMenu(ship)

        view = TargetListView()
        script = view.render_payload()
        body = script[len("setTargetList("):-2]
        state = json.loads(body)
        row = next(r for r in state["rows"] if r["name"] == "Half-hull")
        assert row["hull"] == 50
    finally:
        App.g_kSetManager.DeleteSet("bridge")
        from engine.core.game import _set_current_game
        _set_current_game(None)


def test_view_payload_shield_pct_is_integer_percent_not_ratio():
    """A fully-shielded ship must report shields == 100 (not 1).
    Regression test for the missing * 100."""
    from engine.ui.target_list_view import TargetListView
    from engine.appc.subsystems import ShieldSubsystem

    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    game, player, mission = _setup_game_with_player()
    try:
        ship = _make_targeted_ship("Full-shields")
        shields = ship.GetShields()
        # Seed all six faces; SetMaxShields seeds current when current==0.
        for face in range(ShieldSubsystem.NUM_SHIELDS):
            shields.SetMaxShields(face, 1000.0)
        target_menu.RebuildShipMenu(ship)

        view = TargetListView()
        script = view.render_payload()
        body = script[len("setTargetList("):-2]
        state = json.loads(body)
        row = next(r for r in state["rows"] if r["name"] == "Full-shields")
        assert row["shields"] == 100
    finally:
        App.g_kSetManager.DeleteSet("bridge")
        from engine.core.game import _set_current_game
        _set_current_game(None)
