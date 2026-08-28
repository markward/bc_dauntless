import pytest
from pathlib import Path
import App
from engine.appc.config_mapping import TGConfigMapping


@pytest.fixture
def fresh_config():
    return TGConfigMapping()


@pytest.fixture
def config_under_tmp(tmp_path, monkeypatch):
    """Anchor relative filenames to a tmp dir so SaveConfigFile/LoadConfigFile
    don't pollute the project root."""
    monkeypatch.chdir(tmp_path)
    yield tmp_path


# ── HasValue ──────────────────────────────────────────────────────────────────

def test_has_value_false_for_missing(fresh_config):
    assert fresh_config.HasValue("Sound", "StreamVoices") == 0


def test_has_value_true_after_set(fresh_config):
    fresh_config.SetIntValue("Sound", "StreamVoices", 1)
    assert fresh_config.HasValue("Sound", "StreamVoices") == 1


# ── Typed getters ────────────────────────────────────────────────────────────

def test_get_int_default_zero(fresh_config):
    assert fresh_config.GetIntValue("X", "y") == 0


def test_int_round_trip(fresh_config):
    fresh_config.SetIntValue("Sound", "StreamVoices", 1)
    assert fresh_config.GetIntValue("Sound", "StreamVoices") == 1


def test_int_coerces_from_loaded_string(fresh_config):
    """Values loaded from disk arrive as strings; GetIntValue must coerce."""
    fresh_config._sections["X"] = {"n": "42"}
    assert fresh_config.GetIntValue("X", "n") == 42


def test_float_round_trip(fresh_config):
    fresh_config.SetFloatValue("Audio", "Volume", 0.75)
    assert fresh_config.GetFloatValue("Audio", "Volume") == 0.75


def test_string_round_trip(fresh_config):
    fresh_config.SetStringValue("Multiplayer Options", "Player Name", "Picard")
    assert fresh_config.GetStringValue("Multiplayer Options", "Player Name") == "Picard"


def test_tg_string_round_trip(fresh_config):
    """SDK pattern: pName = App.g_kConfigMapping.GetTGStringValue(...)."""
    fresh_config.SetTGStringValue("Multiplayer Options", "Player Name", "Janeway")
    out = fresh_config.GetTGStringValue("Multiplayer Options", "Player Name")
    assert out == "Janeway"
    assert out.GetCString() == "Janeway"


def test_set_int_then_get_string(fresh_config):
    """Cross-type coercion: stored int reads back as str via GetStringValue."""
    fresh_config.SetIntValue("X", "n", 5)
    assert fresh_config.GetStringValue("X", "n") == "5"


# ── Section introspection ────────────────────────────────────────────────────

def test_has_section(fresh_config):
    assert fresh_config.HasSection("Sound") == 0
    fresh_config.SetIntValue("Sound", "X", 1)
    assert fresh_config.HasSection("Sound") == 1


def test_get_section_names(fresh_config):
    fresh_config.SetIntValue("A", "x", 1)
    fresh_config.SetStringValue("B", "y", "z")
    assert set(fresh_config.GetSectionNames()) == {"A", "B"}


def test_get_keys_in_section(fresh_config):
    fresh_config.SetIntValue("S", "k1", 1)
    fresh_config.SetStringValue("S", "k2", "v")
    assert set(fresh_config.GetKeysInSection("S")) == {"k1", "k2"}


# ── File I/O ─────────────────────────────────────────────────────────────────

def test_save_then_load_round_trip(config_under_tmp, fresh_config):
    fresh_config.SetIntValue("Sound", "StreamVoices", 1)
    fresh_config.SetStringValue("Multiplayer Options", "Player Name", "Picard")
    fresh_config.SetFloatValue("Audio", "Volume", 0.75)
    rc = fresh_config.SaveConfigFile("Options.cfg")
    assert rc == 1

    other = TGConfigMapping()
    rc = other.LoadConfigFile("Options.cfg")
    assert rc == 1
    assert other.GetIntValue("Sound", "StreamVoices") == 1
    assert other.GetStringValue("Multiplayer Options", "Player Name") == "Picard"
    assert other.GetFloatValue("Audio", "Volume") == 0.75


def test_save_writes_ini_format(config_under_tmp, fresh_config):
    fresh_config.SetIntValue("Sound", "StreamVoices", 1)
    fresh_config.SaveConfigFile("Options.cfg")
    raw = (config_under_tmp / "Options.cfg").read_text(encoding="utf-8")
    assert "[Sound]" in raw
    assert "StreamVoices=1" in raw


def test_load_unknown_file_returns_zero(config_under_tmp, fresh_config):
    assert fresh_config.LoadConfigFile("NoSuchFile.cfg") == 0


def test_load_skips_blank_lines_and_comments(config_under_tmp, fresh_config):
    (config_under_tmp / "with-comments.cfg").write_text(
        "# leading comment\n"
        "; semicolon comment\n"
        "\n"
        "[General]\n"
        "Volume=0.5\n"
        "# inline-section comment\n"
        "Mute=0\n"
    )
    assert fresh_config.LoadConfigFile("with-comments.cfg") == 1
    assert fresh_config.GetFloatValue("General", "Volume") == 0.5
    assert fresh_config.GetIntValue("General", "Mute") == 0


def test_load_merges_with_existing_in_memory_state(config_under_tmp, fresh_config):
    """SDK behaviour: layered .cfg files merge — Load shouldn't wipe."""
    fresh_config.SetIntValue("Existing", "n", 99)
    (config_under_tmp / "extra.cfg").write_text("[Loaded]\nk=42\n")
    fresh_config.LoadConfigFile("extra.cfg")
    assert fresh_config.GetIntValue("Existing", "n") == 99    # survived
    assert fresh_config.GetIntValue("Loaded", "k") == 42      # added


def test_save_handles_windows_path(config_under_tmp, fresh_config):
    fresh_config.SetIntValue("X", "y", 1)
    rc = fresh_config.SaveConfigFile("subdir\\nested.cfg")
    assert rc == 1
    assert (config_under_tmp / "subdir" / "nested.cfg").exists()


# ── App namespace ────────────────────────────────────────────────────────────

def test_app_exposes_g_k_config_mapping():
    assert isinstance(App.g_kConfigMapping, TGConfigMapping)


def test_app_round_trip_through_module_singleton(config_under_tmp):
    """SDK pattern: App.g_kConfigMapping.GetIntValue("Sound", "StreamVoices")."""
    App.g_kConfigMapping.SetIntValue("test_section", "test_key", 7)
    assert App.g_kConfigMapping.HasValue("test_section", "test_key") == 1
    assert App.g_kConfigMapping.GetIntValue("test_section", "test_key") == 7
