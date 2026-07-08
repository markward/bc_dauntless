"""C: engine-side defensive-cloak controller. A crippled cloak-capable AI ship
hides (cloaks) to repair, and exits when healed (>= FIT_TO_FIGHT_THRESHOLD) or
forced out by reserve exhaustion (cloak no longer trying). Player/no-cloak ships
are never entered. See docs/superpowers/specs/2026-07-07-cloak-survival-resource-design.md."""
import App
from engine.appc.ships import ShipClass
from engine.appc.subsystems import CloakingSubsystem, HullSubsystem
from engine.appc import defensive_cloak
from engine.appc.defensive_cloak import (
    tick_defensive_cloak, is_defensive, reset_defensive_cloak_state,
    CLOAK_HULL_THRESHOLD, FIT_TO_FIGHT_THRESHOLD,
)


def _reset():
    reset_defensive_cloak_state()
    App.g_kSetManager._sets.clear()


def _combat_cloak_ship(hull_pct=1.0, with_target=True, with_cloak=True, with_ai=True):
    pSet = App.g_kSetManager._sets.get("S")
    if pSet is None:
        pSet = App.SetClass_Create(); pSet.SetName("S"); App.g_kSetManager._sets["S"] = pSet
    ship = ShipClass()
    pSet.AddObjectToSet(ship, "Ship%d" % id(ship))
    hull = HullSubsystem("Hull"); hull.SetMaxCondition(1000.0)
    hull.SetCondition(1000.0 * hull_pct)
    ship.SetHull(hull)
    if with_cloak:
        ship.SetCloakingSubsystem(CloakingSubsystem("Cloaking Device"))
    if with_ai:
        ship.SetAI(object())            # any non-None AI marker
    if with_target:
        tgt = ShipClass(); pSet.AddObjectToSet(tgt, "Tgt%d" % id(tgt))
        ship.SetTarget(tgt)
    return ship


def test_enters_defensive_when_crippled_in_combat():
    _reset()
    ship = _combat_cloak_ship(hull_pct=CLOAK_HULL_THRESHOLD - 0.05)
    tick_defensive_cloak(1.0 / 60.0)
    assert is_defensive(ship)
    assert ship.GetCloakingSubsystem().IsTryingToCloak() == 1
    _reset()


def test_does_not_enter_when_healthy():
    _reset()
    ship = _combat_cloak_ship(hull_pct=0.9)
    tick_defensive_cloak(1.0 / 60.0)
    assert not is_defensive(ship)
    _reset()


def test_does_not_enter_without_target():
    _reset()
    ship = _combat_cloak_ship(hull_pct=0.1, with_target=False)
    tick_defensive_cloak(1.0 / 60.0)
    assert not is_defensive(ship)
    _reset()


def test_player_and_no_cloak_ships_never_enter():
    _reset()
    player = _combat_cloak_ship(hull_pct=0.1, with_ai=False)   # no AI == player-like
    nocloak = _combat_cloak_ship(hull_pct=0.1, with_cloak=False)
    tick_defensive_cloak(1.0 / 60.0)
    assert not is_defensive(player)
    assert not is_defensive(nocloak)
    _reset()


def test_exits_when_healed_above_fit_threshold():
    _reset()
    ship = _combat_cloak_ship(hull_pct=CLOAK_HULL_THRESHOLD - 0.05)
    tick_defensive_cloak(1.0 / 60.0)
    assert is_defensive(ship)
    ship.GetHull().SetCondition(ship.GetHull().GetMaxCondition() * (FIT_TO_FIGHT_THRESHOLD + 0.05))
    tick_defensive_cloak(1.0 / 60.0)
    assert not is_defensive(ship)
    assert ship.GetCloakingSubsystem().IsDecloaking() or ship.GetCloakingSubsystem().IsTryingToCloak() == 0
    _reset()


def test_hysteresis_holds_between_thresholds():
    _reset()
    ship = _combat_cloak_ship(hull_pct=CLOAK_HULL_THRESHOLD - 0.05)
    tick_defensive_cloak(1.0 / 60.0)                     # enter
    ship.GetHull().SetCondition(ship.GetHull().GetMaxCondition() * 0.50)   # between 0.35 and 0.70
    tick_defensive_cloak(1.0 / 60.0)
    assert is_defensive(ship)                            # still hiding, not re-engaged
    _reset()


def test_exits_when_forced_out_by_exhaustion():
    _reset()
    ship = _combat_cloak_ship(hull_pct=CLOAK_HULL_THRESHOLD - 0.05)
    tick_defensive_cloak(1.0 / 60.0)                     # enter, cloaking
    # Simulate Step 0 forced decloak (reserve dry): cloak no longer trying.
    ship.GetCloakingSubsystem().InstantDecloak()
    tick_defensive_cloak(1.0 / 60.0)
    assert not is_defensive(ship)                        # controller released it
    _reset()
