"""WarpEngineSubsystem.SetWarpSequence had NO production caller (spec #8):
WarpSequence_Create(...).Play() never attached itself, so GetWarpSequence()
was None for every ship and ConditionWarpingToSet read FALSE forever. The
ET_SET_WARP_SEQUENCE emitter closed 2026-09-02 was real but unreachable."""
import pytest

import App
from engine.appc.actions import TGAction
from engine.appc.ai import ConditionScript_Create
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem, WarpEngineSubsystem


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


class _StallAction(TGAction):
    """A root step that plays but never self-completes.

    Verified fixture correction (beyond the brief's ship-attach note): every
    action WarpSequence_Create builds (ClearTargets, ChangeRenderedSet,
    PlacePlayer, ArriveFinalize, ArrivalClearTargets, EnableHelmMenu) is a
    plain TGAction whose Play() is `_do_play(); self.Completed()` inline
    (actions.py:107-110) -- there is no VFX flythrough in a headless test
    (`_vfx_enabled` is None), so NONE of them defer. With warp_time=0.0 and a
    destination set that's already registered, the whole 6-action chain
    completes SYNCHRONOUSLY inside seq.Play(): SetWarpSequence(seq) and the
    matching SetWarpSequence(None) both fire, and both ET_SET_WARP_SEQUENCE
    events dispatch, before seq.Play() ever returns to the caller (confirmed
    by tracing ConditionWarpingToSet.SetStateFromSequence: it is called
    twice per Play(), status 1 then 0, back-to-back). A real warp is held
    open for real time by the flythrough VFX timers or by physical transit;
    this stall action reproduces that hold in a headless unit test so the
    attached-while-playing state in the Interfaces contract is actually
    observable, and Completed()/Abort() can be invoked as the deliberate,
    separate "arrival" step the brief's tests exercise."""
    def Play(self) -> None:
        self._playing = True


def _ship_in_set():
    pSet = App.SetClass_Create(); pSet.SetName("S"); App.g_kSetManager._sets["S"] = pSet
    ship = ShipClass()
    ship._hull = HullSubsystem("H"); ship._hull.SetMaxCondition(1000.0)
    # Real setter (not the dead-attribute `ship._warp_engine_subsystem = ...`
    # poke): SetWarpEngineSubsystem wires _parent_ship via _attach_subsystem,
    # and SequenceSet's SetStateFromSequence path requires
    # pWarpSystem.GetParentShip() to resolve the warping ship.
    ship.SetWarpEngineSubsystem(WarpEngineSubsystem("WES"))
    pSet.AddObjectToSet(ship, "Ours")
    return ship


def _held_open(seq):
    """Add a stalling root action so `seq` stays PLAYING after Play() --
    see _StallAction's docstring for why that's required here."""
    seq.AddAction(_StallAction())
    return seq


def test_play_attaches_and_completed_detaches():
    ship = _ship_in_set()
    seq = _held_open(App.WarpSequence_Create(ship, "S", 0.0, "Player Start"))
    assert ship.GetWarpEngineSubsystem().GetWarpSequence() is None
    seq.Play()
    assert ship.GetWarpEngineSubsystem().GetWarpSequence() is seq
    seq.Completed()
    assert ship.GetWarpEngineSubsystem().GetWarpSequence() is None


def test_condition_warping_to_set_follows_the_real_warp_lifecycle():
    ship = _ship_in_set()
    cond = ConditionScript_Create("Conditions.ConditionWarpingToSet",
                                  "ConditionWarpingToSet", "Ours", "S")
    cond.SetActive()
    assert cond._instance is not None, cond._init_error
    assert cond.GetStatus() == 0
    seq = _held_open(App.WarpSequence_Create(ship, "S", 0.0, "Player Start"))
    seq.Play()
    assert cond.GetStatus() == 1, "warp started but the condition never heard ET_SET_WARP_SEQUENCE"
    seq.Completed()
    assert cond.GetStatus() == 0, "warp finished but the condition still reads warping"


def test_a_ship_with_no_warp_engine_still_warps():
    pSet = App.SetClass_Create(); pSet.SetName("S"); App.g_kSetManager._sets["S"] = pSet
    ship = ShipClass(); ship._hull = HullSubsystem("H"); ship._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(ship, "Ours")
    seq = App.WarpSequence_Create(ship, "S", 0.0, "Player Start")
    seq.Play()          # must not raise
    seq.Completed()


def test_abort_also_detaches():
    """An aborted warp must not leave the condition reading "warping" forever.

    Mirrors Completed(): Abort() must clear GetWarpSequence() back to None
    (only if we are still the attached sequence) so
    ConditionWarpingToSet.SequenceSet re-reads False."""
    ship = _ship_in_set()
    seq = _held_open(App.WarpSequence_Create(ship, "S", 0.0, "Player Start"))
    seq.Play()
    assert ship.GetWarpEngineSubsystem().GetWarpSequence() is seq
    seq.Abort()
    assert ship.GetWarpEngineSubsystem().GetWarpSequence() is None
