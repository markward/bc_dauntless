"""The Quick Battle scenario: groups of ships, the player, placements.

Pure: no App, no catalog, no files. Invariants live HERE, not in the UI:
exactly one player group holding exactly one player entry; the player group is
always friendly with no direction/distance; the player entry never moves or
goes. Every enum is a string id so saved presets survive reordering.

Spec: docs/superpowers/specs/2026-10-02-quickbattle-setup-screen-design.md §2
"""
from __future__ import annotations

import logging
import os
import secrets
from dataclasses import dataclass, field
from typing import Optional

_log = logging.getLogger(__name__)

ALLEGIANCES = ("friendly", "enemy", "neutral")
DIRECTIONS = ("fore", "aft", "port", "starboard", "dorsal", "ventral")
DISTANCE_IDS = ("close", "standard", "long", "out_of_range")
DISTANCE_KM = {"close": 20.0, "standard": 35.0, "long": 80.0, "out_of_range": 150.0}
DIFFICULTY_LEVEL = {"low": 0.0, "medium": 0.5, "high": 1.0}
DEFAULT_PLAYER_SHIP = "Galaxy"

_ALLEGIANCE_LABEL = {"friendly": "Friendly", "enemy": "Enemy", "neutral": "Neutral"}


def new_id() -> str:
    return secrets.token_hex(4)


@dataclass
class Entry:
    id: str
    ship: str                      # CatalogEntry.ship_id (the class)
    variant: Optional[str] = None  # Variant.name; None = class default
    player: bool = False


@dataclass
class Group:
    id: str
    name: str
    allegiance: str
    direction: Optional[str]
    distance: Optional[str]
    difficulty: str = "medium"
    player: bool = False
    custom_name: bool = False
    entries: list = field(default_factory=list)


@dataclass
class Scenario:
    groups: list

    # ── lookup ──────────────────────────────────────────────────────────
    def group(self, gid) -> Optional[Group]:
        for g in self.groups:
            if g.id == gid:
                return g
        return None

    def find_entry(self, eid):
        for g in self.groups:
            for e in g.entries:
                if e.id == eid:
                    return g, e
        return None, None

    def player_group(self) -> Group:
        return next(g for g in self.groups if g.player)

    def player_entry(self) -> Entry:
        return next(e for e in self.player_group().entries if e.player)

    def first_non_player_group(self) -> Optional[Group]:
        return next((g for g in self.groups if not g.player), None)

    def can_start(self) -> bool:
        return any(not e.player for g in self.groups for e in g.entries)

    # ── naming ──────────────────────────────────────────────────────────
    def auto_name(self, allegiance: str, exclude_gid=None) -> str:
        base = _ALLEGIANCE_LABEL[allegiance] + " group"
        taken = {g.name for g in self.groups if g.id != exclude_gid}
        if base not in taken:
            return base
        n = 2
        while "%s %d" % (base, n) in taken:
            n += 1
        return "%s %d" % (base, n)

    # ── group edits ─────────────────────────────────────────────────────
    def add_group(self) -> Group:
        g = Group(id=new_id(), name=self.auto_name("enemy"), allegiance="enemy",
                  direction="fore", distance="standard")
        self.groups.append(g)
        return g

    def delete_group(self, gid) -> bool:
        g = self.group(gid)
        if g is None or g.player:
            return False
        self.groups.remove(g)
        return True

    def rename_group(self, gid, name) -> bool:
        g = self.group(gid)
        name = (name or "").strip()
        if g is None or not name or name == g.name:
            return False
        g.name, g.custom_name = name, True
        return True

    def update_details(self, gid, allegiance, direction, distance, difficulty) -> bool:
        g = self.group(gid)
        if g is None or difficulty not in DIFFICULTY_LEVEL:
            return False
        if g.player:
            g.difficulty = difficulty
            return True
        if (allegiance not in ALLEGIANCES or direction not in DIRECTIONS
                or distance not in DISTANCE_IDS):
            return False
        changed = allegiance != g.allegiance
        g.allegiance, g.direction, g.distance, g.difficulty = \
            allegiance, direction, distance, difficulty
        if changed and not g.custom_name:
            g.name = self.auto_name(allegiance, exclude_gid=g.id)
        return True

    # ── entry edits ─────────────────────────────────────────────────────
    def add_ship(self, gid, ship) -> Optional[Entry]:
        g = self.group(gid)
        if g is None or not ship:
            return None
        e = Entry(id=new_id(), ship=ship)
        g.entries.append(e)
        return e

    def remove_entry(self, eid) -> bool:
        g, e = self.find_entry(eid)
        if e is None or e.player:
            return False
        g.entries.remove(e)
        return True

    def move_entry(self, eid, gid) -> bool:
        g, e = self.find_entry(eid)
        dest = self.group(gid)
        if e is None or e.player or dest is None or dest is g:
            return False
        g.entries.remove(e)
        dest.entries.append(e)
        return True

    def set_variant(self, eid, variant) -> bool:
        _g, e = self.find_entry(eid)
        if e is None:
            return False
        e.variant = variant or None
        return True

    def set_player_ship(self, ship) -> None:
        pe = self.player_entry()
        pe.ship, pe.variant = ship, None

    # ── JSON ────────────────────────────────────────────────────────────
    def to_json(self) -> dict:
        return {"groups": [{
            "id": g.id, "name": g.name, "custom_name": g.custom_name,
            "player": g.player, "allegiance": g.allegiance,
            "direction": g.direction, "distance": g.distance,
            "difficulty": g.difficulty,
            "entries": [{"id": e.id, "ship": e.ship, "variant": e.variant,
                         "player": e.player} for e in g.entries],
        } for g in self.groups]}


def default_scenario() -> Scenario:
    player = Group(id=new_id(), name="Friendly group", allegiance="friendly",
                   direction=None, distance=None, player=True,
                   entries=[Entry(id=new_id(), ship=DEFAULT_PLAYER_SHIP, player=True)])
    enemy = Group(id=new_id(), name="Enemy group", allegiance="enemy",
                  direction="fore", distance="standard")
    return Scenario(groups=[player, enemy])


def _req(cond, why):
    if not cond:
        raise ValueError(why)


def from_json(d) -> Scenario:
    """Parse and validate. Raises ValueError on any shape or invariant break."""
    _req(isinstance(d, dict) and isinstance(d.get("groups"), list), "no groups")
    groups = []
    for gd in d["groups"]:
        _req(isinstance(gd, dict), "group not a dict")
        player = bool(gd.get("player"))
        allegiance = gd.get("allegiance")
        _req(allegiance in ALLEGIANCES, "bad allegiance")
        _req(gd.get("difficulty", "medium") in DIFFICULTY_LEVEL, "bad difficulty")
        if player:
            _req(allegiance == "friendly", "player group not friendly")
            direction = distance = None
        else:
            direction, distance = gd.get("direction"), gd.get("distance")
            _req(direction in DIRECTIONS and distance in DISTANCE_IDS, "bad placement")
        name = gd.get("name")
        _req(isinstance(name, str) and name.strip(), "bad name")
        entries = []
        for ed in gd.get("entries") or []:
            _req(isinstance(ed, dict) and isinstance(ed.get("ship"), str)
                 and ed["ship"], "bad entry")
            variant = ed.get("variant")
            _req(variant is None or isinstance(variant, str), "bad variant")
            entries.append(Entry(id=str(ed.get("id") or new_id()), ship=ed["ship"],
                                 variant=variant or None, player=bool(ed.get("player"))))
        groups.append(Group(id=str(gd.get("id") or new_id()), name=name.strip(),
                            allegiance=allegiance, direction=direction,
                            distance=distance, difficulty=gd.get("difficulty", "medium"),
                            player=player, custom_name=bool(gd.get("custom_name")),
                            entries=entries))
    pgs = [g for g in groups if g.player]
    _req(len(pgs) == 1, "need exactly one player group")
    pes = [e for g in groups for e in g.entries if e.player]
    _req(len(pes) == 1 and pes[0] in pgs[0].entries, "need exactly one player entry")
    return Scenario(groups=groups)


def _strip_ids(s: Scenario) -> list:
    out = []
    for g in s.to_json()["groups"]:
        g = dict(g)
        g.pop("id")
        g["entries"] = [{k: v for k, v in e.items() if k != "id"} for e in g["entries"]]
        out.append(g)
    return out


def same_setup(a: Scenario, b: Scenario) -> bool:
    return _strip_ids(a) == _strip_ids(b)


# ── Catalog-aware: reconciliation and the battle plan (spec §2, §4.6) ──────

def catalog_index(entries) -> dict:
    return {e.ship_id.lower(): e for e in entries}


def _lookup(index, ship_id):
    return index.get((ship_id or "").lower())


def resolve_variant(ce, name):
    if not ce.variants:
        return None
    if name is None:
        return ce.variants[0]
    return next((v for v in ce.variants if v.name == name), None)


def can_be_player(ce, variant_name) -> bool:
    v = resolve_variant(ce, variant_name)
    if v is not None and v.playable is not None:
        return bool(v.playable)
    return bool(ce.playable)


def reconcile(scenario: "Scenario", index) -> list:
    msgs = []
    pe = scenario.player_entry()
    ce = _lookup(index, pe.ship)
    if ce is None or not can_be_player(ce, pe.variant):
        msgs.append("player ship %r unavailable; using %s" % (pe.ship, DEFAULT_PLAYER_SHIP))
        pe.ship, pe.variant = DEFAULT_PLAYER_SHIP, None
    for g in scenario.groups:
        for e in list(g.entries):
            ce = _lookup(index, e.ship)
            if ce is None:
                msgs.append("ship %r is no longer installed; removed from %r" % (e.ship, g.name))
                g.entries.remove(e)
                continue
            e.ship = ce.ship_id
            if e.variant is not None and resolve_variant(ce, e.variant) is None:
                msgs.append("named ship %r not found on %s; using class default"
                            % (e.variant, ce.ship_id))
                e.variant = None
    for m in msgs:
        _log.warning("quickbattle: %s", m)
    return msgs


@dataclass(frozen=True)
class PlayerOrder:
    ship_file: str
    class_id: str
    registry: Optional[str]
    display_name: Optional[str]


@dataclass(frozen=True)
class SpawnOrder:
    group_id: str
    entry_id: str
    ship_file: str
    class_id: str
    title: str
    registry: Optional[str]
    display_name: Optional[str]
    allegiance: str
    direction: Optional[str]
    distance_gu: Optional[float]
    ai_level: float


@dataclass(frozen=True)
class BattlePlan:
    player: PlayerOrder
    orders: tuple


def _bc_default_stem(class_id):
    from engine.appc.registry_texture import DEFAULT_REGISTRY_BY_CLASS
    rel = DEFAULT_REGISTRY_BY_CLASS.get(class_id)
    return os.path.splitext(os.path.basename(rel))[0] if rel else None


def _resolve(ce, variant_name):
    """(ship_file, registry_stem, display_name_before_ordinals) for one row."""
    v = resolve_variant(ce, variant_name)
    if v is not None and v.script:
        return v.script, v.registry, v.name
    if v is None or v is ce.variants[0]:
        reg = (v.registry if v is not None else None) or _bc_default_stem(ce.ship_id)
        return ce.ship_id, reg, (v.name if v is not None else None)
    return ce.ship_id, v.registry, v.name


def battle_plan(scenario: "Scenario", index) -> BattlePlan:
    from engine.quickbattle import naming
    from engine.units import GU_TO_KM

    pe = scenario.player_entry()
    pce = _lookup(index, pe.ship)
    p_file, p_reg, p_name = _resolve(pce, pe.variant)
    rows = []
    for g in scenario.groups:
        for e in g.entries:
            if e.player:
                continue
            ce = _lookup(index, e.ship)
            if ce is None:
                continue
            rows.append((g, e, ce) + _resolve(ce, e.variant))
    names = naming.with_ordinals([p_name] + [r[5] for r in rows])
    orders = []
    for (g, e, ce, f, reg, _n), disp in zip(rows, names[1:]):
        orders.append(SpawnOrder(
            group_id=g.id, entry_id=e.id, ship_file=f, class_id=ce.ship_id,
            title=ce.title or ce.ship_id, registry=reg, display_name=disp,
            allegiance=g.allegiance, direction=g.direction,
            distance_gu=(DISTANCE_KM[g.distance] / GU_TO_KM) if g.distance else None,
            ai_level=DIFFICULTY_LEVEL[g.difficulty]))
    return BattlePlan(player=PlayerOrder(p_file, pce.ship_id, p_reg, names[0]),
                      orders=tuple(orders))
