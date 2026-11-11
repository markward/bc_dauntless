"""The first-run screen's state machine, with no CEF and no dialog.

Every decision the screen makes lives here rather than in the page,
because the page cannot be tested: CEF is software-rasterized in this
project, so there is no headless render to assert against.
"""

import hashlib
import json

import pytest

from engine import first_run, paths, stock_scripts
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


def _hash(data: bytes) -> str:
    return hashlib.blake2b(data, digest_size=16).hexdigest()


# A two-file stand-in for the committed stock manifest, so a fake install
# can pass the stock-scripts install check (engine.stock_scripts).
_FILES = {"MissionLib.pyc": b"missionlib", "AI/Preprocessors.pyc": b"preprocessors"}


@pytest.fixture(autouse=True)
def _small_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "cache_dir", lambda: tmp_path / "cache")
    stock_scripts.configure({rel: [_hash(data)] for rel, data in _FILES.items()}, None)
    yield
    stock_scripts.configure(None, None)


def _make_install(root, skip=()):
    for rel in ("data", "data/Models", "data/Textures", "data/Icons"):
        (root / rel).mkdir(parents=True, exist_ok=True)
    for rel, data in _FILES.items():
        if rel in skip:
            continue
        target = root / "scripts" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return root


@pytest.fixture
def install(tmp_path):
    """A game install that passes the stock-scripts check."""
    return _make_install(tmp_path / "install" / "game")   # paths-guard: test fixture tree


@pytest.fixture
def broken_install(tmp_path):
    """Markers all present, one listed stock file missing."""
    return _make_install(tmp_path / "broken" / "game",     # paths-guard: test fixture tree
                         skip=("AI/Preprocessors.pyc",))


def _panel(picker, store=None, argv=None):
    """A panel over a resolution where nothing is configured (or what argv
    names), re-resolving through the boot check the way host_loop does."""
    store = store or FakeStore()
    argv = argv or []
    start = stock_scripts.checked(paths.resolve(argv=argv, env={}, store=store))

    def resolver(picked):
        return stock_scripts.checked(
            paths.resolve(argv=argv, env={}, store=store, picked=picked))

    return FirstRunPanel(start, picker=picker, resolver=resolver)


def _payload(panel):
    """The dict the panel would send to JS, decoded from its JS call."""
    js = panel.render_payload()
    assert js is not None, "expected a payload"
    assert js.startswith("setFirstRun(") and js.endswith(");")
    return json.loads(js[len("setFirstRun("):-len(");")])


def test_one_row_only():
    """The game folder is the one content root (spec 2026-11-11 §4.4)."""
    panel = _panel(RecordingPicker([]))
    payload = _payload(panel)
    assert payload["title"] == "Select Bridge Commander Install"
    assert [row["kind"] for row in payload["rows"]] == ["game"]
    assert payload["rows"][0]["label"] == "Game folder"
    assert payload["rows"][0]["status"] == "Not set"
    assert payload["can_continue"] is False
    assert panel.dispatch_event("browse:sdk") is False   # paths-guard: kind label


def test_a_valid_browse_satisfies_the_row(install):
    game = install
    picker = RecordingPicker([str(game)])
    panel = _panel(picker)
    _payload(panel)                       # drain the initial payload
    panel.dispatch_event("browse:game")
    payload = _payload(panel)
    assert payload["rows"][0]["status"] == "Bridge Commander install found"
    assert payload["rows"][0]["path"] == str(game)
    assert payload["can_continue"] is True
    assert panel.outcome is None          # enabling is not pressing
    assert picker.calls[0][0] == "Select your Bridge Commander game folder"


def test_an_invalid_browse_reports_the_verdict_and_the_hint(install):
    # The data folder is one level too deep -- paths.py emits a hint saying so.
    panel = _panel(RecordingPicker([str(install / "data")]))
    panel.dispatch_event("browse:game")
    payload = _payload(panel)
    row = payload["rows"][0]
    assert row["status"] == "Not a Bridge Commander install"
    assert row["hint"]
    assert payload["can_continue"] is False


def test_a_broken_install_is_rejected_naming_the_file(broken_install):
    """Spec §4.1a: a folder missing a listed stock .pyc is not accepted;
    the row says which file, and Continue stays disabled."""
    panel = _panel(RecordingPicker([str(broken_install)]))
    panel.dispatch_event("browse:game")
    payload = _payload(panel)
    row = payload["rows"][0]
    assert row["status"] == "Not a Bridge Commander install"
    assert row["state"] == "bad"
    assert "scripts/AI/Preprocessors.pyc" in row["hint"]
    assert row["hint"] == stock_scripts.check_install(broken_install).message
    assert payload["can_continue"] is False
    panel.dispatch_event("continue")
    assert panel.outcome is None
    assert panel.resolution.game is None


def test_a_folder_with_no_scripts_is_rejected_naming_the_file(tmp_path):
    """A content-only copy (data but no scripts folder) was accepted before
    stock scripts came from the install; it is the likeliest upgrade case,
    so the row must say what is missing, not just "not an install"."""
    data_only = tmp_path / "content-only"
    for rel in ("data", "data/Models", "data/Textures", "data/Icons"):
        (data_only / rel).mkdir(parents=True, exist_ok=True)
    panel = _panel(RecordingPicker([str(data_only)]))
    panel.dispatch_event("browse:game")
    payload = _payload(panel)
    row = payload["rows"][0]
    assert row["state"] == "bad"
    assert "scripts/MissionLib.pyc" in row["hint"]
    assert payload["can_continue"] is False


def test_a_root_broken_at_boot_opens_with_the_checks_hint(broken_install):
    """host_loop hands the screen a Resolution its boot check unresolved:
    the row opens showing why, not a blank "Not set"."""
    panel = _panel(RecordingPicker([]), argv=["--game-dir", str(broken_install)])
    row = _payload(panel)["rows"][0]
    assert row["state"] == "bad"
    assert row["status"] == "Not a Bridge Commander install"
    assert "scripts/AI/Preprocessors.pyc" in row["hint"]


def test_the_status_line_never_enumerates_markers(install):
    panel = _panel(RecordingPicker([str(install)]))
    panel.dispatch_event("browse:game")
    blob = json.dumps(_payload(panel))
    for marker in paths.GAME_MARKERS:
        assert marker not in blob, (
            "the status line is a verdict, not a checklist -- "
            + marker + " leaked into the payload"
        )


def test_a_cancelled_browse_leaves_the_row_untouched(install):
    panel = _panel(RecordingPicker([str(install), None]))
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


def test_an_already_resolved_root_starts_satisfied(install):
    picker = RecordingPicker([])
    panel = _panel(picker, argv=["--game-dir", str(install)])
    payload = _payload(panel)
    assert payload["rows"][0]["status"] == "Bridge Commander install found"
    assert payload["can_continue"] is True
    assert picker.calls == []


def test_continue_sets_the_outcome_only_when_allowed(install):
    panel = _panel(RecordingPicker([str(install)]))
    panel.dispatch_event("continue")
    assert panel.outcome is None, "Continue must be inert while the row is unsatisfied"
    panel.dispatch_event("browse:game")
    panel.dispatch_event("continue")
    assert panel.outcome == "continue"
    assert panel.resolution.ok


def test_quit_sets_the_outcome_and_keeps_what_validated(install):
    panel = _panel(RecordingPicker([str(install)]))
    panel.dispatch_event("browse:game")
    panel.dispatch_event("quit")
    assert panel.outcome == "quit"
    assert panel.resolution.game == install
    assert panel.resolution.source("game") == "picker"


def test_quit_before_any_pick_leaves_nothing_resolved():
    panel = _panel(RecordingPicker([]))
    panel.dispatch_event("quit")
    assert panel.outcome == "quit"
    assert not panel.resolution.ok


def test_an_unknown_action_is_not_handled():
    panel = _panel(RecordingPicker([]))
    assert panel.dispatch_event("nonsense") is False


def test_render_payload_is_idempotent_until_something_changes(install):
    panel = _panel(RecordingPicker([str(install)]))
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
    picker = RecordingPicker([str(install / "data")])   # one level too deep
    panel = _panel(picker, argv=["--game-dir", str(install)])
    _payload(panel)                       # drain the initial payload
    panel.dispatch_event("browse:game")
    payload = _payload(panel)
    row = payload["rows"][0]
    assert row["ok"] is True
    assert row["status"] == "Bridge Commander install found"
    assert row["path"] == str(install)    # the OLD valid root, not destroyed
    assert row["hint"]                    # the bad click still says something
    assert payload["can_continue"] is True
    assert row["state"] == "ok"           # the row is fine; the LAST CLICK wasn't


def test_a_bad_browse_on_an_unsatisfied_row_still_reports_not_an_install(install):
    """Pin: the behaviour above must not regress the ORIGINAL case -- a bad
    pick on a row with no valid root yet still reports NOT_AN_INSTALL with
    the hint, and can_continue stays False.
    """
    panel = _panel(RecordingPicker([str(install / "data")]))
    panel.dispatch_event("browse:game")
    payload = _payload(panel)
    row = payload["rows"][0]
    assert row["ok"] is False
    assert row["status"] == "Not a Bridge Commander install"
    assert row["path"] == ""
    assert row["hint"]
    assert payload["can_continue"] is False


def test_row_state_pins_ok_bad_and_unset(install):
    """`state` is the page's ONLY signal for the status colour, because
    `path` is "" for both an untouched row and a rejected one and so can't
    tell them apart on its own. Pin all three values across the row's
    lifecycle.
    """
    panel = _panel(RecordingPicker([str(install / "data"), str(install)]))

    assert _payload(panel)["rows"][0]["state"] == "unset"   # never touched

    panel.dispatch_event("browse:game")             # invalid pick
    assert _payload(panel)["rows"][0]["state"] == "bad"     # rejected, never valid

    panel.dispatch_event("browse:game")             # valid pick
    assert _payload(panel)["rows"][0]["state"] == "ok"      # satisfied


def test_a_cancelled_browse_after_a_rejection_leaves_the_rejection_in_place(install):
    """A cancel does not clear a PRIOR rejection -- the row stays exactly as
    it was, hint included, same as the plain cancelled-browse case above.
    """
    panel = _panel(RecordingPicker([str(install / "data"), None]))
    panel.dispatch_event("browse:game")
    before = _payload(panel)
    panel.dispatch_event("browse:game")    # picker returns None this time
    after = panel.render_payload()
    assert after is None, "a cancelled browse changes nothing, so nothing re-renders"
    assert before["rows"][0]["status"] == "Not a Bridge Commander install"
    assert before["rows"][0]["hint"]


def test_a_raising_binding_is_treated_as_no_picker(monkeypatch):
    """FINDING 3: signature drift, a non-UTF-8 path, anything the binding
    itself raises must collapse to the same "no picker" answer as a
    cancel or a missing binding -- not an unhandled traceback out of
    run(). Exercise _default_picker directly against a fake
    _dauntless_host so the real native module is never touched.

    Moved here from tests/unit/test_first_run_picker.py when
    first_run.prompt_for_missing was deleted -- FirstRunPanel is
    _default_picker's only caller now.
    """
    import sys
    import types

    fake_module = types.ModuleType("_dauntless_host")

    def _raising_pick_folder(title, message):
        raise RuntimeError("boom")

    fake_module.pick_folder = _raising_pick_folder
    monkeypatch.setitem(sys.modules, "_dauntless_host", fake_module)

    assert first_run._default_picker("title", "message") is None
