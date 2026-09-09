import os
from pathlib import Path

from engine import mods


def _touch(p: Path, body: str = "x") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


def _roots(tmp_path):
    game = tmp_path / "stock_game"
    sdk = tmp_path / "stock_sdk"
    game.mkdir(); sdk.mkdir()
    return game, sdk


def test_pure_addition_is_neither_override_nor_conflict(tmp_path):
    game, sdk = _roots(tmp_path)
    _touch(tmp_path / "mods" / "M" / "Data" / "new.nif")
    idx = mods.build_index(tmp_path / "mods")
    mods.classify(idx, game, sdk)
    assert idx.overrides == []
    assert idx.conflicts == []


def test_stock_override_is_detected(tmp_path):
    game, sdk = _roots(tmp_path)
    _touch(game / "data" / "shared.nif", "stock")
    _touch(tmp_path / "mods" / "M" / "Data" / "shared.nif", "modded")
    idx = mods.build_index(tmp_path / "mods")
    mods.classify(idx, game, sdk)
    assert idx.overrides == ["data/shared.nif"]


def test_sdk_override_is_detected(tmp_path):
    game, sdk = _roots(tmp_path)
    _touch(sdk / "loadspacehelper.py", "stock")
    _touch(tmp_path / "mods" / "M" / "Scripts" / "loadspacehelper.py", "modded")
    idx = mods.build_index(tmp_path / "mods")
    mods.classify(idx, game, sdk)
    assert idx.overrides == ["loadspacehelper.py"]


def test_mod_conflict_names_loser_and_winner(tmp_path):
    game, sdk = _roots(tmp_path)
    _touch(tmp_path / "mods" / "Alpha" / "Data" / "a.nif")
    _touch(tmp_path / "mods" / "Bravo" / "Data" / "a.nif")
    idx = mods.build_index(tmp_path / "mods")
    mods.classify(idx, game, sdk)
    assert idx.conflicts == [("data/a.nif", "Alpha", "Bravo")]


def test_describe_reports_counts_and_warns_on_conflict(tmp_path):
    game, sdk = _roots(tmp_path)
    _touch(tmp_path / "mods" / "Alpha" / "Data" / "a.nif")
    _touch(tmp_path / "mods" / "Bravo" / "Data" / "a.nif")
    _touch(tmp_path / "mods" / "Bravo" / ".DS_Store")
    idx = mods.build_index(tmp_path / "mods")
    mods.classify(idx, game, sdk)
    text = mods.describe(idx)
    assert "Alpha" in text and "Bravo" in text
    assert "conflict" in text.lower()


def test_describe_is_empty_with_no_mods(tmp_path):
    game, sdk = _roots(tmp_path)
    idx = mods.build_index(tmp_path / "absent")
    mods.classify(idx, game, sdk)
    assert mods.describe(idx) == ""


def test_describe_distinguishes_zero_placed_files(tmp_path):
    """A mod with a content root but zero placed files (all ignored) is legible."""
    game, sdk = _roots(tmp_path)
    _touch(tmp_path / "mods" / "Empty" / "Data" / ".DS_Store")
    _touch(tmp_path / "mods" / "Empty" / "readme.txt")
    idx = mods.build_index(tmp_path / "mods")
    mods.classify(idx, game, sdk)
    text = mods.describe(idx)
    # Should have "Empty" in the output and show the ignored count
    assert "Empty" in text
    # With 2 ignored files, the line should show that
    assert "2 ignored" in text


def test_describe_flags_read_failure_explicitly(tmp_path, monkeypatch):
    """A mod whose walk hit an unreadable directory must be flagged with
    explicit problem language.

    Driven through os.walk's onerror callback -- the real mechanism -- rather
    than by making the walk itself raise. Path.rglob() never raised here at
    all: it swallows a permission error and simply does not descend, which is
    exactly why this reported "0 files" and no problem for the commonest real
    failure."""
    game, sdk = _roots(tmp_path)
    _touch(tmp_path / "mods" / "Broken" / "Data" / "file.nif")
    _touch(tmp_path / "mods" / "Broken" / "Data" / "Sub" / "buried.nif")

    original_scandir = os.scandir

    def mock_scandir(path=".", *args, **kwargs):
        if "Broken" in str(path) and str(path).endswith("Sub"):
            raise PermissionError("Permission denied")
        return original_scandir(path, *args, **kwargs)

    monkeypatch.setattr(os, "scandir", mock_scandir)

    idx = mods.build_index(tmp_path / "mods")
    mods.classify(idx, game, sdk)
    text = mods.describe(idx)

    status = {m.name: m for m in idx.mods}["Broken"]
    assert status.read_error is True
    # The readable half of the mod is still indexed, and still counted.
    assert status.placed == 1
    assert idx.lookup("data/file.nif") is not None
    # Must contain the explicit problem language
    assert "Broken" in text
    assert "could not read mod contents" in text


def test_stock_override_is_detected_when_the_mod_matches_stock_case(tmp_path):
    """classify() stats the mod author's OWN spelling, not just the folded
    one. A stock BC install spells data/Icons/Ships/Galaxy.tga with capitals;
    statting only "data/icons/ships/galaxy.tga" finds nothing on a
    case-sensitive filesystem, so the commonest override of all -- a ship
    icon replacement -- was reported as a pure addition."""
    game, sdk = _roots(tmp_path)
    _touch(game / "data" / "Icons" / "Ships" / "Galaxy.tga", "stock")
    _touch(tmp_path / "mods" / "M" / "Data" / "Icons" / "Ships" / "Galaxy.tga", "modded")
    idx = mods.build_index(tmp_path / "mods")
    mf = idx.lookup("data/Icons/Ships/Galaxy.tga")
    # The un-folded spelling is kept alongside the folded index key.
    assert mf.rel == "data/icons/ships/galaxy.tga"
    assert mf.raw_rel == "Data/Icons/Ships/Galaxy.tga"
    mods.classify(idx, game, sdk)
    assert idx.overrides == ["data/icons/ships/galaxy.tga"]
    assert "1 stock file(s) overridden" in mods.describe(idx)


class _CaseSensitiveRoot:
    """A stand-in stock root whose exists() is case-SENSITIVE.

    APFS (and NTFS) are case-insensitive, so on this machine the folded and
    the raw spelling answer the same question and no real-filesystem test can
    tell them apart. Linux is the platform the fold exists for, and this is
    how a stock root behaves there.
    """

    def __init__(self, present):
        self._present = set(present)
        self._rel = ""

    def __truediv__(self, rel):
        child = _CaseSensitiveRoot(self._present)
        child._rel = f"{self._rel}/{rel}" if self._rel else str(rel)
        return child

    def exists(self):
        return self._rel in self._present


def test_stock_override_survives_a_case_sensitive_filesystem(tmp_path):
    """The un-folded-stat fix, proved without depending on the host FS."""
    _touch(tmp_path / "mods" / "M" / "Data" / "Icons" / "Ships" / "Galaxy.tga")
    idx = mods.build_index(tmp_path / "mods")
    # Stock ships the capitalised spelling and ONLY that one, as BC does.
    game = _CaseSensitiveRoot({"Data/Icons/Ships/Galaxy.tga"})
    mods.classify(idx, game, _CaseSensitiveRoot(set()))
    assert idx.overrides == ["data/icons/ships/galaxy.tga"]


def test_a_pure_addition_is_still_not_an_override_under_case_sensitivity(tmp_path):
    """The other direction: statting two spellings must not invent overrides."""
    _touch(tmp_path / "mods" / "M" / "Data" / "Icons" / "Ships" / "Fsteamr.tga")
    idx = mods.build_index(tmp_path / "mods")
    game = _CaseSensitiveRoot({"Data/Icons/Ships/Galaxy.tga"})
    mods.classify(idx, game, _CaseSensitiveRoot(set()))
    assert idx.overrides == []
