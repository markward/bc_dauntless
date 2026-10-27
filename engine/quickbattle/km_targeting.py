"""Quick Battle AI targeting for the condition stacks: enemies weight every
protected ship, friendly NPCs weight every hunt target, the way BC's own E6M1
weights an escort target.

Victory spec 2026-10-23 §5.2 (live-check fix 1, Mark's ruling: E6M1's
approach), generalised by spec 2026-10-27 §5.1-5.2. E6M1
(Maelstrom/Episode6/E6M1/E6M1.py:595-598) gives each attacker an
`App.ObjectGroupWithInfo` with `{"Priority": 2.0}` on the ship it must kill
and `{"Priority": 1.0}` on the player; the SDK's SelectTarget
(AI/Preprocessors.py:1564-1603) adds Priority x fPriorityFactor (1.0) to its
distance, damage-dealt and popularity terms, so attackers mostly go for the
listed ships and still turn on whoever is hurting them. The popularity term
spreads several attackers across several listed ships.

Stock Quick Battle AI targets a whole side, every ship equal: enemy AI
(QuickBattleAI, StarbaseAI) `App.ObjectGroup_FromModule(
"QuickBattle.QuickBattle", "pFriendlies")`, friendly AI
(QuickBattleFriendlyAI, StarbaseFriendlyAI) `(..., "pEnemies")`. A NEUTRAL
protected ship is not an enemy candidate at all. While a battle is armed,
this module builds up to two weighted groups:

- the ENEMY group, when any Defeat Ships Destroyed list names a ship: every
  protected ship at LISTED_TARGET_PRIORITY, then every pFriendlies member at
  OTHER_TARGET_PRIORITY;
- the FRIENDLY group, when any Victory Ships Destroyed list names a ship:
  every hunt target at LISTED_TARGET_PRIORITY, then every pEnemies member at
  OTHER_TARGET_PRIORITY.

A side with no listed ship gets no group and its AI is never wrapped: BC's
stock targeting, untouched.

Mechanism (no SDK edit): the CreateAI of every AI module the armed sides'
ships of the plan will be given (`spawn._details`, the same lookup that fills
g_kShips) is wrapped for the battle. For a ship in `pEnemies` the wrapper
answers the module's own `App.ObjectGroup_FromModule(
"QuickBattle.QuickBattle", "pFriendlies")` with the enemy group, for a ship
in `pFriendlies` `(..., "pEnemies")` with the friendly group, for the
duration of that one call; every other FromModule call, and every ship of a
side with no group, goes through untouched. StartSimulation2's AI loop and
late_arrivals both reach the wrapper through `__import__(module).CreateAI(
ship)`. pFriendlies and pEnemies -- the mission's IFF groups -- are never
written: a neutral protected ship stays neutral, only a target candidate.

The listed ships are FIRST in their group. BC's attack compounds start on the
group's first name (NonFedAttack.py:11, CloakAttack.py:17) and the current
target earns fIsTargetFactor (1.0), exactly the priority gap; with the player
(or the first enemy) first, that head start would cancel the weighting.

`reset()` (from battle_end.reset: End Combat, Restart, the end timer, a
mission swap) restores every wrapped CreateAI and forgets both groups, so a
battle afterwards without conditions runs BC's stock targeting untouched.
"""
from __future__ import annotations

import logging
from typing import Optional

_log = logging.getLogger(__name__)

LISTED_TARGET_PRIORITY = 2.0      # E6M1.py:597, the escort target
PROTECTED_TARGET_PRIORITY = LISTED_TARGET_PRIORITY   # phase 1's name
OTHER_TARGET_PRIORITY = 1.0       # E6M1.py:596, the player

QB_MODULE = "QuickBattle.QuickBattle"
_ORIG_ATTR = "_dauntless_km_targeting_orig"


class _Side:
    """One side's weighted group: the AI of every ship in `attackers`
    (a QuickBattle group attribute) gets `group` in place of its stock
    `targets` group; the `listed` names lead it at LISTED_TARGET_PRIORITY."""

    def __init__(self, attackers, targets, spawn_side, listed, group):
        self.attackers = attackers     # "pEnemies": whose AI is redirected
        self.targets = targets         # "pFriendlies": the attr redirected
        self.spawn_side = spawn_side   # "Enemy": spawn._details side
        self.listed = list(listed)
        self.group = group


_sides: dict = {}             # "enemy" / "friendly" -> armed _Side
_qb = None                    # the QuickBattle module it was armed for
_wrapped: list = []           # (module, original CreateAI)

# (key, attackers attr, stock targets attr, spawn._details side, allegiance)
_SIDE_SPECS = (("enemy", "pEnemies", "pFriendlies", "Enemy", "enemy"),
               ("friendly", "pFriendlies", "pEnemies", "Friendly", "friendly"))


def _group_of(key):
    side = _sides.get(key)
    return None if side is None else side.group


def enemy_target_group():
    """The enemies' weighted target group (protected ships first), or None."""
    return _group_of("enemy")


def friendly_target_group():
    """The friendly NPCs' weighted target group (hunt targets first), or None."""
    return _group_of("friendly")


def arm(qb, plan, protected_names, target_names, present) -> None:
    """Build the weighted groups for one battle and wrap the AI modules
    their attackers will be given. `protected_names`: every Defeat Ships
    Destroyed ship, `target_names`: every Victory one, each in listing order;
    `present`: the names that exist now (a late, warp-in ship joins in
    `ship_arrived`). A side whose list is empty stays stock."""
    global _qb
    import App
    reset()
    _qb = qb
    listed = {"enemy": list(protected_names or ()),
              "friendly": list(target_names or ())}
    modules = []
    for key, attackers, targets, spawn_side, allegiance in _SIDE_SPECS:
        names = listed[key]
        if not names:
            continue
        group = App.ObjectGroupWithInfo()
        for name in names:
            if name in present:
                group[name] = {"Priority": LISTED_TARGET_PRIORITY}
        _sides[key] = _Side(attackers, targets, spawn_side, names, group)
        for m in _ai_modules(qb, plan, allegiance, spawn_side):
            if m not in modules:
                modules.append(m)
    sync(qb)
    for name in modules:
        _wrap(name)


def _ai_modules(qb, plan, allegiance, spawn_side) -> list:
    from engine.quickbattle import spawn
    names = []
    for order in plan.orders:
        if order.allegiance != allegiance:
            continue
        try:
            ai = spawn._details(qb, order.class_id, spawn_side)[0]
        except Exception:
            _log.exception("quickbattle: no %s AI module for %s", allegiance,
                           order.class_id)
            continue
        if ai and ai not in names:
            names.append(ai)
    return names


def _wrap(module_name) -> None:
    try:
        # As StartSimulation2 and late_arrivals resolve it.
        module = __import__(module_name)
    except Exception:
        _log.exception("quickbattle: cannot import AI %s; its ships keep "
                       "BC's stock targets", module_name)
        return
    orig = getattr(module, "CreateAI", None)
    if orig is None or getattr(orig, _ORIG_ATTR, None) is not None:
        return

    def CreateAI(pShip, *args, **kw):
        return _create_ai(orig, pShip, args, kw)

    setattr(CreateAI, _ORIG_ATTR, orig)
    module.CreateAI = CreateAI
    _wrapped.append((module, orig))


def _side_for(qb, ship) -> Optional[_Side]:
    """The armed side whose attackers group holds `ship`, or None."""
    for side in _sides.values():
        try:
            if getattr(qb, side.attackers).IsNameInGroup(ship.GetName()):
                return side
        except Exception:
            continue
    return None


def _create_ai(orig, pShip, args, kw):
    qb = _qb
    side = None if qb is None or pShip is None else _side_for(qb, pShip)
    if side is None:
        return orig(pShip, *args, **kw)
    import App
    try:
        sync(qb)
    except Exception:
        # StartSimulation2's AI loop runs this: one failure must not abort AI
        # assignment for the ships after it. The group stays as it is.
        _log.exception("quickbattle: AI targets not synced for %s",
                       pShip.GetName())
    group, targets = side.group, side.targets
    real = App.ObjectGroup_FromModule

    def FromModule(module_name, attr_name):
        if module_name == QB_MODULE and attr_name == targets:
            return group
        return real(module_name, attr_name)

    App.ObjectGroup_FromModule = FromModule
    try:
        return orig(pShip, *args, **kw)
    finally:
        App.ObjectGroup_FromModule = real


def sync(qb) -> None:
    """Every member of each armed side's stock target group not yet in its
    weighted group joins at OTHER_TARGET_PRIORITY (a listed ship keeps its
    2.0)."""
    if qb is None:
        return
    for side in _sides.values():
        group = side.group
        for name in getattr(qb, side.targets).GetNameTuple():
            if not group.IsNameInGroup(name):
                group[name] = {"Priority": OTHER_TARGET_PRIORITY}


def _put_first(group, name, info) -> None:
    """Make `name` the group's FIRST name, with `info`; every other name
    keeps its info, in order. Through the group's own API: a group-level
    event flag (SetEventFlag(flag), the form SelectTarget's setup uses) is
    re-applied to each re-added name by AddName."""
    others = [(n, group[n]) for n in group.GetNameTuple() if n != name]
    for n, _info in others:
        group.RemoveName(n)
    group[name] = info
    for n, n_info in others:
        group[n] = n_info


def ship_arrived(qb, name) -> None:
    """A late ship is in the battle and its side's group: it joins the
    other side's weighted group at OTHER_TARGET_PRIORITY, or, when it is a
    listed ship, at LISTED_TARGET_PRIORITY as the group's FIRST name, so
    attackers built from now on start on it (see the module docstring).
    Never raises."""
    if not _sides:
        return
    try:
        for side in _sides.values():
            if name in side.listed:
                _put_first(side.group, name, {"Priority": LISTED_TARGET_PRIORITY})
        sync(qb)
    except Exception:
        _log.exception("quickbattle: AI targets not updated for %s", name)


def reset() -> None:
    """Restore every wrapped CreateAI and forget the battle's groups."""
    global _qb
    for module, orig in reversed(_wrapped):
        current = getattr(module, "CreateAI", None)
        if getattr(current, _ORIG_ATTR, None) is orig:
            module.CreateAI = orig
    _wrapped.clear()
    _sides.clear()
    _qb = None
