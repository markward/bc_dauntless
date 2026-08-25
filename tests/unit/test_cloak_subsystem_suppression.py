"""A cloaked contact is targetable at ship level only — its subsystem tree is
suppressed. This is `Contact.subsystems_targetable`, set by
`perception.perceived_by`, consumed by `target_list_view._snapshot` (empty
`subsystems` tuple) and `_reconcile_subsystem_lock` (drops a live subsystem
lock back to ship level when its ship cloaks).

Named for the effect (subsystems_targetable), not the cause (cloak), because
nebula concealment is a plausible second producer later.

50 GU is the same "inside the bubble" geometry
tests/unit/test_cloak_target_visibility.py uses: these fixtures model no
BaseSensorRange, so effective range is FALLBACK_RANGE_GU (30000) and the cloak
bubble is CLOAK_DETECTION_BASE_GU + FALLBACK_RANGE_GU * CLOAK_RANGE_FACTOR =
the game's largest — well past the 50 GU separation used below, which
`_assert_fixture_geometry` pins rather than assuming.
"""
import json

import App

from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import CloakingSubsystem
from engine.appc.perception import perceived_by
from engine.appc.target_menu import STTargetMenu_CreateW
from tests.helpers.cloak_geometry import assert_inside, FALLBACK_SENSOR_GU


def _pump(menu, player):
    """One frame of the real contact push — perception.perceived_by, exactly
    as host_loop._pump_contacts drives it every tick."""
    menu.set_contacts(perceived_by(player))


def _scene():
    App.g_kSetManager._sets.clear()
    pSet = App.SetClass_Create()
    pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    player = ShipClass_Create("Galaxy")
    player.SetName("Player")
    player.SetTranslateXYZ(0, 0, 0)
    pSet.AddObjectToSet(player, "Player")
    enemy = ShipClass_Create("Warbird")
    enemy.SetName("Enemy")
    enemy.SetTranslateXYZ(0, 50, 0)
    enemy.SetCloakingSubsystem(CloakingSubsystem("Cloaking Device"))
    pSet.AddObjectToSet(enemy, "Enemy")
    menu = STTargetMenu_CreateW("Targets")
    menu.RebuildShipMenus(pSet)
    # These fixtures author no BaseSensorRange, so the observer falls back to
    # FALLBACK_RANGE_GU and gets the game's largest cloak bubble. The 50 GU
    # separation above is meant to sit INSIDE it; pin that rather than assume it,
    # so a cloak retune fails loudly here instead of silently turning every
    # "inside the bubble" test below into an "outside the bubble" one.
    assert_inside(50.0, FALLBACK_SENSOR_GU)
    return pSet, player, enemy, menu


def _with_current_game(player):
    """Install a minimal Game_GetCurrentGame() stand-in returning *player*,
    matching the pattern test_cloak_target_visibility.py uses. Returns the
    restore callback."""
    class _Game:
        def GetPlayer(self):
            return player
        GetCurrentPlayer = GetPlayer
    import engine.core.game as _gmod
    saved = _gmod._current_game
    _gmod._current_game = _Game()

    def _restore():
        _gmod._current_game = saved
    return _restore


def _row_for(state, ship_name):
    return next(r for r in state["rows"] if r["name"] == ship_name)


def test_cloaked_contact_inside_bubble_lists_ship_with_no_subsystems():
    """Ship-level row is present — you can still shoot at it — but its
    subsystem tree is empty, so there is nothing to expand or click."""
    from engine.ui.target_list_view import TargetListView
    pSet, player, enemy, menu = _scene()
    restore = _with_current_game(player)
    try:
        enemy.GetCloakingSubsystem().InstantCloak()
        _pump(menu, player)

        view = TargetListView()
        view._expanded_ships.add("Enemy")
        script = view.render_payload()
        assert script is not None
        state = json.loads(script[len("setTargetList("):-2])

        row = _row_for(state, "Enemy")
        assert row["subsystems"] == []
        # ...and the caret flag agrees, so a collapsed row is suppressed too.
        assert row["has_subsystems"] is False
    finally:
        restore()


def test_uncloaked_contact_at_same_distance_still_carries_subsystems():
    """Control: identical 50 GU separation, no cloak. Subsystems must still
    be present — proving the gate is cloak-driven, not distance-driven."""
    from engine.ui.target_list_view import TargetListView
    pSet, player, enemy, menu = _scene()
    restore = _with_current_game(player)
    try:
        _pump(menu, player)  # never cloaked

        view = TargetListView()
        view._expanded_ships.add("Enemy")
        script = view.render_payload()
        state = json.loads(script[len("setTargetList("):-2])

        row = _row_for(state, "Enemy")
        assert len(row["subsystems"]) > 0
        assert row["has_subsystems"] is True
    finally:
        restore()


def test_subsystem_lock_drops_to_ship_level_when_target_cloaks():
    """A held subsystem lock clears back to ship-level targeting the moment
    its ship cloaks; the ship-level target itself survives."""
    from engine.ui.target_list_view import TargetListView
    pSet, player, enemy, menu = _scene()
    restore = _with_current_game(player)
    try:
        _pump(menu, player)
        player.SetTarget(enemy)
        it = enemy.StartGetSubsystemMatch(App.CT_SHIP_SUBSYSTEM)
        sub = enemy.GetNextSubsystemMatch(it)
        enemy.EndGetSubsystemMatch(it)
        assert sub is not None
        player.SetTargetSubsystem(sub)
        assert player.GetTargetSubsystem() is sub

        enemy.GetCloakingSubsystem().InstantCloak()
        _pump(menu, player)

        view = TargetListView()
        view._reconcile_subsystem_lock()

        assert player.GetTargetSubsystem() is None
        assert player.GetTarget() is enemy  # ship-level lock intact
    finally:
        restore()


def test_subsystem_lock_drops_when_target_cloaks_outside_the_bubble():
    """When a target cloaks OUTSIDE its detection bubble,
    sensor_detection.clear_undetectable_player_lock drops the ship-level
    target via SetTarget(None) — but ShipClass.SetTarget never touches
    _target_subsystem, so nothing else clears the stale subsystem lock
    either. _reconcile_subsystem_lock must catch the target=None case, and
    that clearing must not leak onto whatever the player targets next.
    """
    from engine.ui.target_list_view import TargetListView
    from engine.appc.sensor_detection import clear_undetectable_player_lock
    pSet, player, enemy, menu = _scene()
    other = ShipClass_Create("Other")
    other.SetName("Other")
    other.SetTranslateXYZ(0, 60, 0)
    pSet.AddObjectToSet(other, "Other")
    restore = _with_current_game(player)
    try:
        _pump(menu, player)
        player.SetTarget(enemy)
        it = enemy.StartGetSubsystemMatch(App.CT_SHIP_SUBSYSTEM)
        sub = enemy.GetNextSubsystemMatch(it)
        enemy.EndGetSubsystemMatch(it)
        assert sub is not None
        player.SetTargetSubsystem(sub)

        # Cloak AND push well past the bubble — clear_undetectable_
        # player_lock (the host loop's per-tick guard) drops the ship-level
        # target, but on its own leaves the subsystem lock dangling.
        enemy.GetCloakingSubsystem().InstantCloak()
        enemy.SetTranslateXYZ(0, 5000, 0)
        clear_undetectable_player_lock(player)
        assert player.GetTarget() is None
        assert player.GetTargetSubsystem() is sub  # still dangling, pre-fix

        view = TargetListView()
        view._reconcile_subsystem_lock()
        assert player.GetTargetSubsystem() is None

        # The stale subsystem must not resurface on a DIFFERENT ship.
        player.SetTarget(other)
        assert player.GetTargetSubsystem() is None
    finally:
        restore()


def test_dispatch_event_subsystem_click_rechecks_cloak_flag():
    """A click's action string is built from a payload rendered on a PRIOR
    frame. If the ship finished cloaking since, honouring the click must not
    set a subsystem lock the current record disallows."""
    from engine.ui.target_list_view import TargetListView
    pSet, player, enemy, menu = _scene()
    restore = _with_current_game(player)
    try:
        _pump(menu, player)
        it = enemy.StartGetSubsystemMatch(App.CT_SHIP_SUBSYSTEM)
        sub = enemy.GetNextSubsystemMatch(it)
        enemy.EndGetSubsystemMatch(it)
        assert sub is not None
        sub_name = sub.GetName()

        # Cloak (still inside the bubble — the ship stays targetable) and
        # push, so the record now says subsystems_targetable=False, before
        # the click is dispatched.
        enemy.GetCloakingSubsystem().InstantCloak()
        _pump(menu, player)

        view = TargetListView()
        handled = view.dispatch_event("Enemy/" + sub_name)

        assert handled is True
        assert player.GetTarget() is enemy      # ship-level click still lands
        assert player.GetTargetSubsystem() is None  # subsystem click refused
    finally:
        restore()


def test_enhanced_sensor_contest_off_cloaked_ship_undetected_untouched(monkeypatch):
    """With the stage-4 toggle off, cloak is absolute again — the ship never
    becomes a contact at all, so the subsystem question doesn't arise. Pins
    that this feature adds no new behaviour under the toggle-off
    configuration."""
    import engine.appc.sensor_detection as sd
    monkeypatch.setattr(sd, "ENHANCED_SENSOR_CONTEST", False)
    from engine.ui.target_list_view import TargetListView
    pSet, player, enemy, menu = _scene()
    restore = _with_current_game(player)
    try:
        enemy.GetCloakingSubsystem().InstantCloak()
        _pump(menu, player)

        view = TargetListView()
        script = view.render_payload()
        state = json.loads(script[len("setTargetList("):-2]) if script else {"rows": []}
        names = [r["name"] for r in state["rows"]]
        assert "Enemy" not in names
    finally:
        restore()


def test_cached_subsystem_rows_survive_cloak_then_decloak_without_rebuild():
    """Proves suppression happens at the VIEW, not by touching the cache:
    the STSubsystemMenu row's cached subsystem children are the SAME objects
    before cloaking, while cloaked (merely hidden from the payload), and
    after decloaking — nothing ever rebuilds them."""
    from engine.ui.target_list_view import TargetListView
    pSet, player, enemy, menu = _scene()
    restore = _with_current_game(player)
    try:
        _pump(menu, player)
        row = menu.GetObjectEntry(enemy)
        assert row is not None
        cached_children_before = list(row._children)
        assert cached_children_before  # sanity: real subsystem rows exist

        view = TargetListView()
        view._expanded_ships.add("Enemy")
        state = json.loads(view.render_payload()[len("setTargetList("):-2])
        assert len(_row_for(state, "Enemy")["subsystems"]) > 0

        # Cloak: the row survives, the cache is untouched, but the payload
        # suppresses subsystems.
        enemy.GetCloakingSubsystem().InstantCloak()
        _pump(menu, player)
        assert menu.GetObjectEntry(enemy) is row
        assert list(row._children) == cached_children_before
        view.invalidate()
        state = json.loads(view.render_payload()[len("setTargetList("):-2])
        assert _row_for(state, "Enemy")["subsystems"] == []
        assert _row_for(state, "Enemy")["has_subsystems"] is False
        assert list(row._children) == cached_children_before  # still untouched

        # Decloak: subsystems reappear, still the SAME cached objects — no
        # rebuild was needed to bring them back.
        enemy.GetCloakingSubsystem().InstantDecloak()
        _pump(menu, player)
        assert menu.GetObjectEntry(enemy) is row
        assert list(row._children) == cached_children_before
        view.invalidate()
        state = json.loads(view.render_payload()[len("setTargetList("):-2])
        assert len(_row_for(state, "Enemy")["subsystems"]) > 0
    finally:
        restore()
