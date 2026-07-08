"""Target status panels must show a (de)cloaking ship's shields as DOWN — the
same vulnerability window combat honours (2026-07-08 live-play fix). During the
CLOAKING/DECLOAKING fade the shields don't block, so the ship-display schematic
and the target-list shield bar should read down, not the preserved charge.
"""
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import ShieldSubsystem, CloakingSubsystem
from engine.ui.ship_display_panel import _shields_tuple
from engine.ui.target_list_view import _query_shield_percentage


def _shielded_cloak_ship():
    ship = ShipClass_Create("Target")
    ss = ShieldSubsystem("Shields")
    for f in range(ShieldSubsystem.NUM_SHIELDS):
        ss.SetMaxShields(f, 1000.0)          # seeds current to max
    ship.SetShieldSubsystem(ss)
    ship.SetCloakingSubsystem(CloakingSubsystem("Cloaking Device"))
    return ship, ss


def test_panel_shows_shields_up_when_decloaked():
    ship, _ss = _shielded_cloak_ship()
    assert all(v == 1.0 for v in _shields_tuple(ship))
    assert _query_shield_percentage(ship) == 100


def test_panel_shows_shields_down_while_cloaking():
    ship, _ss = _shielded_cloak_ship()
    ship.GetCloakingSubsystem().StartCloaking()   # CLOAKING (fading out)
    assert all(v == 0.0 for v in _shields_tuple(ship))
    assert _query_shield_percentage(ship) == 0


def test_panel_shows_shields_down_while_decloaking():
    ship, _ss = _shielded_cloak_ship()
    cloak = ship.GetCloakingSubsystem()
    cloak.InstantCloak(); cloak.StopCloaking()    # DECLOAKING (fading in)
    assert all(v == 0.0 for v in _shields_tuple(ship))
    assert _query_shield_percentage(ship) == 0


def test_panel_shows_shields_up_again_after_transition_completes():
    ship, _ss = _shielded_cloak_ship()
    cloak = ship.GetCloakingSubsystem()
    cloak.InstantCloak(); cloak.InstantDecloak()  # fully DECLOAKED again
    assert all(v == 1.0 for v in _shields_tuple(ship))
    assert _query_shield_percentage(ship) == 100
