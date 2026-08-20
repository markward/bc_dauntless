"""Cycling alert level must not refill drained shields.

Confirmed in play 2026-08-19: drop to green alert and go back to yellow, and
every shield facing returns to full. Free, instant, unlimited recharge with no
cooldown — the strongest possible exploit in a combat sim.

Mechanism: ``ShieldSubsystem.TurnOff`` zeroed every face and ``TurnOn`` snapped
every face to max, and ``ShipClass.SetAlertLevel`` calls them on every
transition. Both overrides carried docstrings claiming to "mirror BC".

BC does NOT do that. ``SaveToStream`` (0x56AB60) persists ``m_curShields[i]``
per facing through a power-down — the charge survives, and the off-state is
expressed by short-circuiting the QUERIES rather than by destroying the state
(``IsShieldBreached`` 0x56A620, ``GetShieldPercentage`` 0x56A540).

So the storage now persists, which is the sourced half. For the query half we
report **0.0 while the generator is off**, which is what every downstream
reader already saw when the faces were zeroed — so the HUD arcs, the target
list and the AI shield conditions all behave exactly as before. That number is
OUR choice, matching our own prior observable behaviour. The clean-room note
suggests BC returns 1.0 there, but it is graded reviewed-not-tested, and a
1.0 would paint FULL shield bars on a ship whose shields are down — the exact
bug class the shields-default-on work already had to fix once.
"""
import pytest

from engine.appc.ships import ShipClass, ShipClass_Create
from engine.appc.subsystems import HullSubsystem, ShieldSubsystem

FRONT = 0


def _ship_at_yellow(face_max=1000.0):
    ship = ShipClass_Create("Target")
    hull = HullSubsystem("Hull")
    hull.SetMaxCondition(20000.0)
    ship._hull = hull
    ss = ShieldSubsystem("Shield Generator")
    ss.SetMaxCondition(100.0)
    for f in range(ShieldSubsystem.NUM_SHIELDS):
        ss.SetMaxShields(f, face_max)
    ship.SetShieldSubsystem(ss)
    ship.SetAlertLevel(ShipClass.YELLOW_ALERT)
    return ship


def test_cycling_alert_does_not_refill_drained_shields():
    """The reported exploit, end to end."""
    ship = _ship_at_yellow()
    gen = ship.GetShields()
    gen.SetCurrentShields(FRONT, 150.0)          # took a beating

    ship.SetAlertLevel(ShipClass.GREEN_ALERT)    # shields down
    ship.SetAlertLevel(ShipClass.YELLOW_ALERT)   # shields back up

    assert gen.GetCurrentShields(FRONT) == 150.0, (
        "cycling alert refilled the facing — free instant recharge"
    )


def test_every_facing_survives_the_cycle_independently():
    ship = _ship_at_yellow()
    gen = ship.GetShields()
    levels = [0.0, 100.0, 250.0, 500.0, 750.0, 1000.0]
    for f, v in enumerate(levels):
        gen.SetCurrentShields(f, v)

    ship.SetAlertLevel(ShipClass.GREEN_ALERT)
    ship.SetAlertLevel(ShipClass.RED_ALERT)

    assert [gen.GetCurrentShields(f) for f in range(6)] == levels


def test_powering_down_does_not_destroy_the_stored_charge():
    """The sourced half: BC's SaveToStream persists m_curShields through a
    power-down, so the state must survive even while the generator is off."""
    ship = _ship_at_yellow()
    gen = ship.GetShields()
    gen.SetCurrentShields(FRONT, 400.0)

    ship.SetAlertLevel(ShipClass.GREEN_ALERT)

    assert gen.IsOn() == 0
    assert gen.GetCurrentShields(FRONT) == 400.0


def test_shields_still_read_as_down_to_every_consumer_while_off():
    """Preserving the state must not make a powered-down ship LOOK shielded.
    The HUD arcs (ship_display_panel) and the target list (target_list_view)
    both read these percentages, and both showed empty before this change."""
    ship = _ship_at_yellow()
    gen = ship.GetShields()
    gen.SetCurrentShields(FRONT, 900.0)

    ship.SetAlertLevel(ShipClass.GREEN_ALERT)

    assert gen.GetSingleShieldPercentage(FRONT) == 0.0
    assert gen.GetShieldPercentage() == 0.0


def test_raising_shields_restores_the_readouts():
    ship = _ship_at_yellow()
    gen = ship.GetShields()
    gen.SetCurrentShields(FRONT, 900.0)

    ship.SetAlertLevel(ShipClass.GREEN_ALERT)
    ship.SetAlertLevel(ShipClass.YELLOW_ALERT)

    assert gen.GetSingleShieldPercentage(FRONT) == pytest.approx(0.9)


def test_an_undamaged_ship_is_still_full_after_a_cycle():
    """Regression guard: the common case must not become a downgrade."""
    ship = _ship_at_yellow()
    gen = ship.GetShields()

    ship.SetAlertLevel(ShipClass.GREEN_ALERT)
    ship.SetAlertLevel(ShipClass.YELLOW_ALERT)

    assert gen.GetCurrentShields(FRONT) == 1000.0
    assert gen.GetSingleShieldPercentage(FRONT) == 1.0


def test_regen_still_refills_over_time_while_raised():
    """The legitimate way to get shields back. Cycling is not a shortcut for
    it; waiting is."""
    ship = _ship_at_yellow()
    gen = ship.GetShields()
    gen.SetCurrentShields(FRONT, 100.0)
    gen.SetShieldChargePerSecond(FRONT, 50.0)

    gen.Update(2.0)

    assert gen.GetCurrentShields(FRONT) > 100.0
