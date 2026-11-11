"""engine.paths.stock_scripts: the install's own scripts folder."""
import pytest

from engine import paths


def _configure(root):
    paths.configure(paths.Resolution(
        game=root, game_source="env", game_validation=None))


@pytest.fixture(autouse=True)
def _clear():
    yield
    paths.configure(None)


def test_stock_scripts_is_the_game_roots_scripts_folder(tmp_path):
    (tmp_path / "scripts").mkdir()
    _configure(tmp_path)
    assert paths.stock_scripts() == tmp_path / "scripts"


def test_stock_scripts_matches_case_insensitively(tmp_path):
    (tmp_path / "Scripts").mkdir()
    _configure(tmp_path)
    got = paths.stock_scripts()
    # A case-insensitive volume (macOS default) answers the asked spelling;
    # a case-sensitive one (Linux) must answer the on-disk spelling.
    assert got.is_dir() and got.name.lower() == "scripts"
    assert (tmp_path / "scripts").exists() == (got.name == "scripts")


def test_stock_scripts_resolves_at_use(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    (a / "scripts").mkdir(parents=True)
    (b / "scripts").mkdir(parents=True)
    _configure(a)
    assert paths.stock_scripts() == a / "scripts"
    _configure(b)
    assert paths.stock_scripts() == b / "scripts"
