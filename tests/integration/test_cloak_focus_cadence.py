"""End-to-end: the SDK CloakShip preprocessor cloaks on GotFocus and decloaks
on LostFocus, driven by Task 1's focus-loss lifecycle when the AI tree switches
the active branch. This is the cloak decloak-to-attack cadence."""
from AI.Preprocessors import CloakShip
from engine.appc.ai import (
    PreprocessingAI, PriorityListAI_Create, ArtificialIntelligence,
)
from engine.appc.ai_driver import tick_ai
from engine.appc.ships import ShipClass
from engine.appc.subsystems import CloakingSubsystem

US_ACTIVE = ArtificialIntelligence.US_ACTIVE
US_DORMANT = ArtificialIntelligence.US_DORMANT


class _Plain:
    def Update(self, dEndTime):
        return PreprocessingAI.PS_NORMAL


def _ship_with_cloak():
    ship = ShipClass()
    ship.SetName("Warbird 1")
    ship.SetCloakingSubsystem(CloakingSubsystem("Cloaking Device"))
    return ship


def test_cloakship_cadence_via_focus_loss():
    ship = _ship_with_cloak()
    cloak_inst = CloakShip(1)                      # bCloakOn = 1
    cloak_pp = PreprocessingAI(ship, "Cloak")
    cloak_pp.SetPreprocessingMethod(cloak_inst, "Update")   # sets cloak_inst.pCodeAI = cloak_pp
    other_pp = PreprocessingAI(ship, "Fire")
    other_pp.SetPreprocessingMethod(_Plain(), "Update")

    pl = PriorityListAI_Create(None, "PL")
    pl.AddAI(cloak_pp, 0)                           # cloak higher priority
    pl.AddAI(other_pp, 1)

    # Cloak node focused -> GotFocus -> CheckCloak -> StartCloaking.
    tick_ai(pl, 0.0)
    assert ship.GetCloakingSubsystem().IsTryingToCloak() == 1

    # Tree switches to the fire branch: cloak node drops off the active path ->
    # LostFocus -> StopCloaking.
    cloak_pp._status = US_DORMANT
    tick_ai(pl, 1.0)
    assert ship.GetCloakingSubsystem().IsTryingToCloak() == 0

    # Tree returns to the cloak branch -> GotFocus re-fires -> re-cloak.
    cloak_pp._status = US_ACTIVE
    tick_ai(pl, 2.0)
    assert ship.GetCloakingSubsystem().IsTryingToCloak() == 1
