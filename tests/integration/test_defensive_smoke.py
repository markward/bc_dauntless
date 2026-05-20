"""Activation smoke for AI.PlainAI.Defensive.

SDK requires SetEnemyName(s).

Fixture correction: Defensive.Update reads pShip.GetShields().GetCurShields(face)
for all 6 faces to pick its strongest-shield direction. Without a
ShieldSubsystem attached, GetShields() returns None and Update crashes with
AttributeError. The smoke attaches a ShieldSubsystem with all faces seeded."""
import pytest

import App
from engine.appc.ai import PlainAI_Create, ArtificialIntelligence
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem, ShieldSubsystem


_VALID_STATUS = (
    ArtificialIntelligence.US_ACTIVE,
    ArtificialIntelligence.US_DONE,
    ArtificialIntelligence.US_DORMANT,
    ArtificialIntelligence.US_INVALID,
)


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def test_defensive_update_returns_valid_status():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours._hull = HullSubsystem("H")
    ours._hull.SetMaxCondition(1000.0)
    shields = ShieldSubsystem("Sh")
    for face in range(ShieldSubsystem.NUM_SHIELDS):
        shields.SetMaxShields(face, 100.0)
    ours.SetShieldSubsystem(shields)
    pSet.AddObjectToSet(ours, "Ours")
    enemy = ShipClass(); enemy.SetTranslateXYZ(0, 100, 0)
    enemy._hull = HullSubsystem("H"); enemy._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(enemy, "Enemy")

    plain = PlainAI_Create(ours, "TestAI")
    plain.SetScriptModule("Defensive")
    inst = plain.GetScriptInstance()
    inst.SetEnemyName("Enemy")
    result = inst.Update()
    assert isinstance(result, int)
    assert result in _VALID_STATUS
