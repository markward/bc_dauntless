"""Developer-only "Damage Preview" mission.

Spawns the player plus a stock pre-damaged Akira ~6 GU dead-ahead so the
authored hull-damage path can be eyeballed in a single load:

    DamageAkira.AddDamage(pWreck)
        -> ShipClass.AddObjectDamageVolume(...)        (engine/appc/objects.py)
        -> engine.appc.visible_damage.queue_body_volume (deferred queue)
        -> host.hull_carve_add(...)                     (next host-loop tick)
        -> breach renderer                              (visible breaches)

Reuses QuickBattle's region for a known-good, visible space set + backdrop. The
wreck is a friendly contact so it stays out of the way. Registered into the dev
mission picker ("Developer" family) by engine/host_loop.py — dev mode only, never
present in production builds.

See docs/engine/damagetool-and-hull-damage-gaps.md.
"""
import importlib

import App
import MissionLib
import loadspacehelper

# Stock DamageTool script: 22 authored volumes, within the 24-slot carve field.
_DAMAGE_SCRIPT = "Maelstrom.Episode5.E5M2.DamageAkira"


def PreLoadAssets(pMission):
    """Best-effort model preload (CreateShip also loads on demand)."""
    for module_name in ("ships.Sovereign", "ships.Akira"):
        try:
            mod = importlib.import_module(module_name)
            if hasattr(mod, "PreLoadModel"):
                mod.PreLoadModel()
        except Exception:
            pass


def Initialize(pMission):
    App.Game_SetDifficultyMultipliers(1.0, 1.0, 1.0, 1.0, 1.0, 1.0)

    # Player bridge — CreatePlayerShip expects a loaded bridge.
    import LoadBridge
    LoadBridge.Load("SovereignBridge")

    # Known-good visible space set + backdrop, reused from QuickBattle.
    import Systems.QuickBattle.QuickBattleRegion
    Systems.QuickBattle.QuickBattleRegion.Initialize()
    pSet = App.g_kSetManager.GetSet("QuickBattleRegion")

    # Player at the origin (identity rotation -> forward is +Y).
    pPlayer = MissionLib.CreatePlayerShip("Sovereign", pSet, "Player", "")
    pPlayer.SetTranslateXYZ(0.0, 0.0, 0.0)
    pPlayer.UpdateNodeOnly()

    # Pre-wrecked Akira ~6 GU dead-ahead.
    pWreck = loadspacehelper.CreateShip("Akira", pSet, "Wreck", "")
    pWreck.SetTranslateXYZ(0.0, 6.0, 0.0)
    pWreck.UpdateNodeOnly()

    # Authored visible damage via the stock DamageTool output.
    DamageAkira = importlib.import_module(_DAMAGE_SCRIPT)
    DamageAkira.AddDamage(pWreck)

    # Three collision scuffs for live tuning of the scuff decal (spec
    # 2026-09-20-collision-scuff-normal-decals-design.md §5): small, medium
    # and large radii, three slip directions, the large one straddling the
    # saucer/hull curve. Body-frame offsets in GU. Measured offline via
    # `build/native/tools/dump_bounds -gu -p -q <x,y,z> Akira.nif` (never
    # launch the game to check placement): model_r=5.1 GU overall; the dense
    # hull-core piece cluster (saucer + engineering hull) spans roughly
    # X in [-2.7, 1.3], Y in [-0.5, 0.8], Z in [-0.6, 1.2], with the nacelles
    # extending much farther out (X ~ +-4.2). All three points below probe as
    # "inside" a hull piece with the nearest real vertex only 0.1-0.3 GU away
    # (well inside the 0.5 GU standoff `_mesh_normal` probes), so they land on
    # the hull rather than in space.
    from engine.appc import visible_damage
    visible_damage.queue_body_scuff(pWreck, 0.6, 0.4, 0.15, radius_gu=0.15,
                                    tangent_body=(1.0, 0.0, 0.0))
    visible_damage.queue_body_scuff(pWreck, -0.5, 0.2, 0.15, radius_gu=0.3,
                                    tangent_body=(0.0, 1.0, 0.0))
    visible_damage.queue_body_scuff(pWreck, 0.0, -0.6, 0.05, radius_gu=0.5,
                                    tangent_body=(0.7, 0.7, 0.0))

    # Friendly so the wreck is a clean, non-hostile contact.
    pFriendlies = pMission.GetFriendlyGroup()
    pFriendlies.AddName("Player")
    pFriendlies.AddName("Wreck")
