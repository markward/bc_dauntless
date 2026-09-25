"""Developer-only "System Preview" mission.

Loads a real BC region (Ona1, of the Ona system) through its own SDK
Initialize(), the same way any mission does, and drops the player Galaxy at
its "Player Start" waypoint. Nothing else -- no NPCs, no scripted events.

The system loader (engine/systems/system_loader.py, Task 1) loads Ona1's
siblings (Ona2, Ona3) on the first host_loop tick once it notices the player
sitting in a mapped region; this mission's own Initialize() has nothing to do
beyond getting the player there.

This is what Mark flies with tools/systems/yardstick.py's numbers in hand:
--developer -> Load Mission... -> Developer -> System Preview. Registered
into the picker by engine.host_loop._developer_family_entry() -- dev mode
only, never present in production builds.
"""
import App
import MissionLib


def PreLoadAssets(pMission):
    """Best-effort model preload (CreateShip also loads on demand)."""
    import importlib
    try:
        mod = importlib.import_module("ships.Galaxy")
        if hasattr(mod, "PreLoadModel"):
            mod.PreLoadModel()
    except Exception:
        pass


def Initialize(pMission):
    import LoadBridge
    LoadBridge.Load("GalaxyBridge")

    import Systems.Ona.Ona1
    Systems.Ona.Ona1.Initialize()
    pSet = App.g_kSetManager.GetSet("Ona1")

    MissionLib.CreatePlayerShip("Galaxy", pSet, "player", "Player Start")
