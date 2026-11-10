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
    # name -> "active" / "spent": each ship's one hull fall-back.
    fallback_hull: dict = field(default_factory=dict)
    # name -> (t, strength) samples for protectees that are not members
    # (protect ships, the player), so their damage rate is seen too.
    protect_hist: dict = field(default_factory=dict)
    # The protectee the current guards (Member.guard) cover: guard
    # incumbency holds only while it is unchanged (protect.pick_guards).
    guarded: str | None = None


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
