"""Test normalization of preprocessing method names with trailing parentheses.

The SDK AI editor exports can produce method names like "Update()" with
trailing parentheses (a typo in BC's Defense.py:214). Python's getattr()
fails on "Update()" since it's not a valid attribute name. The fix is to
normalize at bind time in SetPreprocessingMethod by stripping the trailing
"()" before storing the method name.
"""
import App
from engine.appc.ai import PreprocessingAI_Create, PlainAI_Create
from engine.appc.ai_driver import tick_ai
from engine.appc.ships import ShipClass


class _PreprocessorWithTrailingParens:
    """Synthetic preprocessor where the method has trailing parentheses
    in the method name (as seen in Defense.py:214 from BC's AI export)."""
    def __init__(self):
        self.calls = []

    def Update(self, dEndTime):
        self.calls.append(dEndTime)
        return App.PreprocessingAI.PS_NORMAL


def _make_preprocessing_ai(ship, instance, method_name):
    pp = PreprocessingAI_Create(ship, "TestPP")
    pp.SetPreprocessingMethod(instance, method_name)
    return pp


def test_preprocessing_method_with_trailing_parens_red():
    """RED: calling SetPreprocessingMethod with "Update()" (with parens)
    should normalize to "Update" so tick_ai doesn't crash on getattr."""
    ship = ShipClass()
    spy = _PreprocessorWithTrailingParens()

    # This is the problematic call from Defense.py:214
    pp = _make_preprocessing_ai(ship, spy, "Update()")

    # Before the fix: tick_ai would crash with AttributeError:
    # 'PreprocessorWithTrailingParens' object has no attribute 'Update()'
    # After the fix: tick_ai should succeed by finding the 'Update' method.
    tick_ai(pp, game_time=2.0)
    assert spy.calls == [3.0]


def test_preprocessing_method_without_parens_unchanged():
    """GREEN: the normal case without trailing parens should still work."""
    ship = ShipClass()
    spy = _PreprocessorWithTrailingParens()
    pp = _make_preprocessing_ai(ship, spy, "Update")
    tick_ai(pp, game_time=2.0)
    assert spy.calls == [3.0]


def test_preprocessing_method_single_arg_form_with_parens():
    """Test the single-argument form of SetPreprocessingMethod also
    normalizes trailing parens."""
    ship = ShipClass()
    spy = _PreprocessorWithTrailingParens()
    pp = PreprocessingAI_Create(ship, "TestPP")

    # Single-arg form: SetPreprocessingMethod(method_name)
    # This should also normalize the method name.
    pp.SetPreprocessingMethod("Update()")

    # The single-arg form creates an internal _AIScriptInstance wrapper.
    # We can't directly call it with tick_ai, but we can verify the
    # method name is stored correctly by checking the private attr.
    assert pp._preprocessing_method == "Update"


def test_preprocessing_method_multiple_trailing_parens():
    """Edge case: malformed method name with multiple trailing parens
    should only strip one pair."""
    ship = ShipClass()
    spy = _PreprocessorWithTrailingParens()
    pp = PreprocessingAI_Create(ship, "TestPP")
    pp.SetPreprocessingMethod(spy, "Update()()")
    # Should strip only the last "()", leaving "Update()"
    # (This is a pathological case, but let's be precise about the fix.)
    assert pp._preprocessing_method == "Update()"
