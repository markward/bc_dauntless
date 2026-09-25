"""How far from the camera a ship is drawn (system-frames Plan 3, Task 3).

One number, shared by the render cull (host_loop._reconcile_runtime_instances)
and the engine-hum roster (engine.audio.hum_allocator): a ship the scene does
not draw does not hum either. It lives here, not in host_loop, so audio never
imports the host loop.

SHIP_DRAW_DISTANCE_GU is derived so the LARGEST ship class commonly present
still covers at least one pixel at the cull line:
  * exterior vertical FOV 35 deg (engine.cameras.EXTERIOR_FOV_Y_RAD) over a
    1080 px viewport: one pixel ~ radians(35)/1080 = 5.657e-4 rad;
  * ship radius = half the diagonal of the high-LOD NIF's AABB x
    BC_MODEL_SCALE (0.01), measured with the renderer's own model_aabb on each
    ships/*.py GetShipStats()["FilenameHigh"] (2026-09-25):
      Galaxy  data/Models/Ships/Galaxy/Galaxy.nif    half (232.1, 322.2, 70.5)
              -> r = 4.03 GU, 1 px at 2*4.03/5.657e-4  = 14,258 GU
      Warbird data/Models/Ships/Warbird/Warbird.nif  half (493.6, 628.8, 173.2)
              -> r = 8.18 GU, 1 px at 2*8.18/5.657e-4  = 28,917 GU
    The Warbird is the largest non-station ship (next: KessokHeavy 6.71 GU,
    CardHybrid 5.13 GU; bases/stations and the one-mission Sunbuster at
    10.42 GU, which is still 1.23 px at the line, excluded). The hardpoints
    (ships/Hardpoints/*.py) carry no whole-ship radius -- Hull.SetRadius(1.0)
    on the Galaxy is the hull SUBSYSTEM's -- hence the model extent.
  * 28,917 rounded up to a round number: 30,000 GU (5,250 km).

Hysteresis: a hidden ship is shown inside SHIP_DRAW_DISTANCE_GU and a shown
one hidden only past SHIP_DRAW_DISTANCE_GU * (1 + SHIP_DRAW_HYSTERESIS), so a
ship sitting on the line does not flicker.
"""
from __future__ import annotations

SHIP_DRAW_DISTANCE_GU = 30000.0
SHIP_DRAW_HYSTERESIS = 0.10


def within_draw_distance(pos, centre, *, shown: bool = False) -> bool:
    """True when `pos` is within the draw distance of `centre` (both in the
    same set's coordinates). `shown` -- the ship is currently drawn -- widens
    the limit by the hysteresis band."""
    limit = SHIP_DRAW_DISTANCE_GU
    if shown:
        limit *= 1.0 + SHIP_DRAW_HYSTERESIS
    dx = pos[0] - centre[0]
    dy = pos[1] - centre[1]
    dz = pos[2] - centre[2]
    return dx * dx + dy * dy + dz * dz <= limit * limit
