from engine.appc.animation_manager import AnimationManager


def test_load_animation_records_name_to_path():
    m = AnimationManager()
    m.LoadAnimation("data/animations/db_stand_t_l.nif", "db_stand_t_l")
    assert m.path_for("db_stand_t_l") == "data/animations/db_stand_t_l.nif"


def test_path_for_unknown_name_returns_none():
    m = AnimationManager()
    assert m.path_for("nope") is None


def test_reload_same_name_overwrites():
    m = AnimationManager()
    m.LoadAnimation("a.nif", "x")
    m.LoadAnimation("b.nif", "x")
    assert m.path_for("x") == "b.nif"


def test_free_animation_removes_entry():
    m = AnimationManager()
    m.LoadAnimation("data/animations/x.nif", "x")
    m.FreeAnimation("x")
    assert m.path_for("x") is None


def test_free_animation_unknown_name_is_noop():
    m = AnimationManager()
    m.FreeAnimation("never_loaded")   # must not raise


def test_get_animation_length_returns_zero_float():
    m = AnimationManager()
    length = m.GetAnimationLength("x")
    assert length == 0.0
    assert isinstance(length, float)


def test_app_exposes_singleton():
    import App
    assert hasattr(App, "g_kAnimationManager")
    App.g_kAnimationManager.LoadAnimation("data/animations/foo.nif", "foo")
    assert App.g_kAnimationManager.path_for("foo") == "data/animations/foo.nif"
