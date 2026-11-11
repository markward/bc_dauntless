# No SDK at Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The game loads every stock BC script by lifting the retail `.pyc` in the player's install and never reads the SDK; developers and tests still use the SDK.

**Architecture:** A new runtime module `engine/stock_scripts.py` owns "where stock scripts come from": a committed, generated manifest of the retail `.pyc` paths and their known hashes, case-insensitive lookup in the install's `scripts/` folder, the lift (through `engine.py15`) with a one-time warning for unknown hashes, a boot-time install check, the synthetic `Custom` package, and a test-only fixture overlay for the SDK's tutorial sample. Both SDK-loader twins resolve stock modules through it. `engine/paths.py` loses the SDK root. A dev-only `tools/dev_sdk.py` finds the SDK for tests and tools, and a guard test keeps it out of the game.

**Tech Stack:** Python 3.11 (`ast`, `importlib`, `hashlib`), the existing `engine.py15` lifter, pytest; CEF page JS for the first-run screen; no C++ logic changes (comments and one message string only).

**Spec:** `docs/superpowers/specs/2026-11-11-no-sdk-runtime-design.md` (approved 2026-11-11). Read it first; this plan argues from it.

## Global Constraints

- The game never reads the SDK. An SDK path in `settings.json` `[paths].sdk`, `DAUNTLESS_SDK_DIR` or `--sdk-dir` is ignored by the game (spec decision 1).
- The Activision notice splash and its pinned wording are untouched (decision 2).
- Developer SDK chain, in order: `DAUNTLESS_SDK_DIR`, then `settings.json` `[paths].sdk`, then the in-project `sdk/` folder (decision 4). The SDK is a development requirement; no new SDK-specific skip logic (decision 5).
- Only manifest-listed stock modules load from the install; stray `.py` and unlisted `.pyc` there are ignored. An unknown hash loads with ONE warning per file per process (decision 6).
- A missing or unliftable listed file stops boot, naming the file, on the first-run screen; headless raises (decision 7, spec §4.1a).
- The SDK tutorial sample (`Custom/Tutorial`) is a test fixture only (decision 8).
- Never write lifted text, or anything derived from a lifted module, to disk. The manifest holds relative paths and hashes only. The lift-verdict cache holds hashes only.
- Resolve paths at use; never capture one at import. Never spell `game` or `sdk` as a path segment outside `engine/paths.py` except with a `# paths-guard: <reason>` comment (`tests/unit/test_path_indirection.py`).
- Both `_SDKFinder` twins (`tools/mission_harness.py`, `tests/conftest.py`) change in the same commit; `tests/unit/test_sdk_finder_twins_stay_in_sync.py` must stay green.
- Hash: `hashlib.blake2b(data, digest_size=16).hexdigest()` (this plan's choice for the spec's "builder's call").
- ⛔ CLAUDE.md test rules: run only the focused test files named in each task plus the tree guards (`tests/docs`, `tests/unit/test_path_indirection.py`, `tests/unit/test_install_write_guard.py`, `tests/unit/test_gate_tiers.py`). Never a whole suite, never a gate, never `pytest` with an empty file list.
- ⛔ CLAUDE.md git rules: no `git checkout -- / restore / stash / clean / reset --hard / add -A / add .`; stage explicit paths. Work only in `/Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/no-sdk-runtime`. Use plain `uv run`, never `--active`.
- Never launch the game (`./build/dauntless`), headless included, without asking Mark.

## Review Focus

1. **A stale SDK setting or flag.** A machine whose `settings.json` still holds `[paths].sdk` pointing at a deleted folder, or a launch with `--sdk-dir /nonexistent`, must boot normally (the flag logs one line). Test: Task 8 `test_stale_sdk_setting_and_flag_do_not_block_resolution`.
2. **An old-style modded install.** A `scripts/` folder with a stray `QuickBattle/QuickBattle.py` beside the stock `.pyc`, and an extra unlisted `ships/MyShip.pyc`, must load the stock `.pyc` and never see either extra file, including through the bare `import MyShip` fallback. Test: Task 3 `test_unlisted_files_in_the_install_are_invisible`, Task 5 `test_bare_import_never_finds_an_unlisted_install_file`.
3. **Case-sensitive filesystems (Linux).** An install whose folders are spelled `Scripts/` or `Ships/` must still resolve every listed module. Test: Task 3 `test_lookup_is_case_insensitive_on_disk`.
4. **A mod beating a lifted stock module.** A mod `.py` (or `.pyc`) override must win over the stock `.pyc` on every finder branch, the bare-name fallback included. Test: Task 5 `test_mod_py_beats_stock_pyc_on_every_branch`.
5. **Mods under `Custom/` with no SDK.** A mod shipping `Scripts/Custom/Foo.py` (no `Custom/__init__.py`) and the claimed `Custom.NanoFXv2` names must import with no SDK anywhere. Test: Task 5 `test_custom_package_exists_without_the_sdk`.

---

### Task 0: Worktree environment (done by the controller, not a subagent)

- [ ] **Step 1:** In the worktree: `uv sync --extra dev` (plain, never `--active`). Expected: `.venv` with pytest.
- [ ] **Step 2:** Configure a Debug build with the uv 3.11 interpreter, reusing main's fetched deps (memory `feedback_worktrees_runtime_deps`, `feedback_worktree_build_symlink_runs_main_python`):

```bash
U=~/.local/share/uv/python/cpython-3.11.15-macos-aarch64-none
M=/Users/mward/Documents/Projects/bc_dauntless/build/_deps
cmake -B build -S . -DCMAKE_BUILD_TYPE=Debug -DPython3_EXECUTABLE=$PWD/.venv/bin/python3 -DPython3_ROOT_DIR=$U -DPython3_FIND_FRAMEWORK=NEVER -DPython3_FIND_STRATEGY=LOCATION -DFETCHCONTENT_SOURCE_DIR_CEF=$M/cef-src -DFETCHCONTENT_SOURCE_DIR_GOOGLETEST=$M/googletest-src -DFETCHCONTENT_SOURCE_DIR_NLOHMANN_JSON=$M/nlohmann_json-src -DFETCHCONTENT_SOURCE_DIR_OPENAL_SOFT=$M/openal_soft-src -DFETCHCONTENT_SOURCE_DIR_PYBIND11=$M/pybind11-src
cmake --build build -j
```

Expected: `build/dauntless` and `build/python/_dauntless_host.cpython-311-darwin.so`; `grep _Python3_INCLUDE_DIR build/CMakeCache.txt` shows the uv 3.11 path.
- [ ] **Step 3:** Baseline the tree guards: `uv run pytest tests/docs tests/unit/test_path_indirection.py tests/unit/test_install_write_guard.py tests/unit/test_gate_tiers.py -q`. Expected: all pass.

---

### Task 1: Dev SDK accessor and the stock-root path

**Files:**
- Create: `tools/dev_sdk.py`
- Modify: `engine/paths.py` (add `stock_scripts()`; nothing removed yet)
- Test: `tests/unit/test_dev_sdk.py` (new), `tests/unit/test_paths_stock_scripts.py` (new)

**Interfaces:**
- Produces: `tools.dev_sdk.sdk_root(env=None, store=None) -> Path`; `sdk_scripts() -> Path` (`<root>/Build/scripts`); `sdk_data() -> Path` (`<root>/Build/Data`); `class DevSdkMissing(RuntimeError)`; `SDK_MARKERS = ("Build/scripts/App.py", "Build/Data/TGL")` (moved later from `paths`, copied now). `engine.paths.stock_scripts() -> Path`: the game root's `scripts` folder, matched case-insensitively via `case_paths.resolve`, else `game_root() / "scripts"`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_dev_sdk.py`:
- `test_env_wins_over_settings_and_project`: env `DAUNTLESS_SDK_DIR` = a tmp tree with both markers, a fake store whose `has("paths","sdk")` is True pointing elsewhere → `sdk_root(env=..., store=...) == env path`.
- `test_settings_used_when_env_unset`: env `{}`, store set → store path.
- `test_project_folder_is_last` (monkeypatch `dev_sdk.PROJECT_ROOT` to a tmp dir containing `sdk/` with markers; env `{}`, empty store) → `tmp/sdk`.
- `test_missing_sdk_raises_with_the_chain_named`: nothing set → `pytest.raises(DevSdkMissing)`, and the message contains `DAUNTLESS_SDK_DIR`, `settings.json [paths].sdk` and `required for development`.
- `test_set_but_invalid_raises_not_falls_through`: env points at an empty dir while the store holds a valid tree → raises `DevSdkMissing` naming the env path and the missing marker.
- `test_empty_env_value_counts_as_unset` (same asymmetry as `paths._candidate`).

`tests/unit/test_paths_stock_scripts.py`:
- `test_stock_scripts_is_the_game_roots_scripts_folder`: configure a Resolution whose game root is a tmp tree with `scripts/` → `paths.stock_scripts() == root / "scripts"`.
- `test_stock_scripts_matches_case_insensitively`: tree spelled `Scripts/` → returns that spelling.
- `test_stock_scripts_resolves_at_use`: reconfigure to a second root → the new value (no capture).

- [ ] **Step 2: Run them to make sure they fail**

Run: `uv run pytest tests/unit/test_dev_sdk.py tests/unit/test_paths_stock_scripts.py -q`
Expected: FAIL (`ModuleNotFoundError: tools.dev_sdk`, `AttributeError: stock_scripts`).

- [ ] **Step 3: Implement `tools/dev_sdk.py` and `paths.stock_scripts()`**

`dev_sdk` reuses `paths.normalise` and `case_paths`; the store is `engine.settings_store.SettingsStore` loaded lazily when `store is None`. Set-but-invalid raises (never falls through), mirroring `paths._candidate`'s rule. The project folder is `PROJECT_ROOT / "sdk"  # paths-guard: dev SDK chain, decision 4`. Module docstring: dev-only, never imported by the game, spec decisions 4-5, the guard test in Task 8.

- [ ] **Step 4: Run them to make sure they pass**

Run: `uv run pytest tests/unit/test_dev_sdk.py tests/unit/test_paths_stock_scripts.py tests/unit/test_path_indirection.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/dev_sdk.py engine/paths.py tests/unit/test_dev_sdk.py tests/unit/test_paths_stock_scripts.py
git commit -m "feat(paths): dev SDK accessor and the install's stock scripts root"
```

---

### Task 2: The stock manifest, its generator and drift test

**Files:**
- Create: `tools/gen_stock_manifest.py`, `engine/stock_manifest.json` (GENERATED)
- Test: `tests/tools/test_stock_manifest_drift.py` (new), `tests/tools/test_gen_stock_manifest.py` (new)

**Interfaces:**
- Consumes: `paths.stock_scripts()` (Task 1).
- Produces: the manifest file, format:

```json
{
 "format": 1,
 "hash": "blake2b-128",
 "generator": "tools/gen_stock_manifest.py",
 "modules": {
  "AI/Preprocessors.pyc": ["<32 hex chars>"],
  "Bridge/__init__.pyc": ["..."]
 }
}
```

Keys are the install's own spelling, relative, forward slashes; values are sorted lists of known hashes. Serialised with `json.dumps(obj, indent=1, sort_keys=True) + "\n"`.
- `tools.gen_stock_manifest.build(scripts_root: Path, project_root: Path) -> dict` (the `modules` mapping for ONE install); `merge(committed: dict, built: dict) -> dict` (union of hashes per path, union of paths); `serialise(modules: dict) -> str`; CLI: no flag = dry run printing a summary, `--write` replaces the manifest from the configured install, `--add` merges the configured install's hashes into it (spec §4.1: a second verified retail build appends).
- Exclusion rule: skip `<rel>.pyc` when `project_root / (<rel> + ".py")` exists (the project-root shims). Today that excludes only `App`: the root holds `App.py`, `Foundation.py`, `LoadDamageHitSounds.py` and `strop.py`, and retail ships only `App.pyc` of those. (CLAUDE.md's "`LoadBridge.py` shim" is stale: there is no root `LoadBridge.py`, so stock `LoadBridge` loads lifted like any other module.)

- [ ] **Step 1: Write the failing tests**

`tests/tools/test_gen_stock_manifest.py` (fake trees in `tmp_path`, no BC content):
- `test_build_lists_every_pyc_with_its_hash` — two `.pyc` files (any bytes) → keys are their relative paths, values one-element lists equal to `blake2b(data, digest_size=16).hexdigest()`.
- `test_build_ignores_py_and_other_files` — a `.py` and a `.txt` beside them are absent.
- `test_project_root_shims_are_excluded` — `project_root/App.py` exists → `App.pyc` absent.
- `test_merge_appends_hashes_never_replaces` — committed `{"A.pyc": ["h1"]}` + built `{"A.pyc": ["h2"], "B.pyc": ["h3"]}` → `{"A.pyc": ["h1","h2"], "B.pyc": ["h3"]}`.
- `test_serialise_is_deterministic` — the same dict in two insertion orders → identical text ending in `"\n"`.

`tests/tools/test_stock_manifest_drift.py` (real install via `tests/helpers/bc_assets.require_game_dir("scripts")`):
- `test_committed_manifest_matches_the_configured_install` — build from the install; if any built hash is not in the committed set for its path, `pytest.skip` naming those files ("a retail build this manifest does not know"); otherwise assert the built path set equals the committed path set and the committed text equals `serialise(committed modules)`.
- `test_manifest_lists_1201_minus_the_root_shims` — on a known install, `len(modules) == 1201 - <number of excluded shims>` (compute the excluded count from `build`'s rule, not a literal).

- [ ] **Step 2: Run them to make sure they fail**

Run: `uv run pytest tests/tools/test_gen_stock_manifest.py tests/tools/test_stock_manifest_drift.py -q`
Expected: FAIL (module/file missing).

- [ ] **Step 3: Implement the generator, then generate**

Run: `uv run python tools/gen_stock_manifest.py` (dry run: prints counts), then `uv run python tools/gen_stock_manifest.py --write`.
Expected: `engine/stock_manifest.json` with 1,200 entries on Mark's GOG install (1,201 minus `App`). Check that no entry starts with `Custom/`.

- [ ] **Step 4: Run them to make sure they pass**

Run: `uv run pytest tests/tools/test_gen_stock_manifest.py tests/tools/test_stock_manifest_drift.py tests/unit/test_path_indirection.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/gen_stock_manifest.py engine/stock_manifest.json tests/tools/test_gen_stock_manifest.py tests/tools/test_stock_manifest_drift.py
git commit -m "feat(stock): generated manifest of retail script paths and hashes"
```

---

### Task 3: `engine/stock_scripts.py`: lookup, lift, warning, Custom, fixtures

**Files:**
- Create: `engine/stock_scripts.py`
- Test: `tests/unit/test_stock_scripts.py` (new)

**Interfaces:**
- Consumes: the manifest (Task 2), `paths.stock_scripts()` (Task 1), `engine.py15` (`lift_file`, `Py15Unsupported`, `marshal15.load_pyc`).
- Produces:
  - `@dataclass(frozen=True) class StockFile: rel: str` (logical, no extension, the manifest's spelling, e.g. `"AI/Preprocessors"`, `"Bridge"` for a package) `; path: Path` (on disk) `; is_package: bool ; is_fixture: bool` (True for a test-fixture `.py`).
  - `SYNTHETIC_PACKAGES: tuple[str, ...] = ("Custom",)`: the SDK's empty `Custom/__init__.py`, which retail lacks; mods and the claimed `Custom.*` names rely on it.
  - `find(logical: str) -> Optional[StockFile]` — `logical` like `"ai/preprocessors"` or `"Bridge"`, any case, no extension; a package resolves to its `__init__.pyc`. Listed modules only; fixtures after the manifest.
  - `find_by_leaf(name: str) -> list[StockFile]` — every listed (and fixture) module whose last segment folds equal to `name`, packages' `__init__` excluded, sorted by `rel`.
  - `children(rel_dir: str) -> list[StockFile]` — direct module children of a folder (no recursion).
  - `is_stock(rel: str) -> bool` — accepts `"ships/galaxy"`, `"ships/galaxy.py"` or `".pyc"`, any case.
  - `top_level_functions(sf: StockFile) -> dict[str, tuple[str, ...]]` — module-level function name → argument names; from the `.pyc` code object via `marshal15.load_pyc` (consts of type `Code15`, `varnames[:argcount]`), or from `ast` for a fixture `.py`. No lift.
  - `load_tree(path: str, fullname: str) -> ast.Module` — for a listed `.pyc`: read bytes, hash; an unknown hash prints once per path per process `[stock-scripts] scripts/<rel>.pyc differs from every known retail copy (the install may be modded); loading it anyway`; then `py15.lift_file`; a `Py15Unsupported` becomes `StockScriptError`. For a fixture `.py`: `fix_source(read_source(path))` + `ast.parse`.
  - `class StockScriptError(ImportError)` with `.path`.
  - `add_fixture_tree(root: Path, prefix: str, tgl_root: Optional[Path] = None) -> None`, `clear_fixture_trees() -> None`, `fixture_tgl_roots() -> tuple[Path, ...]`. Test-only (decision 8); the game never calls them (guard in Task 8).
  - `configure(manifest_modules: Optional[dict] = None, scripts_root: Optional[Path] = None) -> None` — tests inject a manifest and root; `None` = the committed manifest and `paths.stock_scripts()` at use.
- Lookups are indexed once per (root, manifest) by folded key; the on-disk path is resolved with `case_paths.resolve(root, key)` and memoised.

- [ ] **Step 1: Write the failing tests** (`tests/unit/test_stock_scripts.py`, fake trees + injected manifest; real retail bytes not needed except where noted)

- `test_find_returns_listed_modules_and_packages` — manifest `{"AI/Preprocessors.pyc": [h], "Bridge/__init__.pyc": [h]}` → `find("ai/preprocessors").path` ends `AI/Preprocessors.pyc`, `find("Bridge").is_package`.
- `test_unlisted_files_in_the_install_are_invisible` (Review Focus 2) — tree also holds `QuickBattle/QuickBattle.py` and `ships/MyShip.pyc`, neither listed → `find("QuickBattle/QuickBattle") is None`, `find("ships/MyShip") is None`, `find_by_leaf("MyShip") == []`.
- `test_lookup_is_case_insensitive_on_disk` (Review Focus 3) — on-disk `Scripts/Ships/Galaxy.pyc`, manifest key `ships/Galaxy.pyc` → found; `find("SHIPS/galaxy")` finds it too.
- `test_find_by_leaf_sorted_and_excludes_init`.
- `test_is_stock_accepts_any_extension_and_case`.
- `test_top_level_functions_reads_bytecode_without_lifting` — uses a real retail mission `.pyc` via `require_game_dir("scripts")` (e.g. `Maelstrom/Episode1/E1M1/E1M1.pyc`): `"Initialize" in fns and fns["Initialize"][0] == "pMission"`; monkeypatch `py15.lift_file` to raise to prove no lift.
- `test_unknown_hash_warns_once_and_loads` — real retail `.pyc` bytes copied into a fake tree, manifest lists a different hash → `load_tree` returns a Module; capsys shows the warning exactly once over two calls.
- `test_known_hash_is_silent`.
- `test_unliftable_stock_raises_stock_script_error_naming_the_file` — garbage bytes → `StockScriptError` whose `.path` is the file.
- `test_fixture_tree_modules_resolve_after_the_manifest` — `add_fixture_tree(tmp_sdk, "Custom/Tutorial")` with `Custom/Tutorial/Tutorial.py` → `find("Custom/Tutorial/Tutorial").is_fixture`; `clear_fixture_trees()` → `None`; a fixture never shadows a listed module.
- `test_fixture_tgl_roots_round_trip`.
- `test_no_lifted_text_written` — run `load_tree` with `tests/helpers/write_audit.py`'s audit active; assert no writes.

- [ ] **Step 2: Run to make sure they fail**

Run: `uv run pytest tests/unit/test_stock_scripts.py -q` → FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement `engine/stock_scripts.py`** per the Interfaces block. The module docstring states the spec, the never-write rule, and that the fixture API is test-only.

- [ ] **Step 4: Run to make sure they pass**

Run: `uv run pytest tests/unit/test_stock_scripts.py tests/unit/test_path_indirection.py tests/unit/test_install_write_guard.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/stock_scripts.py tests/unit/test_stock_scripts.py
git commit -m "feat(stock): stock script lookup and lift from the retail install"
```

---

### Task 4: Install check, lift-verdict cache, validation and the headless guard

**Files:**
- Modify: `engine/stock_scripts.py`
- Test: `tests/unit/test_stock_install_check.py` (new)

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class InstallCheck: ok: bool ; missing: tuple[str, ...] ; unliftable: tuple[str, ...] ; changed: tuple[str, ...]` (all `scripts/<rel>.pyc` display strings) and `message: str` (empty when ok).
  - `check_install(game_root: Path) -> InstallCheck` — hashes every manifest file under that root's scripts folder; missing → `missing`; unknown hash → `changed` (+ the Task 3 one-time warning) and lifted once unless the verdict cache says that hash lifts; a failed lift → `unliftable`. `ok = not missing and not unliftable`.
  - Verdict cache: `paths.cache_dir() / "stock_lift_verdicts.json"`, `{"format": 1, "lifts": [<hash>, ...]}`, positive verdicts only, atomic write (temp + `os.replace`), failures through `paths.report_write_failure`.
  - `validate_install(path) -> paths.Validation` — `paths.validate_game_root(path)`; if ok, `check_install`; a failed check returns `Validation(ok=False, root=..., missing=check.missing + check.unliftable, hint=check.message)`.
  - `checked(resolution: paths.Resolution) -> paths.Resolution` — revalidates a valid game root with `validate_install`; a failure returns `dataclasses.replace(resolution, game=None, game_validation=<that Validation>)`.
  - `require_install(game_root: Path) -> InstallCheck` — memoised per root per process; raises `StockInstallError(RuntimeError)` carrying `message` when not ok. For headless and `setup_sdk()` (Task 5).
- Message copy (decision 7; first-run screen and log). Name at most three files, then "and N more":
  - missing: `Your Bridge Commander scripts folder is incomplete: scripts/AI/Preprocessors.pyc is missing. Reinstall Bridge Commander or pick another install.`
  - unliftable: `BC Dauntless can't read scripts/X.pyc in this Bridge Commander install (<reason>). It may be modded: please use a clean install.`

- [ ] **Step 1: Write the failing tests** (fake trees with copied real retail bytes where a lift is needed)

- `test_clean_install_is_ok_and_lifts_nothing` — monkeypatch `py15.lift_file` to raise; all hashes known → `ok`, no lift.
- `test_missing_listed_file_fails_naming_it`.
- `test_unliftable_unknown_file_fails_naming_it`.
- `test_unknown_but_liftable_file_is_ok_and_recorded_as_changed`.
- `test_verdict_cache_skips_the_second_lift` — second `check_install` with a counting `lift_file` → 0 lifts; the cache file holds only hex strings (assert every value matches `^[0-9a-f]{32}$`).
- `test_validate_install_reports_markers_before_scripts` — a tree missing `data/` gets the marker verdict, not the scripts one.
- `test_checked_turns_a_bad_install_into_an_unresolved_game` — `checked(res).game is None` and `game_validation.hint` names the file.
- `test_require_install_raises_with_the_message` and is memoised (second call does not re-hash: count `open` via a hash spy).
- `test_message_names_at_most_three_files`.

- [ ] **Step 2: Run to make sure they fail** — `uv run pytest tests/unit/test_stock_install_check.py -q` → FAIL.
- [ ] **Step 3: Implement** per Interfaces.
- [ ] **Step 4: Run to make sure they pass** — `uv run pytest tests/unit/test_stock_install_check.py tests/unit/test_stock_scripts.py tests/unit/test_install_write_guard.py -q` → PASS.
- [ ] **Step 5: Commit**

```bash
git add engine/stock_scripts.py tests/unit/test_stock_install_check.py
git commit -m "feat(stock): boot install check with named failures and a lift-verdict cache"
```

---

### Task 5: Both loader twins load stock from the install

**Files:**
- Modify: `tools/mission_harness.py` (`_sdk_scripts` → stock root, `_module_tree`, `_FixImplicitRelativeImport`, `_implicit_relative_fixer`, `_stock_dotted_name`, `_SDKFinder.find_spec`, `setup_sdk`, `discover_missions`); `tests/conftest.py` (the twin: same functions, `SDK_SCRIPTS` → `STOCK_SCRIPTS`; content-root pinning; fixture registration); `engine/py15/__init__.py` docstring ("mod files only" → stock and mod)
- Modify: `tests/unit/test_sdk_finder_twins_stay_in_sync.py` (`_NAME_ALIASES`: `"STOCK_SCRIPTS": "stock_scripts"`; the harness local becomes `stock_scripts = _stock_scripts()`)
- Test: `tests/unit/test_stock_loader.py` (new); update `tests/unit/test_mods_sdk_finder.py`, `tests/unit/test_sdk_finder_claimed_reentry.py`, `tests/unit/test_mission_harness.py`

**Interfaces:**
- Consumes: Task 3 (`find`, `find_by_leaf`, `load_tree`, `SYNTHETIC_PACKAGES`, fixtures), Task 4 (`require_install`), `tools.dev_sdk` (conftest only).
- Rules, identical in both twins:
  1. Order unchanged: project-root shims → claimed names → mod override → stock → package `__path__` search → bare-name fallback → mod-only bare names.
  2. Stock = `stock_scripts.find(rel)`; `_SDKLoader(str(sf.path))`; packages get `submodule_search_locations = [str(sf.path.parent)]`.
  3. `_module_tree(path, fullname)`: a stock file (under the stock root, or `is_fixture`) → `stock_scripts.load_tree`; a mod `.pyc` → `py15.load_tree` as today; a mod `.py` → parse as today.
  4. Package `__path__` search: a search dir under the stock root maps to `rel_dir`; lookup is `stock_scripts.find(f"{rel_dir}/{child}")`, never a disk probe for `.py`.
  5. Bare-name fallback: `stock_scripts.find_by_leaf(fullname)` replaces `_case_paths.rglob_py`; the caller-dir preference compares the `co_filename` (a `.pyc` path under the stock root) as today.
  6. `SYNTHETIC_PACKAGES`: after the mod-override check and before stock, a fullname folding to `custom` with no mod `Custom/__init__` gets an empty package spec (`submodule_search_locations=[]`, a loader whose `exec_module` sets nothing).
  7. Implicit-relative siblings: a name is a sibling when a mod sibling dir holds `<name>.py` or `<name>.pyc`, OR `stock_scripts.find(f"{pkg_rel}/{name}")` is listed. `sibling_dirs` stays for `sdk_code_cache` stamps.
  8. `setup_sdk()` calls `stock_scripts.require_install(paths.game_root())` first; `Bridge`, `Actions`, `Multiplayer`, `Bridge/Characters` `__path__`s point at stock-root folders (`case_paths.resolve`).
  9. `_stock_dotted_name` takes parent spelling from the manifest's `rel`s, not an SDK directory walk.
- conftest only: resolve the dev SDK (`dev_sdk.sdk_root()`) BEFORE `DAUNTLESS_DATA_DIR` is redirected (the temp data dir hides `settings.json`) and pin `DAUNTLESS_SDK_DIR` with `setdefault`; call `stock_scripts.add_fixture_tree(dev_sdk.sdk_scripts(), "Custom/Tutorial", tgl_root=dev_sdk.sdk_data() / "TGL")` at import.
- `discover_missions() -> list[str]`: listed (and fixture) modules whose `top_level_functions` has `Initialize` with first argument `pMission`; dotted names from `rel`.

- [ ] **Step 1: Write the failing tests** (`tests/unit/test_stock_loader.py`, run through the harness's `setup_sdk()` with an injected fake manifest/root where needed; real install for the import smoke tests)

- `test_stock_module_imports_from_the_lifted_pyc` — `import MissionLib` → `MissionLib.__file__` ends `MissionLib.pyc` and is under `paths.stock_scripts()`.
- `test_no_module_comes_from_the_sdk` — after importing `MissionLib`, `loadspacehelper`, `QuickBattle.QuickBattle`, `AI.Preprocessors`, no `sys.modules` entry's `__file__` is under `dev_sdk.sdk_root()` except `Custom.Tutorial.*`.
- `test_bare_import_never_finds_an_unlisted_install_file` (Review Focus 2) — fake root with an unlisted `ships/MyShip.pyc` → `import MyShip` raises `ModuleNotFoundError`.
- `test_mod_py_beats_stock_pyc_on_every_branch` (Review Focus 4) — a mod `ships/Galaxy.py` wins for `import ships.Galaxy`, the `Characters`-style `__path__` branch (use a mod `Bridge/Characters/<stock name>.py`), and bare `import Galaxy`.
- `test_custom_package_exists_without_the_sdk` (Review Focus 5) — with fixtures cleared: `import Custom` succeeds and is empty; a mod `Custom/Foo.py` (no `__init__`) imports as `Custom.Foo`; `import Custom.NanoFXv2` returns the claimed package.
- `test_tutorial_fixture_loads_from_the_sdk_in_tests` — `import Custom.Tutorial.Episode.M1Basic.M1Basic` → its `__file__` is under the dev SDK.
- `test_implicit_relative_import_finds_a_pyc_sibling` — `QuickBattle.QuickBattleAI` (or another stock module that does a bare sibling import) imports and binds the sibling module.
- `test_setup_sdk_refuses_a_broken_install` — a fake root missing a listed file → `setup_sdk()` raises `StockInstallError`.
- `test_discover_missions_reads_bytecode` — includes `Maelstrom.Episode1.E1M1.E1M1`, excludes episode scripts (`Initialize(pEpisode)`).

- [ ] **Step 2: Run to make sure they fail** — `uv run pytest tests/unit/test_stock_loader.py -q` → FAIL.
- [ ] **Step 3: Implement** the rules in both twins, the conftest pinning and fixture registration, and the twin-sync alias update.
- [ ] **Step 4: Run the focused set**

Run: `uv run pytest tests/unit/test_stock_loader.py tests/unit/test_sdk_finder_twins_stay_in_sync.py tests/unit/test_mods_sdk_finder.py tests/unit/test_sdk_finder_claimed_reentry.py tests/unit/test_mission_harness.py tests/unit/test_py15_stock_oracle.py tests/integration/test_native_ai_ab.py tests/unit/test_path_indirection.py -q`
Expected: PASS. (`test_native_ai_ab.py` proves the lifted stock code still runs the native AI path; it may first need Task 6's `ai_native` change. If it fails ONLY on the stock-identity check, pull Task 6's `ai_native` step forward into this commit.)
- [ ] **Step 5: Commit** (explicit paths: both twins, the sync test, `engine/py15/__init__.py`, the new and updated tests)

```bash
git commit -m "feat(loader): stock scripts load lifted from the retail install in both SDK loaders"
```

---

### Task 6: Runtime callers move off the SDK

**Files / changes:**
- `engine/appc/ai_native.py` `_stock_file()` → `str(stock_scripts.find("AI/Preprocessors").path)` resolved at use (keep the root-change cache).
- `engine/missions/discovery.py` `discover()` → no arguments; iterates `stock_scripts` listings (families from `_FAMILY_ROOTS`; a family root with no listed or fixture modules is skipped); mission test = `top_level_functions(sf)["Initialize"][0] == "pMission"`; ancestor-pruning by `rel` prefixes. `engine/host_loop.py` `_get_mission_registry` → `discover()`.
- `engine/missions/name_resolver.py` `_tgl_roots()` → `(*stock_scripts.fixture_tgl_roots(), *paths.game_asset_dirs("data/TGL"))`.
- `engine/appc/localization.py` → the SDK candidate becomes one candidate per `stock_scripts.fixture_tgl_roots()` (`root / <path after "data/TGL/">`).
- `engine/bridge_selection._stock_ship_stems()` → `{sf.rel.split("/")[-1].lower(): sf.rel.split("/")[-1] for sf in stock_scripts.children("ships") if not sf.is_package}`.
- `engine/mods.py`: `classify(index, game_root)` and `install(argv, env, game_root)` lose the SDK argument; `_shadows_stock` for kind `"sdk"` → `stock_scripts.is_stock(mf.rel)`; `_classify_ship_scripts` → `stock_scripts.is_stock(f"ships/{name}")`. Keep the kind label `"sdk"` (it is a label; renaming churns the mod index for nothing).
- `engine/dev_character_viewscreen.py` → scan `ast.unparse(stock_scripts.load_tree(...))` text of listed modules (skipping `Bridge/Characters` for the set scan); relax the regexes to accept either quote style; cache keyed by the stock root.
- `engine/dev_missions/ship_preview.py` → print `paths.stock_scripts() / rel` with the `.pyc` suffix.

**Interfaces:** Consumes Tasks 3-4. Produces `discover() -> MissionRegistry` (no args) and the new `mods.classify`/`install` signatures; Task 8 updates their remaining callers.

- [ ] **Step 1: Update/write the failing tests**
  - `tests/missions/test_discovery.py`, `tests/missions/test_registry.py`: call `discover()`; keep their existing assertions (Maelstrom order, Tutorial family present through the fixture, Multiplayer); add `test_discovery_needs_no_sdk_for_maelstrom` (fixtures cleared → Maelstrom and Multiplayer still found, Tutorial absent).
  - `tests/missions/test_name_resolver.py`: tutorial names still resolve (fixture TGL root); add `test_game_tgl_roots_exclude_the_sdk` (fixtures cleared → no root under the dev SDK).
  - `tests/unit/test_mods_boot.py`, `tests/unit/test_mods_sdk_finder.py`: new `classify`/`install` signatures; a mod `ships/Galaxy.py` is still reported in `replaces_ships`.
  - `tests/unit/test_dev_character_viewscreen*.py` (find with `ls tests | grep -ri character_viewscreen`): the catalogue still lists the same character names as before the change (record the old list from the SDK-based build in the test as the expectation, names only).
  - `tests/unit/test_bridge_selection*.py`: stock stems unchanged.
  - Any `ai_native` test (`grep -rl ai_native tests/unit`): stock preprocessors still detected as stock.
- [ ] **Step 2: Run to make sure the new ones fail** (the listed files) → FAIL on the new signatures/assertions.
- [ ] **Step 3: Implement** the changes above.
- [ ] **Step 4: Run** the files listed in Step 1 plus `tests/integration/test_native_ai_ab.py tests/unit/test_dev_mission_picker.py tests/unit/test_path_indirection.py` → PASS.
- [ ] **Step 5: Commit** (explicit paths)

```bash
git commit -m "feat(stock): runtime callers read stock scripts from the install, not the SDK"
```

---

### Task 7: Tests and tools that read the SDK as reference use the dev accessor

Rule (spec §4.7 with decision 5): code that reads SDK **source text or files as data** (parsers, bakes, the oracle, instrumentation) uses `tools.dev_sdk`. Code that exercises **how the game loads scripts** uses `stock_scripts` (done in Tasks 5-6).

**Files → change:**
- `tools/bake_impulse_glow.py`, `tools/bake_warp_glow.py`, `tools/bake_set_course_catalog.py`, `tools/bake_star_colors.py`, `tools/systems/survey.py`, `tools/tgl_harness.py`, `tools/pick_simplest_mission.py`, `tools/setup.py`, `tools/gen_app_constants.py` (if it reads `paths.sdk_*`): `paths.sdk_scripts()/sdk_data()/sdk_root()` → `dev_sdk.sdk_scripts()/sdk_data()/sdk_root()`; module-level constants become functions or in-`main` locals (resolve at use).
- `tools/golden_ab_side.py`: the base side may predate this branch and still need `DAUNTLESS_SDK_DIR`: set it from `dev_sdk.sdk_root()` (and keep `DAUNTLESS_GAME_DIR`).
- Tests: `tests/unit/test_py15_stock_oracle.py`, `tests/integration/test_hardpoint_parser.py`, `test_e1m1_ship_identity.py`, `test_officer_placement_sdk.py`, `test_sdk_bridge_load.py`, `test_ship_catalog_stock_content.py`, `test_bake_set_course_catalog.py`, `tests/missions/conftest.py`, `tests/missions/test_tgl_harness.py`, `tests/tools/test_golden_ab_side.py`, `tests/tools/test_pick_simplest_mission.py`, `tests/unit/test_combat_stress_avoidance_default.py`, `test_dev_key_collisions.py`, `test_preprocess_done_is_lethal.py`, `test_wc_modifier_constants.py`, `tests/helpers/write_audit.py` (frame roots: the stock root AND the dev SDK root), `tests/unit/test_structure_parts_cache_root.py` (docstring only): → `dev_sdk`.

- [ ] **Step 1:** Make the edits (mechanical). For each file, if it reads a module the game now loads lifted, leave a one-line comment `# reads SDK source as reference data (spec 2026-11-11 decision 5)`.
- [ ] **Step 2: Run each changed test file**

Run: `uv run pytest tests/unit/test_py15_stock_oracle.py tests/integration/test_hardpoint_parser.py tests/integration/test_e1m1_ship_identity.py tests/integration/test_officer_placement_sdk.py tests/integration/test_sdk_bridge_load.py tests/integration/test_ship_catalog_stock_content.py tests/integration/test_bake_set_course_catalog.py tests/missions/test_tgl_harness.py tests/tools/test_golden_ab_side.py tests/tools/test_pick_simplest_mission.py tests/unit/test_combat_stress_avoidance_default.py tests/unit/test_dev_key_collisions.py tests/unit/test_preprocess_done_is_lethal.py tests/unit/test_wc_modifier_constants.py tests/unit/test_structure_parts_cache_root.py tests/unit/test_path_indirection.py -q`
Expected: PASS.
- [ ] **Step 3:** `grep -rnE "paths\.(sdk_scripts|sdk_root|sdk_data|sdk_scripts_in)\(" engine tools tests scripts` → only `engine/paths.py` definitions remain.
- [ ] **Step 4: Commit** (explicit paths)

```bash
git commit -m "refactor(dev): SDK reference readers use the dev SDK accessor"
```

---

### Task 8: Paths and the first-run screen are game-only; the guard

**Files:**
- Modify: `engine/paths.py` — remove `sdk_root`, `sdk_scripts`, `sdk_scripts_in`, `sdk_data`, `validate_sdk_root`, `SDK_MARKERS`; `Resolution` drops `sdk`, `sdk_source`, `sdk_validation` (`ok` = game valid; `source`/`validation` keep the `kind` parameter, game only); `CLI_FLAGS`, `ENV_VARS`, `_PROJECT_DIR`, `_VALIDATORS`, `_MARKERS`, `_LABEL`, `resolve`, `persist`, `describe_failure` game only (the failure text's example command drops `--sdk-dir`); `GAME_MARKERS` adds `"scripts/MissionLib.pyc"` (update the comment above it: scripts are now read); the "swapped root" hint goes. New `warn_ignored_sdk_sources(argv) -> None`: one stderr line `[paths] --sdk-dir is no longer used: BC Dauntless reads Bridge Commander's scripts from your game folder` when the flag is present; called from `resolve()` when `argv` is the ambient `sys.argv`. Module docstring: one content root.
- Modify: `engine/host_loop.py` `_resolve_paths_or_report` — `resolution = stock_scripts.checked(_paths.resolve(...))` and the same wrap inside the first-run `resolver` lambda; `mods.install(argv=..., env=..., game_root=resolution.game)`; comments about the SDK finder updated.
- Modify: `engine/ui/first_run_panel.py` — `_ROWS` game only; `_VALIDATORS = {"game": stock_scripts.validate_install}`; `native/assets/ui-cef/js/first_run.js` + `native/assets/ui-cef/index.html` comment (line ~76) for one row; `native/src/platform/folder_picker.cc` message → `pass --game-dir instead`; `native/src/host/host_main.cc` comments (`--sdk-dir` mentions removed; no logic change).
- Modify: `tests/conftest.py` content-root pinning loop → game only (the dev SDK pin is Task 5's).
- Modify: `scripts/package.py` comments that describe the SDK finder (the env-scrub list may keep `DAUNTLESS_SDK_DIR`).
- Tests: rewrite `tests/unit/test_paths_resolve.py`, `test_paths_validate.py`, `test_paths_picked_source.py`, `test_paths_late_reconfigure.py`, `tests/unit/test_first_run_panel.py`, `tests/host/test_host_loop_first_run.py`, `tests/integration/test_packaged_readonly_e2e.py` for game-only resolution. New: `tests/unit/test_game_never_reads_sdk.py`.

**Interfaces:** Consumes Tasks 1-7. Produces the game-only `Resolution(game, game_source, game_validation)`.

- [ ] **Step 1: Write the failing tests**
  - `tests/unit/test_paths_resolve.py::test_stale_sdk_setting_and_flag_do_not_block_resolution` (Review Focus 1) — store with `[paths].sdk = "/nonexistent"`, argv `["--sdk-dir", "/nonexistent"]`, env `DAUNTLESS_SDK_DIR=/nonexistent`, valid game root → `res.ok`; capsys shows the `--sdk-dir is no longer used` line once; `persist` never writes `[paths].sdk`.
  - `test_paths_validate.py::test_game_root_requires_scripts` — a tree with `data/...` markers but no `scripts/MissionLib.pyc` is invalid, `missing == ("scripts/MissionLib.pyc",)`.
  - `test_first_run_panel.py::test_one_row_only` (payload has only the game row) and `test_a_broken_install_is_rejected_naming_the_file` (picker returns a tree missing a listed `.pyc`; the row shows the check's hint; Continue stays disabled).
  - `tests/host/test_host_loop_first_run.py::test_broken_install_reopens_the_first_run_screen` — `_resolve_paths_or_report` with a resolved-but-broken root and `cef_ready=True` runs the first-run screen (stubbed) with the game row's hint naming the file; with `cef_ready=False` prints `describe_failure` naming it and returns `None`.
  - `tests/unit/test_game_never_reads_sdk.py` (parse, don't grep):
    - `test_engine_never_imports_dev_sdk` — no `import tools.dev_sdk` / `from tools import dev_sdk` / `from tools.dev_sdk import` in any `engine/**/*.py`, project-root `*.py`, or `scripts/package.py`'s `_RUNTIME_TOOLS` files.
    - `test_engine_never_registers_fixture_trees` — no call to `add_fixture_tree` outside `tests/`.
    - `test_paths_has_no_sdk_surface` — `engine.paths` has none of `sdk_root`, `sdk_scripts`, `sdk_scripts_in`, `sdk_data`, `validate_sdk_root`, `SDK_MARKERS`; `"sdk" not in paths.ENV_VARS`.
    - `test_package_does_not_ship_dev_sdk` — `"dev_sdk.py" not in package._RUNTIME_TOOLS`.
- [ ] **Step 2: Run to make sure they fail** (the files above) → FAIL.
- [ ] **Step 3: Implement** the Files list.
- [ ] **Step 4: Run**

Run: `uv run pytest tests/unit/test_paths_resolve.py tests/unit/test_paths_validate.py tests/unit/test_paths_picked_source.py tests/unit/test_paths_late_reconfigure.py tests/unit/test_paths_stock_scripts.py tests/unit/test_first_run_panel.py tests/host/test_host_loop_first_run.py tests/integration/test_packaged_readonly_e2e.py tests/unit/test_game_never_reads_sdk.py tests/unit/test_mods_boot.py tests/unit/test_path_indirection.py tests/unit/test_install_write_guard.py -q`
Expected: PASS. Rebuild first if `folder_picker.cc`/`host_main.cc` changed: `cmake --build build -j`.
- [ ] **Step 5: Commit** (explicit paths)

```bash
git commit -m "feat(paths): one content root; the first-run screen asks for the game folder only"
```

---

### Task 9: No-SDK boot test

**Files:**
- Create: `tests/integration/test_no_sdk_boot.py`

**Interfaces:** Consumes everything above. Runs in a subprocess so the in-process SDK fixture and the conftest pins cannot leak in: `subprocess.run([sys.executable, "-c", <script>], env=<copy of os.environ minus DAUNTLESS_SDK_DIR, with DAUNTLESS_GAME_DIR set and DAUNTLESS_DATA_DIR = tmp_path>)`, cwd = a tmp dir (so no in-project `sdk/` is found either).

- [ ] **Step 1: Write the test**
  - `test_missions_load_and_tick_with_no_sdk_anywhere` — the child script: `paths.configure(stock_scripts.checked(paths.resolve(argv=[], store=<empty>)))`, `mission_harness.setup_sdk()`, then for each of `Maelstrom.Episode1.E1M1.E1M1`, `QuickBattle.QuickBattle`: run it headless for 120 ticks using the same entry the existing harness tests use (`tools/mission_harness.run_mission` or `engine.headless_mission`; pick the one `tests/integration/test_gameloop_harness.py` uses), and assert no module in `sys.modules` has a `__file__` containing `"Build" + os.sep + "scripts"` (an SDK layout) — print `OK` on success. Parent asserts return code 0 and `OK` in stdout.
  - `test_a_mod_pyc_override_loads_with_no_sdk` — same child setup with `DAUNTLESS_MODS_DIR` (the `mods.ENV_VAR`) pointing at the worktree's `mods/`; import the LC Intrepid projectile module the existing `.pyc`-mod tests use (`grep -rl "LCIntrepid\|Intrepid" tests/unit/test_py15*`) and assert it is not the photon fallback.
- [ ] **Step 2: Run it** — `uv run pytest tests/integration/test_no_sdk_boot.py -q` → PASS (it is written against finished behaviour; if it fails, fix the code, not the test).
- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_no_sdk_boot.py
git commit -m "test: missions and mod bytecode load headless with no SDK anywhere"
```

---

### Task 10: Docs

**Files:**
- `docs/packaging/README.txt`: requirements list loses the SDK bullet; GETTING STARTED drops step 2 and renumbers; the first-run step describes one folder; "Use a clean copy" adds: Dauntless reads Bridge Commander's scripts from the install too, and a changed stock script logs a warning naming it. The licence paragraph naming the SDK stays.
- `CLAUDE.md`: the "BC content paths" row and section (one runtime root; the dev SDK chain in `tools/dev_sdk.py`; the guard test), the Python 1.5 row ("Mod files only" → stock lifted from the install too; the manifest and its drift test), Setup (the SDK is required for development; `settings.json [paths].sdk` or `DAUNTLESS_SDK_DIR`), the "Project-root SDK shims" list (drop the stale `LoadBridge.py` entry: no such root file exists), and a new row for `engine/stock_scripts.py` + `engine/stock_manifest.json` (GENERATED: `tools/gen_stock_manifest.py --write`, `--add` for a second retail build; never hand-edit).
- `engine/paths.py` docstring (done in Task 8; check), `engine/py15` docstrings (Task 5; check).
- Specs `2026-09-05-bc-path-resolution-design.md`, `2026-09-06-first-run-folder-picker-design.md`, `2026-10-15-pyc-only-mod-modules-design.md`: a one-line note at the top: "Superseded in part by 2026-11-11-no-sdk-runtime-design.md (the game no longer reads the SDK)."
- The spec's Status line: "implemented on `feat/no-sdk-runtime`; not live-verified".

- [ ] **Step 1:** Make the edits.
- [ ] **Step 2:** `uv run pytest tests/docs tests/unit/test_path_indirection.py tests/unit/test_gate_tiers.py -q` → PASS. Also run the boot-notice wording test (`grep -rl "NOT MADE OR SUPPORTED" tests`) → PASS (wording untouched).
- [ ] **Step 3: Commit** (explicit paths)

```bash
git commit -m "docs: players need only Bridge Commander; the SDK is for development"
```

---

### After the tasks

- Whole-branch review (fresh reviewer, told the CLAUDE.md banned-git list and the focused-tests rule).
- Hand Mark the live-check commands (spec §7), run by him in the worktree after removing `paths.sdk` from the worktree's own `settings.json`: first-run screen with one folder, E1M1 intro, a Quick Battle, the LC Intrepid `.pyc` torpedoes. No gate on this branch; the merge gate runs once when Mark says to merge.
