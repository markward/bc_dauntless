# BC Path Resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One authority, `engine/paths.py`, that resolves where the player's Bridge Commander `game/` and `sdk/` content lives, so an install can sit anywhere on disk.

**Architecture:** A pure `resolve()` reads four sources in precedence order (CLI flag → env var → `settings.json [paths]` → the legacy in-project layout), validates each candidate against the markers the engine actually loads, and caches the result. Every consumer — 36 engine sites, both SDK meta-path finders, 23 `tools/` scripts, and the C++ renderer's asset-path base — asks that cache at point of use, never at import.

**Tech Stack:** Python 3.11, pytest, pybind11, CMake/GoogleTest, existing `engine/settings_store.py`.

**Spec:** `docs/superpowers/specs/2026-09-05-bc-path-resolution-design.md`

## Global Constraints

- **Paths resolve at USE, never at import.** No module in `engine/` may bind a module-level name to a path obtained from `engine.paths`. Test scripts and `tools/` scripts that run to completion are exempt from this rule; `tools/mission_harness.py` is **NOT** exempt — it is imported at runtime by `engine/host_loop.py:3507`.
- **Nothing outside `engine/paths.py` may spell `game` or `sdk` as a path segment.** Not in `engine/`, not in `tools/`, not in `tests/conftest.py`, not in `native/src`.
- **Counts come from an AST scan, never a grep.** A grep over-reports (every `engine/` docstring citing `sdk/Build/scripts/...`) and under-reports (a constant split across lines, as `engine/dev_keybindings.py:20` is). The scan is: non-docstring string constants equal to `game`/`sdk` or beginning `game/`/`sdk/`.
- `GAME_MARKERS = ("data", "data/Models", "data/Textures", "data/Icons")`
- `SDK_MARKERS = ("Build/scripts/App.py", "Build/Data/TGL")`
- Precedence: `cli` → `env` → `settings` → `project`. **The highest-precedence source that is *set* wins, even if it is invalid** — it is never skipped in favour of a lower one. `project` is the sole exception: absent means "nothing configured", not an error.
- A CLI flag persists to `settings.json`; an env var never does. **Only a valid path persists.**
- Stored form: `expanduser()` → `abspath()` → `normpath`. **Never `Path.resolve()`** — symlinks must not be followed.
- `engine/paths.py` must not import `engine.settings_store` at module scope. `settings_store` imports `engine.ui.configuration_panel` at its line 29, and `paths` is imported by `engine/audio/` and `engine/appc/`.
- `Resolution.game` / `Resolution.sdk` are set **only when validation passes**. An invalid candidate leaves them `None` and records the attempt in `game_validation` / `sdk_validation`.
- C++ default game root stays the literal `"game"`, so every existing `renderer_tests` case and every `native/tools/` probe behaves exactly as it does now.
- Never run `git add -A` / `git add .`. Stage with explicit pathspecs only. Never run `git checkout --`, `git restore`, `git stash`, `git clean`, or `git reset --hard` — this tree is shared and holds uncommitted work.
- Test gate is `scripts/check_tests.sh`, never `scripts/run_tests.sh`. A failure is "pre-existing" only if it appears in `tests/known_failures.txt`.
- Do not launch the game, even headless. Live verification is Mark's.

## Starting state

`game/` and `sdk/` have been moved out of the project tree to
`/Users/mward/Documents/Star Trek Bridge Commander/{game,sdk}`. **The gate is
red before Task 1 begins** — `pytest --collect-only` reports 18 collection
errors. Task 3 restores it. Tasks 1 and 2 add new test files that run
standalone (`pytest tests/unit/test_paths_validate.py`) and must not be judged
against a green gate.

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `engine/paths.py` (create) | The single authority: markers, validation, resolution, cache, failure text | 1, 2 |
| `tests/conftest.py` (modify) | `fake_bc_install` fixture; SDK finder reads `paths.sdk_scripts()`; fail-fast when unresolved | 1, 3 |
| `tests/unit/test_paths_validate.py` (create) | Markers, the four diagnoses, the case rescan | 1 |
| `tests/unit/test_paths_resolve.py` (create) | The precedence matrix, persistence rules, `PathsUnresolved` | 2 |
| `tools/mission_harness.py` (modify) | Live SDK finder; no module-level path constant | 3 |
| `engine/**` (modify, 36 sites) | Consume `paths.game_asset()` / `paths.sdk_*()` | 4 |
| `tests/unit/test_paths_late_reconfigure.py` (create) | `configure()` twice is observed by every consumer | 4 |
| `tools/*.py` (modify, 23 scripts) | Consume `engine.paths` | 5 |
| `native/src/renderer/asset_path.cc` (create) | The one mutable game-root variable | 6 |
| `native/src/renderer/include/renderer/asset_path.h` (modify) | Declarations; `resolve_asset_path` no longer inline | 6 |
| `native/tests/renderer/asset_path_test.cc` (modify) | Set-root, legacy-prefix warning, idempotence under a changed root | 6 |
| `native/src/host/host_bindings.cc` (modify) | `set_game_root` binding | 6 |
| `engine/renderer.py` (modify) | `set_game_root` façade wrapper + REQUIRED binding | 6 |
| `engine/host_loop.py` (modify) | Boot wiring: resolve → configure → persist → `set_game_root` | 7 |
| `native/src/host/host_main.cc` (modify) | `--game-dir` / `--sdk-dir` pass-through and comment fix | 7 |
| `tests/unit/test_path_indirection.py` (create) | The three guards | 8 |
| `CLAUDE.md`, spec docstrings (modify) | Hard-rule section, table row, cross-references | 8 |

---

### Task 1: `engine/paths.py` — validation

**Files:**
- Create: `engine/paths.py`
- Create: `tests/unit/test_paths_validate.py`
- Modify: `tests/conftest.py` (add the `fake_bc_install` fixture only)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `GAME_MARKERS: tuple[str, ...]`, `SDK_MARKERS: tuple[str, ...]`
  - `@dataclass(frozen=True) Validation(ok: bool, root: Path, missing: tuple[str, ...], hint: str | None)`
  - `validate_game_root(path) -> Validation`
  - `validate_sdk_root(path) -> Validation`
  - pytest fixture `fake_bc_install(tmp_path)` returning `(game: Path, sdk: Path)`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_paths_validate.py`:

```python
"""Validation of a candidate BC game/sdk root.

Every test here runs with no real BC install present: fake_bc_install builds
marker trees under tmp_path.
"""
from pathlib import Path

from engine import paths


def test_a_complete_game_tree_validates(fake_bc_install):
    game, _sdk = fake_bc_install
    v = paths.validate_game_root(game)
    assert v.ok
    assert v.missing == ()
    assert v.hint is None


def test_a_complete_sdk_tree_validates(fake_bc_install):
    _game, sdk = fake_bc_install
    v = paths.validate_sdk_root(sdk)
    assert v.ok
    assert v.missing == ()


def test_missing_markers_are_listed_in_declaration_order(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "Textures").mkdir()
    v = paths.validate_game_root(tmp_path)
    assert not v.ok
    assert v.missing == ("data/Models", "data/Icons")


def test_stbc_exe_and_scripts_are_not_required(fake_bc_install):
    """A content-only copy is usable: neither is loaded at runtime."""
    game, _sdk = fake_bc_install
    assert not (game / "stbc.exe").exists()
    assert not (game / "scripts").exists()
    assert paths.validate_game_root(game).ok


def test_a_nonexistent_path_is_invalid_not_an_error(tmp_path):
    v = paths.validate_game_root(tmp_path / "nope")
    assert not v.ok
    assert v.missing == paths.GAME_MARKERS


# --- diagnoses --------------------------------------------------------------

def test_hint_when_the_parent_was_picked(fake_bc_install):
    """The most common mistake: picking the folder that CONTAINS game/."""
    game, _sdk = fake_bc_install
    v = paths.validate_game_root(game.parent)
    assert not v.ok
    assert v.hint is not None
    assert "contains 'game'" in v.hint
    assert str(game) in v.hint


def test_hint_when_the_two_roots_are_swapped(fake_bc_install):
    game, sdk = fake_bc_install
    v = paths.validate_game_root(sdk)
    assert not v.ok
    assert v.hint == "That's the SDK folder; it belongs in the SDK field."

    v2 = paths.validate_sdk_root(game)
    assert not v2.ok
    assert v2.hint == "That's the game folder; it belongs in the game field."


def test_hint_when_one_level_too_deep(fake_bc_install):
    """Picking game/data instead of game/."""
    game, _sdk = fake_bc_install
    v = paths.validate_game_root(game / "data")
    assert not v.ok
    assert v.hint is not None
    assert "pick its parent" in v.hint
    assert str(game) in v.hint


def test_case_mismatch_improves_the_message_without_changing_the_verdict(tmp_path):
    """On a case-sensitive volume, 'Data/' vs 'data/' is the whole problem."""
    root = tmp_path / "install"
    for rel in ("Data", "Data/Models", "Data/Textures", "Data/Icons"):
        (root / rel).mkdir(parents=True, exist_ok=True)
    v = paths.validate_game_root(root)
    if (root / "data").exists():
        # Case-insensitive filesystem: the exact check already succeeded and
        # the rescan must never have fired.
        assert v.ok
        assert v.hint is None
    else:
        assert not v.ok
        assert v.hint is not None
        assert "Data" in v.hint and "data" in v.hint


def test_hint_is_none_when_the_folder_is_simply_wrong(tmp_path):
    (tmp_path / "unrelated").mkdir()
    v = paths.validate_game_root(tmp_path)
    assert not v.ok
    assert v.hint is None


def test_validation_never_writes_anything(fake_bc_install):
    game, _sdk = fake_bc_install
    before = sorted(p.name for p in game.rglob("*"))
    paths.validate_game_root(game)
    paths.validate_game_root(game.parent)
    assert sorted(p.name for p in game.rglob("*")) == before
```

- [ ] **Step 2: Add the `fake_bc_install` fixture**

Append to `tests/conftest.py` (at the end of the file, after the existing
fixtures):

```python
@pytest.fixture
def fake_bc_install(tmp_path):
    """A minimal BC install: only the markers engine.paths validates.

    Deliberately omits stbc.exe and scripts/ — neither is loaded at runtime,
    so requiring them would reject a usable content-only copy.

    Returns (game_root, sdk_root), siblings under tmp_path/"install" so a test
    can pass their shared parent to reproduce the commonest mistake.
    """
    install = tmp_path / "install"
    game = install / "game"
    sdk = install / "sdk"
    for rel in ("data", "data/Models", "data/Textures", "data/Icons"):
        (game / rel).mkdir(parents=True, exist_ok=True)
    (sdk / "Build" / "scripts").mkdir(parents=True, exist_ok=True)
    (sdk / "Build" / "scripts" / "App.py").write_text("# fake App shim\n")
    (sdk / "Build" / "Data" / "TGL").mkdir(parents=True, exist_ok=True)
    return game, sdk
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_paths_validate.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.paths'`

- [ ] **Step 4: Write `engine/paths.py`**

Create `engine/paths.py`:

```python
"""Where the player's Bridge Commander content lives — the single authority.

BC content is two roots: the game install (models, textures, icons, sounds)
and the SDK (the Python scripts and the TGL string tables). Neither has to
live inside the project tree.

HARD RULE — paths resolve at USE, never at import.
    No module in engine/ may bind a module-level name to a path from here.
    Resolving early enough for import-time constants to work would make the
    first-run picker impossible: it runs after CEF is up, so anything captured
    at import is already stale by the time the player chooses a folder.

Nothing outside this module may spell "game" or "sdk" as a path segment.
tests/unit/test_path_indirection.py enforces both halves.

Spec: docs/superpowers/specs/2026-09-05-bc-path-resolution-design.md
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# The markers are the paths the engine actually loads. stbc.exe and scripts/
# are deliberately absent: neither is read at runtime (scripts/ is only
# tools/setup.py's instrumentation target), so requiring them would reject a
# perfectly usable content-only copy.
GAME_MARKERS: tuple[str, ...] = ("data", "data/Models", "data/Textures", "data/Icons")
SDK_MARKERS: tuple[str, ...] = ("Build/scripts/App.py", "Build/Data/TGL")

_MARKERS = {"game": GAME_MARKERS, "sdk": SDK_MARKERS}
_LABEL = {"game": "game", "sdk": "SDK"}


@dataclass(frozen=True)
class Validation:
    """The verdict on one candidate root.

    `missing` lists the markers that were absent, in declaration order.
    `hint` is a specific diagnosis of a recognisable mistake, or None.
    """
    ok: bool
    root: Path
    missing: tuple[str, ...]
    hint: Optional[str]


def normalise(path) -> Path:
    """expanduser -> abspath -> normpath. Deliberately NOT Path.resolve().

    Symlinks are not followed: an install behind a symlink to an external
    volume keeps working across remounts, where a resolved target would not.
    """
    return Path(os.path.normpath(os.path.abspath(os.path.expanduser(str(path)))))


def _markers_ok(root: Path, markers: tuple[str, ...]) -> bool:
    return all((root / m).exists() for m in markers)


def _case_insensitive_spelling(root: Path, rel: str) -> Optional[str]:
    """The real on-disk spelling of `rel` under `root`, matched case-blind.

    Returns None when no case-blind match exists. On a case-INSENSITIVE
    filesystem this is never reached, because the exact check already
    succeeded.
    """
    current = root
    found: list[str] = []
    for segment in rel.split("/"):
        try:
            entries = list(current.iterdir())
        except OSError:
            return None
        match = next((e for e in entries if e.name.lower() == segment.lower()), None)
        if match is None:
            return None
        found.append(match.name)
        current = match
    return "/".join(found)


def _hint_for(root: Path, kind: str, missing: tuple[str, ...]) -> Optional[str]:
    """Diagnose the mistakes a person actually makes. Order matters: the
    case hint is unambiguous when it fires, so it wins."""
    # Case only — every missing marker has a case-blind match on disk.
    spellings = {m: _case_insensitive_spelling(root, m) for m in missing}
    if missing and all(spellings.values()):
        m = missing[0]
        return f"found '{spellings[m]}', expected '{m}' — this volume is case-sensitive"

    # The parent was picked: this folder CONTAINS a valid game/ or sdk/.
    child = root / kind
    if child.is_dir() and _markers_ok(child, _MARKERS[kind]):
        return f"That folder contains '{kind}' — did you mean {child}?"

    # Swapped: it validates as the OTHER root.
    other = "sdk" if kind == "game" else "game"
    if _markers_ok(root, _MARKERS[other]):
        return (f"That's the {_LABEL[other]} folder; "
                f"it belongs in the {_LABEL[other]} field.")

    # One level too deep: the parent is the root that was wanted.
    parent = root.parent
    if parent != root and _markers_ok(parent, _MARKERS[kind]):
        return f"That's the {root.name} folder — pick its parent ({parent})."

    return None


def _validate(path, kind: str) -> Validation:
    root = normalise(path)
    markers = _MARKERS[kind]
    missing = tuple(m for m in markers if not (root / m).exists())
    if not missing:
        return Validation(ok=True, root=root, missing=(), hint=None)
    return Validation(ok=False, root=root, missing=missing,
                      hint=_hint_for(root, kind, missing))


def validate_game_root(path) -> Validation:
    """Is `path` a usable BC game install? Six stat calls, no writes."""
    return _validate(path, "game")


def validate_sdk_root(path) -> Validation:
    """Is `path` a usable BC SDK tree? Six stat calls, no writes."""
    return _validate(path, "sdk")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_paths_validate.py -q`
Expected: PASS, 11 tests.

- [ ] **Step 6: Commit**

```bash
git add engine/paths.py tests/unit/test_paths_validate.py tests/conftest.py
git commit -m "feat(paths): validate a candidate BC game or sdk root

Six stat calls against the markers the engine actually loads, plus a
diagnosis of the four recognisable mistakes: picking the parent, swapping
the two roots, picking one level too deep, and a case-sensitive volume.

stbc.exe and scripts/ are deliberately not markers -- neither is read at
runtime, so requiring them would reject a content-only copy.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `engine/paths.py` — resolution, cache, and failure text

**Files:**
- Modify: `engine/paths.py`
- Modify: `engine/__init__.py`
- Create: `tests/unit/test_paths_resolve.py`

**Interfaces:**
- Consumes: `Validation`, `validate_game_root`, `validate_sdk_root`, `normalise`, `GAME_MARKERS`, `SDK_MARKERS` from Task 1.
- Produces:
  - `class PathsUnresolved(RuntimeError)`
  - `@dataclass(frozen=True) Resolution` with fields `game: Path | None`, `sdk: Path | None`, `game_source: str`, `sdk_source: str`, `game_validation: Validation | None`, `sdk_validation: Validation | None`, and property `ok: bool`
  - `resolve(argv=None, env=None, store=None) -> Resolution` — pure, no writes
  - `configure(resolution: Resolution) -> None`
  - `current() -> Resolution`
  - `game_root() -> Path`, `sdk_root() -> Path`, `sdk_scripts() -> Path`, `sdk_data() -> Path`, `game_asset(rel) -> Path`
  - `persist(resolution, store=None) -> None`
  - `describe_failure(resolution) -> str`
  - `CLI_FLAGS: dict[str, str]`, `ENV_VARS: dict[str, str]`

- [ ] **Step 0: Put `build/python` on `sys.path` in `engine/__init__.py`**

`resolve()` reads `settings.json`, so it imports `engine.settings_store`,
which imports `engine.dev_mode`, which does a bare `import _dauntless_host`.
That module lives in `build/python/` and **only `tests/conftest.py` puts it on
the path**. Without this step every migrated `tools/` script (Task 5) dies
with `ModuleNotFoundError: No module named '_dauntless_host'` — a confusing
error that says nothing about paths. Verified:

```
$ uv run python -c "from engine.settings_store import SettingsStore"
ModuleNotFoundError: No module named '_dauntless_host'
```

`engine/__init__.py`'s docstring already claims this job — *"Importing this
package prepares the process to load the `_dauntless_host` extension
module"* — but it only does the Windows DLL-directory half. Complete it by
adding, after the existing `if sys.platform == "win32":` block:

```python
# The extension itself lives in build/python/. Under build/dauntless it is a
# built-in (registered via PyImport_AppendInittab before Py_Initialize), and
# under pytest tests/conftest.py adds this directory -- but a bare
# `uv run python tools/foo.py` has neither, and engine.settings_store imports
# it transitively through engine.dev_mode. Built-ins still win over sys.path,
# so this is inert in the host binary.
_build_python = Path(__file__).resolve().parent.parent / "build" / "python"
if _build_python.is_dir() and str(_build_python) not in sys.path:
    sys.path.insert(0, str(_build_python))
```

Verify: `uv run python -c "from engine.settings_store import SettingsStore; print('ok')"`
Expected: `ok`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_paths_resolve.py`:

```python
"""Resolution precedence, caching, and the failure message.

`resolve()` is pure — it takes argv, env and the store explicitly, writes
nothing, and touches no global. Every test drives it directly.
"""
import json
from pathlib import Path

import pytest

from engine import paths
from engine.settings_store import SettingsStore

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _isolate_cache():
    """paths caches a Resolution in a module global.

    Save and RESTORE rather than clearing: tests/conftest.py configures the
    session's real resolution at import, and leaving None behind would make
    every later test file re-resolve from ambient state.
    """
    saved = paths._RESOLUTION
    paths.configure(None)
    yield
    paths.configure(saved)


def _store_with(tmp_path, **kv):
    store = SettingsStore(tmp_path / "settings.json")
    store.load()
    for k, v in kv.items():
        store.set("paths", k, str(v))
    return store


# --- precedence -------------------------------------------------------------

def test_cli_flag_wins(fake_bc_install, tmp_path):
    game, sdk = fake_bc_install
    store = _store_with(tmp_path, game="/nowhere", sdk="/nowhere")
    res = paths.resolve(
        argv=["--game-dir", str(game), "--sdk-dir", str(sdk)],
        env={"DAUNTLESS_GAME_DIR": "/also-nowhere"},
        store=store,
    )
    assert res.game == game
    assert res.game_source == "cli"
    assert res.sdk_source == "cli"


def test_cli_flag_accepts_equals_form(fake_bc_install):
    game, _sdk = fake_bc_install
    res = paths.resolve(argv=[f"--game-dir={game}"], env={}, store=None)
    assert res.game == game
    assert res.game_source == "cli"


def test_env_beats_settings(fake_bc_install, tmp_path):
    game, sdk = fake_bc_install
    store = _store_with(tmp_path, game="/nowhere", sdk=str(sdk))
    res = paths.resolve(argv=[], env={"DAUNTLESS_GAME_DIR": str(game)}, store=store)
    assert res.game == game
    assert res.game_source == "env"
    assert res.sdk == sdk
    assert res.sdk_source == "settings"


def test_settings_beats_the_project_default(fake_bc_install, tmp_path):
    game, sdk = fake_bc_install
    store = _store_with(tmp_path, game=game, sdk=sdk)
    res = paths.resolve(argv=[], env={}, store=store)
    assert res.game == game
    assert res.game_source == "settings"


def test_the_two_roots_resolve_independently(fake_bc_install, tmp_path):
    game, sdk = fake_bc_install
    store = _store_with(tmp_path, sdk=sdk)
    res = paths.resolve(argv=["--game-dir", str(game)], env={}, store=store)
    assert res.game_source == "cli"
    assert res.sdk_source == "settings"


# --- the load-bearing precedence rule ---------------------------------------

def test_a_set_but_invalid_source_is_an_error_not_a_fallthrough(fake_bc_install, tmp_path):
    """--game-dir /typo must be reported, NOT silently replaced by a stale
    settings.json — that would run a different install than was asked for."""
    game, sdk = fake_bc_install
    store = _store_with(tmp_path, game=game, sdk=sdk)
    res = paths.resolve(argv=["--game-dir", "/definitely/not/here"], env={}, store=store)
    assert not res.ok
    assert res.game is None
    assert res.game_source == "cli"
    assert res.game_validation is not None
    assert not res.game_validation.ok
    assert str(res.game_validation.root) == "/definitely/not/here"


def test_an_absent_project_default_is_not_an_error(tmp_path, monkeypatch):
    """Source 4 is a fallback: its absence means 'nothing configured'."""
    monkeypatch.setattr(paths, "PROJECT_ROOT", tmp_path)
    res = paths.resolve(argv=[], env={}, store=_store_with(tmp_path))
    assert not res.ok
    assert res.game is None
    assert res.game_source == ""
    assert res.game_validation is None


def test_the_project_default_is_used_when_present(tmp_path, monkeypatch):
    for rel in ("game/data", "game/data/Models", "game/data/Textures", "game/data/Icons"):
        (tmp_path / rel).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(paths, "PROJECT_ROOT", tmp_path)
    res = paths.resolve(argv=[], env={}, store=_store_with(tmp_path))
    assert res.game == tmp_path / "game"
    assert res.game_source == "project"


# --- stored form ------------------------------------------------------------

def test_stored_paths_expand_user_and_normalise(fake_bc_install, tmp_path, monkeypatch):
    game, _sdk = fake_bc_install
    monkeypatch.setenv("HOME", str(game.parent))
    res = paths.resolve(argv=["--game-dir", "~/game/../game"], env={}, store=None)
    assert res.game == game


def test_symlinks_are_not_followed(fake_bc_install, tmp_path):
    game, _sdk = fake_bc_install
    link = tmp_path / "via-link"
    link.symlink_to(game, target_is_directory=True)
    res = paths.resolve(argv=["--game-dir", str(link)], env={}, store=None)
    assert res.game == link
    assert res.game != game


# --- persistence ------------------------------------------------------------

def test_persist_writes_only_cli_sourced_roots(fake_bc_install, tmp_path):
    game, sdk = fake_bc_install
    store = _store_with(tmp_path, sdk=sdk)
    res = paths.resolve(argv=["--game-dir", str(game)], env={}, store=store)
    paths.persist(res, store)
    doc = json.loads((tmp_path / "settings.json").read_text())
    assert doc["paths"]["game"] == str(game)


def test_persist_never_writes_an_env_sourced_root(fake_bc_install, tmp_path):
    """DAUNTLESS_SDK_DIR=/fixtures pytest must not mutate a real config."""
    game, sdk = fake_bc_install
    store = _store_with(tmp_path)
    res = paths.resolve(argv=[], env={"DAUNTLESS_GAME_DIR": str(game),
                                     "DAUNTLESS_SDK_DIR": str(sdk)}, store=store)
    paths.persist(res, store)
    # The store is write-through: with nothing to persist the file is never
    # created at all, which is itself the assertion.
    settings = tmp_path / "settings.json"
    doc = json.loads(settings.read_text()) if settings.exists() else {}
    assert doc.get("paths", {}) == {}


def test_persist_never_writes_an_invalid_path(tmp_path):
    store = _store_with(tmp_path)
    res = paths.resolve(argv=["--game-dir", "/typo"], env={}, store=store)
    paths.persist(res, store)
    settings = tmp_path / "settings.json"
    doc = json.loads(settings.read_text()) if settings.exists() else {}
    assert "game" not in doc.get("paths", {})


def test_resolve_itself_writes_nothing(fake_bc_install, tmp_path):
    game, _sdk = fake_bc_install
    settings = tmp_path / "settings.json"
    store = _store_with(tmp_path)
    before = settings.read_text() if settings.exists() else None
    paths.resolve(argv=["--game-dir", str(game)], env={}, store=store)
    after = settings.read_text() if settings.exists() else None
    assert after == before


# --- cache and accessors ----------------------------------------------------

def test_accessors_read_the_configured_resolution(fake_bc_install):
    game, sdk = fake_bc_install
    paths.configure(paths.resolve(argv=["--game-dir", str(game),
                                        "--sdk-dir", str(sdk)], env={}, store=None))
    assert paths.game_root() == game
    assert paths.sdk_root() == sdk
    assert paths.sdk_scripts() == sdk / "Build" / "scripts"
    assert paths.sdk_data() == sdk / "Build" / "Data"
    assert paths.game_asset("data/rough.tga") == game / "data" / "rough.tga"


def test_game_asset_accepts_a_path_as_well_as_a_string(fake_bc_install):
    from pathlib import Path
    game, sdk = fake_bc_install
    paths.configure(paths.resolve(argv=["--game-dir", str(game),
                                        "--sdk-dir", str(sdk)], env={}, store=None))
    assert paths.game_asset(Path("data") / "rough.tga") == game / "data" / "rough.tga"


def test_an_unresolved_root_raises_with_the_diagnosis(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "PROJECT_ROOT", tmp_path)
    paths.configure(paths.resolve(argv=[], env={}, store=_store_with(tmp_path)))
    with pytest.raises(paths.PathsUnresolved) as exc:
        paths.game_root()
    assert "cannot locate your Bridge Commander install" in str(exc.value)


# --- the failure message ----------------------------------------------------

def test_describe_failure_names_every_source_it_consulted(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "PROJECT_ROOT", tmp_path)
    res = paths.resolve(argv=[], env={}, store=_store_with(tmp_path))
    text = paths.describe_failure(res)
    assert "--game-dir" in text
    assert "DAUNTLESS_GAME_DIR" in text
    assert "settings.json" in text
    assert "--sdk-dir" in text
    assert "DAUNTLESS_SDK_DIR" in text


def test_describe_failure_reports_missing_markers_and_the_hint(fake_bc_install, tmp_path):
    game, sdk = fake_bc_install
    res = paths.resolve(argv=["--game-dir", str(game.parent),
                              "--sdk-dir", str(sdk)], env={}, store=None)
    text = paths.describe_failure(res)
    assert "data/Models" in text
    assert "contains 'game'" in text
    assert str(game) in text


def test_describe_failure_is_empty_for_a_good_resolution(fake_bc_install):
    game, sdk = fake_bc_install
    res = paths.resolve(argv=["--game-dir", str(game),
                              "--sdk-dir", str(sdk)], env={}, store=None)
    assert res.ok
    assert paths.describe_failure(res) == ""


def test_resolve_works_without_conftest_on_the_path(tmp_path):
    """A bare `uv run python tools/foo.py` must reach settings.json.

    resolve() -> settings_store -> dev_mode -> `import _dauntless_host`, which
    lives in build/python/. Only conftest used to add that directory, so every
    tools/ script would have died with ModuleNotFoundError instead of a path
    error. engine/__init__ now completes the job its docstring claims.
    """
    import subprocess
    import sys as _sys
    result = subprocess.run(
        [_sys.executable, "-c",
         "import sys; sys.path[:] = [p for p in sys.path if 'build/python' not in p];"
         "from engine import paths; print(paths.resolve(argv=[], env={}).game_source)"],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_paths_resolve.py -q`
Expected: FAIL — `AttributeError: module 'engine.paths' has no attribute 'configure'`

- [ ] **Step 3: Append resolution to `engine/paths.py`**

Add to `engine/paths.py`, after the validation section:

```python
# --- resolution -------------------------------------------------------------

# engine/paths.py -> engine/ -> <project root>. Kept as a module attribute
# rather than a local so tests can point the legacy fallback at a tmp_path.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

CLI_FLAGS = {"game": "--game-dir", "sdk": "--sdk-dir"}
ENV_VARS = {"game": "DAUNTLESS_GAME_DIR", "sdk": "DAUNTLESS_SDK_DIR"}
_PROJECT_DIR = {"game": "game", "sdk": "sdk"}
_VALIDATORS = {"game": validate_game_root, "sdk": validate_sdk_root}


class PathsUnresolved(RuntimeError):
    """No usable root for a requested half. Carries describe_failure()'s text.

    Not meant to be handled: it is a boot-time configuration error and the
    message is the whole point.
    """


@dataclass(frozen=True)
class Resolution:
    """The outcome of one resolve(). `game`/`sdk` are set ONLY when valid.

    An invalid candidate leaves the root None and records the attempt in the
    matching Validation, so describe_failure() can name the path and say what
    was wrong with it.
    """
    game: Optional[Path]
    sdk: Optional[Path]
    game_source: str            # "cli" | "env" | "settings" | "project" | ""
    sdk_source: str
    game_validation: Optional[Validation]
    sdk_validation: Optional[Validation]

    @property
    def ok(self) -> bool:
        return self.game is not None and self.sdk is not None

    def source(self, kind: str) -> str:
        return self.game_source if kind == "game" else self.sdk_source

    def validation(self, kind: str) -> Optional[Validation]:
        return self.game_validation if kind == "game" else self.sdk_validation


def _flag_value(argv, flag: str) -> Optional[str]:
    """Support both `--game-dir X` and `--game-dir=X`."""
    for i, token in enumerate(argv):
        if token == flag:
            return argv[i + 1] if i + 1 < len(argv) else ""
        if token.startswith(flag + "="):
            return token[len(flag) + 1:]
    return None


def _candidate(kind: str, argv, env, store):
    """The highest-precedence SET source for one root, as (value, source).

    Returns (None, "") when nothing is set. A set-but-wrong source is
    returned as-is and never skipped in favour of a lower one -- falling
    through would run a different install than the one that was asked for.
    """
    flag = _flag_value(argv, CLI_FLAGS[kind])
    if flag:
        return flag, "cli"

    from_env = env.get(ENV_VARS[kind])
    if from_env:
        return from_env, "env"

    if store is not None and store.has("paths", kind):
        stored = store.get("paths", kind)
        if stored:
            return stored, "settings"

    project = PROJECT_ROOT / _PROJECT_DIR[kind]
    if project.is_dir():
        return str(project), "project"

    return None, ""


def resolve(argv=None, env=None, store=None) -> Resolution:
    """Resolve both roots. PURE: no globals, no writes, no ambient state
    beyond the defaults for argv/env/store.

    settings_store is imported HERE rather than at module scope: it imports
    engine.ui.configuration_panel, and this module is imported by
    engine/audio/ and engine/appc/.
    """
    import sys

    if argv is None:
        argv = sys.argv[1:]
    if env is None:
        env = os.environ
    if store is None:
        from engine.settings_store import SettingsStore
        store = SettingsStore()
        store.load()

    roots: dict = {}
    sources: dict = {}
    validations: dict = {}
    for kind in ("game", "sdk"):
        value, source = _candidate(kind, argv, env, store)
        sources[kind] = source
        if value is None:
            roots[kind] = None
            validations[kind] = None
            continue
        verdict = _VALIDATORS[kind](value)
        validations[kind] = verdict
        roots[kind] = verdict.root if verdict.ok else None

    return Resolution(
        game=roots["game"], sdk=roots["sdk"],
        game_source=sources["game"], sdk_source=sources["sdk"],
        game_validation=validations["game"], sdk_validation=validations["sdk"],
    )


def persist(resolution: Resolution, store=None) -> None:
    """Write CLI-sourced roots to settings.json [paths].

    Only CLI, and only when valid. An env var is ephemeral by contract, so
    `DAUNTLESS_SDK_DIR=/fixtures pytest` cannot mutate a real config; and a
    typo never becomes the stored answer, which would make the NEXT launch
    fail for a reason the player has already forgotten about.
    """
    if store is None:
        from engine.settings_store import SettingsStore
        store = SettingsStore()
        store.load()
    for kind in ("game", "sdk"):
        root = resolution.game if kind == "game" else resolution.sdk
        if root is not None and resolution.source(kind) == "cli":
            store.set("paths", kind, str(root))


# --- the cache --------------------------------------------------------------

_RESOLUTION: Optional[Resolution] = None


def configure(resolution: Optional[Resolution]) -> None:
    """Install a Resolution as the answer every accessor reads.

    Callable more than once, and later calls are observed by every consumer:
    that is what the first-run picker needs, and it is why nothing may capture
    a path at import. Pass None to clear (tests).
    """
    global _RESOLUTION
    _RESOLUTION = resolution


def current() -> Resolution:
    """The configured Resolution, resolving from ambient state if configure()
    has not run. The lazy path keeps a tools/ script or an isolated test
    working without a boot sequence."""
    global _RESOLUTION
    if _RESOLUTION is None:
        _RESOLUTION = resolve()
    return _RESOLUTION


def _root(kind: str) -> Path:
    resolution = current()
    root = resolution.game if kind == "game" else resolution.sdk
    if root is None:
        raise PathsUnresolved(describe_failure(resolution))
    return root


def game_root() -> Path:
    """The BC game install root. Never captured at module scope."""
    return _root("game")


def sdk_root() -> Path:
    """The BC SDK root. Never captured at module scope."""
    return _root("sdk")


def sdk_scripts() -> Path:
    """sdk_root()/Build/scripts — where the SDK's Python modules live."""
    return sdk_root() / "Build" / "scripts"


def sdk_data() -> Path:
    """sdk_root()/Build/Data — TGL string tables and friends."""
    return sdk_root() / "Build" / "Data"


def game_asset(rel) -> Path:
    """Absolutise a BC-relative asset path, e.g. "data/Textures/x.tga"."""
    return game_root() / rel


# --- the failure message ----------------------------------------------------

def describe_failure(resolution: Resolution) -> str:
    """Every source consulted and what each said. Empty when nothing failed."""
    if resolution.ok:
        return ""

    lines = ["dauntless: cannot locate your Bridge Commander install.", ""]
    for kind, label in (("game", "game folder"), ("sdk", "sdk folder ")):
        root = resolution.game if kind == "game" else resolution.sdk
        if root is not None:
            lines.append(f"  {label}: {root}")
            lines.append("")
            continue

        verdict = resolution.validation(kind)
        if verdict is None:
            lines.append(f"  {label}: not found")
            lines.append(f"     {CLI_FLAGS[kind]:<18}(not given)")
            lines.append(f"     {ENV_VARS[kind]:<18}(not set)")
            lines.append(f"     {'settings.json':<18}(not set)")
            project = PROJECT_ROOT / _PROJECT_DIR[kind]
            lines.append(f"     {str(project):<18}(does not exist)")
        else:
            lines.append(f"  {label}: invalid — {verdict.root}")
            lines.append(f"     missing: {', '.join(verdict.missing)}")
            lines.append(f"     source : {resolution.source(kind)}")
            if verdict.hint:
                lines.append(f"     hint   : {verdict.hint}")
        lines.append("")

    lines += [
        "Set them once and they persist:",
        "",
        "  ./build/dauntless \\",
        '      --game-dir "/path/to/Star Trek Bridge Commander/game" \\',
        '      --sdk-dir  "/path/to/Star Trek Bridge Commander/sdk"',
        "",
    ]
    return "\n".join(lines)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_paths_resolve.py tests/unit/test_paths_validate.py -q`
Expected: PASS, 32 tests.

- [ ] **Step 5: Commit**

```bash
git add engine/paths.py engine/__init__.py tests/unit/test_paths_resolve.py
git commit -m "feat(paths): resolve both BC roots from four sources

Precedence: CLI flag, env var, settings.json [paths], the legacy
in-project layout. The highest SET source wins even when invalid --
falling through to a lower one would silently run a different install
than the one that was asked for.

A CLI flag persists and an env var never does, so
DAUNTLESS_SDK_DIR=/fixtures pytest cannot mutate a real config. Only a
valid path persists.

configure() is callable more than once and later calls are observed by
every accessor: that is what the first-run picker will need.

engine/__init__ now puts build/python on sys.path, completing the job its
docstring already claimed. resolve() reaches settings_store, which imports
_dauntless_host transitively, and only conftest used to make that
importable -- so every tools/ script would have failed with
ModuleNotFoundError rather than anything about paths.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: The two SDK finders — restore the gate

**Files:**
- Modify: `tests/conftest.py:16-17` and its 13 `SDK_SCRIPTS` uses
- Modify: `tools/mission_harness.py:29` and its 6 `SDK_SCRIPTS` uses

**Interfaces:**
- Consumes: `paths.sdk_scripts()`, `paths.PathsUnresolved`, `paths.describe_failure`, `paths.resolve` from Task 2.
- Produces: nothing new. After this task `scripts/check_tests.sh` collects and runs.

**Why `mission_harness` is not exempt from the no-capture rule:** it is
imported and called at runtime by `engine/host_loop.py:3507`
(`mission_harness.setup_sdk()`), so a module-level `SDK_SCRIPTS` would be
captured before the first-run picker could change it. `tests/conftest.py` *is*
exempt — it never runs under the picker.

- [ ] **Step 1: Point this machine's `settings.json` at the moved install**

The roots must be configured before any test that imports an SDK module can
run. `settings.json` is git-ignored and local, and its `paths` section is
already reserved by `engine/settings_store.py`.

```bash
uv run python -c "
from engine.settings_store import SettingsStore
s = SettingsStore(); s.load()
s.set('paths', 'game', '/Users/mward/Documents/Star Trek Bridge Commander/game')
s.set('paths', 'sdk',  '/Users/mward/Documents/Star Trek Bridge Commander/sdk')
print(open('settings.json').read())
"
```

Expected: the printed JSON contains a `"paths"` object with both keys.
This file is git-ignored — do not stage it.

- [ ] **Step 2: Write the failing test**

Append to `tests/unit/test_paths_resolve.py`:

```python
def test_the_live_sdk_finder_has_no_module_level_path_constant():
    """tools/mission_harness is imported at runtime by host_loop, so a
    captured path would be stale by the time the picker changes it."""
    import tools.mission_harness as mh
    assert not hasattr(mh, "SDK_SCRIPTS"), (
        "mission_harness.SDK_SCRIPTS captures a path at import; it must call "
        "engine.paths.sdk_scripts() at point of use instead"
    )
```

- [ ] **Step 3: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_paths_resolve.py::test_the_live_sdk_finder_has_no_module_level_path_constant -q`
Expected: FAIL — `assert not hasattr(mh, "SDK_SCRIPTS")`

- [ ] **Step 4: Rewrite `tools/mission_harness.py`**

Delete line 29 (`SDK_SCRIPTS = _PROJECT_ROOT / "sdk" / "Build" / "scripts"`) and
add, just below the `sys.path` block at lines 25-27:

```python
def _sdk_scripts():
    """The SDK's script root, resolved at USE.

    Deliberately not a module-level constant: host_loop.py:3507 imports this
    module at runtime, so a captured path would be stale the moment the
    first-run picker changed it.
    """
    from engine import paths
    return paths.sdk_scripts()
```

Replace every remaining `SDK_SCRIPTS` in the file with a local bound at the
top of its function. The six sites are lines 60, 69, 364, 456, and the two in
`_SDKFinder.find_spec`. For example, at line 60:

```python
    sdk_scripts = _sdk_scripts()
    for py_file in sorted(sdk_scripts.rglob("*.py")):
```

and inside `_SDKFinder.find_spec`, bind once at the top of the method:

```python
    def find_spec(self, fullname, path, target=None):
        sdk_scripts = _sdk_scripts()
        rel = fullname.replace(".", "/")
```

- [ ] **Step 5: Rewrite `tests/conftest.py`'s SDK root**

Replace line 17 (`SDK_SCRIPTS = PROJECT_ROOT / "sdk" / "Build" / "scripts"`) with:

```python
# Resolved once per pytest session. conftest is exempt from the
# resolve-at-use rule in engine/paths.py: the test suite never runs under the
# first-run picker, so nothing can change these roots mid-session.
#
# This FAILS FAST rather than skipping. Skipping would turn a missing install
# into ~800 silent skips, and scripts/check_tests.sh diffs FAILURES against
# tests/known_failures.txt -- a mass-skip would pass the gate green while
# testing nothing.
from engine import paths as _paths

_RESOLUTION = _paths.resolve()
_paths.configure(_RESOLUTION)
if not _RESOLUTION.ok:
    raise RuntimeError(
        _paths.describe_failure(_RESOLUTION)
        + "\nThe test suite needs both roots. Set them with:\n"
        '  uv run python -c "from engine.settings_store import SettingsStore; '
        "s=SettingsStore(); s.load(); s.set('paths','game','/path/to/game'); "
        "s.set('paths','sdk','/path/to/sdk')\"\n"
    )

SDK_SCRIPTS = _paths.sdk_scripts()
```

The 13 existing `SDK_SCRIPTS` uses at lines 384, 476, 483, 498, 502, 511, 524,
532, 539, 573, 580, 619 and 641 are unchanged.

- [ ] **Step 6: Run the full gate**

Run: `scripts/check_tests.sh`
Expected: collection succeeds (the 18 errors are gone) and the run reports
`OK — no new failures. 1 known failure(s) still baselined.`

If any test fails that is not in `tests/known_failures.txt`, that is a
regression from this task — fix it before committing.

- [ ] **Step 7: Commit**

```bash
git add tools/mission_harness.py tests/conftest.py tests/unit/test_paths_resolve.py
git commit -m "refactor(paths): both SDK finders resolve through engine.paths

Restores the gate, which could not collect with sdk/ outside the project
tree.

mission_harness resolves at USE, not import: host_loop.py:3507 imports it
at runtime, so a captured path would be stale the moment the first-run
picker changed it. conftest is exempt -- the suite never runs under the
picker -- but it now FAILS FAST rather than skipping, because ~800 silent
skips would sail through a gate that diffs failures.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Migrate the 36 `engine/` sites

**Files:**
- Modify (19 sites): `engine/host_loop.py` lines 1070, 1886, 4094, 4140, 4212, 4213, 4214, 4621, 5241, 5614, 5617, 5624, 5660, 5662, 5663, 5875, 5883, 5986, 7157
- Modify (3 sites): `engine/appc/backdrops.py` lines 150 (docstring), 162, 171
- Modify (2 sites): `engine/appc/planet.py` lines 172, 185
- Modify (2 sites): `engine/appc/lens_flare.py` lines 56 (docstring), 64
- Modify (2 sites): `engine/appc/localization.py` lines 43, 50
- Modify (2 sites): `engine/missions/name_resolver.py` lines 15-19
- Modify (1 site each): `engine/lip_sync_runtime.py:54`, `engine/ui/weapon_icons.py:77`, `engine/ui/ship_icons.py:39`, `engine/ui/damage_icons.py:35`, `engine/appc/viewscreen_static.py:22`, `engine/appc/bridge_set.py:21`, `engine/dev_keybindings.py:20`, `engine/audio/tg_sound.py:20-28`
- Modify: `tests/audio/test_loadbridge_loadsounds.py:47`
- Modify: `tests/unit/test_appc_suns.py`, `tests/unit/test_aggregate_backdrops.py`, `tests/unit/test_lens_flare.py`, `tests/engine/appc/test_backdrops_procedural.py` (aggregator signature change)
- Create: `tests/unit/test_paths_late_reconfigure.py`

**Interfaces:**
- Consumes: `paths.game_asset(rel)`, `paths.game_root()`, `paths.sdk_root()`, `paths.sdk_data()`, `paths.sdk_scripts()`, `paths.configure()` from Task 2.
- Produces: three changed signatures —
  - `engine.appc.backdrops.aggregate_for_renderer(pSet, game_root)` (was `project_root`)
  - `engine.appc.planet.aggregate_suns_for_renderer(game_root, pSets)` (was `project_root`)
  - `engine.appc.lens_flare.aggregate_lens_flares_for_renderer(game_root, pSets)` (was `project_root`)

  Each now receives the **game root itself**; the internal `/ "game"` join is gone. `host_loop` passes `paths.game_root()`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_paths_late_reconfigure.py`:

```python
"""configure() twice must be observed by every consumer.

This is the guard for the rule that makes a first-run picker possible: the
picker runs AFTER CEF is up, so any module that captured a path at import
would still be pointing at the old install when the player picks a folder.

It is deliberately behavioural rather than structural -- the AST guard in
test_path_indirection.py checks the shape, this checks the effect.
"""
import importlib

import pytest

from engine import paths


@pytest.fixture(autouse=True)
def _restore_cache():
    before = paths.current() if paths._RESOLUTION is not None else None
    yield
    paths.configure(before)


def _point_at(root_pair):
    game, sdk = root_pair
    paths.configure(paths.resolve(
        argv=["--game-dir", str(game), "--sdk-dir", str(sdk)], env={}, store=None))


def _second_install(game):
    other = game.parent / "other-install"
    for rel in ("data", "data/Models", "data/Textures", "data/Icons"):
        (other / rel).mkdir(parents=True, exist_ok=True)
    return other


# Every engine/ site that used to be a module-level constant. All eight are
# listed in the spec's "import-time trap" section; these are the seven with a
# reachable accessor (bridge_set's is exercised via test_paths_resolve).
CONSUMERS = [
    ("engine.ui.weapon_icons", "_game_icons_dir"),
    ("engine.ui.ship_icons", "_game_icons_dir"),
    ("engine.ui.damage_icons", "_damage_dir"),
    ("engine.dev_keybindings", "_test_character_nif"),
]


@pytest.mark.parametrize("module_name,func_name", CONSUMERS)
def test_path_accessors_follow_a_later_configure(fake_bc_install, module_name, func_name):
    game, sdk = fake_bc_install
    module = importlib.import_module(module_name)
    _point_at((game, sdk))
    first = str(getattr(module, func_name)())
    assert str(game) in first

    other = _second_install(game)
    _point_at((other, sdk))
    second = str(getattr(module, func_name)())
    assert str(other) in second
    assert first != second


def test_tgl_roots_follow_a_later_configure(fake_bc_install):
    """name_resolver held BOTH roots in one module-level tuple."""
    from engine.missions import name_resolver
    game, sdk = fake_bc_install
    _point_at((game, sdk))
    assert [str(r) for r in name_resolver._tgl_roots()] == [
        str(sdk / "Build" / "Data" / "TGL"), str(game / "data" / "TGL")]

    other = _second_install(game)
    _point_at((other, sdk))
    assert str(other / "data" / "TGL") in [str(r) for r in name_resolver._tgl_roots()]


def test_tg_sound_follows_a_later_configure(fake_bc_install):
    from engine.audio import tg_sound
    game, sdk = fake_bc_install
    _point_at((game, sdk))
    assert str(game) in tg_sound._resolve_sfx_path("sfx/x.wav")

    other = _second_install(game)
    _point_at((other, sdk))
    assert str(other) in tg_sound._resolve_sfx_path("sfx/x.wav")


def test_no_engine_module_kept_the_old_env_var():
    """OPEN_STBC_GAME_DIR was a second env var doing engine.paths' job."""
    from engine.audio import tg_sound
    assert not hasattr(tg_sound, "_GAME_DIR_ENV")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_paths_late_reconfigure.py -q`
Expected: FAIL — `AttributeError: module 'engine.ui.weapon_icons' has no
attribute '_game_icons_dir'` (the modules still hold module-level constants).

- [ ] **Step 3: Convert the eight module-level constants to functions**

`engine/ui/weapon_icons.py` — delete line 77, add:

```python
def _game_icons_dir():
    """Resolved at USE: a module-level constant would be captured at import,
    before the first-run picker can change the root."""
    from engine import paths
    return str(paths.game_asset("data/Icons"))
```

Replace each use of `_GAME_ICONS_DIR` in the file with `_game_icons_dir()`.

`engine/ui/ship_icons.py` — delete line 39, add the same function returning
`str(paths.game_asset("data/Icons/Ships"))`; replace its uses.

`engine/ui/damage_icons.py` — delete line 35, add `_damage_dir()` returning
`str(paths.game_asset("data/Icons/Damage"))`; replace its uses.

`engine/lip_sync_runtime.py` — delete line 54 (`_GAME_DIR = ...`) and change
line 65 from `return str(_GAME_DIR / wav)` to:

```python
    from engine import paths
    return str(paths.game_asset(wav))
```

`engine/appc/viewscreen_static.py` — delete line 22 and change line 35 from
`base = _GAME_ROOT / "data" / "Textures" / "Effects"` to:

```python
    from engine import paths
    base = paths.game_asset("data/Textures/Effects")
```

`engine/appc/bridge_set.py` — delete line 21; change line 155 from
`return str(_GAME_ROOT / rel)` and line 701 from `nif_abs = str(_GAME_ROOT / path)`
to use `paths.game_asset(rel)` / `paths.game_asset(path)`, importing `paths`
inside each function.

`engine/dev_keybindings.py` — delete lines 19-28 (`_PROJECT_ROOT` and the
nine-line `_TEST_CHARACTER_NIF`) and add:

```python
def _test_character_nif():
    """Resolved at USE. This one was invisible to a line-oriented grep: the
    constant spanned nine lines, so no single line contained both the root and
    the "game" segment."""
    from engine import paths
    return str(paths.game_asset(
        "data/Models/Characters/Bodies/BodyMaleL/BodyMaleL.NIF"))
```

Replace every use of `_TEST_CHARACTER_NIF` with `_test_character_nif()`.

`engine/missions/name_resolver.py` — delete lines 15-19 (`PROJECT_ROOT` and
`TGL_ROOTS`) and add:

```python
def _tgl_roots() -> tuple[Path, ...]:
    """Both TGL sources, resolved at USE. Was a module-level tuple holding
    BOTH roots -- the single densest instance of the capture-at-import trap."""
    from engine import paths
    return (paths.sdk_data() / "TGL", paths.game_asset("data/TGL"))
```

Replace every `TGL_ROOTS` use with `_tgl_roots()`.

- [ ] **Step 4: Remove the rival env var from `tg_sound.py`**

Replace lines 20-28 of `engine/audio/tg_sound.py`:

```python
def _resolve_sfx_path(rel: str) -> str:
    """Absolutise a BC-relative sound path.

    OPEN_STBC_GAME_DIR lived here: a second env var doing engine.paths' job
    under a different name, with its own project-relative fallback. Point
    DAUNTLESS_GAME_DIR at a fixture instead.
    """
    from engine import paths
    return str(paths.game_asset(rel))
```

Update `tests/audio/test_loadbridge_loadsounds.py:47` from
`monkeypatch.setenv("OPEN_STBC_GAME_DIR", str(tmp_path))` to:

```python
    monkeypatch.setenv("DAUNTLESS_GAME_DIR", str(tmp_path))
    for rel in ("data", "data/Models", "data/Textures", "data/Icons"):
        (tmp_path / rel).mkdir(parents=True, exist_ok=True)
    from engine import paths
    paths.configure(paths.resolve(argv=[], store=None))
```

- [ ] **Step 5: Change the three aggregator signatures**

`engine/appc/backdrops.py:126` — rename the parameter and drop the join:

```python
def aggregate_for_renderer(pSet, game_root):
```

At line 162, `abs_path = (project_root / "game" / b._texture_path).resolve()`
becomes `abs_path = (game_root / b._texture_path).resolve()`. At line 171,
`lod_path = (project_root / "game" /` becomes `lod_path = (game_root /`.
Update the line-150 docstring: `exist under project_root/game/` →
`exist under the game root`.

`engine/appc/planet.py:140` — `def aggregate_suns_for_renderer(game_root, pSets):`;
lines 172 and 185 drop `/ "game"`.

`engine/appc/lens_flare.py:53` — `def aggregate_lens_flares_for_renderer(game_root, pSets) -> list:`;
delete line 64 (`game_root = project_root / "game"`) since the parameter now
holds it; update the line-56 docstring from
``Resolves texture paths against ``project_root / "game"``.`` to
``Resolves texture paths against the game root.``

Update the four calling test files. The transformation is uniform — the
argument gains `/ "game"`, and every file-setup line stays exactly as it is,
because the assets were always built under `<root>/game/`:

| File | Lines | Change |
|---|---|---|
| `tests/unit/test_appc_suns.py` | 41, 50, 62, 74, 85, 87, 97 | `aggregate_suns_for_renderer(PROJECT_ROOT, …)` → `(PROJECT_ROOT / "game", …)` |
| `tests/unit/test_appc_suns.py` | 114, 141, 160 | `aggregate_suns_for_renderer(tmp_path, …)` → `(tmp_path / "game", …)` |
| `tests/unit/test_aggregate_backdrops.py` | 13, 20, 34, 53, 72, 92, 108, 110, 122, 137, 154 | `aggregate_for_renderer(pSet, PROJECT_ROOT)` → `(pSet, PROJECT_ROOT / "game")` |
| `tests/unit/test_lens_flare.py` | 84, 110, 119, 125, 137, 149 | `aggregate_lens_flares_for_renderer(PROJECT_ROOT, …)` → `(PROJECT_ROOT / "game", …)` |
| `tests/engine/appc/test_backdrops_procedural.py` | 31, 48 | `bd.aggregate_for_renderer(_Set(…), tmp_path)` → `(_Set(…), tmp_path / "game")` |

Test files are exempt from the no-`"game"`-segment rule: they build fake
install trees, which is the one legitimate reason to spell the layout.

- [ ] **Step 6: Migrate the remaining `host_loop.py` and `localization.py` sites**

In `engine/host_loop.py`, add near the other engine imports:

```python
from engine import paths as _paths
```

Then apply the transformation `PROJECT_ROOT / "game" / X` → `_paths.game_asset(X)`
at lines 1070, 4094, 4140, 4212, 4213, 4214, 4621, 5241, 5614, 5617, 5624,
5660, 5662, 5663, 5875, 5883, 5986. Line 1886
(`return _resolve_asset_path(p, PROJECT_ROOT / "game")`) becomes
`return _resolve_asset_path(p, _paths.game_root())`. Line 7157
(`sdk_scripts = project_root / "sdk" / "Build" / "scripts"`) becomes
`sdk_scripts = _paths.sdk_scripts()`.

Lines 3907, 4083 and 4291 pass `PROJECT_ROOT` to the three renamed
aggregators; change each to `_paths.game_root()`.

In `engine/appc/localization.py`, line 43
(`candidates.append(_PROJECT_ROOT / "game" / filename)`) becomes
`candidates.append(paths.game_asset(filename))` and line 50
(`candidates.append(_PROJECT_ROOT / "sdk" / "Build" / sdk_path)`) becomes
`candidates.append(paths.sdk_root() / "Build" / sdk_path)`, with
`from engine import paths` inside the function.

- [ ] **Step 7: Run the reconfigure test and the full gate**

Run: `uv run pytest tests/unit/test_paths_late_reconfigure.py -q`
Expected: PASS, 7 tests (4 functions, one parametrized over 4 modules).

Run: `scripts/check_tests.sh`
Expected: `OK — no new failures. 1 known failure(s) still baselined.`

- [ ] **Step 8: Commit**

```bash
git add engine/ tests/unit/test_paths_late_reconfigure.py tests/audio/test_loadbridge_loadsounds.py tests/unit/test_appc_suns.py tests/unit/test_aggregate_backdrops.py tests/unit/test_lens_flare.py tests/engine/appc/test_backdrops_procedural.py
git commit -m "refactor(paths): engine/ resolves BC content through engine.paths

37 sites. Six module-level constants become functions -- the whole point
of the exercise, since a constant is captured at import and the first-run
picker runs after CEF is up. name_resolver's TGL_ROOTS was the densest
case: a module-level tuple holding BOTH roots.

Three aggregators now take the game root itself rather than a project
root they joined \"game\" onto.

OPEN_STBC_GAME_DIR is gone: a second env var doing this job under a
different name, with its own project-relative fallback.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Migrate the 23 `tools/` scripts

**Files:**
- Modify: `tools/analyze_power_session.py`, `tools/analyze_scale_log.py`, `tools/analyze_session.py`, `tools/bake_backdrop_appearance.py`, `tools/bake_impulse_glow.py`, `tools/bake_set_course_catalog.py`, `tools/bake_star_colors.py`, `tools/bake_warp_glow.py`, `tools/bcs_inspect.py`, `tools/decode_lip_phonemes.py`, `tools/gameloop_harness.py`, `tools/pick_simplest_mission.py`, `tools/probes/build_ghidra_export.py`, `tools/probes/collect.py`, `tools/probes/collect_q13.py`, `tools/probes/collect_q14.py`, `tools/probes/collect_q15.py`, `tools/probes/collect_q16.py`, `tools/probes/collect_q17.py`, `tools/probes/push.py`, `tools/setup.py`, `tools/tgl_harness.py`, `tools/uninstall.py`

**Interfaces:**
- Consumes: `paths.game_root()`, `paths.game_asset()`, `paths.sdk_root()`, `paths.sdk_scripts()`, `paths.sdk_data()` from Task 2.
- Produces: nothing.

These are offline scripts that run to completion and never see the first-run
picker, so a module-level constant is acceptable here — only the
string-constant guard applies, not the no-capture-at-import rule. They are
broken by the same move that broke the engine, so this is finishing the job.

Find them with the same AST scan the guard uses, rather than a grep:

```bash
uv run python -c "
import ast, pathlib
for p in sorted(pathlib.Path('tools').rglob('*.py')):
    if '__pycache__' in p.parts: continue
    t = ast.parse(p.read_text(errors='replace'))
    for n in ast.walk(t):
        if (isinstance(n, ast.Constant) and isinstance(n.value, str)
                and (n.value in ('game','sdk') or n.value.startswith(('game/','sdk/')))):
            print(f'{p}:{n.lineno}: {n.value[:60]!r}')
"
```

- [ ] **Step 1: Confirm the current breakage**

Run: `uv run python -c "import tools.tgl_harness"` then
`uv run python tools/pick_simplest_mission.py --help`
Expected: either an empty result or a path error — both scripts build
`PROJECT_ROOT / "sdk"`, which no longer exists.

- [ ] **Step 2: Apply the transformation**

In each file, replace the path construction with a call, keeping the existing
constant name where the script uses it repeatedly. The transformations are:

| Old | New |
|---|---|
| `PROJECT_ROOT / "game"` | `paths.game_root()` |
| `PROJECT_ROOT / "game" / X` | `paths.game_asset(X)` |
| `PROJECT_ROOT / "sdk" / "Build" / "scripts"` | `paths.sdk_scripts()` |
| `PROJECT_ROOT / "sdk" / "Build" / "Data" / X` | `paths.sdk_data() / X` |
| `os.path.join(ROOT, "game/...")` | `str(paths.game_asset("..."))` |

Each file gains `from engine import paths` at the top. Scripts that already
insert the project root on `sys.path` need no further change; those that do
not (`tools/probes/*`) must add:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from engine import paths
```

`tools/setup.py` and `tools/uninstall.py` also reference `game/scripts/` for
instrumentation — that becomes `paths.game_asset("scripts")`. `scripts/` stays
out of the validation markers: it is only these two scripts' target, not a
runtime requirement.

**Five of the flagged strings are messages and labels, not paths.** Four are
error text describing the legacy layout and are rewritten to name the new
sources:

- `tools/setup.py:80` — `"game/scripts/ not found - is the game installed in game/?"` becomes
  `f"scripts/ not found under {paths.game_root()} - set --game-dir or settings.json [paths].game"`
- `tools/setup.py:83` — `"sdk/Build/scripts/App.py not found - is the SDK installed in"` becomes
  `f"Build/scripts/App.py not found under {paths.sdk_root()} - set --sdk-dir or settings.json [paths].sdk"`
- `tools/setup.py:124` — `"game/scripts/App.pyc missing - game installation looks incomplete"` becomes
  `f"scripts/App.pyc missing under {paths.game_root()} - the install looks incomplete"`
- `tools/probes/push.py:25` — `f"game/ not found at {GAME}"` becomes `f"game root not found at {GAME}"`

The fifth is genuinely a label: `tools/probes/build_ghidra_export.py:189`
records `"source_binary": "game/stbc.exe"` in an export manifest, where an
absolute machine-specific path would be *worse* — the manifest is meant to be
portable. Mark that one line for the guard:

```python
            "source_binary": "game/stbc.exe",  # paths-guard: label
```

- [ ] **Step 3: Verify each script imports and resolves**

Run:

```bash
for m in analyze_power_session analyze_scale_log analyze_session \
         bake_backdrop_appearance bake_impulse_glow bake_set_course_catalog \
         bake_star_colors bake_warp_glow bcs_inspect decode_lip_phonemes \
         gameloop_harness pick_simplest_mission setup tgl_harness uninstall \
         probes.build_ghidra_export probes.collect probes.collect_q13 \
         probes.collect_q14 probes.collect_q15 probes.collect_q16 \
         probes.collect_q17 probes.push; do
  uv run python -c "import importlib; importlib.import_module('tools.$m')" \
    && echo "OK   $m" || echo "FAIL $m"
done
```

Expected: `OK` for all 23.

- [ ] **Step 4: Verify one script actually finds content**

Run: `uv run python tools/pick_simplest_mission.py 2>&1 | head -5`
Expected: mission names, not an empty list or a path error.

- [ ] **Step 5: Run the gate**

Run: `scripts/check_tests.sh`
Expected: `OK — no new failures. 1 known failure(s) still baselined.`

- [ ] **Step 6: Commit**

```bash
git add tools/
git commit -m "refactor(paths): tools/ resolves BC content through engine.paths

All 23 were broken by the same move that broke the engine -- ten more
than a grep found, because a grep cannot see a constant split across
lines. Module-level constants are fine here: these run to completion and
never see the first-run picker.

Four error strings that described the legacy layout now name the real
sources. One literal survives as a deliberate label: the Ghidra export
manifest records \"game/stbc.exe\" to stay portable.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: The C++ game root

**Files:**
- Create: `native/src/renderer/asset_path.cc`
- Modify: `native/src/renderer/include/renderer/asset_path.h`
- Modify: `native/src/renderer/CMakeLists.txt` (add the new source)
- Modify: `native/tests/renderer/asset_path_test.cc`
- Modify (26 literals): `native/src/renderer/breach_debris.cc`, `breach_pass.cc`, `breach_venting.cc`, `dust_pass.cc`, `frame.cc`, `hit_vfx_pass.cc`, `include/renderer/hit_vfx_pass.h`, `particle_pass.cc`, `phaser_pass.cc`, `subsystem_pin_pass.cc`, `target_reticle_pass.cc`
- Modify: `native/src/host/host_bindings.cc`
- Modify: `engine/renderer.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - C++: `renderer::set_game_root(const std::string&)`, `renderer::game_root() -> const std::string&`, `renderer::resolve_asset_path(const std::string&) -> std::string`
  - Python: `_dauntless_host.set_game_root(str)`, façade `engine.renderer.set_game_root(path: str)`

- [ ] **Step 1: Write the failing tests**

Append to `native/tests/renderer/asset_path_test.cc`:

```cpp
// --- a settable game root ---------------------------------------------------
//
// The 26 literals that used to spell "game/data/..." now spell
// "data/..." and route through resolve_asset_path, so one variable decides
// where BC content lives. The default stays "game" so every test above, and
// every native/tools/ probe, behaves exactly as it did.

namespace {
struct GameRootGuard {
    std::string saved = renderer::game_root();
    ~GameRootGuard() { renderer::set_game_root(saved); }
};
}  // namespace

TEST(AssetPath, DefaultRootIsTheLiteralGame) {
    EXPECT_EQ(renderer::game_root(), "game");
}

TEST(AssetPath, SetRootIsUsedAsThePrefix) {
    GameRootGuard guard;
    renderer::set_game_root("/opt/BC/game");
    EXPECT_EQ(resolve_asset_path("data/rough.tga"), "/opt/BC/game/data/rough.tga");
}

TEST(AssetPath, IdempotentUnderAChangedRoot) {
    GameRootGuard guard;
    renderer::set_game_root("/opt/BC/game");
    EXPECT_EQ(resolve_asset_path("/opt/BC/game/data/rough.tga"),
              "/opt/BC/game/data/rough.tga");
}

TEST(AssetPath, AbsolutePathsStillPassThroughUnderAChangedRoot) {
    GameRootGuard guard;
    renderer::set_game_root("/opt/BC/game");
    EXPECT_EQ(resolve_asset_path("/elsewhere/x.tga"), "/elsewhere/x.tga");
}

TEST(AssetPath, ALegacyGamePrefixIsStrippedNotDoubled) {
    // A missed literal must still LOAD -- and be visible in the log -- rather
    // than resolve to /opt/BC/game/game/data/... and silently draw untextured.
    GameRootGuard guard;
    renderer::set_game_root("/opt/BC/game");
    EXPECT_EQ(resolve_asset_path("game/data/rough.tga"),
              "/opt/BC/game/data/rough.tga");
}

TEST(AssetPath, EmptyRootFallsBackToTheDefault) {
    GameRootGuard guard;
    renderer::set_game_root("");
    EXPECT_EQ(renderer::game_root(), "game");
}
```

- [ ] **Step 2: Run to verify they fail**

Run: `cmake --build build -j && ctest --test-dir build -R renderer_tests --output-on-failure 2>&1 | tail -20`
Expected: FAIL to compile — `no member named 'game_root' in namespace 'renderer'`

- [ ] **Step 3: Rewrite `asset_path.h`**

Replace the `resolve_asset_path` inline definition (lines 34-48) with
declarations, keeping `is_absolute_asset_path` and `kBackslash` inline exactly
as they are:

```cpp
/// The BC install root every relative asset path is resolved against.
/// Defaults to the literal "game", which is cwd-relative and preserves the
/// in-project layout; host_loop sets an absolute path at boot once
/// engine.paths has resolved one. Settable more than once: the first-run
/// picker changes it after the window is already up.
void set_game_root(const std::string& root);
const std::string& game_root();

/// Resolve an SDK/BC asset path (relative to the game install root, e.g.
/// "data/Textures/Effects/ExplosionB.tga") to an openable path.
/// Idempotent: already-rooted, absolute, and empty paths are returned
/// unchanged.
///
/// A path that still carries a literal "game/" prefix while the root is
/// something else is a MISSED MIGRATION: the prefix is stripped so the asset
/// still loads, and the fact is logged once. Without that, the symptom would
/// be an untextured pass and no error at all.
std::string resolve_asset_path(const std::string& path);
```

- [ ] **Step 4: Write `asset_path.cc`**

```cpp
// native/src/renderer/asset_path.cc
#include <renderer/asset_path.h>

#include <cstdio>
#include <string>

namespace renderer {
namespace {

// Default "game": cwd-relative, matching the in-project layout the host
// chdir's into. Not a std::string constant at namespace scope in the header,
// because the whole point is that this is mutable at runtime.
std::string& mutable_game_root() {
    static std::string root = "game";
    return root;
}

bool starts_with_dir(const std::string& path, const std::string& prefix) {
    if (prefix.empty() || path.size() <= prefix.size()) return false;
    if (path.compare(0, prefix.size(), prefix) != 0) return false;
    const char sep = path[prefix.size()];
    return sep == '/' || sep == kBackslash;
}

}  // namespace

void set_game_root(const std::string& root) {
    // An empty root would silently produce "/data/..." -- an absolute path
    // into the filesystem root -- so fall back rather than accept it.
    mutable_game_root() = root.empty() ? "game" : root;
}

const std::string& game_root() { return mutable_game_root(); }

std::string resolve_asset_path(const std::string& path) {
    if (path.empty()) return path;
    if (is_absolute_asset_path(path)) return path;

    const std::string& root = game_root();
    if (starts_with_dir(path, root)) return path;

    std::string rel = path;
    if (root != "game" && starts_with_dir(path, "game")) {
        static bool warned = false;
        if (!warned) {
            warned = true;
            std::fprintf(stderr,
                         "[asset_path] a literal \"game/\" prefix reached "
                         "resolve_asset_path while the root is \"%s\" (first: "
                         "\"%s\"). That is an unmigrated load site -- the "
                         "prefix is being stripped so the asset still loads.\n",
                         root.c_str(), path.c_str());
        }
        rel = path.substr(5);
    }
    return root + "/" + rel;
}

}  // namespace renderer
```

Add `asset_path.cc` to the renderer library's source list in
`native/src/renderer/CMakeLists.txt`.

- [ ] **Step 5: Migrate the 26 literals**

In each file, drop the `"game/"` prefix from the constant, then **resolve once
into a local at the top of the function that uses it** — do not wrap each use
separately. Most constants are read more than once: `phaser_pass.cc` reads
`kBeamTexturePath` three times (the `ifstream` plus two error messages), and
an error message naming the unresolved path is worse than useless when the
whole question is where the file was looked for.

`native/src/renderer/phaser_pass.cc:21` becomes:

```cpp
constexpr const char* kBeamTexturePath = "data/phaser.tga";
```

and its reader at line 34:

```cpp
    const std::string beam_path = resolve_asset_path(kBeamTexturePath);
    std::ifstream in(beam_path, std::ios::binary);
    if (!in) {
        std::fprintf(stderr, "[phaser_pass] failed to open '%s'\n",
                     beam_path.c_str());
        ...
```

with the line-52 message taking `beam_path.c_str()` likewise. Add
`#include <renderer/asset_path.h>` and `#include <string>` where absent.

The constants are: `breach_debris.cc` (`data/spark.tga`, `data/square.tga`),
`breach_pass.cc` (`data/Damage1.tga` … `Damage4.tga`), `breach_venting.cc`
(`data/rough.tga`), `dust_pass.cc` (`data/Textures/spacedust.tga`), `frame.cc`
(`data/Textures/Effects/Damage.tga`), `hit_vfx_pass.cc` +
`include/renderer/hit_vfx_pass.h` (`data/Textures/Tactical/TorpedoFlares.tga`,
`data/rough.tga`), `phaser_pass.cc` (`data/phaser.tga`), `subsystem_pin_pass.cc`
(the nine `data/Icons/Damage/*.tga`), `target_reticle_pass.cc`
(`data/Icons/TargetArrow.tga`, `data/Icons/tilehorizline.tga`,
`data/subtarget.tga`, `data/target.tga`). `particle_pass.cc:100` already calls
`resolve_asset_path` and needs no change.

Confirm the count before and after with the guard's own query:

```bash
grep -rn --include='*.cc' --include='*.h' '"game/' native/src \
  | grep -v ':[0-9]*: *//' | grep -v 'asset_path'
```

Expected before: 26 lines. Expected after: none.

Update the two stale comments: `native/src/host/host_main.cc:162` and
`native/src/renderer/window.cc:22` both say `resolve_asset_path prepends
"game/"` — change to `resolve_asset_path prepends the configured game root
(default "game")`.

- [ ] **Step 6: Add the binding and the façade**

In `native/src/host/host_bindings.cc`, beside the other renderer setters:

```cpp
    m.def("set_game_root",
          [](const std::string& root) { renderer::set_game_root(root); },
          py::arg("root"),
          "Absolute path to the BC game install. Every relative asset path "
          "the renderer resolves is joined onto this. Default is the literal "
          "\"game\" (cwd-relative). Callable more than once.");
```

In `engine/renderer.py`, add the wrapper and the REQUIRED entry:

```python
def set_game_root(root: str) -> None:
    """Point the renderer's relative asset paths at a BC install."""
    _h.set_game_root(root)
```

Add `"set_game_root"` to `_REQUIRED_BINDINGS` at line 32.

- [ ] **Step 7: Run the tests**

Run: `cmake -B build -S . && cmake --build build -j && ctest --test-dir build --output-on-failure 2>&1 | tail -15`
Expected: 0 failures, including the six new `AssetPath` cases.

Run: `scripts/check_tests.sh`
Expected: `OK — no new failures. 1 known failure(s) still baselined.`

- [ ] **Step 8: Commit**

```bash
git add native/src/renderer/asset_path.cc native/src/renderer/include/renderer/asset_path.h native/src/renderer/CMakeLists.txt native/tests/renderer/asset_path_test.cc native/src/renderer/ native/src/host/host_bindings.cc native/src/host/host_main.cc engine/renderer.py
git commit -m "feat(renderer): resolve asset paths against a settable game root

26 literals spelled \"game/\" themselves; now one variable decides, and
the prefix appears once. Default stays the literal \"game\" so every
existing test and every native/tools/ probe is unchanged.

A missed literal is recoverable and LOUD rather than silent: the stale
prefix is stripped so the asset still loads, and the first occurrence is
named on stderr. The failure mode being designed against is an untextured
pass with no error.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Boot wiring and the CLI flags

**Files:**
- Modify: `engine/host_loop.py` (the `run()` prologue, around line 6729)
- Modify: `native/src/host/host_main.cc` (argv pass-through)

**Interfaces:**
- Consumes: `paths.resolve()`, `paths.configure()`, `paths.persist()`, `paths.describe_failure()` from Task 2; `r.set_game_root()` from Task 6.
- Produces: `--game-dir` / `--sdk-dir` accepted by `build/dauntless`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_paths_resolve.py`:

```python
def test_boot_resolution_is_wired_before_the_sdk_finder(monkeypatch):
    """host_loop.run() must configure paths BEFORE _setup_sdk(): the finder
    asks paths.sdk_scripts(), so a later configure would be too late."""
    import inspect
    from engine import host_loop
    source = inspect.getsource(host_loop.run)
    configure_at = source.index("paths.configure(")
    setup_at = source.index("_setup_sdk()")
    assert configure_at < setup_at, (
        "paths.configure() must run before _setup_sdk() in host_loop.run()"
    )


def test_boot_sets_the_renderer_game_root(monkeypatch):
    from engine import host_loop
    import inspect
    source = inspect.getsource(host_loop.run)
    assert "set_game_root(" in source
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_paths_resolve.py -k boot -q`
Expected: FAIL — `ValueError: substring not found`

- [ ] **Step 3: Wire the boot sequence**

In `engine/host_loop.py`, insert immediately before `_setup_sdk()` at line 6729:

```python
    # Resolve where BC content lives before anything asks for any of it. This
    # must precede _setup_sdk(): the SDK meta-path finder calls
    # paths.sdk_scripts(), so configuring afterwards would be too late.
    #
    # persist() writes only a CLI-sourced, valid root -- an env var is
    # ephemeral by contract and a typo never becomes the stored answer.
    from engine import paths as _paths
    _resolution = _paths.resolve()
    _paths.configure(_resolution)
    if not _resolution.ok:
        import sys as _sys
        print(_paths.describe_failure(_resolution), file=_sys.stderr)
        return 1
    _paths.persist(_resolution)

    _setup_sdk()
```

Then, immediately after the `r.init(1280, 720, "open_stbc")` call, add:

```python
    # The renderer joins its own relative asset paths onto this. Set after
    # r.init because the binding needs the module loaded, and before any pass
    # constructs -- their texture constants are relative now.
    r.set_game_root(str(_paths.game_root()))
```

- [ ] **Step 4: Pass the flags through in `host_main.cc`**

`engine.paths.resolve()` reads `sys.argv[1:]`, and `Py_InitializeEx` does not
populate `sys.argv` from the host's argv. Add, immediately after
`Py_InitializeEx(/*initsigs=*/1);` at line 199:

```cpp
    // engine.paths reads sys.argv for --game-dir / --sdk-dir, and
    // Py_InitializeEx leaves sys.argv unset. Build the list directly rather
    // than calling PySys_SetArgvEx, which is deprecated since 3.11 -- and
    // which would also prepend argv[0] to sys.path unless told not to,
    // undoing configure_python_path.
    {
        PyObject* list = PyList_New(0);
        if (list) {
            for (int i = 0; i < argc; ++i) {
                PyObject* item = PyUnicode_DecodeFSDefault(argv[i]);
                if (!item) { PyErr_Clear(); continue; }
                PyList_Append(list, item);
                Py_DECREF(item);
            }
            PySys_SetObject("argv", list);   // borrows; sys holds its own ref
            Py_DECREF(list);
        } else {
            PyErr_Clear();
        }
    }
```

No new includes are needed — `Python.h` is already in scope.

Extend the `--developer` scan comment at line 190-192 to note that
`--game-dir` and `--sdk-dir` are consumed on the Python side via `sys.argv`,
so they need no C++ parsing — only publication.

- [ ] **Step 5: Verify**

Run: `uv run pytest tests/unit/test_paths_resolve.py -q`
Expected: PASS.

Run: `cmake --build build -j`
Expected: build ok.

Run: `scripts/check_tests.sh`
Expected: `OK — no new failures. 1 known failure(s) still baselined.`

- [ ] **Step 6: Commit**

```bash
git add engine/host_loop.py native/src/host/host_main.cc tests/unit/test_paths_resolve.py
git commit -m "feat(paths): resolve BC roots at boot and accept --game-dir/--sdk-dir

configure() runs before _setup_sdk() -- the SDK finder asks
paths.sdk_scripts(), so configuring afterwards would be too late -- and
r.set_game_root() runs right after r.init, before any pass constructs its
now-relative texture constants.

host_main publishes argv via PySys_SetArgvEx with updatepath=0, since
Py_InitializeEx leaves sys.argv unset and engine.paths reads it. The
flags need no C++ parsing, only publication.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: The guards and the documentation

**Files:**
- Create: `tests/unit/test_path_indirection.py`
- Modify: `CLAUDE.md`
- Modify: `engine/settings_store.py` (docstring paragraph about the reserved `paths` section)
- Modify: `docs/superpowers/specs/2026-09-05-settings-persistence-design.md` ("Future: the bootstrap tier")

**Interfaces:**
- Consumes: everything from Tasks 1-7.
- Produces: nothing.

- [ ] **Step 1: Write the guards**

Create `tests/unit/test_path_indirection.py`:

```python
"""The migration's guards. A missed site fails SILENTLY -- a texture that
does not load, a mission that does not list -- so these are structural.

Both Python guards parse rather than grep. A grep for `sdk/` flags every
docstring in engine/ that cites sdk/Build/scripts/... -- there are dozens --
and it MISSES engine/dev_keybindings.py's nine-line constant, where no single
line holds both the root and the segment. A guard that cries wolf gets
deleted, and one that misses the hardest case is worse than none.
"""
import ast
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# The one module allowed to know how BC content is laid out.
_AUTHORITY = PROJECT_ROOT / "engine" / "paths.py"

# An opt-out for a string that DESCRIBES the layout rather than building a
# path -- e.g. the Ghidra export manifest's portable "source_binary" label.
# A comment, not a file allowlist, so the exemption sits next to the reason.
_ESCAPE = "# paths-guard: label"

_BAD_EXACT = {"game", "sdk"}
_BAD_PREFIX = ("game/", "sdk/", "game\\", "sdk\\")


def _sources():
    """engine/ and tools/ entirely, plus conftest -- but not tests/ at large:
    a test fixture that builds a fake install tree is the one legitimate
    reason to spell the layout."""
    for sub in ("engine", "tools"):
        for path in (PROJECT_ROOT / sub).rglob("*.py"):
            if "__pycache__" not in path.parts:
                yield path
    yield PROJECT_ROOT / "tests" / "conftest.py"


def _docstring_ids(tree):
    out = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.FunctionDef,
                                 ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        body = getattr(node, "body", None)
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            out.add(id(body[0].value))
    return out


def _spells_a_root(value: str) -> bool:
    return value in _BAD_EXACT or value.startswith(_BAD_PREFIX)


def test_no_python_source_spells_a_bc_root():
    offenders = []
    for path in _sources():
        if path == _AUTHORITY or not path.exists():
            continue
        text = path.read_text(errors="replace")
        lines = text.splitlines()
        tree = ast.parse(text, filename=str(path))
        docs = _docstring_ids(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant)
                    and isinstance(node.value, str)):
                continue
            if id(node) in docs or not _spells_a_root(node.value):
                continue
            line = lines[node.lineno - 1] if node.lineno <= len(lines) else ""
            if _ESCAPE in line:
                continue
            offenders.append(
                f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}: "
                f"{node.value[:60]!r}")
    assert offenders == [], (
        "these spell a BC root instead of asking engine.paths "
        f"(add '{_ESCAPE}' if the string is a label, not a path):\n"
        + "\n".join(offenders))


def test_no_engine_module_captures_a_path_at_import():
    """The trap that would make a first-run picker impossible.

    A module-level `X = paths.game_asset(...)` is evaluated at import, so it
    still points at the old install after the player chooses a folder. There
    were eight of these; engine/dev_keybindings.py's spanned nine lines.
    """
    watched = {"game_root", "sdk_root", "sdk_scripts", "sdk_data", "game_asset"}
    offenders = []
    for path in (PROJECT_ROOT / "engine").rglob("*.py"):
        if "__pycache__" in path.parts or path == _AUTHORITY:
            continue
        tree = ast.parse(path.read_text(errors="replace"), filename=str(path))
        for node in tree.body:                       # module level ONLY
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            for call in ast.walk(node):
                if not isinstance(call, ast.Call):
                    continue
                func = call.func
                name = (func.attr if isinstance(func, ast.Attribute)
                        else func.id if isinstance(func, ast.Name) else None)
                if name in watched:
                    offenders.append(
                        f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}: "
                        f"module-level {name}()")
    assert offenders == [], (
        "paths must resolve at USE, never at import -- these are captured "
        "when the module loads and would be stale after the first-run "
        "picker:\n" + "\n".join(offenders))


def test_no_cpp_source_spells_a_game_prefix():
    allow = {PROJECT_ROOT / "native" / "src" / "renderer" / "asset_path.cc",
             PROJECT_ROOT / "native" / "src" / "renderer" / "include"
             / "renderer" / "asset_path.h"}
    offenders = []
    for pattern in ("*.cc", "*.h", "*.mm"):
        for path in (PROJECT_ROOT / "native" / "src").rglob(pattern):
            if path in allow:
                continue
            for n, line in enumerate(
                    path.read_text(errors="replace").splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("//") or _ESCAPE in line:
                    continue
                if '"game/' in line:
                    offenders.append(
                        f"{path.relative_to(PROJECT_ROOT)}:{n}: {stripped}")
    assert offenders == [], (
        'these carry a literal "game/" prefix instead of routing through '
        "renderer::resolve_asset_path:\n" + "\n".join(offenders))
```

- [ ] **Step 2: Run the guards**

Run: `uv run pytest tests/unit/test_path_indirection.py -q`
Expected: PASS, 3 tests. If either of the first two fails, it has found a site
Tasks 4-6 missed — **fix the site, not the guard**.

Note that `test_no_engine_module_captures_a_path_at_import` is a **ratchet**:
it passes trivially before the migration, because nothing calls `paths.*` at
all yet. It only has teeth once `engine/` consumes this module — which is why
Step 3 proves it by mutation rather than trusting the green. The one legitimate exemption is a string that
describes the layout rather than building a path, and it is marked in place
with `# paths-guard: label`.

- [ ] **Step 3: Prove each guard actually catches its bug**

Back up, mutate, watch it fail, restore by copy — never with git:

```bash
cp engine/ui/weapon_icons.py /tmp/wi.bak
printf '\n_LEAK = __import__("engine.paths", fromlist=["x"]).game_asset("data")\n' >> engine/ui/weapon_icons.py
uv run pytest tests/unit/test_path_indirection.py::test_no_engine_module_captures_a_path_at_import -q
cp /tmp/wi.bak engine/ui/weapon_icons.py
diff engine/ui/weapon_icons.py /tmp/wi.bak && echo "RESTORED byte-identical"
```

Expected: the pytest run FAILS naming `weapon_icons.py`, then the diff reports
no differences.

- [ ] **Step 4: Document the rule in CLAUDE.md**

Add a section after the rotation-matrix convention:

```markdown
## BC content paths — one authority, resolved at use

`game/` and `sdk/` do not have to live inside the project. `engine/paths.py`
resolves both roots from four sources in precedence order — `--game-dir` /
`--sdk-dir`, `DAUNTLESS_GAME_DIR` / `DAUNTLESS_SDK_DIR`, `settings.json`
`[paths]`, then the legacy in-project layout. The highest source that is
**set** wins even if it is invalid; falling through would silently run a
different install than the one that was asked for. A CLI flag persists; an
env var never does.

### Hard rules

- **Never spell `game` or `sdk` as a path segment.** Not in `engine/`, not in
  `tools/`, not in `tests/conftest.py`, not in `native/src`. Ask
  `paths.game_asset(rel)`, `paths.game_root()`, `paths.sdk_scripts()`,
  `paths.sdk_data()`.
- **Never capture a path at import.** No module-level constant may hold one.
  `paths.configure()` is callable again after boot — that is what the
  first-run picker needs — so anything captured at import is stale the moment
  the player picks a folder. `engine/missions/name_resolver.py`'s `TGL_ROOTS`
  was the densest instance of this trap.
- C++ joins relative asset paths onto `renderer::game_root()`, default the
  literal `"game"`. A literal `"game/"` reaching `resolve_asset_path` is a
  missed migration: it is stripped so the asset still loads, and logged once.

`tests/unit/test_path_indirection.py` enforces all three. The two Python
guards **parse rather than grep**: a grep flags every docstring citing
`sdk/Build/scripts/...` and still misses `dev_keybindings.py`'s nine-line
constant, where no single line holds both the root and the segment. A string
that describes the layout rather than building a path is exempted in place
with `# paths-guard: label`.

Spec: `docs/superpowers/specs/2026-09-05-bc-path-resolution-design.md`
```

Add a row to the reference table:

```markdown
| BC content paths | `engine/paths.py`, `docs/superpowers/specs/2026-09-05-bc-path-resolution-design.md` | Where `game/` and `sdk/` live. Four sources, highest **set** one wins even when invalid. Resolved at USE, never at import — a module-level constant is stale the moment the first-run picker changes a root. Guarded by `tests/unit/test_path_indirection.py`. |
```

- [ ] **Step 5: Update the two stale cross-references**

In `engine/settings_store.py`, replace the paragraph beginning
`The "paths" section is RESERVED for the bootstrap tier` with:

```
The "paths" section holds the bootstrap tier — where the player's BC install
lives. engine/paths.py owns it; see
docs/superpowers/specs/2026-09-05-bc-path-resolution-design.md. Unknown-section
preservation means an older build cannot destroy it.
```

In `docs/superpowers/specs/2026-09-05-settings-persistence-design.md`, replace
the body of "Future: the bootstrap tier" with a pointer:

```markdown
**Built 2026-09-05.** See
`docs/superpowers/specs/2026-09-05-bc-path-resolution-design.md`.
`engine/paths.py` owns the `paths` section; `game/` and `sdk/` are no longer
hardcoded to the project root.
```

- [ ] **Step 6: Run the full gate**

Run: `scripts/check_tests.sh`
Expected: `OK — no new failures. 1 known failure(s) still baselined.`

- [ ] **Step 7: Commit**

```bash
git add tests/unit/test_path_indirection.py CLAUDE.md engine/settings_store.py docs/superpowers/specs/2026-09-05-settings-persistence-design.md
git commit -m "test(paths): guard the indirection; document the hard rules

Two greps and an AST check. The AST one carries the weight: a path
captured into a module-level constant reads as completely ordinary code,
survives any grep, and would leave a module pointing at the old install
after the first-run picker changes a root.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Live verification (Mark only — not visible to the gate)

Run `./build/dauntless --developer` and confirm:

1. **A ship renders WITH TEXTURES.** The C++ migration's failure mode is an
   untextured pass, not an error — a booting binary proves nothing on its own.
   Watch stderr for `[asset_path] a literal "game/" prefix reached ...`, which
   names any missed literal.
2. **Audio plays.** `tg_sound` is the one hot path changing here.
3. **A mission loads** from Developer → Load Mission…, exercising
   `sdk_scripts()` through the live finder rather than the test one.
4. **`--game-dir` persists**: run
   `./build/dauntless --game-dir "/Users/mward/Documents/Star Trek Bridge Commander/game"`,
   quit, confirm `settings.json` gained the entry, then relaunch with no flags
   and confirm it still boots.
5. **A wrong path is diagnosed, not crashed**: run
   `./build/dauntless --game-dir /tmp` and confirm the stderr block names the
   missing markers and exits non-zero.
6. **HUD icons, damage icons and the target reticle draw** — those are three
   of the migrated C++ literal groups (`subsystem_pin_pass`,
   `target_reticle_pass`, `breach_pass`).
