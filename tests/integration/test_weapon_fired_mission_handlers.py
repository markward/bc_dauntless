"""The SDK's mission WeaponFired handlers (E1M2.py:1384, E2M1.py:963) read the
shot's target with ShipClass_Cast(pEvent.GetObjPtr()) and return when it is
None -- so before ET_WEAPON_FIRED carried its target they never got past that
line.  Fire the player's real phaser bank (its fire effect) at a ship and assert what the
handlers do PAST the early return."""
import App
from engine import host_loop
from engine.core.loop import GameLoop
from tests.integration.test_sdk_bridge_load import _fresh_world

E1M2_MODULE = "Maelstrom.Episode1.E1M2.E1M2"
E2M1_MODULE = "Maelstrom.Episode2.E2M1.E2M1"


def _first_bank(ship):
    system = ship.GetPhaserSystem()
    system.TurnOn()
    bank = system.GetChildSubsystem(0)
    bank._charge_level = bank._max_charge
    return bank


def _fire_and_dispatch(ship, target):
    from engine.appc import weapon_subsystems as ws
    bank = _first_bank(ship)
    # The edge's event (the arc test is not under test here): the beam's
    # was-not-firing edge is the native kernel's since fire control went
    # native only (M3), and its delivery posts ET_WEAPON_FIRED through this.
    ws._post_weapon_fired(bank, target)
    GameLoop().advance(2)           # the queued event dispatches


def test_e1m2_weapon_fired_counts_the_players_shot_at_a_ship():
    _fresh_world()
    mission, episode, game, mod = host_loop._init_mission(E1M2_MODULE)
    pSet = App.g_kSetManager.GetSet("Vesuvi6")
    mod.CreateMovingAsteroids()
    rock = App.ShipClass_GetObject(pSet, sorted(mod.g_dAsteroidInfo.keys())[0])
    player = App.Game_GetCurrentPlayer()
    assert player.GetName() == "player" and rock is not None
    mod.g_bHavenSecondHail = mod.TRUE
    before = mod.g_iNumberTimesWeaponFired
    _fire_and_dispatch(player, rock)
    assert mod.g_iNumberTimesWeaponFired == before + 1


def _ship_named(name):
    for pSet in App.g_kSetManager._sets.values():
        obj = pSet.GetObject(name)
        if obj is not None:
            return obj
    return None


def test_e2m1_warbird_firing_at_the_karoon_triggers_the_attack_beat():
    _fresh_world()
    mission, episode, game, mod = host_loop._init_mission(E2M1_MODULE)
    if _ship_named("Warbird") is None:
        mod.CreateBeolShips()
    warbird, karoon = _ship_named("Warbird"), _ship_named("Karoon")
    assert warbird is not None and karoon is not None
    called = []
    mod.WarbirdAttacksKaroon = lambda: called.append(1)
    mod.g_bWarbirdAttacksKaroon = mod.FALSE
    # A disruptor (pulse) fires: the handler's Cast of the source must pass.
    cannon = warbird.GetPulseWeaponSystem().GetChildSubsystem(0)
    cannon._charge_level = cannon._max_charge
    cannon._cooldown_remaining = 0.0
    from engine.appc import weapon_subsystems as ws
    # The bolt's event, as the SPAWN delivery posts it once the bolt exists
    # (the cannon's launch is the kernel's: fire control native only, M3).
    ws._post_weapon_fired(cannon, karoon)
    GameLoop().advance(2)
    assert called == [1]
