"""StatusMap -- CharacterClass's owned keyed status store (tier-0 reference sec 4.6).

BC's status system is a hash keyed 0..5 (struct +0xd8), each key holding one
tooltip-row display string; SetStatus(value, key) with key>5 is a no-op, GetStatus
misses return 0, ClearStatus removes one key's row. Replaces SP1's single
_status["text"] collapse. The status/tooltip UI (m_pStatusUI, +0xd4) is a separate
render concern wired by the CEF CharacterTooltipPanel; this class is pure data.
"""
from __future__ import annotations


class StatusMap:
    MAX_KEY = 5

    def __init__(self, owner):
        self._owner = owner
        self._rows: dict[int, object] = {}
        self._dirty = True

    def set_status(self, value, key=0) -> None:
        k = int(key)
        if k < 0 or k > self.MAX_KEY:      # BC 0x00669D10: key>5 -> return
            return
        self._rows[k] = value
        self._dirty = True

    def get_status(self, key):
        return self._rows.get(int(key), 0)  # BC 0x00669CC0: miss -> 0

    def clear_status(self, key=None) -> None:
        if key is None:
            return
        k = int(key)
        if k in self._rows:                 # BC 0x00669F70: unlink + refresh
            del self._rows[k]
            self._dirty = True

    def rows(self) -> list:
        return [(k, self._rows[k]) for k in sorted(self._rows)]

    def is_dirty(self) -> bool:
        return self._dirty

    def clear_dirty(self) -> None:
        self._dirty = False
