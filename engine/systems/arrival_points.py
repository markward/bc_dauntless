"""Warp arrival points moved off BC's default, per region set.

BC's default warp arrival is the destination's "Player Start". In DryDock that
point is the origin, one unit from "DryDock Start", where the Dry Dock home
station stands, so every default warp into the region arrived inside the dock
(Mark, live 2026-10-26). An entry here adds a waypoint to the region, offset
from "Player Start" in its own frame and facing the same way, and the player's
arrival (warp._PlacePlayerAction, dash.start_set_course) takes it instead of
the default. A placement a mission linked (MissionLib.LinkMenuToPlacement) is
never touched: only the default is swapped.

The point is derived from the SDK's "Player Start" when the region is built
(region_hooks), so no BC coordinate is stored here, only the offset.
"""
from __future__ import annotations

from engine.appc.tg_ui.st_widgets import DEFAULT_ARRIVAL_PLACEMENT

NAME = "Dauntless Arrival"

# set name -> (forward GU, left GU) in "Player Start"'s own frame
# (Mark, 2026-10-26: "20GU forward and 30GU left just for that system").
OFFSETS = {"DryDock": (20.0, 30.0)}


def add_for_set(pSet, set_name: str) -> None:
    """Add the set's moved arrival point, if it has one and does not yet."""
    offset = OFFSETS.get(set_name)
    if offset is None or pSet.GetObject(NAME) is not None:
        return
    import App
    base = App.Waypoint_Cast(pSet.GetObject(DEFAULT_ARRIVAL_PLACEMENT))
    if base is None:
        return
    forward_gu, left_gu = offset
    loc = base.GetWorldLocation()
    rot = base.GetWorldRotation()
    fwd, right, up = rot.GetCol(1), rot.GetCol(0), rot.GetCol(2)
    wp = App.Waypoint_Create(NAME, set_name, None)
    if pSet.GetObject(NAME) is not wp:
        pSet.AddObjectToSet(wp, NAME)
    wp.SetStatic(1)
    wp.SetNavPoint(0)
    wp.SetTranslateXYZ(loc.x + forward_gu * fwd.x - left_gu * right.x,
                       loc.y + forward_gu * fwd.y - left_gu * right.y,
                       loc.z + forward_gu * fwd.z - left_gu * right.z)
    wp.AlignToVectors(fwd, up)
    wp.Update(0)


def placement_in(pSet, placement: str) -> str:
    """The placement to arrive at in ``pSet``: the moved point when the
    course carries the default and the set holds one, else ``placement``."""
    if placement == DEFAULT_ARRIVAL_PLACEMENT and pSet is not None \
            and pSet.GetObject(NAME) is not None:
        return NAME
    return placement
