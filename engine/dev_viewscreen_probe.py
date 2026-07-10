"""Developer-only probe for live-verifying ViewscreenZoomTarget.

The bridge viewscreen now auto-focuses the player's current target (BC's real
first-valid-wins mode chain), so firing MissionLib.ViewscreenWatchObject on
the player's own target is indistinguishable from doing nothing. This probe
instead watches a ship in the player's set that is NOT the current target, so
the mission-override path is visibly distinct from auto-focus when verified
in QuickBattle without reaching an E-series ViewscreenWatch beat. Diagnostics
use print() — the host has no logging handler (memory npc_subsystem_aim_gap).
Remove once live-verified."""


def watch_non_target_ship(*_args):
    """Fire MissionLib.ViewscreenWatchObject on a ship that is NOT the
    player's current target, so the mission override is visibly distinct
    from the auto-focus behaviour. Throwaway; removed after live-verify."""
    from engine.core.game import Game_GetCurrentGame
    game = Game_GetCurrentGame()
    player = game.GetPlayer() if game is not None else None
    if player is None:
        print("[vzt-probe] no current player")
        return
    target = player.GetTarget()
    pick = None
    pSet = player.GetContainingSet()
    if pSet is not None:
        # GetClassObjectList/isinstance is the only filter that actually
        # discriminates here: _LoudStub/_Stub.__getattr__ hands back a
        # truthy lambda for ANY missing attribute (including GetRadius), so
        # hasattr() cannot tell a real ship from a waypoint/set stub. A real
        # isinstance(obj, ShipClass) check can't be faked that way.
        from engine.appc.ships import ShipClass
        for obj in pSet.GetObjectList():
            if obj is player or obj is target:
                continue
            if isinstance(obj, ShipClass):
                pick = obj
                break
    if pick is None:
        print("[vzt-probe] no non-target ship found in the player's set")
        return
    import MissionLib
    ok = MissionLib.ViewscreenWatchObject(pick)
    name = getattr(pick, "GetName", lambda: "?")()
    print("[vzt-probe] ViewscreenWatchObject(%s) -> %s "
          "(player target = %s)" % (name, ok,
                                    getattr(target, "GetName", lambda: None)()))
