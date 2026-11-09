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
    return _branches(root)[9].GetContainedAI().GetContainedAI()


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
    assert [p for p, _a in root._ais] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    b = _branches(root)
    assert b[10] is stock["m2"]
    for prio, kind in ((1, "ram"), (2, "flee"), (9, "rejoin")):
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
    avoid = b[9].GetContainedAI()
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
    for node in [root, b[1], ram, b[2], flee, b[9], avoid, rejoin]:
        assert node.IsInterruptable() == 1


def test_condition_for_a_non_member_registers_nothing():
    pCond = App.ConditionScript_Create("Conditions.ConditionWing",
                                       "ConditionWing", "stranger", "rejoin")
    assert pCond._instance is not None       # the claimed module loaded
    assert pCond.GetStatus() == 0
    assert roster.member("stranger") is None


# ── phase C: reserve + attack branches ─────────────────────────────────────

def test_wrap_tree_branch_order_c():
    _wing, ships, stock = _scene()
    root = ships["m2"].GetAI()
    names = [a.GetName() for _p, a in root._ais]
    assert names[:9] == ["WingRam", "WingFlee", "WingWithdraw", "WingHold",
                         "WingGuard", "WingFallback", "WingReserve",
                         "WingAttack", "WingRejoin"]
    assert root._ais[9][1] is stock["m2"]
    b = _branches(root)
    attack = b[8].GetContainedAI()
    assert attack.GetName() == "WingFire"
    assert attack.GetContainedAI().GetName() == "AvoidObstacles"
    assert attack.GetContainedAI().GetContainedAI().GetScriptModule() \
        == "WingMoveTo"
    reserve = b[7].GetContainedAI()
    assert reserve.GetName() == "AvoidObstacles"
    assert reserve.GetContainedAI().GetScriptModule() == "WingMoveTo"


def test_attack_branch_holds_stock_firescript_with_weapons():
    import AI.Preprocessors
    _wing, ships, _stock = _scene()
    member = roster.member("m2")
    fs = member.fire_script
    assert type(fs) is AI.Preprocessors.FireScript
    assert len(fs.lWeapons) >= 1
    assert fs.lTargetSubsystems == []
    assert not fs.HasSubsystemTargets()
    fs.RestoreSubsystemTargets()
    assert fs.HasSubsystemTargets()
    from engine.appc import ai_optimized
    assert ai_native.preprocessor_is_stock(fs, "FireScript",
                                           ai_optimized._FIRE_METHODS)
    node = _branches(ships["m2"].GetAI())[8].GetContainedAI()
    # the node binds a non-lethal alias that shares the instance's state
    assert node.GetPreprocessingInstance().__dict__ is fs.__dict__


def test_fire_keywords_from_difficulty():
    import AI.Compound.BasicAttack as BA
    kw = tree.fire_keywords(1.0)
    assert kw["Difficulty"] == 1.0
    assert any(k in kw for k in BA.g_lAllFlags)
    assert tree.fire_keywords(None)["Difficulty"] == 0.5


# ── conditions ─────────────────────────────────────────────────────────────

def test_condition_push_activates_branch():
    _wing, ships, _stock = _scene()
    root = ships["m2"].GetAI()
    rejoin_branch = _branches(root)[9]
    ai_driver.tick_ai(root, 1.0)
    assert rejoin_branch._status == AIC.US_DORMANT
    roster.member("m2").conditions["rejoin"].SetStatus(1)
    ai_driver.tick_ai(root, 2.0)
    assert rejoin_branch._status == AIC.US_ACTIVE
    assert _rejoin_ai(root).GetScriptInstance().pcFollowObjectName == "m1"


def test_wrapped_tree_phase_b_order():
    _wing, ships, stock = _scene()
    root = ships["m2"].GetAI()
    member = roster.member("m2")
    b = _branches(root)
    import AI.Preprocessors
    for prio, kind in ((3, "withdraw"), (4, "hold"), (5, "guard"),
                       (6, "fallback"), (7, "reserve")):
        cond_ai = b[prio]
        assert isinstance(cond_ai, aimod.ConditionalAI)
        (cond,) = cond_ai.GetConditions()
        assert cond.GetModuleName() == "Conditions.ConditionWing"
        assert cond.GetArguments() == ("m2", kind)
        assert member.conditions[kind] is cond
        assert cond.GetStatus() == 0
        assert ai_driver._memoisable_evalfunc(cond_ai.GetEvaluationFunction())
        avoid = cond_ai.GetContainedAI()
        assert isinstance(avoid, aimod.PreprocessingAI)
        assert avoid.GetName() == "AvoidObstacles"
        assert isinstance(avoid.GetPreprocessingInstance(),
                          AI.Preprocessors.AvoidObstacles)
        move = avoid.GetContainedAI()
        assert isinstance(move, aimod.PlainAI)
        assert move.GetScriptModule() == "WingMoveTo"
        for node in (cond_ai, avoid, move):
            assert node.IsInterruptable() == 1
    assert b[10] is stock["m2"]


@pytest.mark.parametrize("kind,prio", [("withdraw", 3), ("hold", 4),
                                       ("guard", 5), ("fallback", 6),
                                       ("reserve", 7)])
def test_new_kinds_activate_branch(kind, prio):
    _wing, ships, _stock = _scene()
    root = ships["m2"].GetAI()
    branch = _branches(root)[prio]
    ai_driver.tick_ai(root, 1.0)
    assert branch._status == AIC.US_DORMANT
    roster.member("m2").conditions[kind].SetStatus(1)
    ai_driver.tick_ai(root, 2.0)
    assert branch._status == AIC.US_ACTIVE


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


def test_rejoin_warps_to_a_far_commander():
    """A member beyond leash + slack of its commander in-system warps back
    (BC's own InSystemWarp, as Intercept uses), stopping regroup_gather_gu
    off the commander's surface. FollowObject alone flies at impulse and
    never catches a commander as fast as it (Mark's ruling 2026-11-10).
    An earlier warp's latch does not block it."""
    _wing, ships, _stock = _scene()
    m3 = ships["m3"]
    m3.SetTranslateXYZ(0.0, -600.0, 0.0)      # nose (+Y) on m1 at origin
    ships["m1"].SetTranslateXYZ(0.0, 0.0, 0.0)
    m3._warp_consumed = True
    script = _rejoin_ai(m3.GetAI()).GetScriptInstance()
    assert script.Update() == AIC.US_ACTIVE
    assert m3.IsDoingInSystemWarp()
    flight = m3._insystem_warp_transit
    assert flight.drop_distance == pytest.approx(
        dials.get("regroup_gather_gu") + ships["m1"].GetRadius())


def test_rejoin_does_not_warp_inside_the_leash():
    _wing, ships, _stock = _scene()
    m3 = ships["m3"]
    m3.SetTranslateXYZ(0.0, -250.0, 0.0)
    ships["m1"].SetTranslateXYZ(0.0, 0.0, 0.0)
    script = _rejoin_ai(m3.GetAI()).GetScriptInstance()
    assert script.Update() == AIC.US_ACTIVE
    assert not m3.IsDoingInSystemWarp()


def test_rejoin_turns_before_it_warps():
    _wing, ships, _stock = _scene()
    m3 = ships["m3"]
    m3.SetTranslateXYZ(0.0, 600.0, 0.0)       # nose (+Y) away from m1
    ships["m1"].SetTranslateXYZ(0.0, 0.0, 0.0)
    script = _rejoin_ai(m3.GetAI()).GetScriptInstance()
    assert script.Update() == AIC.US_ACTIVE
    assert not m3.IsDoingInSystemWarp()


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
def test_mod_select_target_subclass_is_not_stock(cls_name, monkeypatch):
    import AI.Preprocessors
    from engine.appc import ai_optimized
    # A class NAMED "SelectTarget" is wrapped by the engine optimizer
    # (OPTIMIZED_PREPROCESSORS dispatches by name), which caches a
    # "SelectTarget_Native" subclass of THIS test's class and publishes it as
    # ai_optimized.SelectTarget_Native -- over the stock class's alias. Restore
    # both so a later test's cached stock alias is still the published one.
    monkeypatch.setattr(ai_optimized, "_NATIVE_SELECT_CLASSES",
                        dict(ai_optimized._NATIVE_SELECT_CLASSES))
    monkeypatch.setattr(ai_optimized, "SelectTarget_Native",
                        getattr(ai_optimized, "SelectTarget_Native", None),
                        raising=False)
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


def test_wrap_tree_caches_the_beam_range():
    """Ruling 2026-11-09: the smallest GetMaxDamageDistance over the
    phaser and pulse banks, cached on the member at wrap (Akira phasers
    60 GU); a ship with neither (no member record here) is skipped."""
    wing, ships, _stock = _scene(2)
    assert roster.member("m1").beam_range_gu == pytest.approx(60.0)


@pytest.mark.parametrize("kind,want", [("Galor", 30.0), ("BirdOfPrey", 100.0),
                                       ("Warbird", 40.0)])
def test_beam_range_of_stock_ships(kind, want):
    pSet = SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "WingTest")
    assert tree.beam_range(_ship(pSet, kind, "x", (0.0, 0.0, 0.0))) == (
        pytest.approx(want))


def test_beam_range_skips_tractors():
    pSet = SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "WingTest")
    ship = _ship(pSet, "Akira", "x", (0.0, 0.0, 0.0))
    assert ship.GetTractorBeamSystem() is not None   # 100 GU tractors
    assert tree.beam_range(ship) == pytest.approx(60.0)


def test_rewrap_recomputes_the_beam_range():
    import AI.Compound.BasicAttack
    wing, ships, _stock = _scene(2)
    m = roster.member("m2")
    m.beam_range_gu = 1.0
    s = ships["m2"]
    s.SetAI(tree.wrap_tree(s, AI.Compound.BasicAttack.CreateAI(
        s, wing.target_group, Difficulty=0.5), wing))
    assert m.beam_range_gu == pytest.approx(60.0)
