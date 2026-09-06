"""The picker flow, driven by a fake picker -- no dialog is ever shown.

Every decision lives here rather than in the .mm file precisely so it can
be tested: a modal NSOpenPanel cannot be exercised by any automated test.
"""

import pytest

from engine import first_run, paths


class FakeStore:
    def __init__(self, values=None):
        self._values = dict(values or {})

    def has(self, section, key):
        return (section, key) in self._values

    def get(self, section, key):
        return self._values[(section, key)]

    def set(self, section, key, value):
        self._values[(section, key)] = value


class RecordingPicker:
    """Returns the queued answers in order and records every prompt."""

    def __init__(self, answers):
        self._answers = list(answers)
        self.calls = []

    def __call__(self, title, message):
        self.calls.append((title, message))
        if not self._answers:
            return None
        return self._answers.pop(0)


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


def _unresolved(store=None):
    return paths.resolve(argv=[], env={}, store=store or FakeStore())


def test_both_missing_prompts_twice_and_resolves(install):
    game, sdk = install
    picker = RecordingPicker([str(game), str(sdk)])
    result = first_run.prompt_for_missing(
        _unresolved(), picker=picker, argv=[], env={}, store=FakeStore())
    assert result.ok
    assert len(picker.calls) == 2
    assert result.source("game") == "picker"


def test_a_resolved_root_is_not_re_asked(install):
    game, sdk = install
    argv = ["--game-dir", str(game)]
    start = paths.resolve(argv=argv, env={}, store=FakeStore())
    assert start.game is not None and start.sdk is None
    picker = RecordingPicker([str(sdk)])
    result = first_run.prompt_for_missing(
        start, picker=picker, argv=argv, env={}, store=FakeStore())
    assert result.ok
    assert len(picker.calls) == 1
    assert "SDK" in picker.calls[0][0]


def test_an_invalid_pick_re_prompts_with_what_was_wrong(install, tmp_path):
    game, sdk = install
    # The parent of a valid game root is itself invalid -- it holds no
    # markers -- so the first answer fails and the panel comes back.
    picker = RecordingPicker([str(tmp_path / "install"), str(game), str(sdk)])
    result = first_run.prompt_for_missing(
        _unresolved(), picker=picker, argv=[], env={}, store=FakeStore())
    assert result.ok
    assert len(picker.calls) == 3          # game, game retry, sdk
    first_message, retry_message = picker.calls[0][1], picker.calls[1][1]
    assert first_message == ""             # nothing to report on a first ask
    assert retry_message                   # the retry says what was wrong


def test_cancel_on_the_first_prompt_asks_nothing_further():
    picker = RecordingPicker([None])
    result = first_run.prompt_for_missing(
        _unresolved(), picker=picker, argv=[], env={}, store=FakeStore())
    assert not result.ok
    assert len(picker.calls) == 1


def test_a_validated_pick_survives_a_later_cancel(install):
    game, _sdk = install
    picker = RecordingPicker([str(game), None])
    result = first_run.prompt_for_missing(
        _unresolved(), picker=picker, argv=[], env={}, store=FakeStore())
    assert not result.ok                   # sdk still missing
    assert result.game == game             # but the game root is kept
    assert result.source("game") == "picker"


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_a_blank_pick_is_a_cancellation(blank):
    picker = RecordingPicker([blank])
    result = first_run.prompt_for_missing(
        _unresolved(), picker=picker, argv=[], env={}, store=FakeStore())
    assert not result.ok
    assert result.game is None             # never Path("."), which Path("") becomes
    assert len(picker.calls) == 1


def test_no_picker_available_returns_the_resolution_unchanged():
    start = _unresolved()
    result = first_run.prompt_for_missing(
        start, picker=lambda title, message: None, argv=[], env={},
        store=FakeStore())
    assert result == start
