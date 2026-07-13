"""QuickBattle: shooting a FRIENDLY ship makes the XO scold you.

This is the live scenario end to end — boot the real QuickBattle mission, add a
friendly ship the way QuickBattle's ship generator does (name into the mission's
friendly group), shoot it, and assert the XO's "DontShoot4" line is registered
as the "FriendlyFireWarning" action.

It guards the WHOLE chain, which had two independent breaks:

1. WeaponHitEvent.GetWeaponType() was a _Stub, so MissionLib:3718's tractor
   exclusion swallowed every hit and the accumulator never moved.
2. UtopiaModule's friendly-fire tolerance defaulted to 0. MissionLib:3727 is
   `if total >= tolerance: GAME_OVER elif <crossed a warning point>: REPORT` —
   with a 0 tolerance the FIRST branch always wins, so the REPORT (the event
   QuickBattle's warning handler listens for) was unreachable. QuickBattle never
   calls SetMaxFriendlyFire; it relies on the engine default, which a real BC
   save from E8M1 (a mission that sets neither value) pins at 5000.0 /
   300.0 warning points — docs/original_game_reference/engine/bcs-save-format.md.

Shooting ENEMIES never warns, in BC or here: QuickBattle's friendly group holds
only the player and ships added on the Friendly side (QuickBattle.py:2778-2782).
"""
import pytest

import App
from engine.appc import combat
from engine.appc.math import TGPoint3
from engine.core.loop import GameLoop


def _boot_quickbattle(monkeypatch):
    from tests.host.test_quickbattle_boot import _fresh_quickbattle_loader
    hl, controller = _fresh_quickbattle_loader(monkeypatch)
    controller.session = controller.loader.load_quickbattle()
    return controller


def _friendly_target(player, name="Akira-1"):
    """A friendly ship, created and named into the mission's friendly group —
    what QuickBattle's generator does for a ship added on the Friendly side."""
    import MissionLib
    import loadspacehelper
    ship = loadspacehelper.CreateShip("Akira", player.GetContainingSet(), name, "")
    MissionLib.GetMission().GetFriendlyGroup().AddName(name)
    return ship


def _shoot(player, target, weapon_type="phaser", damage=100.0, shots=1):
    for _ in range(shots):
        combat.apply_hit(target, damage=damage,
                         hit_point=TGPoint3(0.0, 1.0, 0.0), source=player,
                         weapon_type=weapon_type)


@pytest.fixture
def battle(monkeypatch):
    """Booted QuickBattle, past the XO's 5-second silence gate
    (FriendlyFireWarningHandler bails while GameTime - GetLastTalkTime < 5)."""
    pytest.importorskip("_dauntless_host")
    import MissionLib

    controller = _boot_quickbattle(monkeypatch)
    loop = GameLoop()
    for _ in range(60 * 8):
        loop.tick()

    actions = []
    real_register = App.TGActionManager_RegisterAction
    monkeypatch.setattr(
        App, "TGActionManager_RegisterAction",
        lambda action, name: (actions.append(name), real_register(action, name))[1])

    player = MissionLib.GetPlayer()
    App.g_kUtopiaModule.SetCurrentFriendlyFire(0.0)
    yield player, actions
    App.g_kUtopiaModule.SetCurrentFriendlyFire(0.0)
    del controller


def test_shooting_a_friendly_in_quickbattle_makes_the_xo_object(battle):
    player, actions = battle
    friend = _friendly_target(player)

    # QuickBattle warns at 300 damage points (QuickBattle.py:770).
    _shoot(player, friend, "phaser", damage=100.0, shots=4)

    assert "FriendlyFireWarning" in actions, (
        "XO said nothing after 400 points of friendly fire; "
        "friendly fire total = %r, tolerance = %r"
        % (App.g_kUtopiaModule.GetCurrentFriendlyFire(),
           App.g_kUtopiaModule.GetFriendlyFireTolerance()))


def test_shooting_an_enemy_in_quickbattle_stays_silent(battle):
    """The other half: enemies are not in the friendly group, so no warning —
    stock BC behaviour, and the reason 'fire on enemies' never reproduced this."""
    player, actions = battle
    import loadspacehelper
    enemy = loadspacehelper.CreateShip("Galor", player.GetContainingSet(),
                                       "Galor-1", "")
    _shoot(player, enemy, "phaser", damage=100.0, shots=10)

    assert "FriendlyFireWarning" not in actions
    assert App.g_kUtopiaModule.GetCurrentFriendlyFire() == 0.0


def test_tractoring_a_friendly_in_quickbattle_stays_silent(battle):
    """The tractor exclusion survives the fix: you tow friendlies."""
    player, actions = battle
    friend = _friendly_target(player, "Akira-2")
    _shoot(player, friend, "tractor", damage=100.0, shots=10)

    assert "FriendlyFireWarning" not in actions
    assert App.g_kUtopiaModule.GetCurrentFriendlyFire() == 0.0
