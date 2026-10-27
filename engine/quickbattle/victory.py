"""Quick Battle victory and defeat conditions: two stacks the player adds to.

Each stack has a fixed default that is IMPLICIT and never stored (Victory:
every enemy destroyed; Defeat: the player destroyed). The player adds
conditions on top: Ships Destroyed (a list of ships, ANY or ALL) and Timer
(whole minutes, at most one per stack). Any one condition met settles its
stack; the battle-side evaluation lives in `battle_end`.

Pure: no App. Never imports `scenario` at module level (`scenario` imports
this module); a scenario is used by duck type.

Spec: docs/superpowers/specs/2026-10-27-quickbattle-victory-defeat-conditions-design.md
§3 (eligible ships, Start Battle, keeping conditions valid, presets), §4.1-4.2.
"""
from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass, field
from typing import Optional

_log = logging.getLogger(__name__)

VICTORY = "victory"
DEFEAT = "defeat"
SIDES = (VICTORY, DEFEAT)

SHIPS = "ships"
TIMER = "timer"
KINDS = (SHIPS, TIMER)

ANY = "any"
ALL = "all"
MODES = (ANY, ALL)

MIN_MINUTES = 1
MAX_MINUTES = 60
DEFAULT_MINUTES = 5

NO_ENEMY_PROBLEM = "Add an enemy ship to start"
EMPTY_SHIPS_PROBLEM = "A Ships Destroyed condition has no ships"

# Which group allegiances each stack may name (spec §3). The player entry is
# never eligible on either side.
_ELIGIBLE_ALLEGIANCES = {VICTORY: ("enemy",), DEFEAT: ("friendly", "neutral")}

# Phase 1 battle-type ids, read only to convert old presets.
_P1_ELIMINATION = "elimination"
_P1_KOBAYASHI_MARU = "kobayashi_maru"


@dataclass
class Condition:
    id: str
    side: str                # VICTORY / DEFEAT
    kind: str                # SHIPS / TIMER
    mode: str = ANY          # Ships only; a Timer keeps ANY
    ships: list = field(default_factory=list)   # Entry ids; Ships only
    minutes: int = DEFAULT_MINUTES              # Timer only


@dataclass
class Victory:
    """The ADDED conditions of both stacks, in the order they were added.
    The two defaults are implicit and never stored."""
    conditions: list = field(default_factory=list)


# ── queries ─────────────────────────────────────────────────────────────────

def eligible(scenario, side) -> list:
    """(Group, Entry) of every ship `side`'s stack may name, group order then
    entry order. Victory: enemy groups. Defeat: friendly and neutral groups.
    Never the player. Late (warp-in) groups count."""
    allowed = _ELIGIBLE_ALLEGIANCES.get(side, ())
    return [(g, e) for g in scenario.groups if g.allegiance in allowed
            for e in g.entries if not e.player]


def conditions(scenario, side) -> list:
    return [c for c in scenario.victory.conditions if c.side == side]


def find(scenario, cid) -> Optional[Condition]:
    return next((c for c in scenario.victory.conditions if c.id == cid), None)


def has_timer(scenario, side) -> bool:
    return any(c.kind == TIMER for c in conditions(scenario, side))


def start_problem(scenario) -> Optional[str]:
    """Why Start Battle is blocked, or None. Late (warp-in) enemy groups count
    as enemies. An empty Ships Destroyed list blocks Start (spec §3)."""
    if not any(not e.player for g in scenario.groups if g.allegiance == "enemy"
               for e in g.entries):
        return NO_ENEMY_PROBLEM
    if any(c.kind == SHIPS and not c.ships for c in scenario.victory.conditions):
        return EMPTY_SHIPS_PROBLEM
    return None


def summary_suffix(scenario) -> str:
    """The footer's condition counts, e.g. " · 1 victory · 2 defeat
    conditions"; "" when nothing is added (defaults are not counted)."""
    nv = len(conditions(scenario, VICTORY))
    nd = len(conditions(scenario, DEFEAT))
    if nv + nd == 0:
        return ""
    parts = [("%d victory" % nv) if nv else None,
             ("%d defeat" % nd) if nd else None]
    word = "condition" if nv + nd == 1 else "conditions"
    return " · " + " · ".join(p for p in parts if p) + " " + word


# ── verbs ───────────────────────────────────────────────────────────────────

def add_condition(scenario, side, kind) -> Optional[Condition]:
    """Append a new condition with its defaults (Ships: ANY, no ships; Timer:
    DEFAULT_MINUTES). None for a bad side/kind or a second Timer on a side."""
    if side not in SIDES or kind not in KINDS:
        return None
    if kind == TIMER and has_timer(scenario, side):
        return None
    c = Condition(id=_fresh_id({c.id for c in scenario.victory.conditions}),
                  side=side, kind=kind)
    scenario.victory.conditions.append(c)
    return c


def remove_condition(scenario, cid) -> bool:
    c = find(scenario, cid)
    if c is None:
        return False
    scenario.victory.conditions.remove(c)
    return True


def set_mode(scenario, cid, mode) -> bool:
    c = find(scenario, cid)
    if c is None or c.kind != SHIPS or mode not in MODES:
        return False
    c.mode = mode
    return True


def add_ship(scenario, cid, entry_id) -> bool:
    c = find(scenario, cid)
    if c is None or c.kind != SHIPS or entry_id in c.ships:
        return False
    if entry_id not in _eligible_ids(scenario, c.side):
        return False
    c.ships.append(entry_id)
    return True


def remove_ship(scenario, cid, entry_id) -> bool:
    c = find(scenario, cid)
    if c is None or c.kind != SHIPS or entry_id not in c.ships:
        return False
    c.ships.remove(entry_id)
    return True


def set_minutes(scenario, cid, minutes) -> bool:
    c = find(scenario, cid)
    if c is None or c.kind != TIMER or not _valid_minutes(minutes):
        return False
    c.minutes = minutes
    return True


def reconcile(scenario) -> None:
    """Drop every listed ship its condition's stack may no longer name (gone
    from the setup, or its group changed allegiance). Never removes a
    condition: an emptied list stays and blocks Start (spec §3)."""
    allowed = {side: _eligible_ids(scenario, side) for side in SIDES}
    for c in scenario.victory.conditions:
        if c.kind == SHIPS:
            c.ships[:] = [eid for eid in c.ships if eid in allowed[c.side]]


# ── JSON ────────────────────────────────────────────────────────────────────

def to_json(v: Victory) -> dict:
    return {"conditions": [{"id": c.id, "side": c.side, "kind": c.kind,
                            "mode": c.mode, "ships": list(c.ships),
                            "minutes": c.minutes} for c in v.conditions]}


def from_json(d) -> Victory:
    """Lenient. Absent or unreadable: no conditions. A dict with "type" is a
    phase 1 preset and converts (spec §3 Presets). Otherwise each malformed
    condition is dropped with a warning and the rest kept."""
    if not isinstance(d, dict):
        return Victory()
    if "type" in d:
        return _from_phase1(d)
    raw = d.get("conditions")
    if raw is None:
        return Victory()
    if not isinstance(raw, list):
        _log.warning("quickbattle: victory conditions are not a list; ignored")
        return Victory()
    out, ids = [], set()
    for cd in raw:
        c = _condition_from_json(cd, ids)
        if c is None:
            continue
        if c.kind == TIMER and any(o.kind == TIMER and o.side == c.side for o in out):
            _log.warning("quickbattle: second %s timer dropped", c.side)
            continue
        ids.add(c.id)
        out.append(c)
    return Victory(conditions=out)


def _condition_from_json(cd, taken) -> Optional[Condition]:
    def drop(why):
        _log.warning("quickbattle: victory condition dropped (%s): %r", why, cd)
        return None

    if not isinstance(cd, dict):
        return drop("not a dict")
    side, kind, mode = cd.get("side"), cd.get("kind"), cd.get("mode", ANY)
    if side not in SIDES:
        return drop("unknown side")
    if kind not in KINDS:
        return drop("unknown kind")
    if mode not in MODES:
        return drop("unknown mode")
    cid = cd.get("id")
    if not isinstance(cid, str) or not cid or cid in taken:
        cid = _fresh_id(taken)
    if kind == SHIPS:
        ships = cd.get("ships", [])
        if not isinstance(ships, list) or not all(isinstance(x, str) for x in ships):
            return drop("ships not a list of ids")
        unique = list(dict.fromkeys(ships))
        return Condition(id=cid, side=side, kind=SHIPS, mode=mode, ships=unique)
    minutes = cd.get("minutes")
    if not _valid_minutes(minutes):
        return drop("timer minutes not a whole number in %d..%d"
                    % (MIN_MINUTES, MAX_MINUTES))
    return Condition(id=cid, side=side, kind=TIMER, minutes=minutes)


def _from_phase1(d) -> Victory:
    """Phase 1's battle types: Elimination -> nothing added; Kobayashi Maru ->
    a Defeat Ships Destroyed (ANY) holding the protected ship, plus a Defeat
    Timer when it had a time limit (clamped into MIN..MAX)."""
    t = d.get("type")
    if t != _P1_KOBAYASHI_MARU:
        if t != _P1_ELIMINATION:
            _log.warning("quickbattle: unknown phase 1 victory type %r; "
                         "no conditions", t)
        return Victory()
    out = []
    protect = d.get("protect")
    if isinstance(protect, str) and protect:
        out.append(Condition(id=_fresh_id(set()), side=DEFEAT, kind=SHIPS,
                             ships=[protect]))
    else:
        _log.warning("quickbattle: phase 1 Kobayashi Maru without a ship to "
                     "protect; no Ships Destroyed condition")
    limit = d.get("time_limit_min", 0)
    if type(limit) is int and limit > 0:
        out.append(Condition(id=_fresh_id({c.id for c in out}), side=DEFEAT,
                             kind=TIMER,
                             minutes=min(max(limit, MIN_MINUTES), MAX_MINUTES)))
    return Victory(conditions=out)


# ── helpers ─────────────────────────────────────────────────────────────────

def _valid_minutes(m) -> bool:
    return type(m) is int and MIN_MINUTES <= m <= MAX_MINUTES


def _eligible_ids(scenario, side) -> set:
    return {e.id for _g, e in eligible(scenario, side)}


def _fresh_id(taken) -> str:
    while True:
        cid = secrets.token_hex(4)
        if cid not in taken:
            return cid
