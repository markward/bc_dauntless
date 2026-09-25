"""tools/systems/yardstick.py <System> <Region> [<Region> ...]

What Mark should see, printed before he flies it.

The first named region is where the player is created (a Galaxy at that
region's "Player Start" -- the same starting condition as the "System
Preview" dev mission, engine.dev_missions.system_preview), and
engine.systems.system_loader.ensure_loaded() then brings up every other
region of the system, mapped, exactly as a live boot does on the first
tick. Each later region argument moves the SAME player to ITS OWN
"Player Start" and reports from there -- a Set-Course stop, without flying
it.

For each named region, in order, prints one line per body in
celestial.draw_list(that region) -- name, bearing (port/starboard degrees
and elevation, relative to the player's own heading there), range to centre
and to surface (GU and km), and apparent angular size -- plus the one Sun
that region's own _aggregate_suns() sees.

Thin by design: the geometry comes from celestial.draw_list, frames and
engine.units; this module only turns vectors into a report.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _bearing_elevation(delta, right, forward, up):
    """(bearing_deg, elevation_deg) of `delta` relative to a heading whose
    axes are `right`/`forward`/`up` -- all (x, y, z) tuples.

    Bearing is signed around the up axis, in the horizontal plane spanned by
    forward/right: positive is STARBOARD, negative is PORT, 0 is dead ahead,
    +-180 is dead astern. Elevation is signed above/below that plane:
    positive is UP."""
    def dot(a, b):
        return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
    fwd_c = dot(delta, forward)
    right_c = dot(delta, right)
    up_c = dot(delta, up)
    bearing = math.degrees(math.atan2(right_c, fwd_c))
    horiz = math.hypot(fwd_c, right_c)
    elevation = math.degrees(math.atan2(up_c, horiz))
    return bearing, elevation


def _apparent_size_deg(radius_gu: float, range_gu: float) -> float:
    if range_gu <= 0.0:
        return 180.0
    ratio = min(1.0, radius_gu / range_gu)
    return math.degrees(2.0 * math.asin(ratio))


def _format_bearing(bearing_deg: float) -> str:
    side = "stbd" if bearing_deg >= 0.0 else "port"
    return f"{abs(bearing_deg):6.2f} deg {side}"


def _report_row(name, position, radius_gu, player_pos, right, forward, up,
                 from_units):
    delta = tuple(p - o for p, o in zip(position, player_pos))
    range_gu = math.sqrt(sum(d * d for d in delta))
    bearing, elevation = _bearing_elevation(delta, right, forward, up)
    surface_gu = range_gu - radius_gu
    size_deg = _apparent_size_deg(radius_gu, range_gu)
    print(
        f"  {name:<12s}  bearing {_format_bearing(bearing):>15s}"
        f"  elev {elevation:7.2f} deg"
        f"  range {range_gu:12.1f} gu ({range_gu * from_units.GU_TO_KM:10.1f} km)"
        f"  surface {surface_gu:12.1f} gu ({surface_gu * from_units.GU_TO_KM:10.1f} km)"
        f"  size {size_deg:8.4f} deg"
    )


def _load_region(system: str, region: str):
    import App
    import importlib
    pSet = App.g_kSetManager.GetSet(region)
    if pSet is not None:
        return pSet
    qual = f"Systems.{system}.{region}"
    sys.modules.pop(qual, None)
    importlib.import_module(qual).Initialize()
    pSet = App.g_kSetManager.GetSet(region)
    assert pSet is not None, f"{qual}.Initialize() registered no set {region!r}"
    return pSet


def _place_player_in(player, pSet):
    for s in list(_all_sets()):
        if s.GetObject("player") is player:
            s.RemoveObjectFromSet("player")
    pSet.AddObjectToSet(player, "player")
    player.PlaceObjectByName("Player Start")


def _all_sets():
    import App
    return list(App.g_kSetManager._sets.values())


def _print_station(system, region, player, engine_units):
    import App
    from engine.systems import celestial, frames

    App.g_kSetManager.MakeRenderedSet(region)
    view = frames.viewing_set()
    assert view is not None and view.GetName() == region

    loc = player.GetWorldLocation()
    player_pos = (loc.x, loc.y, loc.z)
    rot = player.GetWorldRotation()
    right_p, fwd_p, up_p = rot.GetCol(0), rot.GetCol(1), rot.GetCol(2)
    right = (right_p.x, right_p.y, right_p.z)
    forward = (fwd_p.x, fwd_p.y, fwd_p.z)
    up = (up_p.x, up_p.y, up_p.z)

    print(f"\n=== {system} / {region} (player at {player_pos}) ===")
    drawn = celestial.draw_list(view)
    for body in drawn:
        _report_row(body.name, body.position, body.radius_gu,
                    player_pos, right, forward, up, engine_units)

    from engine.host_loop import _aggregate_suns
    for sun in _aggregate_suns():
        _report_row("Sun", sun["position"], sun["radius"],
                    player_pos, right, forward, up, engine_units)


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    system = argv[1]
    regions = argv[2:]

    import tools.mission_harness as mh
    mh.setup_sdk()

    import App
    import MissionLib
    from engine.core.game import Game, _set_current_game
    from engine.systems import system_loader
    from engine import units as engine_units

    App.g_kSetManager._sets.clear()
    App.g_kSetManager.ClearRenderedSet()
    system_loader.reset()
    _set_current_game(Game())

    first = regions[0]
    pSet = _load_region(system, first)
    player = MissionLib.CreatePlayerShip("Galaxy", pSet, "player", "Player Start")
    system_loader.ensure_loaded(player)

    for region in regions:
        _load_region(system, region)
        if region != first:
            _place_player_in(player, App.g_kSetManager.GetSet(region))
        _print_station(system, region, player, engine_units)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
