"""SettingCoursePanel — two-level Set Course menu.

Left column lists every galaxy system (from sector_model); selecting one
reveals its warp points (from the baked catalog) in the right column. Clicking
a warp point SETS THE COURSE — it hands the destination set-module to the host
(which records it on the SDK warp button) and closes the popup. The player then
engages the warp from the original SDK Helm "Warp" button. The popup never
warps directly (Stage 1 routes the actual warp through the helm warp button →
the warp spine).

Systems and warp targets the running game currently has in its live SDK Set
Course menu are marked active (bold).

Spec: docs/superpowers/specs/2026-06-21-set-course-two-level-menu-design.md
"""
from __future__ import annotations

import json
from typing import Optional

from engine.appc import sector_model as sm
from engine.ui.panel import Panel


class SettingCoursePanel(Panel):
    def __init__(self, on_course_set=None) -> None:
        super().__init__()
        # Injected by host_loop: records the chosen destination set-module on
        # the SDK warp button (sets the course). None -> selection is a silent
        # no-op (keeps headless construction / existing tests working).
        self._on_course_set = on_course_set
        self._visible = False
        self._course_menu = None
        self._selected_system: Optional[str] = None
        self._last_pushed: Optional[str] = None
        self._systems = [
            s["id"] for s in sm.load_sector_model().get("systems", [])
            if sm.is_real_system(s["id"])
        ]
        self._systems.sort(key=sm.display_label)

    @property
    def name(self) -> str:
        return "setting-course"

    def is_open(self) -> bool:
        return self._visible

    def open(self, course_menu=None) -> None:
        self._course_menu = course_menu
        self._selected_system = None
        self._visible = True

    def close(self) -> None:
        self._visible = False

    def handle_key_esc(self) -> None:
        if self._visible:
            self.close()

    # --- live-menu overlay -------------------------------------------------
    def _active_system_ids(self) -> set:
        out = set()
        for node in getattr(self._course_menu, "_children", []) or []:
            try:
                out.add(sm.system_id_for_set(node.GetLabel()))
            except Exception:
                pass
        return out

    def _active_warp_labels(self, system_id) -> set:
        for node in getattr(self._course_menu, "_children", []) or []:
            try:
                if sm.system_id_for_set(node.GetLabel()) == system_id:
                    return {c.GetLabel() for c in getattr(node, "_children", [])}
            except Exception:
                pass
        return set()

    def _module_for(self, warp_id) -> Optional[str]:
        """Destination set-module for a warp-point id (or the empty-system
        self-row, whose id equals the system id), or None if unavailable."""
        sid = self._selected_system
        if sid is None:
            return None
        for wp in sm.warp_points_for(sid):
            if wp["id"] == warp_id:
                return wp.get("module")
        if warp_id == sid:
            return sm.system_module(sid)
        return None

    def render_payload(self) -> Optional[str]:
        active_systems = self._active_system_ids()
        systems = [{"id": sid, "label": sm.display_label(sid),
                    "active": sid in active_systems}
                   for sid in self._systems]
        warp_points = []
        warp_note = None
        if self._selected_system is not None:
            sid = self._selected_system
            catalog = sm.warp_points_for(sid)
            if catalog:
                active_warps = self._active_warp_labels(sid)
                for wp in catalog:
                    warp_points.append({
                        "id": wp["id"], "label": wp["label"],
                        "active": wp["label"] in active_warps,
                        "available": wp.get("module") is not None,
                    })
            else:
                # Systems with no sub-destinations (single-region systems like
                # Riha) or galaxy-map backdrops not registered in the SDK menu
                # (Deep Space, Tau Ceti): the system itself is the set-course
                # target — if it has a loadable set module.
                sys_module = sm.system_module(sid)
                warp_points.append({
                    "id": sid, "label": sm.display_label(sid),
                    "active": sid in active_systems,
                    "available": sys_module is not None,
                })
                warp_note = (
                    "No separate destinations in this system — "
                    "set course to the system itself."
                    if sys_module is not None else
                    "No course destination available for this system."
                )
        payload = json.dumps({
            "visible": self._visible,
            "selected_system": self._selected_system,
            "systems": systems if self._visible else [],
            "warp_points": warp_points,
            "warp_note": warp_note,
        })
        if payload == self._last_pushed:
            return None
        self._last_pushed = payload
        return "setSettingCoursePanel(" + payload + ");"

    def dispatch_event(self, action: str) -> bool:
        if action == "cancel":
            self.close()
            return True
        if action.startswith("select-system:"):
            self._selected_system = action[len("select-system:"):]
            return True
        if action.startswith("set-course:"):
            warp_id = action[len("set-course:"):]
            module = self._module_for(warp_id)
            if module is None:
                # Unavailable destination (e.g. a galaxy backdrop with no set
                # module) — leave the popup open; the note explains why.
                return False
            if self._on_course_set is not None:
                self._on_course_set(module)
            self.close()
            return True
        return False

    def invalidate(self) -> None:
        self._last_pushed = None
