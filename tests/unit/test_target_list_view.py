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


# ── Per-subsystem condition (Issue 2) ────────────────────────────────────────

def test_view_payload_subsystems_carry_condition_pct():
    """Each subsystem entry in the snapshot includes a `condition`
    integer percent reflecting its live condition."""
    from engine.ui.target_list_view import TargetListView

    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    game, player, mission = _setup_game_with_player()
    try:
        ship = _make_targeted_ship("USS Galaxy")
        # Drop the first subsystem on the ship to 75% condition.
        it = ship.StartGetSubsystemMatch(App.CT_SHIP_SUBSYSTEM)
        first_sub = ship.GetNextSubsystemMatch(it)
        ship.EndGetSubsystemMatch(it)
        first_sub.SetMaxCondition(400.0)
        first_sub.SetCondition(300.0)
        damaged_name = first_sub.GetName()

        target_menu.RebuildShipMenu(ship)
        view = TargetListView()
        script = view.render_payload()
        body = script[len("setTargetList("):-2]
        state = json.loads(body)

        row = next(r for r in state["rows"] if r["name"] == "USS Galaxy")
        damaged_entry = next(s for s in row["subsystems"] if s["name"] == damaged_name)
        assert damaged_entry["condition"] == 75
        # Untouched subsystems stay at 100%.
        for entry in row["subsystems"]:
            assert "condition" in entry
            assert 0 <= entry["condition"] <= 100
            if entry["name"] != damaged_name:
                assert entry["condition"] == 100
    finally:
        App.g_kSetManager.DeleteSet("bridge")
        from engine.core.game import _set_current_game
        _set_current_game(None)


def test_query_subsystem_condition_prefers_combined_over_individual():
    """When a subsystem exposes GetCombinedConditionPercentage, the
    helper uses it (so future parent-weapon aggregation surfaces in
    the panel). When only GetConditionPercentage exists, it falls back."""
    from engine.ui.target_list_view import _query_subsystem_condition

    class FakeWeapons:
        def GetName(self): return "Weapons"
        def GetConditionPercentage(self): return 1.0
        def GetCombinedConditionPercentage(self): return 0.4  # aggregate with damaged children

    class FakeShip:
        def __init__(self, sub): self._sub = sub
        def StartGetSubsystemMatch(self, _ct): return iter([self._sub])
        def GetNextSubsystemMatch(self, it):
            try: return next(it)
            except StopIteration: return None
        def EndGetSubsystemMatch(self, _it): pass

    aggregated = FakeWeapons()
    assert _query_subsystem_condition(FakeShip(aggregated), "Weapons") == 40

    class FakeImpulse:
        def GetName(self): return "Impulse"
        def GetConditionPercentage(self): return 0.6
        # no GetCombinedConditionPercentage

    flat = FakeImpulse()
    assert _query_subsystem_condition(FakeShip(flat), "Impulse") == 60


# ── Nested children + expansion reach the payload (end-to-end) ───────────────

def test_nested_children_and_expanded_reach_payload():
    """End-to-end: a phaser aggregator with two banks must surface in
    render_payload's JSON as a "Phasers" subsystem entry whose
    `children` lists both banks, and toggling the aggregator flips its
    `expanded` flag in the payload."""
    from engine.ui.target_list_view import TargetListView
    from engine.appc.ships import ShipClass_Create
    from engine.appc.properties import WeaponSystemProperty, PhaserProperty

    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    game, player, mission = _setup_game_with_player()
    try:
        ship = ShipClass_Create("X")
        ship.SetName("USS Galaxy")
        ps = ship.GetPropertySet()
        phasers = WeaponSystemProperty("Phasers")
        phasers.SetWeaponSystemType(WeaponSystemProperty.WST_PHASER)
        ps.AddToSet("Scene Root", phasers)
        ps.AddToSet("Scene Root", PhaserProperty("Dorsal Phaser 1"))
        ps.AddToSet("Scene Root", PhaserProperty("Dorsal Phaser 2"))
        ship.SetupProperties()
        target_menu.RebuildShipMenu(ship)

        view = TargetListView()
        # Prime the snapshot cache before toggling.
        view.render_payload()

        # Expand the Phasers aggregator (2nd-level accordion).
        handled = view.dispatch_event_subsystem_toggle("USS Galaxy", "Phasers")
        assert handled is True

        script = view.render_payload()
        body = script[len("setTargetList("):-2]
        state = json.loads(body)

        row = next(r for r in state["rows"] if r["name"] == "USS Galaxy")
        phasers_entry = next(s for s in row["subsystems"] if s["name"] == "Phasers")

        assert phasers_entry["expanded"] is True
        assert len(phasers_entry["children"]) == 2
        child_names = sorted(c["name"] for c in phasers_entry["children"])
        assert child_names == ["Dorsal Phaser 1", "Dorsal Phaser 2"]
    finally:
        from engine.core.game import _set_current_game
        _set_current_game(None)


def test_query_subsystem_condition_defaults_to_100_when_resolution_misses():
    """If the subsystem can't be found on the ship, default to 100 so
    the bar renders full rather than misleadingly empty."""
    from engine.ui.target_list_view import _query_subsystem_condition

    class EmptyShip:
        def StartGetSubsystemMatch(self, _ct): return iter([])
        def GetNextSubsystemMatch(self, it):
            try: return next(it)
            except StopIteration: return None
        def EndGetSubsystemMatch(self, _it): pass

    assert _query_subsystem_condition(EmptyShip(), "Phantom") == 100
    assert _query_subsystem_condition(None, "Anything") == 100
    assert _query_subsystem_condition(EmptyShip(), "") == 100


def test_destroyed_ship_excluded_from_target_list():
    """A ship that is dying or dead (death sequence in progress) must drop
    off the target list immediately, not linger for the throes window."""
    from engine.ui.target_list_view import TargetListView
    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    game, player, mission = _setup_game_with_player()
    try:
        alive = ShipClass(); alive.SetName("Alive")
        doomed = ShipClass(); doomed.SetName("Doomed")
        target_menu.RebuildShipMenu(alive)
        target_menu.RebuildShipMenu(doomed)

        doomed.SetDying(True)   # death sequence started -> not a valid target

        view = TargetListView()
        script = view.render_payload()
        assert script is not None
        body = script[len("setTargetList("):-2]
        state = json.loads(body)
        names = [r["name"] for r in state["rows"]]
        assert names == ["Alive"]

        # A fully dead ship is likewise excluded.
        alive.SetDead(True)
        view.invalidate()
        script2 = view.render_payload()
        body2 = script2[len("setTargetList("):-2]
        names2 = [r["name"] for r in json.loads(body2)["rows"]]
        assert names2 == []
    finally:
        from engine.core.game import _set_current_game
        _set_current_game(None)


def test_destroyed_ship_lingers_in_list_then_drops_after_removal():
    """A ship in its death/linger window stays selectable in the target list;
    once ship_death finally removes it, it drops off."""
    import json
    from engine.ui.target_list_view import TargetListView
    from engine.appc.ships import ShipClass
    from engine.appc import ship_death

    ship_death.reset()
    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    game, player, mission = _setup_game_with_player()
    try:
        wreck = ShipClass(); wreck.SetName("Doomed")
        target_menu.RebuildShipMenu(wreck)

        # Enter the death sequence: now dying (out of action) but a wreck.
        ship_death.begin(wreck)
        view = TargetListView()
        state = json.loads(view.render_payload()[len("setTargetList("):-2])
        assert "Doomed" in [r["name"] for r in state["rows"]]   # listed as a wreck

        # Run out the throes + linger -> final removal -> no longer a wreck.
        ship_death.advance(ship_death.THROES_DURATION)
        ship_death.advance(ship_death.WRECK_LINGER_DURATION)
        assert ship_death.is_targetable_wreck(wreck) is False
        state2 = json.loads(view.render_payload()[len("setTargetList("):-2])
        assert "Doomed" not in [r["name"] for r in state2["rows"]]
    finally:
        ship_death.reset()
        from engine.core.game import _set_current_game
        _set_current_game(None)


# ── Destroyed-subsystem delisting + lock handoff ─────────────────────────────

def _make_phaser_aggregator_ship(name="USS Galaxy"):
    """Build a targeted ship carrying a Phasers aggregator subsystem with
    two child banks, registered in the bridge set so SetTarget resolves it.
    Returns the ship."""
    from engine.appc.ships import ShipClass_Create
    from engine.appc.sets import SetClass
    from engine.appc.properties import WeaponSystemProperty, PhaserProperty

    ship = ShipClass_Create("Galaxy")
    ship.SetName(name)
    bridge = App.g_kSetManager.GetSet("bridge")
    if bridge is None:
        bridge = SetClass()
        App.g_kSetManager.AddSet(bridge, "bridge")
    bridge.AddObjectToSet(ship, name)

    ps = ship.GetPropertySet()
    phasers = WeaponSystemProperty("Phasers")
    phasers.SetWeaponSystemType(WeaponSystemProperty.WST_PHASER)
    ps.AddToSet("Scene Root", phasers)
    ps.AddToSet("Scene Root", PhaserProperty("Dorsal Phaser 1"))
    ps.AddToSet("Scene Root", PhaserProperty("Dorsal Phaser 2"))
    ship.SetupProperties()
    return ship


def _resolve(ship, name):
    from engine.ui.target_list_view import _resolve_subsystem_by_name
    return _resolve_subsystem_by_name(ship, name)


def test_destroyed_child_subsystem_removed_but_parent_kept():
    """A child subsystem at zero condition drops off its parent's child
    list, but the parent stays as long as a sibling survives."""
    from engine.ui.target_list_view import TargetListView
    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    game, player, mission = _setup_game_with_player()
    try:
        ship = _make_phaser_aggregator_ship()
        target_menu.RebuildShipMenu(ship)

        _resolve(ship, "Dorsal Phaser 1").SetCondition(0.0)  # destroyed

        view = TargetListView()
        script = view.render_payload()
        state = json.loads(script[len("setTargetList("):-2])
        row = next(r for r in state["rows"] if r["name"] == "USS Galaxy")
        phasers = next(s for s in row["subsystems"] if s["name"] == "Phasers")
        child_names = [c["name"] for c in phasers["children"]]
        assert child_names == ["Dorsal Phaser 2"]
    finally:
        App.g_kSetManager.DeleteSet("bridge")
        from engine.core.game import _set_current_game
        _set_current_game(None)


def test_parent_delisted_when_all_children_destroyed():
    """When every child of a parent group is destroyed, the parent itself
    drops off the target list."""
    from engine.ui.target_list_view import TargetListView
    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    game, player, mission = _setup_game_with_player()
    try:
        ship = _make_phaser_aggregator_ship()
        target_menu.RebuildShipMenu(ship)

        _resolve(ship, "Dorsal Phaser 1").SetCondition(0.0)
        _resolve(ship, "Dorsal Phaser 2").SetCondition(0.0)

        view = TargetListView()
        script = view.render_payload()
        state = json.loads(script[len("setTargetList("):-2])
        row = next(r for r in state["rows"] if r["name"] == "USS Galaxy")
        names = [s["name"] for s in row["subsystems"]]
        assert "Phasers" not in names
    finally:
        App.g_kSetManager.DeleteSet("bridge")
        from engine.core.game import _set_current_game
        _set_current_game(None)


def test_destroyed_leaf_subsystem_removed_from_list():
    """A top-level subsystem with no children, when destroyed, drops off."""
    from engine.ui.target_list_view import TargetListView
    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    game, player, mission = _setup_game_with_player()
    try:
        ship = _make_targeted_ship("USS Galaxy")
        # Pick the first top-level subsystem that has no children.
        it = ship.StartGetSubsystemMatch(App.CT_SHIP_SUBSYSTEM)
        leaf = None
        sub = ship.GetNextSubsystemMatch(it)
        while sub is not None:
            if sub.GetNumChildSubsystems() == 0:
                leaf = sub
                break
            sub = ship.GetNextSubsystemMatch(it)
        ship.EndGetSubsystemMatch(it)
        assert leaf is not None
        leaf_name = leaf.GetName()
        leaf.SetCondition(0.0)

        target_menu.RebuildShipMenu(ship)
        view = TargetListView()
        script = view.render_payload()
        state = json.loads(script[len("setTargetList("):-2])
        row = next(r for r in state["rows"] if r["name"] == "USS Galaxy")
        names = [s["name"] for s in row["subsystems"]]
        assert leaf_name not in names
    finally:
        App.g_kSetManager.DeleteSet("bridge")
        from engine.core.game import _set_current_game
        _set_current_game(None)


def test_locked_subsystem_destroyed_reassigns_to_next_sibling():
    """When the locked subsystem is destroyed, the lock moves to the next
    surviving sibling in the same group."""
    from engine.ui.target_list_view import TargetListView
    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    game, player, mission = _setup_game_with_player()
    try:
        ship = _make_phaser_aggregator_ship()
        target_menu.RebuildShipMenu(ship)
        bank1 = _resolve(ship, "Dorsal Phaser 1")
        bank2 = _resolve(ship, "Dorsal Phaser 2")
        player.SetTarget("USS Galaxy")
        player.SetTargetSubsystem(bank1)

        bank1.SetCondition(0.0)  # destroyed
        view = TargetListView()
        view.render_payload()  # drives reconciliation

        assert player.GetTargetSubsystem() is bank2
    finally:
        App.g_kSetManager.DeleteSet("bridge")
        from engine.core.game import _set_current_game
        _set_current_game(None)


def test_last_child_destroyed_clears_lock_to_ship_level():
    """When the last surviving child in the group is destroyed, the
    subsystem lock clears (back to ship-level targeting)."""
    from engine.ui.target_list_view import TargetListView
    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    game, player, mission = _setup_game_with_player()
    try:
        ship = _make_phaser_aggregator_ship()
        target_menu.RebuildShipMenu(ship)
        bank1 = _resolve(ship, "Dorsal Phaser 1")
        bank2 = _resolve(ship, "Dorsal Phaser 2")
        player.SetTarget("USS Galaxy")
        player.SetTargetSubsystem(bank2)

        bank1.SetCondition(0.0)
        bank2.SetCondition(0.0)  # whole group gone
        view = TargetListView()
        view.render_payload()  # drives reconciliation

        assert player.GetTargetSubsystem() is None
    finally:
        App.g_kSetManager.DeleteSet("bridge")
        from engine.core.game import _set_current_game
        _set_current_game(None)
