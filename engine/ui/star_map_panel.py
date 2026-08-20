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

# Map viewport inside the modal, in CEF logical pixels. The modal is 880x560
# (.cp-modal), centred in the 1280x720 view (host_loop.py:_CEF_VIEW_W/H) —
# left = (1280-880)/2 = 200, top = (720-560)/2 = 80. .cp-header is a fixed
# 28px (box-sizing: border-box), so the body starts at y = 80 + 28 = 108.
# The map occupies the left 640x520 of that body: MAP_RECT = (200, 108, 640,
# 520). #star-map-viewport is `position: fixed` at these exact numbers (not
# left to flow) precisely so this constant is the only source of truth —
# kept in sync with css/star_map.css, whose test parses the CSS rule back out
# and asserts it against this tuple.
MAP_RECT = (200, 108, 640, 520)


class StarMapPanel(Panel):
    def __init__(self, on_course_set=None) -> None:
        super().__init__()
        self._on_course_set = on_course_set
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
        payload = json.dumps({
            "visible": self._visible,
            "selected_system": self._selected_system,
            "here_system": self._here_system,
            "course_system": self._course_system() if self._visible else None,
            "mission_systems": self._mission_systems() if self._visible else [],
            "labels": [{"id": l["id"], "label": l["label"],
                        "x": round(l["x"], 1), "y": round(l["y"], 1),
                        "visible": l["visible"]} for l in labels],
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
            self.close()
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
