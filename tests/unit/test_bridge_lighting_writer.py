"""Bridge lighting writer (spec 2026-10-08-bridge-emitters §7): deterministic,
atomic, round-trip byte-identical."""
import json

import pytest

from engine.bridge_editor import lighting_doc as ld
from engine.bridge_editor import lighting_writer as lw


def doc():
    d = ld.empty_doc("data/Models/Sets/DBridge/DBridge.nif")
    ld.shape_entry(d, 12, "roof light")["material"] = {"roughness": 0.123456789, "metalness": 1}
    ld.shape_entry(d, 3, "floor")["material"] = {"roughness": 0.5}
    return d


def test_dumps_is_sorted_rounded_and_newline_terminated():
    text = lw.dumps(doc())
    assert text.endswith("\n")
    assert "0.123457" in text and "0.123456789" not in text
    assert text.index('"12:roof light"') < text.index('"3:floor"')   # sorted keys
    assert text.splitlines()[1].startswith("  ")                    # 2-space indent


def test_round_trip_is_byte_identical(tmp_path):
    p = tmp_path / "x.json"
    lw.save(doc(), p)
    first = p.read_text()
    lw.save(ld.validate(json.loads(first)), p)
    assert p.read_text() == first


def test_save_is_atomic_and_leaves_no_tmp(tmp_path):
    p = tmp_path / "sub" / "x.json"
    lw.save(doc(), p)
    assert p.is_file()
    assert [f.name for f in p.parent.iterdir()] == ["x.json"]


def test_save_refuses_an_invalid_doc_without_touching_the_file(tmp_path):
    p = tmp_path / "x.json"
    p.write_text("original")
    bad = doc()
    bad["shapes"]["3:floor"]["material"]["roughness"] = 7
    with pytest.raises(ld.BridgeLightingError):
        lw.save(bad, p)
    assert p.read_text() == "original"


def test_target_path_keeps_where_it_was_found(tmp_path, monkeypatch):
    found = tmp_path / "mod" / "abc.json"
    assert lw.target_path(found, "abc") == found
    monkeypatch.setattr(ld.paths, "project_asset_root", lambda: tmp_path)
    assert lw.target_path(None, "abc") == tmp_path / "bridge_lighting" / "abc.json"
