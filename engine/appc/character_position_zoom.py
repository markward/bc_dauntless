"""PositionZoomTable -- CharacterClass's owned per-station zoom table
(tier-0 reference sec 4.4, struct +0xa8/+0xac, 0x18-byte records).

Each record is (station-name, zoom value, look-at/zoom-target name). BC appends
only if the name is not already present, and GetPositionZoom does a linear search
returning the value or a default sentinel. The bridge camera native-reads this
(no SDK Python caller) to zoom to an officer's station on focus; SP4 wires that
via the MenuUp zoom hook (Task 8).
"""
from __future__ import annotations

# BC returns *0x00888EB4 (a float const) on a GetPositionZoom miss. Its exact
# value was not recoverable from the tier-0/constants sources; 1.0 == "no focus
# zoom" (captain FOV factor) is the documented, behaviourally-safe fallback: a
# miss means "this station has no authored zoom", which the camera treats as no
# zoom. See spec sec 4.1.
POSITION_ZOOM_SENTINEL = 1.0


class PositionZoomTable:
    def __init__(self):
        self._records: list = []   # list[tuple[str, float, str|None]]

    def add_position_zoom(self, name, value, zoom_name="") -> None:
        n = str(name)
        for rn, _v, _la in self._records:
            if rn == n:                        # BC 0x0066C530: append if absent
                return
        self._records.append((n, float(value), str(zoom_name) if zoom_name else None))

    def get_position_zoom(self, name) -> float:
        n = str(name)
        for rn, val, _la in self._records:     # BC 0x0066C690: linear search
            if rn == n:
                return val
        return POSITION_ZOOM_SENTINEL

    def get_position_look_at_name(self, name):
        n = str(name)
        for rn, _val, la in self._records:     # BC 0x0066C720
            if rn == n:
                return la
        return None
