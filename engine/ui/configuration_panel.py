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
    smaa_on: bool = True
    subtitles_on: bool = True
    disable_annoying_dialogue_on: bool = True
    shadows_on: bool = True
    procedural_sky_on: bool = True
    filmic_on: bool = True
    motion_blur_on: bool = True
    warp_flythrough_on: bool = True
    volumetric_nebulae_on: bool = True
    nebula_lightning_on: bool = True


class ConfigurationPanel(Panel):
    def __init__(self,
                 tabs: List[Tuple[str, str]],
                 initial_settings: SettingsSnapshot,
                 set_dust: Callable[[bool], None],
                 set_specular: Callable[[bool], None],
                 set_hdr: Callable[[bool], None],
                 set_rim: Callable[[bool], None],
                 set_decals: Callable[[bool], None],
                 set_smaa: Callable[[bool], None],
                 set_subtitles: Callable[[bool], None],
                 set_disable_annoying_dialogue: Callable[[bool], None],
                 set_fov_rad: Callable[[float], None],
                 set_shadows: Callable[[bool], None],
                 set_procedural_sky: Callable[[bool], None],
                 set_filmic: Callable[[bool], None],
                 set_motion_blur: Callable[[bool], None],
                 set_warp_flythrough: Callable[[bool], None],
                 set_volumetric_nebulae: Callable[[bool], None],
                 set_nebula_lightning: Callable[[bool], None]):
        super().__init__()
        self._tabs = list(tabs)
        self._selected_tab = tabs[0][0]
        self._settings = SettingsSnapshot(
            dust_on=initial_settings.dust_on,
            specular_on=initial_settings.specular_on,
            hdr_on=initial_settings.hdr_on,
            rim_on=initial_settings.rim_on,
            decals_on=initial_settings.decals_on,
            smaa_on=initial_settings.smaa_on,
            fov_deg=int(initial_settings.fov_deg),
            subtitles_on=initial_settings.subtitles_on,
            disable_annoying_dialogue_on=initial_settings.disable_annoying_dialogue_on,
            shadows_on=initial_settings.shadows_on,
            procedural_sky_on=initial_settings.procedural_sky_on,
            filmic_on=initial_settings.filmic_on,
            motion_blur_on=initial_settings.motion_blur_on,
            warp_flythrough_on=initial_settings.warp_flythrough_on,
            volumetric_nebulae_on=initial_settings.volumetric_nebulae_on,
            nebula_lightning_on=initial_settings.nebula_lightning_on,
        )
        self._set_dust = set_dust
        self._set_specular = set_specular
        self._set_hdr = set_hdr
        self._set_rim = set_rim
        self._set_decals = set_decals
        self._set_smaa = set_smaa
        self._set_subtitles = set_subtitles
        self._set_disable_annoying_dialogue = set_disable_annoying_dialogue
        self._set_fov_rad = set_fov_rad
        self._set_shadows = set_shadows
        self._set_procedural_sky = set_procedural_sky
        self._set_filmic = set_filmic
        self._set_motion_blur = set_motion_blur
        self._set_warp_flythrough = set_warp_flythrough
        self._set_volumetric_nebulae = set_volumetric_nebulae
        self._set_nebula_lightning = set_nebula_lightning
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
            self._settings.smaa_on,
            self._settings.subtitles_on,
            self._settings.disable_annoying_dialogue_on,
            self._settings.shadows_on,
            self._settings.procedural_sky_on,
            self._settings.filmic_on,
            self._settings.motion_blur_on,
            self._settings.warp_flythrough_on,
            self._settings.volumetric_nebulae_on,
            self._settings.nebula_lightning_on,
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
                "smaa_on": self._settings.smaa_on,
                "subtitles_on": self._settings.subtitles_on,
                "disable_annoying_dialogue_on": self._settings.disable_annoying_dialogue_on,
                "shadows_on": self._settings.shadows_on,
                "procedural_sky_on": self._settings.procedural_sky_on,
                "filmic_on": self._settings.filmic_on,
                "motion_blur_on": self._settings.motion_blur_on,
                "warp_flythrough_on": self._settings.warp_flythrough_on,
                "volumetric_nebulae_on": self._settings.volumetric_nebulae_on,
                "nebula_lightning_on": self._settings.nebula_lightning_on,
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
        if action == "toggle:procedural_sky":
            new_val = not self._settings.procedural_sky_on
            self._set_procedural_sky(new_val)
            self._settings.procedural_sky_on = new_val
            return True
        if action == "toggle:filmic":
            new_val = not self._settings.filmic_on
            self._set_filmic(new_val)
            self._settings.filmic_on = new_val
            return True
        if action == "toggle:motion_blur":
            new_val = not self._settings.motion_blur_on
            self._set_motion_blur(new_val)
            self._settings.motion_blur_on = new_val
            return True
        if action == "toggle:warp_flythrough":
            new_val = not self._settings.warp_flythrough_on
            self._set_warp_flythrough(new_val)
            self._settings.warp_flythrough_on = new_val
            return True
        if action == "toggle:volumetric_nebulae":
            new_val = not self._settings.volumetric_nebulae_on
            self._set_volumetric_nebulae(new_val)
            self._settings.volumetric_nebulae_on = new_val
            return True
        if action == "toggle:nebula_lightning":
            new_val = not self._settings.nebula_lightning_on
            self._set_nebula_lightning(new_val)
            self._settings.nebula_lightning_on = new_val
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
        if action == "toggle:shadows":
            new_val = not self._settings.shadows_on
            self._set_shadows(new_val)
            self._settings.shadows_on = new_val
            return True
        if action == "toggle:decals":
            new_val = not self._settings.decals_on
            self._set_decals(new_val)
            self._settings.decals_on = new_val
            return True
        if action == "toggle:smaa":
            new_val = not self._settings.smaa_on
            self._set_smaa(new_val)
            self._settings.smaa_on = new_val
            return True
        if action == "toggle:subtitles":
            new_val = not self._settings.subtitles_on
            self._set_subtitles(new_val)
            self._settings.subtitles_on = new_val
            return True
        if action == "toggle:disable_annoying_dialogue":
            new_val = not self._settings.disable_annoying_dialogue_on
            self._set_disable_annoying_dialogue(new_val)
            self._settings.disable_annoying_dialogue_on = new_val
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
        elif activate and kind == "ctrl" and target == "procedural_sky":
            self.dispatch_event("toggle:procedural_sky")
        elif activate and kind == "ctrl" and target == "filmic":
            self.dispatch_event("toggle:filmic")
        elif activate and kind == "ctrl" and target == "motion_blur":
            self.dispatch_event("toggle:motion_blur")
        elif activate and kind == "ctrl" and target == "warp_flythrough":
            self.dispatch_event("toggle:warp_flythrough")
        elif activate and kind == "ctrl" and target == "volumetric_nebulae":
            self.dispatch_event("toggle:volumetric_nebulae")
        elif activate and kind == "ctrl" and target == "nebula_lightning":
            self.dispatch_event("toggle:nebula_lightning")
        elif activate and kind == "ctrl" and target == "hdr":
            self.dispatch_event("toggle:hdr")
        elif activate and kind == "ctrl" and target == "rim":
            self.dispatch_event("toggle:rim")
        elif activate and kind == "ctrl" and target == "decals":
            self.dispatch_event("toggle:decals")
        elif activate and kind == "ctrl" and target == "smaa":
            self.dispatch_event("toggle:smaa")
        elif activate and kind == "ctrl" and target == "shadows":
            self.dispatch_event("toggle:shadows")
        elif activate and kind == "ctrl" and target == "subtitles":
            self.dispatch_event("toggle:subtitles")
        elif activate and kind == "ctrl" and target == "disable_annoying_dialogue":
            self.dispatch_event("toggle:disable_annoying_dialogue")
        elif activate and kind == "tab":
            self.dispatch_event("tab:" + target)

        if kind == "ctrl" and target == "fov":
            if _pressed(k_right):
                self.dispatch_event("fov:" + str(self._settings.fov_deg + FOV_STEP))
            if _pressed(k_left):
                self.dispatch_event("fov:" + str(self._settings.fov_deg - FOV_STEP))

    def _focusables(self) -> list:
        """Ordered focusable list: tab rows then controls in the
        currently selected tab. Order mirrors the rendered rows — the
        general toggles, then the 'Modern VFX' group (procedural_sky leads
        it): [('tab','graphics'), ('ctrl','dust'), ('ctrl','specular'),
         ('ctrl','fov'), ('ctrl','procedural_sky'), ('ctrl','hdr'),
         ('ctrl','rim'), ('ctrl','shadows'), ('ctrl','decals'),
         ('ctrl','smaa'), ('ctrl','filmic'), ('ctrl','motion_blur'),
         ('ctrl','warp_flythrough'), ('ctrl','volumetric_nebulae'),
         ('ctrl','nebula_lightning')]."""
        out: list = [("tab", tid) for tid, _ in self._tabs]
        if self._selected_tab == "graphics":
            out += [("ctrl", "dust"), ("ctrl", "specular"),
                    ("ctrl", "fov"), ("ctrl", "procedural_sky"),
                    ("ctrl", "hdr"), ("ctrl", "rim"), ("ctrl", "shadows"),
                    ("ctrl", "decals"), ("ctrl", "smaa"), ("ctrl", "filmic"),
                    ("ctrl", "motion_blur"), ("ctrl", "warp_flythrough"),
                    ("ctrl", "volumetric_nebulae"), ("ctrl", "nebula_lightning")]
        elif self._selected_tab == "gameplay":
            out += [("ctrl", "subtitles"),
                    ("ctrl", "disable_annoying_dialogue")]
        return out
