"""End-to-end fire diagnostic: real Galaxy hardpoint × BasicAttack AI.

User reports: even after Slices G/H/I land ('movement is more
significant now') hostile ships in M3Gameflow still don't fire.
That mission uses two Galaxy ships running BasicAttack
(→ FedAttack subtree, since Federation). This test does the same
setup via loadspacehelper.CreateShip + FedAttack so we can trace
exactly which firing gate is closed.

The test asserts nothing — it prints a per-second snapshot of
phaser state and at the end reports whether ANY bank ever entered
_firing. Run with `-s` to see.
"""
import App
import pytest

from engine.core.game import Game, Episode, Mission, _set_current_game
from engine.core.loop import GameLoop


@pytest.fixture
def game_context():
    mission = Mission()
    mission.SetScript("tests.integration.test_galaxy_combat_fire_diagnostic")
    episode = Episode()
    episode.SetCurrentMission(mission)
    game = Game()
    game.SetCurrentEpisode(episode)
    _set_current_game(game)
    yield
    _set_current_game(None)


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()
    App.g_kTimerManager._time = 0.0
    App.g_kRealtimeTimerManager._time = 0.0


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def _walk_phaser_banks(ship):
    sys_ = ship.GetPhaserSystem()
    if sys_ is None:
        return []
    return [sys_.GetWeapon(i) for i in range(sys_.GetNumWeapons())]


def _bank_snapshot(bank):
    return {
        "name": getattr(bank, "_name", "?"),
        "firing": bool(bank.IsFiring()),
        "charge": round(getattr(bank, "_charge_level", -1.0), 2),
        "min":    round(getattr(bank, "_min_firing_charge", -1.0), 2),
        "max":    round(getattr(bank, "_max_charge", -1.0), 2),
        "armed":  getattr(bank, "_armed", "?"),
    }


def test_galaxy_vs_galaxy_fire_trace(game_context):
    import loadspacehelper
    import AI.Compound.BasicAttack as basic_attack

    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet

    # Both Galaxy ships, 150 m apart on Y (inside MidRange threshold
    # of 200 m so FireScript dispatches phaser/torp). CreateShip
    # applies the Galaxy hardpoint (galaxy.py) which populates
    # PhaserSystem with the 8 bank banks and full charge.
    attacker = loadspacehelper.CreateShip("Galaxy", pSet, "Galaxy 2", None, 0, 0)
    attacker.SetTranslateXYZ(0.0, 0.0, 0.0)
    target = loadspacehelper.CreateShip("Galaxy", pSet, "Galaxy 1", None, 0, 0)
    target.SetTranslateXYZ(0.0, 150.0, 0.0)

    attacker.SetAI(basic_attack.CreateAI(attacker, "Galaxy 1"))
    target.SetAI(basic_attack.CreateAI(target, "Galaxy 2"))

    print("\n=== Galaxy combat fire trace ===")
    print(f"Attacker phaser system on (t=0, pre-tick): {bool(attacker.GetPhaserSystem().IsOn())}")
    print(f"Attacker alert level (t=0, pre-tick): {attacker.GetAlertLevel()}")
    print(f"Bank inventory (Attacker): "
          f"{[b._name for b in _walk_phaser_banks(attacker)]}")

    loop = GameLoop()
    any_fired = False
    for sec in range(1, 11):  # 10 seconds
        loop.advance(60)
        a_banks = [_bank_snapshot(b) for b in _walk_phaser_banks(attacker)]
        t_banks = [_bank_snapshot(b) for b in _walk_phaser_banks(target)]
        for b in a_banks + t_banks:
            if b["firing"]:
                any_fired = True
        # Just print first bank's state on each side per second.
        a = a_banks[0] if a_banks else {}
        t = t_banks[0] if t_banks else {}
        print(f"  t={sec}s  A.{a.get('name')}: firing={a.get('firing')} "
              f"charge={a.get('charge')}/{a.get('max')} (min={a.get('min')}) "
              f"armed={a.get('armed')}  ||  "
              f"T.{t.get('name')}: firing={t.get('firing')} "
              f"charge={t.get('charge')}/{t.get('max')} (min={t.get('min')}) "
              f"armed={t.get('armed')}")

    print(f"Attacker phaser system on (t=10): {bool(attacker.GetPhaserSystem().IsOn())}")
    print(f"Attacker alert level (t=10): {attacker.GetAlertLevel()}")
    print(f"Distance at t=10: "
          f"{((target.GetWorldLocation().x - attacker.GetWorldLocation().x)**2 + (target.GetWorldLocation().y - attacker.GetWorldLocation().y)**2 + (target.GetWorldLocation().z - attacker.GetWorldLocation().z)**2)**0.5:.1f} m")

    # Walk the AI tree, find FireScript preprocessors, report their state.
    from engine.appc.ai import PreprocessingAI
    for ship_name, ship in (("Attacker", attacker), ("Target", target)):
        ai = ship.GetAI()
        if ai is None:
            continue
        for node in ai.GetAllAIsInTree():
            if isinstance(node, PreprocessingAI):
                inst = node._preprocessing_instance
                if inst is not None and hasattr(inst, "lWeapons"):
                    print(f"  [{ship_name}] FireScript {node.GetName()!r}  "
                          f"target={getattr(inst, 'sTarget', '?')!r}  "
                          f"bTargetVisible={getattr(inst, 'bTargetVisible', '?')}  "
                          f"iLastUpdate={getattr(inst, 'iLastUpdate', '?')}  "
                          f"len(lWeapons)={len(getattr(inst, 'lWeapons', []))}  "
                          f"bEnabled={getattr(inst, 'bEnabled', '?')}")
    print(f"\n=== ANY bank ever fired: {any_fired} ===")
