"""Developer-only probe for live-verifying ViewscreenZoomTarget.

Fires MissionLib.ViewscreenWatchObject on the player's current target, so the
mission-driven VZT path can be verified in QuickBattle without reaching an
E-series ViewscreenWatch beat. Diagnostics use print() — the host has no logging
handler (memory npc_subsystem_aim_gap). Remove once live-verified."""


def watch_current_target(*_args):
    from engine.core.game import Game_GetCurrentGame
    game = Game_GetCurrentGame()
    player = game.GetPlayer() if game is not None else None
    if player is None:
        print("[vzt-probe] no current player")
        return
    target = player.GetTarget()
    if target is None:
        print("[vzt-probe] no player target — select a target first")
        return
    import MissionLib
    ok = MissionLib.ViewscreenWatchObject(target)
    name = getattr(target, "GetName", lambda: "?")()
    print("[vzt-probe] ViewscreenWatchObject(%s) -> %s" % (name, ok))
