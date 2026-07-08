"""C: engine-side defensive-cloak controller. A crippled cloak-capable AI ship
hides (cloaks) to repair, and exits when healed (>= FIT_TO_FIGHT_THRESHOLD) or
forced out by reserve exhaustion (cloak no longer trying). Player/no-cloak ships
are never entered. See docs/superpowers/specs/2026-07-07-cloak-survival-resource-design.md."""
import App
from engine.appc.ships import ShipClass
from engine.appc.subsystems import CloakingSubsystem, HullSubsystem, PowerSubsystem
from engine.appc.properties import PowerProperty
from engine.appc import defensive_cloak
from engine.appc.defensive_cloak import (
    tick_defensive_cloak, is_defensive, reset_defensive_cloak_state,
    CLOAK_HULL_THRESHOLD, FIT_TO_FIGHT_THRESHOLD, CLOAK_REENTRY_RESERVE_FRACTION,
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


def _attach_power(ship, backup_limit=80000.0, backup_power=0.0):
    """Give a ship a real PowerSubsystem with a backup reserve (see
    test_cloak_reserve_depletion._powered_ship / test_cloak_power_starvation._powered_ship)."""
    power = PowerSubsystem("Warp Core")
    prop = PowerProperty("Warp Core")
    prop.SetPowerOutput(1000.0)
    prop.SetMainBatteryLimit(250000.0)
    prop.SetBackupBatteryLimit(backup_limit)
    prop.SetMainConduitCapacity(1200.0)
    prop.SetBackupConduitCapacity(200.0)
    power.SetProperty(prop)
    ship.SetPowerSubsystem(power)
    power.SetBackupBatteryPower(backup_power)
    return power


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


def test_prunes_stale_id_when_ship_leaves_set():
    _reset()
    ship = _combat_cloak_ship(hull_pct=CLOAK_HULL_THRESHOLD - 0.05)
    tick_defensive_cloak(1.0 / 60.0)                     # enter, cloaking
    assert is_defensive(ship)

    # Ship leaves the simulation (e.g. removed from its set ~10s after death,
    # RemoveObjectFromSet) -> iter_ships() no longer yields it.
    pSet = App.g_kSetManager._sets["S"]
    pSet.RemoveObjectFromSet("Ship%d" % id(ship))

    tick_defensive_cloak(1.0 / 60.0)
    assert not is_defensive(ship)
    assert id(ship) not in defensive_cloak._defensive
    _reset()


def test_reentry_gated_when_reserve_not_recovered():
    _reset()
    ship = _combat_cloak_ship(hull_pct=CLOAK_HULL_THRESHOLD - 0.05)
    _attach_power(ship, backup_limit=80000.0, backup_power=100.0)   # near-empty reserve
    tick_defensive_cloak(1.0 / 60.0)
    assert not is_defensive(ship)                        # anti-thrash: reserve not recovered
    _reset()


def test_reentry_allowed_when_reserve_recovered():
    _reset()
    ship = _combat_cloak_ship(hull_pct=CLOAK_HULL_THRESHOLD - 0.05)
    power = _attach_power(ship, backup_limit=80000.0, backup_power=0.0)
    power.SetBackupBatteryPower(80000.0 * CLOAK_REENTRY_RESERVE_FRACTION)   # exactly recovered
    tick_defensive_cloak(1.0 / 60.0)
    assert is_defensive(ship)
    _reset()


# ── 60s timeout + re-hide cooldown (2026-07-08 live-play fix) ────────────────
# AI ships were hiding cloaked too long. A defensive-cloak episode is capped at
# DEFENSIVE_CLOAK_TIMEOUT_S; after a timeout the ship must fight for
# DEFENSIVE_CLOAK_COOLDOWN_S before it can re-hide (else a healthy ship just
# re-cloaks instantly and the timeout is meaningless).

def test_defensive_cloak_times_out():
    _reset()
    ship = _combat_cloak_ship(hull_pct=CLOAK_HULL_THRESHOLD - 0.05)   # stays crippled
    cloak = ship.GetCloakingSubsystem()
    tick_defensive_cloak(1.0 / 60.0)                                  # enter
    assert is_defensive(ship)
    tick_defensive_cloak(defensive_cloak.DEFENSIVE_CLOAK_TIMEOUT_S + 1.0)  # exceed timeout
    assert not is_defensive(ship)                                     # timed out -> released
    assert cloak.IsTryingToCloak() == 0
    _reset()


def test_timeout_cooldown_blocks_then_allows_re_hide():
    _reset()
    ship = _combat_cloak_ship(hull_pct=CLOAK_HULL_THRESHOLD - 0.05)   # crippled the whole time
    tick_defensive_cloak(1.0 / 60.0)                                  # enter
    tick_defensive_cloak(defensive_cloak.DEFENSIVE_CLOAK_TIMEOUT_S + 1.0)  # timeout -> release + cooldown
    assert not is_defensive(ship)
    tick_defensive_cloak(1.0 / 60.0)                                  # cooldown still active
    assert not is_defensive(ship)
    tick_defensive_cloak(defensive_cloak.DEFENSIVE_CLOAK_COOLDOWN_S + 1.0)  # cooldown elapses
    assert is_defensive(ship)                                         # may hide again
    _reset()


def test_normal_short_ticks_never_time_out():
    _reset()
    ship = _combat_cloak_ship(hull_pct=CLOAK_HULL_THRESHOLD - 0.05)
    tick_defensive_cloak(1.0 / 60.0)                                  # enter
    for _ in range(120):                                             # 2 s of real ticks
        tick_defensive_cloak(1.0 / 60.0)
    assert is_defensive(ship)                                         # nowhere near 60 s
    _reset()
