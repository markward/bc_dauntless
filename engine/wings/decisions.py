"""Wing decision registry and the Phase A decisions (spec §8). Pure."""
import dataclasses
from dataclasses import dataclass, field
from typing import Optional, Protocol

from engine.wings import assess, attack, dials, protect


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
    slot_eligible: int = 0
    # The target a running disable started on (the wing's disable_target,
    # which a command-away does not clear, as it does the primary): the
    # latch keys on it. disable_done: targets disable never re-enters
    # against (the brain's cap, or a disable that ended with the target
    # alive).
    disable_target: Optional[str] = None
    disable_done: frozenset = frozenset()
    # Last tick's slot-holders and the held reserve: their stations hang off
    # the primary or their own bearing, not the anchor, so Regroup does not
    # count them as strays (review M7).
    slot_holders: frozenset = frozenset()
    reserve: Optional[str] = None


@dataclass
class Choice:
    primary: Optional[str]
    secondaries: tuple = ()
    gather: bool = False
    protectee: Optional[str] = None
    withdraw: bool = False
    slot_dirs: tuple = ()
    weapons_first: bool = False
    slot_all: bool = False


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
        others = [m for m in ctx.members if m.name != ctx.anchor.name
                  and m.name not in ctx.slot_holders
                  and m.name != ctx.reserve]
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
        # threatened() only returns a protectee with an attacker in reach.
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


def swarm_choice(ctx: Context) -> Choice:
    """What the higher-scoring swarm decision would choose (tie: weakest),
    without stickiness."""
    weakest, cmdr = SwarmWeakest(), SwarmCommander()
    if cmdr.score(ctx) > weakest.score(ctx):
        return cmdr.choose(ctx)
    return weakest.choose(ctx)


def _primary_view(ctx):
    """(swarm choice, the primary's view in ctx.enemies or None)."""
    choice = swarm_choice(ctx)
    if choice.primary is None:
        return choice, None
    for e in ctx.enemies:
        if e.name == choice.primary:
            return choice, e
    return choice, None


class FocusFace:
    name = "focus_face"

    def _target(self, ctx):
        choice, p = _primary_view(ctx)
        if p is None or len(p.faces) != 6:
            return choice, None
        if p not in _in_reach(ctx):
            return choice, None
        return choice, p

    def score(self, ctx: Context) -> float:
        _, p = self._target(ctx)
        if p is None or ctx.slot_eligible < 2:
            return 0.0
        face, value = attack.weakest_face(p.faces)
        limit = dials.get("face_weak")
        if ctx.current == self.name:
            limit += 0.2
        if not value < limit:
            return 0.0
        others = (sum(p.faces) - value) / 5.0
        return 1.2 if others >= 0.6 else 0.0

    def choose(self, ctx: Context) -> Choice:
        choice, p = self._target(ctx)
        if p is None:
            return choice
        n = min(int(dials.get("attack_slots")), ctx.slot_eligible)
        if n <= 0:
            return choice
        face, _ = attack.weakest_face(p.faces)
        return dataclasses.replace(choice,
                                   slot_dirs=attack.focus_dirs(face, n))


class Envelop:
    name = "envelop"

    def _target(self, ctx):
        choice, p = _primary_view(ctx)
        if p is None or len(p.faces) != 6 or p not in _in_reach(ctx):
            return choice, None
        return choice, p

    def score(self, ctx: Context) -> float:
        _, p = self._target(ctx)
        if p is None or ctx.slot_eligible < 3:
            return 0.0
        if min(p.faces) < dials.get("face_weak"):
            return 0.0
        return 1.05 if sum(p.faces) / 6.0 >= 0.5 else 0.0

    def choose(self, ctx: Context) -> Choice:
        choice, p = self._target(ctx)
        if p is None:
            return choice
        n = min(int(dials.get("attack_slots")), ctx.slot_eligible)
        if n <= 0:
            return choice
        return dataclasses.replace(choice, slot_dirs=attack.envelop_dirs(n))


def _disable_target(ctx):
    """The ship to disable, or None. A running disable is latched on its
    target (ctx.disable_target) while it is alive, in reach, not done and
    its weapons are up: the strength ratio is not re-checked, because
    stripping the shields alone halves it (final review I1). Otherwise the
    entry gate: the strongest not-done enemy in reach, weapons up, at least
    disable_threat x our strongest member."""
    reach = [e for e in _in_reach(ctx) if e.name not in ctx.disable_done]
    if ctx.current == "disable" and ctx.disable_target is not None:
        big = next((e for e in reach if e.name == ctx.disable_target), None)
        return None if big is None or big.weapons_down else big
    if not reach or not ctx.members:
        return None
    big = min(reach, key=lambda e: (-assess.strength(e), e.name))
    mine = max(assess.strength(m) for m in ctx.members)
    if big.weapons_down:
        return None
    if assess.strength(big) < dials.get("disable_threat") * mine:
        return None
    return big


class Disable:
    name = "disable"

    def score(self, ctx: Context) -> float:
        return 1.3 if _disable_target(ctx) is not None else 0.0

    def choose(self, ctx: Context) -> Choice:
        big = _disable_target(ctx)
        if big is None:
            return swarm_choice(ctx)
        rest = tuple(n for n in swarm_choice(ctx).secondaries
                     if n != big.name)
        # The five base envelop axes: the brain spreads them once over
        # every holder (slot_all); spreading an already-spread list put two
        # holders on one point.
        return Choice(big.name, rest,
                      slot_dirs=attack.envelop_dirs(len(attack.ENVELOP_ORDER)),
                      weapons_first=True, slot_all=True)


def _stock() -> list:
    return [Regroup(), SwarmWeakest(), SwarmCommander(), Protect(),
            Withdraw(), FocusFace(), Envelop(), Disable()]


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
    """Highest score wins. The current decision gets the stickiness bonus
    and wins ties, but only while it scores above 0: a decision whose own
    rule says stop (an ended Withdraw) must never win on stickiness."""
    bonus = dials.get("stickiness")
    best, best_score = None, None
    for d in _registry:
        s = d.score(ctx)
        sticky = d.name == ctx.current and s > 0.0
        if sticky:
            s += bonus
        if best is None or s > best_score or (s == best_score and sticky):
            best, best_score = d, s
    return best
