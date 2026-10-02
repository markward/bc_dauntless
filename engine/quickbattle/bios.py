"""Ship sheet bio text from Ships.tgl ('<name> Description'), with BC's
'Shield Rating' / 'Hull Rating' lines dropped: they don't match the game's
values (roadmap). Resolved at use; parsed TGL cached until reset()."""
from __future__ import annotations

import logging
from typing import Optional

_log = logging.getLogger(__name__)
_cache: dict = {}


def reset() -> None:
    _cache.clear()


def _strings() -> dict:
    if "strings" not in _cache:
        table = {}
        try:
            from engine import paths
            from engine.missions.tgl_reader import read_tgl
            tgl = read_tgl(paths.game_asset("data/TGL/Ships.tgl"))
            table = dict(tgl.strings)
        except Exception as e:
            _log.info("Ships.tgl unreadable: %s", e)
        _cache["strings"] = table
    return _cache["strings"]


def ship_bio(ce) -> Optional[str]:
    table = _strings()
    for key in (ce.raw_name, ce.title, ce.ship_id):
        text = table.get("%s Description" % key) if key else None
        if text:
            lines = [ln for ln in text.replace("\r", "\n").split("\n")
                     if not ln.strip().startswith(("Shield Rating", "Hull Rating"))]
            return "\n".join(lines).strip() or None
    return None
