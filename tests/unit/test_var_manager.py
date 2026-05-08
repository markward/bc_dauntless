import App
from engine.appc.var_manager import TGVarManager


def test_app_exposes_var_manager():
    assert isinstance(App.g_kVarManager, TGVarManager)


def test_get_float_default_is_zero():
    vm = TGVarManager()
    assert vm.GetFloatVariable("global", "fNotSet") == 0.0


def test_set_then_get_float():
    vm = TGVarManager()
    vm.SetFloatVariable("global", "PlayedTutorial", 1.0)
    assert vm.GetFloatVariable("global", "PlayedTutorial") == 1.0


def test_float_variable_coerces_to_float():
    vm = TGVarManager()
    vm.SetFloatVariable("global", "n", 5)  # int input
    out = vm.GetFloatVariable("global", "n")
    assert out == 5.0
    assert isinstance(out, float)


def test_get_string_default_is_empty():
    vm = TGVarManager()
    out = vm.GetStringVariable("Options", "Missing")
    assert out == ""
    # Returned as _TGString so SDK chains like .GetCString() work.
    assert out.GetCString() == ""


def test_set_then_get_string():
    vm = TGVarManager()
    vm.SetStringVariable("Options", "MissionOverride", "E1M1")
    out = vm.GetStringVariable("Options", "MissionOverride")
    assert out == "E1M1"
    assert out.GetCString() == "E1M1"


def test_scopes_are_independent():
    vm = TGVarManager()
    vm.SetFloatVariable("global", "x", 1.0)
    vm.SetFloatVariable("Options", "x", 2.0)
    assert vm.GetFloatVariable("global", "x") == 1.0
    assert vm.GetFloatVariable("Options", "x") == 2.0


def test_delete_all_variables_clears_both_namespaces():
    vm = TGVarManager()
    vm.SetFloatVariable("global", "f", 1.0)
    vm.SetStringVariable("global", "s", "x")
    vm.DeleteAllVariables()
    assert vm.GetFloatVariable("global", "f") == 0.0
    assert vm.GetStringVariable("global", "s") == ""


def test_delete_scoped_variables_only_clears_one_scope():
    vm = TGVarManager()
    vm.SetFloatVariable("global", "f", 1.0)
    vm.SetFloatVariable("Options", "f", 2.0)
    vm.DeleteAllScopedVariables("Options")
    assert vm.GetFloatVariable("global", "f") == 1.0
    assert vm.GetFloatVariable("Options", "f") == 0.0


def test_make_episode_event_type_returns_unique_ints():
    """SDK pattern: ET_X = App.g_kVarManager.MakeEpisodeEventType(100).
    Each call must return a unique int — re-using IDs would alias events."""
    a = App.g_kVarManager.MakeEpisodeEventType(100)
    b = App.g_kVarManager.MakeEpisodeEventType(101)
    c = App.g_kVarManager.MakeEpisodeEventType(100)  # same offset, different ID
    assert isinstance(a, int)
    assert len({a, b, c}) == 3


def test_make_episode_event_type_shares_counter_with_game_get_next_event_type():
    """Both APIs allocate from the same counter so cross-API IDs don't collide."""
    seen = set()
    for _ in range(5):
        seen.add(App.g_kVarManager.MakeEpisodeEventType(0))
        seen.add(App.Game_GetNextEventType())
    assert len(seen) == 10


def test_var_manager_without_allocator_uses_local_counter():
    """Standalone VarManager (no allocator) still hands back unique ints."""
    vm = TGVarManager()
    a = vm.MakeEpisodeEventType(0)
    b = vm.MakeEpisodeEventType(0)
    assert isinstance(a, int) and isinstance(b, int)
    assert a != b
