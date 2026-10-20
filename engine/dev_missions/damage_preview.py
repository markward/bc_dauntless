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
# Unused on the damage-redesign spike (the Akira starts clean).
_DAMAGE_SCRIPT = "Maelstrom.Episode5.E5M2.DamageAkira"

_DEATH = "<death>"

# SPIKE (damage redesign): the impulse system dies in stages -- controller,
# then port, then starboard engine. Delays are seconds after the PREVIOUS
# step (TGSequence AppendAction semantics).
def _death_delay_s() -> float:
    """DAUNTLESS_DAMAGE_PREVIEW_DEATH_S: seconds from the last impulse blast
    to the kill (default 4). Perf captures lengthen it for a steady
    damaged-but-alive window before the cascade."""
    import os
    try:
        return max(0.0, float(os.environ.get("DAUNTLESS_DAMAGE_PREVIEW_DEATH_S", "4")))
    except ValueError:
        return 4.0


_IMPULSE_STEPS = (
    (3.0, "Impulse Engines"),
    (1.5, "Port Impulse"),
    (1.5, "Star Impulse"),
    (None, _DEATH),          # then the ship dies (_death_delay_s): BC's death cascade
)
_step_index = [0]


def _wreck():
    pSet = App.g_kSetManager.GetSet("QuickBattleRegion")
    ship = App.ShipClass_GetObject(pSet, "Wreck") if pSet is not None else None
    return None if ship is None or App.IsNull(ship) else ship


def _find_subsystem(ship, name):
    ies = ship.GetImpulseEngineSubsystem()
    if ies is None:
        return None
    if ies.GetName() == name:
        return ies
    for i in range(ies.GetNumChildSubsystems()):
        child = ies.GetChildSubsystem(i)
        if child is not None and child.GetName() == name:
            return child
    return None


def DestroyNextImpulseStep(pAction):
    """Destroy the next impulse subsystem the way gameplay does (condition 0)."""
    i = _step_index[0]
    _step_index[0] = i + 1
    if i >= len(_IMPULSE_STEPS):
        return 0
    name = _IMPULSE_STEPS[i][1]
    ship = _wreck()
    if name == _DEATH:
        if ship is not None:
            from engine.appc import ship_death
            ship_death.begin(ship)
            print("[damage-preview] wreck killed: death cascade running")
        return 0
    sub = _find_subsystem(ship, name) if ship is not None else None
    if sub is None:
        print("[damage-preview] no subsystem %r on the wreck" % name)
        return 0
    sub.SetCondition(0.0)
    pos = sub.GetPosition() if hasattr(sub, "GetPosition") else None
    where = "(%.2f, %.2f, %.2f)" % (pos.x, pos.y, pos.z) if pos is not None else "?"
    print("[damage-preview] destroyed %s at body %s GU" % (name, where))
    return 0


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

    # SPIKE (damage redesign): the Akira starts clean -- no authored
    # DamageTool volumes -- and loses its impulse system on a timer, the
    # first internal-explosion scenario (see _IMPULSE_STEPS).
    pSeq = App.TGSequence_Create()
    for delay, _name in _IMPULSE_STEPS:
        if delay is None:
            delay = _death_delay_s()
        pSeq.AppendAction(App.TGScriptAction_Create(__name__, "DestroyNextImpulseStep"), delay)
    pSeq.Play()
    _step_index[0] = 0

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
    # Small one is a grind (scratches); the two larger are impacts (crumple).
    visible_damage.queue_body_scuff(pWreck, 0.6, 0.4, 0.15, radius_gu=0.15,
                                    tangent_body=(1.0, 0.0, 0.0), dent=0.0)
    visible_damage.queue_body_scuff(pWreck, -0.5, 0.2, 0.15, radius_gu=0.3,
                                    tangent_body=(0.0, 1.0, 0.0), dent=1.0)
    visible_damage.queue_body_scuff(pWreck, 0.0, -0.6, 0.05, radius_gu=0.5,
                                    tangent_body=(0.7, 0.7, 0.0), dent=1.0)

    # Friendly so the wreck is a clean, non-hostile contact.
    pFriendlies = pMission.GetFriendlyGroup()
    pFriendlies.AddName("Player")
    pFriendlies.AddName("Wreck")
