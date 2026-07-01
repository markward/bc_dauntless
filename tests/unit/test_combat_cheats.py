"""combat.apply_hit must honour the three dev combat cheats when dev mode
is on: god mode (player takes no damage but feedback still fires), 2x
player weapon strength (player's outgoing damage doubled), and disable
NPC shields (non-player shields stop absorbing). All cheats are no-ops
when dev mode is off. Builds on the ship fixtures used by
test_combat_skips_disabled_shields.py."""
from unittest.mock import patch

import pytest

import App
from engine.appc.math import TGPoint3
from engine.appc.combat import apply_hit
from engine.appc.ships import ShipClass, ShipClass_Create
from engine.appc.subsystems import HullSubsystem, ShieldSubsystem


def _ship(name, hull_max=2000.0, face_max=1000.0):
    """Yellow-alert ship with a healthy powered shield generator + hull."""
    ship = ShipClass_Create(name)
    hull = HullSubsystem("Hull")
    hull.SetMaxCondition(hull_max)
    ship._hull = hull
    ss = ShieldSubsystem("Shield Generator")
    ss.SetMaxCondition(100.0)
    ss.SetDisabledPercentage(0.25)
    for f in range(ShieldSubsystem.NUM_SHIELDS):
        ss.SetMaxShields(f, face_max)
    ship.SetShieldSubsystem(ss)
    ship._radius = 20.0
    ship.SetAlertLevel(ShipClass.YELLOW_ALERT)
    return ship


@pytest.fixture
def env():
    """Dev mode on; a current game with a designated player; cheats reset
    before and after. Yields (player, npc)."""
    import _dauntless_host
    import engine.dev_combat_cheats as cheats
    original_dev = getattr(_dauntless_host, "developer_mode", False)
    _dauntless_host.developer_mode = True
    cheats.reset()
    player = _ship("Player")
    npc = _ship("NPC")
    game = App.Game()
    App._set_current_game(game)
    game.SetPlayer(player)
    try:
        yield player, npc
    finally:
        cheats.reset()
        App._set_current_game(None)
        _dauntless_host.developer_mode = original_dev


# ---- god mode -------------------------------------------------------------

def test_god_mode_player_takes_no_damage_but_feedback_fires(env):
    player, _ = env
    import engine.dev_combat_cheats as cheats
    cheats.set_god_mode(True)
    with patch("engine.appc.hit_feedback.dispatch") as mock_dispatch:
        apply_hit(player, 5000.0, TGPoint3(0, 10, 0), source=None)
    # Shields and hull untouched.
    assert player.GetShields().GetCurrentShields(0) == 1000.0
    assert player.GetHull().GetCondition() == 2000.0
    # Hit feedback still fired (player still sees/hears the impact).
    assert mock_dispatch.called


def test_god_mode_does_not_protect_npc(env):
    player, npc = env
    import engine.dev_combat_cheats as cheats
    cheats.set_god_mode(True)
    # 500 < 1000 shield, so shields absorb and drop to 500; hull intact.
    apply_hit(npc, 500.0, TGPoint3(0, 10, 0), source=None)
    assert npc.GetShields().GetCurrentShields(0) == 500.0


# ---- 2x player weapon strength -------------------------------------------

def test_double_weapons_doubles_player_outgoing_damage(env):
    player, npc = env
    import engine.dev_combat_cheats as cheats
    cheats.set_double_player_weapons(True)
    # Drain NPC shields first so damage reaches the hull predictably.
    npc.GetShields().SetCurrentShields(0, 0.0)
    apply_hit(npc, 500.0, TGPoint3(0, 10, 0), source=player)
    # 500 doubled to 1000 -> hull 2000 - 1000 = 1000.
    assert npc.GetHull().GetCondition() == 1000.0


def test_double_weapons_ignores_non_player_source(env):
    player, npc = env
    import engine.dev_combat_cheats as cheats
    cheats.set_double_player_weapons(True)
    npc.GetShields().SetCurrentShields(0, 0.0)
    apply_hit(npc, 500.0, TGPoint3(0, 10, 0), source=None)  # not the player
    assert npc.GetHull().GetCondition() == 1500.0  # un-doubled


# ---- disable NPC shields --------------------------------------------------

def test_disable_npc_shields_bypasses_npc_absorption(env):
    player, npc = env
    import engine.dev_combat_cheats as cheats
    cheats.set_disable_npc_shields(True)
    apply_hit(npc, 500.0, TGPoint3(0, 10, 0), source=player)
    # Shields bypassed: face HP preserved, hull takes the full hit.
    assert npc.GetShields().GetCurrentShields(0) == 1000.0
    assert npc.GetHull().GetCondition() == 1500.0


def test_disable_npc_shields_leaves_player_shields_intact(env):
    player, _ = env
    import engine.dev_combat_cheats as cheats
    cheats.set_disable_npc_shields(True)
    apply_hit(player, 500.0, TGPoint3(0, 10, 0), source=None)
    # Player is not an NPC: shields still absorb.
    assert player.GetShields().GetCurrentShields(0) == 500.0


# ---- gating ---------------------------------------------------------------

def test_cheats_are_noops_when_dev_mode_off(env):
    player, npc = env
    import _dauntless_host
    import engine.dev_combat_cheats as cheats
    cheats.set_god_mode(True)
    cheats.set_double_player_weapons(True)
    cheats.set_disable_npc_shields(True)
    _dauntless_host.developer_mode = False  # gate everything off
    apply_hit(player, 500.0, TGPoint3(0, 10, 0), source=player)
    # God mode off -> player shields absorb normally.
    assert player.GetShields().GetCurrentShields(0) == 500.0


def test_god_mode_player_gets_no_persistent_decal(env, monkeypatch):
    player, _ = env
    from engine import host_io
    import engine.dev_combat_cheats as cheats
    from engine.appc import damage_decals as dd
    # Deterministic clock so the decal path is fully exercised if (and only
    # if) combat fails to pass persist_decal=False — making this a real guard.
    monkeypatch.setattr(dd, "current_game_time", lambda: 42.0)
    cheats.set_god_mode(True)

    # The scorch decal routes through host_io.damage_decal_add; capture it there.
    # world_to_body → None so the spark path never hits the strict real binding.
    decals = []
    monkeypatch.setattr(host_io, "damage_decal_add",
                        lambda *a, **k: decals.append((a, k)))
    monkeypatch.setattr(host_io, "world_to_body", lambda *a, **k: None)
    monkeypatch.setattr(host_io, "hull_carve_add", lambda *a, **k: None)

    # Drain a face so the hit would reach the hull (the decal path) absent god mode.
    player.GetShields().SetCurrentShields(0, 0.0)
    apply_hit(player, 500.0, TGPoint3(0, 10, 0), source=None,
              normal=TGPoint3(0, 1, 0), ship_instances={player: 1})
    assert decals == []                                 # god mode: no scar
    assert player.GetHull().GetCondition() == 2000.0    # and no damage taken
