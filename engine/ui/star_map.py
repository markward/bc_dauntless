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
# Deliberately the SAME constant as the nebulae, not a copy of its value: a
# star cloud is terrain like a nebula is, and reads as part of the same layer
# rather than as a third thing competing with the amber systems. Referencing
# it means a future nebula retune carries the clusters with it instead of
# silently leaving them behind. (Was the POC's amber #ffe4a0.)
STARCLOUD_COLOR = NEBULA_COLOR
# The glyph holds three sub-stars at 0.40/0.25/0.27 of its half-size, so at
# the old 18 the largest was under 4px across and read as a smudge.
STARCLOUD_SIZE_PX = 32.0
STARCLOUD_OPACITY = 0.85

# Faint reference plane; drop-lines fall to it.
#
# DERIVED from where the systems actually are, not fixed around the world
# origin. The sector layout comes from the POC's force-directed relaxation,
# which had no reason to settle on the origin and did not: the charted systems
# centre near (150, 32) and span ~180 x ~290, so a plane centred on (0, 0) at
# +/-400 sat off to one side and was several times too large.
GRID_DIVISIONS = 16       # lines per axis; the step follows the extent
GRID_MARGIN = 1.15        # reach a little past the outermost system
GRID_FLOOR_DROP = 20.0    # sit this far below the LOWEST system, so every
                          # drop-line falls downward onto the plane
# Fallbacks for an empty model only — never the normal path.
GRID_Z = 0.0
GRID_HALF_EXTENT = 400.0
GRID_STEP = 50.0
COURSE_COLOR = (1.000, 0.612, 0.000)    # #ff9c00

# Bracket presentation. These live here, beside the MARK_* values they key off,
# because this module OWNS the mark enum: if the pass chose colours from `mark`
# itself, renumbering MARK_* here would silently recolour every reticle. The
# pass now receives a colour per bracket and never interprets `mark` at all.
MARK_HERE_COLOR    = (0.698, 0.518, 0.322)  # #b28452
MARK_COURSE_COLOR  = COURSE_COLOR           # #ff9c00, as the plotted course
# Blue against three warm marks, because this is where the mission is sending
# you: it has to separate from the field it sits in rather than blend with it.
MARK_MISSION_COLOR = (0.200, 0.600, 1.000)  # #3399ff

# Brightness multiplier for a system the mission does not offer a course to.
# BC's Set Course menu listed ONLY the systems the mission built (E3M2 creates
# two of the 34 charted), so every entry the player saw was actionable. The map
# keeps drawing the whole sector for spatial context, and says "not this one"
# by dimming rather than by hiding.
#
# Expressed as colour, not alpha: StarMapPoint carries no alpha channel, and
# against the map's dark backdrop half-brightness reads the same as half-opacity
# without a native change and a rebuild.
INERT_DIM = 0.5

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
# A reticle has to ENCLOSE the star it marks, with air between the legs and
# the halo. At 20.0 it was the same width as the star dot after those grew 5x,
# so the corners sat on the star's edge. 40 still clears the 36px selected
# star. Size only — leg thickness is `thick` in starmap.frag.
BRACKET_SIZE_PX       = 40.0
# 5x the original 4.0 / 7.2 (Mark, 2026-08-20). Both scale together so the
# selected star keeps its 1.8x emphasis — raising only the base would have
# quietly flattened the difference to nothing.
STAR_SIZE_PX          = 20.0
STAR_SELECTED_SIZE_PX = 36.0


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


def grid_bounds(systems) -> tuple:
    """(centre_x, centre_y, half_extent, floor_z) for the reference plane.

    Framed on the BOUNDING BOX rather than the centroid: the centroid drifts
    toward whichever region is densest, which would leave the sparse side of
    the chart hanging off the plane.

    The floor sits below the lowest system rather than at z=0. Systems range
    roughly -61..+148, so a plane at zero left some of them underneath the
    floor their own drop-lines fall to.
    """
    if not systems:
        return (0.0, 0.0, GRID_HALF_EXTENT, GRID_Z)
    xs = [s["position"][0] for s in systems]
    ys = [s["position"][1] for s in systems]
    zs = [s["position"][2] for s in systems]
    cx, cy = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
    # One half-extent for both axes keeps the cells square; an axis-wise fit
    # would stretch them into rectangles.
    half = max(max(xs) - min(xs), max(ys) - min(ys)) / 2.0 * GRID_MARGIN
    return (cx, cy, half or GRID_HALF_EXTENT, min(zs) - GRID_FLOOR_DROP)


def _grid_lines(systems) -> list:
    cx, cy, half, z = grid_bounds(systems)
    step = (half * 2.0) / GRID_DIVISIONS
    out = []
    for i in range(GRID_DIVISIONS + 1):
        t = -half + i * step
        out.append({"kind": "grid", "id": None, "color": GRID_COLOR,
                    "a": (cx - half, cy + t, z),
                    "b": (cx + half, cy + t, z)})
        out.append({"kind": "grid", "id": None, "color": GRID_COLOR,
                    "a": (cx + t, cy - half, z),
                    "b": (cx + t, cy + half, z)})
    return out


def build_scene(*, model=None, here_id=None, course_id=None,
                mission_ids: Iterable[str] = (), selected_id=None,
                offered_ids=None, eye: Vec3 = (0.0, 0.0, 0.0)) -> dict:
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
    # One system can hold several states at once — you can set a course
    # within the system you are already in, and most systems have more than
    # one region — but it gets exactly ONE bracket. Precedence is
    # COURSE > MISSION > HERE (Mark, 2026-08-20).
    #
    # Applied WEAKEST FIRST so a stronger mark overwrites a weaker one. The
    # order of these three lines IS the precedence, which is why it is stated
    # above rather than left to be inferred: it was previously incidental —
    # course beat here only by being the second assignment, and mission lost
    # to both through a `setdefault` — and nothing tested any collision.
    reticled = {}
    for sid, mark in ([(here_id, MARK_HERE)]
                      + [(m, MARK_MISSION) for m in mission]
                      + [(course_id, MARK_COURSE)]):
        if sid in by_id:
            reticled[sid] = mark

    _floor_z = grid_bounds(systems)[3]
    lines = _grid_lines(systems)
    for sid in reticled:
        p = by_id[sid]
        lines.append({"kind": "drop", "id": sid, "color": DROP_COLOR,
                      "a": p, "b": (p[0], p[1], _floor_z)})
    if here_id in by_id and course_id in by_id and here_id != course_id:
        lines.append({"kind": "course", "id": course_id, "color": COURSE_COLOR,
                      "a": by_id[here_id], "b": by_id[course_id]})

    # --- points: every real system as a bare dot ----------------------
    # size_px is resolved HERE, not from `selected` in the pass, for the same
    # reason bracket colour is: `selected` is this module's semantics.
    # `offered` is which systems the mission will actually plot a course to.
    # None means UNCONSTRAINED (no Set Course menu attached, e.g. QuickBattle)
    # and must not be confused with an empty set, which means "the mission
    # offers nothing" — the difference between a free map and a dead one.
    #
    # A system carrying a live relationship (here / course / mission) is NEVER
    # dimmed, whatever the offer says: you can sit in a system this mission
    # plots no course back to, and losing the you-are-here star to say "not a
    # destination" costs more than it tells.
    #
    # An EMPTY offer constrains nothing. Hiding names only means anything as a
    # contrast — "these, not those" — and with no "these" it degrades to a
    # nameless star field, strictly worse than the unfiltered map. So `None`
    # (no menu) and an empty set (a menu offering nothing) agree here, even
    # though _offered_systems keeps them distinct for its own purposes.
    constrained = bool(offered_ids)
    points = []
    for s in systems:
        sid = s["id"]
        offered = (not constrained
                   or sid in offered_ids
                   # You must always be able to see where you are, whatever
                   # the mission offers. Stated as its own clause: it also
                   # falls out of `reticled` below, but that is an
                   # implementation detail and this is a rule.
                   or sid == here_id
                   or sid in reticled)
        color = (STAR_COLOR if offered
                 else tuple(c * INERT_DIM for c in STAR_COLOR))
        points.append({"id": sid, "position": by_id[sid],
                       "label": sm.display_label(sid), "color": color,
                       "selected": sid == selected_id, "offered": offered,
                       "size_px": (STAR_SELECTED_SIZE_PX if sid == selected_id
                                   else STAR_SIZE_PX)})

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
DEFAULT_DISTANCE = 400.0   # was 600: 1.5x magnification, so the
                           # whole sector no longer fits on first open
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
                    "x": sx, "y": sy, "visible": bool(inside),
                    "offered": bool(p.get("offered", True))})
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
        # Every charted star stays pickable, offered or not. The offer decides
        # EMPHASIS — whether the name is drawn — never access: the player may
        # want somewhere the current mission has no opinion about, and a star
        # that silently swallows clicks is indistinguishable from a broken one.
        if not p["visible"]:
            continue
        d2 = (p["x"] - local_x) ** 2 + (p["y"] - local_y) ** 2
        if d2 <= best_d2:
            best_id, best_d2 = p["id"], d2
    return best_id
