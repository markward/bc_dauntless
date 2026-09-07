"""Boot's path branch: prompt when unresolved, and degrade safely.

The fallback guard here is the most important test in the feature. If a
picker-less platform ever boots on unresolved paths, or loses the
describe_failure() diagnostic, nothing else in the suite would notice.
"""

import pytest

from engine import first_run, host_loop, paths

# Captured before any fixture gets a chance to monkeypatch paths.persist,
# so test_a_validated_pick_persists_even_when_a_later_pick_is_cancelled can
# reinstate the REAL implementation (pointed at a FakeStore) instead of the
# no-op _nothing_resolves_by_accident installs for every other test here.
_REAL_PERSIST = paths.persist


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
    game = tmp_path / "install" / "game"          # paths-guard: test fixture tree
    for marker in paths.GAME_MARKERS:
        (game / marker).mkdir(parents=True, exist_ok=True)
    sdk = tmp_path / "install" / "sdk"            # paths-guard: test fixture tree
    (sdk / "Build" / "scripts").mkdir(parents=True, exist_ok=True)
    (sdk / "Build" / "scripts" / "App.py").write_text("")
    (sdk / "Build" / "Data" / "TGL").mkdir(parents=True, exist_ok=True)
    return game, sdk


@pytest.fixture(autouse=True)
def _nothing_resolves_by_accident(monkeypatch):
    """Force every ambient source empty, and never touch the real settings.

    Without this the developer's own settings.json would resolve the roots
    and neither test would exercise the branch it names.
    """
    fake_store = FakeStore()
    real_resolve = paths.resolve

    # The keyword names must match what first_run.prompt_for_missing
    # actually passes -- it calls paths.resolve(argv=, env=, store=,
    # picked=), so a replacement that renames `store` raises TypeError
    # rather than running the branch under test.
    def resolve(argv=None, env=None, store=None, picked=None):
        return real_resolve(argv=[], env={}, store=fake_store, picked=picked)

    monkeypatch.setattr(paths, "resolve", resolve)
    monkeypatch.setattr(paths, "persist", lambda resolution, store=None: None)
    monkeypatch.setattr(paths, "configure", lambda resolution: None)
    return fake_store


def test_unresolved_paths_prompt_and_then_boot(monkeypatch, install):
    game, sdk = install
    answers = [str(game), str(sdk)]
    monkeypatch.setattr(first_run, "_default_picker",
                        lambda title, message: answers.pop(0))

    result = host_loop._resolve_paths_or_report()

    assert result is not None and result.ok
    assert result.source("game") == "picker"
    assert answers == []


def test_no_picker_prints_the_diagnostic_and_stops_boot(monkeypatch, capsys):
    """The fallback guard: Windows, Linux, a stale .so, or a plain cancel."""
    monkeypatch.setattr(first_run, "_default_picker",
                        lambda title, message: None)

    result = host_loop._resolve_paths_or_report()

    assert result is None, "boot must not continue on unresolved paths"
    printed = capsys.readouterr().err
    assert "cannot locate your Bridge Commander install" in printed
    assert "--game-dir" in printed


def test_a_validated_pick_persists_even_when_a_later_pick_is_cancelled(
        monkeypatch, install, _nothing_resolves_by_accident):
    """FINDING 1 regression test: a validated pick must reach the STORE,
    not just the in-memory Resolution, even when boot still fails overall.

    _resolve_paths_or_report() used to call persist() only after the
    `if not resolution.ok: return None` branch, so a player who located
    their BC game folder by hand but cancelled the sdk picker got nothing
    written -- next launch asked for BOTH roots again. persist() must run
    on this partial-resolution path too.
    """
    game, _sdk = install
    fake_store = _nothing_resolves_by_accident

    # _nothing_resolves_by_accident stubs persist() to a no-op so the OTHER
    # tests in this file never touch a store. Reinstate the real
    # implementation for this one test, still pointed at the same
    # fake_store paths.resolve() already uses, so the assertion below
    # watches actual writes rather than an in-memory Resolution field.
    monkeypatch.setattr(
        paths, "persist",
        lambda resolution, store=None: _REAL_PERSIST(resolution, store=fake_store))

    # Answer the game picker, then cancel the sdk one.
    monkeypatch.setattr(
        first_run, "_default_picker",
        lambda title, message: (
            str(game) if title == first_run._TITLES["game"] else None))

    result = host_loop._resolve_paths_or_report()

    assert result is None, "sdk is still missing, so boot must still stop"
    assert fake_store.has("paths", "game"), (
        "the validated game root was never persisted -- the player will be "
        "asked for it again next launch")
    assert fake_store.get("paths", "game") == str(game)
    assert not fake_store.has("paths", "sdk"), (
        "the cancelled sdk pick must not be written")


def test_cef_comes_up_before_the_sdk_finder_is_installed():
    """The screen must exist before the roots are known, so CEF init has to
    precede _setup_sdk(). Verified on run()'s source rather than by booting
    a window, the same technique the neighbouring boot-order guards use.

    Anchored on the real spellings, not substrings that match something else
    one character in -- a guard in this family has already broken that way.
    """
    import inspect
    from engine import host_loop
    source = inspect.getsource(host_loop.run)
    init_at = source.index("r.init(")
    cef_at = source.index("r.cef_initialize(")
    resolve_at = source.index("_resolve_paths_or_report()")
    sdk_at = source.index("_setup_sdk()")
    assert init_at < cef_at < resolve_at < sdk_at, (
        "boot order must be: window, CEF, resolve, SDK -- the first-run "
        "screen needs a live browser before the roots are known, and the "
        "SDK meta-path finder needs the roots before it is installed"
    )
