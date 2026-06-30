"""Phase D — AI cloak doctrine (CloakShip preprocessor) end-to-end.

BC's AI cloaks a ship via the SDK CloakShip preprocessor
(sdk/.../AI/Preprocessors.py:2068).  CloakShip puts its work in GotFocus +
Update (both call CheckCloak), and LostFocus force-decloaks.  Our ai_driver
dispatches GotFocus on a PreprocessingAI's first tick and the configured method
each tick (_tick_preprocessing), so a CloakShip wired as the preprocessing
method should engage / hold / drop the cloak with no driver changes — this pins
that path.

Full CloakAttackWrapper combat tactics ride on the not-yet-dispatched
BasicAttack compound (ai_driver.py:153) and remain follow-on; this covers the
preprocessor itself, which is what BasicAttack/CloakAttack ultimately drive.
"""
from AI.Preprocessors import CloakShip

from engine.appc.ai import PreprocessingAI_Create
from engine.appc.ai_driver import tick_ai
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import CloakingSubsystem


def _wire_cloakship(bCloakOn):
    """A warbird with a cloak, driven by a CloakShip preprocessor bound as the
    PreprocessingAI's Update method (mirrors the SDK CodeAISet wiring)."""
    ship = ShipClass_Create("Warbird")
    ship.SetCloakingSubsystem(CloakingSubsystem("Cloaking Device"))
    inst = CloakShip(bCloakOn)
    pp = PreprocessingAI_Create(ship, "CloakPP")
    inst.pCodeAI = pp
    pp.SetPreprocessingMethod(inst, "Update")
    return inst, pp, ship


def test_driver_first_tick_engages_cloak():
    """GotFocus dispatch on the first driver tick → CheckCloak → StartCloaking."""
    inst, pp, ship = _wire_cloakship(bCloakOn=1)
    cloak = ship.GetCloakingSubsystem()
    assert cloak.IsCloaking() == 0
    tick_ai(pp, game_time=0.0)
    assert cloak.IsCloaking() == 1


def test_cloak_completes_and_holds_under_driver():
    """The transition finishes (Phase-A timer) and subsequent driver ticks keep
    the ship cloaked — CheckCloak no-ops once IsCloaked."""
    inst, pp, ship = _wire_cloakship(bCloakOn=1)
    cloak = ship.GetCloakingSubsystem()
    tick_ai(pp, game_time=0.0)
    cloak.Update(cloak._transition_duration + 0.01)
    assert cloak.IsCloaked() == 1
    tick_ai(pp, game_time=1.0)
    assert cloak.IsCloaked() == 1


def test_lost_focus_force_decloaks():
    """CloakShip.LostFocus must drop the cloak (BC: a ship that loses AI focus
    must not stay hidden)."""
    inst, pp, ship = _wire_cloakship(bCloakOn=1)
    cloak = ship.GetCloakingSubsystem()
    tick_ai(pp, game_time=0.0)
    cloak.Update(cloak._transition_duration + 0.01)
    assert cloak.IsCloaked() == 1
    inst.LostFocus()
    assert cloak.IsDecloaking() == 1


def test_cloakship_off_decloaks_a_cloaked_ship():
    """CloakShip(0) keeps the ship visible: a cloaked ship is told to decloak."""
    inst, pp, ship = _wire_cloakship(bCloakOn=0)
    cloak = ship.GetCloakingSubsystem()
    cloak.InstantCloak()
    tick_ai(pp, game_time=0.0)        # GotFocus → CheckCloak → StopCloaking
    assert cloak.IsDecloaking() == 1
