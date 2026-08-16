"""A fully cloaked ship drops off the player's target list / radar and can't be
held as a weapon lock — the same per-render road the destruction filter uses.

Surfaces (all keyed on sensor_detection.is_hidden_by_cloak):
  * radar / sensor panel — filters rows on STSubsystemMenu.IsVisible(); the
    per-tick perception push drops a cloaked contact from the menu.
  * target list view — its _snapshot inclusion predicate drops cloaked ships
    alongside _out_of_action (destroyed) ships.
  * player weapon lock — the host loop clears GetTarget() when it cloaks, which
    also silences fire (FireWeapons no-ops with no target).

Boundary matches can_detect: hidden only while fully CLOAKED, visible again the
moment it starts decloaking.
"""
import App

from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import CloakingSubsystem
from engine.appc.sensor_detection import is_hidden_by_cloak
from engine.appc.perception import perceived_by
from engine.appc.target_menu import STTargetMenu_CreateW, STSubsystemMenu


def _pump(menu, player):
    """One frame of the contact push — the same call host_loop._pump_contacts
    makes. Replaces update_target_list_visibility(..., range_units=30000.0):
    these fixtures model no BaseSensorRange, so effective_sensor_range returns
    FALLBACK_RANGE_GU, which IS 30000.0. Same reach, one source."""
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
    return pSet, player, enemy, menu


def _enemy_visible(menu, enemy):
    """Visible to the radar == a LISTED row whose IsVisible() is 1.

    Both halves count, because the sensors panel walks the menu's children and
    keeps the ones with IsVisible() == 1: a contact leaves the radar either by
    losing its row or by having that row flagged not-visible. This helper used
    to require the row to exist; a cloaked ship now loses it outright (its
    perception record is neither perceivable nor targetable), which is the
    strictly stronger outcome, so "absent" reads as not visible.
    """
    row = menu.GetObjectEntry(enemy)
    if row is None:
        return False
    assert isinstance(row, STSubsystemMenu)
    return row.IsVisible() == 1


def test_is_hidden_by_cloak_predicate():
    enemy = ShipClass_Create("Warbird")
    enemy.SetCloakingSubsystem(CloakingSubsystem("Cloaking Device"))
    assert not is_hidden_by_cloak(enemy)            # DECLOAKED
    enemy.GetCloakingSubsystem().StartCloaking()    # CLOAKING — still visible
    assert not is_hidden_by_cloak(enemy)
    enemy.GetCloakingSubsystem().InstantCloak()     # CLOAKED — hidden
    assert is_hidden_by_cloak(enemy)
    # A ship with no cloak is never hidden.
    plain = ShipClass_Create("Galaxy")
    assert not is_hidden_by_cloak(plain)


def test_cloaked_ship_marked_not_visible_for_radar():
    pSet, player, enemy, menu = _scene()
    _pump(menu, player)
    assert _enemy_visible(menu, enemy)
    enemy.GetCloakingSubsystem().InstantCloak()
    _pump(menu, player)
    assert not _enemy_visible(menu, enemy)
    # Decloak restores it.
    enemy.GetCloakingSubsystem().InstantDecloak()
    _pump(menu, player)
    assert _enemy_visible(menu, enemy)


def test_cloaked_ship_dropped_from_target_list_view():
    pSet, player, enemy, menu = _scene()

    class _Game:
        def GetPlayer(self):
            return player
        GetCurrentPlayer = GetPlayer
    import engine.core.game as _gmod
    saved = _gmod._current_game
    _gmod._current_game = _Game()
    try:
        from engine.ui.target_list_view import TargetListView
        view = TargetListView()
        _pump(menu, player)
        rows_before = view._snapshot()[3]
        names_before = {r[0] for r in rows_before}
        assert "Enemy" in names_before

        # The view reads the pushed record; it no longer keeps its own copy of
        # is_hidden_by_cloak to short-circuit it. The frame's push is what
        # drops the row -- which is the production path, run every frame.
        enemy.GetCloakingSubsystem().InstantCloak()
        _pump(menu, player)
        rows_after = view._snapshot()[3]
        names_after = {r[0] for r in rows_after}
        assert "Enemy" not in names_after
    finally:
        _gmod._current_game = saved


def test_player_lock_drops_cloaked_target(monkeypatch):
    """A player lock on a ship that finishes cloaking is dropped.

    Calls the real guard rather than mirroring it. The previous version
    inlined its own copy of the host-loop `if ... is_hidden_by_cloak(...)`
    branch, so it could not have noticed the guard changing underneath it --
    and it didn't when the predicate was widened to can_detect (see
    tests/unit/test_player_lock_sensor_gate.py).

    STOCK-BC BEHAVIOUR, held under ENHANCED_SENSOR_CONTEST = False. This
    fixture puts the enemy 50 GU away, and cloak is now a range multiplier
    (see tests/unit/test_cloak_detection_contest.py), so with the flag at its
    default the lock survives at this distance -- the contest companion below
    pins that. The assertion here is unchanged; only the configuration it
    describes is now explicit.
    """
    import engine.appc.sensor_detection as sd
    monkeypatch.setattr(sd, "ENHANCED_SENSOR_CONTEST", False)
    from engine.appc.sensor_detection import clear_undetectable_player_lock
    _, player, enemy, _ = _scene()
    player.SetTarget(enemy)
    assert player.GetTarget() is enemy
    # Not yet cloaked → lock holds.
    clear_undetectable_player_lock(player)
    assert player.GetTarget() is enemy
    # Fully cloaked → the guard drops it.
    enemy.GetCloakingSubsystem().InstantCloak()
    clear_undetectable_player_lock(player)
    assert player.GetTarget() is None


def test_player_lock_survives_close_cloak_but_drops_beyond_the_bubble():
    """INTENTIONAL DIVERGENCE (ENHANCED_SENSOR_CONTEST default-on): the lock is
    kept while the cloaked ship is inside 1% of effective sensor range.

    These fixtures model no BaseSensorRange, so effective range is
    FALLBACK_RANGE_GU (30000) and the cloak bubble is 300 GU. The enemy sits at
    50 GU -> still locked. Push it past the bubble and the guard drops it, which
    keeps the original "undetectable target loses the lock" guarantee live under
    the default configuration.
    """
    from engine.appc.sensor_detection import clear_undetectable_player_lock
    _, player, enemy, _ = _scene()
    player.SetTarget(enemy)
    enemy.GetCloakingSubsystem().InstantCloak()

    # 50 GU, inside the 300 GU cloak bubble → the lock holds.
    clear_undetectable_player_lock(player)
    assert player.GetTarget() is enemy

    # Beyond the bubble → dropped, exactly as a cloaked ship always was.
    enemy.SetTranslateXYZ(0, 500, 0)
    clear_undetectable_player_lock(player)
    assert player.GetTarget() is None
