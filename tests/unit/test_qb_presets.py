import json

from engine.quickbattle import presets, scenario as sc


def _store(tmp_path):
    return presets.load_presets(tmp_path / "quickbattle_presets.json")


def test_absent_file_has_no_presets(tmp_path):
    p = _store(tmp_path)
    assert p.names() == [] and not p.exists("x") and p.load("x") is None


def test_save_load_round_trip_and_sorted_names(tmp_path):
    p = _store(tmp_path)
    s = sc.default_scenario()
    s.add_ship(s.groups[1].id, "Warbird")
    assert p.save("  zeta ", s)
    assert p.save("Alpha", sc.default_scenario())
    assert p.names() == ["Alpha", "zeta"]
    again = _store(tmp_path)                      # re-read from disk
    assert sc.same_setup(again.load("zeta"), s)
    raw = json.loads((tmp_path / "quickbattle_presets.json").read_text())
    assert raw["presets"]["zeta"]["saved_at"]


def test_empty_name_refused_overwrite_and_delete(tmp_path):
    p = _store(tmp_path)
    assert not p.save("   ", sc.default_scenario())
    p.save("A", sc.default_scenario())
    s2 = sc.default_scenario()
    s2.add_ship(s2.groups[1].id, "Akira")
    p.save("A", s2)
    assert sc.same_setup(p.load("A"), s2)
    assert p.delete("A") and not p.exists("A") and not p.delete("A")


def test_corrupt_file_quarantined_and_broken_preset_skipped(tmp_path):
    f = tmp_path / "quickbattle_presets.json"
    f.write_text("{not json")
    p = presets.load_presets(f)
    assert p.names() == []
    f.write_text(json.dumps({"version": 1, "presets": {
        "bad": {"saved_at": "x", "scenario": {"groups": []}}}}))
    p = presets.load_presets(f)
    assert p.load("bad") is None


def test_default_path_is_beside_settings_and_resolved_at_use(monkeypatch, tmp_path):
    from engine import settings_store
    monkeypatch.setattr(settings_store, "default_settings_path",
                        lambda: tmp_path / "settings.json")
    assert presets.default_presets_path() == tmp_path / "quickbattle_presets.json"
