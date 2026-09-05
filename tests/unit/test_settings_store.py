"""SettingsStore — JSON persistence for Dauntless settings.

Section/key addressed and table-agnostic; the SETTINGS table lives in the
same module but these tests exercise only the file I/O half.

Spec: docs/superpowers/specs/2026-09-05-settings-persistence-design.md
"""
import json
import stat

import pytest

from engine.settings_store import SCHEMA_VERSION, SettingsStore


def _store(tmp_path):
    return SettingsStore(path=tmp_path / "settings.json")


def test_round_trip_through_a_fresh_store(tmp_path):
    s = _store(tmp_path)
    s.load()
    s.set("graphics", "camera_shake", False)

    reloaded = _store(tmp_path)
    reloaded.load()
    assert reloaded.get("graphics", "camera_shake") is False


def test_missing_file_loads_clean(tmp_path):
    s = _store(tmp_path)
    s.load()                          # file does not exist
    assert s.has("graphics", "smaa") is False
    assert s.get("graphics", "smaa") is None


def test_corrupt_file_is_quarantined_and_load_does_not_raise(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not json at all")
    s = SettingsStore(path=path)
    s.load()

    assert s.has("graphics", "smaa") is False
    assert (tmp_path / "settings.json.corrupt").exists()
    assert (tmp_path / "settings.json.corrupt").read_text() == "{not json at all"


def test_non_object_json_is_also_treated_as_corrupt(tmp_path):
    # Valid JSON, wrong shape — a bare list would explode on .get() later.
    path = tmp_path / "settings.json"
    path.write_text("[1, 2, 3]")
    s = SettingsStore(path=path)
    s.load()

    assert s.has("graphics", "smaa") is False
    assert (tmp_path / "settings.json.corrupt").exists()


def test_unknown_sections_and_keys_survive_a_save(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({
        "version": SCHEMA_VERSION,
        "graphics": {"smaa": True, "future_knob": 7},
        "paths": {"game_dir": "/somewhere"},
    }))
    s = SettingsStore(path=path)
    s.load()
    s.set("graphics", "smaa", False)

    on_disk = json.loads(path.read_text())
    assert on_disk["graphics"]["future_knob"] == 7
    assert on_disk["paths"] == {"game_dir": "/somewhere"}
    assert on_disk["graphics"]["smaa"] is False


def test_a_newer_schema_version_is_not_downgraded(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"version": SCHEMA_VERSION + 5,
                                "graphics": {"smaa": True}}))
    s = SettingsStore(path=path)
    s.load()
    assert s.get("graphics", "smaa") is True     # known keys still read
    s.set("graphics", "dust", False)

    assert json.loads(path.read_text())["version"] == SCHEMA_VERSION + 5


def test_reset_section_deletes_it(tmp_path):
    s = _store(tmp_path)
    s.load()
    s.set("graphics", "smaa", False)
    s.set("gameplay", "subtitles", False)

    s.reset_section("graphics")

    assert s.has("graphics", "smaa") is False
    assert s.has("gameplay", "subtitles") is True
    assert "graphics" not in json.loads((tmp_path / "settings.json").read_text())


def test_set_leaves_no_temp_file_behind(tmp_path):
    s = _store(tmp_path)
    s.load()
    s.set("graphics", "smaa", False)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["settings.json"]


def test_unwritable_location_does_not_raise(tmp_path):
    ro = tmp_path / "ro"
    ro.mkdir()
    s = SettingsStore(path=ro / "settings.json")
    s.load()
    ro.chmod(stat.S_IRUSR | stat.S_IXUSR)          # read + execute, no write
    try:
        s.set("graphics", "smaa", False)            # must not raise
        assert s.get("graphics", "smaa") is False   # in-memory value still holds
    finally:
        ro.chmod(stat.S_IRWXU)                      # restore so tmp_path cleans up


# ── The SETTINGS table ──────────────────────────────────────────────────────

from dataclasses import fields as dataclass_fields
from unittest.mock import Mock

from engine.settings_store import (
    SETTINGS, SettingsContext, apply_all, reset_and_apply_section,
    resolve_default, set_setting, setting_for, snapshot_for_panel,
)
from engine.ui.configuration_panel import (
    FOV_MAX, MASTER_TOGGLES, SettingsSnapshot,
)


def _ctx():
    """Context of Mocks. director.fov_y_rad is a real float so the fov
    default (degrees(fov_y_rad)) resolves to a number, not a Mock."""
    import math
    ctx = SettingsContext(r=Mock(), director=Mock(), crew_speech=Mock(),
                          light_emitters=Mock(), camera_shake=Mock(), App=Mock())
    ctx.director.fov_y_rad = math.radians(45)
    ctx.camera_shake.enabled.return_value = True
    return ctx


def _calls(mock):
    """Names of the methods called on a Mock, e.g. {'set_smaa_enabled'}."""
    return {name for name, _args, _kwargs in mock.mock_calls}


# The applier each MASTER_TOGGLES member name is expected to reach:
# (SettingsContext attribute, method name).
_MEMBER_CALL = {
    "procedural_sky":      ("r", "set_procedural_sky_enabled"),
    "volumetric_nebulae":  ("r", "set_volumetric_nebulae_enabled"),
    "hdr":                 ("r", "set_hdr_enabled"),
    "filmic":              ("r", "set_filmic_enabled"),
    "motion_blur":         ("r", "set_motion_blur_enabled"),
    "hdr_lens_flare":      ("r", "set_hdr_lens_flare_enabled"),
    "rim":                 ("r", "set_rim_enabled"),
    "shadows":             ("r", "set_shadows_enabled"),
    "nebula_lightning":    ("r", "set_nebula_lightning_enabled"),
    "ship_light_emitters": ("light_emitters", "set_enabled"),
}


def test_missing_file_calls_zero_appliers(tmp_path):
    """THE guarantee: no settings.json means boot is byte-identical to today.
    An absent key must never reach its applier — the table's default exists
    only to populate the panel's display snapshot."""
    s = _store(tmp_path)
    s.load()
    ctx = _ctx()

    apply_all(s, ctx)

    for attr in ("r", "director", "crew_speech", "light_emitters",
                 "camera_shake", "App"):
        assert getattr(ctx, attr).mock_calls == [], \
            "%s was touched with no stored settings" % attr


def test_stored_keys_reach_their_appliers(tmp_path):
    s = _store(tmp_path)
    s.load()
    s.set("graphics", "smaa", False)
    s.set("gameplay", "ai_difficulty", 2)
    ctx = _ctx()

    apply_all(s, ctx)

    ctx.r.set_smaa_enabled.assert_called_once_with(False)
    ctx.App.Game_SetDifficulty.assert_called_once_with(2)
    ctx.crew_speech.set_subtitles_enabled.assert_not_called()   # not stored


def test_fov_applies_in_radians(tmp_path):
    import math
    s = _store(tmp_path)
    s.load()
    s.set("graphics", "fov_deg", 30)
    ctx = _ctx()

    apply_all(s, ctx)

    (called_rad,), _kwargs = ctx.director.set_fov.call_args
    assert called_rad == pytest.approx(math.radians(30))


def test_out_of_range_int_is_clamped(tmp_path):
    s = _store(tmp_path)
    s.load()
    s.set("graphics", "fov_deg", 999)
    ctx = _ctx()

    apply_all(s, ctx)

    (called_rad,), _kwargs = ctx.director.set_fov.call_args
    import math
    assert called_rad == pytest.approx(math.radians(FOV_MAX))


def test_uncoercible_value_is_treated_as_absent(tmp_path):
    s = _store(tmp_path)
    s.load()
    s.set("gameplay", "ai_difficulty", "banana")
    ctx = _ctx()

    apply_all(s, ctx)

    ctx.App.Game_SetDifficulty.assert_not_called()


def test_every_snapshot_field_has_exactly_one_setting_row():
    """Adding a toggle to SettingsSnapshot without a SETTINGS row ships a
    control that silently forgets. Same bug class the JS focusables test
    guards on the other side."""
    snapshot_fields = {f.name for f in dataclass_fields(SettingsSnapshot)}
    table_fields = [s.field for s in SETTINGS]
    assert sorted(table_fields) == sorted(snapshot_fields)
    assert len(table_fields) == len(set(table_fields))


def test_every_setting_key_is_unique_and_in_a_known_section():
    keys = [s.key for s in SETTINGS]
    assert len(keys) == len(set(keys))
    assert {s.section for s in SETTINGS} == {"graphics", "gameplay"}


def test_master_fan_out_matches_the_panel_master_table():
    """MASTER_TOGGLES is the panel's own grouping. If the store's fan-out
    drifts from it, a master row toggles a different set of effects than the
    one the player sees described."""
    for key, _label, members in MASTER_TOGGLES:
        ctx = _ctx()
        setting_for(key).apply(ctx, True)
        expected = {}
        for m in members:
            attr, method = _MEMBER_CALL[m]
            expected.setdefault(attr, set()).add(method)
        for attr in ("r", "light_emitters"):
            assert _calls(getattr(ctx, attr)) == expected.get(attr, set()), \
                "master %r fan-out drifted on ctx.%s" % (key, attr)


def test_snapshot_uses_stored_value_where_present_and_default_where_absent(tmp_path):
    s = _store(tmp_path)
    s.load()
    s.set("graphics", "smaa", False)
    ctx = _ctx()
    ctx.camera_shake.enabled.return_value = False   # live getter default

    snap = snapshot_for_panel(s, ctx)

    assert snap.smaa_on is False        # stored
    assert snap.dust_on is True         # static default
    assert snap.camera_shake_on is False  # callable default, read live
    assert snap.fov_deg == 45           # callable default from director


def test_snapshot_does_not_call_any_applier(tmp_path):
    """Building the panel's display state must not mutate the engine."""
    s = _store(tmp_path)
    s.load()
    s.set("graphics", "smaa", False)
    ctx = _ctx()

    snapshot_for_panel(s, ctx)

    assert ctx.r.mock_calls == []
    assert ctx.director.set_fov.called is False


def test_set_setting_writes_to_the_right_section(tmp_path):
    s = _store(tmp_path)
    s.load()
    set_setting(s, "subtitles", False)
    assert s.get("gameplay", "subtitles") is False


def test_reset_and_apply_section_deletes_reapplies_and_returns_fields(tmp_path):
    s = _store(tmp_path)
    s.load()
    s.set("graphics", "smaa", False)
    s.set("gameplay", "subtitles", False)
    ctx = _ctx()

    out = reset_and_apply_section(s, ctx, "graphics")

    assert s.has("graphics", "smaa") is False         # section gone
    assert s.has("gameplay", "subtitles") is True     # other section untouched
    assert out["smaa_on"] is True                     # field-keyed, default value
    assert "subtitles_on" not in out
    ctx.r.set_smaa_enabled.assert_called_once_with(True)   # engine re-applied


def test_resolve_default_handles_values_and_callables():
    ctx = _ctx()
    assert resolve_default(setting_for("dust"), ctx) is True
    assert resolve_default(setting_for("fov_deg"), ctx) == 45
