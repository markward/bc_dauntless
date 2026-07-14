"""PS_DONE means "this node is finished" -> US_DONE, which tears the AI down.

Established 2026-07-14 from the binary: PreprocessingAI::Update (switch at
0x48eab1) maps PS_NORMAL -> run the child, PS_SKIP_ACTIVE -> US_ACTIVE,
PS_SKIP_DORMANT -> US_DORMANT, and default (PS_DONE=3, PS_INVALID=4) -> US_DONE.
US_DONE (not US_DORMANT) is what unlinks and deletes an AI node.

We previously treated PS_DONE as "stop calling the preprocessor, keep running the
child". That was the wrong lesson drawn from AI/Preprocessors.py:ManagePower,
whose `# Unused. return PS_DONE` body NEVER RUNS in the shipped game: the engine
swaps the Python ManagePower node for a native C++ one at bind time via the
GetOptimizedVersion hook (vtable +0x34).

So both halves are tested here: the mapping is now faithful, AND the ManagePower
swap keeps the shipped Compound doctrines alive.
"""
import App
from engine.appc.ai import (
    ArtificialIntelligence, PlainAI_Create, PreprocessingAI_Create,
)
from engine.appc.ai_driver import tick_ai
from engine.appc import ai_optimized


class _Child:
    def __init__(self):
        self.updates = 0

    def GetNextUpdateTime(self):
        return 0.0

    def Update(self):
        self.updates += 1
        return ArtificialIntelligence.US_ACTIVE


class _DonePreproc:
    """A preprocessor that reports PS_DONE, like a naive port of ManagePower."""

    def Update(self, dEndTime):
        return App.PreprocessingAI.PS_DONE


class _InvalidPreproc:
    def Update(self, dEndTime):
        return App.PreprocessingAI.PS_INVALID


class _NormalPreproc:
    def Update(self, dEndTime):
        return App.PreprocessingAI.PS_NORMAL


class _SkipDormantPreproc:
    def GetNextUpdateTime(self):
        return 5.0

    def Update(self, dEndTime):
        return App.PreprocessingAI.PS_SKIP_DORMANT


class _SlowDonePreproc:
    """PS_DONE on a 5 s cadence — pins the cadence-SKIPPED arm of the mapping."""

    def GetNextUpdateTime(self):
        return 5.0

    def Update(self, dEndTime):
        return App.PreprocessingAI.PS_DONE


def _wrap(inst):
    node = PreprocessingAI_Create(None, "wrap")
    child_ai = PlainAI_Create(None, "child")
    child = _Child()
    child_ai._script_instance = child
    node.SetContainedAI(child_ai)
    node.SetPreprocessingMethod(inst, "Update")
    return node, child


def test_ps_done_reports_us_done_and_stops_the_child():
    node, child = _wrap(_DonePreproc())
    status = tick_ai(node, 0.0)
    assert status == ArtificialIntelligence.US_DONE
    assert child.updates == 0, "PS_DONE must NOT fall through to the child"


def test_ps_invalid_also_reports_us_done():
    node, child = _wrap(_InvalidPreproc())
    status = tick_ai(node, 0.0)
    assert status == ArtificialIntelligence.US_DONE
    assert child.updates == 0


def test_ps_normal_runs_the_child():
    node, child = _wrap(_NormalPreproc())
    status = tick_ai(node, 0.0)
    assert status == ArtificialIntelligence.US_ACTIVE
    assert child.updates == 1


def test_cadence_skipped_tick_reproduces_the_last_status():
    """The preprocessor only runs when it is due; on the ticks in between the
    driver reproduces its last decision. That reproduction needs the same
    three-way mapping as the live branch."""
    node, child = _wrap(_SkipDormantPreproc())
    assert tick_ai(node, 0.0) == ArtificialIntelligence.US_DORMANT
    # 1 s later the 5 s cadence has not elapsed: still dormant, child untouched.
    assert tick_ai(node, 1.0) == ArtificialIntelligence.US_DORMANT
    assert child.updates == 0


def test_cadence_skipped_tick_reproduces_a_ps_done_too():
    """The lethal arm has to exist in BOTH halves of the mapping. A node that
    reported PS_DONE stays US_DONE on the ticks where its cadence hasn't
    elapsed — it must not quietly resurrect and start dispatching its child."""
    node, child = _wrap(_SlowDonePreproc())
    assert tick_ai(node, 0.0) == ArtificialIntelligence.US_DONE
    # 1 s later the 5 s cadence has not elapsed: the preprocessor does not run,
    # so the driver reproduces its last decision — still done, child untouched.
    assert tick_ai(node, 1.0) == ArtificialIntelligence.US_DONE
    assert child.updates == 0


def test_the_sdk_manage_power_is_swapped_for_the_engine_replacement():
    """The shipped Compound doctrines build AI.Preprocessors.ManagePower, whose
    Update returns PS_DONE. Unswapped, that would delete every Federation ship's
    AI on the first preprocess tick."""
    import AI.Preprocessors

    sdk_inst = AI.Preprocessors.ManagePower(0)
    assert sdk_inst.Update(0.0) == App.PreprocessingAI.PS_DONE, (
        "sanity: the SDK stub really does return the lethal value")

    node = PreprocessingAI_Create(None, "PowerManagement")
    child_ai = PlainAI_Create(None, "child")
    child = _Child()
    child_ai._script_instance = child
    node.SetContainedAI(child_ai)
    node.SetPreprocessingMethod(sdk_inst, "Update")

    # The bound instance must be OUR replacement, not the SDK stub.
    bound = node.GetPreprocessingInstance()
    assert isinstance(bound, ai_optimized.ManagePower)
    assert bound.GetNextUpdateTime() == 3.0
    assert bound.Update(0.0) == App.PreprocessingAI.PS_NORMAL

    status = tick_ai(node, 0.0)
    assert status == ArtificialIntelligence.US_ACTIVE
    assert child.updates == 1, "the combat subtree must keep running"


def test_conserve_power_argument_is_carried_across_the_swap():
    import AI.Preprocessors
    node = PreprocessingAI_Create(None, "PowerManagement")
    node.SetPreprocessingMethod(AI.Preprocessors.ManagePower(1), "Update")
    assert node.GetPreprocessingInstance().bConservePower == 1


def test_pcodeai_is_bound_onto_the_replacement_not_the_discarded_original():
    """SetPreprocessingMethod binds pCodeAI onto whatever it STORES. Order
    matters: swap first, then bind onto the REPLACEMENT (the original is deleted
    outright in the shipped engine). Our ManagePower replacement defines no
    CodeAISet — the generic CodeAISet() call at bind time is covered by
    tests/unit/test_codeaiset_bind.py."""
    import AI.Preprocessors
    node = PreprocessingAI_Create(None, "PowerManagement")
    sdk_inst = AI.Preprocessors.ManagePower(0)
    node.SetPreprocessingMethod(sdk_inst, "Update")
    bound = node.GetPreprocessingInstance()
    assert bound is not sdk_inst
    assert bound.pCodeAI is node


def test_an_unregistered_preprocessor_is_left_alone():
    """GetOptimizedVersion's default is "return this" — no registry hit, no swap.
    AlertLevel is deliberately NOT registered (it isn't in the binary's registry
    either, which is why its Python body correctly returns PS_NORMAL)."""
    inst = _NormalPreproc()
    node = PreprocessingAI_Create(None, "wrap")
    node.SetPreprocessingMethod(inst, "Update")
    assert node.GetPreprocessingInstance() is inst


def test_the_registry_holds_the_three_classes_whose_python_bodies_can_be_lethal():
    """The binary registers four preprocessors (AvoidObstacles, FireScript,
    ManagePower, SelectTarget). We register the three whose SDK Python Update can
    return PS_DONE: ManagePower (full replacement) plus FireScript and
    AvoidObstacles (thin non-lethal wrappers around the real SDK bodies).

    SelectTarget is deliberately absent — its Python body cannot return PS_DONE
    (pinned below), so it needs no protection."""
    assert set(ai_optimized.OPTIMIZED_PREPROCESSORS) == {
        "ManagePower", "FireScript", "AvoidObstacles",
    }


def test_select_targets_sdk_body_cannot_return_ps_done():
    """The reason SelectTarget stays out of the registry. Its no-target path
    returns PS_SKIP_DORMANT (AI/Preprocessors.py, eNoTargetPreprocessStatus) —
    it never returns PS_DONE, so running its Python body cannot kill an AI node.
    If this ever goes red, SelectTarget needs a wrapper like FireScript's."""
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[2]
    src = (root / "sdk/Build/scripts/AI/Preprocessors.py").read_text()
    # Slice the SelectTarget class body out of the SDK source (the SDK modules
    # are loaded through a custom finder, so inspect.getsource can't see them).
    body = re.search(r"^class SelectTarget:\n(.*?)^class ", src, re.S | re.M)
    assert body is not None, "SelectTarget vanished from the SDK?"
    assert "PS_DONE" not in body.group(1)


# --- FireScript / AvoidObstacles: the SDK bodies CAN return PS_DONE ----------
#
# We run those Python bodies (the shipped engine does not — it swaps in native
# classes). PS_DONE is lethal, and US_DONE is unrecoverable in our driver, so an
# unwrapped FireScript that momentarily loses its target would permanently delete
# the ship's AI. The shipped game plainly does not behave that way.


def _wire_ship_with_fire_script(target_name="Target"):
    """A real SDK FireScript on a real ship in a real set, as CreateAI builds it."""
    from engine.appc.ships import ShipClass
    from engine.appc.subsystems import HullSubsystem
    import AI.Preprocessors

    App.g_kSetManager._sets.clear()
    pSet = App.SetClass_Create()
    pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet

    ours = ShipClass()
    ours.SetTranslateXYZ(0, 0, 0)
    ours._hull = HullSubsystem("H")
    ours._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(ours, "Ours")

    target = ShipClass()
    target.SetTranslateXYZ(0, 100, 0)
    target._hull = HullSubsystem("H")
    target._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(target, target_name)

    node = PreprocessingAI_Create(ours, "FireScript")
    child_ai = PlainAI_Create(ours, "child")
    child = _Child()
    child_ai._script_instance = child
    node.SetContainedAI(child_ai)
    node.SetPreprocessingMethod(AI.Preprocessors.FireScript(target_name), "Update")
    return node, child, pSet, target


def test_a_fire_script_that_loses_its_target_does_not_kill_the_ai():
    """FedAttack/NonFedAttack/CloakAttack all build FireScript nodes. Its Update
    returns PS_DONE the moment GetTarget() comes back None (target destroyed, or
    it left the set). Unwrapped that is US_DONE — the AI node dies forever."""
    node, child, pSet, target = _wire_ship_with_fire_script()

    # Target present: normal dispatch (no weapons added -> PS_NORMAL).
    assert tick_ai(node, 0.0) == ArtificialIntelligence.US_ACTIVE
    assert child.updates == 1

    # Target destroyed / left the set. FireScript.GetTarget -> None -> PS_DONE.
    pSet.RemoveObjectFromSet("Target")
    status = tick_ai(node, 1.0)
    assert status != ArtificialIntelligence.US_DONE, (
        "a targetless FireScript must not delete the ship's AI")
    assert status == ArtificialIntelligence.US_DORMANT
    assert child.updates == 1, "no target: the combat subtree must not run"


def test_the_ai_recovers_when_a_fire_script_re_acquires_a_target():
    """US_DONE is unrecoverable in our driver (_tick_priority_list skips DONE
    children forever). The whole point of the non-lethal translation is that the
    node comes back the moment the SDK body says PS_NORMAL again."""
    node, child, pSet, target = _wire_ship_with_fire_script()
    assert tick_ai(node, 0.0) == ArtificialIntelligence.US_ACTIVE

    pSet.RemoveObjectFromSet("Target")
    assert tick_ai(node, 1.0) == ArtificialIntelligence.US_DORMANT

    # A new contact turns up under the same name (FireScript targets by name).
    pSet.AddObjectToSet(target, "Target")
    assert tick_ai(node, 2.0) == ArtificialIntelligence.US_ACTIVE
    assert child.updates == 2, "the AI must resume firing, not stay dead"


def test_the_wrapped_fire_script_is_still_the_real_sdk_fire_script():
    """The wrapper delegates: it IS an SDK FireScript (subclass, shared state),
    so every other behaviour our driver depends on — CodeAISet's SetTarget
    registration, subsystem choice, weapon lists — is the SDK's, untouched."""
    import AI.Preprocessors
    node, _child, _pSet, _target = _wire_ship_with_fire_script()
    bound = node.GetPreprocessingInstance()
    assert isinstance(bound, AI.Preprocessors.FireScript)
    assert bound.sTarget == "Target"
    assert bound.pCodeAI is node
    # CodeAISet ran on the bound object.
    assert "SetTarget" in node._external_functions


def test_a_shipless_avoid_obstacles_does_not_kill_the_ai():
    """AvoidObstacles.Update: `if pShip == None: return PS_DONE`
    (AI/Preprocessors.py:1688). Same lethal edge, same wrapper."""
    import AI.Preprocessors

    node = PreprocessingAI_Create(None, "AvoidObstacles")   # no ship
    child_ai = PlainAI_Create(None, "child")
    child = _Child()
    child_ai._script_instance = child
    node.SetContainedAI(child_ai)
    node.SetPreprocessingMethod(AI.Preprocessors.AvoidObstacles(), "Update")

    status = tick_ai(node, 0.0)
    assert status != ArtificialIntelligence.US_DONE
    assert status == ArtificialIntelligence.US_DORMANT
    assert child.updates == 0


# --- Pickling non-lethal wrapped instances ------------------------------------


def test_a_wrapped_fire_script_can_be_pickled_and_unpickled():
    """The non-lethal wrapper creates a dynamic subclass with no module-level
    name. Without registering it in the module's globals, pickle cannot find it
    at unpickle time (AttributeError: can't find FireScript_NonLethal). This test
    verifies that wrapped instances round-trip through pickle.dumps/loads."""
    import pickle
    import AI.Preprocessors

    # Create a FireScript instance (the SDK class defines __getstate__/__setstate__).
    sdk_inst = AI.Preprocessors.FireScript("Target")

    # Wrap it via the non-lethal factory.
    wrapped = ai_optimized._wrap_non_lethal(sdk_inst)

    # Pickle and unpickle.
    pickled = pickle.dumps(wrapped)
    restored = pickle.loads(pickled)

    # Verify the restored object is still a wrapped FireScript.
    assert type(restored).__name__ == "FireScript_NonLethal"
    assert isinstance(restored, AI.Preprocessors.FireScript)
    assert restored.sTarget == "Target"


def test_an_unwrapped_sdk_preprocessor_still_pickles():
    """The underlying SDK class (e.g. FireScript) already defines
    __getstate__/__setstate__, so it should still be picklable."""
    import pickle
    import AI.Preprocessors

    sdk_inst = AI.Preprocessors.FireScript("Target")
    pickled = pickle.dumps(sdk_inst)
    restored = pickle.loads(pickled)
    assert restored.sTarget == "Target"
