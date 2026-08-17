"""Range decides whether a contact is drawable on the target list / radar.

Was written against engine.ui.target_list_visibility, the separate per-tick
pass that flipped STSubsystemMenu.SetVisible/SetNotVisible. That module is
gone: the per-frame perception push now carries the verdict and the menu
derives the row from it. These tests exercise the same end-to-end road the
host loop takes (position -> perceived_by -> set_contacts -> row), with the
same distances and the same expected outcomes.

The fixtures model no BaseSensorRange, so effective_sensor_range returns
FALLBACK_RANGE_GU — which IS the 30000.0 these tests used to pass explicitly
as `range_units`.
"""
import App
from engine.appc.perception import perceived_by
from engine.appc.sets import SetClass
from engine.appc.ships import ShipClass_Create


def _ship(name, x=0.0, y=0.0, z=0.0):
    s = ShipClass_Create("test")
    s.SetName(name)
    s.SetTranslateXYZ(x, y, z)
    return s


def _setup_game_with_player():
    from engine.core.game import Game, Episode, Mission, _set_current_game
    mission = Mission()
    episode = Episode(); episode.SetCurrentMission(mission)
    game = Game(); game.SetCurrentEpisode(episode)
    player = _ship("Player", 0.0, 0.0, 0.0)
    game.SetPlayer(player)
    _set_current_game(game)
    pSet = SetClass()
    pSet.AddObjectToSet(player, "Player")
    return game, player, mission, pSet


def _pump(menu, player):
    """One frame of the host loop's contact push (host_loop._pump_contacts)."""
    menu.set_contacts(perceived_by(player))


def _drawable(menu, ship):
    """Is *ship* drawable on the target list / radar?

    Both surfaces walk the menu's children and keep the IsVisible() == 1 rows,
    so a contact leaves the display either by losing its row or by having that
    row flagged not-visible. One record decides both, and a contact out of
    sensor reach now loses the row outright — the stronger outcome. This
    helper reads "not drawable" from either.
    """
    row = menu.GetObjectEntry(ship)
    return row is not None and row.IsVisible() == 1


def test_in_range_ship_remains_visible():
    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    game, player, mission, pSet = _setup_game_with_player()
    try:
        nearby = _ship("Nearby", 1000.0, 0.0, 0.0)
        pSet.AddObjectToSet(nearby, "Nearby")

        _pump(target_menu, player)

        assert _drawable(target_menu, nearby) is True
    finally:
        from engine.core.game import _set_current_game
        _set_current_game(None)


def test_out_of_range_ship_becomes_invisible():
    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    game, player, mission, pSet = _setup_game_with_player()
    try:
        far = _ship("Far", 100000.0, 0.0, 0.0)
        pSet.AddObjectToSet(far, "Far")

        _pump(target_menu, player)

        assert _drawable(target_menu, far) is False
    finally:
        from engine.core.game import _set_current_game
        _set_current_game(None)


def test_ship_pops_back_when_back_in_range():
    """Out → in transition makes the contact drawable again — and on the SAME
    row object, because the row cache outlives the contact list."""
    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    game, player, mission, pSet = _setup_game_with_player()
    try:
        wanderer = _ship("Wanderer", 100000.0, 0.0, 0.0)
        pSet.AddObjectToSet(wanderer, "Wanderer")
        _pump(target_menu, player)
        assert _drawable(target_menu, wanderer) is False

        wanderer.SetTranslateXYZ(500.0, 0.0, 0.0)
        _pump(target_menu, player)

        assert _drawable(target_menu, wanderer) is True
    finally:
        from engine.core.game import _set_current_game
        _set_current_game(None)
