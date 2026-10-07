"""Player Helm "Orbit" altitude scales with the planet radius.

Decision: Mark, 2026-10-07, option C.

BC's `AI/Player/OrbitPlanet.CreateAI(pShip, pPlanet)` builds a CircleObject
PlainAI ("CirclePlanet") with `SetRoughDistances(R + 150, R + 190)` and gates
it behind a `ConditionInRange` at `200.0 + R`. BC planets were R ~ 90, so 150
GU was a sensible standoff; our system maps scale planets ~20x (R 140-9000),
and the stock offsets put the player inside the atmosphere shell.

New rule, player Helm "Orbit" only:

    alt     = max(ORBIT_FLOOR_GU, ORBIT_K * R)
    circle  = (R + alt, R + alt * 190/150)
    trigger = R + alt * 200/150

At the floor this is exactly BC's numbers. The SDK file is never edited:
`install()` wraps the module's `CreateAI`, calls BC's original, and rewrites
the two values on the returned tree. A tree of an unexpected shape (a mod's
own OrbitPlanet) is left untouched with one warning. NPC AI, collisions and
targeting are unaffected -- they keep the bare planet radius.
"""
import logging

_log = logging.getLogger(__name__)

ORBIT_K = 0.15
ORBIT_FLOOR_GU = 150.0

# BC's stock offsets, which the rule scales: circle near/far and trigger
# relative to the 150 GU standoff.
_FAR_RATIO = 190.0 / 150.0
_TRIGGER_RATIO = 200.0 / 150.0

_IN_RANGE_MODULE = "Conditions.ConditionInRange"


def orbit_distances(radius):
    """(inner, outer, trigger) centre distances for orbiting a planet of
    radius `radius` GU."""
    r = float(radius)
    alt = max(ORBIT_FLOOR_GU, ORBIT_K * r)
    return (r + alt, r + alt * _FAR_RATIO, r + alt * _TRIGGER_RATIO)


def _find_targets(root):
    """The CircleObject script instance and the ConditionInRange script
    instance in `root`'s tree, or None when the tree is not BC's shape
    (exactly one of each)."""
    circles, in_ranges = [], []
    for ai in root.GetAllAIsInTree():
        get_module = getattr(ai, "GetScriptModule", None)
        if callable(get_module) and get_module() == "CircleObject":
            circles.append(ai.GetScriptInstance())
        get_conditions = getattr(ai, "GetConditions", None)
        if callable(get_conditions):
            for cond in get_conditions():
                get_name = getattr(cond, "GetModuleName", None)
                if callable(get_name) and get_name() == _IN_RANGE_MODULE:
                    in_ranges.append(getattr(cond, "_instance", None))
    if len(circles) != 1 or len(in_ranges) != 1:
        return None
    circle, in_range = circles[0], in_ranges[0]
    if not callable(getattr(circle, "SetRoughDistances", None)) \
            or not callable(getattr(in_range, "SetDistance", None)):
        return None
    return circle, in_range


def apply_to_tree(root, radius) -> bool:
    """Rewrite BC's orbit distances on an OrbitPlanet tree. False (with one
    warning, values untouched) when the tree is not the expected shape."""
    try:
        found = _find_targets(root) if root is not None else None
    except Exception as e:
        _log.warning("orbit altitude: could not inspect OrbitPlanet tree: %s", e)
        return False
    if found is None:
        _log.warning("orbit altitude: OrbitPlanet tree has an unexpected shape; "
                     "keeping its own orbit distances")
        return False
    circle, in_range = found
    inner, outer, trigger = orbit_distances(radius)
    circle.SetRoughDistances(inner, outer)
    # ConditionInRange's own SetDistance: updates fDistance AND the live
    # proximity sphere's radius, so the new gate takes effect.
    in_range.SetDistance(trigger)
    return True


def install(module=None) -> bool:
    """Wrap `AI.Player.OrbitPlanet.CreateAI` (or `module.CreateAI`) once.
    True if it wrapped now; False if already wrapped or unavailable."""
    if module is None:
        try:
            import AI.Player.OrbitPlanet as module
        except Exception as e:
            _log.warning("orbit altitude: AI.Player.OrbitPlanet unavailable: %s", e)
            return False
    current = getattr(module, "CreateAI", None)
    if current is None or getattr(current, "_dauntless_orbit_altitude_orig", None) is not None:
        return False
    orig = current

    def CreateAI(pShip, pPlanet):
        root = orig(pShip, pPlanet)
        try:
            radius = pPlanet.GetRadius()
        except Exception as e:
            _log.warning("orbit altitude: planet radius unavailable: %s", e)
            return root
        apply_to_tree(root, radius)
        return root

    CreateAI._dauntless_orbit_altitude_orig = orig
    module.CreateAI = CreateAI
    return True
