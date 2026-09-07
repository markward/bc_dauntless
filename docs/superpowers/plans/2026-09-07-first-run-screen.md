# First-Run Screen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the bare native folder dialogs with a full-screen "Select Bridge Commander Install" screen drawn in CEF over the normal game window, with Browse buttons that still open the native panel.

**Architecture:** Boot is reordered so the window and CEF come up before the BC roots are resolved. A `FirstRunPanel` (`Panel` subclass, pure Python) holds all state and decisions; the CEF page renders what it is given and reports button presses; a small pump loop drives `r.frame()` until the player continues or quits, with `set_hologram_only_mode` on so no 3D scene — and therefore no asset load — happens while the roots are unknown.

**Tech Stack:** Python 3.11, CEF (software-rasterized, no WebGL), the existing `Panel` / `PanelRegistry` framework, pybind11.

**Spec:** `docs/superpowers/specs/2026-09-06-first-run-folder-picker-design.md` — revised 2026-09-07. Read it; this plan argues from it.

**Prior work on this branch (already merged into the branch, do not redo):** `paths.resolve(picked=)` with the `"picker"` source, `persist()` accepting it, `folder_picker.mm` / `folder_picker.cc` / the `pick_folder` binding, and `engine/first_run.py`'s picker access and validation helpers.

## Global Constraints

- **`engine/paths.py` stays PURE** — never prompts, never blocks. It must not be modified by this plan.
- **The untestable layer is a renderer, never a decider.** `folder_picker.mm`, the pump loop, and the CEF page have no automated coverage. Every conditional belongs in `FirstRunPanel`, which is testable with a fake picker and a fake transport. If you find yourself writing an `if` in JS beyond show/hide of what Python sent, it belongs in Python.
- **Never capture a path at import.** `tests/unit/test_path_indirection.py` enforces this across all of `engine/`.
- **Never spell the BC root directory names as path segments** in `engine/`, `tools/`, project-root `*.py`, `tests/conftest.py` or `native/src`. A string that only *describes* the layout is exempted in place with `# paths-guard: <reason>`.
- **The row status line is a verdict, never a checklist.** It must never enumerate `GAME_MARKERS` / `SDK_MARKERS`. Exact strings: `Not set`, `Bridge Commander install found`, `Not a Bridge Commander install` (plus the `hint` when present).
- **Screen title: `Select Bridge Commander Install`.** This is a setup step, not an error report. Only a row that was actually answered wrongly says what was wrong.
- **The panel is centred and carries its own semi-opaque card.** Nothing in the layout may depend on what the background image depicts.
- **JS pushed into CEF before the page's scripts have run is silently dropped.** The screen's initial state goes out from the load-end handler, never at `cef_initialize` time.
- **Continue enables only when BOTH roots validate.** `_setup_sdk()` runs immediately after.
- Build only from the canonical tree: `cmake -B build -S .`, `cmake --build build -j`. Never `cmake` inside `native/`.
- Gate with `scripts/check_tests.sh`. Never add a line to `tests/known_failures.txt` — if a new failure appears, stop and report.
- This checkout is shared with concurrent sessions. Read the "Shared checkout" section of CLAUDE.md before any git command that writes. Stage with explicit pathspecs only. To mutate a file temporarily, copy it to `/tmp`, mutate, restore by copying back, and `diff` to prove byte-identity — never revert via git.
- Commit messages end with: `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`

## File Structure

| File | Responsibility |
|---|---|
| `engine/first_run.py` (modify, **Task 4**) | Keep `_default_picker`; `prompt_for_missing` is deleted only once Task 4 replaces its caller |
| `engine/ui/first_run_panel.py` (create) | `Panel` subclass: row state, validation, Continue gating, event dispatch |
| `native/assets/ui-cef/index.html` (modify) | The screen's markup section |
| `native/assets/ui-cef/css/first_run.css` (create) | Centred card over a full-bleed background |
| `native/assets/ui-cef/js/first_run.js` (create) | `setFirstRun(payload)` — render only |
| `engine/host_loop.py` (modify) | Boot reorder; `_run_first_run_screen()` pump loop |
| `tests/unit/test_first_run_panel.py` (create) | The panel's whole state machine |
| `tests/host/test_host_loop_first_run.py` (modify) | Boot-order and fallback guards |

---

### Task 1: `FirstRunPanel` — the state machine

**Files:**
- Create: `engine/ui/first_run_panel.py`
- Modify: `engine/first_run.py` — add a "superseded" comment only; **no deletions** (see Step 4)
- Test: `tests/unit/test_first_run_panel.py`

**Interfaces:**
- Consumes: `paths.validate_game_root`, `paths.validate_sdk_root`, `paths.resolve(picked=…)`, `Resolution.game/.sdk/.ok/.source(kind)`, `Validation.ok/.root/.hint`; `first_run._default_picker(title, message)`.
- Produces: `FirstRunPanel(resolution, picker=None, resolver=None)` with `name == "first-run"`, `render_payload()`, `dispatch_event(action)`, `.outcome` (`None` while running, `"continue"` or `"quit"` when finished), `.resolution` (the current best `Resolution`).

**`prompt_for_missing` is superseded but NOT removed here.** It drives its own blocking loop over the picker, which becomes the panel's job — but its only caller is `host_loop._resolve_paths_or_report()`, which Task 4 rewires. Deleting it in this task leaves the tree red for two whole tasks, which is exactly what happened on this plan's first attempt. Task 4 Step 5 removes it, once nothing calls it.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_first_run_panel.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_first_run_panel.py -q`

Expected: FAIL — `ModuleNotFoundError: No module named 'engine.ui.first_run_panel'`

- [ ] **Step 3: Write `engine/ui/first_run_panel.py`**

```python
"""The "Select Bridge Commander Install" screen's state machine.

Every decision the screen makes is here. The CEF page renders the payload
this class emits and reports button presses back; it holds no logic of its
own, because CEF is software-rasterized in this project and there is no
headless render to test a page against.

Nothing in this module captures a path at import.
"""
from __future__ import annotations

import json
from typing import Callable, Dict, Optional

from engine import first_run, paths
from engine.ui.panel import Panel

TITLE = "Select Bridge Commander Install"

_UNSET = "Not set"
_FOUND = "Bridge Commander install found"
_NOT_AN_INSTALL = "Not a Bridge Commander install"

_ROWS = (
    # kind, label, picker title
    ("game", "Game folder",  # paths-guard: kind label, matches Resolution.source()'s vocabulary
     "Select your Bridge Commander game folder"),
    ("sdk", "SDK folder",    # paths-guard: kind label, matches Resolution.source()'s vocabulary
     "Select your Bridge Commander SDK folder"),
)

_VALIDATORS = {
    "game": paths.validate_game_root,  # paths-guard: kind label, keys paths.py's own validators
    "sdk": paths.validate_sdk_root,    # paths-guard: kind label, keys paths.py's own validators
}


class FirstRunPanel(Panel):
    """One row per BC root, Browse each, Continue gated on both validating.

    `picker` is the folder chooser -- injected so tests never open a modal.
    `resolver` maps a {kind: path} dict to a Resolution; injected for the
    same reason paths.resolve() takes argv/env/store, so a test can supply a
    store without touching the developer's real settings.json.
    """

    def __init__(self, resolution, picker: Optional[Callable[[str, str], Optional[str]]] = None,
                 resolver: Optional[Callable[[Dict[str, str]], object]] = None):
        super().__init__()
        self._picker = picker if picker is not None else first_run._default_picker
        self._resolver = resolver if resolver is not None else _default_resolver
        self._resolution = resolution
        # Rows the player answered this session, kind -> validated path str.
        self._picked: Dict[str, str] = {}
        # Rows the player answered WRONGLY, kind -> hint (or ""). Cleared by a
        # later valid answer. Separate from _picked so a bad answer can be
        # reported without becoming a candidate root.
        self._rejected: Dict[str, str] = {}
        self._outcome: Optional[str] = None
        self._last_pushed: Optional[str] = None

    @property
    def name(self) -> str:
        return "first-run"

    @property
    def outcome(self) -> Optional[str]:
        """None while the screen is running; "continue" or "quit" when done."""
        return self._outcome

    @property
    def resolution(self):
        """The best Resolution so far -- including a root validated before a
        quit, which persist() stores so the next launch asks only for what is
        still missing."""
        return self._resolution

    # ── state ───────────────────────────────────────────────────────────
    def _root_for(self, kind: str):
        return self._resolution.game if kind == "game" else self._resolution.sdk  # paths-guard: kind label, not a path segment

    def _status_for(self, kind: str) -> dict:
        if kind in self._rejected:
            return {"status": _NOT_AN_INSTALL, "hint": self._rejected[kind], "ok": False}
        root = self._root_for(kind)
        if root is None:
            return {"status": _UNSET, "hint": "", "ok": False}
        return {"status": _FOUND, "hint": "", "ok": True}

    def _snapshot(self) -> dict:
        rows = []
        for kind, label, _title in _ROWS:
            root = self._root_for(kind)
            row = {"kind": kind, "label": label, "path": str(root) if root else ""}
            row.update(self._status_for(kind))
            rows.append(row)
        return {
            "title": TITLE,
            "rows": rows,
            "can_continue": self._resolution.ok,
        }

    # ── Panel contract ──────────────────────────────────────────────────
    def render_payload(self) -> Optional[str]:
        script = "setFirstRun(" + json.dumps(self._snapshot()) + ");"
        if script == self._last_pushed:
            return None
        self._last_pushed = script
        return script

    def dispatch_event(self, action: str) -> bool:
        if action.startswith("browse:"):
            return self._browse(action[len("browse:"):])
        if action == "continue":
            # Inert unless both roots validate -- the page disables the
            # button, but the page is not the authority on this.
            if self._resolution.ok:
                self._outcome = "continue"
            return True
        if action == "quit":
            self._outcome = "quit"
            return True
        return False

    def invalidate(self) -> None:
        """Drop the payload snapshot so the next render re-emits. Called on
        CEF document load, which is the only moment the page is guaranteed
        able to receive it -- a push before the page's scripts have run is
        silently dropped."""
        self._last_pushed = None

    def handle_key_esc(self) -> None:
        """ESC does what Quit does, so the two can never disagree."""
        self.dispatch_event("quit")

    # ── browse ──────────────────────────────────────────────────────────
    def _browse(self, kind: str) -> bool:
        if kind not in _VALIDATORS:
            return False
        title = next(t for k, _label, t in _ROWS if k == kind)
        choice = self._picker(title, "")
        # No answer: a cancel, a platform with no picker, or a stale .so.
        # All three mean the same thing -- leave the row exactly as it was.
        # Blank is rejected HERE, before a Path exists: Path("") stringifies
        # to "." at construction and is then indistinguishable from a
        # deliberate Path(".").
        if choice is None or not str(choice).strip():
            return True
        verdict = _VALIDATORS[kind](choice)
        if not verdict.ok:
            self._rejected[kind] = verdict.hint or ""
            return True
        self._rejected.pop(kind, None)
        self._picked[kind] = str(verdict.root)
        self._resolution = self._resolver(dict(self._picked))
        return True


def _default_resolver(picked: Dict[str, str]):
    return paths.resolve(picked=picked)
```

- [ ] **Step 4: Leave `prompt_for_missing` alone — it is deleted in Task 4**

**Corrected 2026-09-07 after this task's first attempt left the tree red.**
An earlier version of this step had you delete `prompt_for_missing` here.
Do not: its only caller is `engine/host_loop.py`'s `_resolve_paths_or_report()`,
which is not rewired until Task 4. Deleting it now breaks three tests in
`tests/host/test_host_loop_first_run.py` with `AttributeError`, including the
feature's most important guard, and Task 2's full gate would then go red for a
reason that has nothing to do with Task 2.

Add a short comment above `prompt_for_missing` saying it is superseded by
`engine.ui.first_run_panel.FirstRunPanel` and is removed once `host_loop` stops
calling it — so the next reader does not delete it again, and does not mistake
it for a second live prompting path.

`engine/first_run.py` is otherwise untouched by this task. `_default_picker`
stays exactly as it is: your panel's default picker is that function.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_first_run_panel.py tests/unit/test_path_indirection.py -q`

Expected: PASS. Then confirm nothing still references the deleted function:

Run: `grep -rn "prompt_for_missing" engine/ tests/`
Expected: no output.

- [ ] **Step 6: Commit**

Stage `engine/ui/first_run_panel.py`, `engine/first_run.py`, `tests/unit/test_first_run_panel.py` and whatever you changed in `tests/unit/test_first_run_picker.py`, then commit:

```
feat(ui): add the first-run screen's state machine

Every decision the screen makes lives here: row state, validation, which
picker title to use, and whether Continue is allowed. The CEF page renders
the payload and reports button presses, because CEF is software-rasterized
in this project and a page has no headless render to test against.

prompt_for_missing is deleted. It drove its own blocking loop over the
picker, which is now the panel's job; left in place it would be dead code
that can still prompt, quietly breaking the spec's guarantee that the
picker is reachable from exactly one call site.

Continue is gated in Python, not only by the page's disabled attribute --
the page is not the authority on whether both roots validated.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
```

---

### Task 2: Reorder boot

**Files:**
- Modify: `engine/host_loop.py` — `run()`
- Test: `tests/host/test_host_loop_first_run.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: a `run()` whose order is `r.init()` → binding validation → `cef_initialize()` → resolve → `_setup_sdk()` → `import App`.

This task changes ONLY the order, with the paths already resolvable. The screen arrives in Task 4. Doing the reorder alone gives it its own review gate, because it is the riskiest change in the plan and everything else depends on it.

- [ ] **Step 1: Write the failing test**

Add to `tests/host/test_host_loop_first_run.py`:

```python
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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/host/test_host_loop_first_run.py -q`

Expected: FAIL — the current order puts `_resolve_paths_or_report()` and `_setup_sdk()` before `r.init(`, so the assertion is false (or `.index` raises if a spelling has moved).

- [ ] **Step 3: Move the resolution block down**

In `engine/host_loop.py`'s `run()`, cut this block:

```python
    _resolution = _resolve_paths_or_report()
    if _resolution is None:
        return 1

    _setup_sdk()

    import App
    from engine.core.loop import GameLoop
    from engine.appc import collisions
    from engine.appc import camera_shake
```

and paste it immediately AFTER the `cef_initialize` block, keeping the comments with it. Update the leading comment to say why it now sits there:

```python
    # Resolve where BC content lives. This runs AFTER cef_initialize so the
    # first-run screen has a live browser to draw into when the roots are
    # not configured -- and still BEFORE _setup_sdk(), because the SDK
    # meta-path finder calls paths.sdk_scripts().
    #
    # Verified safe to boot this far unresolved: CEF's page is project
    # content, not BC content, and window/pipeline init reads no game
    # assets.
    _resolution = _resolve_paths_or_report()
    if _resolution is None:
        return 1

    _setup_sdk()

    import App
    from engine.core.loop import GameLoop
    from engine.appc import collisions
    from engine.appc import camera_shake
```

**Before you move it, check what depends on it.** `import App` and the
`engine.appc` imports are moving from before `r.init()` to after
`cef_initialize`. Anything in between that touches `App`, `GameLoop`,
`collisions` or `camera_shake` would break at runtime, not at import, and
no test would necessarily catch it. Read every line between the old and new
positions and confirm none of them do. Say in your report what you checked
and what you found — "I moved it and the tests pass" is not that check.

- [ ] **Step 4: Move `set_game_root` after the resolution**

`r.set_game_root(str(_paths.game_root()))` currently sits before `cef_initialize`. It must now follow the resolution — calling it earlier would ask `paths.game_root()` for an answer that does not exist yet. Move it to immediately after the `_resolution is None` guard, keeping its existing comment, and leave `host_io.validate_bindings()` / `host_io.verify_keys()` exactly where they are and adjacent to each other.

- [ ] **Step 5: Run the boot tests**

Run: `uv run pytest tests/host/test_host_loop_first_run.py tests/unit/test_paths_resolve.py -q`

Expected: PASS. `test_boot_resolution_is_wired_before_the_sdk_finder`, `test_boot_sets_the_renderer_game_root` and `test_run_returns_nonzero_when_paths_are_unresolved` all still apply and must still pass — if any now fails, the reorder broke an invariant, not just a source-grep.

- [ ] **Step 6: Bounded headless boot**

A clean build proves nothing about boot order — the failure mode here is a runtime import or a call against an unset root. Run the binary with a hard timeout and confirm it reaches the game loop rather than dying:

```bash
timeout 25 ./build/dauntless --smoke-check 2>&1 | tail -20
```

If `--smoke-check` is not a supported flag on this build, run `timeout 25 ./build/dauntless 2>&1 | tail -20` and report what you see. Either way, paste the output into your report — this is the only evidence the reorder actually boots.

- [ ] **Step 7: Run the full gate**

Run: `scripts/check_tests.sh`, then `uv run pytest tests -q --tb=no` and record the raw tail. Compare passed / skipped / xfailed / failed against the pre-task baseline you were given. A rise in skips is a regression.

- [ ] **Step 8: Commit**

```
refactor(boot): bring the window and CEF up before resolving BC roots

The first-run screen needs a live browser to draw into, and it cannot have
one while path resolution gates everything ahead of r.init(). Resolution,
_setup_sdk() and `import App` now follow cef_initialize; set_game_root
follows the resolution, since it asks paths.game_root() for an answer that
does not exist before it.

Safe to boot this far unresolved, verified before committing to it: CEF's
page is native/assets/ui-cef/index.html -- project content, not BC content
-- and window/pipeline init reads no game assets.

This is order only. The screen arrives next; with the roots resolvable the
behaviour is unchanged.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
```

---

### Task 3: The page

**Files:**
- Modify: `native/assets/ui-cef/index.html`
- Create: `native/assets/ui-cef/css/first_run.css`
- Create: `native/assets/ui-cef/js/first_run.js`

**Interfaces:**
- Consumes: `setFirstRun(payload)` called from Python, where payload is `{title, rows: [{kind, label, path, status, hint, ok}], can_continue}`.
- Produces: `dauntlessEvent('first-run/browse:game')`, `'first-run/browse:sdk'`, `'first-run/continue'`, `'first-run/quit'`.

There is no automated test for this task; CEF is software-rasterized here, so there is no headless render to assert against. That is exactly why the page holds no logic: it renders the payload it is handed and reports clicks. **If you write a conditional in JS beyond showing or hiding what Python sent, it belongs in `FirstRunPanel`.**

- [ ] **Step 1: Add the markup**

In `native/assets/ui-cef/index.html`, beside the other panel sections (the `mission-picker` section is a good neighbour), add:

```html
    <section id="first-run" hidden>
        <div class="fr-backdrop"></div>
        <div class="fr-card">
            <h1 class="fr-title" id="fr-title"></h1>
            <div class="fr-rows" id="fr-rows"></div>
            <div class="fr-actions">
                <button type="button" class="fr-btn"
                        onclick="dauntlessEvent('first-run/quit')">Quit</button>
                <button type="button" class="fr-btn fr-btn-primary" id="fr-continue"
                        onclick="dauntlessEvent('first-run/continue')">Continue</button>
            </div>
        </div>
    </section>
```

Add the stylesheet link beside the other `<link>` tags and the script beside the other panel scripts near the end of `<body>`:

```html
    <script src="js/first_run.js"></script>
```

- [ ] **Step 2: Add the stylesheet**

Create `native/assets/ui-cef/css/first_run.css`. The card is centred and carries its own semi-opaque background, so it stays legible over any backdrop — nothing here may depend on what the image depicts.

```css
#first-run {
    position: fixed;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 100;
}

/* Full-bleed background, with a starfield-ish gradient BEHIND it so a
   missing or failed image degrades to something deliberate rather than a
   white void. */
#first-run .fr-backdrop {
    position: absolute;
    inset: 0;
    background:
        url("../images/first-run-bg.png") center / cover no-repeat,
        radial-gradient(ellipse at 30% 40%, #10131c 0%, #05070c 60%, #000 100%);
}

#first-run .fr-card {
    position: relative;
    width: 30rem;
    max-width: 80vw;
    padding: 2rem 2.25rem;
    background: rgba(8, 11, 18, 0.88);
    border: 1px solid rgba(120, 160, 220, 0.35);
    border-radius: 6px;
    box-shadow: 0 1.5rem 4rem rgba(0, 0, 0, 0.6);
    color: #dfe7f5;
}

#first-run .fr-title {
    margin: 0 0 1.5rem;
    font-size: 1.35rem;
    font-weight: 500;
    letter-spacing: 0.02em;
}

#first-run .fr-row { margin-bottom: 1.35rem; }
#first-run .fr-row-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
}
#first-run .fr-label { font-size: 0.95rem; }
#first-run .fr-path {
    margin-top: 0.35rem;
    font-size: 0.8rem;
    color: #93a3bd;
    word-break: break-all;
    min-height: 1em;
}
#first-run .fr-status { margin-top: 0.3rem; font-size: 0.85rem; }
#first-run .fr-status.ok { color: #7fd4a0; }
#first-run .fr-status.bad { color: #e8a0a0; }
#first-run .fr-status.unset { color: #7b8798; }
#first-run .fr-hint {
    margin-top: 0.2rem;
    font-size: 0.8rem;
    color: #c9b98a;
}

#first-run .fr-actions {
    display: flex;
    justify-content: flex-end;
    gap: 0.75rem;
    margin-top: 1.75rem;
}
#first-run .fr-btn {
    padding: 0.45rem 1.1rem;
    font: inherit;
    font-size: 0.9rem;
    color: #dfe7f5;
    background: rgba(40, 52, 72, 0.9);
    border: 1px solid rgba(120, 160, 220, 0.35);
    border-radius: 4px;
    cursor: pointer;
}
#first-run .fr-btn-primary { background: rgba(48, 84, 132, 0.95); }
#first-run .fr-btn:disabled {
    opacity: 0.4;
    cursor: default;
}
```

- [ ] **Step 3: Add the script**

Create `native/assets/ui-cef/js/first_run.js`. Render only — no decisions.

```js
// The "Select Bridge Commander Install" screen.
//
// Renders whatever engine/ui/first_run_panel.py sends and reports button
// presses back. It holds no logic of its own: CEF is software-rasterized in
// this project, so there is no headless render to test a page against, and
// anything conditional therefore belongs in Python where it can be.
function setFirstRun(payload) {
    var root = document.getElementById('first-run');
    if (!root) { return; }
    if (!payload) { root.hidden = true; return; }

    document.getElementById('fr-title').textContent = payload.title;

    var rows = document.getElementById('fr-rows');
    rows.innerHTML = '';
    payload.rows.forEach(function (row) {
        var el = document.createElement('div');
        el.className = 'fr-row';

        var head = document.createElement('div');
        head.className = 'fr-row-head';

        var label = document.createElement('span');
        label.className = 'fr-label';
        label.textContent = row.label;

        var browse = document.createElement('button');
        browse.type = 'button';
        browse.className = 'fr-btn';
        browse.textContent = 'Browse…';
        browse.setAttribute(
            'onclick', "dauntlessEvent('first-run/browse:" + row.kind + "')");

        head.appendChild(label);
        head.appendChild(browse);
        el.appendChild(head);

        var path = document.createElement('div');
        path.className = 'fr-path';
        path.textContent = row.path;
        el.appendChild(path);

        var status = document.createElement('div');
        status.className = 'fr-status ' + (row.ok ? 'ok' : (row.path ? 'bad' : 'unset'));
        status.textContent = row.status;
        el.appendChild(status);

        if (row.hint) {
            var hint = document.createElement('div');
            hint.className = 'fr-hint';
            hint.textContent = row.hint;
            el.appendChild(hint);
        }

        rows.appendChild(el);
    });

    document.getElementById('fr-continue').disabled = !payload.can_continue;
    root.hidden = false;
}
```

- [ ] **Step 4: Verify the assets are syntactically sound**

There is no render to test, so check what can be checked:

```bash
node --check native/assets/ui-cef/js/first_run.js
```

If `node` is unavailable, say so in your report and instead confirm by inspection that every `getElementById` in the script matches an `id` in the markup, and that every `id` referenced exists. List the pairs you checked.

Also confirm the background image is where the CSS expects it:

```bash
ls -l native/assets/ui-cef/images/first-run-bg.png
```

- [ ] **Step 5: Commit**

```
feat(ui): add the first-run screen's page

Renders the payload engine/ui/first_run_panel.py sends and reports button
presses back. No logic: CEF is software-rasterized in this project, so a
page has no headless render to test against, and every conditional
therefore lives in Python where a fake transport can drive it.

The card is centred and carries its own semi-opaque background, so it stays
legible over any backdrop -- nothing in the layout reads the image, which
is expected to be replaced. A starfield gradient sits behind the image so a
missing or failed asset degrades to something deliberate rather than a
white void.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
```

---

### Task 4: The pump loop and wiring

**Files:**
- Modify: `engine/host_loop.py` — `_resolve_paths_or_report()` and a new `_run_first_run_screen()`
- Test: `tests/host/test_host_loop_first_run.py`

**Interfaces:**
- Consumes: `FirstRunPanel` from Task 1; `r.frame()`, `r.should_close()`, `r.set_hologram_only_mode(enabled, bg)`, `_h.cef_execute_javascript(js)`, `_h.cef_set_event_handler(cb)`.
- Produces: `host_loop._run_first_run_screen(resolution) -> Resolution`, and a `_resolve_paths_or_report()` that calls it when resolution fails.

`r.frame()` already pumps CEF and composites it internally (`native/src/host/host_bindings.cc:1477` and `:1484`), so the loop body is four lines. **`set_hologram_only_mode` must be on for the whole screen**: it clears to a solid colour and skips the entire space and bridge pass, which is what guarantees no asset load happens while the game root is still unset. Turn it off before returning.

**⚠️ Source-grep tests: anchor on spellings that cannot match by accident.**
This branch has now been bitten three times by a `source.index(...)` guard
matching something other than what it named — once by `"paths.configure("`
matching the aliased `"_paths.configure("` one character in, and once by a
comment this plan itself suggested containing the literal `_setup_sdk()`,
which made a *comment* satisfy an ordering assertion about *code*. When you
write or edit one of these, check that the substring you search for appears
exactly once and in the position you mean — comments included.

- [ ] **Step 1: Write the failing tests**

Add to `tests/host/test_host_loop_first_run.py`:

```python
def test_the_screen_suppresses_the_3d_scene_while_it_runs(monkeypatch):
    """No asset may load while the game root is unset, so the scene pass is
    off for the screen's whole lifetime and back on before boot continues."""
    import inspect
    from engine import host_loop
    source = inspect.getsource(host_loop._run_first_run_screen)
    on_at = source.index("set_hologram_only_mode(True")
    off_at = source.index("set_hologram_only_mode(False")
    assert on_at < off_at, "the scene pass must be re-enabled after the screen"


def test_the_screen_pushes_its_first_payload_from_the_load_end_handler():
    """A push before the page's scripts have run is silently dropped in this
    project, which has caused real bugs. The screen's initial state must go
    out from the document-load handler, not at cef_initialize time."""
    import inspect
    from engine import host_loop
    source = inspect.getsource(host_loop._run_first_run_screen)
    assert "invalidate" in source, (
        "the panel must be invalidated on document load so its first payload "
        "is emitted once the page can actually receive it"
    )
```

Also assert the fallback still holds after the screen exists — the existing `test_no_picker_prints_the_diagnostic_and_stops_boot` must keep passing unchanged.

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/host/test_host_loop_first_run.py -q`

Expected: FAIL — `module 'engine.host_loop' has no attribute '_run_first_run_screen'`

- [ ] **Step 3: Write the pump loop**

Add above `_resolve_paths_or_report()` in `engine/host_loop.py`:

```python
def _run_first_run_screen(resolution):
    """Draw the "Select Bridge Commander Install" screen until the player
    continues or quits. Returns the best Resolution reached.

    r.frame() already pumps CEF and composites it, so this loop is only:
    emit whatever the panel has to say, draw, check the outcome.

    The 3D scene pass is OFF for the screen's whole lifetime. The game root
    is still unset here, so a scene pass could ask the renderer to resolve
    an asset path against the literal default -- hologram-only mode clears
    to a solid colour and skips the space and bridge passes entirely, which
    makes that impossible rather than unlikely.
    """
    from engine.ui.first_run_panel import FirstRunPanel

    panel = FirstRunPanel(resolution)

    _set_handler = getattr(_h, "cef_set_event_handler", None) if _h else None
    if _set_handler is not None:
        def _dispatch(event: str) -> None:
            prefix = panel.name + "/"
            if event.startswith(prefix):
                panel.dispatch_event(event[len(prefix):])
        _set_handler(_dispatch)

    r.set_hologram_only_mode(True, (0.0, 0.0, 0.0))
    try:
        # The page's scripts have not necessarily run yet, and a push before
        # they do is dropped. invalidate() forces a re-emit, and the loop
        # below re-emits every frame the snapshot changes, so the first
        # payload the page CAN receive is the first one it does.
        panel.invalidate()
        while not r.should_close() and panel.outcome is None:
            script = panel.render_payload()
            if script is not None and _h is not None:
                _h.cef_execute_javascript(script)
            r.frame()
    finally:
        r.set_hologram_only_mode(False, (0.0, 0.0, 0.0))
        if _h is not None:
            try:
                _h.cef_execute_javascript("setFirstRun(null);")
            except Exception as _e:
                dev_mode.log_swallowed("first-run screen teardown", _e)

    return panel.resolution
```

- [ ] **Step 4: Call it from the resolution branch**

Change `_resolve_paths_or_report()` so the screen replaces the old prompt:

```python
def _resolve_paths_or_report():
    """Resolve the BC roots, asking the player if they are not configured.

    Returns the Resolution on success. Returns None after printing the full
    diagnostic, which means run() should return 1.

    The screen is reachable from here and nowhere else: paths.current() is
    reached lazily by tools/ scripts, pytest and CI, none of which can drive
    a UI. A prompt reachable from the library would hang them, so the
    library never has one.
    """
    resolution = _paths.resolve()
    if not resolution.ok:
        resolution = _run_first_run_screen(resolution)
    _paths.configure(resolution)
    # Above the early return on purpose: a root the player located by hand
    # is stored even if they quit before finding the other one, so the next
    # launch asks only for what is still missing.
    _paths.persist(resolution)
    if not resolution.ok:
        import sys as _sys
        print(_paths.describe_failure(resolution), file=_sys.stderr)
        return None
    return resolution
```

- [ ] **Step 5: Delete `prompt_for_missing` — now that nothing calls it**

You have just replaced its only caller. Remove `prompt_for_missing` from
`engine/first_run.py`, along with `_message_for`, `_TITLES` and `_VALIDATORS`
if nothing else references them once it is gone — check with a grep rather
than assuming; `FirstRunPanel` has its own copies of the titles and validator
table. **Keep `_default_picker`**: the panel's default picker is that function.

Remove from `tests/unit/test_first_run_picker.py` every test that exercises
`prompt_for_missing`. Keep the tests covering `_default_picker` — the getattr
guard and the raising-picker guard — moving them into
`tests/unit/test_first_run_panel.py` if that empties the file.

This deletion belongs here and not earlier: leaving a second, blocking
prompting path alive would break the spec's guarantee that the picker is
reachable from exactly one call site, but deleting it before its caller is
replaced leaves the tree red for two whole tasks.

Confirm with `grep -rn "prompt_for_missing" engine/ tests/` — expect no output.

- [ ] **Step 6: Restore the real event handler after the screen**

The screen installs its own CEF event handler. `run()` installs the `PanelRegistry` handler later (search for `cef_set_event_handler`), which overwrites it — confirm by reading that this happens AFTER the screen returns, and say so in your report. If it does not, the screen's handler would survive into the game and swallow panel events.

- [ ] **Step 7: Run the tests**

Run: `uv run pytest tests/host/test_host_loop_first_run.py tests/unit/test_first_run_panel.py tests/unit/test_paths_resolve.py -q`

Expected: PASS.

- [ ] **Step 8: End-to-end boot evidence**

**Corrected 2026-09-07.** An earlier version of this step asked for
`timeout 25 ./build/dauntless --smoke-check`. Do not use that: `--smoke-check`
calls `engine.bootstrap.smoke_check()`, a different code path that never
invokes `host_loop.run()`, so it exercises none of this. Task 2 found that.
Launching the game directly is also against a standing project rule — Mark does
all live testing.

Use the existing pinned tests that drive `run()` end-to-end through the real
compiled bindings instead, including the clean-subprocess one, which is what
catches import-order bugs that an in-process run can mask:

```bash
uv run pytest tests/host/test_host_loop_unit.py -q -k "test_run_"
```

With the roots resolvable the screen must not appear and `run()` must return 0
exactly as before. Paste the output into your report.

- [ ] **Step 9: Run the full gate**

Run: `scripts/check_tests.sh`, then `uv run pytest tests -q --tb=no` and record the raw tail. Compare passed / skipped / xfailed / failed against the baseline. A rise in skips is a regression.

- [ ] **Step 10: Commit**

```
feat(paths): draw the first-run screen instead of bare dialogs

r.frame() already pumps and composites CEF, so the loop is: emit what the
panel has to say, draw, check the outcome.

The 3D scene pass is off for the screen's whole lifetime. The game root is
still unset there, so a scene pass could ask the renderer to resolve an
asset path against the literal default; hologram-only mode skips the space
and bridge passes entirely, which makes that impossible rather than
unlikely.

The panel is invalidated before the loop starts because a JS push before
the page's scripts have run is silently dropped in this project -- so the
first payload the page can receive is the first one it does.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
```

---

## Live verification (Mark runs these)

The spec's list is authoritative; these cannot be checked headlessly. The two most likely to fail:

- **Browse takes focus in front of the game window.** The screen now runs after `r.init()`, so GLFW has already created the `NSApp` that `pick_folder` used to create itself.
- **Continue hands off cleanly** from the pump loop to the real game loop — no leftover screen, no stuck input focus, no swallowed panel events.
