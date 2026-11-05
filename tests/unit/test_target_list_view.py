import json
import App
from engine.appc.ships import ShipClass
from engine.appc.perception import Contact
from tests.helpers.native_off import native_switch_zero  # noqa: F401


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
    from engine.ui.target_list_view import (
        TargetListView, reconcile_subsystem_lock)
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
    from engine.ui.target_list_view import (
        TargetListView, reconcile_subsystem_lock)
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
    from engine.ui.target_list_view import (
        TargetListView, reconcile_subsystem_lock)
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
    from engine.ui.target_list_view import (
        TargetListView, reconcile_subsystem_lock)

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


def test_dispatch_event_subsystem_click_sets_both_target_and_subsystem():
    from engine.ui.target_list_view import (
        TargetListView, reconcile_subsystem_lock)
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
    from engine.ui.target_list_view import (
        TargetListView, reconcile_subsystem_lock)
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
    from engine.ui.target_list_view import (
        TargetListView, reconcile_subsystem_lock)
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
    from engine.ui.target_list_view import (
        TargetListView, reconcile_subsystem_lock)
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
    from engine.ui.target_list_view import (
        TargetListView, reconcile_subsystem_lock)
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
    from engine.ui.target_list_view import (
        TargetListView, reconcile_subsystem_lock)
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
    from engine.ui.target_list_view import (
        TargetListView, reconcile_subsystem_lock)

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


def test_destroyed_ship_excluded_from_target_list():
    """A ship that is dying or dead (death sequence in progress) must drop
    off the target list immediately, not linger for the throes window.

    Driven through the real push: death is decided ONCE, by
    perception.perceived_by, and reaches the panel as `Contact.targetable`.
    The view used to re-run _out_of_action on its own, a second copy of the
    rule that could disagree with the record.
    """
    from engine.ui.target_list_view import (
        TargetListView, reconcile_subsystem_lock)
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


def test_view_does_not_re_derive_detectability(monkeypatch,
                                               native_switch_zero):
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
    # The monkeypatched flag is a Python-only double (the native globals are
    # pushed, not read at use): DAUNTLESS_NATIVE_COMBAT=0 (native_switch_zero).
    import engine.appc.sensor_detection as sd
    monkeypatch.setattr(sd, "ENHANCED_SENSOR_CONTEST", False)
    from engine.ui.target_list_view import (
        TargetListView, reconcile_subsystem_lock)
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
        assert [r[0] for r in view._snapshot()[5]] == ["Enemy"]

        enemy.GetCloakingSubsystem().InstantCloak()      # no re-push
        assert [r[0] for r in view._snapshot()[5]] == ["Enemy"]

        _pump(target_menu, player)                       # the frame that drops it
        assert [r[0] for r in view._snapshot()[5]] == []
    finally:
        contact_index.reset()
        from engine.core.game import _set_current_game
        _set_current_game(None)


def test_destroyed_ship_lingers_in_list_then_drops_after_removal():
    """A ship in its death/linger window stays selectable in the target list;
    once ship_death finally removes it, it drops off."""
    import json
    from engine.ui.target_list_view import (
        TargetListView, reconcile_subsystem_lock)
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

        # Run out the throes -> hulk -> no longer a wreck (V7: same sample).
        ship_death.advance(ship_death.MAX_THROES_DURATION)
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


def test_locked_subsystem_destroyed_reassigns_to_next_sibling():
    """When the locked subsystem is destroyed, the lock moves to the next
    surviving sibling in the same group."""
    from engine.ui.target_list_view import (
        TargetListView, reconcile_subsystem_lock)
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
        # The host loop drives this per frame, NOT the throttled panel --
        # it is a combat rule the weapon-aim path reads, so it must not run on
        # the target list's 2 Hz poll cadence.
        reconcile_subsystem_lock()

        assert player.GetTargetSubsystem() is bank2
    finally:
        App.g_kSetManager.DeleteSet("bridge")
        from engine.core.game import _set_current_game
        _set_current_game(None)


def test_last_child_destroyed_clears_lock_to_ship_level():
    """When the last surviving child in the group is destroyed, the
    subsystem lock clears (back to ship-level targeting)."""
    from engine.ui.target_list_view import (
        TargetListView, reconcile_subsystem_lock)
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
        # The host loop drives this per frame, NOT the throttled panel --
        # it is a combat rule the weapon-aim path reads, so it must not run on
        # the target list's 2 Hz poll cadence.
        reconcile_subsystem_lock()

        assert player.GetTargetSubsystem() is None
    finally:
        App.g_kSetManager.DeleteSet("bridge")
        from engine.core.game import _set_current_game
        _set_current_game(None)


def test_the_subsystem_lock_rule_is_not_reachable_through_the_render_path():
    """The handoff is a COMBAT rule: both weapon-aim paths in host_loop read
    GetTargetSubsystem(). While it lived in TargetListView.render_payload it
    inherited the panel's poll cadence, and throttling the panel to 2 Hz
    silently made the player's phasers keep aiming at a destroyed subsystem
    for up to half a second.

    Pinned two ways, because either alone rots: the module must expose the
    rule independently of the panel, and render_payload must not call it.
    """
    import inspect
    from engine.ui import target_list_view as tlv

    assert callable(getattr(tlv, "reconcile_subsystem_lock", None)), (
        "the rule must be callable without constructing a panel")
    assert not inspect.signature(tlv.reconcile_subsystem_lock).parameters, (
        "it derives the player itself; a parameter invites a second caller "
        "passing something else")

    src = inspect.getsource(tlv.TargetListView.render_payload)
    assert "reconcile_subsystem_lock" not in src, (
        "render_payload calls the lock rule again — it is back on the panel's "
        "2 Hz cadence")


def test_the_host_loop_drives_the_rule_every_frame():
    """It must sit in the unthrottled per-frame block, beside the other
    player-lock rule it belongs with — not inside the panel registry, which
    is what applies the poll interval."""
    import ast
    import pathlib
    from engine import host_loop

    src = pathlib.Path(host_loop.__file__).read_text(encoding="utf-8")
    calls = [n for n in ast.walk(ast.parse(src))
             if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name)
             and n.func.id == "reconcile_subsystem_lock"]
    assert calls, "host_loop never calls reconcile_subsystem_lock"

    # It belongs next to clear_undetectable_player_lock: same category of rule,
    # same required cadence, and that one is already correct.
    neighbours = [n.lineno for n in ast.walk(ast.parse(src))
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                  and n.func.id == "clear_undetectable_player_lock"]
    assert any(abs(c.lineno - nb) < 30 for c in calls for nb in neighbours), (
        "reconcile_subsystem_lock drifted away from the per-frame lock block")


def test_row_carries_marker():
    from engine.ui import target_markers
    from engine.ui.target_list_view import TargetListView
    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    _setup_game_with_player()
    target_markers.clear()
    try:
        a = ShipClass(); a.SetName("Alpha")
        b = ShipClass(); b.SetName("Beta")
        target_menu.set_contacts(_listed(a, b))
        view = TargetListView()
        view.render_payload()
        target_markers.set_marker("Alpha", "protect")
        script = view.render_payload()
        assert script is not None, "marker-only change must re-render"
        state = json.loads(script[len("setTargetList("):-2])
        by_name = {r["name"]: r for r in state["rows"]}
        assert by_name["Alpha"]["marker"] == "protect"
        assert by_name["Beta"]["marker"] is None
        assert view.render_payload() is None
        target_markers.clear_marker("Alpha")
        assert view.render_payload() is not None
    finally:
        target_markers.clear()
        from engine.core.game import _set_current_game
        _set_current_game(None)
