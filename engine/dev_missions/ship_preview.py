"""Developer-only "Ship Preview" mission — spawn one ship by script name.

WHY THIS EXISTS. A mod that adds a ship is only half-installable without
Foundation: the `Scripts/Ships/<X>.py` + `Scripts/Ships/Hardpoints/<X>.py` +
`Data/Models/...` half is stock-shaped and loads through the mod overlay
alone, but the `Scripts/Custom/Ships/<X>.py` half — the part that registers a
ship in the QuickBattle menus — imports Foundation, which we do not have.

So there is no in-game way to *select* an added ship, and therefore no way to
check whether the overlay actually resolved its script, hardpoints, model and
icon. This mission is that way: it spawns one ship by its script name,
straight through `loadspacehelper.CreateShip`, bypassing the menus entirely.

It is a TEST INSTRUMENT for the mod overlay, not a game mode. No AI is
attached, so the ship holds station and can be flown around and inspected.

The ship is a required argument — this mission names no particular ship, so
it works for stock and added content alike, and pointing it at a stock name
and then an added one is a direct A/B of the overlay:

    DAUNTLESS_SHIP=Galaxy \\
    DAUNTLESS_MISSION=engine.dev_missions.ship_preview \\
        ./build/dauntless --developer

On startup it prints to stderr where each of that ship's assets actually
resolved from. That report is the point: a path under the mods root proves
the index served it, a path under the game root proves it fell through to
stock, and the report is emitted *before* the spawn so it is still visible
when the spawn is the thing that fails.
"""
import os

import App
import MissionLib
import loadspacehelper

_SHIP_ENV = "DAUNTLESS_SHIP"

# Distance ahead of the player, in game units (1 GU = 175 m). Far enough that
# a large hull fits in frame, close enough to read detail.
_SPAWN_AHEAD_GU = 2.5


class ShipNotSpecified(RuntimeError):
    """Raised when the mission is started without a ship to spawn."""


def ship_name() -> str:
    """The ship script to spawn. Required — this mission has no default.

    Deliberately not defaulted to any particular ship: a default would name
    one piece of content in a file that exists to be content-agnostic, and
    would silently preview the wrong thing when the variable is misspelled.
    """
    name = os.environ.get(_SHIP_ENV, "").strip()
    if not name:
        raise ShipNotSpecified(
            "ship_preview needs a ship script name. Set %s to the name of a "
            "ship script (the stem of Scripts/Ships/<name>.py), e.g. "
            "%s=Galaxy." % (_SHIP_ENV, _SHIP_ENV))
    return name


def _report_resolution(name: str) -> None:
    """Print where this ship's assets came from — a mod tree, or the stock root.

    Runs before the spawn so the paths are visible even when CreateShip then
    fails, which is the case you most want diagnosed.
    """
    import sys

    from engine import mods, paths

    lines = ["[ship_preview] resolving assets for ship %r:" % name]

    # Script and hardpoints resolve through the SDK finder.
    for rel in ("ships/%s.py" % name, "ships/Hardpoints/%s.py" % name):
        hit = mods.sdk_override(rel)
        if hit is not None:
            lines.append("  %-34s MOD    %s" % (rel, hit))
        else:
            lines.append("  %-34s stock  %s" % (rel, paths.sdk_scripts() / rel))

    # The model path is named by the ship script itself, so read it back
    # rather than guessing at the layout.
    nif = ""
    try:
        import importlib

        stats = importlib.import_module("ships.%s" % name).GetShipStats()
        nif = stats.get("FilenameHigh", "")
    except Exception as exc:
        lines.append("  (could not read GetShipStats: %r)" % (exc,))

    for rel in [r for r in (nif, "data/Icons/Ships/%s.tga" % name) if r]:
        resolved = paths.game_asset(rel)
        source = "MOD   " if mods.game_override(rel) is not None else "stock "
        lines.append("  %-34s %s %s" % (rel, source, resolved))
        lines.append("  %-34s %s" % ("", "exists" if resolved.exists() else "MISSING"))

    print("\n".join(lines), file=sys.stderr, flush=True)


def Initialize(pMission):
    # Read the ship first: a missing argument should fail before a bridge and
    # a region have been built, not after.
    name = ship_name()

    App.Game_SetDifficultyMultipliers(1.0, 1.0, 1.0, 1.0, 1.0, 1.0)

    import LoadBridge
    LoadBridge.Load("SovereignBridge")

    import Systems.QuickBattle.QuickBattleRegion
    Systems.QuickBattle.QuickBattleRegion.Initialize()
    pSet = App.g_kSetManager.GetSet("QuickBattleRegion")

    pPlayer = MissionLib.CreatePlayerShip("Sovereign", pSet, "Player", "")
    pPlayer.SetTranslateXYZ(0.0, 0.0, 0.0)
    pPlayer.UpdateNodeOnly()

    _report_resolution(name)

    pShip = loadspacehelper.CreateShip(name, pSet, name, "")
    if App.IsNull(pShip):
        # Loudly, not silently: an absent ship and an invisible one look
        # identical on screen, and telling them apart is why this exists.
        raise RuntimeError(
            "ship_preview: CreateShip(%r) returned null. The ship script was "
            "not found or failed to load — the resolution report above shows "
            "where the finder looked." % name)

    # Model-Y is forward (see the rotation convention in CLAUDE.md), so +Y
    # puts the ship directly ahead of the player.
    pShip.SetTranslateXYZ(0.0, _SPAWN_AHEAD_GU, 0.0)
    pShip.UpdateNodeOnly()

    pMission.GetFriendlyGroup().AddName("Player")
    pMission.GetFriendlyGroup().AddName(name)


def Terminate(pMission):
    pass
