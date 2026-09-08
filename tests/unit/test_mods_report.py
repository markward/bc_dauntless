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
    """A mod whose rglob walk failed must be flagged with explicit problem language."""
    game, sdk = _roots(tmp_path)
    _touch(tmp_path / "mods" / "Broken" / "Data" / "file.nif")

    # Monkeypatch Path.rglob to raise OSError for the Broken mod's content root.
    original_rglob = Path.rglob
    def mock_rglob(self, pattern):
        if "Broken" in str(self):
            raise OSError("Permission denied")
        return original_rglob(self, pattern)

    monkeypatch.setattr(Path, "rglob", mock_rglob)

    idx = mods.build_index(tmp_path / "mods")
    mods.classify(idx, game, sdk)
    text = mods.describe(idx)

    # Must contain the explicit problem language
    assert "Broken" in text
    assert "could not read mod contents" in text
