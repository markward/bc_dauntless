"""Kobayashi Maru enemy targeting: the protected ship is the enemies' first
choice, the way BC's own E6M1 weights an escort target.

Victory spec 2026-10-23 §5.2 (live-check fix 1, Mark's ruling: E6M1's
approach). E6M1 (Maelstrom/Episode6/E6M1/E6M1.py:595-598) gives each attacker
an `App.ObjectGroupWithInfo` with `{"Priority": 2.0}` on the ship it must kill
and `{"Priority": 1.0}` on the player; the SDK's SelectTarget
(AI/Preprocessors.py:1564-1603) adds Priority x fPriorityFactor (1.0) to its
distance, damage-dealt and popularity terms, so attackers mostly go for the
escort target and still turn on whoever is hurting them.

Stock Quick Battle enemy AI (QuickBattleAI, StarbaseAI) targets
`App.ObjectGroup_FromModule("QuickBattle.QuickBattle", "pFriendlies")`: every
friendly equal, and a NEUTRAL protected ship not a candidate at all. While a
Kobayashi Maru battle is armed, this module builds one weighted group for the
battle -- the protected ship at PROTECTED_TARGET_PRIORITY, every pFriendlies
member at OTHER_TARGET_PRIORITY -- and hands it to each enemy's attack AI.

Mechanism (no SDK edit): the CreateAI of every AI module an enemy of the plan
will be given (`spawn._details`, the same lookup that fills g_kShips) is
wrapped for the battle. For a ship in `pEnemies` the wrapper answers the
module's own `App.ObjectGroup_FromModule("QuickBattle.QuickBattle",
"pFriendlies")` with the weighted group for the duration of that one call;
every other FromModule call, and every non-enemy ship, goes through
untouched. StartSimulation2's AI loop and late_arrivals both reach the
wrapper through `__import__(module).CreateAI(ship)`. pFriendlies -- the
mission's friendly group, i.e. IFF -- is never written: a neutral protected
ship stays neutral, only a target candidate.

The protected ship is FIRST in the group. BC's attack compounds start on the
group's first name (NonFedAttack.py:11, CloakAttack.py:17) and the current
target earns fIsTargetFactor (1.0), exactly the priority gap; with the player
first, that head start would cancel the weighting.

`reset()` (from battle_end.reset: End Combat, Restart, the end timer, a
mission swap) restores every wrapped CreateAI and forgets the group, so an
Elimination battle afterwards runs BC's stock targeting untouched.
"""
from __future__ import annotations

import logging
from typing import Optional

_log = logging.getLogger(__name__)

PROTECTED_TARGET_PRIORITY = 2.0   # E6M1.py:597, the escort target
OTHER_TARGET_PRIORITY = 1.0       # E6M1.py:596, the player

QB_MODULE = "QuickBattle.QuickBattle"
QB_TARGETS_ATTR = "pFriendlies"
_ORIG_ATTR = "_dauntless_km_targeting_orig"

_group = None                 # the armed battle's ObjectGroupWithInfo
_qb = None                    # the QuickBattle module it was armed for
_protected: Optional[str] = None
_wrapped: list = []           # (module, original CreateAI)


def target_group():
    """The armed Kobayashi Maru battle's weighted enemy target group, or None."""
    return _group


def arm(qb, plan, protected_name, present) -> None:
    """Build the weighted group for a Kobayashi Maru battle and wrap the AI
    modules its enemies will be given. `present`: the protected ship already
    exists (False for a late, warp-in protected ship, which joins in
    `ship_arrived`)."""
    global _group, _qb, _protected
    import App
    reset()
    _qb = qb
    _protected = protected_name
    _group = App.ObjectGroupWithInfo()
    if protected_name is not None and present:
        _group[protected_name] = {"Priority": PROTECTED_TARGET_PRIORITY}
    sync(qb)
    for name in _enemy_ai_modules(qb, plan):
        _wrap(name)


def _enemy_ai_modules(qb, plan) -> list:
    from engine.quickbattle import spawn
    names = []
    for order in plan.orders:
        if order.allegiance != "enemy":
            continue
        try:
            ai = spawn._details(qb, order.class_id, "Enemy")[0]
        except Exception:
            _log.exception("quickbattle: no enemy AI module for %s", order.class_id)
            continue
        if ai and ai not in names:
            names.append(ai)
    return names


def _wrap(module_name) -> None:
    try:
        # As StartSimulation2 and late_arrivals resolve it.
        module = __import__(module_name)
    except Exception:
        _log.exception("quickbattle: cannot import enemy AI %s; its ships keep "
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


def _is_enemy(ship) -> bool:
    try:
        return bool(_qb.pEnemies.IsNameInGroup(ship.GetName()))
    except Exception:
        return False


def _create_ai(orig, pShip, args, kw):
    group, qb = _group, _qb
    if group is None or qb is None or pShip is None or not _is_enemy(pShip):
        return orig(pShip, *args, **kw)
    import App
    try:
        sync(qb)
    except Exception:
        # StartSimulation2's AI loop runs this: one failure must not abort AI
        # assignment for the ships after it. The group stays as it is.
        _log.exception("quickbattle: Kobayashi Maru targets not synced for %s",
                       pShip.GetName())
    real = App.ObjectGroup_FromModule

    def FromModule(module_name, attr_name):
        if module_name == QB_MODULE and attr_name == QB_TARGETS_ATTR:
            return group
        return real(module_name, attr_name)

    App.ObjectGroup_FromModule = FromModule
    try:
        return orig(pShip, *args, **kw)
    finally:
        App.ObjectGroup_FromModule = real


def sync(qb) -> None:
    """Every pFriendlies member not yet in the group joins at
    OTHER_TARGET_PRIORITY (a protected friendly keeps its 2.0)."""
    group = _group
    if group is None or qb is None:
        return
    for name in qb.pFriendlies.GetNameTuple():
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
    """A late ship is in the battle and its side's group: friendlies join the
    targets, and the protected ship joins at PROTECTED_TARGET_PRIORITY as the
    FIRST name, so enemies built from now on start on it (see the module
    docstring). Never raises."""
    if _group is None:
        return
    try:
        if name == _protected:
            _put_first(_group, name, {"Priority": PROTECTED_TARGET_PRIORITY})
        sync(qb)
    except Exception:
        _log.exception("quickbattle: Kobayashi Maru targets not updated for %s", name)


def reset() -> None:
    """Restore every wrapped CreateAI and forget the battle's group."""
    global _group, _qb, _protected
    for module, orig in reversed(_wrapped):
        current = getattr(module, "CreateAI", None)
        if getattr(current, _ORIG_ATTR, None) is orig:
            module.CreateAI = orig
    _wrapped.clear()
    _group = None
    _qb = None
    _protected = None
