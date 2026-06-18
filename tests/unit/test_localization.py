from engine.appc.localization import (
    TGLocalizationManager, TGLocalizationDatabase, TGString, _TGString,
)


# ---------------------------------------------------------------------------
# TGString comparison API — the real Appc binds both Compare (TGString vs
# TGString) and CompareC (TGString vs C string) on TGString (App.py:436-437),
# with C strcmp semantics (0 == equal). Both our TGString classes must expose
# them: the mutable factory (App.TGString()) and the str-subclass returned by
# localization lookups. Bridge menu enable/disable + docking-AI name matching
# depend on this (e.g. HelmMenuHandlers.py:2125, MissionLib.py:1818).
# ---------------------------------------------------------------------------

def test_mutable_tgstring_compare_equal_returns_zero():
    kString = TGString("USS Dauntless")
    assert kString.Compare(_TGString("USS Dauntless")) == 0


def test_mutable_tgstring_compare_different_is_nonzero():
    kString = TGString("USS Dauntless")
    assert kString.Compare(_TGString("Starbase 12")) != 0


def test_mutable_tgstring_compare_case_insensitive_flag():
    kString = TGString("USS Dauntless")
    assert kString.Compare("uss dauntless", 1) == 0
    assert kString.Compare("uss dauntless", 0) != 0


def test_mutable_tgstring_compare_against_tgstring_arg():
    """BridgeMenus.py:135 — kName.Compare(kMenuName) where both are TGString;
    the arg's repr must NOT leak into the comparison."""
    assert TGString("Helm").Compare(TGString("Helm")) == 0
    assert TGString("Helm").Compare(TGString("Tactical")) != 0


def test_mutable_tgstring_comparec_matches_c_string():
    assert TGString("Docking Entry Start").CompareC("Docking Entry Start", 1) == 0


def test_immutable_tgstring_compare_round_trips():
    assert _TGString("Helm").Compare("Helm") == 0
    assert _TGString("Helm").Compare(_TGString("Tactical")) != 0


def test_tgstring_acts_as_python_str():
    s = _TGString("Helm")
    assert s == "Helm"
    assert s + " Officer" == "Helm Officer"
    assert "saves/" + s + ".bcs" == "saves/Helm.bcs"


def test_tgstring_get_cstring_returns_str_compatible():
    """GetCString returns a value that compares == to str and supports str ops.
    The concrete type is _TGString so that downstream `% args` formatting
    routes through our tolerant __mod__."""
    s = _TGString("Helm")
    out = s.GetCString()
    assert out == "Helm"
    assert isinstance(out, str)


def test_tgstring_get_length():
    assert _TGString("ab").GetLength() == 2


def test_tgstring_chain_get_string_get_cstring():
    """SDK pattern: pDatabase.GetString("k").GetCString()"""
    s = _TGString("Helm")
    assert s.GetString().GetCString() == "Helm"


def test_tgstring_mod_with_placeholders_substitutes():
    s = _TGString("Score: %s / Kills: %s")
    assert s % ("12", "3") == "Score: 12 / Kills: 3"


def test_tgstring_mod_without_placeholders_returns_self():
    """Phase 1: key-as-value fallback strings tolerate excess format args."""
    s = _TGString("Your Stats")  # no placeholders (fallback returned the key)
    assert s % ("12", "3") == "Your Stats"


def test_tgstring_mod_returns_tgstring_subclass():
    s = _TGString("a=%s")
    out = s % ("1",)
    assert isinstance(out, _TGString)
    assert out.GetCString() == "a=1"


def test_load_returns_database():
    mgr = TGLocalizationManager()
    db = mgr.Load("data/TGL/Bridge Menus.tgl")
    assert isinstance(db, TGLocalizationDatabase)
    assert db.GetSourceFilename() == "data/TGL/Bridge Menus.tgl"


def test_load_same_file_twice_returns_same_database():
    mgr = TGLocalizationManager()
    db1 = mgr.Load("a.tgl")
    db2 = mgr.Load("a.tgl")
    assert db1 is db2


def test_get_if_registered_returns_loaded_db():
    mgr = TGLocalizationManager()
    db = mgr.Load("a.tgl")
    assert mgr.GetIfRegistered("a.tgl") is db
    assert mgr.GetIfRegistered("never-loaded.tgl") is None


def test_get_string_returns_key_when_not_decoded():
    db = TGLocalizationDatabase("any.tgl")
    assert db.GetString("Helm") == "Helm"
    assert db.GetString("Friendly Fire") == "Friendly Fire"


def test_get_string_returns_tgstring_with_cstring():
    """SDK chains pDatabase.GetString(k).GetCString() — must not raise."""
    db = TGLocalizationDatabase("any.tgl")
    assert db.GetString("Helm").GetCString() == "Helm"


def test_get_string_returns_translation_when_present():
    db = TGLocalizationDatabase("any.tgl")
    db._strings["Helm"] = "Conn"
    assert db.GetString("Helm") == "Conn"


def test_has_string_reflects_registered_keys():
    db = TGLocalizationDatabase("any.tgl")
    assert db.HasString("Helm") is False
    db._strings["Helm"] = "Conn"
    assert db.HasString("Helm") is True


def test_get_filename_returns_empty_string_when_unknown():
    db = TGLocalizationDatabase("any.tgl")
    assert db.GetFilename("OpenCaptain05") == ""


def test_get_filename_returns_registered_wav():
    db = TGLocalizationDatabase("any.tgl")
    db._sounds["OpenCaptain05"] = "OpenCaptain05.wav"
    assert db.GetFilename("OpenCaptain05") == "OpenCaptain05.wav"


def test_unload_decrements_refcount():
    mgr = TGLocalizationManager()
    db = mgr.Load("a.tgl")
    mgr.Load("a.tgl")  # refcount = 2
    mgr.Unload(db)     # refcount = 1
    assert mgr.GetIfRegistered("a.tgl") is db
    mgr.Unload(db)     # refcount = 0 -> evicted
    assert mgr.GetIfRegistered("a.tgl") is None


def test_unload_unknown_database_is_noop():
    mgr = TGLocalizationManager()
    other = TGLocalizationDatabase("not-loaded.tgl")
    mgr.Unload(other)  # must not raise


def test_register_database_inserts_into_cache():
    mgr = TGLocalizationManager()
    db = TGLocalizationDatabase("manual.tgl")
    mgr.RegisterDatabase(db)
    assert mgr.GetIfRegistered("manual.tgl") is db


def test_delete_all_clears_cache():
    mgr = TGLocalizationManager()
    mgr.Load("a.tgl")
    mgr.Load("b.tgl")
    mgr.DeleteAll()
    assert mgr.GetIfRegistered("a.tgl") is None
    assert mgr.GetIfRegistered("b.tgl") is None


def test_database_is_truthy():
    db = TGLocalizationDatabase("any.tgl")
    assert bool(db) is True


def test_app_tgstring_factory_round_trips_value():
    """SDK hardpoint pattern: kS = App.TGString(); kS.SetString("x;y"); pProp.SetFiringChainString(kS).

    App.TGString must be a real factory (not _NamedStub) so the firing-chain
    CSV survives to GetFiringChainString().GetString() consumers.
    """
    import App
    kS = App.TGString()
    kS.SetString("0;Single;123;Dual;53;Quad")
    assert kS.GetString() == "0;Single;123;Dual;53;Quad"
    assert kS.GetCString() == "0;Single;123;Dual;53;Quad"


def test_app_tgstring_initial_value():
    import App
    kS = App.TGString("hello")
    assert kS.GetString() == "hello"


def test_app_tgstring_factory_round_trips_through_property():
    """End-to-end: SDK hands the TGString to WeaponSystemProperty; getter returns the CSV."""
    import App
    phasers = App.WeaponSystemProperty_Create("Phasers")
    kS = App.TGString()
    kS.SetString("0;Single;123;Dual")
    phasers.SetFiringChainString(kS)
    assert phasers.GetFiringChainString().GetString() == "0;Single;123;Dual"


def test_app_exposes_localization_manager():
    import App
    assert isinstance(App.g_kLocalizationManager, TGLocalizationManager)


def test_app_load_round_trip():
    import App
    App.g_kLocalizationManager.DeleteAll()
    db = App.g_kLocalizationManager.Load("data/TGL/Bridge Menus.tgl")
    assert isinstance(db, TGLocalizationDatabase)
    assert db.GetString("Helm") == "Helm"
    App.g_kLocalizationManager.Unload(db)
    assert App.g_kLocalizationManager.GetIfRegistered("data/TGL/Bridge Menus.tgl") is None


# ── Manager actually parses TGL files when they exist on disk ────────────────
# The shim used to return an empty database for every Load(), so consumers
# fell back to "key as value". With real parsing wired up, the SDK call form
# Load("data/TGL/...") resolves to either game/data/TGL/... or
# sdk/Build/Data/TGL/... and the resulting database carries the parsed strings
# and per-key media filenames.

def test_load_populates_strings_from_sdk_tgl():
    """Load() finds an SDK-shipped TGL and decodes its values."""
    mgr = TGLocalizationManager()
    db = mgr.Load("data/TGL/Tutorial/Tutorial.tgl")
    assert db.GetString("Unused").startswith("This string is only here")


def test_load_populates_filenames_from_sdk_tgl():
    """The same TGL exposes the per-key media filename."""
    mgr = TGLocalizationManager()
    db = mgr.Load("data/TGL/Tutorial/Tutorial.tgl")
    assert db.GetFilename("Unused") == "Unused.wav"


def test_load_unknown_file_falls_back_to_empty_database():
    """When the TGL can't be resolved on disk, Load() returns an empty
    database — GetString falls back to returning the key so SDK menu lookups
    keep operating on real strings rather than stubs."""
    mgr = TGLocalizationManager()
    db = mgr.Load("data/TGL/__does_not_exist__.tgl")
    assert db.GetString("Foo") == "Foo"
    assert db.HasString("Foo") is False
    assert db.GetFilename("Foo") == ""


def test_load_caches_parsed_database_across_calls():
    """Re-Load() with the same filename returns the same instance (no
    re-parse), matching Appc's reference-counted database lifetime."""
    mgr = TGLocalizationManager()
    db1 = mgr.Load("data/TGL/Tutorial/Tutorial.tgl")
    db2 = mgr.Load("data/TGL/Tutorial/Tutorial.tgl")
    assert db1 is db2
