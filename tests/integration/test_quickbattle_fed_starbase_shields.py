"""Headless: a Quick Battle Fed Starbase spawns shielded and its shields hold.

DELIBERATE DEPARTURE FROM BC. The stock hardpoint (ships/Hardpoints/
fedstarbase.py) declares every face at SetMaxShields 0, and the original game
really has none: stbc-oracle's mission-scenes.md records Starbase_12 at red
alert with all six faces at 0.00 in E3M1, E4M5, E4M6, E7M6 and E8M1. Dauntless
gives it the Cardassian Starbase's figures (6000 a face, 5/s, generator 600/s)
through the machine-owned hardpoint override, so it applies wherever the stock
Fed Starbase spawns, campaign included.

Driven from the setup panel so the ship goes through loadspacehelper's real
ClearLocalTemplates -> reload -> LoadPropertySet path, which is where the
override has to land on the ShieldGenerator template before SetupProperties
copies it onto the live ShieldSubsystem.
"""
import pytest

pytest.importorskip("_dauntless_host")

from tests.integration.test_quickbattle_setup_e2e import (  # noqa: E402,F401
    _do, _go, _ships, world,
)

MAX_PER_FACE = 6000.0
CHARGE_PER_SECOND = 5.0
GENERATOR_POWER = 600.0


def _enemy_fed_starbase(hl, panel, QB):
    _do(panel, "add:FedStarbase")
    _go(hl, panel)
    station = [s for n, s in _ships(QB).items() if n != "Player"][0]
    assert station.GetObjID() in QB.g_kShips
    return station


def test_enemy_fed_starbase_spawns_with_full_shields(world):
    hl, _c, panel, QB = world
    station = _enemy_fed_starbase(hl, panel, QB)
    sh = station.GetShields()
    for face in range(6):
        assert sh.GetMaxShields(face) == MAX_PER_FACE
        assert sh.GetCurShields(face) == MAX_PER_FACE
        assert sh.GetShieldChargePerSecond(face) == CHARGE_PER_SECOND
    assert sh.GetNormalPowerPerSecond() == GENERATOR_POWER
    assert sh.HasShields()


def test_enemy_fed_starbase_shields_absorb_a_hit(world):
    hl, _c, panel, QB = world
    import App
    from engine.appc import combat
    station = _enemy_fed_starbase(hl, panel, QB)
    player = App.Game_GetCurrentGame().GetPlayer()
    sh = station.GetShields()
    hull = station.GetHull()
    hull_before = hull.GetCondition()
    shields_before = sum(sh.GetCurShields(f) for f in range(6))

    # A hit well out along the station's own forward axis: the front face.
    loc = station.GetWorldLocation()
    fwd = station.GetWorldRotation().GetCol(1)
    hit = App.TGPoint3()
    hit.SetXYZ(loc.x + fwd.x * 200.0, loc.y + fwd.y * 200.0,
               loc.z + fwd.z * 200.0)
    combat.apply_hit(station, 1000.0, hit, player, weapon_type="phaser")

    # A full face (fraction >= 0.6) passes nothing through to the hull.
    assert hull.GetCondition() == hull_before
    assert sum(sh.GetCurShields(f) for f in range(6)) == pytest.approx(
        shields_before - 1000.0)
    assert sh.GetCurShields(App.ShieldClass.FRONT_SHIELDS) == pytest.approx(
        MAX_PER_FACE - 1000.0)
