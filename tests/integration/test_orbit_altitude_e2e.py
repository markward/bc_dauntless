"""End-to-end: a player ordered to orbit a large planet stays above its
atmosphere (engine.orbit_altitude; Mark, 2026-10-07, option C).

Real SDK AI.Player.OrbitPlanet tree (AvoidObstacles -> PriorityList ->
CloseEnough/ConditionInRange -> Sequence -> CircleObject, else Intercept),
driven by the real GameLoop (AI + motion + proximity). R = 7200 GU:
alt = 0.15 * 7200 = 1080, circle (8280, 8568), trigger 8640. Atmosphere top
is 0.06 * R = 432 GU.
"""
import pytest

import App
from engine import orbit_altitude as oa
from engine.appc.planet import Planet_Create
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem, ImpulseEngineSubsystem
from engine.core.loop import GameLoop

R = 7200.0
ATMOSPHERE_TOP = 0.06 * R          # 432 GU
SETTLED = (1080.0, 1370.0)


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture
def orbit_mod(monkeypatch):
    _reset_app_state()
    import AI.Player.OrbitPlanet as mod
    orig = getattr(mod.CreateAI, "_dauntless_orbit_altitude_orig", None) or mod.CreateAI
    monkeypatch.setattr(mod, "CreateAI", orig)
    yield mod
    _reset_app_state()


def _fly_orbit(mod, start, max_speed, seconds=240):
    """Altitudes (centre distance - R) sampled once per game second."""
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ship = ShipClass(); ship.SetName("Player")
    ship._hull = HullSubsystem("H"); ship._hull.SetMaxCondition(1000.0)
    ship._impulse_engine_subsystem = ImpulseEngineSubsystem("IES")
    ship._impulse_engine_subsystem.SetMaxSpeed(max_speed)
    pSet.AddObjectToSet(ship, "Player")
    planet = Planet_Create(R, "colony.nif"); planet.SetName("Giant")
    pSet.AddObjectToSet(planet, "Giant")
    ship.SetTranslateXYZ(0.0, float(start), 0.0)

    ship.SetAI(mod.CreateAI(ship, planet))
    loop = GameLoop()
    alts = []
    for i in range(seconds * 60):
        loop.tick()
        if i % 60 == 59:
            p = ship.GetWorldLocation()
            alts.append((p.x * p.x + p.y * p.y + p.z * p.z) ** 0.5 - R)
    return alts


# Galaxy cruise (SetMaxSpeed 6.3) from just inside the trigger and from
# beyond it (Intercept approach first); plus a fast approach from far out.
@pytest.mark.parametrize("start, max_speed", [(8400.0, 6.3), (12000.0, 6.3),
                                              (20000.0, 120.0)])
def test_player_orbit_settles_above_the_atmosphere(orbit_mod, start, max_speed):
    oa.install(orbit_mod)
    alts = _fly_orbit(orbit_mod, start, max_speed)
    assert min(alts) > ATMOSPHERE_TOP, "dipped into the atmosphere: %.1f" % min(alts)
    settled = alts[-60:]                    # the last game minute
    assert SETTLED[0] <= min(settled) and max(settled) <= SETTLED[1], \
        "settled altitude %.1f..%.1f outside %s" % (min(settled), max(settled), SETTLED)


def test_control_bc_stock_orbit_sits_inside_the_atmosphere(orbit_mod):
    """Without the hook BC's R + 150 standoff puts the ship inside the shell
    -- the bug this fixes, and proof the test above can fail."""
    alts = _fly_orbit(orbit_mod, 7400.0, 6.3)
    assert min(alts[-60:]) < ATMOSPHERE_TOP
