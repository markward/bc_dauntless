import App


def test_friendly_fire_defaults_to_zero():
    # Constructed at module load; these accessors must always return floats.
    fresh = App._UtopiaModule()
    assert fresh.GetCurrentFriendlyFire() == 0.0
    assert isinstance(fresh.GetCurrentFriendlyFire(), float)


def test_friendly_fire_ceilings_default_to_the_engine_values():
    """QuickBattle never calls SetMaxFriendlyFire — it relies on the engine
    default. A 0 tolerance makes MissionLib:3727's `>= tolerance` game-over
    branch always win, so the warning REPORT (the elif) can never fire and the
    XO stays silent. Both values are decoded from a real BC save taken in E8M1,
    a mission that sets neither: docs/original_game_reference/engine/
    bcs-save-format.md preamble scalars 1 and 3."""
    fresh = App._UtopiaModule()
    assert fresh.GetMaxFriendlyFire() == 5000.0
    assert fresh.GetFriendlyFireTolerance() == 5000.0
    assert fresh.GetFriendlyFireWarningPoints() == 300.0


def test_friendly_fire_round_trip():
    fresh = App._UtopiaModule()
    fresh.SetCurrentFriendlyFire(125.5)
    assert fresh.GetCurrentFriendlyFire() == 125.5


def test_friendly_fire_accepts_int_and_coerces_to_float():
    """QuickBattle.py:769 calls SetCurrentFriendlyFire(0) (int)."""
    fresh = App._UtopiaModule()
    fresh.SetCurrentFriendlyFire(0)
    assert fresh.GetCurrentFriendlyFire() == 0.0
    assert isinstance(fresh.GetCurrentFriendlyFire(), float)


def test_friendly_tractor_time_defaults_to_zero():
    fresh = App._UtopiaModule()
    assert fresh.GetFriendlyTractorTime() == 0.0


def test_friendly_tractor_time_round_trip():
    fresh = App._UtopiaModule()
    fresh.SetFriendlyTractorTime(3.25)
    assert fresh.GetFriendlyTractorTime() == 3.25


def test_get_game_time_still_works():
    """Sanity: adding friendly-fire/tractor state must not break the
    pre-existing GetGameTime heartbeat."""
    fresh = App._UtopiaModule()
    assert fresh.GetGameTime() == App.g_kTimerManager.get_time()


def test_singleton_exposes_methods():
    """g_kUtopiaModule (the live module-level instance) routes the SDK calls."""
    App.g_kUtopiaModule.SetCurrentFriendlyFire(42.0)
    assert App.g_kUtopiaModule.GetCurrentFriendlyFire() == 42.0
    App.g_kUtopiaModule.SetCurrentFriendlyFire(0.0)
    App.g_kUtopiaModule.SetFriendlyTractorTime(1.5)
    assert App.g_kUtopiaModule.GetFriendlyTractorTime() == 1.5
    App.g_kUtopiaModule.SetFriendlyTractorTime(0.0)


def test_max_friendly_fire_round_trip():
    fresh = App._UtopiaModule()
    fresh.SetMaxFriendlyFire(500.0)
    assert fresh.GetMaxFriendlyFire() == 500.0


def test_friendly_fire_warning_points_round_trip():
    fresh = App._UtopiaModule()
    fresh.SetFriendlyFireWarningPoints(150.0)
    assert fresh.GetFriendlyFireWarningPoints() == 150.0


def test_captain_name_default():
    fresh = App._UtopiaModule()
    name = fresh.GetCaptainName()
    assert name == "Picard"
    # Must support .GetCString() chain (MissionLib.py:2801)
    assert name.GetCString() == "Picard"


def test_captain_name_round_trip():
    fresh = App._UtopiaModule()
    fresh.SetCaptainName("Janeway")
    assert fresh.GetCaptainName() == "Janeway"
    assert fresh.GetCaptainName().GetCString() == "Janeway"


def test_multiplayer_state_defaults_to_offline():
    fresh = App._UtopiaModule()
    assert fresh.IsHost() == 0
    assert fresh.IsClient() == 0
    assert fresh.IsMultiplayer() == 0
    assert fresh.GetNetwork() is None  # SDK guards with `if pNetwork:`


def test_get_next_event_type_returns_increasing_ints():
    a = App.g_kUtopiaModule.GetNextEventType()
    b = App.g_kUtopiaModule.GetNextEventType()
    assert isinstance(a, int)
    assert b > a


def test_module_level_get_next_event_type_alias_returns_int():
    """SDK calls App.UtopiaModule_GetNextEventType() at module top-level."""
    a = App.UtopiaModule_GetNextEventType()
    b = App.UtopiaModule_GetNextEventType()
    assert isinstance(a, int)
    assert b > a


def test_module_level_and_method_share_counter():
    """Both forms must allocate from the same counter — duplicate IDs would
    cause distinct event types to collide."""
    seen = set()
    for _ in range(5):
        seen.add(App.UtopiaModule_GetNextEventType())
        seen.add(App.g_kUtopiaModule.GetNextEventType())
        seen.add(App.Game_GetNextEventType())
    assert len(seen) == 15
