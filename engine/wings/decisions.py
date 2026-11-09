"""Wing decision registry and the Phase A decisions (spec §8). Pure."""
from dataclasses import dataclass, field
from typing import Optional, Protocol

from engine.wings import assess, dials, protect


@dataclass
class Context:
    members: list
    anchor: assess.ShipView
    enemies: list
    current: Optional[str] = None
    protectees: list = ()
    rates: dict = field(default_factory=dict)
    armed_strength: float = 0.0
    now: float = 0.0
    withdraw_since: Optional[float] = None
    withdraw_cooldown_until: float = -1.0
    clear_since: Optional[float] = None
    player_commands: bool = False


@dataclass
class Choice:
    primary: Optional[str]
    secondaries: tuple = ()
    gather: bool = False
    protectee: Optional[str] = None
    withdraw: bool = False


class Decision(Protocol):
    name: str

    def score(self, ctx: Context) -> float: ...

    def choose(self, ctx: Context) -> Choice: ...


def _in_reach(ctx):
    leash = dials.get("leash_gu")
    return [e for e in ctx.enemies
            if assess.dist(e.pos, ctx.anchor.pos) <= leash]


def _outmatched(ctx) -> bool:
    engage = dials.get("engage_gu")
    ours = assess.side_strength(ctx.members, ctx.anchor.pos, engage)
    theirs = assess.side_strength(ctx.enemies, ctx.anchor.pos, engage)
    return ours < dials.get("odds_ratio") * theirs


def _weakest_choice(ctx, gather=False) -> Choice:
    reach = sorted(_in_reach(ctx), key=lambda v: (assess.strength(v), v.name))
    if not reach:
        return Choice(None, (), gather)
    return Choice(reach[0].name, tuple(v.name for v in reach[1:3]), gather)


class Regroup:
    name = "regroup"

    def score(self, ctx: Context) -> float:
        others = [m for m in ctx.members if m.name != ctx.anchor.name]
        radius = dials.get("leash_gu") + dials.get("leash_slack_gu")
        return 2.0 * assess.fraction_beyond(others, ctx.anchor.pos, radius)

    def choose(self, ctx: Context) -> Choice:
        return _weakest_choice(ctx, gather=True)


class SwarmWeakest:
    name = "swarm_weakest"

    def score(self, ctx: Context) -> float:
        return 0.4 if _outmatched(ctx) else 1.0

    def choose(self, ctx: Context) -> Choice:
        return _weakest_choice(ctx)


class SwarmCommander:
    name = "swarm_commander"

    def score(self, ctx: Context) -> float:
        if _outmatched(ctx) and any(e.is_commander for e in _in_reach(ctx)):
            return 1.0
        return 0.3

    def choose(self, ctx: Context) -> Choice:
        reach = _in_reach(ctx)
        cmds = [e for e in reach if e.is_commander]
        if not cmds:
            return Choice(None, (), False)
        cmd = min(cmds, key=lambda e: (assess.dist(e.pos, ctx.anchor.pos),
                                       e.name))
        mates = sorted((e for e in reach
                        if e.wing_id == cmd.wing_id and e.name != cmd.name),
                       key=lambda e: (assess.dist(e.pos, cmd.pos), e.name))
        return Choice(cmd.name, tuple(e.name for e in mates[:2]), False)


class Protect:
    name = "protect"

    def score(self, ctx: Context) -> float:
        hit = protect.threatened(ctx.protectees, ctx.rates, ctx.enemies,
                                 ctx.anchor)
        return 1.5 if hit is not None else 0.0

    def choose(self, ctx: Context) -> Choice:
        p = protect.threatened(ctx.protectees, ctx.rates, ctx.enemies,
                               ctx.anchor)
        if p is None:
            return Choice(None, ())
        atk = sorted(protect.attackers_of(p.name, ctx.enemies, ctx.anchor.pos,
                                          dials.get("engage_gu")),
                     key=lambda e: (assess.dist(e.pos, p.pos), e.name))
        if not atk:
            return Choice(None, (), protectee=p.name)
        return Choice(atk[0].name, tuple(e.name for e in atk[1:3]),
                      protectee=p.name)


class Withdraw:
    name = "withdraw"

    def score(self, ctx: Context) -> float:
        engage = dials.get("engage_gu")
        odds = dials.get("withdraw_odds")
        ours = assess.side_strength(ctx.members, ctx.anchor.pos, engage)
        theirs = assess.side_strength(ctx.enemies, ctx.anchor.pos, engage)
        if ctx.withdraw_since is not None:
            if (ctx.now - ctx.withdraw_since >= dials.get("withdraw_max_s")
                    or (ctx.clear_since is not None
                        and ctx.now - ctx.clear_since
                        >= dials.get("withdraw_clear_s"))
                    or (theirs > 0 and ours >= odds * 1.5 * theirs)):
                return 0.0
            return 2.5
        if ctx.player_commands or ctx.now < ctx.withdraw_cooldown_until:
            return 0.0
        if not ours < odds * theirs:
            return 0.0
        members = sum(assess.strength(m) for m in ctx.members)
        if not members < dials.get("withdraw_wing_frac") * ctx.armed_strength:
            return 0.0
        return 2.5

    def choose(self, ctx: Context) -> Choice:
        # Every member withdraws on its own line (brain._apply_moves): no
        # gather, nobody waits for the commander.
        return Choice(None, (), withdraw=True)


def _stock() -> list:
    return [Regroup(), SwarmWeakest(), SwarmCommander(), Protect(),
            Withdraw()]


_registry: list = _stock()


def register(decision) -> None:
    for i, d in enumerate(_registry):
        if d.name == decision.name:
            _registry[i] = decision
            return
    _registry.append(decision)


def registered() -> list:
    return list(_registry)


def reset_registry() -> None:
    _registry[:] = _stock()


def pick(ctx: Context):
    bonus = dials.get("stickiness")
    best, best_score = None, None
    for d in _registry:
        s = d.score(ctx) + (bonus if d.name == ctx.current else 0.0)
        if best is None or s > best_score or (
                s == best_score and d.name == ctx.current):
            best, best_score = d, s
    return best
