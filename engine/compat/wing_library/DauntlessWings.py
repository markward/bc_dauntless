"""DauntlessWings -- the SDK-facing surface of Dauntless wings.

Served by the claimed-namespace rule (engine/compat/claimed.py); mission and
mod scripts use `import DauntlessWings`. A wing is a group of ships that fight
together under a commander chosen by rated power; Quick Battle groups are
wings. All names are ship NAMES (strings).

    CreateWing(sWingID, pEnemyGroup)  Make a wing against an enemy ObjectGroup.
    AddMember(sWingID, sShip, bPlayer=0, bChainEligible=1)
                                      Add a ship; the player may be a member;
                                      bChainEligible=0 keeps it out of command.
    ArmWing(sWingID)                  Build the chain; start the 1 Hz brain.
    WrapTree(pShip, pTree)            The wing AI tree around pTree, or pTree
                                      itself when wings are off / not a member.
    GetWing(sShip)                    The ship's wing id, or None.
    GetCommander(sShip)               Name of the wing's commander, or None.
    IsCommander(sShip)                1 if the ship commands its wing.
    IsLeaderless(sShip)               1 once the wing has lost its chain.
    GetWingTargets(sShip)             Tuple of the wing's target names with
                                      Priority > 0, highest first.
    RegisterDecision(pDecision)       Add a decision (score/choose, see
                                      engine.wings.decisions) to the brain.
    IsEnabled()                       1 unless DAUNTLESS_WINGS=0.

While wings are disabled (IsEnabled() is 0) CreateWing, AddMember and ArmWing
do nothing and return None, so no wing exists and the Get*/Is* calls answer
as for a ship in no wing.
"""
from engine.wings import decisions, roster, service, tree


def IsEnabled():
    return 1 if service.enabled() else 0


def CreateWing(sWingID, pEnemyGroup):
    if not service.enabled():
        return None
    roster.create_wing(sWingID, pEnemyGroup)
    return None


def AddMember(sWingID, sShip, bPlayer=0, bChainEligible=1):
    if not service.enabled():
        return None
    wing = roster._wings.get(sWingID)
    if wing is None:
        return
    roster.add_member(wing, sShip, is_player=bool(bPlayer),
                      chain_eligible=bool(bChainEligible))


def ArmWing(sWingID):
    if not service.enabled():
        return None
    wing = roster._wings.get(sWingID)
    if wing is not None:
        service.arm(wing)


def WrapTree(pShip, pTree):
    if not service.enabled():
        return pTree
    name = pShip.GetName()
    if roster.member(name) is None:
        return pTree
    return tree.wrap_tree(pShip, pTree, roster.wing_of(name))


def GetWing(sShip):
    wing = roster.wing_of(sShip)
    return wing.wing_id if wing is not None else None


def GetCommander(sShip):
    wing = roster.wing_of(sShip)
    return wing.commander if wing is not None else None


def IsCommander(sShip):
    wing = roster.wing_of(sShip)
    return 1 if wing is not None and wing.commander == sShip else 0


def IsLeaderless(sShip):
    wing = roster.wing_of(sShip)
    return 1 if wing is not None and wing.leaderless else 0


def GetWingTargets(sShip):
    wing = roster.wing_of(sShip)
    if wing is None:
        return ()
    group = wing.target_group
    scored = [(group[n].get("Priority", 0.0), n)
              for n in group.GetNameTuple()]
    scored = [s for s in scored if s[0] > 0]
    scored.sort(key=lambda s: -s[0])
    return tuple(n for _, n in scored)


def RegisterDecision(pDecision):
    decisions.register(pDecision)
