"""Torpedo "spread" selector -> firing-chain selection (weapon_config).

Audited: BC's tactical "torpedo spread" toggle IS
``WeaponSystem::SetFiringChainMode`` — there is no tube-count parameter
anywhere in BC (weapon-firing-mechanics.md §2.10). This replaces the earlier
invented Single/Dual/Quad tube-count heuristic (the old
tests/unit/test_torpedo_spread.py) with chain-label selection: the active
chain's authored label ("Single"/"Dual"/"Quad" on Galaxy/Sovereign) is what
the UI shows and cycles, and a hull that authors no ``FiringChainString``
(67 of 70 stock hardpoints) shows no spread control at all.
"""
from engine.appc import weapon_config
from tests.helpers.torpedo_fixtures import make_ship_with_torpedo_chains


def test_config_exposes_chain_labels_for_galaxy_style_chains():
    ship = make_ship_with_torpedo_chains("0;Single;123;Dual;53;Quad")
    cfg = weapon_config.read_weapon_config(ship)
    assert cfg["spread_options"] == ["Single", "Dual", "Quad"]
    assert cfg["spread"] == "Single"


def test_cycle_advances_chain_mode_and_wraps():
    ship = make_ship_with_torpedo_chains("0;Single;123;Dual;53;Quad")
    torps = ship.GetTorpedoSystem()
    weapon_config.cycle_torpedo_spread(ship)
    assert torps.GetFiringChainMode() == 1
    weapon_config.cycle_torpedo_spread(ship)
    weapon_config.cycle_torpedo_spread(ship)
    assert torps.GetFiringChainMode() == 0            # wrapped


def test_cycle_advances_chain_label_in_config():
    ship = make_ship_with_torpedo_chains("0;Single;123;Dual;53;Quad")
    weapon_config.cycle_torpedo_spread(ship)
    assert weapon_config.read_weapon_config(ship)["spread"] == "Dual"
    weapon_config.cycle_torpedo_spread(ship)
    assert weapon_config.read_weapon_config(ship)["spread"] == "Quad"
    weapon_config.cycle_torpedo_spread(ship)           # wraps
    assert weapon_config.read_weapon_config(ship)["spread"] == "Single"


def test_chainless_ship_shows_no_spread_control():
    ship = make_ship_with_torpedo_chains("")
    cfg = weapon_config.read_weapon_config(ship)
    assert cfg["spread_options"] == []
    assert cfg["spread"] == ""
    weapon_config.cycle_torpedo_spread(ship)          # silent no-op
    assert weapon_config.read_weapon_config(ship)["spread"] == ""


def test_single_chain_ship_no_op_cycle():
    """Only one authored chain -> nothing to cycle to (n < 2 no-op)."""
    ship = make_ship_with_torpedo_chains("0;Single")
    cfg = weapon_config.read_weapon_config(ship)
    assert cfg["spread_options"] == ["Single"]
    weapon_config.cycle_torpedo_spread(ship)
    assert weapon_config.read_weapon_config(ship)["spread"] == "Single"


def test_cycle_torpedo_spread_absent_no_crash():
    weapon_config.cycle_torpedo_spread(None)
