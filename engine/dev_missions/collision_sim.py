"""Developer-only "Collision Sim" mission.

Spawns the player Galaxy parked directly ABOVE a static Romulan Warbird, close
enough that ~10 degrees of pitch or ~20 degrees of roll grinds the saucer
into the Warbird's wings: a reproducible low-speed hull contact for judging the
collision scuff decals live (spec
docs/superpowers/specs/2026-09-20-collision-scuff-normal-decals-design.md §5)
without depending on AI or on flying a ram.

The Warbird is `SetStatic`, i.e. a fixed anchor in the collision solver: it
takes no impulse, no damage and therefore NO decals (collisions.py treats an
immobile body like a planet). The scuffs land on the Galaxy — watch it from
the external camera.

Placement (GU): the collision solver sees hull PIECES -- bounding spheres
round flat plates, with up to ~1.5 GU of slack above the Warbird's wing mesh
-- so the gap that matters is the one between piece spheres, not meshes.
Measured offline by simulating the shipping splitter's 128 pieces per hull
(`build/native/tools/dump_bounds -gu -p`, overlap when d < 0.8 * (ra + rb) as
collisions.py does): with the Warbird's centre at ANVIL_Z_GU the deepest pair
is 0.32 GU CLEAR at rest, and first contact comes at ~10 degrees of nose-down
pitch or ~20 degrees of roll. At -3.0 (the mesh-based gap first tried) the
pieces already overlapped by 0.44 GU at rest. Never launch the game to check
placement.

Registered into the dev mission picker ("Developer" family) by
engine/host_loop.py — dev mode only, never present in production builds.
"""
import App
import MissionLib
import loadspacehelper

ANVIL_Z_GU = -3.8            # Warbird centre below the Galaxy's; see the docstring


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

    # The anvil: a static Warbird parked ANVIL_Z_GU under the Galaxy.
    pAnvil = loadspacehelper.CreateShip("Warbird", pSet, "Anvil", "")
    pAnvil.SetTranslateXYZ(0.0, 0.0, ANVIL_Z_GU)
    pAnvil.SetStatic(1)
    pAnvil.UpdateNodeOnly()

    # Friendly so nothing opens fire; the only interaction is the hull contact.
    pFriendlies = pMission.GetFriendlyGroup()
    pFriendlies.AddName("Player")
    pFriendlies.AddName("Anvil")
