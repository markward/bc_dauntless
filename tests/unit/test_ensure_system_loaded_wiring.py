"""host_loop._ensure_system_loaded must read the LIVE player, not
session.player (system-frames spec §3, fix round 1 review focus).

On a RecreatePlayer tick session.player is still the OLD ship until
_reconcile_runtime_instances (which runs right after this call in the host
loop) updates it. Reading session.player instead of
Game_GetCurrentGame().GetPlayer() would resolve last tick's set -- one tick
late -- so a player who spawns straight into a mapped region would sit there
for a full frame with its siblings unloaded.
"""
import App
from engine.appc.sets import SetClass_Create
from engine.core.game import Game, _set_current_game
from engine.systems import region_hooks, system_loader
from tests.helpers.mapped_regions import load_region


def setup_function(_):
    App.g_kSetManager._sets.clear()
    system_loader.reset()


def teardown_function(_):
    _set_current_game(None)
    App.g_kSetManager._sets.clear()
    system_loader.reset()


def _ship_in(pSet, name):
    ship = App.ShipClass_Create()
    ship.SetName(name)
    pSet.AddObjectToSet(ship, name)
    return ship


def test_ensure_system_loaded_reads_the_live_player_not_session_player():
    from engine import host_loop as hl

    # session.player is stale: a ship left over in an unmapped set (as it
    # would be for one tick right after RecreatePlayer, before the
    # reconciliation pass below updates session.player).
    stale_set = SetClass_Create()
    App.g_kSetManager.AddSet(stale_set, "StaleSet")
    stale_player = _ship_in(stale_set, "stale_player")

    # The game's CURRENT player is already in a mapped region this tick.
    live_player = _ship_in(load_region("Ona", "Ona1"), "live_player")

    game = Game()
    game.SetPlayer(live_player)
    _set_current_game(game)

    sess = hl.MissionSession(mission_name="t")
    sess.player = stale_player

    hl._ensure_system_loaded(sess)

    # Reading session.player (the stale, unmapped ship) would have loaded
    # nothing. Reading the live player loads Ona1's siblings.
    assert App.g_kSetManager.GetSet("Ona2") is not None
    assert App.g_kSetManager.GetSet("Ona3") is not None
    assert region_hooks.is_mapped(App.g_kSetManager.GetSet("Ona2"))
    assert system_loader.loaded_system() == "Ona"


def test_ensure_system_loaded_is_a_guarded_no_op_without_a_game():
    from engine import host_loop as hl
    _set_current_game(None)
    sess = hl.MissionSession(mission_name="t")
    sess.player = None
    hl._ensure_system_loaded(sess)  # must not raise
    assert system_loader.loaded_system() is None


def test_ensure_system_loaded_is_a_guarded_no_op_with_no_session():
    from engine import host_loop as hl
    hl._ensure_system_loaded(None)  # must not raise
