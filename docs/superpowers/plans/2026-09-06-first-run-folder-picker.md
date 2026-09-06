# First-Run Folder Picker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a BC root cannot be resolved at launch, ask the player for it with a native folder panel, validate the choice, persist what validates, and continue booting.

**Architecture:** A near-logicless native `NSOpenPanel` in the always-built `platform` library, exposed to Python as `_dauntless_host.pick_folder`. All decision logic (which roots to ask for, order, retry, cancel, persistence) lives in a new pure-Python `engine/first_run.py`, called from exactly one place — the boot failure branch of `host_loop.run()`. `engine/paths.py` gains a highest-precedence `picked` source and stays pure: it never prompts.

**Tech Stack:** Python 3.11, pybind11, Objective-C++ / AppKit, CMake.

**Spec:** `docs/superpowers/specs/2026-09-06-first-run-folder-picker-design.md`

## Global Constraints

- **`engine/paths.py` never prompts and never blocks.** `paths.current()` is reached lazily by `tools/`, pytest and CI, none of which can dismiss a modal dialog. The only caller of the picker is `host_loop.run()`.
- **Never spell the BC root directory names as path segments** in `engine/`, `tools/`, project-root `*.py`, `tests/conftest.py` or `native/src`. Ask `paths.game_asset(rel)`, `paths.game_root()`, `paths.sdk_scripts()`, `paths.sdk_data()`. Enforced by `tests/unit/test_path_indirection.py`. A string that only *describes* the layout is exempted in place with a `# paths-guard: <reason>` comment.
- **Never capture a path at import.** No module-level constant may hold one. `paths.configure()` is callable again after boot — that is exactly what this feature needs.
- **The existing source names are `"cli" | "env" | "settings" | "project" | ""`.** The in-project fallback is spelled `"project"`, not `"legacy"`. The new source is `"picker"`; the `resolve()` keyword is `picked`.
- **A cancel, an unsupported platform, and a stale `.so` missing the binding are the same branch.** All three yield `None` and route to `describe_failure()` + exit 1.
- **Build only from the canonical tree:** `cmake -B build -S .` then `cmake --build build -j`. Never run `cmake` inside `native/`.
- **Gate with `scripts/check_tests.sh`**, never `scripts/run_tests.sh`. Never add a line to `tests/known_failures.txt` — if a new failure appears, stop and report.
- **This checkout is shared with concurrent sessions.** Read the "Shared checkout" section of CLAUDE.md before running any git command that writes. Stage with explicit pathspecs only, never a whole-tree add. To mutate a file temporarily, copy it to `/tmp`, mutate, restore by copying back, and `diff` to prove the restore is byte-identical — never revert via git.
- **Commit messages end with:** `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`

## File Structure

| File | Responsibility |
|---|---|
| `engine/paths.py` (modify) | Add `picked` as the highest-precedence source; `persist()` accepts `"picker"` |
| `engine/first_run.py` (create) | All picker flow: order, retry, cancel, empty-string, partial persist. The only module that prompts |
| `native/src/platform/folder_picker.h` (create) | Declaration + the contract that cancel and no-implementation are indistinguishable |
| `native/src/platform/folder_picker.mm` (create) | macOS `NSOpenPanel`. No logic beyond showing the panel |
| `native/src/platform/folder_picker.cc` (create) | Non-Apple fallback returning `std::nullopt` |
| `native/src/platform/CMakeLists.txt` (modify) | Add the sources; link AppKit on Apple |
| `native/src/host/host_bindings.cc` (modify) | `pick_folder` binding |
| `engine/host_loop.py` (modify) | Extract `_resolve_paths_or_report()`; call the picker from it |
| `tests/unit/test_paths_picked_source.py` (create) | Precedence and persistence of the new source |
| `tests/unit/test_first_run_picker.py` (create) | The whole flow, with a fake picker |
| `tests/host/test_pick_folder_binding.py` (create) | The binding exists and has the expected shape |
| `tests/host/test_host_loop_first_run.py` (create) | Boot wiring + the no-picker fallback guard |

---

### Task 1: The `picked` source in `engine/paths.py`

**Files:**
- Modify: `engine/paths.py` — `_candidate()`, `resolve()`, `persist()`
- Test: `tests/unit/test_paths_picked_source.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `paths.resolve(argv=None, env=None, store=None, picked=None) -> Resolution` where `picked` is `dict[str, str] | None` keyed `"game"` / `"sdk"`.
  - `Resolution.source(kind)` returns `"picker"` for a picked root.
  - `paths.persist(resolution, store=None)` writes roots whose source is `"cli"` or `"picker"`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_paths_picked_source.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_paths_picked_source.py -q`

Expected: FAIL — `resolve() got an unexpected keyword argument 'picked'`

- [ ] **Step 3: Add the `picked` tier to `_candidate()`**

In `engine/paths.py`, change the signature and prepend the new tier. The existing docstring stays; add the picker paragraph as the first branch comment.

```python
def _candidate(kind: str, argv, env, store, picked=None):
    """The highest-precedence SET source for one root, as (value, source).

    Returns (None, "") when nothing is set. A set-but-wrong source is
    returned as-is and never skipped in favour of a lower one -- falling
    through would run a different install than the one that was asked for.

    "Set" is deliberately NOT the same test at every tier -- see each
    branch below for why.
    """
    # Picker: a folder the player chose in the first-run dialog, and the
    # most recent explicit human act there is. It outranks the CLI tier
    # BECAUSE of the set-wins rule, not in spite of it: an invalid
    # --game-dir stays "set", so anything lower would lose to the very
    # flag the dialog exists to correct.
    if picked is not None:
        chosen = picked.get(kind)
        if chosen is not None:
            return chosen, "picker"

    # CLI: present in argv -> SET, even when the value is "". Typing the
    # ... (rest of the function unchanged)
```

- [ ] **Step 4: Thread `picked` through `resolve()`**

Change the signature and the one call site inside the loop:

```python
def resolve(argv=None, env=None, store=None, picked=None) -> Resolution:
    """Resolve both roots. PURE: no globals, no writes, no ambient state
    beyond the defaults for argv/env/store.

    `picked` is the first-run dialog's answer -- a dict keyed "game" /
    "sdk" -- and outranks every other source. It is a plain argument, not
    ambient state, so this function still never prompts and never blocks.

    settings_store is imported HERE rather than at module scope: it imports
    engine.ui.configuration_panel, and this module is imported by
    engine/audio/ and engine/appc/.
    """
```

and inside the `for kind in ("game", "sdk"):` loop:

```python
        value, source = _candidate(kind, argv, env, store, picked)
```

- [ ] **Step 5: Let `persist()` accept a picked root**

```python
def persist(resolution: Resolution, store=None) -> None:
    """Write CLI- and picker-sourced roots to settings.json [paths].

    Only these two, and only when valid. An env var is ephemeral by
    contract, so `DAUNTLESS_SDK_DIR=/fixtures pytest` cannot mutate a real
    config; and a typo never becomes the stored answer, which would make
    the NEXT launch fail for a reason the player has already forgotten
    about. A picked root is stored for the opposite reason: the whole
    point of asking was to not ask again.
    """
    if store is None:
        from engine.settings_store import SettingsStore
        store = SettingsStore()
        store.load()
    for kind in ("game", "sdk"):
        root = resolution.game if kind == "game" else resolution.sdk
        if root is not None and resolution.source(kind) in ("cli", "picker"):
            store.set("paths", kind, str(root))
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_paths_picked_source.py -q`

Expected: PASS (7 tests)

- [ ] **Step 7: Run the existing path suites for regressions**

Run: `uv run pytest tests/unit/test_paths_resolve.py tests/unit/test_paths_validate.py tests/unit/test_paths_late_reconfigure.py tests/unit/test_path_indirection.py -q`

Expected: PASS, with no change in the collected count.

- [ ] **Step 8: Commit**

Stage exactly `engine/paths.py` and `tests/unit/test_paths_picked_source.py`, then commit:

```
feat(paths): add picked as the highest-precedence root source

A pick is the most recent explicit human act and must outrank the flag it
is correcting. Writing it into settings.json and re-resolving would not:
the set-wins rule keeps an invalid --game-dir winning over the folder the
player just chose in the dialog.

persist() now stores cli- and picker-sourced roots. Env and settings are
still refused, for the reasons already documented there.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
```

---

### Task 2: `engine/first_run.py` — the flow

**Files:**
- Create: `engine/first_run.py`
- Test: `tests/unit/test_first_run_picker.py`

**Interfaces:**
- Consumes: `paths.resolve(..., picked=...)` from Task 1; `paths.validate_game_root`, `paths.validate_sdk_root`, `Resolution.validation(kind)`, `Validation.missing`, `Validation.hint`, `Validation.root`.
- Produces: `first_run.prompt_for_missing(resolution, picker=None, argv=None, env=None, store=None) -> Resolution`, where `picker` is `Callable[[str, str], str | None]` taking `(title, message)`. Also `first_run._default_picker(title, message)`, which Task 5's tests monkeypatch.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_first_run_picker.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_first_run_picker.py -q`

Expected: FAIL — `ImportError: cannot import name 'first_run' from 'engine'`

- [ ] **Step 3: Write `engine/first_run.py`**

```python
"""The first-run folder picker's flow. The ONLY module that may prompt.

engine/paths.py stays pure on purpose. tools/ scripts, pytest and CI all
reach paths.current() lazily, and none of them can dismiss a modal
dialog -- a picker reachable from the library would hang them. Keeping
the prompt here, called from exactly one place in host_loop.run(), makes
that true by construction rather than by discipline.

Nothing in this module captures a path at import.
"""

from typing import Callable, Dict, Optional

from engine import paths

_TITLES = {
    "game": "Select your Bridge Commander game folder",
    "sdk": "Select your Bridge Commander SDK folder",
}

_VALIDATORS = {"game": paths.validate_game_root, "sdk": paths.validate_sdk_root}


def _default_picker(title: str, message: str) -> Optional[str]:
    """The native panel, when this build and platform have one.

    Deliberately getattr-guarded rather than declared in the renderer's
    _REQUIRED_BINDINGS: this runs BEFORE validate_bindings(), so a stale
    .so reaches here first and would raise instead of being reported. A
    missing binding is simply "no picker", which is the same branch as a
    cancel and as a platform with no implementation.
    """
    try:
        import _dauntless_host
    except ImportError:
        return None
    pick = getattr(_dauntless_host, "pick_folder", None)
    if pick is None:
        return None
    return pick(title, message)


def _message_for(verdict) -> str:
    """What the panel says. Empty on a first ask, informative on a retry."""
    if verdict is None:
        return ""
    parts = []
    if verdict.missing:
        parts.append("That folder is missing: " + ", ".join(verdict.missing))
    if verdict.hint:
        parts.append(verdict.hint)
    return "  ".join(parts)


def prompt_for_missing(
    resolution,
    picker: Optional[Callable[[str, str], Optional[str]]] = None,
    argv=None,
    env=None,
    store=None,
):
    """Ask for each unresolved root; return a Resolution built from the answers.

    Asks for game first, then sdk, skipping any root that already
    resolved. An invalid choice re-prompts saying what was wrong; a cancel
    stops immediately. A root that validated before a later cancel is
    KEPT, so the next launch only asks for what is still missing.

    A blank answer is treated as a cancellation. Path("") stringifies to
    "." at construction, so once built it cannot be told apart from a
    deliberate Path(".") -- the rejection has to happen here, before any
    Path exists.
    """
    if picker is None:
        picker = _default_picker

    picked: Dict[str, str] = {}
    for kind in ("game", "sdk"):
        already = resolution.game if kind == "game" else resolution.sdk
        if already is not None:
            continue
        message = _message_for(resolution.validation(kind))
        cancelled = False
        while True:
            choice = picker(_TITLES[kind], message)
            if choice is None or not str(choice).strip():
                cancelled = True
                break
            verdict = _VALIDATORS[kind](choice)
            if verdict.ok:
                picked[kind] = str(verdict.root)
                break
            message = _message_for(verdict)
        if cancelled:
            break

    if not picked:
        return resolution
    return paths.resolve(argv=argv, env=env, store=store, picked=picked)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_first_run_picker.py -q`

Expected: PASS (9 tests — the blank case is parametrised three ways)

- [ ] **Step 5: Confirm the import-time guard still passes**

`first_run.py` lives in `engine/`, so `tests/unit/test_path_indirection.py` scans it automatically for module-level path captures.

Run: `uv run pytest tests/unit/test_path_indirection.py -q`

Expected: PASS

- [ ] **Step 6: Commit**

Stage exactly `engine/first_run.py` and `tests/unit/test_first_run_picker.py`, then commit:

```
feat(paths): add the first-run picker flow

All of the picker's decisions -- order, retry, cancel, blank answers,
partial persistence -- live here in Python rather than in the native
panel, because a modal NSOpenPanel cannot be exercised by any automated
test. The native side is left with one job: show a panel.

A blank answer is rejected here, before a Path exists: Path("")
stringifies to "." at construction, so nothing downstream can tell it
from a deliberate Path(".").

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
```

---

### Task 3: The native panel

**Files:**
- Create: `native/src/platform/folder_picker.h`
- Create: `native/src/platform/folder_picker.mm`
- Create: `native/src/platform/folder_picker.cc`
- Modify: `native/src/platform/CMakeLists.txt`

**Interfaces:**
- Consumes: nothing.
- Produces: `std::optional<std::string> dauntless::platform::pick_folder(const std::string& title, const std::string& message)`.

There is no automated test for this task, and that is deliberate rather than an omission. A modal panel cannot be driven by ctest, and the game is not launched during verification. That is exactly why the file holds no logic: if its body grows past roughly 30 lines, the design has leaked and the excess belongs in `engine/first_run.py`. Verification here is that the tree builds and the existing ctest suite still passes.

- [ ] **Step 1: Write the header**

Create `native/src/platform/folder_picker.h`:

```cpp
// native/src/platform/folder_picker.h
//
// Native "choose a folder" panel for the first-run path picker.
//
// std::nullopt means BOTH "the player cancelled" AND "this platform has
// no implementation". Callers must treat them identically -- that is what
// lets Windows and Linux ship with no picker and no special case: boot
// falls through to the same describe_failure() + exit 1 either way.
//
// Deliberately in `platform` rather than `ui_cef`: src/ui_cef/CMakeLists.txt
// returns early when DAUNTLESS_ENABLE_CEF is off, so anything living there
// does not exist in --no-cef builds -- precisely the builds most likely to
// be run from a bare checkout with no BC content.
#pragma once

#include <optional>
#include <string>

namespace dauntless::platform {

/// Show a modal folder chooser. Blocks until dismissed.
///
/// `title` names the window; `message` is the explanatory line inside the
/// panel, and carries the previous attempt's problem on a retry.
std::optional<std::string> pick_folder(const std::string& title,
                                       const std::string& message);

}  // namespace dauntless::platform
```

- [ ] **Step 2: Write the macOS implementation**

Create `native/src/platform/folder_picker.mm`:

```objc
// native/src/platform/folder_picker.mm
//
// macOS NSOpenPanel folder chooser. See folder_picker.h for the contract.

#import <AppKit/AppKit.h>

#include "folder_picker.h"

namespace dauntless::platform {

std::optional<std::string> pick_folder(const std::string& title,
                                       const std::string& message) {
    @autoreleasepool {
        // NSOpenPanel needs an NSApplication to exist, and we cannot assume
        // one does: install_macos_app() sits behind DAUNTLESS_ENABLE_CEF,
        // and this runs from the boot failure branch BEFORE r.init(), so
        // GLFW has not made one either. sharedApplication is idempotent and
        // creates it if needed.
        [NSApplication sharedApplication];

        NSOpenPanel* panel = [NSOpenPanel openPanel];
        panel.canChooseFiles = NO;
        panel.canChooseDirectories = YES;
        panel.allowsMultipleSelection = NO;
        panel.prompt = @"Choose";
        if (!title.empty()) {
            panel.title = [NSString stringWithUTF8String:title.c_str()];
        }
        if (!message.empty()) {
            panel.message = [NSString stringWithUTF8String:message.c_str()];
        }

        if ([panel runModal] != NSModalResponseOK) {
            return std::nullopt;
        }
        NSURL* url = panel.URLs.firstObject;
        if (url == nil) {
            return std::nullopt;
        }
        const char* chosen = url.fileSystemRepresentation;
        if (chosen == nullptr || *chosen == '\0') {
            return std::nullopt;
        }
        return std::string(chosen);
    }
}

}  // namespace dauntless::platform
```

- [ ] **Step 3: Write the non-Apple fallback**

Create `native/src/platform/folder_picker.cc`:

```cpp
// native/src/platform/folder_picker.cc
//
// Fallback for platforms with no folder-chooser implementation. Compiles
// to nothing on Apple, where folder_picker.mm provides the symbol.
//
// Returning nullopt is not a stub awaiting completion so much as a
// deliberate degradation: boot treats it exactly like a cancel and prints
// the full describe_failure() diagnostic, which is the behaviour every
// platform had before this feature existed.

#include "folder_picker.h"

#ifndef __APPLE__

namespace dauntless::platform {

std::optional<std::string> pick_folder(const std::string& /*title*/,
                                       const std::string& /*message*/) {
    return std::nullopt;
}

}  // namespace dauntless::platform

#endif  // !__APPLE__
```

- [ ] **Step 4: Wire it into the build**

In `native/src/platform/CMakeLists.txt`, replace the single `add_library(platform STATIC exe_path.cc)` line with the source list and the AppKit link. The existing header comment above it stays as-is.

```cmake
set(PLATFORM_SOURCES exe_path.cc folder_picker.cc)
if(APPLE)
    list(APPEND PLATFORM_SOURCES folder_picker.mm)
endif()

add_library(platform STATIC ${PLATFORM_SOURCES})

# NSOpenPanel. PUBLIC so every target linking `platform` inherits the
# framework; both _dauntless_host and the host binary do.
if(APPLE)
    target_link_libraries(platform PUBLIC "-framework AppKit")
endif()
```

- [ ] **Step 5: Build and verify the C++ suite is unaffected**

Run:

```bash
cmake -B build -S .
cmake --build build -j
ctest --test-dir build
```

Expected: build succeeds; ctest reports 0 failures. Also confirm the ctest **case count** is unchanged from before this task — a test that silently stops registering looks identical to a passing one in the summary.

- [ ] **Step 6: Commit**

Stage exactly the three new `native/src/platform/folder_picker.*` files and `native/src/platform/CMakeLists.txt`, then commit:

```
feat(platform): add a native folder chooser

NSOpenPanel on macOS; std::nullopt everywhere else. Cancel and
no-implementation are deliberately the same answer, so Windows and Linux
degrade to the describe_failure() path with no special case.

It lives in platform, not ui_cef: ui_cef/CMakeLists.txt returns early
when CEF is off, so anything there is absent from --no-cef builds -- the
builds most likely to be run from a bare checkout with no BC content.

The file holds no logic. A modal panel cannot be exercised by ctest, so
every decision lives in engine/first_run.py where it is testable.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
```

---

### Task 4: The `pick_folder` binding

**Files:**
- Modify: `native/src/host/host_bindings.cc` — beside the `set_game_root` binding (find it by searching for `m.def("set_game_root"`)
- Test: `tests/host/test_pick_folder_binding.py`

**Interfaces:**
- Consumes: `dauntless::platform::pick_folder` from Task 3.
- Produces: `_dauntless_host.pick_folder(title: str, message: str) -> str | None`, which Task 2's `_default_picker` already calls.

`native/src/host/CMakeLists.txt` already links `platform` into `_dauntless_host`, so no link change is needed. `pybind11/stl.h` is already included, and that is what maps `std::optional<std::string>` to `str | None`.

- [ ] **Step 1: Write the failing test**

Create `tests/host/test_pick_folder_binding.py`:

```python
"""The binding exists and has the shape first_run expects.

Deliberately never CALLS it: pick_folder shows a modal panel and would
hang the suite forever. What is worth pinning is that the symbol is
present, because engine/first_run.py getattr-guards it -- so a stale .so
degrades to "no picker" in silence, which is the same class of failure
that hid ~73 dark-skipped tests on the path-resolution branch.
"""

import inspect

import pytest

_h = pytest.importorskip("_dauntless_host")


def test_pick_folder_binding_is_present():
    assert hasattr(_h, "pick_folder"), (
        "_dauntless_host.pick_folder is missing -- rebuild from build/. "
        "engine/first_run.py treats an absent binding as 'no picker', so "
        "without this test a stale .so silently disables the first-run "
        "dialog instead of failing."
    )


def test_pick_folder_documents_its_two_arguments():
    doc = inspect.getdoc(_h.pick_folder) or ""
    assert "title" in doc and "message" in doc
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/host/test_pick_folder_binding.py -q`

Expected: FAIL — `_dauntless_host.pick_folder is missing`

- [ ] **Step 3: Add the binding**

Add the include beside the other project includes near the top of `native/src/host/host_bindings.cc`:

```cpp
#include <platform/folder_picker.h>
```

and the binding immediately after the `set_game_root` definition:

```cpp
    m.def("pick_folder",
          [](const std::string& title, const std::string& message)
              -> std::optional<std::string> {
              // The panel is modal and blocks for as long as the player
              // takes to answer. Holding the GIL across that would freeze
              // every other Python thread for the duration.
              py::gil_scoped_release release;
              return dauntless::platform::pick_folder(title, message);
          },
          py::arg("title"), py::arg("message"),
          "Show a native folder chooser and return the chosen absolute "
          "path. Returns None when the player cancels -- and also when "
          "this platform has no implementation, which callers must treat "
          "identically. title names the window; message is the "
          "explanatory line inside the panel.");
```

- [ ] **Step 4: Rebuild and run the test**

Run:

```bash
cmake --build build -j
uv run pytest tests/host/test_pick_folder_binding.py -q
```

Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

Stage exactly `native/src/host/host_bindings.cc` and `tests/host/test_pick_folder_binding.py`, then commit:

```
feat(host): expose pick_folder to Python

The test pins presence only and never calls it -- a modal panel would
hang the suite. Presence is worth a test because first_run.py
getattr-guards the binding, so a stale .so would silently disable the
first-run dialog rather than fail.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
```

---

### Task 5: Wire it into boot

**Files:**
- Modify: `engine/host_loop.py` — the path-resolution block inside `run()` (find it by searching for `_paths.resolve()`)
- Test: `tests/host/test_host_loop_first_run.py`

**Interfaces:**
- Consumes: `first_run.prompt_for_missing` and `first_run._default_picker` from Task 2; `paths.resolve`, `paths.configure`, `paths.persist`, `paths.describe_failure`.
- Produces: `host_loop._resolve_paths_or_report() -> paths.Resolution | None`. `None` means the diagnostic has already been printed and `run()` should return 1.

The extraction exists so the branch is testable without booting a window: entering `run()` in a test is not viable, but a small named function is.

- [ ] **Step 1: Write the failing tests**

Create `tests/host/test_host_loop_first_run.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/host/test_host_loop_first_run.py -q`

Expected: FAIL — `module 'engine.host_loop' has no attribute '_resolve_paths_or_report'`

- [ ] **Step 3: Import `first_run` in `engine/host_loop.py`**

`host_loop` already imports `paths` as `_paths`. Add `first_run` beside that import at module scope — it pulls in only `typing` and `engine.paths`, so it is cheap and captures no paths:

```python
from engine import first_run
```

- [ ] **Step 4: Extract the branch into a testable function**

Add this immediately above `run()`:

```python
def _resolve_paths_or_report():
    """Resolve the BC roots, asking the player if they are not configured.

    Returns the Resolution on success. Returns None after printing the
    full diagnostic, which means run() should return 1.

    The prompt sits behind this one call site on purpose: paths.current()
    is reached lazily by tools/ scripts, pytest and CI, none of which can
    dismiss a modal dialog. A picker reachable from the library would hang
    them, so the library never has one.
    """
    resolution = _paths.resolve()
    if not resolution.ok:
        resolution = first_run.prompt_for_missing(resolution)
    _paths.configure(resolution)
    if not resolution.ok:
        import sys as _sys
        print(_paths.describe_failure(resolution), file=_sys.stderr)
        return None
    _paths.persist(resolution)
    return resolution
```

- [ ] **Step 5: Call it from `run()`**

Replace the existing block — the six lines from `_resolution = _paths.resolve()` through `_paths.persist(_resolution)` — with:

```python
    # Resolve where BC content lives before anything asks for any of it. This
    # must precede the SDK setup call below: the SDK meta-path finder calls
    # paths.sdk_scripts(), so configuring afterwards would be too late.
    #
    # An unresolved root prompts the player with a native folder panel. A
    # cancel, an unsupported platform and a stale .so all land on the same
    # branch, which prints the diagnostic instead.
    _resolution = _resolve_paths_or_report()
    if _resolution is None:
        return 1
```

Leave `_setup_sdk()` and everything after it untouched.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/host/test_host_loop_first_run.py -q`

Expected: PASS (2 tests)

- [ ] **Step 7: Run the full gate and check the counts, not just the verdict**

Run: `scripts/check_tests.sh`

Expected: `OK — no new failures.`

Then run `uv run pytest tests -q --tb=no` and compare the raw tail against the pre-task baseline: **8205 passed, 3 skipped, 1 xfailed, 1 known failure**. A rise in the skip count means a test went dark — that is a regression, not noise, and the gate cannot see it. Confirm the ctest case count is unchanged too.

- [ ] **Step 8: Commit**

Stage exactly `engine/host_loop.py` and `tests/host/test_host_loop_first_run.py`, then commit:

```
feat(paths): prompt for the BC roots on first run

Boot's failure branch now offers a native folder panel instead of only
printing to stderr and exiting -- the game is a GUI binary that may be
launched from Finder with no terminal, where that message is invisible
and both remedies it suggests need a terminal to act on.

The branch is extracted into _resolve_paths_or_report() so the fallback
is testable without booting a window. That fallback guard is the
important one: if a picker-less platform ever boots on unresolved paths,
or drops the diagnostic, no other test would catch it.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
```

---

## Live verification (Mark runs these)

None of this can be checked headlessly, and the panel is unreachable from any automated test.

1. Remove the `[paths]` section from `settings.json`, with no BC content inside the project → two dialogs appear, game first.
2. Pick both valid folders → the game boots.
3. Relaunch → no dialogs.
4. Pick an invalid folder → the panel reappears, naming the missing markers.
5. Cancel → the terminal shows the full `describe_failure()` text and a non-zero exit.
