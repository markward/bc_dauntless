"""Hand-authored star-system descriptions for the Set Course map.

descriptions.json is the one file in engine/systems/ that a human writes and
no tool regenerates — the maps beside it are the opposite. These tests guard
the two things that would make it quietly useless: drifting out of step with
the systems the star map can actually select, and a half-written entry
rendering with a blank half.
"""
import json

from engine.appc import sector_model as sm
from engine.systems import descriptions as sysdesc


def _ids() -> set:
    return {s["id"] for s in sm.load_sector_model()["systems"]}


def test_every_charted_system_has_a_description():
    """A system the player can select and get nothing for is a hole in the
    nav UI, and the only way to notice is a test."""
    missing = sorted(_ids() - set(sysdesc.available()))
    assert missing == [], f"systems with no description: {missing}"


def test_no_description_names_a_system_that_does_not_exist():
    """An entry for an id the star map never selects is dead text nobody
    will ever see, and reads as coverage when it is not."""
    extra = sorted(set(sysdesc.available()) - _ids())
    assert extra == [], f"descriptions for unknown systems: {extra}"


def test_lookup_is_case_insensitive_and_safe_on_junk():
    assert sysdesc.for_system("VESUVI") == sysdesc.for_system("vesuvi")
    assert sysdesc.for_system("no-such-system") is None
    assert sysdesc.for_system("") is None
    assert sysdesc.for_system(None) is None


def test_a_half_written_entry_is_refused_rather_than_half_rendered():
    """Better no description than a heading with nothing under it."""
    raw = json.loads(sysdesc.descriptions_path().read_text(encoding="utf-8"))
    for key, entry in raw.items():
        if key.startswith("_"):
            continue
        assert entry.get("summary"), f"{key} has no summary"
        assert entry.get("detail"), f"{key} has no detail"


def test_the_fiction_we_established_is_actually_in_the_text():
    """These three systems carry the plot -- BC's own, not invented. If a
    rewrite drops it, the nav UI stops being where the story lives."""
    vesuvi = sysdesc.for_system("vesuvi")["detail"].lower()
    assert "vesuvi iv" in vesuvi or "survey station" in vesuvi
    assert "debris" in vesuvi or "dust" in vesuvi

    belaruz = sysdesc.for_system("belaruz")["detail"].lower()
    assert "dust" in belaruz or "nebula" in belaruz
    assert "not a casualty" in belaruz or "moving through" in belaruz

    omega = sysdesc.for_system("omegadraconis")["detail"].lower()
    assert "solarformer" in omega
    assert "kessok" in omega


def test_summaries_stay_short_enough_for_a_one_line_readout():
    for sid in sysdesc.available():
        summary = sysdesc.for_system(sid)["summary"]
        assert len(summary) <= 90, f"{sid} summary is {len(summary)} chars"


def test_a_missing_file_degrades_to_no_descriptions_rather_than_raising(
        tmp_path, monkeypatch):
    """The nav map must still open if this file is absent or malformed."""
    sysdesc._load.cache_clear()
    monkeypatch.setattr(sysdesc, "descriptions_path",
                        lambda: tmp_path / "gone.json")
    try:
        assert sysdesc.available() == []
        assert sysdesc.for_system("vesuvi") is None
    finally:
        sysdesc._load.cache_clear()
