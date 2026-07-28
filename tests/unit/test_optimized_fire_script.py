import App
import engine.appc.ai as ai


def test_optimized_fire_script_is_a_class():
    # Must be usable as the 2nd argument of isinstance (a type), not a
    # _NamedStub instance — the bug at TacticalMenuHandlers.py:1861.
    assert isinstance(ai.OptimizedFireScript, type)


def test_app_exposes_optimized_fire_script_as_a_type():
    assert isinstance(App.OptimizedFireScript, type)


def test_isinstance_against_app_optimized_fire_script_does_not_raise():
    # Reproduces the crash: before the fix, App.OptimizedFireScript is a
    # _NamedStub *instance*, so this line raised TypeError inside StartAI.
    assert isinstance(object(), App.OptimizedFireScript) is False


def test_generic_ai_script_instance_is_not_a_fire_script():
    # The data-bag GetPreprocessingInstance returns is (correctly) not a
    # fire script — so StartAI's fire branch is skipped, but SetPlayerAI runs.
    databag = ai._AIScriptInstance(ai=None)
    assert isinstance(databag, App.OptimizedFireScript) is False
