import json
import App
from engine.appc.ships import ShipClass
from engine.appc.perception import Contact


def _listed(*ships):
    """Contact records for ships the player can see and target — what
    perceived_by returns for an in-range, uncloaked, living contact.

    set_contacts takes perception.Contact records rather than bare ships: the
    record carries the frame's verdict, and the menu derives the listing from
    `targetable`. Row IsVisible is NOT derived from `perceivable` — set_contacts
    asserts SetVisible() on every listed row, so that flag answers nothing about
    detectability; readers that need it read `perceivable` off the record.
    The distance is 0.0 because nothing in this file reads it.
    """
    return [Contact(ship=s, surface_gu=0.0,
                    perceivable=True, targetable=True) for s in ships]




def _pump(target_menu, player):
    """One frame of the host loop's contact push (host_loop._pump_contacts).

    The listing is DERIVED from the pushed record, so a change to a ship's
    state reaches the panel on the next push — as it does in game, where the
    push runs every frame before the panels render. The view no longer keeps
    its own copy of the cloak/death rule to short-circuit that.
    """
    from engine.appc.perception import perceived_by
    target_menu.set_contacts(perceived_by(player))


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
        target_menu.set_contacts(_listed(a, b))
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
        target_menu.set_contacts(_listed(a))
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
        target_menu.set_contacts(_listed(a))
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


def test_row_flag_does_not_gate_the_payload_drawability_is_targetable():
    """DRAWABILITY IS `targetable`, NOT the row's IsVisible flag.

    The view used to re-filter its rows on `child.IsVisible()`. Row visibility
    is PUMP-OWNED: `STTargetMenu.set_contacts` asserts `SetVisible()` on EVERY
    listed row, unconditionally, every frame — so on a frame that has been
    pushed the flag carries no information and the filter dropped nothing. The
    projection (`Contact.targetable`) is what decides what the panel draws.

    Between a `SetNotVisible` and the next push the two CAN disagree, and there
    the old filter was not redundant but wrong: it blanked a live contact from
    the panel. That is the window this test drives — `SetNotVisible` (real SDK
    surface, read by CycleTarget) with no intervening push. The row must still
    be drawn.
    """
    import json
    from engine.ui.target_list_view import TargetListView

    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    _setup_game_with_player()
    try:
        a = ShipClass(); a.SetName("Dauntless")
        target_menu.set_contacts(_listed(a))
        target_menu.GetObjectEntry(a).SetNotVisible()
        assert target_menu.GetObjectEntry(a).IsVisible() == 0  # not vacuous

        view = TargetListView()
        state = json.loads(view.render_payload()[len("setTargetList("):-2])

        assert [r["name"] for r in state["rows"]] == ["Dauntless"]
    finally:
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
        target_menu.set_contacts(_listed(ship))
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
        # Subsystem CONTENT is an expanded-row property now: a collapsed
        # row ships an empty list because the tree is only built when it
        # will be drawn. Expand so this asserts what it means to assert.
        view._expanded_ships.add(ship.GetName())
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
        target_menu.set_contacts(_listed(ship))
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


def test_dispatch_event_will_not_lock_a_non_targetable_group_header():
    """Clicking a group header ("Warp Engines") targets the SHIP but must not
    set a subsystem lock.

    BC flags every aggregator `SetTargetable(0)` — the player can lock the
    Port Warp nacelle, never the "Warp Engines" group. The header exists to
    organise the list, and the JS wires its row body to the same
    `target/<ship>/<subsystem>` action a lockable leaf uses, so the refusal
    has to be enforced here.
    """
    from engine.ui.target_list_view import TargetListView
    from engine.appc.ships import ShipClass_Create
    from engine.appc.properties import WeaponSystemProperty, PhaserProperty

    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    game, player, mission = _setup_game_with_player()
    try:
        ship = ShipClass_Create("Galaxy")
        ps = ship.GetPropertySet()
        group = WeaponSystemProperty("Phasers")
        group.SetWeaponSystemType(WeaponSystemProperty.WST_PHASER)
        group.SetTargetable(0)                     # as every real hardpoint does
        ps.AddToSet("Scene Root", group)
        leaf = PhaserProperty("Dorsal Phaser 1")
        leaf.SetTargetable(1)
        ps.AddToSet("Scene Root", leaf)
        ship.SetupProperties()
        ship.SetName("USS Galaxy")
        target_menu.set_contacts(_listed(ship))
        bridge = App.g_kSetManager.GetSet("bridge")
        if bridge is None:
            from engine.appc.sets import SetClass
            bridge = SetClass()
            App.g_kSetManager.AddSet(bridge, "bridge")
        bridge.AddObjectToSet(ship, "USS Galaxy")

        view = TargetListView()
        assert view.dispatch_event("USS Galaxy/Phasers") is True
        assert player.GetTarget() is ship
        assert player.GetTargetSubsystem() is None, \
            "a non-targetable group header must never become the subsystem lock"

        # The lockable leaf underneath it still locks normally.
        assert view.dispatch_event("USS Galaxy/Dorsal Phaser 1") is True
        assert player.GetTargetSubsystem() is not None
        assert player.GetTargetSubsystem().GetName() == "Dorsal Phaser 1"
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
        target_menu.set_contacts(_listed(ship))
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
        # Push both the player and an enemy as contacts.
        enemy = ShipClass(); enemy.SetName("Kor")
        target_menu.set_contacts(_listed(player, enemy))

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
        target_menu.set_contacts(_listed(kor))

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
        target_menu.set_contacts(_listed(kor))

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
        target_menu.set_contacts(_listed(kor))

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
    push the ship into the target menu's contact list (via
    `target_menu.set_contacts(_listed(ship))`) for it to appear in render
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
        target_menu.set_contacts(_listed(ship))

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
        target_menu.set_contacts(_listed(ship))

        view = TargetListView()
        script = view.render_payload()
        body = script[len("setTargetList("):-2]
        state = json.loads(body)
        row = next(r for r in state["rows"] if r["name"] == "Full-shields")
        assert row["shields"] == 100
        assert row["has_shields"] is True
    finally:
        App.g_kSetManager.DeleteSet("bridge")
        from engine.core.game import _set_current_game
        _set_current_game(None)


def test_view_payload_flags_shieldless_target():
    """A ship whose shield faces all have MaxShields==0 (e.g. an asteroid)
    reports has_shields=False so the view can drop the shield bar, even
    though GetShieldPercentage() returns the AI's 'not a factor' 1.0."""
    from engine.ui.target_list_view import TargetListView

    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    game, player, mission = _setup_game_with_player()
    try:
        ship = _make_targeted_ship("Inert-rock")  # ShipClass_Create → shields max 0
        target_menu.set_contacts(_listed(ship))

        view = TargetListView()
        script = view.render_payload()
        state = json.loads(script[len("setTargetList("):-2])
        row = next(r for r in state["rows"] if r["name"] == "Inert-rock")
        assert row["has_shields"] is False
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

        target_menu.set_contacts(_listed(ship))
        view = TargetListView()
        # Subsystem CONTENT is an expanded-row property now: a collapsed
        # row ships an empty list because the tree is only built when it
        # will be drawn. Expand so this asserts what it means to assert.
        view._expanded_ships.add(ship.GetName())
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
        target_menu.set_contacts(_listed(ship))

        view = TargetListView()
        # Subsystem CONTENT is an expanded-row property now: a collapsed
        # row ships an empty list because the tree is only built when it
        # will be drawn. Expand so this asserts what it means to assert.
        view._expanded_ships.add(ship.GetName())
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
    off the target list immediately, not linger for the throes window.

    Driven through the real push: death is decided ONCE, by
    perception.perceived_by, and reaches the panel as `Contact.targetable`.
    The view used to re-run _out_of_action on its own, a second copy of the
    rule that could disagree with the record.
    """
    from engine.ui.target_list_view import TargetListView
    from engine.appc.sets import SetClass
    from engine.appc import contact_index
    contact_index.reset()
    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    game, player, mission = _setup_game_with_player()
    try:
        pSet = SetClass()
        pSet.AddObjectToSet(player, "Player")
        alive = ShipClass(); alive.SetName("Alive")
        pSet.AddObjectToSet(alive, "Alive")
        doomed = ShipClass(); doomed.SetName("Doomed")
        pSet.AddObjectToSet(doomed, "Doomed")

        doomed.SetDying(True)   # death sequence started -> not a valid target
        _pump(target_menu, player)

        view = TargetListView()
        script = view.render_payload()
        assert script is not None
        body = script[len("setTargetList("):-2]
        state = json.loads(body)
        names = [r["name"] for r in state["rows"]]
        assert names == ["Alive"]

        # A fully dead ship is likewise excluded.
        alive.SetDead(True)
        _pump(target_menu, player)
        view.invalidate()
        script2 = view.render_payload()
        body2 = script2[len("setTargetList("):-2]
        names2 = [r["name"] for r in json.loads(body2)["rows"]]
        assert names2 == []
    finally:
        contact_index.reset()
        from engine.core.game import _set_current_game
        _set_current_game(None)


def test_view_does_not_re_derive_detectability(monkeypatch):
    """The record is the frame's answer; the view does not second-guess it.

    Cloaking a ship without re-pushing must NOT change the listing — the next
    push is what drops the row (tests/unit/test_cloak_target_visibility.py
    covers that path end to end). The view used to carry its own
    is_hidden_by_cloak / _out_of_action copy of the rule on top of the record,
    which is the same duplication that retired engine.ui.target_list_visibility
    for disagreeing with the menu.

    Held under ENHANCED_SENSOR_CONTEST = False so that cloaking is guaranteed
    to change the answer at all. Since stage 4 the push runs can_detect, where
    cloak is a range multiplier, and this fixture leaves the enemy at the
    player's own position — well inside the cloak bubble — so with the flag at
    its default the row correctly survives the push and there would be no
    before/after difference for this test to observe. The subject here is the
    VIEW's non-duplication, not the cloak rule; the flag just restores a
    detectability change for it to not-re-derive.
    """
    import engine.appc.sensor_detection as sd
    monkeypatch.setattr(sd, "ENHANCED_SENSOR_CONTEST", False)
    from engine.ui.target_list_view import TargetListView
    from engine.appc.sets import SetClass
    from engine.appc.subsystems import CloakingSubsystem
    from engine.appc.ships import ShipClass_Create
    from engine.appc import contact_index
    contact_index.reset()
    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    game, player, mission = _setup_game_with_player()
    try:
        pSet = SetClass()
        pSet.AddObjectToSet(player, "Player")
        enemy = ShipClass_Create("Warbird"); enemy.SetName("Enemy")
        enemy.SetCloakingSubsystem(CloakingSubsystem("Cloaking Device"))
        pSet.AddObjectToSet(enemy, "Enemy")
        _pump(target_menu, player)

        view = TargetListView()
        assert [r[0] for r in view._snapshot()[3]] == ["Enemy"]

        enemy.GetCloakingSubsystem().InstantCloak()      # no re-push
        assert [r[0] for r in view._snapshot()[3]] == ["Enemy"]

        _pump(target_menu, player)                       # the frame that drops it
        assert [r[0] for r in view._snapshot()[3]] == []
    finally:
        contact_index.reset()
        from engine.core.game import _set_current_game
        _set_current_game(None)


def test_destroyed_ship_lingers_in_list_then_drops_after_removal():
    """A ship in its death/linger window stays selectable in the target list;
    once ship_death finally removes it, it drops off."""
    import json
    from engine.ui.target_list_view import TargetListView
    from engine.appc.ships import ShipClass
    from engine.appc.sets import SetClass
    from engine.appc import contact_index, ship_death

    ship_death.reset()
    contact_index.reset()
    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    game, player, mission = _setup_game_with_player()
    try:
        pSet = SetClass()
        pSet.AddObjectToSet(player, "Player")
        wreck = ShipClass(); wreck.SetName("Doomed")
        pSet.AddObjectToSet(wreck, "Doomed")

        # Enter the death sequence: now dying (out of action) but a wreck.
        ship_death.begin(wreck)
        _pump(target_menu, player)
        view = TargetListView()
        state = json.loads(view.render_payload()[len("setTargetList("):-2])
        assert "Doomed" in [r["name"] for r in state["rows"]]   # listed as a wreck

        # Run out the throes + linger -> final removal -> no longer a wreck.
        ship_death.advance(ship_death.THROES_DURATION)
        ship_death.advance(ship_death.WRECK_LINGER_DURATION)
        assert ship_death.is_targetable_wreck(wreck) is False
        _pump(target_menu, player)
        state2 = json.loads(view.render_payload()[len("setTargetList("):-2])
        assert "Doomed" not in [r["name"] for r in state2["rows"]]
    finally:
        ship_death.reset()
        contact_index.reset()
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
        target_menu.set_contacts(_listed(ship))

        _resolve(ship, "Dorsal Phaser 1").SetCondition(0.0)  # destroyed

        view = TargetListView()
        # Subsystem CONTENT is an expanded-row property now: a collapsed
        # row ships an empty list because the tree is only built when it
        # will be drawn. Expand so this asserts what it means to assert.
        view._expanded_ships.add(ship.GetName())
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
        target_menu.set_contacts(_listed(ship))

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

        target_menu.set_contacts(_listed(ship))
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
        target_menu.set_contacts(_listed(ship))
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
        target_menu.set_contacts(_listed(ship))
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


def test_collapsed_rows_ship_no_subsystem_tree_but_keep_the_caret_flag():
    """A collapsed row must not pay to build a tree nobody will draw.

    target_list.js emits subsystem child rows only inside `if (expanded)`, so
    the only thing a collapsed row's tree decided was whether to show the
    expand caret. Building it walked every contact x every subsystem x every
    child, ~2-3 condition queries per grandchild, to produce a tuple that was
    compared and discarded — 84 ms at 100 contacts, the largest non-sim item in
    the frame.

    has_subsystems now carries the caret, so the tree can be skipped. Both
    halves matter: skipping the tree, AND still telling the UI a caret is due.
    """
    import json
    from engine.ui.target_list_view import TargetListView
    from engine.appc.ships import ShipClass_Create

    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    game, player, mission = _setup_game_with_player()
    try:
        ship = ShipClass_Create("Galaxy")
        ship.SetName("USS Galaxy")
        target_menu.set_contacts(_listed(ship))

        view = TargetListView()
        state = json.loads(view.render_payload()[len("setTargetList("):-2])
        row = next(r for r in state["rows"] if r["name"] == "USS Galaxy")

        assert row["expanded"] is False
        assert row["subsystems"] == [], "collapsed row built a tree it cannot draw"
        assert row["has_subsystems"] is True, (
            "caret flag lost: the row has subsystems, the UI must still offer "
            "the expand caret")

        # Expanding must produce the real tree.
        view._expanded_ships.add("USS Galaxy")
        view.invalidate()
        state = json.loads(view.render_payload()[len("setTargetList("):-2])
        row = next(r for r in state["rows"] if r["name"] == "USS Galaxy")
        assert row["expanded"] is True
        assert len(row["subsystems"]) > 0
        assert row["has_subsystems"] is True
    finally:
        from engine.core.game import _set_current_game
        _set_current_game(None)


def test_a_ship_with_no_subsystems_reports_no_caret():
    """has_subsystems must be able to say False, or the caret is drawn on rows
    that cannot expand — which is what the length check used to prevent."""
    import json
    from engine.ui.target_list_view import TargetListView
    from engine.appc.ships import ShipClass_Create

    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    game, player, mission = _setup_game_with_player()
    try:
        ship = ShipClass_Create("Galaxy")
        ship.SetName("Bare")
        target_menu.set_contacts(_listed(ship))
        for child in list(getattr(target_menu.GetFirstChild(), "_children", [])):
            target_menu.GetFirstChild()._children.remove(child)

        view = TargetListView()
        state = json.loads(view.render_payload()[len("setTargetList("):-2])
        row = next(r for r in state["rows"] if r["name"] == "Bare")
        assert row["has_subsystems"] is False
        assert row["subsystems"] == []
    finally:
        from engine.core.game import _set_current_game
        _set_current_game(None)
