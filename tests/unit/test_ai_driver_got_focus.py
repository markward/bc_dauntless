"""PreprocessingAI driver should call GotFocus() on the preprocessing
instance the first time the wrapper becomes active.

Why this matters: SDK preprocessors like AlertLevel
(sdk/Build/scripts/AI/Preprocessors.py:2018) put their side-effecting
initialization in GotFocus, not Update. AlertLevel.Update is a no-op
returning PS_NORMAL; the SetAlertLevel(RED_ALERT) call lives in
GotFocus. Without this dispatch, enemy ships running NonFedAttack
never go to red alert → weapon systems stay TurnOff'd →
PhaserSystem.StartFiring early-returns silently. See
tests/integration/test_close_range_combat_diagnostic.py for the
trail that established this.

Other SDK preprocessors that rely on GotFocus: CloakShip (toggles
the cloaking subsystem), Defensive (resets sub-AI state), and a
handful in mission-specific scripts.
"""
from engine.appc.ai import ArtificialIntelligence, PreprocessingAI
from engine.appc.ai_driver import tick_ai
from engine.appc.ships import ShipClass


class _PreprocessorWithFocus:
    def __init__(self):
        self.got_focus_calls = 0
        self.update_calls = 0

    def GotFocus(self):
        self.got_focus_calls += 1

    def Update(self, dEndTime):
        self.update_calls += 1
        return PreprocessingAI.PS_NORMAL


class _PreprocessorNoFocus:
    def __init__(self):
        self.update_calls = 0

    def Update(self, dEndTime):
        self.update_calls += 1
        return PreprocessingAI.PS_NORMAL


def _wrap(inst):
    pp = PreprocessingAI(ShipClass(), "PP")
    pp.SetPreprocessingMethod(inst, "Update")
    return pp


def test_got_focus_called_once_on_first_active_tick():
    inst = _PreprocessorWithFocus()
    pp = _wrap(inst)
    tick_ai(pp, game_time=0.0)
    assert inst.got_focus_calls == 1
    assert inst.update_calls == 1


def test_got_focus_not_recalled_on_subsequent_ticks():
    inst = _PreprocessorWithFocus()
    pp = _wrap(inst)
    tick_ai(pp, game_time=0.0)
    tick_ai(pp, game_time=1.0)
    tick_ai(pp, game_time=2.0)
    assert inst.got_focus_calls == 1
    assert inst.update_calls == 3


def test_preprocessor_without_got_focus_does_not_error():
    inst = _PreprocessorNoFocus()
    pp = _wrap(inst)
    tick_ai(pp, game_time=0.0)
    assert inst.update_calls == 1
    assert pp._status == ArtificialIntelligence.US_ACTIVE


def test_got_focus_side_effects_visible_to_contained_ai():
    """AlertLevel pattern: GotFocus mutates ship state; that state
    becomes the precondition for whatever the contained AI does."""
    class AlertLevelLike:
        def __init__(self, ship):
            self.ship = ship

        def GotFocus(self):
            # Mirror sdk/.../AI/Preprocessors.py:2049-2052.
            self.ship._alert_level = ShipClass.RED_ALERT

        def Update(self, dEndTime):
            return PreprocessingAI.PS_NORMAL

    ship = ShipClass()
    assert ship._alert_level == ShipClass.GREEN_ALERT
    inst = AlertLevelLike(ship)
    pp = PreprocessingAI(ship, "PP")
    pp.SetPreprocessingMethod(inst, "Update")
    tick_ai(pp, game_time=0.0)
    assert ship._alert_level == ShipClass.RED_ALERT
