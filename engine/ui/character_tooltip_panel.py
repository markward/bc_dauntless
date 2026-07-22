"""CharacterTooltipPanel -- the CEF crew tooltip box (BC's native status box,
built by Bridge.BridgeMenus.CreateCharacterTooltipBox). Renders the current
tooltip owner's StatusMap rows 0..5 as a top-centre .bc-panel. Visibility follows
CharacterClass_GetCurrentToolTipOwner: the host-loop owner-selection tick (Task 8)
sets the owner to the focused officer; this panel just reflects it.

Title comes from CharacterStatus.tgl keyed by GetCharacterName (headless/miss ->
the raw name). Rows come from StatusMap.rows() in ascending key order.
"""
from __future__ import annotations

import json
from typing import Optional

from engine.ui.panel import Panel
from engine.appc.characters import CharacterClass_GetCurrentToolTipOwner


class CharacterTooltipPanel(Panel):
    def __init__(self):
        super().__init__()
        self._last_pushed: Optional[str] = None

    @property
    def name(self) -> str:
        return "character-tooltip"

    def _title_for(self, owner) -> str:
        raw = owner.GetCharacterName()
        try:
            import App
            db = App.g_kLocalizationManager.Load("data/TGL/CharacterStatus.tgl")
            try:
                s = str(db.GetString(raw))
                return s or raw
            finally:
                App.g_kLocalizationManager.Unload(db)
        except Exception:
            return raw

    def snapshot(self) -> dict:
        owner = CharacterClass_GetCurrentToolTipOwner()
        if owner is None:
            return {"visible": False, "title": "", "rows": []}
        rows = [str(v) for _k, v in owner._status_map.rows()]
        if not rows:
            return {"visible": False, "title": "", "rows": []}
        return {"visible": True, "title": self._title_for(owner), "rows": rows}

    def render_payload(self) -> Optional[str]:
        payload = json.dumps(self.snapshot())
        if payload == self._last_pushed:
            return None
        self._last_pushed = payload
        return "setCharacterTooltip(" + payload + ");"

    def dispatch_event(self, action: str) -> bool:
        return False        # display-only; no interaction

    def invalidate(self) -> None:
        self._last_pushed = None
