"""Unit tests for AI driver preprocess signature widening.

SDK preprocess methods come in two shapes:
  Update(self)              — 0-arg (existing synthetic tests use this)
  Update(self, dEndTime)    — 1-arg (SDK SelectTarget, FireScript, etc.)
The driver detects via inspect.signature and passes game_time + 1.0
when the method accepts a positional arg."""
import App
from engine.appc.ai import PreprocessingAI_Create, PlainAI_Create
from engine.appc.ai_driver import tick_ai
from engine.appc.ships import ShipClass


class _ZeroArgPreprocessor:
    """Synthetic preprocessor with 0-arg Preprocess (matches the
    existing test pattern from prior slices)."""
    def __init__(self):
        self.calls = []

    def Preprocess(self):
        self.calls.append("zero")
        return App.PreprocessingAI.PS_NORMAL


class _OneArgPreprocessor:
    """SDK-shaped preprocessor with 1-arg Update."""
    def __init__(self):
        self.calls = []

    def Update(self, dEndTime):
        self.calls.append(dEndTime)
        return App.PreprocessingAI.PS_NORMAL


def _make_preprocessing_ai(ship, instance, method_name):
    pp = PreprocessingAI_Create(ship, "TestPP")
    pp.SetPreprocessingMethod(instance, method_name)
    return pp


def test_zero_arg_preprocess_called_with_no_args():
    ship = ShipClass()
    spy = _ZeroArgPreprocessor()
    pp = _make_preprocessing_ai(ship, spy, "Preprocess")
    tick_ai(pp, game_time=0.5)
    assert spy.calls == ["zero"]


def test_one_arg_preprocess_receives_game_time_plus_one():
    ship = ShipClass()
    spy = _OneArgPreprocessor()
    pp = _make_preprocessing_ai(ship, spy, "Update")
    tick_ai(pp, game_time=2.0)
    # Driver passes game_time + 1.0 as the deadline.
    assert spy.calls == [3.0]


def test_signature_introspection_caches_after_first_tick():
    """Arity decision is cached on the PreprocessingAI instance after
    the first dispatch — subsequent ticks don't re-introspect."""
    import inspect

    ship = ShipClass()
    spy = _OneArgPreprocessor()
    pp = _make_preprocessing_ai(ship, spy, "Update")

    # First tick: introspection runs, cache is populated.
    tick_ai(pp, game_time=1.0)
    assert hasattr(pp, "_preprocess_arity_cache")
    cached = pp._preprocess_arity_cache

    # Patch inspect.signature so a second call would crash if used.
    real_sig = inspect.signature
    inspect.signature = lambda fn: (_ for _ in ()).throw(
        RuntimeError("re-introspected; cache miss"))
    try:
        tick_ai(pp, game_time=5.0)
    finally:
        inspect.signature = real_sig

    assert pp._preprocess_arity_cache is cached
    assert spy.calls == [2.0, 6.0]
