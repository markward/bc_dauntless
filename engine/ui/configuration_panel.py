"""Configuration panel — pause-menu modal with tabbed settings.

Subclasses engine.ui.panel.Panel; pumped by PanelRegistry like the
mission picker. Owns a SettingsSnapshot and five injected appliers
(dust, specular, hdr, rim, fov). Every state mutation immediately fires
the matching applier — there is no Apply/Cancel; closing the panel does
not revert. Settings are not persisted across launches.

Spec: docs/superpowers/specs/2026-06-05-configuration-panel-design.md
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from engine.ui.panel import Panel


FOV_MIN  = 40
FOV_MAX  = 80
FOV_STEP = 5


@dataclass
class SettingsSnapshot:
    dust_on: bool
    specular_on: bool
    hdr_on: bool
    rim_on: bool
    decals_on: bool
    fov_deg: int
    fxaa_on: bool = True
    subtitles_on: bool = True


class ConfigurationPanel(Panel):
    def __init__(self,
                 tabs: List[Tuple[str, str]],
                 initial_settings: SettingsSnapshot,
                 set_dust: Callable[[bool], None],
                 set_specular: Callable[[bool], None],
                 set_hdr: Callable[[bool], None],
                 set_rim: Callable[[bool], None],
                 set_decals: Callable[[bool], None],
                 set_fxaa: Callable[[bool], None],
                 set_subtitles: Callable[[bool], None],
                 set_fov_rad: Callable[[float], None]):
        super().__init__()
        self._tabs = list(tabs)
        self._selected_tab = tabs[0][0]
        self._settings = SettingsSnapshot(
            dust_on=initial_settings.dust_on,
            specular_on=initial_settings.specular_on,
            hdr_on=initial_settings.hdr_on,
            rim_on=initial_settings.rim_on,
            decals_on=initial_settings.decals_on,
            fxaa_on=initial_settings.fxaa_on,
            fov_deg=int(initial_settings.fov_deg),
            subtitles_on=initial_settings.subtitles_on,
        )
        self._set_dust = set_dust
        self._set_specular = set_specular
        self._set_hdr = set_hdr
        self._set_rim = set_rim
        self._set_decals = set_decals
        self._set_fxaa = set_fxaa
        self._set_subtitles = set_subtitles
        self._set_fov_rad = set_fov_rad
        self._visible: bool = False
        self._focused: int = -1
        self._last_pushed: Optional[tuple] = None

    @property
    def name(self) -> str:
        return "configuration"

    def is_open(self) -> bool:
        return self._visible

    def open(self) -> None:
        self._visible = True

    def close(self) -> None:
        self._visible = False
        self._focused = -1

    def render_payload(self) -> Optional[str]:
        snapshot = (
            self._visible,
            tuple(self._tabs),
            self._selected_tab,
            self._focused,
            self._settings.dust_on,
            self._settings.specular_on,
            self._settings.hdr_on,
            self._settings.rim_on,
            self._settings.decals_on,
            self._settings.fxaa_on,
            self._settings.subtitles_on,
            self._settings.fov_deg,
        )
        if snapshot == self._last_pushed:
            return None
        self._last_pushed = snapshot
        if not self._visible:
            return "setConfigurationPanel(" + json.dumps({"visible": False}) + ");"
        payload = {
            "visible": True,
            "tabs": [{"id": tid, "label": label} for tid, label in self._tabs],
            "selected_tab": self._selected_tab,
            "focused": self._focused,
            "settings": {
                "dust_on": self._settings.dust_on,
                "specular_on": self._settings.specular_on,
                "hdr_on": self._settings.hdr_on,
                "rim_on": self._settings.rim_on,
                "decals_on": self._settings.decals_on,
                "fxaa_on": self._settings.fxaa_on,
                "subtitles_on": self._settings.subtitles_on,
                "fov_deg": self._settings.fov_deg,
            },
        }
        return "setConfigurationPanel(" + json.dumps(payload) + ");"

    def dispatch_event(self, action: str) -> bool:
        # Applier is invoked before the local state write — if the
        # applier raises, _settings stays on the previous value and the
        # renderer state is whatever the applier left behind. For the
        # no-persistence first pass that's acceptable (panel reflects
        # engine state, exception propagates to the caller).
        if action == "cancel":
            self.close()
            return True
        if action == "toggle:dust":
            new_val = not self._settings.dust_on
            self._set_dust(new_val)
            self._settings.dust_on = new_val
            return True
        if action == "toggle:specular":
            new_val = not self._settings.specular_on
            self._set_specular(new_val)
            self._settings.specular_on = new_val
            return True
        if action == "toggle:hdr":
            new_val = not self._settings.hdr_on
            self._set_hdr(new_val)
            self._settings.hdr_on = new_val
            return True
        if action == "toggle:rim":
            new_val = not self._settings.rim_on
            self._set_rim(new_val)
            self._settings.rim_on = new_val
            return True
        if action == "toggle:decals":
            new_val = not self._settings.decals_on
            self._set_decals(new_val)
            self._settings.decals_on = new_val
            return True
        if action == "toggle:fxaa":
            new_val = not self._settings.fxaa_on
            self._set_fxaa(new_val)
            self._settings.fxaa_on = new_val
            return True
        if action == "toggle:subtitles":
            new_val = not self._settings.subtitles_on
            self._set_subtitles(new_val)
            self._settings.subtitles_on = new_val
            return True
        if action.startswith("fov:"):
            raw = action[len("fov:"):]
            try:
                deg = int(raw)
            except ValueError:
                return False
            deg = max(FOV_MIN, min(FOV_MAX, deg))
            self._set_fov_rad(math.radians(deg))
            self._settings.fov_deg = deg
            return True
        if action.startswith("tab:"):
            tab_id = action[len("tab:"):]
            if any(tid == tab_id for tid, _ in self._tabs):
                self._selected_tab = tab_id
                return True
            return False
        return False

    def invalidate(self) -> None:
        # Focus reset is handled by close(); invalidate() is only the
        # CEF document-reload hook for re-emitting the last payload.
        self._last_pushed = None

    def handle_key_esc(self) -> None:
        if self._visible:
            self.close()

    def handle_input(self, h) -> None:
        """Poll ↑/↓/←/→/Space/Enter when the panel is visible. Mirrors
        the bindings-module shape PauseMenuModel.handle_input uses.
        Missing optional keys (e.g. KEY_LEFT/RIGHT on older bindings)
        degrade silently."""
        if not self._visible:
            return
        keys = h.keys
        focusables = self._focusables()
        if not focusables:
            return

        if h.key_pressed(keys.KEY_DOWN):
            self._focused = 0 if self._focused < 0 else (self._focused + 1) % len(focusables)
        if h.key_pressed(keys.KEY_UP):
            self._focused = (len(focusables) - 1) if self._focused < 0 \
                else (self._focused - 1) % len(focusables)

        kind, target = focusables[self._focused] if self._focused >= 0 else (None, None)

        # Optional keys — older bindings may omit these. getattr-with-default
        # mirrors PauseMenuModel.handle_input's KEY_ENTER pattern.
        k_space = getattr(keys, "KEY_SPACE", None)
        k_enter = getattr(keys, "KEY_ENTER", None)
        k_left  = getattr(keys, "KEY_LEFT",  None)
        k_right = getattr(keys, "KEY_RIGHT", None)

        def _pressed(code):
            return code is not None and h.key_pressed(code)

        activate = _pressed(k_space) or _pressed(k_enter)

        if activate and kind == "ctrl" and target == "dust":
            self.dispatch_event("toggle:dust")
        elif activate and kind == "ctrl" and target == "specular":
            self.dispatch_event("toggle:specular")
        elif activate and kind == "ctrl" and target == "hdr":
            self.dispatch_event("toggle:hdr")
        elif activate and kind == "ctrl" and target == "rim":
            self.dispatch_event("toggle:rim")
        elif activate and kind == "ctrl" and target == "decals":
            self.dispatch_event("toggle:decals")
        elif activate and kind == "ctrl" and target == "fxaa":
            self.dispatch_event("toggle:fxaa")
        elif activate and kind == "ctrl" and target == "subtitles":
            self.dispatch_event("toggle:subtitles")
        elif activate and kind == "tab":
            self.dispatch_event("tab:" + target)

        if kind == "ctrl" and target == "fov":
            if _pressed(k_right):
                self.dispatch_event("fov:" + str(self._settings.fov_deg + FOV_STEP))
            if _pressed(k_left):
                self.dispatch_event("fov:" + str(self._settings.fov_deg - FOV_STEP))

    def _focusables(self) -> list:
        """Ordered focusable list: tab rows then controls in the
        currently selected tab. For the only tab today (graphics):
        [('tab','graphics'), ('ctrl','dust'), ('ctrl','specular'),
         ('ctrl','fov'), ('ctrl','hdr'), ('ctrl','rim'), ('ctrl','decals'),
         ('ctrl','fxaa')]."""
        out: list = [("tab", tid) for tid, _ in self._tabs]
        if self._selected_tab == "graphics":
            out += [("ctrl", "dust"), ("ctrl", "specular"), ("ctrl", "fov"),
                    ("ctrl", "hdr"), ("ctrl", "rim"), ("ctrl", "decals"),
                    ("ctrl", "fxaa")]
        elif self._selected_tab == "gameplay":
            out += [("ctrl", "subtitles")]
        return out
