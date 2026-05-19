"""Unit tests for SDK AI.Preprocessors.SelectTarget.GetTargetRating.

Load the real class via _SDKFinder; build a minimal PreprocessingAI
shell with the SelectTarget as preprocess; exercise GetTargetRating
with controlled targets and assert each factor moves the rating
in the expected direction."""
import pytest

import App
from engine.appc.ai import PreprocessingAI_Create
from engine.appc.events import TGEvent_Create
from engine.appc.objects import ObjectGroup
from engine.appc.ships import ShipClass_Create, ShipClass
from engine.appc.subsystems import HullSubsystem, ShieldSubsystem


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def _make_select_target(our_ship, *target_names):
    """Construct a real SDK SelectTarget with our_ship as the
    pCodeAI's ship."""
    from AI.Preprocessors import SelectTarget
    pp = PreprocessingAI_Create(our_ship, "TestSel")
    grp = ObjectGroup()
    for n in target_names:
        grp.AddName(n)
    inst = SelectTarget(grp)
    inst.pCodeAI = pp
    # SDK normally seeds dDamageReceived inside CodeAISet / DamageEvent, both
    # of which require the optimized C++ Update path. Initialize it directly
    # so GetTargetRating's `has_key` check has a real dict to query.
    inst.dDamageReceived = {}
    pp.SetPreprocessingMethod(inst, "Update")
    return inst, pp


def _make_target_ship_at(name, x, y, z, *, hull_max=10000.0):
    pSet = App.g_kSetManager.GetSet("S")
    if pSet is None:
        pSet = App.SetClass_Create(); pSet.SetName("S")
        App.g_kSetManager._sets["S"] = pSet
    t = ShipClass()
    t.SetTranslateXYZ(x, y, z)
    hull = HullSubsystem("Hull"); hull.SetMaxCondition(hull_max)
    t._hull = hull
    # SDK GetTargetRating blindly calls pShip.GetShields().GetShieldPercentage();
    # give every target a default (full) shield so the call doesn't NPE.
    # Tests that care about shield deltas overwrite this.
    ss = ShieldSubsystem("S")
    from engine.appc.properties import ShieldProperty as _SP
    for _f in range(_SP.NUM_SHIELDS):
        ss.SetMaxShields(_f, 100.0)
        ss.SetCurrentShields(_f, 100.0)
    t._shield_subsystem = ss
    pSet.AddObjectToSet(t, name)
    return t


def test_closer_target_rates_higher_than_farther():
    """Distance factor (positive weight) → closer is better."""
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours.SetTranslateXYZ(0, 0, 0)
    pSet.AddObjectToSet(ours, "Ours")
    close = _make_target_ship_at("Close", 0, 50, 0)
    far = _make_target_ship_at("Far", 0, 500, 0)

    inst, _pp = _make_select_target(ours, "Close", "Far")
    rating_close = inst.GetTargetRating(close)
    rating_far = inst.GetTargetRating(far)
    assert rating_close > rating_far


def test_in_front_target_rates_higher_than_behind():
    """Ship at origin facing +Y. Target at +Y rates higher than target
    at -Y (other factors equal)."""
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours.SetTranslateXYZ(0, 0, 0)
    pSet.AddObjectToSet(ours, "Ours")
    ahead = _make_target_ship_at("Ahead", 0, 100, 0)
    behind = _make_target_ship_at("Behind", 0, -100, 0)

    inst, _ = _make_select_target(ours, "Ahead", "Behind")
    assert inst.GetTargetRating(ahead) > inst.GetTargetRating(behind)


def test_target_with_lower_shields_rates_higher_under_default_weights():
    """Shield factor weight is NEGATIVE (-0.2) by default — lower
    shields → less subtraction → higher rating."""
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours.SetTranslateXYZ(0, 0, 0)
    pSet.AddObjectToSet(ours, "Ours")
    from engine.appc.subsystems import ShieldSubsystem
    from engine.appc.properties import ShieldProperty
    full = _make_target_ship_at("Full", 0, 100, 0)
    low = _make_target_ship_at("Low", 0, 100, 0)
    for ship, frac in ((full, 1.0), (low, 0.1)):
        ss = ShieldSubsystem("S")
        for f in range(ShieldProperty.NUM_SHIELDS):
            ss.SetMaxShields(f, 100.0)
            ss.SetCurrentShields(f, 100.0 * frac)
        ship._shield_subsystem = ss

    inst, _ = _make_select_target(ours, "Full", "Low")
    assert inst.GetTargetRating(low) > inst.GetTargetRating(full)


def test_damage_dealt_to_us_boosts_target_rating():
    """fDamage factor (positive weight 1.0) — targets that have damaged
    us recently rate higher."""
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours.SetTranslateXYZ(0, 0, 0)
    ours._hull = HullSubsystem("OursHull"); ours._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(ours, "Ours")
    aggro = _make_target_ship_at("Aggro", 0, 100, 0)
    peaceful = _make_target_ship_at("Peaceful", 0, 100, 0)

    inst, _ = _make_select_target(ours, "Aggro", "Peaceful")
    # Simulate damage from Aggro into our running total.
    inst.dDamageReceived = {aggro.GetObjID(): 0.5}
    assert inst.GetTargetRating(aggro) > inst.GetTargetRating(peaceful)


def test_priority_info_boosts_target_rating():
    """fPriority factor (positive weight 1.0) — ObjectGroupWithInfo
    targets with a Priority key in their info dict rate higher."""
    from engine.appc.objects import ObjectGroupWithInfo
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours.SetTranslateXYZ(0, 0, 0)
    pSet.AddObjectToSet(ours, "Ours")
    vip = _make_target_ship_at("VIP", 0, 100, 0)
    grunt = _make_target_ship_at("Grunt", 0, 100, 0)

    from AI.Preprocessors import SelectTarget
    pp = PreprocessingAI_Create(ours, "TestSel")
    grp = ObjectGroupWithInfo()
    grp.AddNameAndInfo("VIP", {"Priority": 10.0})
    grp.AddNameAndInfo("Grunt", {})
    inst = SelectTarget(grp); inst.pCodeAI = pp
    inst.dDamageReceived = {}
    pp.SetPreprocessingMethod(inst, "Update")

    assert inst.GetTargetRating(vip) > inst.GetTargetRating(grunt)


def test_current_target_gets_is_target_bonus():
    """fIsTarget factor (positive weight 1.0) — when the ship's current
    target matches the rated target, rating gets a boost."""
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours.SetTranslateXYZ(0, 0, 0)
    pSet.AddObjectToSet(ours, "Ours")
    current = _make_target_ship_at("Current", 0, 100, 0)
    other = _make_target_ship_at("Other", 0, 100, 0)
    ours.SetTarget(current)

    inst, _ = _make_select_target(ours, "Current", "Other")
    inst.bSetShipTarget = 1
    assert inst.GetTargetRating(current) > inst.GetTargetRating(other)


def test_rating_returns_minus_one_when_ship_is_none():
    """SDK contract: pCodeAI.GetShip() returning None → rating -1.0."""
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    target = _make_target_ship_at("X", 0, 100, 0)

    from AI.Preprocessors import SelectTarget
    pp = PreprocessingAI_Create(None, "TestSel")
    grp = ObjectGroup(); grp.AddName("X")
    inst = SelectTarget(grp); inst.pCodeAI = pp
    assert inst.GetTargetRating(target) == -1
