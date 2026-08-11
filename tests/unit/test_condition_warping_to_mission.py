"""ConditionWarpingToMission must not fire for an ordinary in-set warp.

Gap C2 (docs/engine/aieditor-ai-surface-and-gaps.md §4). The condition reads::

    if pWarpSequence and (pWarpSequence.GetDestinationMission()
                          or pWarpSequence.GetDestinationEpisode()):
        self.pCodeCondition.SetStatus(1)

-- Conditions/ConditionWarpingToMission.py:23.

Our ``WarpSequence`` (engine/appc/warp.py:530) defined neither accessor, and a
missing attribute resolves to a **truthy** ``_Stub``. So the condition reported
"warping to a new mission" for *every* warp sequence that existed -- an inverted
failure, not a silent-off one. Live-confirmed at ``docs/stub_heatmap.md`` rank
95 (136 hits, 58/233 runs). Consumer: ``AI/Compound/FollowThroughWarp.py``,
registered by ``AI/Setup.py:135``.

Dauntless never constructs a cross-mission warp sequence today -- every
``WarpSequence_Create`` carries a *set* destination -- so the correct answer for
all of them is false.
"""
import pytest

import App
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


def _ship_warping_within_a_set():
    """A ship mid-warp to another SET (not another mission or episode)."""
    pSet = App.SetClass_Create()
    pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet

    ship = ShipClass()
    ship._hull = HullSubsystem("H")
    ship._hull.SetMaxCondition(1000.0)
    warp = WarpEngineSubsystem("WES")
    ship._warp_engine_subsystem = warp
    pSet.AddObjectToSet(ship, "Ours")

    seq = App.WarpSequence_Create(ship, "S", 0.0, "Player Start")
    warp.SetWarpSequence(seq)
    return ship, seq


def test_in_set_warp_is_not_a_mission_warp():
    """The bug: this reported True for every warp sequence in existence."""
    _ship_warping_within_a_set()

    cond = ConditionScript_Create(
        "Conditions.ConditionWarpingToMission", "ConditionWarpingToMission",
        "Ours")

    assert cond.GetStatus() == 0, (
        "ConditionWarpingToMission fired for an ordinary in-set warp -- "
        "GetDestinationMission()/GetDestinationEpisode() are returning a "
        "truthy stub instead of a real falsy value")


def test_warp_sequence_reports_no_mission_or_episode_destination():
    """The accessors must return real falsy values, not truthy stubs.

    Asserted directly as well as through the condition, because a stub is
    truthy AND passes ``is not None`` -- so only an explicit falsiness check
    catches it.
    """
    _ship, seq = _ship_warping_within_a_set()

    assert not seq.GetDestinationMission()
    assert not seq.GetDestinationEpisode()


def test_condition_is_false_when_the_ship_is_not_warping_at_all():
    """Baseline: no warp sequence means no mission warp.

    Distinguishes "we fixed the accessors" from "the condition is now hard-wired
    to zero" -- this case was already correct before the fix and must stay so.
    """
    pSet = App.SetClass_Create()
    pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ship = ShipClass()
    ship._hull = HullSubsystem("H")
    ship._hull.SetMaxCondition(1000.0)
    ship._warp_engine_subsystem = WarpEngineSubsystem("WES")
    pSet.AddObjectToSet(ship, "Ours")

    cond = ConditionScript_Create(
        "Conditions.ConditionWarpingToMission", "ConditionWarpingToMission",
        "Ours")

    assert cond.GetStatus() == 0
