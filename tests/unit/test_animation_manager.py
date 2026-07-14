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


def test_a_later_registration_must_win_or_the_captains_sit_camera_breaks():
    """LAST-write-wins is load-bearing: BC re-registers a name to CORRECT it.

    GalaxyBridge.py:193's PreloadAnimations has a TYPO - it registers
    "DBCameraSitDown" against 'DB_Camera_Sit_Downp.nif' ("Downp"), a file that
    does not exist. The animation builder later re-registers the SAME name
    against the correct 'DB_Camera_Sit_Down.nif'. The correct path must win.

    Making this first-write-wins (commit 20c62e96) let the TYPO win:
    GetAnimationLength("DBCameraSitDown") went to 0.0, every sequence delay of
    the form `GetAnimationLength(x) - 1.7` went NEGATIVE, TGSequence treats a
    negative delay as fire-now, and E1M1's whole opening collapsed to t=0 (the
    captain's walk-on skipped, all timers firing at once, Admiral Liu on the
    viewscreen while Helm was still announcing her call).

    The extension-less console-gesture paths are tolerated at LOAD time
    instead - see engine/host_loop.py::_resolve_asset_path.
    """
    m = AnimationManager()
    m.LoadAnimation("data/animations/DB_Camera_Sit_Downp.nif", "DBCameraSitDown")
    m.LoadAnimation("data/animations/DB_Camera_Sit_Down.nif", "DBCameraSitDown")
    assert m.path_for("DBCameraSitDown") == "data/animations/DB_Camera_Sit_Down.nif"


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


# GetAnimationLength must return the REAL clip length.
#
# The SDK schedules the walk-off lift door relative to it:
#     fTime = kAM.GetAnimationLength("db_PtoL1_P")
#     pSequence.AddAction(pDoorAction, pAnimAction_Stand, fTime - 1.25)
# Returning 0.0 makes that offset -1.25s, so the door timing is meaningless.

def test_get_animation_length_uses_the_duration_provider():
    am = AnimationManager()
    am.LoadAnimation("data/animations/db_PtoL1_P.nif", "db_PtoL1_P")
    am.set_duration_provider(lambda path: 4.5 if path.endswith("db_PtoL1_P.nif") else 0.0)
    assert am.GetAnimationLength("db_PtoL1_P") == 4.5


def test_walk_off_door_offset_is_positive():
    """The whole point: fTime - 1.25 must land INSIDE the walk, not before it."""
    am = AnimationManager()
    am.LoadAnimation("data/animations/db_PtoL1_P.nif", "db_PtoL1_P")
    am.set_duration_provider(lambda path: 4.5)
    assert am.GetAnimationLength("db_PtoL1_P") - 1.25 > 0.0


def test_duration_is_cached_per_name():
    calls = []

    def provider(path):
        calls.append(path)
        return 2.0

    am = AnimationManager()
    am.LoadAnimation("data/animations/x.nif", "x")
    am.set_duration_provider(provider)
    assert am.GetAnimationLength("x") == 2.0
    assert am.GetAnimationLength("x") == 2.0
    assert len(calls) == 1, "the clip must be measured once, not once per query"


def test_unknown_name_and_no_provider_return_zero_not_raise():
    am = AnimationManager()
    assert am.GetAnimationLength("nope") == 0.0        # no provider, headless
    am.set_duration_provider(lambda path: 3.0)
    assert am.GetAnimationLength("nope") == 0.0        # name never registered


def test_provider_failure_degrades_to_zero():
    def boom(path):
        raise RuntimeError("no renderer")

    am = AnimationManager()
    am.LoadAnimation("data/animations/x.nif", "x")
    am.set_duration_provider(boom)
    assert am.GetAnimationLength("x") == 0.0


def test_freeing_an_animation_drops_its_cached_duration():
    am = AnimationManager()
    am.LoadAnimation("data/animations/x.nif", "x")
    am.set_duration_provider(lambda path: 2.0)
    assert am.GetAnimationLength("x") == 2.0
    am.FreeAnimation("x")
    assert am.GetAnimationLength("x") == 0.0


def test_reloading_a_name_with_a_different_path_invalidates_cached_duration():
    """A bridge/mission reload can re-register the same NAME against a
    DIFFERENT underlying clip (LoadAnimation's own docstring: a re-load of a
    name overwrites). The cached duration measured against the OLD path must
    not survive - otherwise the walk-off door timing silently uses the FIRST
    mission's clip length forever (g_kAnimationManager is a process-lifetime
    singleton)."""
    am = AnimationManager()
    am.LoadAnimation("data/animations/a.nif", "x")
    am.set_duration_provider(lambda path: 4.5 if path.endswith("a.nif") else 9.0)
    assert am.GetAnimationLength("x") == 4.5

    am.LoadAnimation("data/animations/b.nif", "x")
    assert am.GetAnimationLength("x") == 9.0


def test_provider_exception_result_is_retried_not_poisoned():
    """A provider EXCEPTION is caught and degrades to 0.0 - but that must not
    be cached, since a transient failure (e.g. renderer not ready yet) should
    be retryable on the next query rather than poisoning the cache for the
    process lifetime. (This is distinct from a provider that successfully
    returns a genuine 0.0 - that result IS cached, same as any other length;
    see test_duration_is_cached_per_name.)"""
    calls = []

    def provider(path):
        calls.append(path)
        if len(calls) == 1:
            raise RuntimeError("renderer not ready yet")
        return 3.0

    am = AnimationManager()
    am.LoadAnimation("data/animations/x.nif", "x")
    am.set_duration_provider(provider)
    assert am.GetAnimationLength("x") == 0.0
    assert am.GetAnimationLength("x") == 3.0
    assert len(calls) == 2
