"""Developer-only "Combat Stress" mission — a reproducible profiling load.

WHY THIS EXISTS. The first frame-profiler captures were taken on QuickBattle
and on the Maelstrom missions, and all of them measured a scene with no combat
in it: QuickBattle boots with `g_kEnemyList = []` (a lone Galaxy on a bridge),
and E3M1 / E2M1 / E8M1 run 900 ticks with **zero projectiles fired and zero
hull damage taken**. Every conclusion drawn from those captures was a
conclusion about an idle game.

This mission spawns two hostile groups running the SDK's own `QuickBattleAI`
and lets them fight, so a capture exercises the paths an idle scene never
touches: weapon firing and beam rendering, projectile flight and guidance,
shield impacts, hull carve and damage decals, hit VFX, subsystem cascades,
ship death, and the contact/target-menu churn all of that drives.

Size it with DAUNTLESS_COMBAT_SHIPS (default 8, meaning 4 per side, plus the
player). Ships are placed on a ring so everyone starts in weapons range and
the fight begins within a few seconds rather than after a long approach.

Reuses QuickBattle's region for a known-good visible set + backdrop, the same
way damage_preview does.

Usage:

    OPEN_STBC_HOST_HEADLESS=1 DAUNTLESS_PROFILE_FRAMES=900 \
        ./build-cef/dauntless.exe --developer

with the mission selected from the dev picker, or driven directly by
tools/profile_capture.py.
"""
import math
import os

import App
import MissionLib
import loadspacehelper

# The SDK's own quick-battle combat AI — the same module QuickBattle attaches
# to every enemy it spawns (g_dEnemyShipTypeToDetails, column 3). Using the
# stock AI keeps the load representative rather than a bespoke firing loop.
#
# NOT QuickBattleAI itself: that wrapper resolves its target group through
# App.ObjectGroup_FromModule("QuickBattle.QuickBattle", "pFriendlies"), i.e. it
# reads QuickBattle's own module globals, which do not exist unless QuickBattle
# is the running mission. Calling it from here raises IndexError inside
# CreateAI. BasicAttack is what QuickBattleAI wraps, and it takes the target
# group as a parameter, so it composes with this mission's own groups.
#
# Import and attach failures are FATAL, never swallowed: the first version of
# this mission caught the ImportError, attached no AI at all, and produced a
# nine-ship scene that sat there doing nothing — precisely the idle-capture
# problem this mission exists to fix.
_ATTACK_AI_MODULE = "AI.Compound.BasicAttack"

# 0-3 in the SDK; 2 is QuickBattle's default "normal" opponent.
_AI_DIFFICULTY = 2

# Nominal hull radius seeded when a ship has none.
#
# The renderer's realize step sets GetRadius() from the model AABB, and a
# headless run has no realize step -- so every ship reads back 0.0. That is not
# cosmetic: _test_course_override skips any obstacle with `ob_r <= 0.0`, and
# personal_space is `radius * AVOID_PERSONAL_SPACE_MULT`, so a zero radius
# makes headless avoidance process NOTHING while looking like it ran. A
# measurement taken that way reports whatever the caller hoped. ~4 GU is a
# Galaxy's bounding sphere (stbc-reference spec/ShieldFacingDamage.md).
_NOMINAL_HULL_RADIUS_GU = 4.0

# Ships are placed on a ring sized so they do NOT interpenetrate.
#
# A fixed 20 GU ring was the original and it is wrong past ~15 ships: the
# circumference is 126 GU, a hull is ~8 GU across, so 100 ships were being
# spawned 1.26 GU apart -- deeply inside one another. Every measurement taken
# on that scene was of a pile-up resolving itself, not a battle.
#
# radius = N * hull_diameter * SPACING / (2*pi) keeps neighbours SPACING hull
# diameters apart at any N. The floor keeps small counts inside weapons range
# (BC's phaser envelope is ~60 GU).
_RING_SPACING_HULLS = 2.0
_MIN_RING_RADIUS_GU = 20.0


def ring_radius_gu(n_ships: int) -> float:
    """Ring radius that keeps `n_ships` hulls from overlapping."""
    circumference = max(1, n_ships) * (2.0 * _NOMINAL_HULL_RADIUS_GU) * _RING_SPACING_HULLS
    return max(_MIN_RING_RADIUS_GU, circumference / (2.0 * math.pi))

_DEFAULT_SHIPS = 8


def avoidance_enabled() -> bool:
    """DAUNTLESS_COMBAT_AVOID=1 wraps each ship's attack AI in an
    AvoidObstacles preprocessor, the way the Fleet doctrines do.

    Off by default because BasicAttack -- what this mission installs -- does
    NOT install one, and that is faithful: since the engine node replaced the
    duplicate GameLoop pass, avoidance is opt-in per doctrine rather than a
    property of having an AI. The knob exists so avoidance can be profiled at
    all: with it off this mission exercises no avoidance whatsoever, and a
    capture taken against it says nothing about that code path.
    """
    return os.environ.get("DAUNTLESS_COMBAT_AVOID", "") == "1"

# Alternating pairs so the two sides interleave around the ring and every ship
# has an enemy nearby, rather than two clumps that must close first.
_FRIEND_TYPES = ("Sovereign", "Akira", "Galaxy", "Nebula")
_ENEMY_TYPES = ("Warbird", "Vorcha", "Galor", "BirdOfPrey")


def ship_count() -> int:
    """Total AI ships (excluding the player). Even, at least 2."""
    try:
        n = int(os.environ.get("DAUNTLESS_COMBAT_SHIPS", _DEFAULT_SHIPS))
    except ValueError:
        n = _DEFAULT_SHIPS
    n = max(2, n)
    return n - (n % 2)


def PreLoadAssets(pMission):
    """Best-effort model preload so first-fire does not stall the capture.

    A model loaded lazily mid-capture puts its decode cost in whichever frame
    happened to trigger it, which reads as a random spike rather than as
    loading. CreateShip still loads on demand if this misses.
    """
    import importlib
    for name in _FRIEND_TYPES + _ENEMY_TYPES:
        try:
            mod = importlib.import_module("ships." + name)
            if hasattr(mod, "PreLoadModel"):
                mod.PreLoadModel()
        except Exception:
            pass


def _place_on_ring(pShip, index: int, total: int) -> None:
    radius = ring_radius_gu(total)
    angle = (2.0 * math.pi * index) / max(1, total)
    pShip.SetTranslateXYZ(radius * math.cos(angle),
                          radius * math.sin(angle),
                          0.0)
    pShip.UpdateNodeOnly()
    # Seed a hull radius when the ship has none. See _NOMINAL_HULL_RADIUS_GU:
    # headless has no realize step, and a zero radius silently disables
    # avoidance entirely rather than failing.
    try:
        if pShip.GetRadius() <= 0.0:
            pShip.SetRadius(_NOMINAL_HULL_RADIUS_GU)
    except Exception:
        pass


def Initialize(pMission):
    App.Game_SetDifficultyMultipliers(1.0, 1.0, 1.0, 1.0, 1.0, 1.0)

    import LoadBridge
    LoadBridge.Load("SovereignBridge")

    import Systems.QuickBattle.QuickBattleRegion
    Systems.QuickBattle.QuickBattleRegion.Initialize()
    pSet = App.g_kSetManager.GetSet("QuickBattleRegion")

    pPlayer = MissionLib.CreatePlayerShip("Sovereign", pSet, "Player", "")
    pPlayer.SetTranslateXYZ(0.0, 0.0, 0.0)
    pPlayer.UpdateNodeOnly()
    # Same reason as the ring ships: headless has no realize step, and a zero
    # radius removes the player from avoidance and collision entirely.
    try:
        if pPlayer.GetRadius() <= 0.0:
            pPlayer.SetRadius(_NOMINAL_HULL_RADIUS_GU)
    except Exception:
        pass

    pFriendlies = pMission.GetFriendlyGroup()
    pEnemies = pMission.GetEnemyGroup()
    pFriendlies.AddName("Player")

    total = ship_count()
    per_side = total // 2
    created = []

    for i in range(total):
        friendly = (i % 2 == 0)
        side_index = i // 2
        if friendly:
            ship_type = _FRIEND_TYPES[side_index % len(_FRIEND_TYPES)]
            name = "Friend-%d" % (side_index + 1)
        else:
            ship_type = _ENEMY_TYPES[side_index % len(_ENEMY_TYPES)]
            name = "Enemy-%d" % (side_index + 1)

        pShip = loadspacehelper.CreateShip(ship_type, pSet, name, "")
        if App.IsNull(pShip):
            continue
        _place_on_ring(pShip, i, total)
        if friendly:
            pFriendlies.AddName(name)
        else:
            pEnemies.AddName(name)
        created.append((pShip, friendly))

    # Attach the stock AI last, once every ship exists — an AI that acquires a
    # target during spawn would pick from a half-built world.
    import importlib
    try:
        pAIModule = importlib.import_module(_ATTACK_AI_MODULE)
    except Exception as exc:
        raise RuntimeError(
            "combat_stress: could not import %s (%r). Without it this mission "
            "spawns ships that never fight, which makes it useless as a "
            "profiling load." % (_ATTACK_AI_MODULE, exc))

    attached = 0
    failures = []
    for pShip, is_friendly in created:
        # Each side attacks the other's group.
        pTargets = pEnemies if is_friendly else pFriendlies
        try:
            pAI = pAIModule.CreateAI(pShip, pTargets,
                                     Difficulty=_AI_DIFFICULTY,
                                     FollowTargetThroughWarp=1,
                                     UseCloaking=1)
            if pAI is None:
                failures.append("CreateAI returned None")
                continue
            if avoidance_enabled():
                # Exactly the Fleet doctrines' construction
                # (AI/Fleet/DestroyTarget.py:24-32): a PreprocessingAI bound to
                # an AvoidObstacles script instance, containing the attack tree.
                import AI.Preprocessors
                pScript = AI.Preprocessors.AvoidObstacles()
                pAvoid = App.PreprocessingAI_Create(pShip, "AvoidObstacles")
                pAvoid.SetInterruptable(1)
                pAvoid.SetPreprocessingMethod(pScript, "Update")
                pAvoid.SetContainedAI(pAI)
                pAI = pAvoid
            pShip.SetAI(pAI, 0, 0)
            attached += 1
        except Exception as exc:
            failures.append(repr(exc))
    if attached == 0:
        raise RuntimeError(
            "combat_stress: AI module imported but attached to 0 of %d ships "
            "(%s)." % (len(created), "; ".join(failures[:3])))
    if failures:
        print("[combat_stress] WARNING: AI attach failed on %d of %d ships: %s"
              % (len(failures), len(created), failures[0]))

    # Red alert: shields up and weapons hot from t=0, so the capture is not
    # measuring the run-up to combat.
    try:
        pPlayer.SetAlertLevel(App.ShipClass.RED_ALERT)
    except Exception:
        pass

    ring = ring_radius_gu(total)
    spacing = (2.0 * math.pi * ring) / max(1, total)
    print("[combat_stress] %d AI ships (%d per side) + player; ring %.0f GU, "
          "neighbour spacing %.1f GU (~%.1f hull diameters); AI attached to %d; "
          "avoidance=%s"
          % (len(created), per_side, ring, spacing,
             spacing / (2.0 * _NOMINAL_HULL_RADIUS_GU), attached,
             "ON" if avoidance_enabled() else "off"))
