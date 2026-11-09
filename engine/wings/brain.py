"""Wing brain glue: the live world in, the wing's target group and member
condition statuses out (spec 2026-11-09-wing-leaders-phase-a-design.md
§5-§7, §9, §10).

The decision logic is pure (assess, chain, decisions, plans); this module is
the only one that reads ships. Ships are found by name in the wing's home
set: the set holding most of its live non-player members, else the player's.
A name that resolves to nothing, or to a dead / dying ship, is skipped, never
raised on.
"""
import dataclasses
import os
import sys

from engine.wings import (assess, attack, chain, decisions, dials, plans,
                          protect, reserve, roster, rotate)

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


def _shield_faces(ship) -> tuple:
    """The six per-face fractions (index = face constant), () with no
    shield generator."""
    shields = ship.GetShields()
    if shields is None:
        return ()
    return tuple(float(shields.GetSingleShieldPercentage(i))
                 for i in range(_NUM_SHIELDS))


def _shield_fraction(ship) -> float:
    faces = _shield_faces(ship)
    return sum(faces) / _NUM_SHIELDS if faces else 0.0


def _weapons_down(ship) -> bool:
    """Every existing weapon system is disabled or has no condition left;
    no weapons at all counts. Weapons-first aim lands on the system's own
    condition (stock ChooseTargetSubsystem picks the non-targetable system
    itself), which its IsDisabled() -- the children's aggregate -- never
    reads; at 0 the FireScript stops choosing it and the weapon is silent
    (Phase C Task 6)."""
    systems = [s for s in (ship.GetTorpedoSystem(), ship.GetPhaserSystem(),
                           ship.GetPulseWeaponSystem()) if s is not None]
    return all(s.IsDisabled() or s.GetCondition() <= 0.0 for s in systems)


def _cloaked(ship) -> bool:
    """Cloaked or cloaking: the cloak subsystem's own state predicates (the
    ones stock SelectTarget.FindGoodTarget reads; it skips IsCloaked). A
    ship with no cloaking device is never cloaked."""
    cloak = ship.GetCloakingSubsystem()
    return cloak is not None and bool(cloak.IsCloaked() or cloak.IsCloaking())


def view_of(ship, wing_id=None, is_commander=False, weapons=False):
    if not _alive(ship):
        return None
    loc = ship.GetWorldLocation()
    hull = ship.GetHull()
    target = ship.GetTarget()
    faces = _shield_faces(ship)
    return assess.ShipView(
        name=ship.GetName(),
        pos=(loc.x, loc.y, loc.z),
        # No hull subsystem reads as intact, so it never trips desperation.
        hull=float(hull.GetConditionPercentage()) if hull is not None else 1.0,
        shield=sum(faces) / _NUM_SHIELDS if faces else 0.0,
        weak_face=min(faces) if faces else 0.0,
        power=_rated_power(ship),
        wing_id=wing_id,
        is_commander=is_commander,
        target=target.GetName() if target is not None else None,
        faces=faces if len(faces) == _NUM_SHIELDS else (),
        weapons_down=_weapons_down(ship) if weapons else False,
    )


def _find_anywhere(name):
    import App
    return App.ShipClass_GetObject(None, name)   # null set: every set


def arm_chain(wing) -> None:
    eligible, player, armed, views = [], None, 0.0, []
    for name, m in wing.members.items():
        v = view_of(_find_anywhere(name))
        if v is not None:
            armed += assess.strength(v)
            views.append(v)
        if m.is_player:
            player = name
        elif m.in_chain_eligible:
            ship = _find_anywhere(name)
            eligible.append((name, _rated_power(ship) if ship else 0.0))
    wing.chain = chain.build_chain(eligible, player)
    # Withdraw compares the live wing against this (spec §2).
    wing.armed_strength = armed
    wing.commander = wing.chain[0] if wing.chain else None
    _arm_reserve(wing, views)


def _arm_reserve(wing, views) -> None:
    """The reserve pick (spec §6), at arming. A late wave's chain re-arms
    on each first-wave arrival, so the pick lands once the wave reaches
    reserve_min_wing; a reserve already held is kept (its clock too), and
    a committed one is never re-picked."""
    import App
    players = {n for n, m in wing.members.items() if m.is_player}
    # Counted the way a led tick counts (live non-players in the home set),
    # so a member elsewhere at arming never reads as a loss on the first
    # tick.
    home = _home_set(wing)
    wing.reserve_live = 0 if home is None else sum(
        1 for name in wing.members if name not in players
        and _alive(App.ShipClass_GetObject(home, name)))
    if wing.reserve_spent or wing.reserve is not None:
        return
    wing.reserve = reserve.pick_reserve(
        views, wing.commander, players, int(dials.get("reserve_min_wing")))
    if wing.reserve is None:
        return
    wing.reserve_since = float(App.g_kUtopiaModule.GetGameTime())
    for name, m in wing.members.items():
        m.reserve = name == wing.reserve
    log("%s reserve %s" % (wing.wing_id, wing.reserve))


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


class _EnemySnapshot:
    """One side's enemy views, shared by every wing that reads the same
    candidates in the same home set (final review M2). Plain values only:
    names, numbers and ShipViews (frozen), never a ship object."""
    __slots__ = ("built_s", "views", "flags", "users")

    def __init__(self, built_s):
        self.built_s = built_s
        self.views = []          # ShipView per live, uncloaked candidate
        self.flags = []          # (wing_id, is_commander) each view carries
        self.users = set()       # wing ids that have read this entry


# (id(home set), id(enemy group), candidate names) -> _EnemySnapshot
_enemy_cache: dict = {}


def reset_cache() -> None:
    _enemy_cache.clear()


def _roster_flags(name):
    other = roster.wing_of(name)
    if other is None:
        return (None, False)
    return (other.wing_id, other.commander == name)


def _enemy_views(wing, home, candidates, ship_of):
    """The enemy ShipViews for `candidates`: built once per brain period per
    (home set, enemy group, candidates) and reused by the other wings that
    tick inside that period. A wing never reuses an entry it already read,
    so its own next tick always sees a fresh world. The roster flags
    (wing_id, is_commander) are re-read on every use, so a handover between
    two wings' ticks is never stale."""
    import App
    now = float(App.g_kUtopiaModule.GetGameTime())
    key = (id(home), id(wing.enemy_group), tuple(candidates))
    period = dials.get("brain_period_s")
    entry = _enemy_cache.get(key)
    if (entry is None or wing.wing_id in entry.users
            or not 0.0 <= now - entry.built_s < period):
        # Rebuilds are about one per side per period: drop expired entries
        # (an old candidate list keys nothing any wing will ask for again).
        for k in [k for k, e in _enemy_cache.items()
                  if not 0.0 <= now - e.built_s < period]:
            del _enemy_cache[k]
        entry = _EnemySnapshot(now)
        for name in candidates:
            ship = ship_of(name)
            # A cloaked enemy is no candidate: SelectTarget would skip it,
            # so a group of only cloaked ships (the nothing-in-reach pick)
            # idles the wing. It comes back on the tick after it decloaks.
            if ship is not None and _cloaked(ship):
                continue
            flags = _roster_flags(name)
            v = view_of(ship, *flags, weapons=True)
            if v is not None:
                entry.views.append(v)
                entry.flags.append(flags)
        _enemy_cache[key] = entry
    else:
        # Warm: a ship that died since the build drops out (a lookup and
        # two predicates, no shield reads), so no wing targets a corpse.
        views, all_flags = [], []
        for v, old in zip(entry.views, entry.flags):
            if not _alive(ship_of(v.name)):
                continue
            flags = _roster_flags(v.name)
            if flags != old:
                v = dataclasses.replace(
                    v, wing_id=flags[0], is_commander=flags[1])
            views.append(v)
            all_flags.append(flags)
        entry.views, entry.flags = views, all_flags
    entry.users.add(wing.wing_id)
    return list(entry.views)


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
    # Candidates: the enemy group, then any listed (km) ship not in it --
    # a neutral protect target is in no side's group.
    km = wing.km_priorities()
    candidates = list(wing.enemy_group.GetNameTuple())
    seen = set(candidates)
    candidates += [n for n in km if n not in seen]
    enemies = _enemy_views(wing, home, candidates, ship_of)

    # 2. Chain: the first entry alive AND in the home set commands.
    if not wing.leaderless:
        commander = chain.current_commander(wing.chain,
                                            lambda n: n in members)
        if commander is None and any(_alive(_find_anywhere(n))
                                     for n in wing.chain):
            # Command is alive but away (a warp): temporarily leaderless,
            # not latched -- stock targeting, no desperation, until a chain
            # entry is in the home set again.
            _command_away(wing, enemies, km)
            return
        wing.away = False
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
    now = float(App.g_kUtopiaModule.GetGameTime())
    anchor = members[wing.commander]
    near = _near_anchor(enemies, anchor)
    protectees = _protectees(wing, members, ship_of)
    rates = _sample_strength(wing, members, protectees, now)
    if wing.withdraw_since is not None:
        # Clear: no enemy within engage_gu of the anchor (spec §5).
        if near:
            wing.clear_since = None
        elif wing.clear_since is None:
            wing.clear_since = now
    player_commands = _player_commands(wing)
    if player_commands and wing.withdraw_since is not None:
        # Withdraw never applies to a player-led wing: a handover to the
        # player ends one in progress (the cooldown starts).
        _end_withdraw(wing, now)
    _disable_cap(wing, now)
    ctx = decisions.Context(
        members=list(members.values()), anchor=anchor, enemies=enemies,
        current=wing.decision, protectees=protectees, rates=rates,
        armed_strength=wing.armed_strength, now=now,
        withdraw_since=wing.withdraw_since,
        withdraw_cooldown_until=wing.withdraw_cooldown_until,
        clear_since=wing.clear_since, player_commands=player_commands,
        slot_eligible=_slot_eligible(wing, members),
        current_primary=wing.primary,
        disable_done=frozenset(wing.disable_done),
        slot_holders=frozenset(n for n, m in wing.members.items()
                               if m.slot is not None),
        reserve=wing.reserve)
    decision = decisions.pick(ctx)
    if decision.name != wing.decision:
        log("%s decision %s -> %s"
            % (wing.wing_id, wing.decision, decision.name))
        wing.decision = decision.name
    choice = decision.choose(ctx)
    _track_disable(wing, decision.name, choice, now)
    if choice.withdraw and wing.withdraw_since is None:
        wing.withdraw_since = now
        log("%s withdraw" % wing.wing_id)
    elif not choice.withdraw and wing.withdraw_since is not None:
        _end_withdraw(wing, now)

    # 5. Apply.
    player_target = _player_target(wing) if player_commands else None
    if choice.withdraw:
        prios = {}                     # nobody turns back to fight
    else:
        prios = plans.target_priorities(enemies, anchor, choice, km,
                                        player_target, player_commands)
    _write_group(wing.target_group, prios)
    _update_reserve(wing, members, enemies, near, anchor, now)
    guards, fallers, withdrawers = _apply_moves(
        wing, members, anchor, enemies, near, protectees, choice, now)
    busy = ({wing.commander} | guards | fallers | withdrawers
            | {n for n, m in wing.members.items()
               if m.is_player or m.reserve})
    holders = _apply_attack(wing, members, enemies, choice, busy, ship_of)

    player = next((n for n, m in wing.members.items() if m.is_player), None)
    # A commanding player with nothing to fight: the escorts form up on it.
    gather = choice.gather or (player_commands and not prios)
    flags = plans.rejoin_flags(
        list(members.values()), anchor,
        {n: m.rejoin for n, m in wing.members.items()},
        gather, wing.commander, player)
    for name, m in wing.members.items():
        # Outside the home set WingRejoin cannot reach the commander: off.
        # Withdrawing, every member runs its own line: off too. A
        # slot-holder's slot hangs off the primary, inside reach: off. The
        # reserve holds its own point behind the commander: off.
        flag = (flags.get(name, False) and not choice.withdraw
                and name not in holders and name != wing.reserve)
        m.rejoin = flag
        _push(m, "rejoin", flag)

    primary = _primary_of(prios)
    if primary != wing.primary:
        wing.primary = primary
        for m in wing.members.values():
            for node in m.select_nodes:
                node.ForceUpdate()


def _disable_cap(wing, now) -> None:
    """A disable running disable_max_s on one target gives it up: the
    target is done, so disable scores 0 against it from this tick."""
    if (wing.disable_target is not None
            and now - wing.disable_since >= dials.get("disable_max_s")):
        wing.disable_done.add(wing.disable_target)


def _track_disable(wing, decision, choice, now) -> None:
    """Record when disable starts on a target; when it ends for any reason
    but the target dying (weapons down, the cap, out of reach, another
    decision winning), the target is done: disable never re-enters
    against it (final review I1)."""
    target = choice.primary if decision == "disable" else None
    old = wing.disable_target
    if old is not None and old != target:
        if _alive(_find_anywhere(old)):
            wing.disable_done.add(old)
            log("%s disable done %s" % (wing.wing_id, old))
        wing.disable_target = wing.disable_since = None
    if target is not None and wing.disable_target is None:
        wing.disable_target, wing.disable_since = target, now


def _near_anchor(enemies, anchor):
    """Enemies within engage_gu of the anchor: Phase B's reach (withdraw
    odds, protect attackers, the fall-back centroid)."""
    reach = dials.get("engage_gu")
    return [e for e in enemies if assess.dist(e.pos, anchor.pos) <= reach]


def _protectees(wing, members, ship_of):
    """Live member views, then the wing's protect ships (Quick Battle's
    protect list, the player) resolved in the home set, deduped."""
    out = list(members.values())
    seen = set(members)
    for name in wing.protect_names():
        if name in seen:
            continue
        seen.add(name)
        v = view_of(ship_of(name), *_roster_flags(name))
        if v is not None:
            out.append(v)
    return out


def _sample_strength(wing, members, protectees, now):
    """Append one strength sample per live protectee (members on their
    record, protect ships on the wing), trim to heavy_fire_window_s, and
    return the damage rate per name."""
    window = dials.get("heavy_fire_window_s")
    rates = {}
    others = {}
    for v in protectees:
        m = wing.members.get(v.name)
        hist = (m.strength_hist if m is not None
                else wing.protect_hist.get(v.name, []))
        hist = [(t, x) for t, x in hist if now - t <= window]
        hist.append((now, assess.strength(v)))
        if m is not None:
            m.strength_hist = hist
        else:
            others[v.name] = hist
        rates[v.name] = protect.damage_rate(hist, now, window)
    wing.protect_hist = others        # a protect ship gone drops its history
    return rates


def _strength_frac(v):
    return assess.strength(v) / v.power if v.power > 0.0 else 0.0


def _update_reserve(wing, members, enemies, near, anchor, now) -> None:
    """Commit the reserve on the first trigger (spec §6), before the moves
    are applied. A reserve that is gone (dead, out of the home set) is
    spent; one that now commands is committed. The live count and the last
    centroid in reach are kept every led tick, reserve or not."""
    live = sum(1 for n in members if not wing.members[n].is_player)
    if near:
        wing.last_centroid = assess.centroid(near)
    held = wing.reserve
    if held is not None:
        if held not in members:
            why = "gone"
        elif held == wing.commander:
            why = "command"
        else:
            primary = next((e for e in enemies if e.name == wing.primary),
                           None)
            engage = dials.get("engage_gu")
            why = reserve.commit_reason(
                lost_member=live < wing.reserve_live,
                decision=wing.decision,
                primary_hull=primary.hull if primary is not None else None,
                ours=assess.side_strength(members.values(), anchor.pos,
                                          engage),
                theirs=assess.side_strength(enemies, anchor.pos, engage),
                enemies_in_reach=len(near),
                held_s=now - wing.reserve_since)
        if why is not None:
            _commit_reserve(wing, why)
    wing.reserve_live = live


def _commit_reserve(wing, why) -> None:
    """Permanently: the reserve is an ordinary member from here on."""
    if wing.reserve is None:
        return
    wing.reserve = None
    wing.reserve_spent = True
    for m in wing.members.values():
        m.reserve = False
    log("%s reserve commits (%s)" % (wing.wing_id, why))


def _reserve_point(wing, members, anchor, near):
    """reserve_gu farther from the enemy centroid than the anchor, on the
    reserve's own bearing (reserve.hold_point): the centroid in reach,
    else the last one seen, else the anchor itself."""
    centroid = (assess.centroid(near) if near else
                wing.last_centroid if wing.last_centroid is not None
                else anchor.pos)
    return reserve.hold_point(anchor.pos, members[wing.reserve].pos,
                              centroid, dials.get("reserve_gu"))


def _apply_moves(wing, members, anchor, enemies, near, protectees, choice,
                 now):
    """Withdraw (every member), guards (protect) and fallers (the standing
    rotate rule): move points and branch pushes for every non-player
    member. One move point per member; the sets are disjoint."""
    # Exclusivity, all four rules (the player is never in any set):
    # 1. withdraw > everything: a withdrawing wing has no protectee and no
    #    fallers, and tick_wing turns rejoin off for it;
    # 2. guard > fallback: guards are picked first and excluded from falling
    #    back; a ship already falling back (last tick's fallback_since) or
    #    with shields under rotate_out_shield is never a guard candidate;
    # 3. the commander is never a guard or a faller; the protectee is never
    #    its own guard, but a member protectee MAY fall back (ruling
    #    2026-11-09) and its guards then cover its current position;
    # 4. fallback / guard > rejoin by tree priority only: m.rejoin may stay
    #    True under either (it keeps rejoin's hysteresis), and the guard and
    #    fallback branches outrank the rejoin branch.
    # 5. the reserve (Phase C) is never a guard or a faller: it holds the
    #    reserve point, or withdraws with everyone.
    players = {n for n, m in wing.members.items() if m.is_player}
    held = {wing.reserve} if wing.reserve is not None else set()
    points = {}

    # Withdraw: every non-player member opens distance on its own line away
    # from the enemy centroid, recomputed each tick; nobody rejoins.
    withdrawers = set()
    if choice.withdraw:
        away_from = assess.centroid(near or enemies)
        step = dials.get("withdraw_step_gu")
        for name, v in members.items():
            if name in players:
                continue
            withdrawers.add(name)
            points[name] = (rotate.fallback_point(v.pos, away_from, step)
                            if away_from is not None else None)

    # Protect: guards between the protectee and its primary attacker.
    guards = []
    protectee = None
    if choice.protectee is not None:
        protectee = next((p for p in protectees
                          if p.name == choice.protectee), None)
        attacker = next((e for e in enemies if e.name == choice.primary),
                        None)
        if protectee is not None and attacker is not None:
            live = list(members.values())
            # A ship already falling back is never a guard: it keeps
            # falling back until its shields recover.
            falling = {n for n, m in wing.members.items()
                       if m.fallback_since is not None}
            prev = ([n for n, m in wing.members.items() if m.guard]
                    if wing.guarded == protectee.name else [])
            guards = protect.pick_guards(
                live, protectee, {wing.commander} | players | falling | held,
                {v.name: _strength_frac(v) for v in live}, prev)
            point = protect.guard_point(protectee.pos, attacker.pos)
            for name in guards:
                points[name] = point

    # Fall back: never while withdrawing, never with nothing to hide from.
    fallers = {}
    if not choice.withdraw and near:
        exclude = {wing.commander} | players | set(guards) | held
        fallers = rotate.fallback_flags(
            list(members.values()), {n: m.fallback_since
                                     for n, m in wing.members.items()},
            now, exclude, wing.fallback_cooldown, wing.fallback_hull)
        behind = rotate.fallback_point(anchor.pos, assess.centroid(near),
                                       dials.get("regroup_gather_gu"))
        for name, since in fallers.items():
            if since is not None:
                points[name] = behind

    holding = held and not choice.withdraw
    if holding:
        points[wing.reserve] = _reserve_point(wing, members, anchor, near)

    wing.guarded = protectee.name if guards else None
    for name, m in wing.members.items():
        if m.is_player:
            continue
        m.guard = name in guards
        was = m.fallback_since
        m.fallback_since = fallers.get(name)
        if was is None and m.fallback_since is not None:
            log("%s %s falls back (%s)" % (
                wing.wing_id, name,
                rotate.reason(name, members.get(name), wing.fallback_hull)))
        elif was is not None and m.fallback_since is None:
            log("%s %s returns" % (wing.wing_id, name))
        m.move_point = points.get(name)
        _push(m, "withdraw", name in withdrawers)
        _push(m, "guard", m.guard)
        _push(m, "fallback", m.fallback_since is not None)
        _push(m, "reserve", bool(holding) and name in held)
    return (set(guards),
            {n for n, since in fallers.items() if since is not None},
            withdrawers)


def _slot_eligible(wing, members) -> int:
    """Live non-player, non-commander members in the home set, less last
    tick's fallers and the reserve. Guards are not taken off: they are
    chosen after the decision."""
    return sum(1 for name in members
               if name != wing.commander
               and not wing.members[name].is_player
               and wing.members[name].fallback_since is None
               and not wing.members[name].reserve)


def _slot_points(wing, members, choice, busy, ship_of):
    """(candidate views, (body_dir, world point) per slot) for the choice's
    slot directions round its primary, or None when nobody can hold a slot
    this tick: no directions, or a primary that is no live, uncloaked
    ship. A member without the wing tree (no wing FireScript, e.g. a wrap
    that failed) is no candidate: it could not fly or fire the slot."""
    if not choice.slot_dirs or choice.primary is None:
        return None
    target = ship_of(choice.primary)
    # The warm enemy snapshot re-checks only _alive, so a primary that
    # cloaked since the build is caught here.
    if not _alive(target) or _cloaked(target):
        return None
    cands = [v for n, v in members.items()
             if n not in busy and wing.members[n].fire_script is not None]
    if not cands:
        return None
    dirs = choice.slot_dirs
    n = len(cands) if choice.slot_all else len(dirs)
    loc = target.GetWorldLocation()
    R = target.GetWorldRotation()
    cols = [(c.x, c.y, c.z) for c in (R.GetCol(0), R.GetCol(1), R.GetCol(2))]
    standoff = dials.get("attack_standoff_gu")
    # More holders than directions (slot_all): each wrap turned, so no two
    # share a point (review M2).
    slots = [(d, attack.slot_point((loc.x, loc.y, loc.z), cols, d, standoff))
             for d in attack.spread_dirs(dirs, n)]
    return cands, slots


def _apply_attack(wing, members, enemies, choice, busy, ship_of):
    """Attack slots (spec §3): the choice's slot directions round its
    primary go to the members not in `busy` (commander, players, guards,
    fallers, reserve, withdrawers), nearest first. Each holder's wing
    FireScript and ship target follow the primary (changes only) and its
    aim mode follows choice.weapons_first; its attack branch is pushed on.
    Everyone else has no slot and the branch off. Returns the holders.
    `enemies` is unused (kept for the plan's interface): the primary is
    resolved live through `ship_of`, the home-set lookup."""
    holders = {}
    prev_assign = wing.attack_prev
    wing.attack_prev = None
    plan = _slot_points(wing, members, choice, busy, ship_of)
    if plan is not None:
        cands, slots = plan
        dirs = tuple(d for d, _p in slots)
        # Incumbency (final review I2) only while the primary and the slot
        # set are unchanged; otherwise a fresh nearest-first pairing.
        prev = (prev_assign[2] if prev_assign is not None
                and prev_assign[:2] == (choice.primary, dirs) else None)
        got = attack.assign_slots(cands, [p for _d, p in slots], prev)
        holders = {name: slots[j][0] for name, j in got.items()}
        wing.attack_prev = (choice.primary, dirs, got)
    primary = choice.primary
    standoff = dials.get("attack_standoff_gu")
    for name, m in wing.members.items():
        if m.is_player:
            continue
        if name not in holders:
            m.slot = None
            m.slot_hold = False
            m.attack_target = None
            _push(m, "attack", False)
            continue
        slot = (primary, holders[name], standoff)
        if slot != m.slot:
            m.slot_hold = False           # WingMoveTo re-enters on arrival
        m.slot = slot
        fire = m.fire_script
        if m.attack_target != primary:
            if fire is not None:
                fire.SetTarget(primary)
            ship = ship_of(name)
            if ship is not None:
                ship.SetTarget(primary)
            m.attack_target = primary
        if m.weapons_first != choice.weapons_first:
            if fire is not None:
                if choice.weapons_first:
                    fire.RestoreSubsystemTargets()
                else:
                    fire.IgnoreSubsystemTargets()
            m.weapons_first = choice.weapons_first
        _push(m, "attack", True)
        _push(m, "rejoin", False)
    sig = ((primary, tuple(sorted(holders)), bool(choice.weapons_first))
           if holders else None)
    if sig != wing.attack_sig:
        wing.attack_sig = sig
        if sig is not None:
            log("%s attack %s slots=%d weapons_first=%d"
                % (wing.wing_id, primary, len(holders),
                   int(choice.weapons_first)))
        else:
            log("%s attack ends" % wing.wing_id)
    return set(holders)


def _end_withdraw(wing, now) -> None:
    wing.withdraw_cooldown_until = now + dials.get("withdraw_cooldown_s")
    wing.withdraw_since = None
    wing.clear_since = None
    log("%s withdraw ends" % wing.wing_id)


def _stand_down(wing, why) -> None:
    """Leaderless or command away: every Phase B branch, the attack and
    reserve branches off, no move points or slots (like rejoin). A withdraw
    in progress ends; a held reserve is committed, and a wing without
    command never holds one later (spent either way)."""
    _commit_reserve(wing, why)
    wing.reserve_spent = True
    if wing.withdraw_since is not None:
        import App
        _end_withdraw(wing, float(App.g_kUtopiaModule.GetGameTime()))
    wing.guarded = None
    if wing.attack_sig is not None:
        wing.attack_sig = None
        log("%s attack ends" % wing.wing_id)
    wing.attack_prev = None
    for m in wing.members.values():
        m.move_point = None
        m.guard = False
        m.fallback_since = None
        m.slot = None
        m.slot_hold = False
        m.attack_target = None
        if m.is_player:
            continue
        for kind in ("withdraw", "guard", "fallback", "attack", "reserve"):
            _push(m, kind, False)


def _primary_of(prios):
    """The written primary: the highest priority at >= 3.0 (ties by name),
    else None. Change detection only (ForceUpdate)."""
    top = [(-p, n) for n, p in prios.items() if p >= 3.0]
    return min(top)[1] if top else None


def _player_commands(wing) -> bool:
    m = wing.members.get(wing.commander)
    return m is not None and m.is_player


def _player_target(wing):
    """The player's current target name (call only when the player
    commands)."""
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


def _command_away(wing, enemies, km) -> None:
    """Command alive but away: every candidate at stock priority, each
    member's popularity as found, rejoin off for every member in any set
    (nobody can rejoin a commander in another set); SelectTarget forced once
    on entering. Not latched: the next tick with a chain entry home is a
    normal one (popularity re-applied there)."""
    from engine.wings import tree
    _write_group(wing.target_group, plans.leaderless_priorities(enemies, km))
    entering = not wing.away
    if entering:
        wing.away = True
        wing.primary = None
        log("%s command away" % wing.wing_id)
    for m in wing.members.values():
        tree.restore_popularity(m)
        m.rejoin = False
        _push(m, "rejoin", False)
        if entering:
            for node in m.select_nodes:
                node.ForceUpdate()
    _stand_down(wing, "away")


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
    _stand_down(wing, "leaderless")


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
