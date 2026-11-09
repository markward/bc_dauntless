"""Wing brain glue: the live world in, the wing's target group and member
condition statuses out (spec 2026-11-09-wing-leaders-phase-a-design.md
§5-§7, §9, §10).

The decision logic is pure (assess, chain, decisions, plans); this module is
the only one that reads ships. Ships are found by name in the wing's home
set: the set holding most of its live non-player members, else the player's.
A name that resolves to nothing, or to a dead / dying ship, is skipped, never
raised on.
"""
import os
import sys

from engine.wings import assess, chain, decisions, plans, roster

_NUM_SHIELDS = 6


def log(msg: str) -> None:
    if os.environ.get("DAUNTLESS_WINGS_LOG") == "1":
        print("[wings] " + msg, file=sys.stderr)


def _alive(ship) -> bool:
    return ship is not None and not ship.IsDead() and not ship.IsDying()


def _rated_power(ship) -> float:
    power = ship.GetPowerSubsystem()
    prop = power.GetProperty() if power is not None else None
    return float(prop.GetPowerOutput()) if prop is not None else 0.0


def _shield_fraction(ship) -> float:
    shields = ship.GetShields()
    if shields is None:
        return 0.0
    return sum(float(shields.GetSingleShieldPercentage(i))
               for i in range(_NUM_SHIELDS)) / _NUM_SHIELDS


def view_of(ship, wing_id=None, is_commander=False):
    if not _alive(ship):
        return None
    loc = ship.GetWorldLocation()
    hull = ship.GetHull()
    return assess.ShipView(
        name=ship.GetName(),
        pos=(loc.x, loc.y, loc.z),
        # No hull subsystem reads as intact, so it never trips desperation.
        hull=float(hull.GetConditionPercentage()) if hull is not None else 1.0,
        shield=_shield_fraction(ship),
        power=_rated_power(ship),
        wing_id=wing_id,
        is_commander=is_commander,
    )


def _find_anywhere(name):
    import App
    return App.ShipClass_GetObject(None, name)   # null set: every set


def arm_chain(wing) -> None:
    eligible, player = [], None
    for name, m in wing.members.items():
        if m.is_player:
            player = name
        elif m.in_chain_eligible:
            ship = _find_anywhere(name)
            eligible.append((name, _rated_power(ship) if ship else 0.0))
    wing.chain = chain.build_chain(eligible, player)
    wing.commander = wing.chain[0] if wing.chain else None


def _home_set(wing):
    """The set holding the most live non-player members (ties: the set of
    the first such member in group order), else the player's set, else
    None. Recomputed every tick, so a warp moves the wing with its body."""
    counts, first = {}, []
    for name, m in wing.members.items():
        if m.is_player:
            continue
        ship = _find_anywhere(name)
        pset = ship.GetContainingSet() if _alive(ship) else None
        if pset is None:
            continue
        key = id(pset)
        if key not in counts:
            counts[key] = 0
            first.append(pset)
        counts[key] += 1
    if first:
        return max(first, key=lambda p: counts[id(p)])   # max keeps first
    for name, m in wing.members.items():
        if m.is_player:
            ship = _find_anywhere(name)
            if _alive(ship):
                return ship.GetContainingSet()
    return None


def _ensure_select_nodes(wing, ship_of) -> None:
    """Discover a member's stock SelectTarget nodes once its attack
    builders have run (they build SelectTarget lazily, on the first AI
    tick). Members that already have nodes are not walked again -- unless
    the ship's AI was replaced, which makes them stale. Never the player."""
    from engine.wings import tree
    for name, m in wing.members.items():
        if m.is_player:
            continue
        ship = ship_of(name)
        if not _alive(ship):
            continue
        if ship.GetAI() is not m.ai_root:
            m.select_nodes.clear()
            m.select_saved.clear()
        if not m.select_nodes:
            tree.discover_select_nodes(ship, m)


def tick_wing(wing) -> None:
    import App
    home = _home_set(wing)
    if home is None:
        return

    def ship_of(name):
        return App.ShipClass_GetObject(home, name)

    _ensure_select_nodes(wing, ship_of)

    # 1. Snapshot.
    members = {}
    for name in wing.members:
        v = view_of(ship_of(name), wing.wing_id)
        if v is not None:
            members[name] = v
    enemies = []
    for name in wing.enemy_group.GetNameTuple():
        other = roster.wing_of(name)
        v = view_of(ship_of(name),
                    other.wing_id if other is not None else None,
                    other is not None and other.commander == name)
        if v is not None:
            enemies.append(v)
    km = wing.km_priorities()

    # 2. Chain: the first entry alive AND in the home set commands.
    if not wing.leaderless:
        commander = chain.current_commander(wing.chain,
                                            lambda n: n in members)
        if commander is None and any(_alive(_find_anywhere(n))
                                     for n in wing.chain):
            # Command is alive but away (a warp): leave the wing's targets
            # alone, but nobody here can rejoin it -- stand the flags down
            # so members fight with their stock tree until it is back.
            for name in members:
                m = wing.members[name]
                m.rejoin = False
                _push(m, "rejoin", False)
            return
        if commander != wing.commander:
            if commander is not None:
                log("%s handover %s -> %s"
                    % (wing.wing_id, wing.commander, commander))
            wing.commander = commander
        if commander is None:
            _go_leaderless(wing)

    # 3. Leaderless: stock targeting plus desperation, nothing else.
    if wing.leaderless:
        _write_group(wing.target_group,
                     plans.leaderless_priorities(enemies, km))
        _desperation(wing, members, ship_of)
        return

    from engine.wings import tree
    for m in wing.members.values():
        tree.apply_popularity(m)          # the dial is read at use

    # 4. Decide.
    anchor = members[wing.commander]
    ctx = decisions.Context(members=list(members.values()), anchor=anchor,
                            enemies=enemies, current=wing.decision)
    decision = decisions.pick(ctx)
    if decision.name != wing.decision:
        log("%s decision %s -> %s"
            % (wing.wing_id, wing.decision, decision.name))
        wing.decision = decision.name
    choice = decision.choose(ctx)

    # 5. Apply.
    player_target = _player_target(wing)
    prios = plans.target_priorities(enemies, anchor, choice, km,
                                    player_target)
    _write_group(wing.target_group, prios)

    player = next((n for n, m in wing.members.items() if m.is_player), None)
    flags = plans.rejoin_flags(
        list(members.values()), anchor,
        {n: m.rejoin for n, m in wing.members.items()},
        choice.gather, wing.commander, player)
    for name, flag in flags.items():
        m = wing.members[name]
        m.rejoin = flag
        _push(m, "rejoin", flag)

    primary = _primary_of(prios, choice, player_target)
    if primary != wing.primary:
        wing.primary = primary
        for m in wing.members.values():
            for node in m.select_nodes:
                node.ForceUpdate()


def _primary_of(prios, choice, player_target):
    if player_target is not None and player_target in prios:
        return player_target
    if choice.primary in prios:
        return choice.primary
    if len(prios) == 1:          # nothing in reach: the nearest, at 3.0
        (name, p), = prios.items()
        if p >= 3.0:
            return name
    return None


def _player_target(wing):
    """The player's current target name, when the player commands."""
    m = wing.members.get(wing.commander)
    if m is None or not m.is_player:
        return None
    import App
    player = App.Game_GetCurrentPlayer()
    target = player.GetTarget() if player is not None else None
    return target.GetName() if target is not None else None


def _write_group(group, prios) -> None:
    for name in group.GetNameTuple():
        if name not in prios:
            group.RemoveName(name)
    for name, p in prios.items():
        group[name] = {"Priority": p}


def _push(member, kind, on) -> None:
    cond = member.conditions.get(kind)
    if cond is not None:
        cond.SetStatus(1 if on else 0)


def _go_leaderless(wing) -> None:
    """Latched: no re-election (spec §5). Members fight like stock BC."""
    wing.leaderless = True
    wing.primary = None
    log("%s leaderless" % wing.wing_id)
    from engine.wings import tree
    for m in wing.members.values():
        tree.restore_popularity(m)
        for node in m.select_nodes:
            node.ForceUpdate()
        m.rejoin = False
        _push(m, "rejoin", False)


def _desperation(wing, members, ship_of) -> None:
    views = [v for n, v in members.items() if not wing.members[n].is_player]
    already = {n: m.desperate for n, m in wing.members.items()}
    for name, kind in plans.desperation(views, already, wing.rng).items():
        m = wing.members[name]
        target = ship_of(name).GetTarget()
        if kind == "ram" and target is None:
            kind = "flee"            # nothing to ram
        m.desperate = kind
        log("%s %s %s" % (wing.wing_id, name, kind))
        if kind == "ram" and m.ram_script is not None:
            m.ram_script.SetTargetObjectName(target.GetName())
        _push(m, kind, True)


def tick_safely(wing) -> None:
    """One wing's tick, an exception logged once (dev mode) and contained so
    it never stops the other wings."""
    try:
        tick_wing(wing)
    except Exception as exc:  # noqa: BLE001 - one wing must not stop the rest
        from engine import dev_mode
        dev_mode.log_swallowed("wings brain tick", exc)


def tick_all() -> None:
    for wing in roster.wings():
        tick_safely(wing)
