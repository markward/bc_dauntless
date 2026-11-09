"""Wing decision registry and the Phase A decisions (spec §8). Pure."""
import copy
import dataclasses
import math
from dataclasses import dataclass, field
from typing import Optional, Protocol

from engine.wings import allies as _allies
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
    # Seconds the current decision has been current (0 with none), and the
    # protectee a running protect covers: protect holds protect_min_s on
    # it, and a young attack decision is not cut off by attacker count.
    decision_age_s: float = 0.0
    protect_prev: Optional[str] = None
    # Ordinary wing members: protect.threatened's real-danger rule.
    strict_protectees: frozenset = frozenset()
    # Phase D: the WingStatus of the other wings on this wing's side.
    allies: tuple = ()
    # Phase D latches and cooldowns, filled by the brain: the ally a running
    # reinforce is helping and the allies on reinforce cooldown; the ally a
    # running feint is luring toward, whether the feint cooldown is over,
    # and how long no enemy has been within engage_gu of our anchor while
    # feinting; how long the current decision has been current.
    reinforce_ally: Optional[str] = None
    reinforce_done: frozenset = frozenset()
    feint_ally: Optional[str] = None
    feint_ready: bool = True
    feint_quiet_s: float = 0.0
    decision_age_s: float = 0.0


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
    # Phase D: far keeps the primary and secondaries beyond leash
    # (reinforce); a hold point and its kind ("screen" | "flank" | "feint")
    # for the hold branch; the ally the decision is about.
    far: bool = False
    hold_point: Optional[tuple] = None
    hold_kind: Optional[str] = None
    ally: Optional[str] = None


class Decision(Protocol):
    name: str

    def score(self, ctx: Context) -> float: ...

    def choose(self, ctx: Context) -> Choice: ...


def _memo(ctx, kind, inputs, compute):
    """compute() once per context while `inputs` are unchanged (the same
    objects, the same dial values): every decision's score and the winner's
    choose read the same reach, side strengths and swarm choice in one tick.
    Kept off the dataclass fields, so a dataclasses.replace() copy starts
    empty and repr / == are unchanged."""
    memo = ctx.__dict__.setdefault("_memo", {})
    hit = memo.get(kind)
    # Tuple == tests each pair by identity first: the context's lists and
    # anchor match by identity, the dial floats by value.
    if hit is not None and hit[0] == inputs:
        return hit[1]
    value = compute()
    memo[kind] = (inputs, value)
    return value


def _in_reach(ctx):
    leash = dials.get("leash_gu")
    return list(_memo(
        ctx, "reach", (ctx.enemies, ctx.anchor, leash),
        lambda: [e for e in ctx.enemies
                 if assess.dist(e.pos, ctx.anchor.pos) <= leash]))


def _near(ctx):
    """Enemies within engage_gu of the anchor (we are engaged when any)."""
    engage = dials.get("engage_gu")
    return list(_memo(
        ctx, "near", (ctx.enemies, ctx.anchor, engage),
        lambda: [e for e in ctx.enemies
                 if assess.dist(e.pos, ctx.anchor.pos) <= engage]))


def _sides(ctx, engage):
    """(our, their) strength within `engage` of the anchor."""
    return _memo(
        ctx, "sides", (ctx.members, ctx.enemies, ctx.anchor, engage),
        lambda: (assess.side_strength(ctx.members, ctx.anchor.pos, engage),
                 assess.side_strength(ctx.enemies, ctx.anchor.pos, engage)))


def _outmatched(ctx) -> bool:
    ours, theirs = _sides(ctx, dials.get("engage_gu"))
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


_ATTACKS = frozenset({"focus_face", "envelop", "disable"})


def _protectee(ctx):
    """The protectee protect covers this tick, or None.

    Fresh: protect.threatened (heavy fire: heavy_fire_frac lost in the
    window, or heavy_fire_attackers on it). A young attack decision
    (focus_face, envelop, disable; under attack_min_s) is cut off only by
    real damage, never by the attacker count alone. Dwell: a protect under
    protect_min_s keeps its protectee while it lives and has an attacker in
    reach. Mark's C play test (2026-11-10): the attacker count came and
    went, protect and focus_face swapped every few seconds, and each swap
    ended the flank slots before they formed."""
    hit = protect.threatened(ctx.protectees, ctx.rates, ctx.enemies,
                             ctx.anchor, ctx.strict_protectees)
    if (hit is not None and ctx.current in _ATTACKS
            and ctx.decision_age_s < dials.get("attack_min_s")
            and ctx.rates.get(hit.name, 0.0) < dials.get("heavy_fire_frac")):
        hit = None
    if hit is not None:
        return hit
    if (ctx.current == "protect" and ctx.protect_prev is not None
            and ctx.decision_age_s < dials.get("protect_min_s")):
        p = next((p for p in ctx.protectees if p.name == ctx.protect_prev),
                 None)
        if p is not None and protect.attackers_of(
                p.name, ctx.enemies, ctx.anchor.pos, dials.get("engage_gu")):
            return p
    return None


class Protect:
    name = "protect"

    def score(self, ctx: Context) -> float:
        return 1.5 if _protectee(ctx) is not None else 0.0

    def choose(self, ctx: Context) -> Choice:
        p = _protectee(ctx)
        if p is None:
            return Choice(None, ())
        atk = sorted(protect.attackers_of(p.name, ctx.enemies, ctx.anchor.pos,
                                          dials.get("engage_gu")),
                     key=lambda e: (assess.dist(e.pos, p.pos), e.name))
        # _protectee() only returns a protectee with an attacker in reach.
        return Choice(atk[0].name, tuple(e.name for e in atk[1:3]),
                      protectee=p.name)


class Withdraw:
    name = "withdraw"

    def score(self, ctx: Context) -> float:
        odds = dials.get("withdraw_odds")
        ours, theirs = _sides(ctx, dials.get("engage_gu"))
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
    without stickiness. Made once per context (a copy each call: a caller
    may replace fields on what it gets)."""
    def compute():
        weakest, cmdr = SwarmWeakest(), SwarmCommander()
        if cmdr.score(ctx) > weakest.score(ctx):
            return cmdr.choose(ctx)
        return weakest.choose(ctx)
    inputs = (ctx.members, ctx.enemies, ctx.anchor, dials.get("leash_gu"),
              dials.get("engage_gu"), dials.get("odds_ratio"))
    return copy.copy(_memo(ctx, "swarm", inputs, compute))


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


# --- Phase D: wings working together (spec 2026-11-09 phase D §4-§6) ------

def _strength_frac(ctx) -> float:
    """Our live strength / armed strength, as the published status."""
    armed = ctx.armed_strength
    if not armed:
        return 0.0
    return sum(assess.strength(m) for m in ctx.members) / armed


def _ally(ctx, wing_id):
    return next((a for a in ctx.allies if a.wing_id == wing_id), None)


def _to(ctx, a) -> float:
    return assess.dist(a.anchor, ctx.anchor.pos)


def _odds(a) -> float:
    return a.ours / a.theirs if a.theirs > 0 else math.inf


def _reinforce_ally(ctx):
    """The ally to reinforce, or None. Latched (a current reinforce on
    ctx.reinforce_ally): only the end conditions -- arrival within leash of
    its anchor, it no longer in trouble or gone, the reinforce_max_s cap.
    Otherwise the entry gate: we are not engaged or can spare the help, and
    the in-trouble ally within reinforce_range_gu with the worst odds
    (ties: nearest), skipping allies on cooldown."""
    leash = dials.get("leash_gu")
    if ctx.current == "reinforce" and ctx.reinforce_ally is not None:
        a = _ally(ctx, ctx.reinforce_ally)
        if (a is None or not _allies.in_trouble(a) or _to(ctx, a) <= leash
                or ctx.decision_age_s >= dials.get("reinforce_max_s")):
            return None
        return a
    if _near(ctx):
        ours, theirs = _sides(ctx, dials.get("engage_gu"))
        if not ours >= dials.get("reinforce_spare_odds") * theirs:
            return None
    reach = dials.get("reinforce_range_gu")
    cands = [a for a in ctx.allies
             if a.wing_id not in ctx.reinforce_done and _allies.in_trouble(a)
             and leash < _to(ctx, a) <= reach]
    if not cands:
        return None
    return min(cands, key=lambda a: (_odds(a), _to(ctx, a), a.wing_id))


class Reinforce:
    name = "reinforce"

    def score(self, ctx: Context) -> float:
        return 1.25 if _reinforce_ally(ctx) is not None else 0.0

    def choose(self, ctx: Context) -> Choice:
        a = _reinforce_ally(ctx)
        if a is None:
            return swarm_choice(ctx)
        engage = dials.get("engage_gu")
        theirs = sorted(
            (e for e in ctx.enemies if assess.dist(e.pos, a.anchor) <= engage),
            key=lambda e: (assess.dist(e.pos, a.anchor), e.name))
        if not theirs:
            return Choice(None, (), far=True, ally=a.wing_id)
        return Choice(theirs[0].name, tuple(e.name for e in theirs[1:3]),
                      far=True, ally=a.wing_id)


def _feint_ally(ctx):
    """The ally F to lure toward, or None. Latched (a current feint on
    ctx.feint_ally): only the §6 ends -- we are within feint_stop_gu + 50
    of F, F is engaged (the trap is sprung, or F is busy elsewhere) or gone,
    no enemy near us for 10 s, the feint_max_s cap. Otherwise the entry
    gate: we are engaged at strength_frac >= 0.5, the cooldown is over,
    and the nearest F that is idle, at strength_frac >= 0.6, between
    engage_gu and feint_range_gu from us, with theirs <= (ours + F.ours) x
    feint_odds."""
    if ctx.current == "feint" and ctx.feint_ally is not None:
        f = _ally(ctx, ctx.feint_ally)
        if (f is None or f.engaged
                or _to(ctx, f) <= dials.get("feint_stop_gu") + 50.0
                or ctx.feint_quiet_s >= 10.0
                or ctx.decision_age_s >= dials.get("feint_max_s")):
            return None
        return f
    if not ctx.feint_ready or not _near(ctx) or _strength_frac(ctx) < 0.5:
        return None
    engage = dials.get("engage_gu")
    ours, theirs = _sides(ctx, engage)
    lo, hi = engage, dials.get("feint_range_gu")
    odds = dials.get("feint_odds")
    cands = [f for f in ctx.allies
             if not f.engaged and f.strength_frac >= 0.6
             and lo < _to(ctx, f) <= hi
             and theirs <= (ours + f.ours) * odds]
    if not cands:
        return None
    return min(cands, key=lambda f: (_to(ctx, f), f.wing_id))


class Feint:
    name = "feint"

    def score(self, ctx: Context) -> float:
        return 1.2 if _feint_ally(ctx) is not None else 0.0

    def choose(self, ctx: Context) -> Choice:
        f = _feint_ally(ctx)
        if f is None:
            return swarm_choice(ctx)
        return Choice(None, (), hold_kind="feint", ally=f.wing_id,
                      hold_point=_allies.lure_point(ctx.anchor.pos, f.anchor))


def _closing_centroid(ctx, a):
    """Centroid of the enemies within screen_watch_gu of ally a's anchor,
    or None. Memoised per ally: score and choose read the same one."""
    watch = dials.get("screen_watch_gu")
    return _memo(
        ctx, ("watch", a.wing_id), (ctx.enemies, a.anchor, watch),
        lambda: assess.centroid(
            e for e in ctx.enemies if assess.dist(e.pos, a.anchor) <= watch))


def _screen_target(ctx):
    """(ally, enemy centroid) to screen, or None. No latch: we are not
    engaged at strength_frac >= 0.6; the ally is weak (strength_frac < 0.5,
    or withdrawing); the enemies watched near it have not reached it (their
    centroid is beyond engage_gu). The weakest such ally, ties nearest."""
    if _near(ctx) or _strength_frac(ctx) < 0.6:
        return None
    engage = dials.get("engage_gu")
    best = None
    for a in ctx.allies:
        if not (a.strength_frac < 0.5 or a.decision == "withdraw"):
            continue
        c = _closing_centroid(ctx, a)
        if c is None or assess.dist(c, a.anchor) <= engage:
            continue
        key = (a.strength_frac, _to(ctx, a), a.wing_id)
        if best is None or key < best[0]:
            best = (key, a, c)
    return None if best is None else best[1:]


class Screen:
    name = "screen"

    def score(self, ctx: Context) -> float:
        return 1.15 if _screen_target(ctx) is not None else 0.0

    def choose(self, ctx: Context) -> Choice:
        hit = _screen_target(ctx)
        choice = swarm_choice(ctx)
        if hit is None:
            return choice
        a, c = hit
        return dataclasses.replace(
            choice, hold_point=_allies.screen_point(a.anchor, c),
            hold_kind="screen", ally=a.wing_id)


def _flank_target(ctx):
    """(ally, hold point) to flank, or None. Ends (checked latched or not):
    an enemy within engage_gu of our anchor, the ally not engaged or gone,
    our anchor within leash_gu of the hold point (recomputed from the
    ally's status every tick). Entry adds: the ally is not in trouble and
    within reinforce_range_gu; latched (a current flank) skips those two,
    so an ally slipping into trouble mid-swing does not flip us to
    reinforce. The nearest such ally."""
    if _near(ctx):
        return None
    latched = ctx.current == "flank"
    reach = dials.get("reinforce_range_gu")
    leash = dials.get("leash_gu")
    best = None
    for a in ctx.allies:
        if not a.engaged or a.enemy_centroid is None:
            continue
        if not latched and (_allies.in_trouble(a) or _to(ctx, a) > reach):
            continue
        p = _allies.flank_point(ctx.anchor.pos, a.anchor, a.enemy_centroid)
        if assess.dist(p, ctx.anchor.pos) <= leash:
            continue
        key = (_to(ctx, a), a.wing_id)
        if best is None or key < best[0]:
            best = (key, a, p)
    return None if best is None else best[1:]


class Flank:
    name = "flank"

    def score(self, ctx: Context) -> float:
        return 1.1 if _flank_target(ctx) is not None else 0.0

    def choose(self, ctx: Context) -> Choice:
        hit = _flank_target(ctx)
        choice = swarm_choice(ctx)
        if hit is None:
            return choice
        a, p = hit
        return dataclasses.replace(choice, hold_point=p, hold_kind="flank",
                                   ally=a.wing_id)


def _stock() -> list:
    return [Regroup(), SwarmWeakest(), SwarmCommander(), Protect(),
            Withdraw(), FocusFace(), Envelop(), Disable(), Reinforce(),
            Feint(), Screen(), Flank()]


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
