# Mission Initialize Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `tools/mission_harness.py` — a standalone script that discovers all 35 SDK mission scripts, attempts `Initialize(pMission)` on each, and prints a ranked summary of failures so we know exactly what to implement next.

**Architecture:** A standalone Python script (runnable via `uv run python tools/mission_harness.py`) that replicates the SDK compatibility setup from `tests/conftest.py`, discovers missions by scanning for `def Initialize(pMission)` in SDK scripts, runs each in isolation by evicting freshly-imported modules between runs, and groups failures by error type for prioritised reporting. No pytest involvement — expected failures are output to be read, not counted as test regressions.

**Tech Stack:** Python 3 stdlib only (`pathlib`, `importlib`, `ast`, `collections`, `sys`); `engine.core.game` from this project.

---

## Background: how the SDK import machinery works

`tests/conftest.py` installs three things at pytest startup that make SDK scripts importable:

1. **`_SDKFinder`** — a `sys.meta_path` finder that maps `"Foo.Bar.Baz"` → `sdk/Build/scripts/Foo/Bar/Baz.py` (or `__init__.py` for packages) and loads them via `_SDKLoader`.
2. **`_SDKLoader`** — applies two AST transformers before `exec()`: `_MoveGlobalsToTop` (Python 1.5 global-declaration ordering) and `_FixDottedImport` (rewrites `__import__(x)` → `importlib.import_module(x)` to restore Python 1.5 leaf-module semantics).
3. **Stub modules** — `loadspacehelper`, `LoadBridge`, `Bridge.HelmMenuHandlers` as `_StubModule` (callable attributes returning None); `Bridge.*` and others as plain `types.ModuleType`.

The harness must replicate this setup before importing any SDK scripts.

---

## File map

| Status | Path | What changes |
|--------|------|--------------|
| Create | `tools/mission_harness.py` | Discovery, SDK setup, runner, reporter |
| Create | `tests/unit/test_mission_harness.py` | Unit tests for discovery function |

---

### Task 1: Mission discovery + unit test

The discovery function scans `sdk/Build/scripts/` recursively for `.py` files containing `def Initialize(pMission)` and converts their paths to dotted module names. Episode-level scripts (which use `def Initialize(pEpisode)`) are naturally excluded.

**Files:**
- Create: `tools/mission_harness.py`
- Create: `tests/unit/test_mission_harness.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_mission_harness.py`:

```python
def test_discover_missions_finds_m1basic():
    from tools.mission_harness import discover_missions
    missions = discover_missions()
    assert "Custom.Tutorial.Episode.M1Basic.M1Basic" in missions


def test_discover_missions_count():
    from tools.mission_harness import discover_missions
    missions = discover_missions()
    # SDK has 35 files with def Initialize(pMission) — sanity-check the range
    assert 30 <= len(missions) <= 40


def test_discover_missions_no_init_files():
    from tools.mission_harness import discover_missions
    missions = discover_missions()
    assert not any("__init__" in m for m in missions)


def test_discover_missions_no_episode_scripts():
    from tools.mission_harness import discover_missions
    # Episode-level scripts use Initialize(pEpisode), not Initialize(pMission)
    missions = discover_missions()
    assert not any(m.endswith("Episode1") or m.endswith("Episode5") for m in missions)
```

- [ ] **Step 2: Verify the tests fail**

```bash
export PATH="$HOME/.local/bin:$PATH"
uv run pytest tests/unit/test_mission_harness.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'tools.mission_harness'`

- [ ] **Step 3: Write the discovery function**

Create `tools/mission_harness.py`:

```python
"""
Mission Initialize harness for open_stbc.

Discovers all SDK mission scripts and attempts Initialize(pMission) on each,
reporting a ranked summary of failures.

Usage:
    uv run python tools/mission_harness.py
"""
import ast
import importlib
import importlib.abc
import importlib.machinery
import sys
import types
import warnings
from collections import Counter
from pathlib import Path

# Ensure project root is on sys.path whether run as script or imported in tests
_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

SDK_SCRIPTS = _PROJECT_ROOT / "sdk" / "Build" / "scripts"


def discover_missions() -> list[str]:
    """Return sorted list of dotted module names for all SDK mission scripts.

    A mission script is any .py file (not __init__.py) that contains the
    string 'def Initialize(pMission)'.  Episode-level scripts use
    'def Initialize(pEpisode)' and are therefore excluded automatically.
    """
    missions = []
    for py_file in sorted(SDK_SCRIPTS.rglob("*.py")):
        if py_file.name == "__init__.py":
            continue
        try:
            text = py_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "def Initialize(pMission)" not in text:
            continue
        rel = py_file.relative_to(SDK_SCRIPTS)
        module_name = ".".join(rel.with_suffix("").parts)
        missions.append(module_name)
    return missions
```

- [ ] **Step 4: Verify the tests pass**

```bash
export PATH="$HOME/.local/bin:$PATH"
uv run pytest tests/unit/test_mission_harness.py -v
```

Expected: all 4 PASS

- [ ] **Step 5: Run full suite — no regressions**

```bash
export PATH="$HOME/.local/bin:$PATH"
uv run pytest -v
```

Expected: 36 previously passing + 4 new = 40 PASS

- [ ] **Step 6: Commit**

```bash
git add tools/mission_harness.py tests/unit/test_mission_harness.py
git commit -m "feat(harness): mission discovery function"
```

---

### Task 2: SDK setup + per-mission runner

The harness needs the same compatibility machinery as `tests/conftest.py` — copy the necessary classes (no shared module needed; the harness is a standalone tool). Then add a `run_mission()` function that creates a fresh game context, runs `Initialize()`, and cleans up `sys.modules` between runs.

**Files:**
- Modify: `tools/mission_harness.py`

- [ ] **Step 1: Add SDK compatibility classes and `setup_sdk()`**

Append to `tools/mission_harness.py` after the `discover_missions` function:

```python
# ── SDK compatibility machinery ───────────────────────────────────────────────
# Mirrors tests/conftest.py.  Kept separate so the harness has no pytest dep.

class _MoveGlobalsToTop(ast.NodeTransformer):
    def visit_FunctionDef(self, node):
        self.generic_visit(node)
        globals_stmts = [s for s in node.body if isinstance(s, ast.Global)]
        other_stmts = [s for s in node.body if not isinstance(s, ast.Global)]
        node.body = globals_stmts + other_stmts
        return node
    visit_AsyncFunctionDef = visit_FunctionDef


class _FixDottedImport(ast.NodeTransformer):
    def visit_Module(self, node):
        self.generic_visit(node)
        node.body.insert(0, ast.Import(
            names=[ast.alias(name="importlib", asname="_sdk_importlib")]
        ))
        return node

    def visit_Call(self, node):
        self.generic_visit(node)
        if (
            isinstance(node.func, ast.Name)
            and node.func.id == "__import__"
            and len(node.args) == 1
            and not node.keywords
        ):
            return ast.Call(
                func=ast.Attribute(
                    value=ast.Name(id="_sdk_importlib", ctx=ast.Load()),
                    attr="import_module",
                    ctx=ast.Load(),
                ),
                args=node.args,
                keywords=[],
            )
        return node


class _StubModule(types.ModuleType):
    def __getattr__(self, name):
        return lambda *args, **kwargs: None


class _SDKLoader(importlib.abc.Loader):
    def __init__(self, path: str):
        self.path = path

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        with open(self.path, encoding="utf-8", errors="replace") as f:
            source = f.read()
        source = source.expandtabs(4)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tree = ast.parse(source, filename=self.path)
        tree = _MoveGlobalsToTop().visit(tree)
        tree = _FixDottedImport().visit(tree)
        ast.fix_missing_locations(tree)
        code = compile(tree, self.path, "exec")
        exec(code, module.__dict__)


class _SDKFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        rel = fullname.replace(".", "/")
        if (_PROJECT_ROOT / (rel + ".py")).exists():
            return None
        if (_PROJECT_ROOT / rel).is_dir() and (_PROJECT_ROOT / rel / "__init__.py").exists():
            return None
        candidate = SDK_SCRIPTS / (rel + ".py")
        if candidate.exists():
            loader = _SDKLoader(str(candidate))
            return importlib.machinery.ModuleSpec(fullname, loader, origin=str(candidate))
        pkg_init = SDK_SCRIPTS / rel / "__init__.py"
        if pkg_init.exists():
            loader = _SDKLoader(str(pkg_init))
            spec = importlib.machinery.ModuleSpec(fullname, loader, origin=str(pkg_init))
            spec.submodule_search_locations = [str(pkg_init.parent)]
            return spec
        return None


_BASELINE_MODULES: set[str] = set()


def setup_sdk() -> None:
    """Install SDK finder and stub modules.  Call once before run_mission()."""
    global _BASELINE_MODULES

    if not any(isinstance(f, _SDKFinder) for f in sys.meta_path):
        sys.meta_path.insert(0, _SDKFinder())

    _callable_stubs = ["loadspacehelper", "LoadBridge"]
    for name in _callable_stubs:
        if name not in sys.modules:
            sys.modules[name] = _StubModule(name)

    if "Bridge" not in sys.modules:
        sys.modules["Bridge"] = types.ModuleType("Bridge")
    if "Bridge.HelmMenuHandlers" not in sys.modules:
        _helm = _StubModule("Bridge.HelmMenuHandlers")
        sys.modules["Bridge.HelmMenuHandlers"] = _helm
        sys.modules["Bridge"].HelmMenuHandlers = _helm  # type: ignore[attr-defined]

    _plain_stubs = [
        "Bridge.TacticalCharacterHandlers",
        "Bridge.HelmCharacterHandlers",
        "Bridge.XOCharacterHandlers",
        "Bridge.ScienceCharacterHandlers",
        "Bridge.EngineerCharacterHandlers",
        "BridgeHandlers",
        "Actions",
        "Actions.MissionScriptActions",
    ]
    for name in _plain_stubs:
        if name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)

    _BASELINE_MODULES = set(sys.modules.keys())
```

- [ ] **Step 2: Add `run_mission()`**

Append to `tools/mission_harness.py`:

```python
def run_mission(module_name: str) -> tuple[str, Exception | None]:
    """Import module_name and call Initialize(pMission).

    Returns ("pass", None) on success or ("fail", exc) on any exception.
    Cleans up all sys.modules entries added during the run so each mission
    starts from the same baseline state.
    """
    from engine.core.game import Game, Episode, Mission, _set_current_game

    mission = Mission()
    episode = Episode()
    episode.SetCurrentMission(mission)
    game = Game()
    game.SetCurrentEpisode(episode)
    _set_current_game(game)

    try:
        mod = importlib.import_module(module_name)
        mod.Initialize(mission)
        return ("pass", None)
    except Exception as exc:
        return ("fail", exc)
    finally:
        _set_current_game(None)
        for key in [k for k in sys.modules if k not in _BASELINE_MODULES]:
            del sys.modules[key]
```

- [ ] **Step 3: Run the full suite — no regressions**

```bash
export PATH="$HOME/.local/bin:$PATH"
uv run pytest -v
```

Expected: 40 PASS (no regressions from adding dead code to the harness)

- [ ] **Step 4: Commit**

```bash
git add tools/mission_harness.py
git commit -m "feat(harness): SDK setup and per-mission runner"
```

---

### Task 3: Summary output, `main()`, and first run

**Files:**
- Modify: `tools/mission_harness.py`

- [ ] **Step 1: Add `main()` and the script entry point**

Append to `tools/mission_harness.py`:

```python
def main() -> None:
    setup_sdk()
    missions = discover_missions()

    print("open_stbc mission harness")
    print("=" * 50)
    print(f"Found {len(missions)} missions\n")
    print("Running Initialize()...\n")

    results: dict[str, tuple[str, Exception | None]] = {}
    for name in missions:
        status, exc = run_mission(name)
        results[name] = (status, exc)
        marker = "PASS" if status == "pass" else "FAIL"
        short = name.split(".")[-1]  # last component for readability
        if exc:
            err_line = str(exc).splitlines()[0][:90]
            print(f"  {marker}  {name}")
            print(f"         {type(exc).__name__}: {err_line}")
        else:
            print(f"  {marker}  {name}")

    passed = sum(1 for s, _ in results.values() if s == "pass")
    failed = len(results) - passed
    print(f"\n{'=' * 50}")
    print(f"Results: {passed} passed, {failed} failed of {len(results)} total")

    if failed:
        errors: Counter[str] = Counter()
        for status, exc in results.values():
            if exc is not None:
                key = f"{type(exc).__name__}: {str(exc).splitlines()[0][:80]}"
                errors[key] += 1
        print(f"\nTop errors ({len(errors)} distinct):")
        for msg, count in errors.most_common(15):
            print(f"  [{count:2d}]  {msg}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the harness and capture output**

```bash
export PATH="$HOME/.local/bin:$PATH"
uv run python tools/mission_harness.py 2>&1 | tee /tmp/harness_run.txt
```

Expected: output listing all 35 missions, most failing, with a ranked error summary at the bottom. The output file can be referenced when planning the next implementation phase.

- [ ] **Step 3: Run the full test suite — no regressions**

```bash
export PATH="$HOME/.local/bin:$PATH"
uv run pytest -v
```

Expected: 40 PASS

- [ ] **Step 4: Commit**

```bash
git add tools/mission_harness.py
git commit -m "feat(harness): summary output and main(); ready to run"
```
