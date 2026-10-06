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
from urllib.parse import unquote

from engine import dev_mode
from engine.appc import sector_model as sm
from engine.systems import descriptions as sysdesc
from engine.ui import star_map
from engine.ui.modal_geometry import (large_modal_content_origin,
                                      large_modal_size)
from engine.ui.panel import Panel

# Most search results listed at once. More than fit beside the map is noise:
# a longer query narrows it.
SEARCH_MAX_RESULTS = 8

# Only used when the TGL is unreachable (headless, or game/ absent). Never the
# normal path: the label comes from the same database the Helm menu reads.
_WARP_FALLBACK = "Warp"

# Map geometry in CEF logical pixels. The modal is the shared large modal
# (engine/ui/modal_geometry.py, `.cp-modal--large`), so its size tracks the
# view; only the header and footer strips are fixed. The map fills the WHOLE
# body BETWEEN them, by construction: #star-map-viewport is `inset: 0` inside
# .sm-body, which is the flex child between .cp-header and .cp-footer.
#
# The map height is DERIVED, never asserted. It was once a hardcoded 520
# against a 478px body, so the map's opaque GL backdrop overran the footer
# strip by 42px. HEADER_H and FOOTER_H are pinned to the real CSS by
# test_the_map_rect_fits_the_modal_body — .cp-header's height in
# configuration_panel.css, .cp-footer's in star_map.css (the shared rule is
# padding-sized, i.e. font-dependent, so the map gives it a fixed height to
# subtract).
HEADER_H = 28
FOOTER_H = 54

# Two-panel layout, at every window size: a system-information panel takes
# the left INFO_FRACTION of the body and the map the rest. Mirrored by the
# `30%` in star_map.css (#star-map-info's width, #star-map-viewport's inset);
# test_star_map_cef_assets pins the agreement. (It switched off below a
# 1024px view until 2026-10-06.)
INFO_FRACTION = 0.3


def rect_for_view(view_w, view_h) -> tuple:
    """Map viewport rect (x, y, w, h) for a CEF logical view of this size.

    The CEF view is NOT a constant: it tracks the host window's size in
    points (host_loop._compute_cef_resize), and the large modal is both sized
    from it (80vw x 80vh) and flex-CENTRED in it. So the rect is recomputed
    from the view every frame (set_view_size), from the one shared rule in
    modal_geometry.

    Chromium lays 80vw out in fractional pixels and may disagree with this
    round() by <=1px, shifting the GL stars up to 1px against the CEF labels.
    That is invisible, and it cannot separate the labels from the hole: the
    labels live INSIDE #star-map-viewport, so they move with the CSS rect
    whatever it resolves to.

    The map is the body's right 1 - INFO_FRACTION, beside the
    system-information panel.

    Clamped at 0 so a view smaller than the modal's floor never yields a
    negative origin (which the GL scissor would reject and picking would
    mis-offset).
    """
    w, h = large_modal_size(view_w, view_h)
    x, y = large_modal_content_origin(view_w, view_h)
    right = x + w
    x += INFO_FRACTION * w            # the info panel's share, on the left
    # Round both EDGES, not the origin and the width separately, so the map
    # always ends exactly where the body does.
    left = max(0, round(x))
    return (left, max(0, round(y + HEADER_H)),
            round(right) - left, round(h - HEADER_H - FOOTER_H))


# The rect at the boot view size (host_loop.py:_CEF_VIEW_W/H start 1280x720).
# Kept as a named constant because it is the panel's own starting rect.
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
        # The system the left-hand info panel describes (wide layout). Opens
        # on the player's own system and follows the last star clicked; unlike
        # _selected_system it is NOT cleared when a course is set, so the
        # panel keeps describing what the player last looked at.
        self._info_system: Optional[str] = None
        self._here_system: Optional[str] = None
        # The player's own set name at open (e.g. "DryDock"): which
        # destination row they are already in.
        self._here_set: Optional[str] = None
        self._last_pushed: Optional[str] = None
        self._show_all_labels = False
        # The search box's text, as last typed (star-map/search:<query>).
        # Results are recomputed from it on render.
        self._search_query = ""
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
        # The player's system is still resolved — for the you-are-here arrow
        # and the info panel — but the camera opens on the middle of the
        # cluster, not on the player.
        self._search_query = ""
        here, _player_pos = star_map.resolve_anchor(set_name)
        self._here_system = here
        self._here_set = set_name
        self._info_system = here
        self.cam = star_map.StarMapCamera(anchor=star_map.cluster_centre())
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
    def _course_module(self) -> Optional[str]:
        """Module on the SDK warp button, or None."""
        try:
            import App
            btn = App.SortedRegionMenu_GetWarpButton()
            dest = btn.GetDestination() if btn is not None else None
            return str(dest) if dest else None
        except Exception as e:
            dev_mode.log_swallowed("star map course module", e)
        return None

    def _course_system(self) -> Optional[str]:
        """System of the destination currently on the SDK warp button."""
        dest = self._course_module()
        return sm.system_id_for_set(dest.split(".")[-1]) if dest else None

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
        """The info panel system's destinations, as (rows, note). The info
        panel lists them, each with a set-course control."""
        sid = self._info_system
        if sid is None:
            return ([], None)
        # Which row, if any, the mission itself asked for. The 3D map marks
        # the SYSTEM; without this the player is told "Vesuvi" and then left
        # to guess which of its regions was meant.
        mission_dest = self._mission_destination()
        course = self._course_module()

        def shaped(rows):
            # Either of BC's two region-level "go here" signals marks the row:
            # the destination the mission plotted for itself, or a pointer
            # arrow aimed at the node. Missions use one or the other, never
            # both — E3M2 plots Vesuvi4, E1M1 arrows Starbase 12.
            return [{"id": r["id"], "label": r["label"],
                     "available": r.get("module") is not None,
                     "mission": bool(r.get("attention")
                                     or (mission_dest is not None
                                         and r.get("module") == mission_dest)),
                     # The course currently on the warp button — set here,
                     # from Helm -> Set Course, or by the mission.
                     "course": (course is not None
                                and r.get("module") == course)}
                    for r in rows]

        # The mission's own offer FIRST: it is authoritative about labels and
        # about regions the offline bake never saw. But it is NOT a gate — a
        # system the mission never mentioned is still somewhere the player may
        # choose to go, so an absent or empty offer falls through to the
        # catalog rather than presenting a dead end.
        offered = self._offered_rows(sid)
        if offered:
            return (self._mark_objective(sid, offered, shaped(offered)), None)

        catalog = sm.warp_points_for(sid)
        if catalog:
            return (self._mark_objective(sid, catalog, shaped(catalog)), None)
        mod = sm.system_module(sid)
        note = ("No separate destinations in this system — "
                "set course to the system itself." if mod is not None
                else "No course destination available for this system.")
        only = [{"id": sid, "label": sm.display_label(sid), "module": mod}]
        return (self._mark_objective(sid, only, shaped(only)), note)

    def _mark_objective(self, sid, source_rows, rows) -> list:
        """Stamp `objective` on the rows that show the objective marker.

        A row the mission names itself (`mission`: a pointer arrow, or the
        destination it plotted) is the objective. When the mission names the
        SYSTEM but no row in it — E1M1 offers only Tau Ceti and points at
        Starbase 12 only later in the tutorial — the objective is inferred:
        the one destination left once the one the player is already in is
        set aside. Inference, not a mission signal (Mark's call, 2026-10-06);
        with zero or several candidates nothing is marked rather than a
        guess.
        """
        named = [r["mission"] for r in rows]
        if not any(named) and sid in self._mission_systems():
            here = (self._here_set or "").lower()
            candidates = [i for i, (src, r) in enumerate(zip(source_rows, rows))
                          if r["available"]
                          and str(src.get("module") or "").split(".")[-1].lower()
                          != here]
            if len(candidates) == 1:
                named[candidates[0]] = True
        for r, obj in zip(rows, named):
            r["objective"] = obj
        return rows

    def _search(self) -> list:
        """Charted systems matching the search box, best first.

        A system matches on its own name or on the name of any destination in
        it — the live menu's labels and the catalog's — so "starbase 12"
        finds Tau Ceti. Case-insensitive substring. Ranked: name starts with
        the query, then name contains it, then a destination does; ties
        alphabetical. `via` names the destination that matched, when it was
        one, so the result can say why Tau Ceti is listed.
        """
        q = self._search_query.strip().lower()
        if not q:
            return []
        hits = []
        for system in star_map._real_systems(sm.load_sector_model()):
            sid = system["id"]
            name = sm.display_label(sid)
            low = name.lower()
            if low.startswith(q):
                rank, via = 0, None
            elif q in low:
                rank, via = 1, None
            else:
                labels = [r.get("label") for r in
                          (self._offered_rows(sid) or [])
                          + sm.warp_points_for(sid)]
                via = next((str(l) for l in labels
                            if l and q in str(l).lower()), None)
                if via is None:
                    continue
                rank = 2
            hits.append((rank, low, {"system": sid, "name": name, "via": via}))
        hits.sort(key=lambda h: (h[0], h[1]))
        return [h[2] for h in hits[:SEARCH_MAX_RESULTS]]

    def _outermost_module(self, sid) -> Optional[str]:
        """The system's outermost region: what a double-click on its star
        sets course to.

        BC's own system default — the region Systems/<X>/<X>.py hands
        CreateSystemMenu, which is the highest-numbered and outermost in every
        multi-region system (Vesuvi6, Alioth8, Itari8). A system with no
        default of its own (Tau Ceti folds Starbase 12 and Dry Dock onto one
        star) takes the last destination it lists.
        """
        mod = sm.system_module(sid)
        if mod is not None:
            return mod
        mods = [r.get("module") for r in (self._offered_rows(sid) or
                                          sm.warp_points_for(sid))]
        mods = [m for m in mods if m is not None]
        return mods[-1] if mods else None

    def _module_for(self, warp_id) -> Optional[str]:
        sid = self._info_system
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

    # --- description ----------------------------------------------------
    def _info(self) -> Optional[dict]:
        """What the wide layout's left panel shows: the described system's
        name, whether the player is in it, and its written description
        (blank halves when it has none). None when there is no system to
        describe — the player is in a set that maps to no charted system."""
        sid = self._info_system
        if not sid:
            return None
        entry = sysdesc.for_system(sid) or {}
        return {"system": sid, "name": sm.display_label(sid),
                "is_here": sid == self._here_system,
                "summary": entry.get("summary", ""),
                "detail": entry.get("detail", "")}

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
            "warp_enabled": self._warp_enabled(),
            "warp_label": self._warp_label(),
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
            # The info panel system's destinations, listed in the panel with
            # a set-course crosshair each (star-map/set-course:<id>).
            "warp_points": warp_points,
            "warp_note": warp_note,
            # The wide layout's left panel. Sent at every width — CSS alone
            # decides whether the panel is shown, so Python needs no second
            # copy of the breakpoint on this path.
            "info": self._info() if self._visible else None,
            # The search box (bottom-right of the map): what was typed and
            # the systems it found.
            "search_query": self._search_query,
            "search_results": self._search() if self._visible else [],
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
        if action.startswith("search:"):
            self._search_query = unquote(action[len("search:"):])
            return True
        if action == "toggle-labels":
            self._show_all_labels = not self._show_all_labels
            return True
        if action.startswith("select-system:"):
            # Selects only — the camera anchor deliberately does not move.
            self._selected_system = action[len("select-system:"):]
            self._info_system = self._selected_system
            self._rebuild_scene()
            return True
        if action.startswith("set-course:"):
            module = self._module_for(action[len("set-course:"):])
            if module is None:
                return False
            if self._on_course_set is not None:
                self._on_course_set(module)
            # The modal stays OPEN: the player should see the course line
            # they just plotted and then press Warp.
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
        if action.startswith("pick-course:"):
            # Double-click on a star: select it (the info panel follows) and
            # set course straight to its outermost region.
            try:
                x, y = action[len("pick-course:"):].split(",")
                hit = star_map.pick_system(float(x), float(y), self.scene,
                                           self.cam, self.rect)
            except ValueError as e:
                dev_mode.log_swallowed("star map pick-course", e)
                return False
            if hit is None:
                return True
            self._selected_system = hit
            self._info_system = hit
            module = self._outermost_module(hit)
            if module is not None and self._on_course_set is not None:
                self._on_course_set(module)
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
                self._info_system = hit
                self._rebuild_scene()
            return True
        return False

    def invalidate(self) -> None:
        self._last_pushed = None
