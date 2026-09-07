"""Configuration panel — pause-menu modal with tabbed settings.

Subclasses engine.ui.panel.Panel; pumped by PanelRegistry like the
mission picker. Owns a SettingsSnapshot and one injected applier per
effect. Every state mutation immediately fires the matching applier —
there is no Apply/Cancel; closing the panel does not revert. Settings
persist across launches via engine.settings_store: the host loop
loads the store, applies stored values, and binds on_change/on_reset. The
panel itself never imports the store.

Three rows are masters over several appliers each: Improved Space
Visuals (volumetric nebulae, procedural sky), Camera Realism
(HDR, filmic filter, motion blur, modern lens flares) and Cinematic
Lighting (Fresnel rim light, dynamic shadows, nebula lightning,
subsystem light emitters, directional ambient). The appliers stay
individually injected so the renderer surface is unchanged.

Effects deliberately NOT exposed, because they are core to how the game
reads rather than preferences: specular highlights, damage decals, hull
breaches, and the set-to-set warp cinematic.

Spec: docs/superpowers/specs/2026-06-05-configuration-panel-design.md
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from engine.ui.panel import Panel


FOV_MIN  = 25
FOV_MAX  = 55
FOV_STEP = 5

# AI difficulty index (0=Easy, 1=Medium, 2=Hard) — mirrors App.Game_GetDifficulty.
AI_DIFFICULTY_LABELS = ("Easy", "Medium", "Hard")

# ── Anti-aliasing modes ─────────────────────────────────────────────────────
# One mutually-exclusive selector replaces the old independent SMAA toggle:
# SMAA is post-process and MSAA is multisample geometry, and running both
# would spend twice for one edge.
#
# The stored value is the INDEX, not a sample count. The settings table's
# lo/hi does a contiguous-range check, which an index satisfies and the set
# {0, 2, 4, 8} does not. Driver capability is a separate concern, handled by
# clamping at apply time against GL_MAX_SAMPLES — so a settings file carrying
# AA_MSAA_8X on a 4x-max machine applies 4x, and applies 8x again if that file
# moves to a machine that supports it.
AA_OFF = 0
AA_SMAA = 1
AA_MSAA_2X = 2
AA_MSAA_4X = 3
AA_MSAA_8X = 4

# Indexed by aa_mode. SMAA is not a sample count, hence the second 0.
AA_MODE_SAMPLES = (0, 0, 2, 4, 8)
AA_MODE_LABELS = ("Off", "SMAA", "2×", "4×", "8×")

# ── Master toggles ───────────────────────────────────────────────────────────
# One player-facing row over several renderer appliers. (key, label, appliers),
# in rendered order. The key drives everything by construction: the settings
# field `<key>_on`, the action `toggle:<key>`, the payload key, and the
# focusable ('ctrl', key) — so adding or re-grouping a master is a single edit
# here plus the matching row in configuration_panel.js.
#
# Applier names are the constructor's `set_<name>` parameters.
MASTER_TOGGLES = (
    ("improved_space", "Improved Space Visuals",
     ("procedural_sky", "volumetric_nebulae")),
    ("camera_realism", "Camera Realism",
     ("hdr", "filmic", "motion_blur", "hdr_lens_flare", "dof")),
    # NOTE label vs key: the row reads "Cinematic Lighting" but the key stays
    # `realistic_lighting`. The key drives the action string, the payload key,
    # the focusable AND the persisted settings key, so renaming it would need
    # a schema migration for a purely cosmetic change. The divergence is
    # deliberate — do not "fix" it without one.
    ("realistic_lighting", "Cinematic Lighting",
     ("rim", "shadows", "nebula_lightning", "ship_light_emitters",
      "ambient_gradient")),
)

MASTER_KEYS = tuple(key for key, _label, _appliers in MASTER_TOGGLES)


@dataclass
class SettingsSnapshot:
    fov_deg: int
    aa_mode: int = AA_SMAA
    subtitles_on: bool = True
    disable_annoying_dialogue_on: bool = True
    ai_difficulty: int = 1
    dust_on: bool = True
    # One master toggle over the volumetric nebulae and the procedural sky.
    # Off == stock BC space: authored starbox, flat nebulae. Space dust was
    # folded in here and pulled back out after a live look — it reads as its
    # own thing rather than part of the sky.
    improved_space_on: bool = True
    # One master toggle over HDR, the filmic filter, motion blur and modern
    # lens flares — four settings the player used to set independently.
    camera_realism_on: bool = True
    # One master toggle over Fresnel rim light, dynamic shadows, nebula
    # lightning, the subsystem light emitters, and directional ambient. The
    # row displays "Cinematic Lighting" but the field/key stays
    # `realistic_lighting` deliberately: that key drives the action string,
    # the payload key sent to CEF, the focusable id, and the persisted
    # setting name, so renaming it would be a migration, not a relabel.
    realistic_lighting_on: bool = True
    # Weapon-impact camera kick. Sits under Modern VFX beside the masters.
    camera_shake_on: bool = True


class ConfigurationPanel(Panel):
    def __init__(self,
                 tabs: List[Tuple[str, str]],
                 initial_settings: SettingsSnapshot,
                 set_dust: Callable[[bool], None],
                 set_hdr: Callable[[bool], None],
                 set_rim: Callable[[bool], None],
                 set_aa_mode: Callable[[int], None],
                 set_subtitles: Callable[[bool], None],
                 set_disable_annoying_dialogue: Callable[[bool], None],
                 set_ai_difficulty: Callable[[int], None],
                 set_fov_rad: Callable[[float], None],
                 set_shadows: Callable[[bool], None],
                 set_procedural_sky: Callable[[bool], None],
                 set_filmic: Callable[[bool], None],
                 set_motion_blur: Callable[[bool], None],
                 set_dof: Callable[[bool], None],
                 set_volumetric_nebulae: Callable[[bool], None],
                 set_nebula_lightning: Callable[[bool], None],
                 set_hdr_lens_flare: Callable[[bool], None],
                 set_ship_light_emitters: Callable[[bool], None],
                 set_camera_shake: Callable[[bool], None],
                 set_ambient_gradient: Callable[[bool], None],
                 input_map=None,
                 # GL_MAX_SAMPLES from the live context. Defaults to the
                 # highest mode we offer so every existing construction site
                 # and test shows all five segments; the host loop passes the
                 # driver's real ceiling.
                 max_msaa_samples: int = 8,
                 on_change: Optional[Callable[[str, object], None]] = None,
                 on_reset: Optional[Callable[[str], dict]] = None):
        super().__init__()
        self._tabs = list(tabs)
        self._selected_tab = tabs[0][0]
        self._settings = SettingsSnapshot(
            aa_mode=max(AA_OFF, min(AA_MSAA_8X, int(initial_settings.aa_mode))),
            fov_deg=int(initial_settings.fov_deg),
            subtitles_on=initial_settings.subtitles_on,
            disable_annoying_dialogue_on=initial_settings.disable_annoying_dialogue_on,
            ai_difficulty=max(0, min(2, int(initial_settings.ai_difficulty))),
            dust_on=initial_settings.dust_on,
            improved_space_on=initial_settings.improved_space_on,
            camera_realism_on=initial_settings.camera_realism_on,
            realistic_lighting_on=initial_settings.realistic_lighting_on,
            camera_shake_on=initial_settings.camera_shake_on,
        )
        # Master-member appliers, addressed by the names in MASTER_TOGGLES.
        # Kept as explicit constructor params (not **kwargs) so a missing one
        # is a TypeError at construction rather than a silently dead toggle.
        self._appliers = {
            "hdr": set_hdr,
            "rim": set_rim,
            "shadows": set_shadows,
            "procedural_sky": set_procedural_sky,
            "filmic": set_filmic,
            "motion_blur": set_motion_blur,
            "dof": set_dof,
            "volumetric_nebulae": set_volumetric_nebulae,
            "nebula_lightning": set_nebula_lightning,
            "hdr_lens_flare": set_hdr_lens_flare,
            "ship_light_emitters": set_ship_light_emitters,
            "ambient_gradient": set_ambient_gradient,
        }
        # Standalone rows keep their own attribute.
        self._set_dust = set_dust
        self._set_camera_shake = set_camera_shake
        self._set_aa_mode = set_aa_mode
        self._max_msaa_samples = int(max_msaa_samples)
        self._set_subtitles = set_subtitles
        self._set_disable_annoying_dialogue = set_disable_annoying_dialogue
        self._set_ai_difficulty = set_ai_difficulty
        self._set_fov_rad = set_fov_rad
        # Controls tab: action → physical-key remapping (engine.input_map.InputMap).
        # Optional so existing construction/tests without a controls tab still work.
        self._input_map = input_map
        # Persistence seam. Defaults are no-ops so the panel works standalone
        # and every existing construction site keeps compiling. The panel never
        # imports the settings store — the host loop binds these.
        self._on_change = on_change or (lambda key, value: None)
        self._on_reset = on_reset or (lambda section: {})
        self._capturing_action: Optional[str] = None  # action_id mid key-capture
        self._controls_message: str = ""              # transient conflict/info text
        self._visible: bool = False
        self._focused: int = -1
        self._last_pushed: Optional[tuple] = None

    @property
    def name(self) -> str:
        return "configuration"

    def is_open(self) -> bool:
        return self._visible

    @property
    def capturing_action(self) -> Optional[str]:
        """The action_id awaiting a key (host loop scans keys when set)."""
        return self._capturing_action

    def open(self) -> None:
        self.visible = True

    def close(self) -> None:
        self.visible = False
        self._focused = -1
        self._capturing_action = None
        self._controls_message = ""

    def _controls_rows(self) -> list:
        """[{id, label, category, key}] for the Controls tab, in ACTIONS order."""
        if self._input_map is None:
            return []
        from engine.input_map import ACTIONS
        return [{"id": aid, "label": label, "category": cat,
                 "key": self._input_map.name(aid)}
                for (aid, label, cat, _default) in ACTIONS]

    def render_payload(self) -> Optional[str]:
        controls_rows = self._controls_rows()
        controls_sig = tuple((r["id"], r["key"]) for r in controls_rows)
        snapshot = (
            self._visible,
            tuple(self._tabs),
            self._selected_tab,
            self._focused,
            controls_sig,
            self._capturing_action,
            self._controls_message,
            self._settings.aa_mode,
            self._settings.subtitles_on,
            self._settings.disable_annoying_dialogue_on,
            self._settings.ai_difficulty,
            self._settings.dust_on,
            self._settings.camera_shake_on,
            tuple(getattr(self._settings, k + "_on") for k in MASTER_KEYS),
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
            "controls": controls_rows,
            "capturing_action": self._capturing_action,
            "capturing_label": (self._input_map.label(self._capturing_action)
                                if (self._capturing_action and self._input_map)
                                else ""),
            "controls_message": self._controls_message,
            "settings": {
                "aa_mode": self._settings.aa_mode,
                # The driver's ceiling: the JS omits segments above it rather
                # than showing options this machine cannot deliver.
                "max_msaa_samples": self._max_msaa_samples,
                "subtitles_on": self._settings.subtitles_on,
                "disable_annoying_dialogue_on": self._settings.disable_annoying_dialogue_on,
                "ai_difficulty": self._settings.ai_difficulty,
                "dust_on": self._settings.dust_on,
                "camera_shake_on": self._settings.camera_shake_on,
                "fov_deg": self._settings.fov_deg,
                **{k + "_on": getattr(self._settings, k + "_on")
                   for k in MASTER_KEYS},
            },
        }
        return "setConfigurationPanel(" + json.dumps(payload) + ");"

    def dispatch_event(self, action: str) -> bool:
        # Applier is invoked before the local state write — if the
        # applier raises, _settings stays on the previous value and the
        # renderer state is whatever the applier left behind. This ordering
        # is now load-bearing, not just tolerated: on_change (settings
        # persistence) fires from the same branches AFTER the setattr, so an
        # applier that raises must also skip on_change — otherwise the store
        # would record a value the engine never actually reached. See
        # test_a_raising_applier_does_not_report_a_change.
        if action == "cancel":
            self.close()
            return True
        # ── Controls tab: action → physical-key remapping ────────────────────
        if action.startswith("rebind:"):
            if self._input_map is None:
                return False
            self._capturing_action = action[len("rebind:"):]
            self._controls_message = ""
            return True
        if action == "capture_cancel":
            self._capturing_action = None
            self._controls_message = ""
            return True
        if action == "controls_reset":
            if self._input_map is None:
                return False
            self._input_map.reset()
            self._input_map.save()
            self._capturing_action = None
            self._controls_message = ""
            return True
        if action.startswith("bind:"):
            # "bind:<action_id>:<key_name>" — apply a captured key.
            if self._input_map is None:
                return False
            rest = action[len("bind:"):]
            action_id, _, key_name = rest.partition(":")
            if not action_id or not key_name:
                return False
            from engine.input_map import GLFW_KEYS, RESERVED
            if key_name in RESERVED or key_name not in GLFW_KEYS:
                self._controls_message = "%s can't be bound" % (key_name,)
                return True  # stay in capture so the user can try another key
            owner = self._input_map.action_for(key_name)
            if owner is not None and owner != action_id:
                # Block + warn: leave both bindings unchanged.
                self._controls_message = "%s is already bound to %s" % (
                    key_name, self._input_map.label(owner))
                return True
            self._input_map.set(action_id, key_name)
            self._input_map.save()
            self._capturing_action = None
            self._controls_message = ""
            return True
        for key, _label, appliers in MASTER_TOGGLES:
            if action != "toggle:" + key:
                continue
            # Appliers run before the local write, matching every other branch
            # here: if one raises, the earlier ones have already fired and
            # _settings stays on the old value, so the panel re-reads as the
            # pre-toggle state.
            new_val = not getattr(self._settings, key + "_on")
            for name in appliers:
                self._appliers[name](new_val)
            setattr(self._settings, key + "_on", new_val)
            self._on_change(key, new_val)
            return True
        if action == "toggle:camera_shake":
            new_val = not self._settings.camera_shake_on
            self._set_camera_shake(new_val)
            self._settings.camera_shake_on = new_val
            self._on_change("camera_shake", new_val)
            return True
        if action == "toggle:dust":
            new_val = not self._settings.dust_on
            self._set_dust(new_val)
            self._settings.dust_on = new_val
            self._on_change("dust", new_val)
            return True
        if action.startswith("aa_mode:"):
            try:
                mode = int(action[len("aa_mode:"):])
            except ValueError:
                return False
            if not (AA_OFF <= mode <= AA_MSAA_8X):
                return False
            self._set_aa_mode(mode)
            self._settings.aa_mode = mode
            self._on_change("aa_mode", mode)
            return True
        if action == "toggle:subtitles":
            new_val = not self._settings.subtitles_on
            self._set_subtitles(new_val)
            self._settings.subtitles_on = new_val
            self._on_change("subtitles", new_val)
            return True
        if action == "toggle:disable_annoying_dialogue":
            new_val = not self._settings.disable_annoying_dialogue_on
            self._set_disable_annoying_dialogue(new_val)
            self._settings.disable_annoying_dialogue_on = new_val
            self._on_change("disable_annoying_dialogue", new_val)
            return True
        if action.startswith("ai_difficulty:"):
            raw = action[len("ai_difficulty:"):]
            try:
                level = int(raw)
            except ValueError:
                return False
            level = max(0, min(2, level))
            self._set_ai_difficulty(level)
            self._settings.ai_difficulty = level
            self._on_change("ai_difficulty", level)
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
            self._on_change("fov_deg", deg)
            return True
        if action.startswith("reset:"):
            # Per-tab reset. Scoped rather than global so a fat-finger can't
            # wipe keybindings, which the Controls tab resets on its own.
            section = action[len("reset:"):]
            if section not in ("graphics", "gameplay"):
                return False
            for field, value in self._on_reset(section).items():
                setattr(self._settings, field, value)
            return True
        if action.startswith("tab:"):
            tab_id = action[len("tab:"):]
            if any(tid == tab_id for tid, _ in self._tabs):
                self._selected_tab = tab_id
                self._capturing_action = None   # leaving the tab cancels capture
                self._controls_message = ""
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
        # While capturing a key the host loop owns the keyboard (it scans for the
        # bound key); don't let panel nav consume those presses.
        if self._capturing_action is not None:
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

        if activate and kind == "ctrl" and target in MASTER_KEYS:
            self.dispatch_event("toggle:" + target)
        elif activate and kind == "ctrl" and target == "camera_shake":
            self.dispatch_event("toggle:camera_shake")
        elif activate and kind == "ctrl" and target == "dust":
            self.dispatch_event("toggle:dust")
        # aa_mode has no activate branch: it is a multi-value selector driven
        # by left/right below, like ai_difficulty, not a toggle.
        elif activate and kind == "ctrl" and target == "subtitles":
            self.dispatch_event("toggle:subtitles")
        elif activate and kind == "ctrl" and target == "disable_annoying_dialogue":
            self.dispatch_event("toggle:disable_annoying_dialogue")
        elif activate and kind == "ctrl" and target == "controls_reset":
            self.dispatch_event("controls_reset")
        elif activate and kind == "ctrl" and target == "reset_graphics":
            self.dispatch_event("reset:graphics")
        elif activate and kind == "ctrl" and target == "reset_gameplay":
            self.dispatch_event("reset:gameplay")
        elif activate and kind == "rebind":
            self.dispatch_event("rebind:" + target)
        elif activate and kind == "tab":
            self.dispatch_event("tab:" + target)

        if kind == "ctrl" and target == "fov":
            if _pressed(k_right):
                self.dispatch_event("fov:" + str(self._settings.fov_deg + FOV_STEP))
            if _pressed(k_left):
                self.dispatch_event("fov:" + str(self._settings.fov_deg - FOV_STEP))

        if kind == "ctrl" and target == "ai_difficulty":
            if _pressed(k_right):
                self.dispatch_event("ai_difficulty:" + str(self._settings.ai_difficulty + 1))
            if _pressed(k_left):
                self.dispatch_event("ai_difficulty:" + str(self._settings.ai_difficulty - 1))

        # Clamped here rather than relying on dispatch_event's range check, so
        # holding right at 8x is a no-op instead of a rejected event.
        if kind == "ctrl" and target == "aa_mode":
            if _pressed(k_right):
                self.dispatch_event(
                    "aa_mode:" + str(min(AA_MSAA_8X, self._settings.aa_mode + 1)))
            if _pressed(k_left):
                self.dispatch_event(
                    "aa_mode:" + str(max(AA_OFF, self._settings.aa_mode - 1)))

    def _focusables(self) -> list:
        """Ordered focusable list: tab rows then controls in the
        currently selected tab. Order mirrors the rendered rows — the two
        standalone controls, then the 'Modern VFX' group of master toggles,
        then the per-tab Reset row:
        [('tab','graphics'), ('ctrl','aa_mode'), ('ctrl','dust'), ('ctrl','fov'),
         ('ctrl','improved_space'), ('ctrl','camera_realism'),
         ('ctrl','realistic_lighting'), ('ctrl','camera_shake'),
         ('ctrl','reset_graphics')].

        configuration_panel.js mirrors this list by hand; the two are pinned
        together by test_js_graphics_focusables_match_python."""
        out: list = [("tab", tid) for tid, _ in self._tabs]
        if self._selected_tab == "graphics":
            out += [("ctrl", "aa_mode"), ("ctrl", "dust"), ("ctrl", "fov")]
            out += [("ctrl", k) for k in MASTER_KEYS]
            out += [("ctrl", "camera_shake")]
            out += [("ctrl", "reset_graphics")]
        elif self._selected_tab == "gameplay":
            out += [("ctrl", "subtitles"),
                    ("ctrl", "disable_annoying_dialogue"),
                    ("ctrl", "ai_difficulty"),
                    ("ctrl", "reset_gameplay")]
        elif self._selected_tab == "controls" and self._input_map is not None:
            from engine.input_map import ACTION_IDS
            out += [("rebind", aid) for aid in ACTION_IDS]
            out += [("ctrl", "controls_reset")]
        return out
