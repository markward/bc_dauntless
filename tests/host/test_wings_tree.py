"""The wrapped wing tree and its library modules (spec
2026-11-09-wing-leaders-phase-a-design.md §7, §10, §11): wing branches (ram,
flee, rejoin) above a ship's stock AI tree, driven by ConditionWing
conditions the brain pushes, and the stock SelectTarget nodes found in the
built tree and weighted for the wing.

Headless against real loadspacehelper ships and the SDK's BasicAttack."""
import pytest

pytest.importorskip("_dauntless_host")

import App  # noqa: E402
import loadspacehelper  # noqa: E402

from engine.appc import ai as aimod, ai_driver, ai_native  # noqa: E402
from engine.appc.sets import SetClass_Create  # noqa: E402
from engine.wings import brain, decisions, dials, roster, tree  # noqa: E402

AIC = App.ArtificialIntelligence
_STOCK_FACTORS = ("fDistanceFactor", "fInFrontFactor", "fIsTargetFactor",
                  "fShieldFactor", "fWeaponsFactor", "fHullFactor",
                  "fDamageFactor", "fPriorityFactor")


@pytest.fixture(autouse=True)
def _isolate():
    def _clear():
        App.g_kSetManager._sets.clear()
        roster.reset()
        dials.reset()
        decisions.reset_registry()
    _clear()
    yield
    _clear()


def _ship(pSet, kind, name, xyz):
    s = loadspacehelper.CreateShip(kind, pSet, name, None, 0, 0)
    s.SetTranslateXYZ(*xyz)
    return s


def _scene(n_members=3):
    """Akira members m1.. (m1 commands) with wrapped BasicAttack trees
    against one Bird of Prey, e1, 100 GU off."""
    import AI.Compound.BasicAttack
    pSet = SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "WingTest")
    ships = {"m%d" % i: _ship(pSet, "Akira", "m%d" % i,
                              (20.0 * (i - 1), 0.0, 0.0))
             for i in range(1, n_members + 1)}
    ships["e1"] = _ship(pSet, "BirdOfPrey", "e1", (100.0, 0.0, 0.0))
    group = App.ObjectGroup()
    group.AddName("e1")
    wing = roster.create_wing("blue", group)
    for i in range(1, n_members + 1):
        roster.add_member(wing, "m%d" % i)
    wing.chain = ["m1"]
    wing.commander = "m1"
    stock = {}
    for i in range(1, n_members + 1):
        s = ships["m%d" % i]
        stock[s.GetName()] = AI.Compound.BasicAttack.CreateAI(
            s, wing.target_group, Difficulty=0.5)
        s.SetAI(tree.wrap_tree(s, stock[s.GetName()], wing))
    return wing, ships, stock


def _branches(root):
    return dict(root._ais)


def _rejoin_ai(root):
    return _branches(root)[3].GetContainedAI().GetContainedAI()


def _activate_builders(ship):
    for a in ship.GetAI().GetAllAIsInTree():
        if isinstance(a, aimod.BuilderAI):
            ai_driver._activate_builder(a)


def _select_nodes(ship):
    return [a for a in ship.GetAI().GetAllAIsInTree()
            if isinstance(a, aimod.PreprocessingAI)
            and a.GetName() == "SelectTarget"]


# ── shape ──────────────────────────────────────────────────────────────────

def test_wrapped_tree_shape():
    wing, ships, stock = _scene()
    root = ships["m2"].GetAI()
    member = roster.member("m2")
    assert isinstance(root, aimod.PriorityListAI)
    assert [p for p, _a in root._ais] == [1, 2, 3, 4]
    b = _branches(root)
    assert b[4] is stock["m2"]
    for prio, kind in ((1, "ram"), (2, "flee"), (3, "rejoin")):
        cond_ai = b[prio]
        assert isinstance(cond_ai, aimod.ConditionalAI)
        (cond,) = cond_ai.GetConditions()
        assert cond.GetModuleName() == "Conditions.ConditionWing"
        assert cond.GetArguments() == ("m2", kind)
        assert member.conditions[kind] is cond
        assert cond.GetStatus() == 0
        fn = cond_ai.GetEvaluationFunction()
        assert ai_driver._memoisable_evalfunc(fn)
        assert fn(1) == AIC.US_ACTIVE and fn(0) == AIC.US_DORMANT
    ram = b[1].GetContainedAI()
    assert isinstance(ram, aimod.PlainAI) and ram.GetScriptModule() == "Ram"
    assert member.ram_script is ram.GetScriptInstance()
    flee = b[2].GetContainedAI()
    assert isinstance(flee, aimod.PlainAI) and flee.GetScriptModule() == "Flee"
    assert flee.GetScriptInstance().pFleeObjectGroup is wing.enemy_group
    avoid = b[3].GetContainedAI()
    assert isinstance(avoid, aimod.PreprocessingAI)
    assert avoid.GetName() == "AvoidObstacles"
    import AI.Preprocessors
    assert isinstance(avoid.GetPreprocessingInstance(),
                      AI.Preprocessors.AvoidObstacles)   # the engine's alias
    rejoin = avoid.GetContainedAI()
    assert isinstance(rejoin, aimod.PlainAI)
    assert rejoin.GetScriptModule() == "WingRejoin"
    import AI.PlainAI.FollowObject
    import AI.PlainAI.WingRejoin
    script = rejoin.GetScriptInstance()
    assert isinstance(script, AI.PlainAI.WingRejoin.WingRejoin)
    assert isinstance(script, AI.PlainAI.FollowObject.FollowObject)
    for node in [root, b[1], ram, b[2], flee, b[3], avoid, rejoin]:
        assert node.IsInterruptable() == 1


def test_condition_for_a_non_member_registers_nothing():
    pCond = App.ConditionScript_Create("Conditions.ConditionWing",
                                       "ConditionWing", "stranger", "rejoin")
    assert pCond._instance is not None       # the claimed module loaded
    assert pCond.GetStatus() == 0
    assert roster.member("stranger") is None


# ── conditions ─────────────────────────────────────────────────────────────

def test_condition_push_activates_branch():
    _wing, ships, _stock = _scene()
    root = ships["m2"].GetAI()
    rejoin_branch = _branches(root)[3]
    ai_driver.tick_ai(root, 1.0)
    assert rejoin_branch._status == AIC.US_DORMANT
    roster.member("m2").conditions["rejoin"].SetStatus(1)
    ai_driver.tick_ai(root, 2.0)
    assert rejoin_branch._status == AIC.US_ACTIVE
    assert _rejoin_ai(root).GetScriptInstance().pcFollowObjectName == "m1"


# ── SelectTarget discovery ─────────────────────────────────────────────────

def test_select_target_discovered_after_builder_activation():
    _wing, ships, _stock = _scene()
    member = roster.member("m2")
    assert tree.discover_select_nodes(ships["m2"], member) is False
    assert member.select_nodes == []
    _activate_builders(ships["m2"])
    nodes = _select_nodes(ships["m2"])
    assert nodes
    before = {f: getattr(nodes[0].GetPreprocessingInstance(), f)
              for f in _STOCK_FACTORS}
    assert tree.discover_select_nodes(ships["m2"], member) is True
    assert member.select_nodes == nodes
    inst = nodes[0].GetPreprocessingInstance()
    assert inst.fPopularityFactor == pytest.approx(-0.3)
    assert {f: getattr(inst, f) for f in _STOCK_FACTORS} == before
    # Found once: a second walk adds nothing.
    assert tree.discover_select_nodes(ships["m2"], member) is False
    assert member.select_nodes == nodes


def test_leaderless_wing_records_nodes_but_keeps_stock_weights():
    wing, ships, _stock = _scene()
    wing.leaderless = True
    member = roster.member("m2")
    _activate_builders(ships["m2"])
    nodes = _select_nodes(ships["m2"])
    stock_pop = nodes[0].GetPreprocessingInstance().fPopularityFactor
    assert tree.discover_select_nodes(ships["m2"], member) is True
    assert member.select_nodes == nodes
    assert nodes[0].GetPreprocessingInstance().fPopularityFactor == stock_pop


def test_select_target_stays_native():
    _wing, ships, _stock = _scene()
    member = roster.member("m2")
    _activate_builders(ships["m2"])
    assert tree.discover_select_nodes(ships["m2"], member)
    for node in member.select_nodes:
        inst = node.GetPreprocessingInstance()
        assert ai_native.preprocessor_is_stock(
            inst, "SelectTarget", ("GetTargetRating",))


def test_brain_tick_discovers_select_nodes_once_built():
    wing, ships, _stock = _scene()
    brain.tick_wing(wing)
    assert all(m.select_nodes == [] for m in wing.members.values())
    for s in ("m1", "m2", "m3"):
        _activate_builders(ships[s])
    brain.tick_wing(wing)
    for s in ("m1", "m2", "m3"):
        nodes = roster.member(s).select_nodes
        assert nodes == _select_nodes(ships[s])
        assert nodes[0].GetPreprocessingInstance().fPopularityFactor \
            == pytest.approx(-0.3)


# ── WingRejoin ─────────────────────────────────────────────────────────────

def test_rejoin_follows_handover():
    wing, ships, _stock = _scene()
    rejoin = _rejoin_ai(ships["m3"].GetAI())
    script = rejoin.GetScriptInstance()
    assert script.pcFollowObjectName == "m1"
    assert script.Update() == AIC.US_ACTIVE
    assert script.pcFollowObjectName == "m1"
    wing.commander = "m2"
    assert script.Update() == AIC.US_ACTIVE
    assert script.pcFollowObjectName == "m2"
    assert _rejoin_ai(ships["m3"].GetAI()) is rejoin      # no tree rebuild


def test_rejoin_ignores_a_set_target_broadcast():
    _wing, ships, _stock = _scene()
    rejoin = _rejoin_ai(ships["m3"].GetAI())
    rejoin.CallExternalFunction("SetTarget", "e1")
    script = rejoin.GetScriptInstance()
    script.Update()
    assert script.pcFollowObjectName == "m1"


def test_rejoin_without_a_commander_is_done():
    wing, ships, _stock = _scene()
    script = _rejoin_ai(ships["m3"].GetAI()).GetScriptInstance()
    wing.commander = None
    assert script.Update() == AIC.US_DONE


def test_rejoin_waits_while_the_commander_is_not_in_the_set():
    """FollowObject reports DONE when its object is gone, and a DONE PlainAI
    is latched for good. Between the commander leaving the set and the
    brain's next handover the branch must hold, not die."""
    wing, ships, _stock = _scene()
    script = _rejoin_ai(ships["m3"].GetAI()).GetScriptInstance()
    wing.commander = "gone"
    assert script.Update() == AIC.US_ACTIVE
    wing.commander = "m2"
    assert script.Update() == AIC.US_ACTIVE
    assert script.pcFollowObjectName == "m2"


def test_rejoin_hold_stops_the_ship():
    wing, ships, _stock = _scene()
    script = _rejoin_ai(ships["m3"].GetAI()).GetScriptInstance()
    ships["m3"].SetImpulse(1.0, App.TGPoint3_GetModelForward(),
                           App.PhysicsObjectClass.DIRECTION_MODEL_SPACE)
    assert ships["m3"].GetSpeedSetpoint()[0] > 0.0
    wing.commander = "gone"
    assert script.Update() == AIC.US_ACTIVE
    assert ships["m3"].GetSpeedSetpoint()[0] == 0.0


# ── weights: popularity only, saved, re-applied, restored ──────────────────

def test_weighting_touches_only_popularity():
    _wing, ships, _stock = _scene()
    member = roster.member("m2")
    _activate_builders(ships["m2"])
    inst = _select_nodes(ships["m2"])[0].GetPreprocessingInstance()
    inst.fDistanceFactor = 2.5                 # a mission's own weighting
    inst.fPopularityFactor = -0.7
    assert tree.discover_select_nodes(ships["m2"], member)
    assert inst.fDistanceFactor == 2.5
    assert inst.fPopularityFactor == pytest.approx(-0.3)


def test_leaderless_restores_the_saved_popularity():
    _wing, ships, _stock = _scene()
    _activate_builders(ships["m2"])
    inst = _select_nodes(ships["m2"])[0].GetPreprocessingInstance()
    inst.fPopularityFactor = -0.7
    brain.tick_wing(_wing)
    assert inst.fPopularityFactor == pytest.approx(-0.3)
    ships["m1"].SetDead()                      # the whole chain
    brain.tick_wing(_wing)
    assert _wing.leaderless is True
    assert inst.fPopularityFactor == pytest.approx(-0.7)


def test_tick_reapplies_the_popularity_dial():
    wing, ships, _stock = _scene()
    _activate_builders(ships["m2"])
    brain.tick_wing(wing)
    inst = roster.member("m2").select_nodes[0].GetPreprocessingInstance()
    dials._step("wing_popularity", +1)
    brain.tick_wing(wing)
    assert inst.fPopularityFactor == pytest.approx(dials.get("wing_popularity"))
    assert inst.fPopularityFactor == pytest.approx(-0.2)


def test_replaced_ai_is_rediscovered():
    import AI.Compound.BasicAttack
    wing, ships, _stock = _scene()
    _activate_builders(ships["m2"])
    brain.tick_wing(wing)
    old = list(roster.member("m2").select_nodes)
    assert old
    ships["m2"].SetAI(AI.Compound.BasicAttack.CreateAI(
        ships["m2"], wing.target_group, Difficulty=0.5))
    _activate_builders(ships["m2"])
    brain.tick_wing(wing)
    nodes = roster.member("m2").select_nodes
    assert nodes == _select_nodes(ships["m2"])
    assert not any(n is o for n in nodes for o in old)
    assert nodes[0].GetPreprocessingInstance().fPopularityFactor \
        == pytest.approx(-0.3)


def test_player_member_is_never_weighted():
    wing, ships, _stock = _scene()
    member = roster.member("m2")
    member.is_player = True
    _activate_builders(ships["m2"])
    stock_pop = _select_nodes(ships["m2"])[0] \
        .GetPreprocessingInstance().fPopularityFactor
    assert tree.discover_select_nodes(ships["m2"], member) is False
    brain.tick_wing(wing)
    assert member.select_nodes == []
    assert _select_nodes(ships["m2"])[0] \
        .GetPreprocessingInstance().fPopularityFactor == stock_pop


# ── stock detection ────────────────────────────────────────────────────────

@pytest.mark.parametrize("cls_name", ["ModSelectTarget", "SelectTarget"])
def test_mod_select_target_subclass_is_not_stock(cls_name):
    import AI.Preprocessors
    wing, ships, _stock = _scene()
    mod_cls = type(cls_name, (AI.Preprocessors.SelectTarget,), {})
    node = App.PreprocessingAI_Create(ships["m2"], "SelectTarget")
    node.SetPreprocessingMethod(mod_cls(wing.target_group), "Update")
    root = App.PriorityListAI_Create(ships["m2"], "ModRoot")
    root.AddAI(node, 1)
    ships["m2"].SetAI(root)
    member = roster.member("m2")
    assert tree.discover_select_nodes(ships["m2"], member) is False
    assert member.select_nodes == []
