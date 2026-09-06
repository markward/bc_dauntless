"""Boot's path branch: prompt when unresolved, and degrade safely.

The fallback guard here is the most important test in the feature. If a
picker-less platform ever boots on unresolved paths, or loses the
describe_failure() diagnostic, nothing else in the suite would notice.
"""

import pytest

from engine import first_run, host_loop, paths


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
