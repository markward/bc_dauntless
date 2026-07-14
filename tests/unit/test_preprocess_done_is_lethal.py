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


def test_the_replacement_gets_pcodeai_and_its_codeaiset_runs():
    """SetPreprocessingMethod binds pCodeAI onto whatever it stores, and calls
    that object's CodeAISet(). Order matters: swap first, then bind onto the
    REPLACEMENT (the original is deleted outright in the shipped engine)."""
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


def test_fire_script_and_select_target_are_deliberately_not_registered():
    """The binary swaps four preprocessors; we register only ManagePower. The
    other three have working SDK Python bodies that our driver runs, and we have
    no native replacements — a documented divergence, pinned here so nobody
    "completes" the registry by accident."""
    assert set(ai_optimized.OPTIMIZED_PREPROCESSORS) == {"ManagePower"}
