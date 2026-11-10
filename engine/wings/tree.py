"""The wrapped wing tree (spec 2026-11-09-wing-leaders-phase-a-design.md
§10, §11).

    PriorityList
      1  Conditional[ConditionWing(ship, "ram")]     -> Ram (current target)
      2  Conditional[ConditionWing(ship, "flee")]    -> Flee (enemy group)
      3  Conditional[ConditionWing(ship, "withdraw")] -> AvoidObstacles(WingMoveTo)
      4  Conditional[ConditionWing(ship, "guard")]    -> AvoidObstacles(WingMoveTo)
      5  Conditional[ConditionWing(ship, "fallback")] -> AvoidObstacles(WingMoveTo)
      6  Conditional[ConditionWing(ship, "reserve")] -> AvoidObstacles(WingMoveTo)
      7  Conditional[ConditionWing(ship, "attack")]  -> WingFire (the wing's own
                                   stock FireScript) -> AvoidObstacles(WingMoveTo)
      8  Conditional[ConditionWing(ship, "rejoin")]  -> AvoidObstacles(WingRejoin)
      9  <stock tree, unchanged>

Every condition is pushed by the brain (status 0/1); nothing here polls.
The stock tree keeps its own preprocessors; its SelectTarget nodes are found
once its builders have run (discover_select_nodes) and weighted for the
wing: popularity only, saved as found and restored when the wing goes
leaderless. Only a weight is set on them, so they stay on the native rating
path.
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


def fire_keywords(difficulty):
    """FireScript keywords for an AI difficulty (None = 0.5), set exactly as
    AI.Compound.BasicAttack.CreateAI sets them."""
    import AI.Compound.BasicAttack
    kw = {"Difficulty": difficulty if difficulty is not None else 0.5}
    prefix = ("Easy_", "", "Hard_")[App.Game_GetDifficulty()]
    AI.Compound.BasicAttack.SetFlagsFromDifficulty(prefix, kw)
    return kw


def _build_fire_script(pShip, kw):
    """The stock FireScript, built as FedAttack builds FireAll. Its initial
    target is the ship itself: a placeholder the brain replaces before the
    attack branch is ever switched on.

    It keeps the stock attack flags (attack disabled subsystems, fire with
    no valid subsystem) in both modes; only the subsystem list is switched
    (IgnoreSubsystemTargets / RestoreSubsystemTargets). Weapons-first still
    prefers a live weapon: ChooseTargetSubsystem picks among the
    non-disabled ones while any is left. SetAttackDisabled(0) is never
    set: the SDK's WeaponTooDangerous then reads pSubsystem.GetCondition()
    with no subsystem chosen (hull aim, a fresh target), so a torpedo frame
    raised and left the weapon cycle stuck; and its DisableOnly partner,
    SetAttackWithoutValidSubsystems(0), returns from a fire frame before
    the cycle advances, so a fresh target never reaches its choose frame."""
    import AI.Preprocessors
    keywords = dict(kw)
    keywords["TargetSubsystems"] = [(App.CT_WEAPON_SYSTEM, 1)]
    pFire = AI.Preprocessors.FireScript(pShip.GetName(), **keywords)
    for pSystem in (pShip.GetTorpedoSystem(), pShip.GetPhaserSystem(),
                    pShip.GetPulseWeaponSystem()):
        if not App.IsNull(pSystem):
            pFire.AddWeaponSystem(pSystem)
    pFire.IgnoreSubsystemTargets()
    return pFire


def beam_range(pShip):
    """The smallest GetMaxDamageDistance (GU) over the ship's phaser and
    pulse banks -- the children of GetPhaserSystem() /
    GetPulseWeaponSystem(), read from each bank's property -- or None.
    Tractors and torpedoes are not beams that set a standoff."""
    from engine.wings import attack
    out = []
    for pSystem in (pShip.GetPhaserSystem(), pShip.GetPulseWeaponSystem()):
        if App.IsNull(pSystem):
            continue
        for i in range(pSystem.GetNumChildSubsystems()):
            pProp = pSystem.GetChildSubsystem(i).GetProperty()
            if pProp is not None:
                out.append(pProp.GetMaxDamageDistance())
    return attack.beam_range(out)


def wrap_tree(pShip, pStockTree, wing, fire_keywords=None):
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

    def avoiding(sName, pContained):
        pAvoid = App.PreprocessingAI_Create(pShip, sName)
        pAvoid.SetInterruptable(1)
        pAvoid.SetPreprocessingMethod(AI.Preprocessors.AvoidObstacles(),
                                      "Update")
        pAvoid.SetContainedAI(pContained)
        return pAvoid

    kw = fire_keywords or globals()["fire_keywords"](None)
    pFire = _build_fire_script(pShip, kw)
    if member is not None:
        member.fire_script = pFire
        member.beam_range_gu = beam_range(pShip)
        # A fresh script (own-name target, hull mode): the brain's
        # change-only writes must see it as untargeted, or a re-wrapped
        # slot-holder keeps a script aimed at its own ship.
        member.attack_target = None
        member.weapons_first = False

    pAvoidObstacles = avoiding("AvoidObstacles",
                               _plain(pShip, "Rejoin", "WingRejoin"))

    pRoot = App.PriorityListAI_Create(pShip, "WingPriorityList")
    pRoot.SetInterruptable(1)
    pRoot.AddAI(_conditional(pShip, "WingRam", "ram", pRam), 1)
    pRoot.AddAI(_conditional(pShip, "WingFlee", "flee", pFlee), 2)
    for sKind, iPriority in (("withdraw", 3), ("guard", 4), ("fallback", 5)):
        pMove = avoiding("AvoidObstacles",
                         _plain(pShip, "Move" + sKind, "WingMoveTo"))
        pRoot.AddAI(_conditional(pShip, "Wing" + sKind.capitalize(), sKind,
                                 pMove), iPriority)
    pReserve = avoiding("AvoidObstacles",
                        _plain(pShip, "Movereserve", "WingMoveTo"))
    pRoot.AddAI(_conditional(pShip, "WingReserve", "reserve", pReserve), 6)
    pWingFire = App.PreprocessingAI_Create(pShip, "WingFire")
    pWingFire.SetInterruptable(1)
    pWingFire.SetPreprocessingMethod(pFire, "Update")
    pWingFire.SetContainedAI(avoiding("AvoidObstacles",
                                      _plain(pShip, "Moveattack",
                                             "WingMoveTo")))
    pRoot.AddAI(_conditional(pShip, "WingAttack", "attack", pWingFire), 7)
    pRoot.AddAI(_conditional(pShip, "WingRejoin", "rejoin", pAvoidObstacles), 8)
    pRoot.AddAI(pStockTree, 9)
    return pRoot


def _is_stock_select_target(inst) -> bool:
    """Exactly the SDK's AI.Preprocessors.SelectTarget class -- or the
    engine's native-rating alias of it (ai_optimized._native_select_class,
    whose only method is marked _dauntless_native_entry). A mod subclass is
    not stock, whatever it is named."""
    import AI.Preprocessors
    cls = type(inst)
    entry = cls.__dict__.get("GetTargetRating")
    if getattr(entry, "_dauntless_native_entry", False):
        cls = cls.__mro__[1]
    return cls is AI.Preprocessors.SelectTarget


def apply_popularity(member) -> None:
    """Set every recorded node's popularity to the wing dial (read at use).
    Popularity is the only weight a wing touches."""
    fPopularity = dials.get("wing_popularity")
    for node in member.select_nodes:
        inst = node.GetPreprocessingInstance()
        if inst.fPopularityFactor != fPopularity:
            inst.fPopularityFactor = fPopularity


def restore_popularity(member) -> None:
    """Put back each node's popularity as it was found (leaderless)."""
    for node in member.select_nodes:
        saved = member.select_saved.get(id(node))
        if saved is not None:
            node.GetPreprocessingInstance().fPopularityFactor = saved


def discover_select_nodes(pShip, member) -> bool:
    """Record the stock SelectTarget nodes in `pShip`'s built AI tree on
    `member` (and the tree's root as member.ai_root), saving each new node's
    popularity and setting it to the wing dial -- unless the wing is
    leaderless (left as found). True if a new node was found. Before the
    attack builders have run there is nothing to find. A player member is
    never touched: its AI is not the wing's to weight."""
    if member.is_player:
        return False
    pAI = pShip.GetAI()
    member.ai_root = pAI
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
        member.select_saved[id(pNode)] = inst.fPopularityFactor
        found = True
    if found and weight:
        apply_popularity(member)
    return found
