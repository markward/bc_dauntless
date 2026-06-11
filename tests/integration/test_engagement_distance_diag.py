"""Diagnostic (C): measure the engagement distance a NonFedAttack AI ship
actually settles at against a stationary target, driving the real GameLoop
(AI + proximity + ship motion) headlessly.

SDK NonFedAttack range bands: close=100 GU (17.5 km), mid=200 GU (35 km),
long=350 GU (61 km). User wants combat held at ~15-25 km = ~85-143 GU.

Run with:  uv run pytest tests/integration/test_engagement_distance_diag.py -s -q
"""
import importlib
import sys

import pytest
import App
from engine.appc.ships import ShipClass_Create
from engine.appc.math import TGPoint3
from engine.appc.subsystems import HullSubsystem
from engine.core.game import Game, Episode, Mission, _set_current_game
from engine.core.loop import GameLoop


def _load_galaxy(ship):
    App.g_kModelPropertyManager.ClearLocalTemplates()
    mod_name = "ships.Hardpoints.galaxy"
    if mod_name in sys.modules:
        importlib.reload(sys.modules[mod_name])
    else:
        importlib.import_module(mod_name)
    mod = sys.modules[mod_name]
    mod.LoadPropertySet(ship.GetPropertySet())
    ship.SetupProperties()


@pytest.fixture
def game_context():
    mission = Mission()
    mission.SetScript("tests.integration.test_engagement_distance_diag")
    episode = Episode(); episode.SetCurrentMission(mission)
    game = Game(); game.SetCurrentEpisode(episode)
    _set_current_game(game)
    yield
    _set_current_game(None)


@pytest.fixture(autouse=True)
def _isolate():
    from engine.appc import projectiles
    projectiles._active.clear()
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()
    yield
    projectiles._active.clear()
    App.g_kSetManager._sets.clear()
    App.g_kModelPropertyManager.ClearLocalTemplates()
    for k in list(sys.modules):
        if k == "ships" or k.startswith("ships."):
            del sys.modules[k]


def test_engagement_distance_trajectory(game_context):
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet

    attacker = ShipClass_Create("Galaxy")
    _load_galaxy(attacker)
    attacker.SetWorldLocation(TGPoint3(0, 0, 0))
    attacker.SetAlertLevel(attacker.RED_ALERT)
    pSet.AddObjectToSet(attacker, "Attacker")

    start = 300.0
    target = ShipClass_Create("Target")
    thull = HullSubsystem("Hull"); thull.SetMaxCondition(1e6)
    target._hull = thull
    target.SetWorldLocation(TGPoint3(0, start, 0))
    target._radius = 20.0
    type(target).GetRadius = lambda self: self._radius
    pSet.AddObjectToSet(target, "Target")

    import AI.Compound.NonFedAttack as non_fed_attack
    builder = non_fed_attack.CreateAI(attacker, "Target")
    attacker.SetAI(builder)

    loop = GameLoop()
    ies = attacker.GetImpulseEngineSubsystem()
    max_speed = ies.GetMaxSpeed() if ies is not None else None
    print(f"\n[diag] Galaxy IES max speed = {max_speed} GU/s; start dist = {start} GU")

    samples = []
    for step in range(3000):          # 50 s of sim @ 60 Hz
        loop.tick()
        if step % 300 == 0:           # every 5 s
            d = (target.GetWorldLocation() - attacker.GetWorldLocation()).Length()
            samples.append((step / 60.0, d))

    closest = min(d for _, d in samples)
    final = samples[-1][1]
    print(f"\n[diag] closest = {closest:.1f} GU ({closest*0.175:.2f} km); "
          f"final = {final:.1f} GU ({final*0.175:.2f} km)")

    # Pursuit regression guard: a NonFedAttack ship starting at 300 GU must
    # close into combat range. The ICO settles ~115-140 GU (~20-24 km),
    # inside the desired 15-25 km band; assert it reaches at most 160 GU
    # (28 km) so a regression that breaks pursuit/closing is caught.
    assert closest < 160.0, (
        f"AI ship failed to close to combat range; closest={closest:.1f} GU"
    )
