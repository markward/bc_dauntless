"""Engine-owned GetShipStats overlays for stock ship definitions.

Why: extend or override what ships/<Name>.py reports through GetShipStats()
(SpecularCoef fleet-wide, per-ship DamageRadMod, future Dauntless-only keys
like DamageType) without editing sdk/Build/scripts/. `apply(module)` runs from
the SDK-loader hook (engine/appc/sdk_overrides.py) after a ships.<Leaf> module
executes and wraps its GetShipStats so every consumer — SDK loadspacehelper,
host_loop's NIF-path lookup, LOD models, the QuickBattle panel — sees the
overlaid dict.

Merge order: original stats -> GLOBAL_STATS_OVERLAY -> SHIP_STATS_OVERLAYS
(per-ship wins). Ship modules are import-cached (not reloaded per spawn), so
the wrap persists; a genuine re-exec rebinds the pristine function and the
sentinel-guarded wrap re-applies cleanly.

Authoring convention: one commented section per ship inside
SHIP_STATS_OVERLAYS, keyed by the ship module leaf name (Capitalized, e.g.
"Galaxy" for ships/Galaxy.py).
"""

# Applied to EVERY ships.<Leaf> module (e.g. a fleet-wide SpecularCoef).
GLOBAL_STATS_OVERLAY: dict = {}

SHIP_STATS_OVERLAYS: dict = {
    ############################################
    # Galaxy
    ############################################
    # "Galaxy": {"DamageRadMod": ..., "DauntlessDamageType": ...},
}


def apply(module) -> None:
    """Wrap module.GetShipStats with the merged overlay for this ship."""
    leaf = module.__name__.rsplit(".", 1)[-1]
    overlay = dict(GLOBAL_STATS_OVERLAY)
    overlay.update(SHIP_STATS_OVERLAYS.get(leaf, {}))
    if not overlay:
        return
    orig = module.__dict__.get("GetShipStats")
    if orig is None or getattr(orig, "_dauntless_overlay", False):
        return  # not a ship-stats module, or already wrapped

    def GetShipStats():
        stats = dict(orig())  # copy: callers may mutate their view
        stats.update(overlay)
        return stats

    GetShipStats._dauntless_overlay = True
    module.GetShipStats = GetShipStats
