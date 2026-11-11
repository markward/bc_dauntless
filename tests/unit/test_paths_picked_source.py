"""The picked source outranks everything, including a flag it corrects.

Spec 1's rule is that the highest source which is SET wins even when
invalid -- falling through would boot a different install than the one
that was asked for. That makes the obvious cheap design WRONG: writing a
pick into settings.json and re-running resolve() would leave an invalid
--game-dir still winning over the folder the player just chose. A pick is
the most recent explicit human act, so it outranks the flag.
"""

import pytest

from engine import paths


class FakeStore:
    def __init__(self, values=None):
        self._values = dict(values or {})

    def has(self, section, key):
        return (section, key) in self._values

    def get(self, section, key):
        return self._values[(section, key)]

    def set(self, section, key, value):
        self._values[(section, key)] = value


@pytest.fixture
def install(tmp_path):
    """A valid game root (the one content root), outside the project."""
    game = tmp_path / "install" / "game"          # paths-guard: test fixture tree
    for rel in ("data", "data/Models", "data/Textures", "data/Icons", "scripts"):
        (game / rel).mkdir(parents=True, exist_ok=True)
    (game / "scripts" / "MissionLib.pyc").write_bytes(b"")
    return game


def test_picked_outranks_an_invalid_cli_flag(install, tmp_path):
    game = install
    bogus = tmp_path / "not-an-install"
    bogus.mkdir()
    r = paths.resolve(
        argv=["--game-dir", str(bogus)],
        env={},
        store=FakeStore(),
        picked={"game": str(game)},
    )
    assert r.ok
    assert r.game == game
    assert r.source("game") == "picker"


def test_picked_outranks_env_and_settings(install):
    game = install
    r = paths.resolve(
        argv=[],
        env={"DAUNTLESS_GAME_DIR": "/nope"},
        store=FakeStore({("paths", "game"): "/also-nope"}),
        picked={"game": str(game)},
    )
    assert r.source("game") == "picker"
    assert r.ok


def test_a_picked_sdk_entry_is_ignored(install):
    """The picker has one row; a stray "sdk" key names no root."""
    game = install
    r = paths.resolve(argv=[], env={}, store=FakeStore(),
                      picked={"game": str(game), "sdk": "/nope"})  # paths-guard: kind label
    assert r.ok and r.source("game") == "picker"


def test_picked_none_behaves_exactly_as_before(install):
    game = install
    argv = ["--game-dir", str(game)]
    without = paths.resolve(argv=argv, env={}, store=FakeStore())
    with_none = paths.resolve(argv=argv, env={}, store=FakeStore(), picked=None)
    assert without == with_none


def test_an_invalid_pick_is_reported_not_skipped(tmp_path):
    bogus = tmp_path / "empty"
    bogus.mkdir()
    r = paths.resolve(argv=[], env={}, store=FakeStore(),
                      picked={"game": str(bogus)})
    assert not r.ok
    assert r.game is None
    assert r.source("game") == "picker"
    assert r.validation("game").missing


def test_persist_writes_a_picked_root(install):
    game = install
    store = FakeStore()
    r = paths.resolve(argv=[], env={}, store=FakeStore(),
                      picked={"game": str(game)})
    paths.persist(r, store=store)
    assert store.get("paths", "game") == str(game)
    assert not store.has("paths", "sdk")


def test_persist_still_refuses_env_and_settings(install):
    game = install
    store = FakeStore()
    r = paths.resolve(argv=[], env={"DAUNTLESS_GAME_DIR": str(game)},
                      store=FakeStore())
    assert r.ok and r.source("game") == "env"
    paths.persist(r, store=store)
    assert not store.has("paths", "game")
