"""Tests for engine.dev_combat_cheats — the three dev-only combat cheat
flags. Each flag defaults Off, is mutated via a setter, and its
``*_active()`` getter returns False whenever dev mode is off (so a
production build's combat path is never affected)."""
import pytest


@pytest.fixture
def reset_cheats():
    """Reset cheat flags and the dev-mode attribute around each test."""
    import _dauntless_host
    import engine.dev_combat_cheats as cheats
    original_dev = getattr(_dauntless_host, "developer_mode", False)
    cheats.reset()
    try:
        yield cheats
    finally:
        cheats.reset()
        _dauntless_host.developer_mode = original_dev


def test_all_flags_default_off(reset_cheats):
    import _dauntless_host
    _dauntless_host.developer_mode = True
    cheats = reset_cheats
    assert cheats.god_mode_active() is False
    assert cheats.double_player_weapons_active() is False
    assert cheats.disable_npc_shields_active() is False


def test_set_god_mode_flips_active_when_dev_on(reset_cheats):
    import _dauntless_host
    _dauntless_host.developer_mode = True
    cheats = reset_cheats
    cheats.set_god_mode(True)
    assert cheats.god_mode_active() is True
    cheats.set_god_mode(False)
    assert cheats.god_mode_active() is False


def test_set_double_weapons_flips_active_when_dev_on(reset_cheats):
    import _dauntless_host
    _dauntless_host.developer_mode = True
    cheats = reset_cheats
    cheats.set_double_player_weapons(True)
    assert cheats.double_player_weapons_active() is True
    cheats.set_double_player_weapons(False)
    assert cheats.double_player_weapons_active() is False


def test_set_disable_npc_shields_flips_active_when_dev_on(reset_cheats):
    import _dauntless_host
    _dauntless_host.developer_mode = True
    cheats = reset_cheats
    cheats.set_disable_npc_shields(True)
    assert cheats.disable_npc_shields_active() is True
    cheats.set_disable_npc_shields(False)
    assert cheats.disable_npc_shields_active() is False


def test_getters_gated_off_when_dev_mode_off(reset_cheats):
    """Flags can be set, but the *_active() getters must report False
    while dev mode is off — production combat must never change."""
    import _dauntless_host
    cheats = reset_cheats
    cheats.set_god_mode(True)
    cheats.set_double_player_weapons(True)
    cheats.set_disable_npc_shields(True)
    # Gate is live: with dev mode on the flags read active...
    _dauntless_host.developer_mode = True
    assert cheats.god_mode_active() is True
    assert cheats.double_player_weapons_active() is True
    assert cheats.disable_npc_shields_active() is True
    # ...and flipping dev mode off forces every getter dark regardless.
    _dauntless_host.developer_mode = False
    assert cheats.god_mode_active() is False
    assert cheats.double_player_weapons_active() is False
    assert cheats.disable_npc_shields_active() is False


def test_reset_clears_all_flags(reset_cheats):
    import _dauntless_host
    _dauntless_host.developer_mode = True
    cheats = reset_cheats
    cheats.set_god_mode(True)
    cheats.set_double_player_weapons(True)
    cheats.set_disable_npc_shields(True)
    cheats.reset()
    assert cheats.god_mode_active() is False
    assert cheats.double_player_weapons_active() is False
    assert cheats.disable_npc_shields_active() is False
