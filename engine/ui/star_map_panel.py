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

# Shifted RIGHT of centre, deliberately. #tactical-left-column (the HUD, and
# with it the open Helm menu) is left:24 width:224, i.e. x 24..248. A centred
# 880-wide modal starts at x 200, so the menu covered the map's leftmost 48px
# — and the menu has to stay visible, because Set Course is opened FROM it.
# 56 clears 248 with 8px to spare. Mirrored by the CSS calc() offsets, which
# the agreement test checks against this constant.
MODAL_OFFSET_X = 56


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
    return (max(0, round(view_w / 2 - MODAL_W / 2 + MODAL_OFFSET_X)),
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
        self._show_all_labels = False
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
        # Through the SETTER, never self._visible: the setter is what marks
        # the panel due on a flip, and PanelRegistry does not poll a panel
        # that is not visible. See close().
        self.visible = True
        # A transient look-around, not a preference: every opening presents
        # the mission's own shortlist first.
        self._show_all_labels = False
        here, anchor = star_map.resolve_anchor(set_name)
        self._here_system = here
        self.cam = star_map.StarMapCamera(anchor=anchor)
        self._rebuild_scene()

    def close(self) -> None:
        # Through the SETTER. PanelRegistry skips panels that are not visible,
        # which is safe ONLY because the flip to hidden marks the panel due for
        # one more frame — and that marking lives in the setter. Assigning
        # self._visible directly skipped it, so the payload carrying
        # visible:false never went out: ESC killed the GL map (which reads
        # is_open() itself, every frame) and left the CEF labels and footer
        # drawn over the bridge. Cancel escaped it only because dispatching an
        # event marks the panel due as well.
        self.visible = False
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

    def _is_pointed_at(self, node) -> bool:
        """Has a mission aimed BC's pointer arrow at this menu node?

        The third way a mission says "go here", and the only one E1M1 uses for
        Starbase 12: it never names a mission on that node and never pre-sets
        the warp button, it calls MissionLib.ShowPointerArrow on the Set Course
        submenu (E1M1.py:3607-3613). engine.ui.ui_attention already records the
        target's widget id for the crew menu's own highlight; this reads the
        same record rather than inventing a second one.

        Self-clearing: HidePointerArrows empties the set wholesale, so the mark
        goes when the tutorial moves on, with no lifecycle of ours to leak.
        """
        try:
            from engine.appc.tg_ui.widgets import ensure_widget_id
            from engine.ui import ui_attention
            return ensure_widget_id(node) in ui_attention.highlighted_ids()
        except Exception as e:
            dev_mode.log_swallowed("star map pointer arrow", e)
            return False

    def _mission_systems(self) -> list:
        """Systems a mission has actually named as an objective.

        This used to return every system the menu OFFERED, so the blue
        reticle meant "reachable" and tinted most of the map. BC's own marker
        is SortedRegionMenu.SetMissionName — E3M2.py:258 names Vesuvi, and
        E3M2.py:254 clears Starbase 12 in the same breath, which only makes
        sense if the mark is meant to single one out.

        A system with no mission name is simply not marked; there is no
        fallback to the old behaviour, because "mark everything" is the bug.

        Reconciliation can miss; log rather than swallow, so an absent
        mission reticle is diagnosable instead of mysterious.
        """
        out = []
        for node in getattr(self._course_menu, "_children", []) or []:
            try:
                if not (node.GetMissionName() or self._is_pointed_at(node)):
                    continue
                sid = sm.system_id_for_set(node.GetLabel())
                # Several nodes fold onto one map system (Tau Ceti gets both
                # "Dry Dock" and "Starbase 12"); one reticle, listed once.
                if sid not in out:
                    out.append(sid)
            except Exception as e:
                dev_mode.log_swallowed("star map mission system", e)
        if out:
            return out

        # Nothing said it outright. If the mission offers exactly ONE system,
        # that IS where it is sending you — there is nowhere else to go, so
        # saying so cannot mislead, and it needs no new signal to infer from.
        #
        # This carries the openings BC leaves unmarked. E1M1 offers only Tau
        # Ceti (its "Starbase 12" and "Dry Dock" nodes both fold onto it) and
        # raises no objective signal until Picard's warp prod reaches tutorial
        # state 2; E8M1 offers only Starbase 12 until its briefing creates
        # Riha. Both previously showed a map with no objective at all.
        #
        # Deliberately a FALLBACK, never an override: a mission that names a
        # system has said which one, and is believed over an inference drawn
        # from the size of its menu.
        offered = self._offered_systems()
        if offered is not None and len(offered) == 1:
            return list(offered)
        return []

    def _mission_destination(self) -> Optional[str]:
        """Set-module the current mission plotted for itself, if any.

        Latched on the warp button at the moment a mission script calls
        SetDestination (E3M2.py:2124 -> "Systems.Vesuvi.Vesuvi4"), so it
        survives the player browsing other rows in this map.
        """
        try:
            import App
            btn = App.SortedRegionMenu_GetWarpButton()
            if btn is not None:
                return btn.get_mission_destination()
        except Exception as e:
            dev_mode.log_swallowed("star map mission destination", e)
        return None

    def _offered_rows(self, sid) -> Optional[list]:
        """Destinations the live SDK menu offers in system `sid`.

        None when there is no menu at all (QuickBattle) — the caller then
        falls back to the baked catalog. An EMPTY LIST is different and
        meaningful: a menu exists and this system is not in it, i.e. the
        mission does not let you go there.

        Mirrors Systems/Utils.CreateSystemMenuInternal, which is what built
        the tree: one node per system the mission called CreateMenus() for,
        each carrying its regions as children. Several nodes can fold onto one
        map system (Tau Ceti gets both "Dry Dock" and "Starbase 12"), so nodes
        accumulate rather than the first one winning.
        """
        if self._course_menu is None:
            return None
        rows, seen = [], set()
        for node in getattr(self._course_menu, "_children", []) or []:
            try:
                if sm.system_id_for_set(node.GetLabel()) != sid:
                    continue
                children = getattr(node, "_children", []) or []
                # A node with regions offers those; a single-region system
                # (Riha, Starbase 12) offers ITSELF, via its own module.
                for child in children or [node]:
                    mod = child.GetRegionModule()
                    if mod is None or mod in seen:
                        continue
                    seen.add(mod)
                    # An arrow on the node that CONTRIBUTES this row. For a
                    # system with regions that is the region node; for a
                    # single-region system (and each half of the Tau Ceti
                    # fold) it is the system node itself, which is what makes
                    # E1M1's arrow on "Starbase 12" mark that row and not
                    # "Dry Dock" beside it. An arrow on a system that HAS
                    # regions marks the system only — it never said which
                    # region, so neither do we.
                    rows.append({"id": str(mod), "label": child.GetLabel(),
                                 "module": mod,
                                 "attention": self._is_pointed_at(child)})
            except Exception as e:
                dev_mode.log_swallowed("star map offered rows", e)
        return rows

    def _offered_systems(self):
        """System ids the live Set Course menu offers, or None if no menu.

        None is not the empty set: no menu means unconstrained (QuickBattle
        has no Set Course), whereas an empty set would black out the map.
        """
        if self._course_menu is None:
            return None
        out = set()
        for node in getattr(self._course_menu, "_children", []) or []:
            try:
                out.add(sm.system_id_for_set(node.GetLabel()))
            except Exception as e:
                dev_mode.log_swallowed("star map offered system", e)
        return out

    def _rebuild_scene(self) -> None:
        self.scene = star_map.build_scene(
            here_id=self._here_system,
            course_id=self._course_system(),
            mission_ids=self._mission_systems(),
            selected_id=self._selected_system,
            offered_ids=self._offered_systems(),
            eye=self.cam.camera.eye(),
        )

    # --- warp points ----------------------------------------------------
    def _warp_rows(self) -> tuple:
        sid = self._selected_system
        if sid is None:
            return ([], None)
        # Which row, if any, the mission itself asked for. The 3D map marks
        # the SYSTEM; without this the player is told "Vesuvi" and then left
        # to guess which of its regions was meant.
        mission_dest = self._mission_destination()

        def shaped(rows):
            # Either of BC's two region-level "go here" signals marks the row:
            # the destination the mission plotted for itself, or a pointer
            # arrow aimed at the node. Missions use one or the other, never
            # both — E3M2 plots Vesuvi4, E1M1 arrows Starbase 12.
            return [{"id": r["id"], "label": r["label"],
                     "available": r.get("module") is not None,
                     "mission": bool(r.get("attention")
                                     or (mission_dest is not None
                                         and r.get("module") == mission_dest))}
                    for r in rows]

        # The mission's own offer FIRST: it is authoritative about labels and
        # about regions the offline bake never saw. But it is NOT a gate — a
        # system the mission never mentioned is still somewhere the player may
        # choose to go, so an absent or empty offer falls through to the
        # catalog rather than presenting a dead end.
        offered = self._offered_rows(sid)
        if offered:
            return (shaped(offered), None)

        catalog = sm.warp_points_for(sid)
        if catalog:
            return (shaped(catalog), None)
        mod = sm.system_module(sid)
        note = ("No separate destinations in this system — "
                "set course to the system itself." if mod is not None
                else "No course destination available for this system.")
        return (shaped([{"id": sid, "label": sm.display_label(sid),
                         "module": mod}]), note)

    def _module_for(self, warp_id) -> Optional[str]:
        sid = self._selected_system
        if sid is None:
            return None
        # Resolved from the same source the row was listed from, so a row the
        # offline bake never saw is still actionable — and so a catalog row
        # for an unoffered system still resolves (see _warp_rows).
        for r in self._offered_rows(sid) or ():
            if r["id"] == warp_id:
                return r["module"]
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
            # Unlisted systems keep their dot but lose their name, so the map
            # reads as "where this mission will take you" at a glance. The
            # toggle restores the rest; it is offered only when something is
            # actually being withheld, and stays offered while show-all is on
            # so the player can put the map back.
            "show_all_labels": self._show_all_labels,
            "has_hidden_labels": any(not p.get("offered", True)
                                     for p in self.scene["points"]),
            "here_system": self._here_system,
            # Where CEF hangs the you-are-here arrow. Taken from the SAME
            # projection the labels use, so the arrow and the star's name can
            # never disagree about where the star is. None when the player's
            # set maps to no charted system (deep space, an unmapped set) —
            # a marker at the origin would claim a position they don't have.
            "here_marker": next(
                ({"x": round(l["x"], 1), "y": round(l["y"], 1),
                  "visible": l["visible"]}
                 for l in labels if l["id"] == self._here_system), None),
            "course_system": self._course_system() if self._visible else None,
            "mission_systems": self._mission_systems() if self._visible else [],
            "labels": [{"id": l["id"], "label": l["label"],
                        "x": round(l["x"], 1), "y": round(l["y"], 1),
                        "visible": l["visible"],
                        "offered": l["offered"]} for l in labels],
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
        if action == "toggle-labels":
            # Deliberately NOT in _MAP_ACTIONS: it is chrome, not a map
            # gesture, so it keeps working while the target popup is up.
            self._show_all_labels = not self._show_all_labels
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
