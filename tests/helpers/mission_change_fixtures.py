"""A running mission to change away from (spec §2), shared by the mission
change tests: a Game -> Episode "_t.EpOld" -> Mission "_t.Old", the player in
BC's "warp" set, a "bridge" set and one old region set "Beol4". Fake SDK
modules are installed straight into sys.modules with `_install`; `log` is the
shared call log `_world()` clears."""
import sys
import types

import App
from engine.core.game import Game, Episode, Mission, _set_current_game
from engine.appc.sets import SetClass_Create

log = []

FAKE_MODULES = ("_t.Old", "_t.New", "_t.EpOld", "_t.EpNew")


def _install(name, **fns):
    m = types.ModuleType(name)
    for k, v in fns.items():
        setattr(m, k, v)
    sys.modules[name] = m


def _world():
    App.g_kSetManager._sets.clear()
    log.clear()
    game = Game(); ep = Episode(); mis = Mission()
    ep.SetCurrentMission(mis); game.SetCurrentEpisode(ep); _set_current_game(game)
    mis._module_name = "_t.Old"; ep._module_name = "_t.EpOld"
    ws = App.WarpSequence_GetWarpSet()
    player = App.ShipClass_Create(); player.SetName("player")
    ws.AddObjectToSet(player, "player"); game.SetPlayer(player)
    bridge = SetClass_Create(); App.g_kSetManager.AddSet(bridge, "bridge")
    old = SetClass_Create(); App.g_kSetManager.AddSet(old, "Beol4")
    return game, player, bridge


def _forget_world():
    for n in FAKE_MODULES:
        sys.modules.pop(n, None)
    _set_current_game(None)

