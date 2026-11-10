"""Wing roster: Wing and Member records plus the module-level registry."""
from __future__ import annotations

import random
import zlib
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field


@dataclass
class Member:
    name: str
    is_player: bool = False
    in_chain_eligible: bool = True
    select_nodes: list = field(default_factory=list)
    # id(node) -> the node's fPopularityFactor as found, restored when the
    # wing goes leaderless; ai_root is the tree the nodes were found under.
    select_saved: dict = field(default_factory=dict)
    ai_root: object = None
    rejoin: bool = False
    desperate: str | None = None
    conditions: dict = field(default_factory=dict)
    ram_script: object = None
    strength_hist: list = field(default_factory=list)   # (t, strength)
    move_point: tuple | None = None
    guard: bool = False
    fallback_since: float | None = None
    # Phase C: (target_name, body_dir, standoff_gu) the member holds;
    # fire_script is the wing-owned stock FireScript of its attack branch.
    slot: tuple | None = None
    # WingMoveTo's hold mode on the slot (final review I3): entered within
    # 20 GU of it, left past 40; the brain clears it when the slot changes.
    slot_hold: bool = False
    fire_script: object = None
    # The smallest full-damage distance (GU) of its phaser and pulse banks,
    # None with none: cached at wrap (fixed per hardpoint), it sets the
    # member's slot standoff (attack.holder_standoff).
    beam_range_gu: float | None = None
    attack_target: str | None = None
    weapons_first: bool = False
    reserve: bool = False


@dataclass
class Wing:
    wing_id: str
    enemy_group: object
    target_group: object
    members: dict = field(default_factory=dict)
    chain: list = field(default_factory=list)
    commander: str | None = None
    leaderless: bool = False
    away: bool = False           # command alive but outside the home set
    decision: str | None = None
    primary: str | None = None
    km_priorities: Callable[[], dict] = field(default=lambda: {})
    phase_s: float = 0.0
    accum_s: float = 0.0
    rng: random.Random = field(default_factory=random.Random)
    armed_strength: float = 0.0
    protect_names: Callable[[], Iterable[str]] = field(default=lambda: ())
    withdraw_since: float | None = None
    withdraw_cooldown_until: float = -1.0
    clear_since: float | None = None
    # name -> time before which a timed-out faller may not fall back again
    # (rotate.fallback_flags owns the rule; one dict per wing across ticks).
    fallback_cooldown: dict = field(default_factory=dict)
    # Game time the current decision became current; the protectee the
    # last protect covered (decisions._protectee's dwell).
    decision_since: float = 0.0
    protect_prev: str | None = None
    # name -> "active" / "spent": each ship's one hull fall-back.
    fallback_hull: dict = field(default_factory=dict)
    # name -> (t, strength) samples for protectees that are not members
    # (protect ships, the player), so their damage rate is seen too.
    protect_hist: dict = field(default_factory=dict)
    # The protectee the current guards (Member.guard) cover: guard
    # incumbency holds only while it is unchanged (protect.pick_guards).
    guarded: str | None = None
    # (primary, holder names, weapons_first) last logged by the brain's
    # attack step: it logs only on a change.
    attack_sig: tuple | None = None
    # (primary, slot body dirs, {holder: slot index}) of the last attack
    # step: the incumbents attack.assign_slots keeps (final review I2).
    attack_prev: tuple | None = None
    # Phase C reserve (spec §6): the member held back, when it was picked,
    # whether the wing has already committed it (never re-picked), the live
    # non-player count last tick (a drop is a loss) and the last enemy
    # centroid in reach (the reserve point with nobody in reach).
    reserve: str | None = None
    reserve_since: float | None = None
    reserve_spent: bool = False
    reserve_live: int = 0
    last_centroid: tuple | None = None
    # Disable (final review I1): the target the running disable started on
    # and when; targets it never re-enters against (the disable_max_s cap,
    # or a disable that ended with the target still alive).
    disable_target: str | None = None
    disable_since: float | None = None
    disable_done: set = field(default_factory=set)


_wings: dict[str, Wing] = {}
_by_member: dict[str, Wing] = {}


def create_wing(wing_id, enemy_group, km_priorities=None) -> Wing:
    import App
    target_group = App.ObjectGroupWithInfo()
    for name in enemy_group.GetNameTuple():
        target_group[name] = {"Priority": 0.0}
    wing = Wing(
        wing_id=wing_id,
        enemy_group=enemy_group,
        target_group=target_group,
        km_priorities=km_priorities or (lambda: {}),
        rng=random.Random(zlib.crc32(wing_id.encode())),
    )
    _wings[wing_id] = wing
    return wing


def add_member(wing, name, *, is_player=False, chain_eligible=True) -> Member:
    existing = wing.members.get(name)
    if existing is not None:
        return existing
    m = Member(name=name, is_player=is_player, in_chain_eligible=chain_eligible)
    wing.members[name] = m
    _by_member[name] = wing
    return m


def wing_of(name) -> Wing | None:
    return _by_member.get(name)


def member(name) -> Member | None:
    w = _by_member.get(name)
    return w.members.get(name) if w else None


def wings() -> list[Wing]:
    return list(_wings.values())


def reset() -> None:
    _wings.clear()
    _by_member.clear()
