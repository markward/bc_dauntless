"""Player-facing star-system descriptions for the Set Course map.

Owns descriptions.json, which is HAND-AUTHORED — no tool writes it and nothing
regenerates it. That is the opposite of everything else in this package: the
maps beside it are generated from BC's own data and must never be hand-edited,
so the two are kept in separate files precisely so the distinction stays
obvious.

Keys are the system ids in engine/appc/sector_model.json, which is what the
star map selects by.

The path is computed per call rather than held in a module constant, matching
engine/systems/map.py — the parse is cached instead, so repeated lookups from
the panel's render path cost a dict hit.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


def descriptions_path() -> Path:
    """Where the hand-authored descriptions live. Computed per call."""
    return Path(__file__).with_name("descriptions.json")


@lru_cache(maxsize=1)
def _load() -> dict:
    try:
        raw = json.loads(descriptions_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # A missing or malformed file must not take the nav map down with it:
        # a system simply has no description, which the panel already handles.
        return {}
    return {k: v for k, v in raw.items()
            if not k.startswith("_") and isinstance(v, dict)}


def for_system(system_id):
    """`{"summary": str, "detail": str}` for a system id, or None.

    Returns None for an unknown id, and for an entry missing either field —
    a half-written description is a bug to notice, not something to render
    with a blank half.
    """
    if not system_id:
        return None
    entry = _load().get(str(system_id).lower())
    if not entry:
        return None
    summary, detail = entry.get("summary"), entry.get("detail")
    if not summary or not detail:
        return None
    return {"summary": summary, "detail": detail}


def available() -> list:
    """Every system id that has a usable description, sorted."""
    return sorted(k for k in _load() if for_system(k) is not None)
