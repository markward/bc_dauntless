"""The wrapped wing tree (spec 2026-11-09-wing-leaders-phase-a-design.md
§10, §11).

    PriorityList
      1  Conditional[ConditionWing(ship, "ram")]     -> Ram (current target)
      2  Conditional[ConditionWing(ship, "flee")]    -> Flee (enemy group)
      3  Conditional[ConditionWing(ship, "rejoin")]  -> AvoidObstacles(WingRejoin)
      4  <stock tree, unchanged>

Every condition is pushed by the brain (status 0/1); nothing here polls.
The stock tree keeps its own preprocessors; its SelectTarget nodes are found
once its builders have run (discover_select_nodes) and weighted for the
wing. Only weights are set on them, so they stay on the native rating path.
"""
import App

from engine.wings import dials, roster

_CONDITION_MODULE = "Conditions.ConditionWing"


def EvalFunc(bOn):
    """Pure (App only), so the native walker memoises it
    (ai_driver._memoisable_evalfunc)."""
    if bOn:
        return App.ArtificialIntelligence.US_ACTIVE
    return App.ArtificialIntelligence.US_DORMANT


def _conditional(pShip, sName, sKind, pContained):
    pCondition = App.ConditionScript_Create(
        _CONDITION_MODULE, "ConditionWing", pShip.GetName(), sKind)
    pConditional = App.ConditionalAI_Create(pShip, sName)
    pConditional.SetInterruptable(1)
    pConditional.SetContainedAI(pContained)
    pConditional.AddCondition(pCondition)
    pConditional.SetEvaluationFunction(EvalFunc)
    return pConditional


def _plain(pShip, sName, sModule):
    pPlain = App.PlainAI_Create(pShip, sName)
    pPlain.SetScriptModule(sModule)
    pPlain.SetInterruptable(1)
    return pPlain


def wrap_tree(pShip, pStockTree, wing):
    """The wing tree for `pShip` with `pStockTree` as its last branch. The
    ship must already be a member of `wing` for its conditions to register."""
    import AI.Preprocessors
    member = wing.members.get(pShip.GetName())

    pRam = _plain(pShip, "Ram", "Ram")
    pRamScript = pRam.GetScriptInstance()
    pRamScript.SetMaximumSpeed()
    if member is not None:
        member.ram_script = pRamScript

    pFlee = _plain(pShip, "Flee", "Flee")
    pFlee.GetScriptInstance().SetFleeFromGroup(wing.enemy_group)

    pRejoin = _plain(pShip, "Rejoin", "WingRejoin")
    pAvoidObstacles = App.PreprocessingAI_Create(pShip, "AvoidObstacles")
    pAvoidObstacles.SetInterruptable(1)
    pAvoidObstacles.SetPreprocessingMethod(AI.Preprocessors.AvoidObstacles(),
                                           "Update")
    pAvoidObstacles.SetContainedAI(pRejoin)

    pRoot = App.PriorityListAI_Create(pShip, "WingPriorityList")
    pRoot.SetInterruptable(1)
    pRoot.AddAI(_conditional(pShip, "WingRam", "ram", pRam), 1)
    pRoot.AddAI(_conditional(pShip, "WingFlee", "flee", pFlee), 2)
    pRoot.AddAI(_conditional(pShip, "WingRejoin", "rejoin", pAvoidObstacles), 3)
    pRoot.AddAI(pStockTree, 4)
    return pRoot


def _is_stock_select_target(inst) -> bool:
    """The SDK's own SelectTarget class -- or the engine's native-rating
    alias of it (ai_optimized._native_select_class), whose only method is
    marked _dauntless_native_entry. A mod subclass is not stock."""
    cls = type(inst)
    entry = cls.__dict__.get("GetTargetRating")
    if getattr(entry, "_dauntless_native_entry", False):
        cls = cls.__mro__[1]
    return cls.__name__ == "SelectTarget"


def discover_select_nodes(pShip, member) -> bool:
    """Record the stock SelectTarget nodes in `pShip`'s built AI tree on
    `member`, weighting each new one for the wing (popularity), unless the
    wing is leaderless (stock weights then). True if a new node was found.
    Before the attack builders have run there is nothing to find."""
    pAI = pShip.GetAI()
    if pAI is None:
        return False
    wing = roster.wing_of(member.name)
    weight = wing is not None and not wing.leaderless
    found = False
    for node in pAI.GetAllAIsInTree():
        pNode = App.PreprocessingAI_Cast(node)
        if pNode is None or pNode.GetName() != "SelectTarget":
            continue
        if any(n is pNode for n in member.select_nodes):
            continue
        inst = pNode.GetPreprocessingInstance()
        if not _is_stock_select_target(inst):
            continue
        member.select_nodes.append(pNode)
        if weight:
            inst.SetRelativeImportance(fPopularity=dials.get("wing_popularity"))
        found = True
    return found
