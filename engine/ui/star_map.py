"""Star map scene assembly, anchor resolution, camera and picking.

Pure Python — no GL, no CEF. The native starmap pass draws the lists this
module produces, in the order given, so every ordering decision (disc
back-to-front sort, painter's order across primitive kinds) is made and
tested here rather than in C++.

Spec: docs/superpowers/specs/2026-08-20-star-map-set-course-design.md
"""
from __future__ import annotations

import math
from typing import Iterable, Optional, Tuple

from engine.appc import sector_model as sm
from engine.ui.ship_property_viewer import OrbitCamera, project

Vec3 = Tuple[float, float, float]

# Bracket reticle marks — reserved for a LIVE relationship to the player.
MARK_NONE = 0
MARK_HERE = 1       # you are here
MARK_COURSE = 2     # course currently set
MARK_MISSION = 3    # offered by the live SDK Set Course menu

# --- palette -------------------------------------------------------------
# Recovered from the stellar-cartography proof of concept (poc/, throwaway),
# whose look was drawn from the Star Trek films' chart displays: warm amber
# systems, deep-blue grid, and nebulae as CHARTED REGIONS — a faint flat fill
# with a crisp bright border — rather than soft clouds.
#
# Every value here is a Python constant precisely so a live tuning pass costs
# a page refresh, not a rebuild. The pass interprets none of them.
STAR_COLOR = (1.000, 0.706, 0.329)      # POC #ffb454 — halo tint; core is white
GRID_COLOR = (0.086, 0.204, 0.361)      # POC 0x16345c
DROP_COLOR = (0.114, 0.227, 0.388)      # POC 0x1d3a63

# Nebulae are scenery and must not compete with the stars. The POC got that
# from CONSTRUCTION rather than opacity alone: a faint interior with a defined
# edge reads as "a region is here" without drowning the stars inside it. The
# fill is deliberately heavier than the POC's 0.22 — Mark's call, 2026-08-20;
# trim it here if it crowds the stars.
NEBULA_OPACITY = 0.5          # flat interior fill
NEBULA_BORDER_OPACITY = 0.9   # crisp boundary stroke
NEBULA_HATCH_OPACITY = 0.30   # diagonal bands inside the boundary

# ONE colour for every nebula, deliberately overriding the per-nebula tint in
# sector_model.json. Those tints are the in-scene backdrop colours and several
# are fully saturated primaries — the MRegion entries are #1fbf1f green,
# #bfbf1f yellow and #1f1fbf blue — which on a chart read as alarm states
# rather than as terrain. Belaruz's muted blue-violet is the one that sat
# right, so it governs. The model keeps its own colours untouched: the
# map-driven starsphere renders from the same file and does want them.
NEBULA_COLOR = (0.3922, 0.3882, 0.5725)  # Belaruz #646392

# Star clouds are POC decoration: a small three-star glyph at a FIXED SCREEN
# size, not a world-scaled volume. Drawn from the model's `size` they became
# huge soft blobs that swallowed whole regions of the map.
STARCLOUD_COLOR = (1.000, 0.894, 0.627)  # POC #ffe4a0
STARCLOUD_SIZE_PX = 18.0
STARCLOUD_OPACITY = 0.85

# Faint ground grid; drop-lines fall to this plane.
GRID_Z = 0.0
GRID_HALF_EXTENT = 400.0
GRID_STEP = 50.0
COURSE_COLOR = (0.475, 0.949, 0.690)    # POC #79f2b0

# Bracket presentation. These live here, beside the MARK_* values they key off,
# because this module OWNS the mark enum: if the pass chose colours from `mark`
# itself, renumbering MARK_* here would silently recolour every reticle. The
# pass now receives a colour per bracket and never interprets `mark` at all.
MARK_HERE_COLOR    = (0.337, 0.902, 1.000)  # POC #56e6ff — the brightest mark
MARK_COURSE_COLOR  = COURSE_COLOR           # same green as the plotted course
MARK_MISSION_COLOR = (1.000, 0.706, 0.329)  # POC #ffb454, its default bracket

# Deliberately no `.get(mark, <grey>)` fallback anywhere: an unmapped mark must
# raise here, in Python, next to the enum — not render as a plausible colour.
_MARK_COLORS = {
    MARK_HERE:    MARK_HERE_COLOR,
    MARK_COURSE:  MARK_COURSE_COLOR,
    MARK_MISSION: MARK_MISSION_COLOR,
}

# On-screen marker sizes, in logical pixels before the renderer's
# device-scale-factor. Here rather than as C++ literals so tuning them after a
# live run costs an edit, not a rebuild.
BRACKET_SIZE_PX       = 20.0
STAR_SIZE_PX          = 4.0
STAR_SELECTED_SIZE_PX = 7.2


def _real_systems(model) -> list:
    return [s for s in model.get("systems", []) if sm.is_real_system(s["id"])]


def _chart_nebulae(model) -> list:
    """Nebulae worth charting: the MRegion* entries are multiplayer-map
    scaffolding, the same family as the `multi*` systems `is_real_system`
    already drops, and they are not places a player can set course to.

    Filtered HERE rather than in sector_model because this is a chart
    decision, not a fact about the data: the map-driven starsphere renders
    from the same nebula records and does want them when the player is
    actually standing in a multiplayer set. Matching on the name mirrors
    `is_real_system`'s own prefix test — the baked records carry no
    multiplayer flag to key off.
    """
    return [n for n in model.get("nebulae", [])
            if not str(n.get("name") or "").lower().startswith("mregion")]


def _centroid(systems) -> Vec3:
    if not systems:
        return (0.0, 0.0, 0.0)
    n = float(len(systems))
    return (sum(s["position"][0] for s in systems) / n,
            sum(s["position"][1] for s in systems) / n,
            sum(s["position"][2] for s in systems) / n)


def resolve_anchor(set_name, model=None) -> Tuple[Optional[str], Vec3]:
    """Resolve the camera anchor from the player's set name.

    Returns (system_id, position). A None id means the set could not be
    matched to a mapped system — Deep Space, a multiplayer set, or anything
    unmapped. Callers must then omit the "you are here" reticle: a misplaced
    one on a nav map is worse than none.
    """
    model = model if model is not None else sm.load_sector_model()
    systems = _real_systems(model)
    if set_name is not None:
        sysid = sm.system_id_for_set(set_name)
        for s in systems:
            if s["id"] == sysid:
                return (s["id"], tuple(float(c) for c in s["position"]))
    return (None, _centroid(systems))


def _grid_lines() -> list:
    out = []
    n = int(GRID_HALF_EXTENT / GRID_STEP)
    for i in range(-n, n + 1):
        t = i * GRID_STEP
        out.append({"kind": "grid", "id": None, "color": GRID_COLOR,
                    "a": (-GRID_HALF_EXTENT, t, GRID_Z),
                    "b": (GRID_HALF_EXTENT, t, GRID_Z)})
        out.append({"kind": "grid", "id": None, "color": GRID_COLOR,
                    "a": (t, -GRID_HALF_EXTENT, GRID_Z),
                    "b": (t, GRID_HALF_EXTENT, GRID_Z)})
    return out


def build_scene(*, model=None, here_id=None, course_id=None,
                mission_ids: Iterable[str] = (), selected_id=None,
                eye: Vec3 = (0.0, 0.0, 0.0)) -> dict:
    """Assemble the draw-ordered scene.

    Painter's order across kinds is discs -> lines -> points -> brackets, so
    star markers are NEVER occluded by nebulae regardless of depth. The pass
    draws with depth test off and honours this order literally.
    """
    model = model if model is not None else sm.load_sector_model()
    systems = _real_systems(model)
    by_id = {s["id"]: tuple(float(c) for c in s["position"]) for s in systems}
    mission = {m for m in mission_ids if m in by_id}

    # --- discs (nebula regions), back-to-front ------------------------
    # Star clouds are NOT discs any more: they are screen-scaled glyphs, so
    # they neither sort with these nor take a world radius.
    discs = []
    for neb in _chart_nebulae(model):
        pos = tuple(float(c) for c in neb["position"])
        # `or ""` not `.get("name", "")`: the source map can carry an explicit
        # "name": null, which the default form passes straight through — and a
        # None reaching the JS renders as the literal string "null" over the
        # map. An empty label is skipped by project_disc_labels.
        discs.append({"kind": "nebula", "label": neb.get("name") or "",
                      "position": pos, "radius": float(neb["radius"]),
                      "color": NEBULA_COLOR,
                      "opacity": NEBULA_OPACITY,
                      "border_opacity": NEBULA_BORDER_OPACITY,
                      "_camera_distance": _distance(pos, eye)})
    discs.sort(key=lambda d: d["_camera_distance"], reverse=True)

    # --- star clouds: fixed-size decoration, never selectable ---------
    starclouds = [{"position": tuple(float(c) for c in gx["position"]),
                   "color": STARCLOUD_COLOR, "size_px": STARCLOUD_SIZE_PX,
                   "opacity": STARCLOUD_OPACITY}
                  for gx in model.get("starclouds", [])]

    # --- lines: faint grid, drop-lines for reticled systems, course ---
    reticled = {}
    if here_id in by_id:
        reticled[here_id] = MARK_HERE
    if course_id in by_id:
        reticled[course_id] = MARK_COURSE
    for m in mission:
        reticled.setdefault(m, MARK_MISSION)

    lines = _grid_lines()
    for sid in reticled:
        p = by_id[sid]
        lines.append({"kind": "drop", "id": sid, "color": DROP_COLOR,
                      "a": p, "b": (p[0], p[1], GRID_Z)})
    if here_id in by_id and course_id in by_id and here_id != course_id:
        lines.append({"kind": "course", "id": course_id, "color": COURSE_COLOR,
                      "a": by_id[here_id], "b": by_id[course_id]})

    # --- points: every real system as a bare dot ----------------------
    # size_px is resolved HERE, not from `selected` in the pass, for the same
    # reason bracket colour is: `selected` is this module's semantics.
    points = [{"id": s["id"], "position": by_id[s["id"]],
               "label": sm.display_label(s["id"]), "color": STAR_COLOR,
               "selected": s["id"] == selected_id,
               "size_px": (STAR_SELECTED_SIZE_PX if s["id"] == selected_id
                           else STAR_SIZE_PX)}
              for s in systems]

    # --- brackets: ONLY live relationships ----------------------------
    brackets = [{"id": sid, "position": by_id[sid], "mark": mark,
                 "color": _MARK_COLORS[mark], "size_px": BRACKET_SIZE_PX}
                for sid, mark in reticled.items()]

    return {"discs": discs, "lines": lines, "points": points,
            "brackets": brackets, "starclouds": starclouds}


def _distance(a: Vec3, b: Vec3) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


# ---------------------------------------------------------------------------
# Camera — FIXED anchor. Orbit and zoom only.
# ---------------------------------------------------------------------------

PICK_RADIUS_PT = 12.0
MIN_DISTANCE = 40.0
MAX_DISTANCE = 2000.0
DEFAULT_DISTANCE = 600.0
ZOOM_STEP = 1.12
_MAX_PITCH = math.radians(89.0)


class StarMapCamera:
    """Orbits the player's current system. The anchor NEVER moves.

    Clicking a star selects it; it does not re-centre the view. With a fixed
    anchor every on-screen position is read relative to the player, which is
    the whole job of a nav map — re-centring destroys that, because after one
    click the centre no longer means anything. There is deliberately no
    set_anchor/focus/look_at: anchor-moving is absent, not deferred.
    """

    def __init__(self, anchor: Vec3, distance: float = DEFAULT_DISTANCE):
        self._anchor = tuple(float(c) for c in anchor)
        self.camera = OrbitCamera(target=self._anchor, distance=distance,
                                  yaw=0.0, pitch=math.radians(25.0))

    @property
    def anchor(self) -> Vec3:
        return self._anchor

    def orbit(self, dyaw: float, dpitch: float) -> None:
        self.camera.yaw += dyaw
        self.camera.pitch = max(-_MAX_PITCH,
                                min(_MAX_PITCH, self.camera.pitch + dpitch))

    def zoom(self, steps: float) -> None:
        d = self.camera.distance * (ZOOM_STEP ** steps)
        self.camera.distance = max(MIN_DISTANCE, min(MAX_DISTANCE, d))


def project_points(scene: dict, cam: StarMapCamera, rect) -> list:
    """Project system dots to RECT-LOCAL pixels (top-left origin).

    Rect-local, not screen-absolute: CEF positions the labels inside the map
    element, so absolute coordinates would offset every label by the modal's
    own position.
    """
    _x, _y, w, h = rect
    out = []
    for p in scene["points"]:
        sx, sy, _depth, visible = project(p["position"], cam.camera, (w, h))
        inside = visible and 0.0 <= sx <= w and 0.0 <= sy <= h
        out.append({"id": p["id"], "label": p["label"],
                    "x": sx, "y": sy, "visible": bool(inside)})
    return out


def project_disc_labels(scene: dict, cam: StarMapCamera, rect) -> list:
    """Project labelled disc CENTRES to RECT-LOCAL pixels, as project_points.

    Nebulae are the only labelled discs today (star clouds are baked without a
    name), and they are SCENERY: the caller renders these at deliberately
    lower emphasis than the system labels, which are what the map is for.

    Discs with an empty label are skipped rather than emitted blank — an empty
    label div is an invisible click-blocking rectangle over the map, and a
    None would reach the JS as the string "null".

    Deliberately no `id`: nothing picks a nebula, so handing the UI an id it
    could hang a click on would misrepresent the interaction model.
    """
    _x, _y, w, h = rect
    out = []
    for d in scene["discs"]:
        if not d.get("label"):
            continue
        sx, sy, _depth, visible = project(d["position"], cam.camera, (w, h))
        inside = visible and 0.0 <= sx <= w and 0.0 <= sy <= h
        out.append({"label": d["label"], "x": sx, "y": sy,
                    "visible": bool(inside)})
    return out


def pick_system(cursor_x: float, cursor_y: float, scene: dict,
                cam: StarMapCamera, rect) -> Optional[str]:
    """Nearest system within PICK_RADIUS_PT of the cursor, or None.

    Cursor is in CEF-VIEW pixels; rect is the map's (x, y, w, h) in the same
    space. Clicks outside the rect always miss, so chrome and the warp-point
    list never select a star behind them.
    """
    rx, ry, w, h = rect
    if not (rx <= cursor_x <= rx + w and ry <= cursor_y <= ry + h):
        return None
    local_x, local_y = cursor_x - rx, cursor_y - ry
    best_id, best_d2 = None, PICK_RADIUS_PT ** 2
    for p in project_points(scene, cam, rect):
        if not p["visible"]:
            continue
        d2 = (p["x"] - local_x) ** 2 + (p["y"] - local_y) ** 2
        if d2 <= best_d2:
            best_id, best_d2 = p["id"], d2
    return best_id
