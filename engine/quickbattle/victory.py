"""Quick Battle victory settings: which way a battle is won, and its blanks.

Pure: no App. Never imports `scenario` at module level (`scenario` imports
this module); a scenario is used by duck type.

Spec: docs/superpowers/specs/2026-10-23-quickbattle-victory-conditions-design.md
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

_log = logging.getLogger(__name__)

ELIMINATION = "elimination"
KOBAYASHI_MARU = "kobayashi_maru"

NO_CANDIDATE_REASON = "Add a friendly or neutral ship first"
NO_ENEMY_PROBLEM = "Add an enemy ship to start"
FALLBACK_NOTICE = "Kobayashi Maru needs a ship to protect; switched to Elimination"

_ELIMINATION_RULE = "You win when every enemy is destroyed. You lose if you are."
_KM_RULE = ("You win when every enemy is destroyed. You lose if the ship you "
            "protect is destroyed, or you are.")
_KM_TIME_RULE = " You also lose if time runs out."


@dataclass(frozen=True)
class TypeInfo:
    id: str
    label: str
    description: str


TYPES = (
    TypeInfo(ELIMINATION, "Elimination", "Destroy every enemy to win."),
    TypeInfo(KOBAYASHI_MARU, "Kobayashi Maru",
             "Destroy every enemy and keep one ship alive"),
)
_IDS = tuple(t.id for t in TYPES)


@dataclass
class Victory:
    type: str = ELIMINATION
    protect: Optional[str] = None      # an Entry.id
    time_limit_min: int = 0            # 0 = no limit


def protect_candidates(scenario) -> list:
    """(Group, Entry) for every non-player entry of a friendly or neutral
    group, in group order then entry order."""
    return [(g, e) for g in scenario.groups
            if g.allegiance in ("friendly", "neutral")
            for e in g.entries if not e.player]


def unavailable_reason(scenario, type_id) -> Optional[str]:
    if type_id == KOBAYASHI_MARU and not protect_candidates(scenario):
        return NO_CANDIDATE_REASON
    return None


def start_problem(scenario) -> Optional[str]:
    """Why Start Battle is blocked, or None. Late (warp-in) enemy groups count."""
    if any(not e.player for g in scenario.groups if g.allegiance == "enemy"
           for e in g.entries):
        return None
    return NO_ENEMY_PROBLEM


def set_type(scenario, type_id) -> bool:
    if type_id not in _IDS or unavailable_reason(scenario, type_id) is not None:
        return False
    v = scenario.victory
    v.type = type_id
    if type_id == KOBAYASHI_MARU and v.protect not in _candidate_ids(scenario):
        v.protect = protect_candidates(scenario)[0][1].id
    return True


def set_protect(scenario, entry_id) -> bool:
    if entry_id not in _candidate_ids(scenario):
        return False
    scenario.victory.protect = entry_id
    return True


def set_time_limit(scenario, minutes) -> bool:
    if type(minutes) is not int or minutes < 0:
        return False
    scenario.victory.time_limit_min = minutes
    return True


def reconcile(scenario) -> Optional[str]:
    """Fall back to Elimination when Kobayashi Maru lost its ship to protect.
    Returns the notice to show, else None."""
    v = scenario.victory
    if v.type == KOBAYASHI_MARU and v.protect not in _candidate_ids(scenario):
        v.type, v.protect = ELIMINATION, None
        return FALLBACK_NOTICE
    return None


def rule_text(scenario) -> str:
    v = scenario.victory
    if v.type == KOBAYASHI_MARU:
        return _KM_RULE + (_KM_TIME_RULE if v.time_limit_min > 0 else "")
    return _ELIMINATION_RULE


def summary_suffix(scenario, title_of) -> str:
    v = scenario.victory
    if v.type != KOBAYASHI_MARU:
        return ""
    _g, e = scenario.find_entry(v.protect)
    if e is None:
        return ""
    return " · Kobayashi Maru · protect %s" % title_of(e)


def to_json(v: Victory) -> dict:
    return {"type": v.type, "protect": v.protect,
            "time_limit_min": v.time_limit_min}


def from_json(d) -> Victory:
    """Lenient: anything unreadable is the default Elimination."""
    if not isinstance(d, dict):
        return Victory()
    t = d.get("type", ELIMINATION)
    if t not in _IDS:
        _log.warning("quickbattle: unknown victory type %r; using Elimination", t)
        return Victory()
    protect, limit = d.get("protect"), d.get("time_limit_min", 0)
    if (protect is not None and not isinstance(protect, str)) \
            or type(limit) is not int or limit < 0:
        return Victory()
    return Victory(type=t, protect=protect, time_limit_min=limit)


def _candidate_ids(scenario) -> set:
    return {e.id for _g, e in protect_candidates(scenario)}
