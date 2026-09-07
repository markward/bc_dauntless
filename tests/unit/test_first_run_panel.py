"""The first-run screen's state machine, with no CEF and no dialog.

Every decision the screen makes lives here rather than in the page,
because the page cannot be tested: CEF is software-rasterized in this
project, so there is no headless render to assert against.
"""

import json

import pytest

from engine import paths
from engine.ui.first_run_panel import FirstRunPanel


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
    def __init__(self, answers):
        self._answers = list(answers)
        self.calls = []

    def __call__(self, title, message):
        self.calls.append((title, message))
        return self._answers.pop(0) if self._answers else None


@pytest.fixture
def install(tmp_path):
    game = tmp_path / "install" / "game"        # paths-guard: test fixture tree
    for marker in paths.GAME_MARKERS:
        (game / marker).mkdir(parents=True, exist_ok=True)
    sdk = tmp_path / "install" / "sdk"          # paths-guard: test fixture tree
    (sdk / "Build" / "scripts").mkdir(parents=True, exist_ok=True)
    (sdk / "Build" / "scripts" / "App.py").write_text("")
    (sdk / "Build" / "Data" / "TGL").mkdir(parents=True, exist_ok=True)
    return game, sdk


def _panel(picker, store=None, argv=None):
    """A panel over a resolution where nothing is configured."""
    store = store or FakeStore()
    argv = argv or []
    start = paths.resolve(argv=argv, env={}, store=store)

    def resolver(picked):
        return paths.resolve(argv=argv, env={}, store=store, picked=picked)

    return FirstRunPanel(start, picker=picker, resolver=resolver)


def _payload(panel):
    """The dict the panel would send to JS, decoded from its JS call."""
    js = panel.render_payload()
    assert js is not None, "expected a payload"
    assert js.startswith("setFirstRun(") and js.endswith(");")
    return json.loads(js[len("setFirstRun("):-len(");")])


def test_both_rows_start_unset():
    panel = _panel(RecordingPicker([]))
    payload = _payload(panel)
    assert payload["title"] == "Select Bridge Commander Install"
    assert [row["status"] for row in payload["rows"]] == ["Not set", "Not set"]
    assert payload["can_continue"] is False


def test_a_valid_browse_satisfies_that_row_only(install):
    game, _sdk = install
    panel = _panel(RecordingPicker([str(game)]))
    _payload(panel)                       # drain the initial payload
    panel.dispatch_event("browse:game")
    payload = _payload(panel)
    assert payload["rows"][0]["status"] == "Bridge Commander install found"
    assert payload["rows"][0]["path"] == str(game)
    assert payload["rows"][1]["status"] == "Not set"
    assert payload["can_continue"] is False


def test_continue_enables_only_when_both_validate(install):
    game, sdk = install
    panel = _panel(RecordingPicker([str(game), str(sdk)]))
    panel.dispatch_event("browse:game")
    panel.dispatch_event("browse:sdk")
    payload = _payload(panel)
    assert payload["can_continue"] is True
    assert panel.outcome is None          # enabling is not pressing


def test_an_invalid_browse_reports_the_verdict_and_the_hint(install, tmp_path):
    sdk = install[1]
    # The Build folder is one level too deep -- paths.py emits a hint saying so.
    panel = _panel(RecordingPicker([str(sdk / "Build")]))
    panel.dispatch_event("browse:sdk")
    payload = _payload(panel)
    row = payload["rows"][1]
    assert row["status"] == "Not a Bridge Commander install"
    assert row["hint"]
    assert payload["can_continue"] is False


def test_the_status_line_never_enumerates_markers(install):
    game, _sdk = install
    panel = _panel(RecordingPicker([str(game)]))
    panel.dispatch_event("browse:game")
    blob = json.dumps(_payload(panel))
    for marker in paths.GAME_MARKERS + paths.SDK_MARKERS:
        assert marker not in blob, (
            "the status line is a verdict, not a checklist -- "
            + marker + " leaked into the payload"
        )


def test_a_cancelled_browse_leaves_the_row_untouched(install):
    game, _sdk = install
    panel = _panel(RecordingPicker([str(game), None]))
    panel.dispatch_event("browse:game")
    before = _payload(panel)
    panel.dispatch_event("browse:game")    # picker returns None this time
    after = panel.render_payload()
    assert after is None, "a cancelled browse changes nothing, so nothing re-renders"
    assert before["rows"][0]["status"] == "Bridge Commander install found"


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_a_blank_browse_answer_is_treated_as_a_cancel(blank):
    panel = _panel(RecordingPicker([blank]))
    _payload(panel)
    panel.dispatch_event("browse:game")
    assert panel.render_payload() is None
    assert panel.resolution.game is None    # never Path("."), which Path("") becomes


def test_an_already_resolved_root_starts_satisfied_and_is_not_asked(install):
    game, sdk = install
    picker = RecordingPicker([str(sdk)])
    panel = _panel(picker, argv=["--game-dir", str(game)])
    payload = _payload(panel)
    assert payload["rows"][0]["status"] == "Bridge Commander install found"
    panel.dispatch_event("browse:sdk")
    assert len(picker.calls) == 1
    assert "SDK" in picker.calls[0][0]


def test_continue_sets_the_outcome_only_when_allowed(install):
    game, sdk = install
    panel = _panel(RecordingPicker([str(game), str(sdk)]))
    panel.dispatch_event("continue")
    assert panel.outcome is None, "Continue must be inert while a row is unsatisfied"
    panel.dispatch_event("browse:game")
    panel.dispatch_event("browse:sdk")
    panel.dispatch_event("continue")
    assert panel.outcome == "continue"
    assert panel.resolution.ok


def test_quit_sets_the_outcome_and_keeps_what_validated(install):
    game, _sdk = install
    panel = _panel(RecordingPicker([str(game)]))
    panel.dispatch_event("browse:game")
    panel.dispatch_event("quit")
    assert panel.outcome == "quit"
    assert panel.resolution.game == game
    assert panel.resolution.source("game") == "picker"
    assert not panel.resolution.ok


def test_an_unknown_action_is_not_handled():
    panel = _panel(RecordingPicker([]))
    assert panel.dispatch_event("nonsense") is False


def test_render_payload_is_idempotent_until_something_changes(install):
    game, _sdk = install
    panel = _panel(RecordingPicker([str(game)]))
    assert panel.render_payload() is not None
    assert panel.render_payload() is None
    panel.dispatch_event("browse:game")
    assert panel.render_payload() is not None


def test_invalidate_forces_a_re_emit():
    panel = _panel(RecordingPicker([]))
    panel.render_payload()
    assert panel.render_payload() is None
    panel.invalidate()
    assert panel.render_payload() is not None


def test_a_bad_browse_on_an_already_satisfied_row_keeps_the_valid_root(install):
    """Regression: a bad re-browse of an already-valid row must not produce
    a self-contradictory payload -- claiming "Not a Bridge Commander
    install" while still showing the OLD, still-valid path, with
    can_continue coming from the still-good Resolution regardless. The
    player's earlier work must stand; the bad click should still say
    something (via hint), or it looks like it did nothing.
    """
    game, sdk = install
    # One level too deep -- invalid, same fixture shape as the existing
    # invalid-browse test.
    picker = RecordingPicker([str(sdk / "Build")])
    panel = _panel(picker, argv=["--game-dir", str(game), "--sdk-dir", str(sdk)])
    _payload(panel)                       # drain the initial payload
    panel.dispatch_event("browse:sdk")
    payload = _payload(panel)
    row = payload["rows"][1]
    assert row["ok"] is True
    assert row["status"] == "Bridge Commander install found"
    assert row["path"] == str(sdk)        # the OLD valid root, not destroyed
    assert row["hint"]                    # the bad click still says something
    assert payload["can_continue"] is True
    assert row["state"] == "ok"           # the row is fine; the LAST CLICK wasn't


def test_a_bad_browse_on_an_unsatisfied_row_still_reports_not_an_install(install):
    """Pin: the behaviour above must not regress the ORIGINAL case -- a bad
    pick on a row with no valid root yet still reports NOT_AN_INSTALL with
    the hint, and can_continue stays False.
    """
    sdk = install[1]
    panel = _panel(RecordingPicker([str(sdk / "Build")]))
    panel.dispatch_event("browse:sdk")
    payload = _payload(panel)
    row = payload["rows"][1]
    assert row["ok"] is False
    assert row["status"] == "Not a Bridge Commander install"
    assert row["path"] == ""
    assert row["hint"]
    assert payload["can_continue"] is False


def test_row_state_pins_ok_bad_and_unset(install):
    """`state` is the page's ONLY signal for the status colour, because
    `path` is "" for both an untouched row and a rejected one and so can't
    tell them apart on its own. Pin all three values across one row's
    lifecycle plus the sibling row staying untouched throughout.
    """
    game, sdk = install
    panel = _panel(RecordingPicker([str(sdk / "Build"), str(game)]))

    payload = _payload(panel)
    assert payload["rows"][0]["state"] == "unset"   # never touched
    assert payload["rows"][1]["state"] == "unset"

    panel.dispatch_event("browse:sdk")              # invalid pick
    payload = _payload(panel)
    assert payload["rows"][1]["state"] == "bad"     # rejected, never valid
    assert payload["rows"][0]["state"] == "unset"   # still untouched

    panel.dispatch_event("browse:game")             # valid pick
    payload = _payload(panel)
    assert payload["rows"][0]["state"] == "ok"      # satisfied


def test_a_cancelled_browse_after_a_rejection_leaves_the_rejection_in_place(install):
    """A cancel does not clear a PRIOR rejection -- the row stays exactly as
    it was, hint included, same as the plain cancelled-browse case above.
    """
    sdk = install[1]
    panel = _panel(RecordingPicker([str(sdk / "Build"), None]))
    panel.dispatch_event("browse:sdk")
    before = _payload(panel)
    panel.dispatch_event("browse:sdk")    # picker returns None this time
    after = panel.render_payload()
    assert after is None, "a cancelled browse changes nothing, so nothing re-renders"
    assert before["rows"][1]["status"] == "Not a Bridge Commander install"
    assert before["rows"][1]["hint"]
