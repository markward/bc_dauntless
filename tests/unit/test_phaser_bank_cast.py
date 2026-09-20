"""App.PhaserBank_Cast — heatmap ranks 7-10/61 (23,864 hits).

Two SDK consumers, both silently wrong without it:
  * AI/PlainAI/PhaserSweep.py:52 builds lpPhaserBanks from the cast; a
    stub's CalculateRoughDirection().Dot() is a stub, `stub > fSweepDot`
    is False, so the sweep never picked a bank and always nosed onto the
    target.
  * Conditions/ConditionInPhaserFiringArc.py:173 — stub.CanFire() and
    stub.CanHit() are truthy, so the condition read TRUE forever and
    FedAttack's TorpsReadyAndNotInEnemyFiringArc branch was permanently
    dormant."""
import App
from engine.appc.ai import ConditionScript_Create
from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem
from engine.appc.weapon_subsystems import PhaserSystem, PhaserBank, TorpedoSystem
import pytest


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def test_cast_is_real_and_type_checks():
    assert not isinstance(App.PhaserBank_Cast, App._NamedStub)
    bank = PhaserBank("Fwd")
    assert App.PhaserBank_Cast(bank) is bank
    assert App.PhaserBank_Cast(PhaserSystem("P")) is None
    assert App.PhaserBank_Cast(TorpedoSystem("T")) is None
    assert App.PhaserBank_Cast(None) is None


def _ship_with_forward_bank(pSet, name, x, y, z):
    """Same bank authoring as tests/unit/test_phaser_can_hit.py::_forward_bank,
    on a real ShipClass: forward-facing, +-50deg width, 100 GU range.

    Registers the bank through the real ShipClass surface
    (SetPhaserSystem -> GetPhaserSystem), not an ad hoc `._phaser`
    attribute: ConditionInPhaserFiringArc.CheckState (the SDK code under
    test) reaches the weapon system via `pShip.GetPhaserSystem()`, and
    that getter reads `self._phaser_system`, which only SetPhaserSystem
    populates (engine/appc/ships.py:986-987). A few other smoke tests
    stash a `._phaser` attribute instead, but nothing in engine/ reads
    that name back -- it's dead for this ship type, so it would leave
    GetPhaserSystem() at None and CheckState's `if pPhaserSystem:` guard
    would never traverse into the bank at all, passing this test
    vacuously (bState stays 0) rather than for the reason under test.
    AddChildSubsystem only wires `_parent_subsystem`, not `_parent_ship`
    (subsystems.py:984), so the bank's `_parent_ship` -- read directly by
    PhaserBank.CanHit via GetParentShip() -- is still set explicitly.
    """
    from engine.appc.properties import PhaserProperty
    s = ShipClass(); s.SetTranslateXYZ(x, y, z)
    s._hull = HullSubsystem("H"); s._hull.SetMaxCondition(1000.0)
    phasers = PhaserSystem("P")
    bank = PhaserBank("Fwd"); bank._parent_ship = s
    prop = PhaserProperty("Fwd")
    prop.SetPosition(0.0, 0.0, 0.0)
    prop.SetOrientation(TGPoint3(0.0, 1.0, 0.0), TGPoint3(0.0, 0.0, 1.0))
    prop.SetArcWidthAngles(-0.872665, 0.872665)
    prop.SetArcHeightAngles(-0.052360, 1.047198)
    prop.SetMaxDamageDistance(100.0)
    bank.SetProperty(prop)
    phasers.AddChildSubsystem(bank)
    s.SetPhaserSystem(phasers)
    pSet.AddObjectToSet(s, name)
    return s, bank


def test_condition_in_phaser_firing_arc_reads_false_out_of_arc():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    enemy, bank = _ship_with_forward_bank(pSet, "Enemy", 0, 0, 0)
    ours = ShipClass(); ours.SetTranslateXYZ(0, -2000, 0)   # dead astern of Enemy
    ours._hull = HullSubsystem("H"); ours._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(ours, "Ours")
    # Precondition: the real bank says the point astern is NOT hittable.
    assert bank.CanHit(ours.GetWorldLocation()) == 0

    # Constructor args after pCodeCondition are (sTargetName,
    # sPhaserObjectName, bOnlyDangerousArcs, ...) --
    # Conditions/ConditionInPhaserFiringArc.py:16 -- confirmed against
    # tests/unit/test_condition_external_functions.py's
    # _REAL_CONDITIONS entry: ("Enemy-1", "Friend-1", 0). bOnlyDangerousArcs
    # is required (no default), so it must be passed explicitly; 0 means
    # CanFire() is never consulted (`(not self.bDangerousOnly) or
    # pBank.CanFire()` short-circuits), which is what lets this test
    # isolate CanHit/arc geometry rather than power/charge state.
    cond = ConditionScript_Create(
        "Conditions.ConditionInPhaserFiringArc", "ConditionInPhaserFiringArc",
        "Ours", "Enemy", 0)
    assert cond._instance is not None, cond._init_error
    # Both ships are already in the same set at construction time, so
    # ConditionInPhaserFiringArc.__init__ already ran CheckState(pTarget,
    # pPhaserObject) once (SDK line ~34-36). Calling `cond._instance
    # .CheckState()` with no arguments -- CheckState takes two required
    # positional args -- would raise TypeError; SetActive() re-derives
    # the same two objects and calls the real CheckState(pTarget,
    # pPhaserObject) again, which is the supported re-evaluation path.
    cond.SetActive()
    assert cond.GetStatus() == 0, (
        "condition reads in-arc for a target the bank cannot hit — "
        "PhaserBank_Cast handed back a truthy stub")
