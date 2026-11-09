"""Quick Battle groups fight as wings (spec
2026-11-09-wing-leaders-phase-a-design.md §4, §11 "Quick Battle consumer").

Armed from `battle_end.begin` for every plan-driven battle (no-op when
`engine.wings.service.enabled()` is false, the setup screen's "Wing
commanders" switch is Off (`plan.wings`), or BC's own GenerateShips ran):

- One wing per non-neutral group that has a member, id ``"qb:<group id>"``.
  Members are the MOBILE ships (an impulse engine with an authored max
  speed > 0) of the orders whose AI module (`spawn._details`, the same
  lookup that fills g_kShips) is QuickBattleAI or QuickBattleFriendlyAI.
  Station AI, stations given QuickBattleAI (BC's own table does that for
  Biranu Station) and neutral groups are never members: a station can't
  anchor a leash (spec §12 call 1). A non-member gets its stock tree and no
  redirect.
- The player joins the wing of `plan.player.group_id` (`is_player`); its
  name is read from App.Game_GetCurrentPlayer() at arm time.
- A late (warp-in) order is not a member at arm: `ship_arrived` adds it
  just before late_arrivals gives it its AI, outside the chain -- except
  that a wing whose members are ALL late (every order of a QB group shares
  its warp-in) builds its chain from its first MOBILE arrival wave (fixed by
  the first mobile ship to arrive: a late station never joins, so it cannot
  set the wave), re-running `brain.arm_chain` after each of those arrivals.
- The candidate enemy group is the QuickBattle group the members' stock AI
  attacks: enemies' wings `pFriendlies`, friendlies' wings `pEnemies`.
- `km_priorities` reads `km_targeting.priorities_for(allegiance)` at use, so
  a listed protect / hunt target keeps its weight in the wing group, and the
  brain counts a listed ship outside the enemy group (a neutral protect
  target) as a candidate. km arms after the wings, so those ships are seeded
  into the wing group at the first member's CreateAI, not at create_wing.

Mechanism (no SDK edit), the km_targeting pattern: the member modules'
CreateAI is wrapped for the battle. For a member ship the wrapper answers the
module's own `App.ObjectGroup_FromModule("QuickBattle.QuickBattle",
<attacked side>)` with the wing's `target_group` for that one call -- so every
SelectTarget built there shares the wing group, which the brain only ever
mutates (spec §2) -- and returns `tree.wrap_tree(pShip, <stock tree>, wing)`.
Any other ship goes through untouched. km_targeting wraps on top of this
wrapper (its own tag attribute, so neither mistakes the other's wrapper for
its own) and, for a ship `owns` names, calls straight through without its
own redirect.

Wing chains are armed (`service.arm`) after every initial member is added:
`begin` runs after GenerateShips, so the ships exist and their rated power
can be read.

`reset()` (from battle_end.reset: End Combat, Restart, the end timer, a
mission swap) restores every wrapped CreateAI and resets the wing service.
battle_end.reset calls km_targeting.reset first: km's wrapper sits on top.
"""
from __future__ import annotations

import logging

_log = logging.getLogger(__name__)

QB_MODULE = "QuickBattle.QuickBattle"
MEMBER_MODULES = ("QuickBattleAI", "QuickBattleFriendlyAI")
_ORIG_ATTR = "_dauntless_wings_qb_orig"
# allegiance -> the QuickBattle group that side's attack AI targets
_ATTACKED = {"enemy": "pFriendlies", "friendly": "pEnemies"}

_wrapped: list = []          # (module, original CreateAI)
_owned: dict = {}            # non-player member name -> its wing
_attacked: dict = {}         # wing id -> the attacked QuickBattle group attr
_by_group: dict = {}         # QB group id -> its wing
_first_wave: dict = {}       # all-late group id -> its first mobile
                             # arrivals' warp_in_s (None until one arrives)


def _is_mobile(ship) -> bool:
    """A ship that can move: an impulse engine whose authored max speed
    (the property's, not the damage-derated live figure) is above 0."""
    if ship is None:
        return False
    engine = ship.GetImpulseEngineSubsystem()
    prop = engine.GetProperty() if engine is not None else None
    speed = prop.GetMaxSpeed() if prop is not None else None
    return speed is not None and float(speed) > 0.0


def _member_module(qb, order):
    """The order's AI module name when it makes the ship a wing member,
    else None (station AI, neutral, no details)."""
    from engine.quickbattle import spawn
    side = spawn._SIDE.get(order.allegiance)
    if side is None:
        return None
    try:
        ai = spawn._details(qb, order.class_id, side)[0]
    except Exception:
        _log.exception("quickbattle wings: no AI module for %s", order.class_id)
        return None
    return ai if ai in MEMBER_MODULES else None


def arm(qb, plan) -> None:
    """Create, fill and arm the battle's wings and wrap the member AI
    modules. Never called with a stale battle: resets first."""
    import App
    from engine.quickbattle import km_targeting, naming
    from engine.wings import roster, service
    reset()
    if (plan is None or not service.enabled()
            or not getattr(plan, "wings", True)):    # the setup's switch Off
        return
    groups: dict = {}            # group id -> (allegiance, [initial names])
    late: set = set()            # group ids with a late order
    modules: list = []
    for n, order in enumerate(plan.orders, start=1):
        ai = _member_module(qb, order)
        if ai is None:
            continue
        name = naming.object_name(order.title, n)
        if order.warp_in_s > 0:
            late.add(order.group_id)
        elif not _is_mobile(App.ShipClass_GetObject(None, name)):
            continue             # a station (or a ship that did not spawn)
        _alleg, members = groups.setdefault(order.group_id, (order.allegiance, []))
        if order.warp_in_s <= 0:
            members.append(name)
        if ai not in modules:
            modules.append(ai)
    player = App.Game_GetCurrentPlayer()
    player_gid = getattr(plan.player, "group_id", None)
    if player is not None and player_gid is not None:
        groups.setdefault(player_gid, ("friendly", []))
    for gid, (allegiance, members) in groups.items():
        attacked = _ATTACKED[allegiance]
        wing = roster.create_wing(
            "qb:" + gid, App.ObjectGroup_FromModule(QB_MODULE, attacked),
            km_priorities=lambda a=allegiance: km_targeting.priorities_for(a))
        _attacked[wing.wing_id] = attacked
        _by_group[gid] = wing
        if gid == player_gid and player is not None:
            roster.add_member(wing, player.GetName(), is_player=True)
        for name in members:
            roster.add_member(wing, name)
            _owned[name] = wing
        if not wing.members and gid in late:
            # All late: its first mobile arrival wave will build the chain.
            _first_wave[gid] = None
    for name in modules:
        _wrap(name)
    for wing in _by_group.values():
        service.arm(wing)


def _wrap(module_name) -> None:
    try:
        # As StartSimulation2 and late_arrivals resolve it.
        module = __import__(module_name)
    except Exception:
        _log.exception("quickbattle wings: cannot import AI %s; its ships "
                       "fight without wings", module_name)
        return
    orig = getattr(module, "CreateAI", None)
    if orig is None or getattr(orig, _ORIG_ATTR, None) is not None:
        return

    def CreateAI(pShip, *args, **kw):
        return _create_ai(orig, pShip, args, kw)

    setattr(CreateAI, _ORIG_ATTR, orig)
    module.CreateAI = CreateAI
    _wrapped.append((module, orig))


def owns(name) -> bool:
    """True when `name` is a wing member whose CreateAI this module
    redirects (km_targeting then leaves the redirect to us)."""
    return name in _owned


def _create_ai(orig, pShip, args, kw):
    wing = _owned.get(pShip.GetName()) if pShip is not None else None
    if wing is None:
        return orig(pShip, *args, **kw)
    import App
    from engine.wings import tree
    group, attacked = wing.target_group, _attacked[wing.wing_id]
    real = App.ObjectGroup_FromModule

    def FromModule(module_name, attr_name):
        if module_name == QB_MODULE and attr_name == attacked:
            return group
        return real(module_name, attr_name)

    # Listed (km) ships the enemy group lacks -- a neutral protect target --
    # are candidates from the start; km is armed by now (battle_end.begin
    # arms it after us, StartSimulation2 runs CreateAI after that).
    try:
        for name, priority in wing.km_priorities().items():
            if not group.IsNameInGroup(name):
                group[name] = {"Priority": priority}
    except Exception:
        _log.exception("quickbattle wings: listed ships not seeded for %s",
                       pShip.GetName())
    App.ObjectGroup_FromModule = FromModule
    try:
        stock = orig(pShip, *args, **kw)
    finally:
        App.ObjectGroup_FromModule = real
    try:
        return tree.wrap_tree(pShip, stock, wing)
    except Exception:
        # StartSimulation2's AI loop runs this: the ship keeps its stock tree.
        _log.exception("quickbattle wings: tree not wrapped for %s",
                       pShip.GetName())
        return stock


def ship_arrived(qb, order, name) -> None:
    """A late ship of `order` is in the battle, its AI not yet set: it joins
    its group's wing -- in the chain only when the wing had no initial
    member and this is its first MOBILE arrival wave (the chain is rebuilt
    after each), otherwise outside it. Never raises."""
    if not _by_group:
        return
    try:
        import App
        from engine.wings import brain, roster
        wing = _by_group.get(order.group_id)
        if wing is None or _member_module(qb, order) is None:
            return
        if not _is_mobile(App.ShipClass_GetObject(None, name)):
            return
        gid = order.group_id
        if gid in _first_wave and _first_wave[gid] is None:
            _first_wave[gid] = order.warp_in_s       # first mobile arrival
        eligible = gid in _first_wave and _first_wave[gid] == order.warp_in_s
        roster.add_member(wing, name, chain_eligible=eligible)
        _owned[name] = wing
        if eligible:
            brain.arm_chain(wing)
    except Exception:
        _log.exception("quickbattle wings: %s did not join its wing", name)


def reset() -> None:
    """Restore every wrapped CreateAI and drop every wing."""
    from engine.wings import service
    for module, orig in reversed(_wrapped):
        current = getattr(module, "CreateAI", None)
        if getattr(current, _ORIG_ATTR, None) is orig:
            module.CreateAI = orig
    _wrapped.clear()
    _owned.clear()
    _attacked.clear()
    _by_group.clear()
    _first_wave.clear()
    service.reset()
