"""ShipClass thin scripted-API accessors (SDK App.py §5) that previously fell
through to the truthy TGObject _Stub — each stub was a latent bug (e.g.
IsPlayerShip() returning a truthy stub made EVERY ship read as the player).

Contracts recovered from SDK call sites:
* GetImpulse() -> impulse as a fraction 0..1 (E3M1: `>= 1.0`; BridgeHandlers:
  `* 9 + 0.1`); magnitude only — FlyForward negates it via IsReverse().
* IsReverse() -> sign of current speed.
* IsPlayerShip() -> is this the current game's player.
* CompleteStop() -> halt the ship immediately.
* StopFiringWeapons() -> cease-fire on every weapon system.
* Get/SetNetPlayerID() -> MP player id (default -1 when non-networked).
"""
import pytest

import App
from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass_Create


# ── IsPlayerShip ────────────────────────────────────────────────────────────
@pytest.fixture
def game_env():
    player = ShipClass_Create("Player")
    npc = ShipClass_Create("NPC")
    game = App.Game()
    App._set_current_game(game)
    game.SetPlayer(player)
    try:
        yield player, npc
    finally:
        App._set_current_game(None)


def test_is_player_ship_true_only_for_player(game_env):
    player, npc = game_env
    assert player.IsPlayerShip() == 1
    assert npc.IsPlayerShip() == 0   # NOT a truthy stub


def test_is_player_ship_false_with_no_game():
    App._set_current_game(None)
    ship = ShipClass_Create("Lonely")
    assert ship.IsPlayerShip() == 0


# ── IsReverse ───────────────────────────────────────────────────────────────
def test_is_reverse_reflects_speed_sign():
    ship = ShipClass_Create("S")
    ship._current_speed = 12.0
    assert ship.IsReverse() == 0
    ship._current_speed = -3.0
    assert ship.IsReverse() == 1
    ship._current_speed = 0.0
    assert ship.IsReverse() == 0


# ── GetImpulse (fraction of authored max speed, magnitude only) ─────────────
def test_get_impulse_is_speed_fraction():
    ship = ShipClass_Create("S")
    ship.GetImpulseEngineSubsystem().SetMaxSpeed(10.0)
    ship._current_speed = 5.0
    assert ship.GetImpulse() == pytest.approx(0.5)
    ship._current_speed = -10.0          # reverse: magnitude only, sign via IsReverse
    assert ship.GetImpulse() == pytest.approx(1.0)


def test_get_impulse_zero_without_max_speed():
    ship = ShipClass_Create("S")
    ship.GetImpulseEngineSubsystem().SetMaxSpeed(0.0)
    ship._current_speed = 5.0
    assert ship.GetImpulse() == 0.0      # no divide-by-zero, no stub


# ── CompleteStop ────────────────────────────────────────────────────────────
def test_complete_stop_halts_the_ship():
    ship = ShipClass_Create("S")
    ship._current_speed = 40.0
    ship.SetSpeed(40.0, TGPoint3(0, 1, 0), 0)
    ship.SetTargetAngularVelocityDirect(TGPoint3(1, 1, 1))
    ship._current_angular_velocity = TGPoint3(2, 2, 2)
    ship.CompleteStop()
    assert ship._current_speed == 0.0
    sp = ship.GetSpeedSetpoint()
    assert sp is not None and sp[0] == 0.0
    assert ship._current_angular_velocity.Length() == 0.0


# ── StopFiringWeapons ───────────────────────────────────────────────────────
def test_stop_firing_weapons_ceasefires_every_system():
    ship = ShipClass_Create("S")
    calls = []
    for getter in (ship.GetPhaserSystem, ship.GetTorpedoSystem,
                   ship.GetPulseWeaponSystem, ship.GetTractorBeamSystem):
        sys_ = getter()
        sys_.StopFiring = (lambda name: (lambda *a, **k: calls.append(name)))(
            sys_.GetName())
    ship.StopFiringWeapons()
    assert len(calls) == 4


# ── Net player id ───────────────────────────────────────────────────────────
def test_net_player_id_defaults_and_roundtrips():
    ship = ShipClass_Create("S")
    assert ship.GetNetPlayerID() == -1     # non-networked default
    ship.SetNetPlayerID(7)
    assert ship.GetNetPlayerID() == 7
