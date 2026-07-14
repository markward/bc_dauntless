"""SetPreprocessingMethod calls CodeAISet() on the bound instance.

Appc's PreprocessingAI::SetPreprocessingMethod (0x0048e400) writes pCodeAI onto
the Python instance and then calls its CodeAISet() hook. Four shipped
preprocessors have a real one; ours never fired, so UpdateAIStatus never
registered QueryAIStatus and UseShipTarget never installed its target handler.
"""
from engine.appc.ai import PreprocessingAI_Create


class _Preproc:
    def __init__(self):
        self.code_ai_set_calls = 0
        self.pCodeAI_at_call = "unset"

    def CodeAISet(self):
        self.code_ai_set_calls += 1
        # pCodeAI MUST already be bound when the hook runs — the shipped hooks
        # dereference it (FireScript.CodeAISet calls
        # self.pCodeAI.RegisterExternalFunction).
        self.pCodeAI_at_call = self.pCodeAI

    def Update(self, dEndTime):
        return None


class _NoHook:
    def Update(self, dEndTime):
        return None


def test_code_ai_set_is_called_after_pcodeai_is_bound():
    node = PreprocessingAI_Create(None, "wrap")
    inst = _Preproc()
    node.SetPreprocessingMethod(inst, "Update")

    assert inst.code_ai_set_calls == 1
    assert inst.pCodeAI_at_call is node


def test_an_instance_without_the_hook_binds_cleanly():
    node = PreprocessingAI_Create(None, "wrap")
    inst = _NoHook()
    node.SetPreprocessingMethod(inst, "Update")   # must not raise
    assert node.GetPreprocessingInstance() is inst
