"""Developer-only "Collision Sim" mission.

Spawns the player Galaxy parked directly ABOVE a static Romulan Warbird with
0.2 GU of clearance, so a slow roll or pitch swings the saucer rim down into
the Warbird's wings: a reproducible low-speed hull contact for judging the
collision scuff decals live (spec
docs/superpowers/specs/2026-09-20-collision-scuff-normal-decals-design.md §5)
without depending on AI or on flying a ram.

The Warbird is `SetStatic`, i.e. a fixed anchor in the collision solver: it
takes no impulse, no damage and therefore NO decals (collisions.py treats an
immobile body like a planet). The scuffs land on the Galaxy — watch it from
the external camera.

Placement (GU, measured offline with `build/native/tools/dump_bounds -gu -v`;
never launch the game to check): Galaxy ~101 model units/GU, lowest point the
engineering hull at z ~ -1.07 (saucer underside ~ -0.32, rim at x ~ +-2.3);
Warbird ~100 model units/GU, highest point the dorsal spine / wing tops at
z ~ +1.53, wings spanning x ~ +-4.8. Both at identity rotation (forward +Y),
Warbird centre at z = -(1.07 + 1.53 + CLEARANCE_GU). A ~25 degree roll or
pitch brings the saucer rim to the wing tops.

Registered into the dev mission picker ("Developer" family) by
engine/host_loop.py — dev mode only, never present in production builds.
"""
import App
import MissionLib
import loadspacehelper

GALAXY_LOWEST_GU = 1.07      # below the Galaxy's centre (engineering hull)
WARBIRD_HIGHEST_GU = 1.53    # above the Warbird's centre (dorsal spine)
CLEARANCE_GU = 0.2           # gap between the two at rest


def PreLoadAssets(pMission):
    """Best-effort model preload (CreateShip also loads on demand)."""
    import importlib
    for module_name in ("ships.Galaxy", "ships.Warbird"):
        try:
            mod = importlib.import_module(module_name)
            if hasattr(mod, "PreLoadModel"):
                mod.PreLoadModel()
        except Exception:
            pass


def Initialize(pMission):
    App.Game_SetDifficultyMultipliers(1.0, 1.0, 1.0, 1.0, 1.0, 1.0)

    import LoadBridge
    LoadBridge.Load("GalaxyBridge")

    # Known-good visible space set + backdrop, reused from QuickBattle.
    import Systems.QuickBattle.QuickBattleRegion
    Systems.QuickBattle.QuickBattleRegion.Initialize()
    pSet = App.g_kSetManager.GetSet("QuickBattleRegion")

    # Player at the origin (identity rotation -> forward is +Y, up is +Z).
    pPlayer = MissionLib.CreatePlayerShip("Galaxy", pSet, "Player", "")
    pPlayer.SetTranslateXYZ(0.0, 0.0, 0.0)
    pPlayer.UpdateNodeOnly()

    # The anvil: a static Warbird parked CLEARANCE_GU under the Galaxy.
    pAnvil = loadspacehelper.CreateShip("Warbird", pSet, "Anvil", "")
    pAnvil.SetTranslateXYZ(0.0, 0.0,
                           -(GALAXY_LOWEST_GU + WARBIRD_HIGHEST_GU + CLEARANCE_GU))
    pAnvil.SetStatic(1)
    pAnvil.UpdateNodeOnly()

    # Friendly so nothing opens fire; the only interaction is the hull contact.
    pFriendlies = pMission.GetFriendlyGroup()
    pFriendlies.AddName("Player")
    pFriendlies.AddName("Anvil")
