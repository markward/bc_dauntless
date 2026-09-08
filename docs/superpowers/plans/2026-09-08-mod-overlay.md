# Mod Overlay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Load Bridge Commander mods from `mods/` non-destructively, so a mod's files win over stock content everywhere without anything being copied, symlinked, or overwritten.

**Architecture:** At boot, walk only the mod directories and build a case-folded index mapping `relative path → absolute path`. Three consumers then check that index before falling back to stock: `paths.game_asset()`, both `_SDKFinder` copies, and a small override map pushed into C++ `resolve_asset_path`. Stock content is never walked and never touched.

**Tech Stack:** Python 3 (`engine/`), pytest, C++17 + GoogleTest (`native/`), CMake.

**Spec:** `docs/superpowers/specs/2026-09-08-mod-overlay-design.md`

## Global Constraints

- **Never spell `game` or `sdk` as a path segment** anywhere outside `engine/paths.py`. Ask `paths.game_root()`, `paths.sdk_scripts()`, `paths.game_asset(rel)`. Enforced by `tests/unit/test_path_indirection.py`, which **parses** rather than greps. Where a string is a *kind label* rather than a path (e.g. a dict key `"game"`), annotate it in place with a `# paths-guard: <reason>` comment — a prefix, not a fixed string.
- **Never capture a path at import.** No module-level constant may hold one. `paths.configure()` is callable again after boot; anything captured at import is stale the moment a picker or mod screen changes it.
- **Never run destructive git.** Banned: `git checkout -- <path>`, `git checkout .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`. Always stage with an explicit pathspec. To mutate a file temporarily, `cp` it aside and `cp` it back, then `diff` to prove the restore.
- **The test gate is `scripts/check_tests.sh`**, never `scripts/run_tests.sh` (which is pytest-only and cannot see C++ regressions). It diffs failures against `tests/known_failures.txt` and exits non-zero naming anything not baselined. Never call a failure "pre-existing" by eyeball.
- **`mods/` is gitignored.** No test may depend on real mod content. All fixtures are synthetic trees built in `tmp_path`.
- **Zero mods must be byte-identical to today.** A modless boot may not change any resolved path.
- **`_SDKFinder` is duplicated** in `tools/mission_harness.py` and `tests/conftest.py`. Both copies change together, always.
- **C++ binding changes need a `dauntless` rebuild**: `cmake -B build -S . && cmake --build build -j`. Never run `cmake` from inside `native/`. One build tree only: `<project-root>/build/`.

---

## File Structure

| File | Responsibility |
|---|---|
| `engine/mods.py` (create) | Mods root resolution, discovery, index build, classification, report. The single authority, mirroring `paths.py`'s shape. |
| `engine/paths.py` (modify) | `game_asset()` consults the index; new `game_asset_dirs()` for callers that search a directory. |
| `tools/mission_harness.py` (modify) | `_SDKFinder` checks the index before the SDK. |
| `tests/conftest.py` (modify) | Same change, second copy. |
| `engine/ui/{ship,weapon,damage}_icons.py` (modify) | Directory-join lookups become single relative-path lookups. |
| `engine/missions/name_resolver.py` (modify) | `_tgl_roots()` includes mod TGL directories. |
| `engine/appc/viewscreen_static.py` (modify) | Effects directory becomes a search list. |
| `engine/host_loop.py` (modify) | Texture and planet searches gain mod dirs; boot builds and installs the index. |
| `native/src/renderer/asset_path.{h,cc}` (modify) | Override map consulted before the root prefix. |
| `native/src/host/host_bindings.cc` (modify) | `set_asset_overrides` binding. |
| `engine/renderer.py` (modify) | Export + require the new binding. |
| `tests/unit/test_mods_*.py` (create) | Python unit tests. |
| `native/tests/renderer/asset_path_test.cc` (modify) | C++ override tests. |

---

### Task 1: Mods root resolution and mod discovery

**Files:**
- Create: `engine/mods.py`
- Test: `tests/unit/test_mods_discovery.py`

**Interfaces:**
- Consumes: `engine.paths.PROJECT_ROOT`, `engine.paths.normalise`
- Produces:
  - `mods_root(argv=None, env=None) -> Path`
  - `CONTENT_DIRS: frozenset[str]` == `{"data", "scripts"}`
  - `find_content_root(mod_dir: Path, max_depth: int = 3) -> Path | None`
  - `discover_mods(root: Path) -> list[ModCandidate]` sorted by `name`
  - `@dataclass(frozen=True) ModCandidate(name: str, mod_dir: Path, content_root: Path | None)`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_mods_discovery.py
from pathlib import Path

import pytest

from engine import mods


def _touch(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x")


def test_flat_layout_content_root_is_the_mod_dir(tmp_path):
    mod = tmp_path / "SomeShip"
    _touch(mod / "Data" / "Models" / "a.nif")
    _touch(mod / "Scripts" / "Ships" / "a.py")
    assert mods.find_content_root(mod) == mod


def test_redundant_nesting_is_descended(tmp_path):
    mod = tmp_path / "SomeShip"
    _touch(mod / "SomeShip" / "Data" / "Models" / "a.nif")
    assert mods.find_content_root(mod) == mod / "SomeShip"


def test_descent_stops_at_depth_cap(tmp_path):
    mod = tmp_path / "Deep"
    _touch(mod / "a" / "b" / "c" / "d" / "Data" / "x.nif")
    assert mods.find_content_root(mod, max_depth=3) is None


def test_no_content_dirs_yields_none(tmp_path):
    mod = tmp_path / "JustDocs"
    _touch(mod / "readme.txt")
    assert mods.find_content_root(mod) is None


def test_content_dirs_matched_case_blind(tmp_path):
    mod = tmp_path / "LowerCase"
    _touch(mod / "data" / "x.nif")
    assert mods.find_content_root(mod) == mod


def test_ambiguous_branch_is_not_descended(tmp_path):
    # Two subdirs and no content dir: we cannot know which to follow.
    mod = tmp_path / "Ambiguous"
    _touch(mod / "one" / "Data" / "x.nif")
    _touch(mod / "two" / "Data" / "x.nif")
    assert mods.find_content_root(mod) is None


def test_discover_lists_each_subdir_sorted(tmp_path):
    _touch(tmp_path / "Bravo" / "Data" / "b.nif")
    _touch(tmp_path / "Alpha" / "Data" / "a.nif")
    _touch(tmp_path / "Broken" / "readme.txt")
    found = mods.discover_mods(tmp_path)
    assert [m.name for m in found] == ["Alpha", "Bravo", "Broken"]
    assert found[2].content_root is None


def test_discover_missing_root_is_empty_not_an_error(tmp_path):
    assert mods.discover_mods(tmp_path / "nope") == []


def test_mods_root_defaults_to_project_root(monkeypatch, tmp_path):
    monkeypatch.setattr(mods.paths, "PROJECT_ROOT", tmp_path)
    assert mods.mods_root(argv=[], env={}) == tmp_path / "mods"


def test_mods_root_cli_flag_wins_over_env(tmp_path):
    got = mods.mods_root(argv=["--mods-dir", str(tmp_path / "a")],
                         env={"DAUNTLESS_MODS_DIR": str(tmp_path / "b")})
    assert got == mods.paths.normalise(tmp_path / "a")


def test_mods_root_env_used_when_no_flag(tmp_path):
    got = mods.mods_root(argv=[], env={"DAUNTLESS_MODS_DIR": str(tmp_path / "b")})
    assert got == mods.paths.normalise(tmp_path / "b")


def test_mods_root_empty_env_is_unset(monkeypatch, tmp_path):
    # Mirrors paths.py: an empty env var is idiomatic shell for "unset".
    monkeypatch.setattr(mods.paths, "PROJECT_ROOT", tmp_path)
    assert mods.mods_root(argv=[], env={"DAUNTLESS_MODS_DIR": ""}) == tmp_path / "mods"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_mods_discovery.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.mods'`

- [ ] **Step 3: Write minimal implementation**

```python
# engine/mods.py
"""Where the player's installed mods live, and what they provide.

A mod is a BC-shaped tree the player drops into mods/. Nothing here ever
writes, copies, or symlinks: the index answers "who provides this file?"
and the stock roots answer everything else.

HARD RULE -- like engine/paths.py, paths resolve at USE, never at import.

Spec: docs/superpowers/specs/2026-09-08-mod-overlay-design.md
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from engine import paths

# Top-level directories inside a mod that we know how to place. Lowercase
# because every comparison here is case-folded.
CONTENT_DIRS = frozenset({"data", "scripts"})

CLI_FLAG = "--mods-dir"
ENV_VAR = "DAUNTLESS_MODS_DIR"


@dataclass(frozen=True)
class ModCandidate:
    """One subdirectory of the mods root, before its files are indexed."""
    name: str
    mod_dir: Path
    content_root: Optional[Path]


def mods_root(argv=None, env=None) -> Path:
    """Where mods live. CLI flag, then env, then PROJECT_ROOT/mods.

    Deliberately simpler than paths.resolve(): there is no settings tier and
    no validation, because an absent or empty mods root is not an error --
    it just means no mods.
    """
    import sys

    if argv is None:
        argv = sys.argv[1:]
    if env is None:
        env = os.environ

    flag = paths._flag_value(argv, CLI_FLAG)
    if flag is not paths._UNSET and str(flag).strip():
        return paths.normalise(flag)

    from_env = env.get(ENV_VAR)
    if from_env:
        return paths.normalise(from_env)

    return paths.PROJECT_ROOT / "mods"


def find_content_root(mod_dir: Path, max_depth: int = 3) -> Optional[Path]:
    """The directory inside `mod_dir` that holds Data/ and/or Scripts/.

    Archives are inconsistent: some extract to <mod>/{Data,Scripts}, others
    add a redundant <mod>/<name>/ level. Descend only while the answer is
    unambiguous -- exactly one subdirectory and no content dir here.
    """
    current = mod_dir
    for _ in range(max_depth + 1):
        try:
            entries = [e for e in current.iterdir() if e.is_dir()]
        except OSError:
            return None
        if any(e.name.lower() in CONTENT_DIRS for e in entries):
            return current
        if len(entries) != 1:
            return None
        current = entries[0]
    return None


def discover_mods(root: Path) -> list[ModCandidate]:
    """Every immediate subdirectory of `root`, sorted by name.

    A missing root is not an error -- it means no mods.
    """
    try:
        dirs = sorted((e for e in root.iterdir() if e.is_dir()),
                      key=lambda p: p.name)
    except OSError:
        return []
    return [ModCandidate(name=d.name, mod_dir=d, content_root=find_content_root(d))
            for d in dirs]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_mods_discovery.py -v`
Expected: PASS (12 tests)

- [ ] **Step 5: Confirm the path-indirection guard still passes**

Run: `uv run pytest tests/unit/test_path_indirection.py -v`
Expected: PASS. `engine/mods.py` spells neither root as a path segment and captures nothing at import.

- [ ] **Step 6: Commit**

```bash
git add engine/mods.py tests/unit/test_mods_discovery.py
git commit -m "feat(mods): discover mods and locate each content root"
```

---

### Task 2: Build the case-folded index

**Files:**
- Modify: `engine/mods.py`
- Test: `tests/unit/test_mods_index.py`

**Interfaces:**
- Consumes: Task 1's `ModCandidate`, `discover_mods`, `CONTENT_DIRS`
- Produces:
  - `@dataclass(frozen=True) ModFile(abs_path: Path, mod_name: str, target: str, rel: str)` — `target` is `"game"` or `"sdk"` (kind labels, not path segments)
  - `@dataclass ModIndex` with `.files: dict[str, ModFile]`, `.mods: list[ModStatus]`, `.lookup(rel) -> ModFile | None`, `.dirs_for(rel) -> list[Path]`
  - `@dataclass ModStatus(name, placed: int, ignored: int, unplaced: list[str], content_root: Path | None)`
  - `fold(rel) -> str`
  - `build_index(root: Path) -> ModIndex`
- Note: `target` values `"game"`/`"sdk"` are **kind labels**; annotate with `# paths-guard:` where they appear as literals.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_mods_index.py
from pathlib import Path

from engine import mods


def _touch(p: Path, body: str = "x") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


def test_fold_lowercases_and_normalises_separators():
    assert mods.fold("Data\\Models\\A.NIF") == "data/models/a.nif"
    assert mods.fold("data/Models/a.nif") == "data/models/a.nif"


def test_data_maps_to_the_game_target(tmp_path):
    _touch(tmp_path / "M" / "Data" / "Models" / "Ships" / "A.NIF")
    idx = mods.build_index(tmp_path)
    hit = idx.lookup("data/Models/Ships/a.nif")
    assert hit is not None
    assert hit.target == "game"
    assert hit.mod_name == "M"
    assert hit.abs_path == tmp_path / "M" / "Data" / "Models" / "Ships" / "A.NIF"


def test_scripts_maps_to_the_sdk_target(tmp_path):
    _touch(tmp_path / "M" / "Scripts" / "Ships" / "Fsteamr.py")
    idx = mods.build_index(tmp_path)
    hit = idx.lookup("ships/Fsteamr.py")
    assert hit is not None and hit.target == "sdk"


def test_case_collisions_all_resolve(tmp_path):
    # The three real collisions from the reference mod.
    _touch(tmp_path / "M" / "Data" / "Models" / "S" / "Fsteamr.NIF")
    idx = mods.build_index(tmp_path)
    for spelling in ("data/Models/S/Fsteamr.nif",
                     "DATA/models/s/FSTEAMR.NIF",
                     "data/models/s/fsteamr.nif"):
        assert idx.lookup(spelling) is not None, spelling


def test_unknown_top_level_dir_is_recorded_not_dropped(tmp_path):
    _touch(tmp_path / "M" / "Data" / "a.nif")
    _touch(tmp_path / "M" / "Sounds" / "b.wav")
    idx = mods.build_index(tmp_path)
    assert idx.lookup("sounds/b.wav") is None
    status = {m.name: m for m in idx.mods}["M"]
    assert "Sounds" in status.unplaced


def test_junk_is_ignored_and_counted(tmp_path):
    _touch(tmp_path / "M" / "Data" / "a.nif")
    _touch(tmp_path / "M" / ".DS_Store")
    _touch(tmp_path / "M" / "Data" / ".DS_Store")
    _touch(tmp_path / "M" / "readme.txt")
    idx = mods.build_index(tmp_path)
    status = {m.name: m for m in idx.mods}["M"]
    assert status.placed == 1
    assert status.ignored == 3


def test_later_mod_wins_and_ordering_is_deterministic(tmp_path):
    _touch(tmp_path / "Alpha" / "Data" / "a.nif", "alpha")
    _touch(tmp_path / "Bravo" / "Data" / "a.nif", "bravo")
    idx = mods.build_index(tmp_path)
    assert idx.lookup("data/a.nif").mod_name == "Bravo"
    assert mods.build_index(tmp_path).lookup("data/a.nif").mod_name == "Bravo"


def test_mod_without_content_root_contributes_nothing(tmp_path):
    _touch(tmp_path / "JustDocs" / "readme.txt")
    idx = mods.build_index(tmp_path)
    assert idx.files == {}
    assert {m.name for m in idx.mods} == {"JustDocs"}


def test_empty_root_yields_empty_index(tmp_path):
    idx = mods.build_index(tmp_path / "absent")
    assert idx.files == {}
    assert idx.mods == []


def test_dirs_for_returns_every_providing_mod_dir(tmp_path):
    _touch(tmp_path / "Alpha" / "Data" / "Tex" / "a.tga")
    _touch(tmp_path / "Bravo" / "Data" / "Tex" / "b.tga")
    idx = mods.build_index(tmp_path)
    got = idx.dirs_for("data/Tex")
    assert sorted(p.name for p in got) == ["Tex", "Tex"]
    assert {p.parent.parent.name for p in got} == {"Alpha", "Bravo"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_mods_index.py -v`
Expected: FAIL — `AttributeError: module 'engine.mods' has no attribute 'fold'`

- [ ] **Step 3: Write minimal implementation**

Append to `engine/mods.py`:

```python
IGNORED_NAMES = frozenset({".ds_store", "thumbs.db"})
IGNORED_SUFFIXES = (".txt", ".html", ".htm", ".pdf", ".rtf", ".doc")

# Mod top-level directory -> target root kind. The values are KIND LABELS
# keying paths.py's own vocabulary, not path segments.
_TARGET_FOR = {
    "data": "game",     # paths-guard: kind label, keys paths.game_root()
    "scripts": "sdk",   # paths-guard: kind label, keys paths.sdk_scripts()
}


def fold(rel) -> str:
    """The index key for a relative path: lowercase, forward slashes.

    BC ran on a case-insensitive filesystem, so mod authors were never
    forced to be consistent and overwhelmingly are not -- the reference mod
    alone spells Data/data, Ships/ships and .NIF/.nif. Folding here makes
    resolution correct on case-sensitive filesystems too.
    """
    return str(rel).replace("\\", "/").strip("/").lower()


@dataclass(frozen=True)
class ModFile:
    abs_path: Path
    mod_name: str
    target: str          # "game" or "sdk" -- a kind label, not a path segment
    rel: str             # folded, relative to that target root


@dataclass
class ModStatus:
    name: str
    content_root: Optional[Path]
    placed: int = 0
    ignored: int = 0
    unplaced: list = None        # top-level dir names we could not place

    def __post_init__(self):
        if self.unplaced is None:
            self.unplaced = []


@dataclass
class ModIndex:
    files: dict
    mods: list

    def lookup(self, rel) -> Optional[ModFile]:
        return self.files.get(fold(rel))

    def dirs_for(self, rel) -> list:
        """Every mod directory that provides files under `rel`.

        For the one consumer that hands a directory LIST to C++; a single
        file lookup should use lookup() instead.
        """
        prefix = fold(rel) + "/"
        seen = []
        for key, mf in self.files.items():
            if not key.startswith(prefix):
                continue
            depth = len(key[len(prefix):].split("/")) - 1
            d = mf.abs_path
            for _ in range(depth + 1):
                d = d.parent
            if d not in seen:
                seen.append(d)
        return seen


def _is_ignored(path: Path, content_root: Path) -> bool:
    if path.name.lower() in IGNORED_NAMES:
        return True
    # Documents at the content root only -- a readme buried in a model
    # folder is harmless to place, and BC content does include stray .txt.
    if path.parent == content_root and path.suffix.lower() in IGNORED_SUFFIXES:
        return True
    return False


def build_index(root: Path) -> ModIndex:
    """Index every enabled mod under `root`. O(mod files), never the install.

    Later mods win, and discover_mods() sorts by name, so the winner is
    deterministic across runs.
    """
    files: dict = {}
    statuses: list = []

    for candidate in discover_mods(root):
        status = ModStatus(name=candidate.name, content_root=candidate.content_root)
        statuses.append(status)
        if candidate.content_root is None:
            continue

        for path in sorted(candidate.content_root.rglob("*")):
            if not path.is_file():
                continue
            if _is_ignored(path, candidate.content_root):
                status.ignored += 1
                continue
            rel_parts = path.relative_to(candidate.content_root).parts
            top = rel_parts[0].lower()
            target = _TARGET_FOR.get(top)
            if target is None:
                if rel_parts[0] not in status.unplaced:
                    status.unplaced.append(rel_parts[0])
                continue
            # Under "scripts" the target root IS the scripts dir, so the
            # segment itself is dropped; under "data" it is kept, because
            # game_asset() is called with "data/..." paths.
            keep = rel_parts if target == "game" else rel_parts[1:]  # paths-guard: kind label
            rel = fold("/".join(keep))
            files[rel] = ModFile(abs_path=path, mod_name=candidate.name,
                                 target=target, rel=rel)
            status.placed += 1

    return ModIndex(files=files, mods=statuses)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_mods_index.py tests/unit/test_mods_discovery.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add engine/mods.py tests/unit/test_mods_index.py
git commit -m "feat(mods): build a case-folded index of mod-provided files"
```

---

### Task 3: Shadow classification and the boot report

**Files:**
- Modify: `engine/mods.py`
- Test: `tests/unit/test_mods_report.py`

**Interfaces:**
- Consumes: Task 2's `ModIndex`, `ModFile`, `ModStatus`
- Produces:
  - `classify(index, game_root: Path, sdk_scripts: Path) -> None` — mutates each `ModFile`'s owner status and fills `index.conflicts` / `index.overrides`
  - `ModIndex.conflicts: list[tuple[str, str, str]]` — `(rel, loser_mod, winner_mod)`
  - `ModIndex.overrides: list[str]` — folded rels shadowing stock files
  - `describe(index) -> str` — the boot report

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_mods_report.py
from pathlib import Path

from engine import mods


def _touch(p: Path, body: str = "x") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


def _roots(tmp_path):
    game = tmp_path / "stock_game"
    sdk = tmp_path / "stock_sdk"
    game.mkdir(); sdk.mkdir()
    return game, sdk


def test_pure_addition_is_neither_override_nor_conflict(tmp_path):
    game, sdk = _roots(tmp_path)
    _touch(tmp_path / "mods" / "M" / "Data" / "new.nif")
    idx = mods.build_index(tmp_path / "mods")
    mods.classify(idx, game, sdk)
    assert idx.overrides == []
    assert idx.conflicts == []


def test_stock_override_is_detected(tmp_path):
    game, sdk = _roots(tmp_path)
    _touch(game / "data" / "shared.nif", "stock")
    _touch(tmp_path / "mods" / "M" / "Data" / "shared.nif", "modded")
    idx = mods.build_index(tmp_path / "mods")
    mods.classify(idx, game, sdk)
    assert idx.overrides == ["data/shared.nif"]


def test_sdk_override_is_detected(tmp_path):
    game, sdk = _roots(tmp_path)
    _touch(sdk / "loadspacehelper.py", "stock")
    _touch(tmp_path / "mods" / "M" / "Scripts" / "loadspacehelper.py", "modded")
    idx = mods.build_index(tmp_path / "mods")
    mods.classify(idx, game, sdk)
    assert idx.overrides == ["loadspacehelper.py"]


def test_mod_conflict_names_loser_and_winner(tmp_path):
    game, sdk = _roots(tmp_path)
    _touch(tmp_path / "mods" / "Alpha" / "Data" / "a.nif")
    _touch(tmp_path / "mods" / "Bravo" / "Data" / "a.nif")
    idx = mods.build_index(tmp_path / "mods")
    mods.classify(idx, game, sdk)
    assert idx.conflicts == [("data/a.nif", "Alpha", "Bravo")]


def test_describe_reports_counts_and_warns_on_conflict(tmp_path):
    game, sdk = _roots(tmp_path)
    _touch(tmp_path / "mods" / "Alpha" / "Data" / "a.nif")
    _touch(tmp_path / "mods" / "Bravo" / "Data" / "a.nif")
    _touch(tmp_path / "mods" / "Bravo" / ".DS_Store")
    idx = mods.build_index(tmp_path / "mods")
    mods.classify(idx, game, sdk)
    text = mods.describe(idx)
    assert "Alpha" in text and "Bravo" in text
    assert "conflict" in text.lower()


def test_describe_is_empty_with_no_mods(tmp_path):
    game, sdk = _roots(tmp_path)
    idx = mods.build_index(tmp_path / "absent")
    mods.classify(idx, game, sdk)
    assert mods.describe(idx) == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_mods_report.py -v`
Expected: FAIL — `AttributeError: module 'engine.mods' has no attribute 'classify'`

- [ ] **Step 3: Write minimal implementation**

Add `conflicts: list` and `overrides: list` fields to `ModIndex` (defaulting to empty lists via `field(default_factory=list)`), record the losing mod during `build_index` when a key is replaced, then:

```python
def classify(index: ModIndex, game_root: Path, sdk_scripts: Path) -> None:
    """Fill index.overrides. Costs one stat PER MOD KEY -- never a walk of
    the install."""
    roots = {"game": game_root, "sdk": sdk_scripts}  # paths-guard: kind labels
    index.overrides = [
        rel for rel, mf in sorted(index.files.items())
        if (roots[mf.target] / mf.rel).exists()
    ]


def describe(index: ModIndex) -> str:
    """The boot report. Empty when no mods are installed."""
    if not index.mods:
        return ""
    lines = []
    for status in index.mods:
        if status.content_root is None:
            lines.append(f"  {status.name}: no BC content found -- not loaded")
            continue
        line = f"  {status.name}: {status.placed} files"
        if status.ignored:
            line += f", {status.ignored} ignored"
        if status.unplaced:
            line += f", unplaced: {', '.join(status.unplaced)}"
        lines.append(line)
    if index.overrides:
        lines.append(f"  {len(index.overrides)} stock file(s) overridden")
    for rel, loser, winner in index.conflicts:
        lines.append(f"  WARNING conflict: {rel} -- {winner} wins over {loser}")
    return "mods:\n" + "\n".join(lines)
```

To record conflicts, in `build_index`'s inner loop replace the bare assignment with:

```python
            existing = files.get(rel)
            if existing is not None and existing.mod_name != candidate.name:
                conflicts.append((rel, existing.mod_name, candidate.name))
            files[rel] = ModFile(...)
```

...collecting into a local `conflicts: list = []` and passing it to `ModIndex`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_mods_report.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add engine/mods.py tests/unit/test_mods_report.py
git commit -m "feat(mods): classify stock overrides and mod conflicts, report at boot"
```

---

### Task 4: Framework detection (unresolved imports)

**Files:**
- Modify: `engine/mods.py`
- Test: `tests/unit/test_mods_frameworks.py`

**Interfaces:**
- Consumes: Task 2's `ModIndex`, `ModStatus`
- Produces:
  - `KNOWN_FRAMEWORKS: frozenset[str]` == `{"Foundation", "FoundationTech", "FoundationTriggers", "Registry"}`
  - `detect_frameworks(index: ModIndex) -> None` — fills `ModStatus.requires: list[str]`
  - `_imported_names(source: str) -> set[str]` — `ast` with a regex fallback

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_mods_frameworks.py
from pathlib import Path

from engine import mods


def _touch(p: Path, body: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


def test_plain_import_is_detected():
    assert "Foundation" in mods._imported_names("import Foundation\n")


def test_from_import_is_detected():
    assert "Foundation" in mods._imported_names("from Foundation import ShipDef\n")


def test_dotted_import_records_the_root():
    assert "Foundation" in mods._imported_names("import Foundation.Sub\n")


def test_python15_syntax_falls_back_to_regex():
    # Backtick-repr is a SyntaxError under Python 3; the scan must survive it.
    src = "import Foundation\nx = `1`\n"
    assert "Foundation" in mods._imported_names(src)


def test_requires_is_recorded_per_mod(tmp_path):
    _touch(tmp_path / "M" / "Scripts" / "Custom" / "Ships" / "A.py",
           "import App\nimport Foundation\n")
    _touch(tmp_path / "M" / "Scripts" / "Ships" / "A.py", "import App\n")
    idx = mods.build_index(tmp_path)
    mods.detect_frameworks(idx)
    assert {m.name: m.requires for m in idx.mods}["M"] == ["Foundation"]


def test_mod_needing_nothing_records_nothing(tmp_path):
    _touch(tmp_path / "M" / "Scripts" / "Ships" / "A.py", "import App\n")
    idx = mods.build_index(tmp_path)
    mods.detect_frameworks(idx)
    assert {m.name: m.requires for m in idx.mods}["M"] == []


def test_a_mod_providing_the_framework_itself_does_not_require_it(tmp_path):
    _touch(tmp_path / "Found" / "Scripts" / "Foundation.py", "x = 1\n")
    _touch(tmp_path / "Found" / "Scripts" / "Custom" / "A.py", "import Foundation\n")
    idx = mods.build_index(tmp_path)
    mods.detect_frameworks(idx)
    assert {m.name: m.requires for m in idx.mods}["Found"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_mods_frameworks.py -v`
Expected: FAIL — `AttributeError: module 'engine.mods' has no attribute '_imported_names'`

- [ ] **Step 3: Write minimal implementation**

Add `requires: list = None` to `ModStatus` (defaulted in `__post_init__` like `unplaced`), then:

```python
import ast
import re

KNOWN_FRAMEWORKS = frozenset({
    "Foundation", "FoundationTech", "FoundationTriggers", "Registry",
})

_IMPORT_RE = re.compile(
    r"^\s*(?:import\s+([A-Za-z_][\w.]*)|from\s+([A-Za-z_][\w.]*)\s+import)",
    re.MULTILINE)


def _imported_names(source: str) -> set:
    """Root module names imported by `source`.

    Mod scripts are Python 1.5 era and may not parse under Python 3
    (backtick-repr, `has_key`), so a regex fallback covers what ast cannot.
    Same posture tests/unit/test_path_indirection.py takes for tools/probes/.
    """
    names = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        for m in _IMPORT_RE.finditer(source):
            raw = m.group(1) or m.group(2)
            names.add(raw.split(".")[0])
        return names

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def detect_frameworks(index: ModIndex) -> None:
    """Record which unavailable frameworks each mod imports.

    A mod that SUPPLIES the framework does not require it -- checked against
    the index, so a bundled Foundation counts as present.
    """
    provided = {Path(mf.rel).stem for mf in index.files.values()
                if mf.rel.endswith(".py")}
    by_mod: dict = {status.name: status for status in index.mods}
    for status in index.mods:
        status.requires = []

    for mf in index.files.values():
        if not mf.rel.endswith(".py"):
            continue
        try:
            source = mf.abs_path.read_text(errors="replace")
        except OSError:
            continue
        status = by_mod[mf.mod_name]
        for name in sorted(_imported_names(source)):
            if name in KNOWN_FRAMEWORKS and name.lower() not in provided \
                    and name not in status.requires:
                status.requires.append(name)
```

Extend `describe()` to append `requires: …  (unsupported)` when `status.requires` is non-empty.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_mods_frameworks.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add engine/mods.py tests/unit/test_mods_frameworks.py
git commit -m "feat(mods): detect unavailable frameworks a mod imports"
```

---

### Task 5: The module cache, and `game_asset()` integration

**Files:**
- Modify: `engine/mods.py`, `engine/paths.py:386-389`
- Test: `tests/unit/test_mods_game_asset.py`

**Interfaces:**
- Consumes: Tasks 2–4
- Produces:
  - `configure(index: ModIndex | None) -> None`
  - `current() -> ModIndex` (lazily builds an EMPTY index when unconfigured — never scans disk implicitly)
  - `paths.game_asset(rel)` returns the mod path when indexed, else `game_root() / rel` unchanged

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_mods_game_asset.py
from pathlib import Path

import pytest

from engine import mods, paths


def _touch(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x")


@pytest.fixture(autouse=True)
def _clear_index():
    mods.configure(None)
    yield
    mods.configure(None)


def test_zero_mods_is_byte_identical_to_the_stock_path(monkeypatch, tmp_path):
    # THE regression guard: a modless boot must not shift at all.
    monkeypatch.setattr(paths, "game_root", lambda: tmp_path / "g")
    assert paths.game_asset("data/Textures/x.tga") == tmp_path / "g" / "data/Textures/x.tga"


def test_unconfigured_index_does_not_scan_disk(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "game_root", lambda: tmp_path / "g")
    monkeypatch.setattr(mods, "discover_mods",
                        lambda root: pytest.fail("must not scan"))
    assert paths.game_asset("data/x.tga") == tmp_path / "g" / "data/x.tga"


def test_indexed_file_resolves_to_the_mod(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "game_root", lambda: tmp_path / "g")
    _touch(tmp_path / "mods" / "M" / "Data" / "Textures" / "X.TGA")
    mods.configure(mods.build_index(tmp_path / "mods"))
    got = paths.game_asset("data/Textures/x.tga")
    assert got == tmp_path / "mods" / "M" / "Data" / "Textures" / "X.TGA"


def test_unindexed_file_still_falls_back_to_stock(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "game_root", lambda: tmp_path / "g")
    _touch(tmp_path / "mods" / "M" / "Data" / "Textures" / "X.TGA")
    mods.configure(mods.build_index(tmp_path / "mods"))
    assert paths.game_asset("data/other.tga") == tmp_path / "g" / "data/other.tga"


def test_sdk_targeted_entries_do_not_leak_into_game_asset(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "game_root", lambda: tmp_path / "g")
    _touch(tmp_path / "mods" / "M" / "Scripts" / "ships" / "A.py")
    mods.configure(mods.build_index(tmp_path / "mods"))
    # "ships/A.py" is an SDK path; game_asset must not serve it.
    assert paths.game_asset("ships/A.py") == tmp_path / "g" / "ships/A.py"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_mods_game_asset.py -v`
Expected: FAIL — `AttributeError: module 'engine.mods' has no attribute 'configure'`

- [ ] **Step 3: Write minimal implementation**

In `engine/mods.py`:

```python
_INDEX: Optional[ModIndex] = None


def configure(index: Optional[ModIndex]) -> None:
    """Install the index every consumer reads. Pass None to clear (tests)."""
    global _INDEX
    _INDEX = index


def current() -> ModIndex:
    """The configured index, or an EMPTY one.

    Deliberately unlike paths.current(): it never builds from ambient state.
    A tool or test that has not opted in must see stock content, and an
    implicit disk scan on first asset lookup would be a surprising cost.
    """
    global _INDEX
    if _INDEX is None:
        _INDEX = ModIndex(files={}, mods=[])
    return _INDEX


def game_override(rel) -> Optional[Path]:
    """The mod file for a game-root-relative path, or None."""
    hit = current().lookup(rel)
    if hit is None or hit.target != "game":  # paths-guard: kind label
        return None
    return hit.abs_path
```

In `engine/paths.py`, replace `game_asset`:

```python
def game_asset(rel) -> Path:
    """Absolutise a BC-relative asset path, e.g. "data/Textures/x.tga".

    An installed mod that provides this path wins. Imported lazily, like
    settings_store in resolve(), so engine.mods can import engine.paths.
    """
    from engine import mods
    override = mods.game_override(rel)
    if override is not None:
        return override
    return game_root() / rel
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_mods_game_asset.py tests/unit/test_path_indirection.py -v`
Expected: PASS

- [ ] **Step 5: Run the full Python suite for regressions**

Run: `uv run pytest -q`
Expected: only `tests/known_failures.txt` entries fail. Compare, do not eyeball.

- [ ] **Step 6: Commit**

```bash
git add engine/mods.py engine/paths.py tests/unit/test_mods_game_asset.py
git commit -m "feat(mods): resolve game assets through the mod index"
```

---

### Task 6: Both `_SDKFinder` copies

**Files:**
- Modify: `tools/mission_harness.py:458-470`, `tests/conftest.py:487-499`
- Test: `tests/unit/test_mods_sdk_finder.py`

**Interfaces:**
- Consumes: Task 5's `mods.current()`
- Produces: `mods.sdk_override(module_rel: str) -> Path | None` in `engine/mods.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_mods_sdk_finder.py
from pathlib import Path

import pytest

from engine import mods


def _touch(p: Path, body: str = "x = 1\n") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


@pytest.fixture(autouse=True)
def _clear_index():
    mods.configure(None)
    yield
    mods.configure(None)


def test_sdk_override_returns_the_mod_module(tmp_path):
    _touch(tmp_path / "M" / "Scripts" / "ships" / "Fsteamr.py")
    mods.configure(mods.build_index(tmp_path))
    assert mods.sdk_override("ships/Fsteamr.py") is not None


def test_sdk_override_is_case_blind_both_ways(tmp_path):
    _touch(tmp_path / "M" / "Scripts" / "Ships" / "Fsteamr.py")
    mods.configure(mods.build_index(tmp_path))
    # BC's filesystem made Ships and ships one directory; so do we.
    assert mods.sdk_override("ships/Fsteamr.py") is not None
    assert mods.sdk_override("Ships/Fsteamr.py") is not None


def test_game_targeted_entries_do_not_leak_into_sdk_override(tmp_path):
    _touch(tmp_path / "M" / "Data" / "a.py")
    mods.configure(mods.build_index(tmp_path))
    assert mods.sdk_override("data/a.py") is None


def test_no_index_means_no_override(tmp_path):
    assert mods.sdk_override("ships/Fsteamr.py") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_mods_sdk_finder.py -v`
Expected: FAIL — `AttributeError: module 'engine.mods' has no attribute 'sdk_override'`

- [ ] **Step 3: Write minimal implementation**

In `engine/mods.py`:

```python
def sdk_override(module_rel) -> Optional[Path]:
    """The mod file for an SDK-scripts-relative path, or None."""
    hit = current().lookup(module_rel)
    if hit is None or hit.target != "sdk":  # paths-guard: kind label
        return None
    return hit.abs_path
```

In **both** `tools/mission_harness.py` and `tests/conftest.py`, inside `_SDKFinder.find_spec`, immediately after the `_PROJECT_ROOT` shadow checks and **before** the `candidate = sdk_scripts / (rel + ".py")` line:

```python
        # An installed mod's script wins over the stock SDK module. Checked
        # after the project-root shims (those are OUR replacements and must
        # not be overridable) and before the SDK itself.
        from engine import mods as _mods
        _override = _mods.sdk_override(rel + ".py")
        if _override is not None:
            loader = _SDKLoader(str(_override))
            return importlib.machinery.ModuleSpec(
                fullname, loader, origin=str(_override))
        _pkg_override = _mods.sdk_override(rel + "/__init__.py")
        if _pkg_override is not None:
            loader = _SDKLoader(str(_pkg_override))
            spec = importlib.machinery.ModuleSpec(
                fullname, loader, origin=str(_pkg_override))
            spec.submodule_search_locations = [str(Path(_pkg_override).parent)]
            return spec
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_mods_sdk_finder.py -v`
Expected: PASS

- [ ] **Step 5: Verify BOTH copies changed**

Run: `grep -c "sdk_override" tools/mission_harness.py tests/conftest.py`
Expected: a non-zero count for **both** files. A zero here is the duplicate-transform trap.

- [ ] **Step 6: Run the full Python suite**

Run: `uv run pytest -q`
Expected: only baselined failures.

- [ ] **Step 7: Commit**

```bash
git add engine/mods.py tools/mission_harness.py tests/conftest.py tests/unit/test_mods_sdk_finder.py
git commit -m "feat(mods): let mod scripts override SDK modules in both finders"
```

---

### Task 7: Icon consumers (directory-then-join → single lookup)

**Files:**
- Modify: `engine/ui/ship_icons.py`, `engine/ui/weapon_icons.py`, `engine/ui/damage_icons.py`
- Test: `tests/unit/test_mods_consumers.py`

**Interfaces:**
- Consumes: Task 5's `paths.game_asset`
- Produces: `ship_icons._game_icon_file(stem) -> Path`, `weapon_icons._game_icon_file(stem) -> Path`, `damage_icons._game_icon_file(stem) -> Path`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_mods_consumers.py
from pathlib import Path

import pytest

from engine import mods, paths


def _touch(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x")


@pytest.fixture(autouse=True)
def _clear_index():
    mods.configure(None)
    yield
    mods.configure(None)


def test_ship_icon_path_prefers_a_mod(monkeypatch, tmp_path):
    from engine.ui import ship_icons
    monkeypatch.setattr(paths, "game_root", lambda: tmp_path / "g")
    _touch(tmp_path / "mods" / "M" / "Data" / "Icons" / "Ships" / "Fsteamr.tga")
    mods.configure(mods.build_index(tmp_path / "mods"))
    got = ship_icons._game_icon_file("Fsteamr")
    assert got == tmp_path / "mods" / "M" / "Data" / "Icons" / "Ships" / "Fsteamr.tga"


def test_ship_icon_path_falls_back_to_stock(monkeypatch, tmp_path):
    from engine.ui import ship_icons
    monkeypatch.setattr(paths, "game_root", lambda: tmp_path / "g")
    got = ship_icons._game_icon_file("Galaxy")
    assert got == tmp_path / "g" / "data/Icons/Ships/Galaxy.tga"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_mods_consumers.py -v`
Expected: FAIL — `AttributeError: module 'engine.ui.ship_icons' has no attribute '_game_icon_file'`

- [ ] **Step 3: Write minimal implementation**

In `engine/ui/ship_icons.py`, add alongside the existing `_game_icons_dir()`:

```python
def _game_icon_file(stem: str):
    """The TGA for one species, mod-aware.

    Resolved as a single relative path rather than dir-then-join so an
    installed mod's icon is found by the index. Resolved at USE.
    """
    from engine import paths
    return paths.game_asset(f"data/Icons/Ships/{stem}.tga")
```

Replace the call site that joins `_game_icons_dir()` with a filename so it calls `_game_icon_file(stem)`.

Apply the identical pattern in the other two modules, changing only the relative path and keeping each module's existing stem-building logic untouched:

```python
# engine/ui/weapon_icons.py
def _game_icon_file(stem: str):
    from engine import paths
    return paths.game_asset(f"data/Icons/{stem}.tga")

# engine/ui/damage_icons.py
def _game_icon_file(stem: str):
    from engine import paths
    return paths.game_asset(f"data/Icons/Damage/{stem}.tga")
```

Leave `_game_icons_dir()` in place in all three modules if anything else still calls it; delete it only where it becomes unused.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_mods_consumers.py -v`
Expected: PASS

- [ ] **Step 5: Run the full Python suite**

Run: `uv run pytest -q`
Expected: only baselined failures.

- [ ] **Step 6: Commit**

```bash
git add engine/ui/ship_icons.py engine/ui/weapon_icons.py engine/ui/damage_icons.py tests/unit/test_mods_consumers.py
git commit -m "feat(mods): resolve icon files through the mod index"
```

---

### Task 8: Directory-search consumers

**Files:**
- Modify: `engine/paths.py`, `engine/host_loop.py` (`_ship_texture_search` ~4347, planet search ~4829 and ~5465, bridge texture dirs ~5848 and ~5887), `engine/missions/name_resolver.py:16-20`, `engine/appc/viewscreen_static.py:29`
- Test: `tests/unit/test_mods_search_dirs.py`

**Interfaces:**
- Consumes: Task 2's `ModIndex.dirs_for`, Task 5's `mods.current()`
- Produces: `paths.game_asset_dirs(rel) -> list[Path]` — mod directories first (later mods win), then the stock directory. Always returns at least the stock directory.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_mods_search_dirs.py
from pathlib import Path

import pytest

from engine import mods, paths


def _touch(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x")


@pytest.fixture(autouse=True)
def _clear_index():
    mods.configure(None)
    yield
    mods.configure(None)


def test_no_mods_yields_only_the_stock_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "game_root", lambda: tmp_path / "g")
    assert paths.game_asset_dirs("data/TGL") == [tmp_path / "g" / "data/TGL"]


def test_mod_dirs_come_first(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "game_root", lambda: tmp_path / "g")
    _touch(tmp_path / "mods" / "M" / "Data" / "TGL" / "Extra.TGL")
    mods.configure(mods.build_index(tmp_path / "mods"))
    got = paths.game_asset_dirs("data/TGL")
    assert got == [tmp_path / "mods" / "M" / "Data" / "TGL",
                   tmp_path / "g" / "data/TGL"]


def test_every_providing_mod_contributes(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "game_root", lambda: tmp_path / "g")
    _touch(tmp_path / "mods" / "Alpha" / "Data" / "TGL" / "a.TGL")
    _touch(tmp_path / "mods" / "Bravo" / "Data" / "TGL" / "b.TGL")
    mods.configure(mods.build_index(tmp_path / "mods"))
    got = paths.game_asset_dirs("data/TGL")
    assert len(got) == 3
    assert got[-1] == tmp_path / "g" / "data/TGL"


def test_a_mod_providing_nothing_there_is_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "game_root", lambda: tmp_path / "g")
    _touch(tmp_path / "mods" / "M" / "Data" / "Icons" / "a.tga")
    mods.configure(mods.build_index(tmp_path / "mods"))
    assert paths.game_asset_dirs("data/TGL") == [tmp_path / "g" / "data/TGL"]


def test_tgl_roots_include_mod_dirs(monkeypatch, tmp_path):
    from engine.missions import name_resolver
    monkeypatch.setattr(paths, "game_root", lambda: tmp_path / "g")
    monkeypatch.setattr(paths, "sdk_data", lambda: tmp_path / "s")
    _touch(tmp_path / "mods" / "M" / "Data" / "TGL" / "FTBShips.TGL")
    mods.configure(mods.build_index(tmp_path / "mods"))
    roots = name_resolver._tgl_roots()
    assert tmp_path / "mods" / "M" / "Data" / "TGL" in roots
    assert tmp_path / "s" / "TGL" in roots
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_mods_search_dirs.py -v`
Expected: FAIL — `AttributeError: module 'engine.paths' has no attribute 'game_asset_dirs'`

- [ ] **Step 3: Write minimal implementation**

In `engine/paths.py`, beside `game_asset`:

```python
def game_asset_dirs(rel) -> list:
    """Every directory to SEARCH for `rel`, mod directories first.

    game_asset() answers "which file?", which a caller that scans a
    directory cannot use. Always includes the stock directory last, so a
    modless call is exactly today's single-directory behaviour wrapped in a
    list.
    """
    from engine import mods
    return [*mods.current().dirs_for(rel), game_root() / rel]
```

Then convert each Shape-B site. `engine/missions/name_resolver.py`:

```python
def _tgl_roots() -> tuple:
    """Every TGL source, resolved at USE: SDK, then mod dirs, then stock."""
    from engine import paths
    return (paths.sdk_data() / "TGL", *paths.game_asset_dirs("data/TGL"))
```

`engine/appc/viewscreen_static.py:29` — return the list instead of one path, and update its caller to iterate:

```python
    return paths.game_asset_dirs("data/Textures/Effects")
```

`engine/host_loop.py` `_ship_texture_search` (~4347) — replace the two shared-directory entries and prepend per-ship mod dirs:

```python
    return [
        str(Path(nif_path).parent / tier),
        *[str(p) for p in _paths.game_asset_dirs(f"{share}/{tier}")],
        *[str(p) for p in _paths.game_asset_dirs(DEFAULT_TEXTURE_SEARCH)],
        *[str(p) for p in _paths.game_asset_dirs(
            "data/Models/SharedTextures/FedBases/High")],
    ]
```

At `~4829` and `~5465`, `planet_tex_search` becomes a list; pass every entry where one was passed before. At `~5848` and `~5887`, apply `game_asset_dirs` to the bridge texture directories the same way.

**If a native binding accepts only a single search directory**, do not silently drop the mod dirs: pass the first entry that exists on disk, and leave a comment naming the binding as the limitation. Record it in the plan's follow-ups rather than widening the C++ API in this task.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_mods_search_dirs.py -v`
Expected: PASS

- [ ] **Step 5: Run the full Python suite**

Run: `uv run pytest -q`
Expected: only baselined failures. Texture and TGL resolution are widely exercised, so a break here shows up immediately.

- [ ] **Step 6: Commit**

```bash
git add engine/paths.py engine/host_loop.py engine/missions/name_resolver.py engine/appc/viewscreen_static.py tests/unit/test_mods_search_dirs.py
git commit -m "feat(mods): search mod directories for TGL, textures and effects"
```

---

### Task 9: The C++ override map

**Files:**
- Modify: `native/src/renderer/include/renderer/asset_path.h`, `native/src/renderer/asset_path.cc`, `native/src/host/host_bindings.cc`, `engine/renderer.py:32`
- Test: `native/tests/renderer/asset_path_test.cc`

**Interfaces:**
- Consumes: nothing from earlier tasks (pure C++ plus a binding)
- Produces:
  - `renderer::set_asset_overrides(const std::map<std::string, std::string>&)`
  - `renderer::clear_asset_overrides()`
  - `_dauntless_host.set_asset_overrides(dict)` → `renderer.set_asset_overrides`

- [ ] **Step 1: Write the failing test**

Append to `native/tests/renderer/asset_path_test.cc`:

```cpp
// --- mod overrides ----------------------------------------------------------
//
// A mod's file lives outside the game root entirely, so the root prefix can
// never name it. The map is consulted first, keyed by the same case-folded
// relative path engine/mods.py builds.

namespace {
struct OverrideGuard {
    ~OverrideGuard() { renderer::clear_asset_overrides(); }
};
}  // namespace

TEST(AssetPath, OverrideWinsOverTheRootPrefix) {
    OverrideGuard guard;
    renderer::set_asset_overrides({{"data/textures/spacedust.tga",
                                    "/mods/M/Data/Textures/SpaceDust.tga"}});
    EXPECT_EQ(resolve_asset_path("data/Textures/spacedust.tga"),
              "/mods/M/Data/Textures/SpaceDust.tga");
}

TEST(AssetPath, OverrideLookupIsCaseInsensitive) {
    OverrideGuard guard;
    renderer::set_asset_overrides({{"data/textures/spacedust.tga", "/mods/x.tga"}});
    EXPECT_EQ(resolve_asset_path("DATA/Textures/SPACEDUST.TGA"), "/mods/x.tga");
}

TEST(AssetPath, UnmatchedPathsStillUseTheRoot) {
    OverrideGuard guard;
    renderer::set_asset_overrides({{"data/textures/spacedust.tga", "/mods/x.tga"}});
    EXPECT_EQ(resolve_asset_path("data/rough.tga"), "game/data/rough.tga");
}

TEST(AssetPath, ClearRestoresStockResolution) {
    renderer::set_asset_overrides({{"data/rough.tga", "/mods/x.tga"}});
    renderer::clear_asset_overrides();
    EXPECT_EQ(resolve_asset_path("data/rough.tga"), "game/data/rough.tga");
}

TEST(AssetPath, AbsolutePathsAreNotOverridden) {
    OverrideGuard guard;
    renderer::set_asset_overrides({{"/abs/path.tga", "/mods/x.tga"}});
    EXPECT_EQ(resolve_asset_path("/abs/path.tga"), "/abs/path.tga");
}

TEST(AssetPath, NoOverridesIsByteIdenticalToStock) {
    OverrideGuard guard;
    renderer::set_asset_overrides({});
    EXPECT_EQ(resolve_asset_path("data/rough.tga"), "game/data/rough.tga");
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cmake -B build -S . && cmake --build build -j --target renderer_tests`
Expected: FAIL to compile — `'set_asset_overrides' is not a member of 'renderer'`

- [ ] **Step 3: Write minimal implementation**

In `asset_path.h`, before `resolve_asset_path`:

```cpp
/// Files supplied by installed mods, keyed by the case-folded relative path
/// (lowercase, forward slashes) that engine/mods.py builds. A mod's file
/// lives outside the game root, so no prefix can reach it -- this map is the
/// only way C++-internal asset loads see mod content. Empty by default, so a
/// modless run resolves byte-identically to before.
void set_asset_overrides(const std::map<std::string, std::string>& overrides);
void clear_asset_overrides();
```

...with `#include <map>` added.

In `asset_path.cc`:

```cpp
std::map<std::string, std::string>& mutable_overrides() {
    static std::map<std::string, std::string> overrides;
    return overrides;
}

std::string fold_key(const std::string& path) {
    std::string out;
    out.reserve(path.size());
    for (char c : path) {
        out.push_back(c == kBackslash ? '/'
                                      : static_cast<char>(std::tolower(
                                            static_cast<unsigned char>(c))));
    }
    return out;
}
```

...then at the top of `resolve_asset_path`, after the empty and absolute guards:

```cpp
    const auto& overrides = mutable_overrides();
    if (!overrides.empty()) {
        const auto it = overrides.find(fold_key(path));
        if (it != overrides.end()) return it->second;
    }
```

...and the two setters:

```cpp
void set_asset_overrides(const std::map<std::string, std::string>& overrides) {
    mutable_overrides() = overrides;
}

void clear_asset_overrides() { mutable_overrides().clear(); }
```

In `host_bindings.cc`, next to the existing `set_game_root` binding (~line 1682):

```cpp
    m.def("set_asset_overrides",
          [](const std::map<std::string, std::string>& overrides) {
              renderer::set_asset_overrides(overrides);
          },
          "Install mod asset overrides, keyed by case-folded relative path.");
```

In `engine/renderer.py`, add `"set_asset_overrides"` to `_REQUIRED_BINDINGS` and to the `__all__`-style export list beside `set_game_root`, plus:

```python
def set_asset_overrides(overrides: dict) -> None:
    """Install mod asset overrides in the renderer (case-folded keys)."""
    _h.set_asset_overrides(overrides)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cmake --build build -j --target renderer_tests && ./build/native/tests/renderer_tests --gtest_filter='AssetPath.*'`
Expected: PASS, all `AssetPath.*` cases

- [ ] **Step 5: Rebuild the host so the new binding exists**

Run: `cmake --build build -j`
Expected: success. A stale `.so` here causes `AttributeError: module '_dauntless_host' has no attribute 'set_asset_overrides'` at boot — rebuild, never work around it in Python.

- [ ] **Step 6: Commit**

```bash
git add native/src/renderer/include/renderer/asset_path.h native/src/renderer/asset_path.cc native/src/host/host_bindings.cc engine/renderer.py native/tests/renderer/asset_path_test.cc
git commit -m "feat(mods): let mod files override C++-resolved asset paths"
```

---

### Task 10: Boot wiring

**Files:**
- Modify: `engine/host_loop.py` (after `_paths.configure(resolution)` ~line 7132, and near `r.set_game_root(...)` ~line 7263)
- Test: `tests/unit/test_mods_boot.py`

**Interfaces:**
- Consumes: every earlier task
- Produces: `engine.mods.install(argv=None, env=None) -> ModIndex` — the one call boot makes

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_mods_boot.py
from pathlib import Path

import pytest

from engine import mods, paths


def _touch(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x")


@pytest.fixture(autouse=True)
def _clear_index():
    mods.configure(None)
    yield
    mods.configure(None)


def test_install_builds_classifies_and_configures(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "game_root", lambda: tmp_path / "g")
    monkeypatch.setattr(paths, "sdk_scripts", lambda: tmp_path / "s")
    (tmp_path / "g").mkdir(); (tmp_path / "s").mkdir()
    _touch(tmp_path / "mods" / "M" / "Data" / "a.nif")
    _touch(tmp_path / "mods" / "M" / "Scripts" / "Custom" / "x.py",)
    (tmp_path / "mods" / "M" / "Scripts" / "Custom" / "x.py").write_text(
        "import Foundation\n")

    idx = mods.install(argv=["--mods-dir", str(tmp_path / "mods")], env={})

    assert mods.current() is idx
    assert idx.lookup("data/a.nif") is not None
    assert {m.name: m.requires for m in idx.mods}["M"] == ["Foundation"]


def test_install_with_no_mods_dir_is_an_empty_index(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "game_root", lambda: tmp_path / "g")
    monkeypatch.setattr(paths, "sdk_scripts", lambda: tmp_path / "s")
    idx = mods.install(argv=["--mods-dir", str(tmp_path / "absent")], env={})
    assert idx.files == {}
    assert mods.describe(idx) == ""


def test_renderer_override_payload_is_game_targets_only(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "game_root", lambda: tmp_path / "g")
    monkeypatch.setattr(paths, "sdk_scripts", lambda: tmp_path / "s")
    (tmp_path / "g").mkdir(); (tmp_path / "s").mkdir()
    _touch(tmp_path / "mods" / "M" / "Data" / "a.nif")
    _touch(tmp_path / "mods" / "M" / "Scripts" / "b.py")
    idx = mods.install(argv=["--mods-dir", str(tmp_path / "mods")], env={})
    payload = mods.renderer_overrides(idx)
    assert list(payload) == ["data/a.nif"]
    assert payload["data/a.nif"].endswith("a.nif")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_mods_boot.py -v`
Expected: FAIL — `AttributeError: module 'engine.mods' has no attribute 'install'`

- [ ] **Step 3: Write minimal implementation**

In `engine/mods.py`:

```python
def renderer_overrides(index: ModIndex) -> dict:
    """The game-targeted subset, as {folded_rel: abs_path_str}, for C++."""
    return {rel: str(mf.abs_path) for rel, mf in sorted(index.files.items())
            if mf.target == "game"}  # paths-guard: kind label


def install(argv=None, env=None) -> ModIndex:
    """Build, classify, scan and install the index. Called once at boot,
    AFTER paths.configure() -- mapping Data/ and Scripts/ to their targets
    needs the resolved roots."""
    index = build_index(mods_root(argv=argv, env=env))
    classify(index, paths.game_root(), paths.sdk_scripts())
    detect_frameworks(index)
    configure(index)
    return index
```

In `engine/host_loop.py`, immediately after `_paths.configure(resolution)`:

```python
    # Mods layer over the resolved roots, so this must follow configure().
    from engine import mods as _mods
    _mod_index = _mods.install(argv=argv, env=env)
    _report = _mods.describe(_mod_index)
    if _report:
        print(_report, file=_sys.stderr)
```

...and immediately after `r.set_game_root(str(_paths.game_root()))`:

```python
    r.set_asset_overrides(_mods.renderer_overrides(_mods.current()))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_mods_boot.py -v`
Expected: PASS

- [ ] **Step 5: Run the FULL gate**

Run: `scripts/check_tests.sh`
Expected: exit 0. Any failure it names that is **not** in `tests/known_failures.txt` is a regression this branch introduced — fix it, do not baseline it.

- [ ] **Step 6: Commit**

```bash
git add engine/mods.py engine/host_loop.py tests/unit/test_mods_boot.py
git commit -m "feat(mods): build and install the mod index at boot"
```

---

## Live verification (Mark only)

The gate cannot see game feel or asset paths, and this project's convention is that **Claude never launches the game**. After Task 10, Mark should verify in the main checkout (not this worktree — runtime deps and `mods/` live there):

1. Boot with no mods → the stderr report is absent and nothing changes.
2. Drop the reference Steamrunner mod into `mods/` → boot prints `Steamrunner Aad: 42 files … requires: Foundation, FoundationTech (unsupported)`.
3. QuickBattle → the ship is **not** in the menus (expected: that half needs Foundation).
4. Confirm the ship's model loads if spawned by script — `Data/Models/Ships/Steamrunner_Aad/Fsteamr.NIF` resolving through the index despite the `.nif` spelling in `GetShipStats()` is the single most important thing to see working.

Step 4 is the real acceptance test for this plan: it exercises discovery, case folding, the two-root mapping, and `game_asset()` in one action.
