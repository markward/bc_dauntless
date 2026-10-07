"""engine.appc.dialogue_patches: the runtime patch table
(spec docs/superpowers/specs/2026-10-07-dialogue-patches-design.md)."""
import json

import pytest

from engine.appc import dialogue_patches as dp

E1M2 = "data/TGL/Maelstrom/Episode 1/E1M2.TGL"


@pytest.fixture
def patches(monkeypatch, tmp_path):
    """Point the module at a temp patches.json; returns a writer."""
    path = tmp_path / "patches.json"
    monkeypatch.setattr(dp, "patches_path", lambda: path)
    dp.reset_cache()

    def write(data):
        path.write_text(json.dumps(data) if not isinstance(data, str) else data)
        dp.reset_cache()
    yield write
    dp.reset_cache()


def test_patches_path_is_under_the_project_assets():
    from engine import paths
    assert dp.patches_path() == paths.project_asset_root() / "dialogue" / "patches.json"


def test_inserts_are_looked_up_by_tgl_and_key(patches):
    patches({E1M2: {"insert_after": {"A": [{"speaker": "MiscEng/Soams", "key": "B"}]}}})
    assert dp.inserts_for(E1M2, "A") == [{"speaker": "MiscEng/Soams", "key": "B"}]
    assert dp.inserts_for(E1M2, "Other") == []
    assert dp.inserts_for("data/TGL/Elsewhere.tgl", "A") == []


def test_tgl_spelling_differences_still_match(patches):
    patches({E1M2: {"insert_after": {"A": [{"speaker": "bridge/XO", "key": "B"}]}}})
    for spelling in ("data/TGL/Maelstrom/Episode 1/E1M2.tgl",
                     "data\\TGL\\Maelstrom\\Episode 1\\E1M2.TGL",
                     "DATA/tgl/maelstrom/episode 1/e1m2.tgl"):
        assert dp.inserts_for(spelling, "A"), spelling


def test_replacements_are_looked_up_by_tgl(patches):
    patches({E1M2: {"replace": {"K": {"text": "New."}}}})
    assert dp.replacements_for("data/TGL/Maelstrom/Episode 1/E1M2.tgl") == {"K": {"text": "New."}}
    assert dp.replacements_for("data/TGL/Elsewhere.tgl") == {}


def test_a_missing_file_means_no_patches(patches):
    assert dp.table() == {}
    assert dp.inserts_for(E1M2, "A") == []


@pytest.mark.parametrize("bad", [
    "{not json",
    "[]",
    {E1M2: {"insert_after": {"A": [{"speaker": "Soams", "key": "B"}]}}},
    {E1M2: {"insert_after": {"A": []}}},
    {E1M2: {"insert_after": {"A": [{"speaker": "bridge/XO"}]}}},
    {E1M2: {"replace": {"K": {}}}},
    {E1M2: {"replace": {"K": {"voice": "x.wav"}}}},
    {E1M2: {"surprise": {}}},
])
def test_a_malformed_file_means_no_patches_and_never_raises(patches, bad):
    patches(bad)
    assert dp.table() == {}
    assert dp.inserts_for(E1M2, "A") == []


def test_validate_shape_names_each_problem():
    errors = dp.validate_shape({E1M2: {"insert_after": {"A": [{"speaker": "Soams", "key": "B"}]},
                                       "replace": {"K": {"voice": "x"}}}})
    assert len(errors) == 2
    assert any("Soams" in e for e in errors)
    assert any("K" in e for e in errors)


def test_validate_shape_accepts_a_good_table():
    assert dp.validate_shape({E1M2: {
        "insert_after": {"A": [{"speaker": "bridge/XO", "key": "B", "tgl": "data/TGL/Dauntless Crew.tgl"}]},
        "replace": {"K": {"text": "t", "sound": "sfx/x.wav"}}}}) == []


def test_an_edited_file_is_picked_up_without_a_restart(patches):
    patches({E1M2: {"replace": {"K": {"text": "one"}}}})
    assert dp.replacements_for(E1M2)["K"]["text"] == "one"
    import os, time
    p = dp.patches_path()
    p.write_text(json.dumps({E1M2: {"replace": {"K": {"text": "two"}}}}))
    st = p.stat()
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
    assert dp.replacements_for(E1M2)["K"]["text"] == "two"


def test_the_shipped_file_is_well_formed():
    raw = json.loads(dp.patches_path().read_text(encoding="utf-8"))
    assert dp.validate_shape(raw) == []


# ── Insert cycles: A->[A] / A->[B],B->[A] loop Completed() forever ──────────

def test_a_self_cycle_is_rejected():
    errors = dp.validate_shape(
        {E1M2: {"insert_after": {"A": [{"speaker": "bridge/XO", "key": "A"}]}}})
    assert any("cycle" in e.lower() for e in errors)


def test_a_two_step_cycle_is_rejected():
    errors = dp.validate_shape({E1M2: {"insert_after": {
        "A": [{"speaker": "bridge/XO", "key": "B"}],
        "B": [{"speaker": "bridge/XO", "key": "A"}],
    }}})
    assert any("cycle" in e.lower() for e in errors)


def test_a_cycle_crossing_tgls_via_the_tgl_field_is_rejected():
    OTHER = "data/TGL/Dauntless Crew.tgl"
    errors = dp.validate_shape({
        E1M2: {"insert_after": {"A": [{"speaker": "bridge/XO", "key": "X", "tgl": OTHER}]}},
        OTHER: {"insert_after": {"X": [{"speaker": "bridge/XO", "key": "A", "tgl": E1M2}]}},
    })
    assert any("cycle" in e.lower() for e in errors)


def test_a_non_cyclic_chain_is_accepted():
    assert dp.validate_shape({E1M2: {"insert_after": {
        "A": [{"speaker": "bridge/XO", "key": "B"}],
        "B": [{"speaker": "bridge/XO", "key": "C"}],
    }}}) == []


def test_a_cyclic_table_is_rejected_by_table(patches):
    patches({E1M2: {"insert_after": {"A": [{"speaker": "bridge/XO", "key": "A"}]}}})
    assert dp.table() == {}
    assert dp.inserts_for(E1M2, "A") == []
