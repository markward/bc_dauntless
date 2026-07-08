"""End-to-end (headless GameLoop): a crippled cloak-capable AI ship enters
DEFENSIVE (cloaks); with a healthy reactor + repair progress it heals and
re-engages; with a weak reactor it is flushed out by reserve exhaustion before
healing. Repair is simulated by an external per-tick hull bump (repair proxy);
the real RepairSubsystem heal path is covered by test_gameloop_repair_tick.py."""
import App
import pytest
from engine.core.game import Game, Episode, Mission, _set_current_game
from engine.core.loop import GameLoop
from engine.appc import defensive_cloak
from engine.appc.ships import ShipClass
from engine.appc.ai import ArtificialIntelligence
from engine.appc.subsystems import CloakingSubsystem, HullSubsystem, PowerSubsystem
from engine.appc.properties import PowerProperty


class _InertAI:
    """Minimal AI whose SDK tick is a harmless no-op: tick_ai's type-dispatch
    matches none of the AI classes and falls through to `return ai._status`, so
    this must carry `_status` (and GetShip for the inert-coast gate). Used so a
    ship that EXITS defensive mode and resumes its SDK AI doesn't crash the loop."""
    def __init__(self, ship):
        self._ship = ship
        self._status = ArtificialIntelligence.US_ACTIVE
    def GetShip(self):
        return self._ship


@pytest.fixture(autouse=True)
def _iso():
    defensive_cloak.reset_defensive_cloak_state()
    App.g_kSetManager._sets.clear()
    App.g_kTimerManager._time = 0.0; App.g_kRealtimeTimerManager._time = 0.0
    yield
    defensive_cloak.reset_defensive_cloak_state()
    App.g_kSetManager._sets.clear()


def _game():
    m = Mission(); m.SetScript("tests.integration.test_defensive_cloak_cadence")
    e = Episode(); e.SetCurrentMission(m); g = Game(); g.SetCurrentEpisode(e)
    _set_current_game(g)


def _build(pSet, name, reactor_output, hull_pct):
    ship = ShipClass(); pSet.AddObjectToSet(ship, name)
    hull = HullSubsystem("Hull"); hull.SetMaxCondition(1000.0)
    hull.SetCondition(1000.0 * hull_pct); ship.SetHull(hull)
    power = PowerSubsystem("Warp Core"); prop = PowerProperty("Warp Core")
    prop.SetPowerOutput(reactor_output); prop.SetMainBatteryLimit(100000.0)
    prop.SetBackupBatteryLimit(8000.0)          # small reserve so exhaustion is reachable
    prop.SetMainConduitCapacity(1700.0); prop.SetBackupConduitCapacity(300.0)
    power.SetProperty(prop); ship.SetPowerSubsystem(power)
    power.SetMainBatteryPower(100000.0)         # main full -> reactor output spills to reserve
    power.SetBackupBatteryPower(8000.0)
    ship.SetCloakingSubsystem(CloakingSubsystem("Cloaking Device"))
    ship.SetAI(_InertAI(ship))
    tgt = ShipClass(); pSet.AddObjectToSet(tgt, name + "_tgt"); ship.SetTarget(tgt)
    return ship


def _bump_hull(ship, per_tick):
    hull = ship.GetHull()
    hull.SetCondition(min(hull.GetMaxCondition(), hull.GetCondition() + per_tick))


def test_healthy_ship_hides_repairs_and_re_engages():
    # Healthy reactor (1500 > 1000 drain) sustains cloak; repair proxy heals it
    # past the fit threshold -> re-engages.
    _game()
    pSet = App.SetClass_Create(); pSet.SetName("S"); App.g_kSetManager._sets["S"] = pSet
    ship = _build(pSet, "Fixer", reactor_output=1500.0, hull_pct=0.30)
    loop = GameLoop()
    entered = False
    for _ in range(60 * 30):                    # up to 30 s
        loop.advance(1)
        if defensive_cloak.is_defensive(ship):
            entered = True
            _bump_hull(ship, per_tick=1.0)       # ~60 hull/s repair proxy
        elif entered:
            break
    assert entered, "crippled ship should have hidden"
    assert not defensive_cloak.is_defensive(ship), "should re-engage once healed"
    assert ship.GetHull().GetConditionPercentage() >= defensive_cloak.FIT_TO_FIGHT_THRESHOLD


def test_weak_reactor_ship_is_flushed_out_before_healing():
    # Weak reactor (200 << 1000 drain): reserve empties -> Step 0 forces decloak
    # -> controller releases it, still hurt. No repair proxy (never heals).
    _game()
    pSet = App.SetClass_Create(); pSet.SetName("S"); App.g_kSetManager._sets["S"] = pSet
    ship = _build(pSet, "Doomed", reactor_output=200.0, hull_pct=0.30)
    loop = GameLoop()
    entered = False
    for _ in range(60 * 30):
        loop.advance(1)
        if defensive_cloak.is_defensive(ship):
            entered = True
        elif entered:
            break
    assert entered
    assert not defensive_cloak.is_defensive(ship)
    assert ship.GetHull().GetConditionPercentage() < defensive_cloak.FIT_TO_FIGHT_THRESHOLD
