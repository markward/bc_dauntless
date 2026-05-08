from engine.appc.localization import (
    TGLocalizationManager, TGLocalizationDatabase, _TGString,
)


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
