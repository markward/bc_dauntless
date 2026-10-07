"""E1M2's Haven/Vesuvi6 Facility station has no AI -- AsteroidHitStation
sends it toward the planet with a bare `pStation.SetVelocity`
(E1M2.py ~3248). Without engine.appc.drift it reports a nonzero velocity
but never actually moves (the same bug as the probe launch / E8M2 Matan).
"""
from tests.integration.test_e1m2_asteroid_crash import _init_e1m2

import App
from engine.appc.ship_motion import tick_all_ship_motion


def test_station_drifts_toward_planet_after_asteroid_hit():
    mod = _init_e1m2()
    pSet = App.g_kSetManager.GetSet("Vesuvi6")
    station = App.ShipClass_GetObject(pSet, "Facility")
    assert station is not None
    p0 = station.GetTranslate()

    mod.AsteroidHitStation()
    v = station.GetVelocityTG()
    assert (v.x * v.x + v.y * v.y + v.z * v.z) > 0.0

    for _ in range(60):
        tick_all_ship_motion(1.0 / 60.0)

    p1 = station.GetTranslate()
    dist = ((p1.x - p0.x) ** 2 + (p1.y - p0.y) ** 2 + (p1.z - p0.z) ** 2) ** 0.5
    assert dist > 0.5
