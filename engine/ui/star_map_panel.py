"""StarMapPanel — 3D star map for Helm -> Set Course.

Replaces SettingCoursePanel's left-hand system list with a native-GL star
map; the warp-point column is unchanged. Satisfies the SAME contract as the
panel it replaces: produce a destination set-module, call on_course_set,
close. The player then engages the warp from the SDK Helm "Warp" button.

Spec: docs/superpowers/specs/2026-08-20-star-map-set-course-design.md
"""
from __future__ import annotations

import json
from typing import Optional

from engine import dev_mode
from engine.appc import sector_model as sm
from engine.ui import star_map
from engine.ui.panel import Panel

# Modal + map geometry in CEF logical pixels. The modal (.cp-modal) is
# 880x560 with a 1px border, a fixed 28px .cp-header and a fixed 54px
# .cp-footer; the map fills the WHOLE body BETWEEN them.
#
# MAP_H is DERIVED, never asserted. It was a hardcoded 520 against a 478px
# body, so the map's opaque GL backdrop overran the footer strip by 42px. The
# three vertical terms must sum to MODAL_H, and every one of them is pinned to
# the real CSS by test_the_map_rect_fits_the_modal_body — .cp-header's height
# in configuration_panel.css, .cp-footer's in star_map.css (the shared rule is
# padding-sized, i.e. font-dependent, so the map gives it a fixed height to
# divide by), and .cp-modal's own width/height literals.
# Actions that drive the MAP itself. Ignored while the target popup is open,
# which is what makes that popup modal.
_MAP_ACTIONS = frozenset({"orbit", "zoom", "pick"})

# Only used when the TGL is unreachable (headless, or game/ absent). Never the
# normal path: the label comes from the same database the Helm menu reads.
_WARP_FALLBACK = "Warp"

MODAL_W, MODAL_H = 880, 560
MODAL_BORDER = 1
HEADER_H = 28
FOOTER_H = 54
MAP_W = MODAL_W        # the map fills the modal; targets are a popup OVER it
MAP_H = MODAL_H - HEADER_H - FOOTER_H


def rect_for_view(view_w, view_h) -> tuple:
    """Map viewport rect (x, y, w, h) for a CEF logical view of this size.

    The CEF view is NOT a constant: it tracks the host window's size in
    points (host_loop._compute_cef_resize), and .cp-modal is flex-CENTRED in
    it. Pinning the viewport at one view's numbers made the map coincide with
    its own chrome only at 1280x720 — at 1512x982 the frame sat at (316, 211)
    while the map drew at (200, 108), outside it. So the centring rule is
    expressed here, once, and mirrored by exactly one CSS calc() per axis.

    The 1px border cancels out of the centring: the modal's OUTER box is
    MODAL_W + 2 wide (content-box), so the content's left edge is
    (view - (MODAL_W + 2)) / 2 + 1 == view / 2 - MODAL_W / 2. Hence the CSS is
    `calc(50% - 440px)` / `calc(50% - 252px)` with no border term, and
    MODAL_BORDER exists to name why it is absent rather than to be used.

    Chromium resolves `50%` in device pixels and may disagree with Python's
    round() by <=1px on odd view dimensions, shifting the GL stars up to 1px
    against the CEF labels. That is invisible, and it cannot separate the
    labels from the hole: the labels live INSIDE #star-map-viewport, so they
    move with the CSS rect whatever it resolves to.

    Clamped at 0 so a view smaller than the modal never yields a negative
    origin (which the GL scissor would reject and picking would mis-offset).
    """
    return (max(0, round(view_w / 2 - MODAL_W / 2)),
            max(0, round(view_h / 2 - MODAL_H / 2 + HEADER_H)),
            MAP_W, MAP_H)


# The rect at the boot view size (host_loop.py:_CEF_VIEW_W/H start 1280x720).
# Kept as a named constant because it is the panel's own starting rect and the
# value the CSS-agreement test pins the formula against.
MAP_RECT = rect_for_view(1280, 720)


class StarMapPanel(Panel):
    def __init__(self, on_course_set=None, on_warp_engage=None) -> None:
        super().__init__()
        self._on_course_set = on_course_set
        # Same hook the Helm "Warp" button uses, so the in-modal button and
        # the SDK one run one code path — gate, then execute_warp. The SDK
        # button is untouched and still works on its own.
        self._on_warp_engage = on_warp_engage
        self._visible = False
        self._course_menu = None
        self._selected_system: Optional[str] = None
        self._here_system: Optional[str] = None
        self._last_pushed: Optional[str] = None
        self.rect = MAP_RECT
        self.cam = star_map.StarMapCamera(anchor=(0.0, 0.0, 0.0))
        self.scene = star_map.build_scene(model={"systems": [], "nebulae": [],
                                                 "starclouds": []})

    @property
    def name(self) -> str:
        return "star-map"

    def is_open(self) -> bool:
        return self._visible

    def _warp_destination(self):
        """The set-module currently recorded on the SDK warp button, or None.

        This is the SAME source the Helm "Warp" button reads, so the in-modal
        button cannot disagree with it — including a course set before the map
        was ever opened, or set from the old Set Course list.
        """
        try:
            import App
            btn = App.SortedRegionMenu_GetWarpButton()
            dest = btn.GetDestination() if btn is not None else None
            return dest or None
        except Exception as e:
            dev_mode.log_swallowed("star map warp destination", e)
            return None

    def _warp_enabled(self) -> bool:
        return self._warp_destination() is not None

    def _warp_label(self) -> str:
        """The Helm menu's own translated string, not a hard-coded "Warp".

        Bridge Menus.tgl is where HelmMenuHandlers gets it
        (App.g_kLocalizationManager.Load(...).GetString("Warp")), so the two
        buttons cannot drift apart or ship untranslated in one place.
        """
        try:
            import App
            db = App.g_kLocalizationManager.Load("data/TGL/Bridge Menus.tgl")
            return str(db.GetString("Warp")) or _WARP_FALLBACK
        except Exception as e:
            dev_mode.log_swallowed("star map warp label", e)
            return _WARP_FALLBACK

    def _targets_open(self) -> bool:
        """The target popup is shown exactly when a system is selected — no
        separate flag to fall out of step with the selection."""
        return self._selected_system is not None

    def set_view_size(self, view_w, view_h) -> None:
        """Re-centre the map rect for the live CEF logical view size.

        The host loop calls this every frame, before rendering panels, so
        label projection, click picking and the GL scissor all read the same
        rect within a frame — they share self.rect, so they can only agree.
        """
        self.rect = rect_for_view(view_w, view_h)

    def open(self, course_menu=None, set_name=None) -> None:
        self._course_menu = course_menu
        self._selected_system = None
        self._visible = True
        here, anchor = star_map.resolve_anchor(set_name)
        self._here_system = here
        self.cam = star_map.StarMapCamera(anchor=anchor)
        self._rebuild_scene()

    def close(self) -> None:
        self._visible = False
        # Drop the SDK menu handle. It belongs to the mission that opened the
        # modal, and this panel outlives mission swaps — retaining it would
        # keep a dead SortedRegionMenu (and everything it owns) alive across
        # one. Nothing reads it while closed, and open() reassigns it, so this
        # is a lifetime fix, not a behaviour change.
        self._course_menu = None

    def handle_key_esc(self) -> None:
        if self._visible:
            self.close()

    # --- scene ----------------------------------------------------------
    def _course_system(self) -> Optional[str]:
        """System of the destination currently on the SDK warp button."""
        try:
            import App
            btn = App.SortedRegionMenu_GetWarpButton()
            dest = btn.GetDestination() if btn is not None else None
            if dest:
                return sm.system_id_for_set(str(dest).split(".")[-1])
        except Exception as e:
            dev_mode.log_swallowed("star map course system", e)
        return None

    def _mission_systems(self) -> list:
        """Systems the live SDK Set Course menu currently offers.

        Reconciliation can miss; log rather than swallow, so an absent
        mission reticle is diagnosable instead of mysterious.
        """
        out = []
        for node in getattr(self._course_menu, "_children", []) or []:
            try:
                out.append(sm.system_id_for_set(node.GetLabel()))
            except Exception as e:
                dev_mode.log_swallowed("star map mission system", e)
        return out

    def _rebuild_scene(self) -> None:
        self.scene = star_map.build_scene(
            here_id=self._here_system,
            course_id=self._course_system(),
            mission_ids=self._mission_systems(),
            selected_id=self._selected_system,
            eye=self.cam.camera.eye(),
        )

    # --- warp points ----------------------------------------------------
    def _warp_rows(self) -> tuple:
        sid = self._selected_system
        if sid is None:
            return ([], None)
        catalog = sm.warp_points_for(sid)
        if catalog:
            return ([{"id": wp["id"], "label": wp["label"],
                      "available": wp.get("module") is not None}
                     for wp in catalog], None)
        mod = sm.system_module(sid)
        note = ("No separate destinations in this system — "
                "set course to the system itself." if mod is not None
                else "No course destination available for this system.")
        return ([{"id": sid, "label": sm.display_label(sid),
                  "available": mod is not None}], note)

    def _module_for(self, warp_id) -> Optional[str]:
        sid = self._selected_system
        if sid is None:
            return None
        for wp in sm.warp_points_for(sid):
            if wp["id"] == warp_id:
                return wp.get("module")
        if warp_id == sid:
            return sm.system_module(sid)
        return None

    # --- Panel ----------------------------------------------------------
    def render_payload(self) -> Optional[str]:
        warp_points, warp_note = self._warp_rows()
        labels = (star_map.project_points(self.scene, self.cam, self.rect)
                  if self._visible else [])
        # Nebula names, rendered at deliberately lower emphasis than the
        # system labels (see .sm-label--disc in star_map.css): they are
        # scenery, and must never compete with the stars the map is for.
        disc_labels = (star_map.project_disc_labels(self.scene, self.cam,
                                                    self.rect)
                       if self._visible else [])
        payload = json.dumps({
            "visible": self._visible,
            "selected_system": self._selected_system,
            "targets_open": self._targets_open(),
            "warp_enabled": self._warp_enabled(),
            "warp_label": self._warp_label(),
            "targets_title": (sm.display_label(self._selected_system)
                              if self._targets_open() else ""),
            "here_system": self._here_system,
            "course_system": self._course_system() if self._visible else None,
            "mission_systems": self._mission_systems() if self._visible else [],
            "labels": [{"id": l["id"], "label": l["label"],
                        "x": round(l["x"], 1), "y": round(l["y"], 1),
                        "visible": l["visible"]} for l in labels],
            "disc_labels": [{"label": d["label"],
                             "x": round(d["x"], 1), "y": round(d["y"], 1),
                             "visible": d["visible"]} for d in disc_labels],
            "warp_points": warp_points,
            "warp_note": warp_note,
        })
        if payload == self._last_pushed:
            return None
        self._last_pushed = payload
        return "setStarMapPanel(" + payload + ");"

    def dispatch_event(self, action: str) -> bool:
        if action == "cancel":
            self.close()
            return True
        if action == "warp":
            # Guarded by the same condition that greys the button, so a stale
            # payload or a synthetic event cannot warp without a course.
            if not self._warp_enabled():
                return False
            if self._on_warp_engage is not None:
                import App
                self._on_warp_engage(App.SortedRegionMenu_GetWarpButton())
            self.close()
            return True
        if action == "back":
            # Dismiss the target popup and return to the map. Deliberately
            # separate from "cancel": that closes the whole modal.
            self._selected_system = None
            self._rebuild_scene()
            return True
        if self._targets_open() and action.split(":", 1)[0] in _MAP_ACTIONS:
            # The target popup is MODAL over the map: orbit, zoom and picking
            # are ignored while it is up, so Back is the only way out and a
            # click near the card's edge can never be ambiguous.
            return False
        if action.startswith("select-system:"):
            # Selects only — the camera anchor deliberately does not move.
            self._selected_system = action[len("select-system:"):]
            self._rebuild_scene()
            return True
        if action.startswith("set-course:"):
            module = self._module_for(action[len("set-course:"):])
            if module is None:
                return False
            if self._on_course_set is not None:
                self._on_course_set(module)
            # The modal stays OPEN: the player should see the course line
            # they just plotted and then press Warp. Dismiss the target popup
            # so the map is visible again.
            self._selected_system = None
            self._rebuild_scene()
            return True
        if action.startswith("orbit:"):
            try:
                dx, dy = action[len("orbit:"):].split(",")
                self.cam.orbit(float(dx), float(dy))
            except ValueError as e:
                dev_mode.log_swallowed("star map orbit", e)
                return False
            self._rebuild_scene()
            return True
        if action.startswith("zoom:"):
            try:
                self.cam.zoom(float(action[len("zoom:"):]))
            except ValueError as e:
                dev_mode.log_swallowed("star map zoom", e)
                return False
            self._rebuild_scene()
            return True
        if action.startswith("pick:"):
            try:
                x, y = action[len("pick:"):].split(",")
                hit = star_map.pick_system(float(x), float(y), self.scene,
                                           self.cam, self.rect)
            except ValueError as e:
                dev_mode.log_swallowed("star map pick", e)
                return False
            if hit is not None:
                self._selected_system = hit
                self._rebuild_scene()
            return True
        return False

    def invalidate(self) -> None:
        self._last_pushed = None
