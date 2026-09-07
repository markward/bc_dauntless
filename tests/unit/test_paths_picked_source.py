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
    """A valid game root and a valid sdk root, both outside the project."""
    game = tmp_path / "install" / "game"          # paths-guard: test fixture tree
    for marker in paths.GAME_MARKERS:
        (game / marker).mkdir(parents=True, exist_ok=True)
    sdk = tmp_path / "install" / "sdk"            # paths-guard: test fixture tree
    (sdk / "Build" / "scripts").mkdir(parents=True, exist_ok=True)
    (sdk / "Build" / "scripts" / "App.py").write_text("")
    (sdk / "Build" / "Data" / "TGL").mkdir(parents=True, exist_ok=True)
    return game, sdk


def test_picked_outranks_an_invalid_cli_flag(install, tmp_path):
    game, sdk = install
    bogus = tmp_path / "not-an-install"
    bogus.mkdir()
    r = paths.resolve(
        argv=["--game-dir", str(bogus), "--sdk-dir", str(bogus)],
        env={},
        store=FakeStore(),
        picked={"game": str(game), "sdk": str(sdk)},
    )
    assert r.ok
    assert r.game == game
    assert r.source("game") == "picker"


def test_picked_outranks_env_and_settings(install):
    game, sdk = install
    r = paths.resolve(
        argv=[],
        env={"DAUNTLESS_GAME_DIR": "/nope", "DAUNTLESS_SDK_DIR": "/nope"},
        store=FakeStore({("paths", "game"): "/also-nope",
                         ("paths", "sdk"): "/also-nope"}),
        picked={"game": str(game), "sdk": str(sdk)},
    )
    assert r.source("game") == "picker"
    assert r.source("sdk") == "picker"


def test_picked_may_cover_only_one_root(install):
    game, sdk = install
    r = paths.resolve(
        argv=["--sdk-dir", str(sdk)],
        env={},
        store=FakeStore(),
        picked={"game": str(game)},
    )
    assert r.source("game") == "picker"
    assert r.source("sdk") == "cli"
    assert r.ok


def test_picked_none_behaves_exactly_as_before(install):
    game, sdk = install
    argv = ["--game-dir", str(game), "--sdk-dir", str(sdk)]
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
    game, sdk = install
    store = FakeStore()
    r = paths.resolve(argv=[], env={}, store=FakeStore(),
                      picked={"game": str(game), "sdk": str(sdk)})
    paths.persist(r, store=store)
    assert store.get("paths", "game") == str(game)
    assert store.get("paths", "sdk") == str(sdk)


def test_persist_still_refuses_env_and_settings(install):
    game, sdk = install
    store = FakeStore()
    r = paths.resolve(argv=[], env={"DAUNTLESS_GAME_DIR": str(game),
                                    "DAUNTLESS_SDK_DIR": str(sdk)},
                      store=FakeStore())
    assert r.ok and r.source("game") == "env"
    paths.persist(r, store=store)
    assert not store.has("paths", "game")
