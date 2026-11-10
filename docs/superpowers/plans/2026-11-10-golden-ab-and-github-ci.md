# Golden A/B and GitHub CI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop committing per-tick golden recordings, replace them with an on-demand base-vs-HEAD A/B tool, and add GitHub Actions CI that checks the project's rules, builds on three platforms and runs the tests that need no BC content.

**Architecture:** Three phases, each mergeable on its own. (A) The golden scenes stay as code. Their recordings and the record/compare machinery go, and the invariants they asserted become plain tests. (B) `tools/golden_ab.py` runs each scene in a child pytest process in two trees, a cached detached worktree of the base commit and the current tree, and compares the rows. (C) A workflow runs a size check and the tree guards, then builds on Linux/macOS/Windows and runs a generated list of CI-runnable tests against a fake (markers-only) BC install. Per-platform failure ledgers only ever shrink.

**Tech Stack:** Python 3.11 (uv), pytest, CMake + googletest, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-11-10-golden-ab-and-github-ci-design.md`

## Global Constraints

- ⛔ Never run `git checkout -- / restore / stash / clean / reset --hard / add -A / add .`. Stage with explicit pathspecs only (CLAUDE.md "Shared checkout"). The only worktree commands the A/B tool may run are `git worktree add --detach` and `git worktree remove` on its own `golden-ab-base-*` paths.
- ⛔ No gate runs (`gate_merge.sh` / `gate_full.sh`) and no whole-suite pytest runs. Run only the focused test files each task names, plus the tree guards: `tests/docs`, `tests/unit/test_path_indirection.py`, `tests/unit/test_install_write_guard.py`, `tests/unit/test_gate_tiers.py`.
- ⛔ Never run the golden A/B tool, any golden scene test (each runs 300–1500 ticks), or the game without asking Mark first. This machine is used for perf testing.
- ⛔ Never push, open a PR or trigger a workflow without asking Mark first. Phase C's verification needs pushes, so each push is a checkpoint.
- No BC content (game files or SDK) on GitHub: not uploaded, cached or in an artifact.
- Never spell `game` or `sdk` as a path segment in code (`tests/unit/test_path_indirection.py`). Use `engine.paths`. A fixture building a fake install tree marks the line `# paths-guard: <reason>`.
- Generated lists are never hand-edited. Each has a generator and a guard test.
- Thresholds (spec §7.2): a file under `tests/` over **256 KB** (262144 bytes) fails. Any other file over **5 MB** (5242880 bytes) fails unless allowlisted. Any changed file over **1 MB** (1048576 bytes) is listed in the summary.
- CI builds **Debug**: the `RockPerfEquivalence.Near*` digests are bit-exact only at -O0.
- Commit messages through `git commit -F <file>` (a hook trips on some inline messages), ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Before Task 1: worktree setup (once)

The branch `feat/golden-ab-ci` lives at `.claude/worktrees/golden-ab-ci` and has no build. In that directory:

```bash
cp ../../../settings.json .
mkdir -p mods && cp -Rc ../../../mods/. mods/
uv sync --extra dev
```

Then configure and build with the recipe in memory `feedback_worktrees_runtime_deps`, plus `-DFETCHCONTENT_SOURCE_DIR_<DEP>=<main>/build/_deps/<dep>-src` for CEF, GOOGLETEST, NLOHMANN_JSON, OPENAL_SOFT, PYBIND11 and FREETYPE:
- `-DCMAKE_BUILD_TYPE=Debug`
- `-DPython3_EXECUTABLE=$PWD/.venv/bin/python3`
- `-DPython3_ROOT_DIR=<uv cpython-3.11 dir>` (copy it from the main checkout's `build/CMakeCache.txt`)
- `-DPython3_FIND_FRAMEWORK=NEVER -DPython3_FIND_STRATEGY=LOCATION`

Never symlink or clone `build/`. Check: `uv run pytest tests/unit/test_gate_tiers.py -q` passes.

## Deviations from the spec (decided while planning; tell Mark at hand-off)

1. **The live motion comparison runs both arms in one process, not in child processes** (spec §5). `run_scene` is already built to run scenes back to back in one process: the suite has always run `test_motion_branches` and `test_motion_branches_python_motion_arm` that way.
2. **The no-content mode is a fake install, not a conftest bypass** (spec §7.3). CI points `DAUNTLESS_GAME_DIR`/`DAUNTLESS_SDK_DIR` at a markers-only tree built by the existing `fake_bc_install` logic, so the conftest's fail-fast never changes. The conftest only gains a collection filter, active when `DAUNTLESS_CI_TIER=1`.
3. **The two lists are named `ci_*` and `local_*`, not `content_free`/`needs_content`.** A test can be local-only for reasons other than content, such as needing a GPU.
4. **Classification is per file where it can be.** A file whose tests all classify the same way is listed as the file, so a new test in that file inherits its class. A file whose tests split is listed function by function. "Unclassified" therefore means a new file, or a new function in a split file.
5. **The first classification happens automatically.** When the lists don't exist yet, the Linux job runs every test and uploads the lists as an artifact. Later wholesale rebuilds use `workflow_dispatch`.
6. **`test_scene_skips_identical_writes_and_audit_is_clean` loses its golden comparison and gets no replacement.** Its oracle (behaviour from before write-skipping existed) has done its job, and the audit assertion it keeps proves mirror agreement.

## Review Focus

1. **A base too old for the tool**, whose `golden_fight.py` has no `run_scene` or `SCENES`: expect a tool error naming the requirement, never a crash or "differs". Pinned in Task 5.
2. **Base equals HEAD:** every scene `identical`, no harness warning, exit 0. Pinned in Task 6.
3. **A scene that crashes on one side:** reported `error` with the child's tail, exit 2, never "differs". Pinned in Task 5.
4. **A Windows command line too long for a list of tests:** CI passes lists by file (pytest conftest filter, gtest `--gtest_flagfile`), never on the command line. Pinned in Task 9.
5. **A ledgered test that now passes:** the job fails with "remove it from the ledger". Pinned in Task 10.

---

## Phase A — retire the recordings

### Task 1: The row vocabulary and the subsystem scene move into helpers

**Files:**
- Create: `tests/helpers/golden_rows.py` (no engine, SDK or pytest imports)
- Create: `tests/helpers/subsystems_scene.py`
- Modify: `tests/helpers/golden_fight.py`, `tests/integration/test_native_subsystems_scene.py`
- Test: `tests/unit/test_golden_rows.py`, `tests/integration/test_native_subsystems_scene.py`

**Interfaces:**
- Produces, in `golden_rows`: `COMPONENTS`, `FIELDS`, `EVENT_FIELDS` (moved verbatim); `first_difference(want, got, at=()) -> tuple | None` (was `golden_fight._first_difference`); `differences(want, got, limit: int) -> list[tuple]`, every `(at, want, got)` up to `limit`, in `first_difference`'s order; `describe(t: int, at: tuple, want_row) -> str` (was `_describe`); `norm(v)` (was `_norm`).
- `golden_fight` re-exports these names. Its own uses switch to them.
- `subsystems_scene.run() -> Result`, where `Result` is a NamedTuple `(log, handled, counts, events, skips, rigged, audit)` (today's `_run()` tuple); `subsystems_scene.canonical_rows(log) -> list` (today's `_golden_rows`); constants `SHIPS="16"`, `TICKS=600`, `SEED=20261105`.
- `golden_fight.SCENES["native_subsystems_scene"] = Scene("native_subsystems_scene", "native", SEED, SHIPS, TICKS, 1, _native_subsystems)`. Its run returns canonical rows (a `list`), and `run_scene` returns a `list` take unchanged instead of passing it through `_canonical`.

- [ ] **Step 1: Write `tests/unit/test_golden_rows.py`**
  - `test_first_difference_names_path`: `first_difference([0,[1,2]],[0,[1,3]]) == ((1,1),2,3)`.
  - `test_differences_lists_all_up_to_limit`: `len(differences([1,2,3],[4,5,6],limit=2)) == 2`.
  - `test_describe_names_kind_label_field`: for the row `["weapon","Player/Phaser 1",["bool",True],"Enemy-1",["float","0x1p+0"]]` at path `(1,0,4)`, the result contains `"tick 2"`, `"weapon 'Player/Phaser 1'"` and `"_fire_timer"`.
  - `test_module_is_light`: in a subprocess, `python -c "import tests.helpers.golden_rows, sys; assert 'engine' not in sys.modules and 'pytest' not in sys.modules"` exits 0.
  - Add `test_subsystems_scene_is_a_golden_scene` to `test_golden_rows.py`: imports `golden_fight`, then asserts `SCENES["native_subsystems_scene"].ticks == 600` and that its `run` is `golden_fight._native_subsystems`.
- [ ] **Step 2:** `uv run pytest tests/unit/test_golden_rows.py -q`. Expected: FAIL, module not found.
- [ ] **Step 3: Move the code.**
  - Move the moved names into `golden_rows.py`. Move `_World`, `ShieldWatcherHandler`, `_hex`, `_ser`, the field tuples, `TRACKED` and `_run` into `subsystems_scene.py`.
  - ⚠️ Find every place the handler is registered by module path (search `ShieldWatcherHandler` and `__name__` in the moved code) and point it at `tests.helpers.subsystems_scene`.
  - The test module keeps its `_clean` fixture and imports from the helper.
- [ ] **Step 4:** `uv run pytest tests/unit/test_golden_rows.py -q`. Expected: PASS.
- [ ] **Step 5: Ask Mark**, then run `uv run pytest tests/integration/test_native_subsystems_scene.py -q`. Expected: PASS against the still-present golden. This proves the move changed nothing.
- [ ] **Step 6: Commit** the five files.

### Task 2: Retire the recordings; invariants and the live motion check stay

**Files:**
- Delete: `tests/fixtures/golden_fights/` (all 11 files, `git rm`)
- Modify: `tests/helpers/golden_fight.py`, `tests/integration/test_golden_fights.py`, `tests/integration/test_native_subsystems_scene.py`

**Interfaces:**
- Consumes: Task 1's `golden_rows.first_difference`, `describe`, and `subsystems_scene`.
- Removed from `golden_fight`: `record`, `check`, `path`, `header`, `_load`, `_encode`, `_decode`, `_key`, `_digest`, `_drop_baked_offset`, `_UPGRADES`, `FIXTURES`, `UPDATE_ENV`, `SCHEMA`, `_LAST_ARM`, the `gzip`/`hashlib` imports, and the docstring's re-record instructions.
- **Keep every existing test node ID** in `test_golden_fights.py`, so `tests/gate_tiers/deep_pytest.txt` stays valid with no regeneration.

- [ ] **Step 1: Rewrite the scene tests in `test_golden_fights.py`.**
  - `_golden(name)` becomes `_invariants(name)`. It runs `rows = golden_fight.run_scene(name, arm)` and asserts `len(rows) == golden_fight.SCENES[name].ticks + 1`, plus the existing `_no_turn_goal_hand_backs()` and `_no_subsystem_skips()`.
  - `run_scene` already asserts `k1_no_fire` is all zero.
  - Each `test_<scene>` keeps its name and calls `_invariants`.
- [ ] **Step 2: Make `test_motion_branches_python_motion_arm` a live comparison.**
  - `nat = run_scene("motion_branches", "native")`, then `py = run_scene("motion_branches", "python_motion")`. Assert `native_motion.counts()["native_calls"] == 0` after the second run.
  - For each tick `t`, `d = golden_rows.first_difference(nat[t], py[t])`. Assert `d is None`, with the message `describe(t, d[0], nat[t])`. Also assert `len(nat) == len(py)`.
- [ ] **Step 3: Delete the recorder tests and add a guard.**
  - Delete `test_golden_missing_platform_skips`, `_tiny_rows`, `test_golden_round_trip_and_first_difference` and `test_golden_schema_2_reads_without_baked_offset`. Keep `test_golden_arm_is_native_only`.
  - Add `test_no_recordings_are_committed`: asserts `not (Path(__file__).parents[1] / "fixtures" / "golden_fights").exists()`.
- [ ] **Step 4: Update `test_native_subsystems_scene.py`.**
  - `test_combat_scene_runs_every_piece_natively` drops the `monkeypatch.setitem`/`record`/`check` lines and keeps every other assertion.
  - `test_scene_skips_identical_writes_and_audit_is_clean` drops its `setitem`/`check` and keeps its stats, skips and audit assertions (deviation 6).
  - Update both docstrings.
- [ ] **Step 5: Delete the fixtures and the recorder code** listed above. Rewrite the module docstring's last paragraph: scenes are code, the A/B tool compares them across commits, nothing is recorded.
- [ ] **Step 6:** `uv run pytest tests/integration/test_golden_fights.py -q -k "arm_is_native_only or no_recordings"` and `uv run pytest tests/unit/test_golden_rows.py tests/unit/test_gate_tiers.py -q`. Expected: PASS.
- [ ] **Step 7: Ask Mark**, then run `uv run pytest tests/integration/test_golden_fights.py tests/integration/test_native_subsystems_scene.py -q`. Expected: all pass. This runs every scene (~10 min).
- [ ] **Step 8: Commit** with `git rm -r tests/fixtures/golden_fights` plus the three modified files.

### Task 3: Docs say the recordings are gone

**Files:**
- Modify: `CLAUDE.md` (lines 49 and 51)
- Modify: `docs/reference/engine/native-motion/golden-fights-for-motion.md`, `docs/reference/engine/native-combat/k1-retirement-map.md`, `docs/reference/engine/native-motion/radius-scale-audit.md`, `docs/reference/architecture/test-suite-audit.md`, `docs/reference/architecture/test-suite-memory.md`
- Modify: `native/tests/combat/k1_fire_control_test.cc:6`

- [ ] **Step 1: Edit CLAUDE.md.**
  - In the "Native combat mirror" row, replace `tests/integration/test_golden_fights.py` with `tests/integration/test_golden_fights.py` (scene invariants) plus `tools/golden_ab.py` (cross-commit A/B).
  - In the "Native AI tree engine" row, change "goldens" to "golden scenes". Don't touch other rows.
- [ ] **Step 2: Edit the reference docs.** Each gets a dated one-paragraph note at the top, "2026-11-10: recordings retired; scenes are compared across commits with `tools/golden_ab.py`; see spec <path>". Leave their history text alone. `UPDATE_COMBAT_GOLDEN` instructions become "historical".
- [ ] **Step 3:** `uv run pytest tests/docs -q`. Expected: PASS.
- [ ] **Step 4: Commit.** **Phase A is mergeable here.** Tell Mark. The merge gate runs only when he says to merge.

## Phase B — the golden A/B tool

### Task 4: Compare and report (pure)

**Files:**
- Create: `tools/golden_ab_compare.py`
- Test: `tests/tools/test_golden_ab_compare.py`

**Interfaces:**
- Consumes: `tests.helpers.golden_rows` (`differences`, `describe`, `COMPONENTS`).
- Produces:
  - `SceneDiff` dataclass: `scene: str`, `status: str` (one of `"identical"`, `"differs"`, `"only in base"`, `"only in HEAD"`, `"error"`), `first_tick: int | None`, `fields: list[str]`, `differing_ticks: int`, `last_tick: int | None`, `first_kind: str | None`, `error: str | None`.
  - `compare_scene(scene: str, base_rows: list, head_rows: list) -> SceneDiff`
  - `format_value(v) -> str`
  - `format_report(diffs: list[SceneDiff], harness_changed: list[str]) -> str`
  - `exit_code(diffs) -> int`: 2 if any `error`, else 1 if any `differs`/`only in *`, else 0.

- [ ] **Step 1: Write tests on tiny hand-built rows** (shape `(tick, state, events, queued, calls, presented, notes)`, as in the deleted `_tiny_rows`):
  - `test_identical`: status `"identical"`, `exit_code == 0`.
  - `test_first_tick_fields_and_counts`: rows differ at ticks 2 and 4 → `first_tick == 2`, `differing_ticks == 2`, `last_tick == 4`, `first_kind == "state/weapon"`, and `fields[0]` contains `"'Player/Phaser 1'"`, `"_fire_timer"` and `"2.0 → 2.5"`.
  - `test_fields_capped_at_20`: 30 differing fields in one tick → `len(fields) == 20`.
  - `test_length_mismatch`: head one tick shorter → status `"differs"`, `fields` mentions `"ticks"`.
  - `test_format_value`: `format_value("0x1.4p+1") == "2.5 [0x1.4p+1]"`; non-float strings and ints pass through.
  - `test_report_harness_warning_first_line`: with `harness_changed=["tests/helpers/k1_fight.py"]`, the first line starts `"WARNING: harness differs"` and names the file.
  - `test_report_only_in_and_error`: statuses render as `only in base` / `only in HEAD` / `error: <first line>`, and `exit_code` is 1 / 1 / 2.
- [ ] **Step 2:** `uv run pytest tests/tools/test_golden_ab_compare.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - `first_kind` is the component name, and for `state` also `"/" + row kind`.
  - A field line reads `"<describe(...)>: <base> → <head>"`.
  - The report has one line per scene, `"<scene>: <status>"`. Each `differs` scene adds an indented block: first tick, fields, "N ticks differ, last at T".
- [ ] **Step 4:** Same command. Expected: PASS.
- [ ] **Step 5: Commit.**

### Task 5: The child and the side runner

**Files:**
- Create: `tests/helpers/golden_ab_child.py`, `tools/golden_ab_side.py`
- Test: `tests/tools/test_golden_ab_side.py`

**Interfaces:**
- Child (run by pytest in a tree): `test_child()`. It skips unless `GOLDEN_AB_OUT` is set.
  - With `GOLDEN_AB_LIST=1`, it writes `sorted(golden_fight.SCENES)` as JSON to `GOLDEN_AB_OUT`.
  - Otherwise it runs `golden_fight.run_scene(os.environ["GOLDEN_AB_SCENE"], "native")` and writes the rows to `GOLDEN_AB_OUT` as one zlib-compressed JSON array (`json.dumps(rows, sort_keys=True, separators=(",", ":"))`, compressed a row at a time). It imports nothing from `tests/helpers` except `golden_fight` and `bc_assets`, so it runs in any base that has them.
  - It sets `DAUNTLESS_MODS_DIR` to an empty temp dir and calls `bc_assets.require_game_dir("data/Models/Ships/BirdOfPrey")`, as the golden fixture did.
- Side runner:
  - `run_child(tree: Path, env: dict, out: Path) -> None` raises `ChildError(tail: str)` on a non-zero exit. The command is `[sys.executable, "-m", "pytest", "tests/helpers/golden_ab_child.py::test_child", "-q", "-x", "-p", "no:cacheprovider"]` with `cwd=tree`.
  - `child_env(base_env: dict) -> dict` adds `DAUNTLESS_GAME_DIR`/`DAUNTLESS_SDK_DIR` from `engine.paths.game_root()`/`sdk_root()` and a fresh temp `DAUNTLESS_DATA_DIR`.
  - `list_scenes(tree) -> list[str]`, `run_scene_rows(tree, scene) -> list`.
  - `install_child(tree: Path) -> None` copies HEAD's `golden_ab_child.py` into `tree/tests/helpers/` (untracked; used for the base tree).
  - `check_base_usable(tree) -> str | None`: an error message if `tree/tests/helpers/golden_fight.py` lacks `def run_scene` or `SCENES =`, and the message names the missing piece. The base never needs `golden_rows.py`: only the parent, on HEAD, compares.

- [ ] **Step 1: Tests, with `subprocess.run` monkeypatched; no scene runs.**
  - `test_child_env_points_at_resolved_roots`.
  - `test_run_child_raises_with_tail`: a fake process with return code 1 and stdout "boom" → `ChildError` whose tail contains "boom".
  - `test_check_base_usable`: a tmp tree whose `golden_fight.py` lacks `def run_scene` → a message naming it; with `def run_scene` and `SCENES =` → `None`.
  - `test_install_child_copies_into_tree`.
- [ ] **Step 2:** `uv run pytest tests/tools/test_golden_ab_side.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement both files.**
- [ ] **Step 4:** Same command, plus `uv run pytest tests/helpers/golden_ab_child.py -q` (skips: no `GOLDEN_AB_OUT`). Expected: PASS, and 1 skipped.
- [ ] **Step 5: Commit.**

### Task 6: Base tree, builds and the CLI

**Files:**
- Create: `tools/golden_ab_build.py`, `tools/golden_ab.py`
- Test: `tests/tools/test_golden_ab_build.py`

**Interfaces:**
- `cache_options(cache_text: str, build_dir: Path) -> list[str]`: `-D` args copied from HEAD's `CMakeCache.txt`. It takes `CMAKE_BUILD_TYPE`, `DAUNTLESS_ENABLE_CEF` and whichever of `Python3_EXECUTABLE`, `Python3_ROOT_DIR`, `Python3_FIND_FRAMEWORK`, `Python3_FIND_STRATEGY` are present. It adds `-DDAUNTLESS_BUILD_TESTS=OFF`, plus `-DFETCHCONTENT_SOURCE_DIR_<UPPER>=<build_dir>/_deps/<dep>-src` for each `<dep>-src` directory that exists (`openal_soft` → `OPENAL_SOFT`).
- `base_tree_path(main_root: Path, sha: str) -> Path` returns `main_root/.claude/worktrees/golden-ab-base-<sha[:12]>`. `main_root` is the parent of `git rev-parse --path-format=absolute --git-common-dir`.
- `ensure_base(sha, head_build: Path) -> Path`: reuses the tree if its `HEAD == sha` and `build/python/_dauntless_host*` exists. Otherwise it runs `git worktree add --detach <path> <sha>`, then `cmake -B build -S . <cache_options>`, then `cmake --build build --target _dauntless_host -j`.
- `build_head(tree) -> None`: `cmake --build <tree>/build --target _dauntless_host -j`. It errors if `CMakeCache.txt` is missing.
- `harness_changed(base_sha) -> list[str]`: `git diff --name-only <sha> -- tests/helpers tests/conftest.py`, run in the current tree (this includes uncommitted changes).
- `prune_bases(main_root) -> list[Path]`: `git worktree remove --force` on each `golden-ab-base-*` path only.
- CLI `tools/golden_ab.py [--base REV] [--scene NAME ...] [--prune]`. `--base` defaults to `git merge-base HEAD main`. Errors exit 2. The help text says: run from the branch's own worktree; on demand only, never in a gate or CI; it rebuilds HEAD first.
- Flow:
  1. Resolve the sha.
  2. `build_head(cwd)`, then `ensure_base`, `install_child(base)` and `check_base_usable`.
  3. List scenes on both sides.
  4. For each scene, serially, run both sides. A child error becomes `SceneDiff(status="error")`.
  5. Print `format_report(diffs, harness_changed)` and exit with `exit_code`.

- [ ] **Step 1: Tests (no git or cmake run).**
  - `test_cache_options_copies_build_type_python_and_deps`: from a sample cache text and a tmp build dir holding `_deps/cef-src` and `_deps/openal_soft-src`, assert the exact `-D` list.
  - `test_base_tree_path`.
  - `test_prune_only_touches_own_paths`: `subprocess.run` patched, worktree list fixture with `golden-ab-base-abc` and `feature-x` → only the first is removed.
  - `test_cli_same_base_and_head_reports_identical`: monkeypatch `ensure_base`, `build_head`, `list_scenes` and `run_scene_rows` to return equal rows → stdout every scene `identical`, exit 0 (Review Focus 2).
- [ ] **Step 2:** `uv run pytest tests/tools/test_golden_ab_build.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** Same command. Expected: PASS.
- [ ] **Step 5: Live check, only after asking Mark** (this builds a base tree and runs a scene).
  - Run `uv run python tools/golden_ab.py --base 5be71b598^ --scene tractor_modes`.
  - Expected: the harness warning (the helpers changed since then), `tractor_modes: differs`, first tick **620** (the recorded reason of `e8d2c880a`: power pacing's starve beat), exit 1.
  - Then `--base HEAD --scene tractor_modes` → `identical`, no warning, exit 0.
- [ ] **Step 6: Commit.** **Phase B is mergeable here.**

## Phase C — GitHub CI

### Task 7: Layer 1 checks that run locally

**Files:**
- Create: `tools/ci/check_sizes.py`, `tools/ci/large_files.txt`, `tests/tools/test_ci_check_sizes.py`, `tests/unit/test_known_failures_has_no_failures.py`

**Interfaces:**
- `check(changes: list[tuple[str, int]], allow: dict[str, str]) -> tuple[list[str], list[str]]` returns (failures, notices).
- `load_allowlist(path) -> dict` reads lines of the form `<path>  # <reason>`. A missing reason is an error.
- CLI `check_sizes.py --base REV`: changed files come from `git diff --name-only --diff-filter=AM REV...HEAD`, sizes from the working tree. It prints the notices and failures, appends both to `$GITHUB_STEP_SUMMARY` if set, and exits 1 on any failure.
- The allowlist is seeded with every tracked file over 5242880 bytes at the commit that adds it (`git ls-tree -r -l HEAD`). After Phase A that should be only `native/assets/textures/scuff_normal.tga`; verify.

- [ ] **Step 1: Tests.**
  - `tests/x.json.gz` at 262145 bytes fails; at 262144 it passes.
  - `native/a.png` at 5242881 bytes fails, unless allowlisted.
  - Any file at 1048577 bytes appears in the notices.
  - An allowlist line without a reason raises.
  - `test_known_failures_has_no_failures`: every non-comment line of `tests/known_failures.txt` starts with `skip:` or `optional-mod:`.
- [ ] **Step 2:** Run both test files. Expected: FAIL (the module is missing; the ledger test passes already, and that's fine).
- [ ] **Step 3: Implement and seed the allowlist.**
- [ ] **Step 4:** Run them again. Expected: PASS.
- [ ] **Step 5: Commit.**

### Task 8: Fake install, the CI tier lists, the classifier

**Files:**
- Create: `tests/helpers/fake_install.py`, `tests/helpers/ci_tiers.py`, `tools/ci_tiers.py`, `tools/ci/fake_install.py`
- Modify: `tests/conftest.py` (the `fake_bc_install` fixture body; a collection filter)
- Test: `tests/unit/test_ci_tiers_logic.py`

**Interfaces:**
- `make_fake_install(root: Path) -> tuple[Path, Path]` holds the fixture's current body, verbatim. The fixture becomes `return make_fake_install(tmp_path / "install")`.
- `tools/ci/fake_install.py <dir>` builds it and prints `DAUNTLESS_GAME_DIR=...` and `DAUNTLESS_SDK_DIR=...` lines (for `$GITHUB_ENV`).
- Lists live in `tests/ci_tiers/`: `ci_pytest.txt`, `local_pytest.txt`, `ci_gtest.txt`, `local_gtest.txt`, with a GENERATED header like the gate tiers'.
  - pytest entries: a file, or `path::function`.
  - gtest entries: `Suite.*` or `Suite.Case` (binary-agnostic; TEST_P names are normalised with `gate_tiers.split_gtest`).
- `ci_tiers.load(name) -> list[str]`, `ci_tiers.matcher(entries) -> Callable[[str], bool]` (pytest: reuse `gate_tiers.deep_matcher`), and `gtest_matcher(entries)`.
- `classify_pytest(outcomes: dict[str, str]) -> tuple[list, list]`: maps nodeid to `passed`/`failed`/`skipped`/`error`. Only `passed` counts as CI. A file whose every function agrees collapses to the file. Function keys come from `gate_tiers.function_key`. A function with mixed parametrize outcomes is local.
- `classify_gtest(outcomes: dict[str, str]) -> tuple[list, list]`, with the same rule per suite.
- `unclassified_pytest() -> list[str]` uses `gate_tiers.all_test_files`/`tests_in_file`, with keys matched by neither list. `unclassified_gtest()` uses `gate_tiers.cpp_tests()`.
- `stale_entries() -> list[str]`: entries naming tests that no longer exist.
- `tools/ci_tiers.py` subcommands:
  - `generate <results dir>`: reads `pytest.xml` (JUnit) and `gtest_*.xml` and rewrites all four lists. Rewriting the lists is allowed only here and in `classify`.
  - `classify`: locally, builds a fake install in a temp dir and runs ONLY the unclassified pytest keys and the unclassified gtest cases (each binary with `--gtest_filter`, `--gtest_output=xml`) against it. It merges the results into the lists, keeping existing entries.
  - `flagfile <binary> <out>`: writes `--gtest_filter=<ci entries>` for gtest's `--gtest_flagfile`.
- Conftest: when `DAUNTLESS_CI_TIER=1`, `pytest_ignore_collect` ignores any test file with no CI entry, and `pytest_collection_modifyitems` deselects items the CI matcher rejects. Outside that variable, behaviour is unchanged.

- [ ] **Step 1: Tests (pure; no subprocess).**
  - `test_classify_collapses_agreeing_file`.
  - `test_classify_splits_mixed_file`.
  - `test_skip_is_local`.
  - `test_mixed_params_are_local`.
  - `test_gtest_suite_collapse`.
  - `test_unclassified_finds_new_file`: monkeypatch the lists to empty → a known test key is unclassified.
  - `test_stale_entry_reported`.
  - `test_ci_filter_inactive_without_env`: the conftest hook functions return `None`/keep everything when the variable is unset; call them directly with fake items.
  - `test_fake_install_validates`: `engine.paths.validate_game_root(game).ok` and `validate_sdk_root(sdk).ok`.
- [ ] **Step 2:** `uv run pytest tests/unit/test_ci_tiers_logic.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** Same command, plus `uv run pytest tests/unit/test_path_indirection.py tests/unit/test_install_write_guard.py -q`. Expected: PASS.
- [ ] **Step 5: Commit.** The guard test that requires every test to be classified lands in Task 9, together with the first lists.

### Task 9: Linux workflow, bootstrap classification, the guard

**Files:**
- Create: `.github/workflows/ci.yml`, `tools/ci/run_tests.py`, `tests/unit/test_ci_tiers.py`, `tests/ci_tiers/*.txt` (from the bootstrap artifact)

**Interfaces:**
- `tools/ci/run_tests.py --platform {linux,macos,windows} --results DIR [--all]`. In list mode, pytest runs with `DAUNTLESS_CI_TIER=1 --junitxml=DIR/pytest.xml`, and each gtest binary in `build/` runs with `--gtest_flagfile` (from `ci_tiers.py flagfile`) and `--gtest_output=xml:DIR/gtest_<binary>.xml`. With `--all`, it runs no filters (bootstrap). It never fails on test outcomes itself; Task 10's ledger decides. The binary list comes from `gate_tiers.cpp_tests`'s CMake scan (`gtest_discover_tests` targets), resolved to files under `build/`.
- Workflow `ci.yml`:
  - Triggers: `pull_request`, `push: branches: [main]` and `workflow_dispatch`, with permissions `contents: read`. Never `pull_request_target`.
  - Layer 1 runs inside the `linux` job, not as a job of its own: the pytest guards need the built module, because the conftest's autouse fixture configures native combat. Check out with `fetch-depth: 0`. The size-check base is `origin/${{ github.base_ref }}` on a PR and `${{ github.event.before }}` on a push.
  - Job `linux` (ubuntu-24.04):
    1. apt packages for GLFW, CEF and Mesa (`xvfb`, `libgl1-mesa-dri`; find the rest by building, and list each one with a one-line comment).
    2. Pinned `astral-sh/setup-uv`, `uv python install 3.11`, `uv sync --extra dev`.
    3. Cache `build/_deps`, keyed on the OS plus a hash of `native/CMakeLists.txt`.
    4. Configure with `cmake -B build -S . -DCMAKE_BUILD_TYPE=Debug -DPython3_EXECUTABLE=$PWD/.venv/bin/python`, then `cmake --build build -j`.
    5. Fake install into `$GITHUB_ENV`.
    6. Layer 1: `check_sizes.py`, then `uv run pytest` on the tree guards and drift tests named in spec §7.2 item 1, plus `tests/unit/test_known_failures_has_no_failures.py` and `tests/unit/test_ci_tiers.py`.
    7. Layer 2 under `xvfb-run -a`: `run_tests.py --platform linux`, or `--all` when `tests/ci_tiers/ci_pytest.txt` is absent or on `workflow_dispatch`. In `--all` mode, `tools/ci_tiers.py generate` runs and the four lists are uploaded as artifact `ci-tiers`.
    8. Upload `DIR` as artifact `results-linux`.
  - Every job writes a summary first line: "Content-free tests only: gameplay scenes need BC content and were not run."
- `tests/unit/test_ci_tiers.py` (merge tier, cheap):
  - `test_every_test_is_classified`: `unclassified_pytest() == []` and `unclassified_gtest() == []`, with the message "run `uv run python tools/ci_tiers.py classify`".
  - `test_no_stale_entries`.
  - `test_lists_are_in_generator_order`.
  - `test_no_entry_on_both_lists`.

- [ ] **Step 1:** Write the workflow and `run_tests.py`. Write `tests/unit/test_ci_tiers.py`, but don't commit it yet.
- [ ] **Step 2:** Lint the workflow: `uvx --from actionlint-py actionlint .github/workflows/ci.yml`, or `uv run python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/ci.yml'))"` if actionlint is unavailable. Expected: no errors.
- [ ] **Step 3:** Commit the workflow and `run_tests.py`.
- [ ] **Step 4: ⛔ Ask Mark** to push `feat/golden-ab-ci` and open a draft PR. Watch the run with `gh run watch`. Fix the Linux build until it is green; each fix is a commit, and each push needs Mark's OK.
- [ ] **Step 5:** Download the `ci-tiers` artifact with `gh run download <id> -n ci-tiers -D tests/ci_tiers`. Check the counts are sane: the CI lists are non-empty, and the guards and drift tests named in spec §7.2 are on `ci_pytest.txt`. A guard that landed in `local` because it reads content gets dropped from step 6 of the `linux` job, and the plan's hand-off says so.
- [ ] **Step 6:** `uv run pytest tests/unit/test_ci_tiers.py -q`. Expected: PASS.
- [ ] **Step 7: Commit** the lists and the guard test, then push (with Mark's OK). The next run uses list mode.

### Task 10: Failure ledgers that only shrink

**Files:**
- Create: `tools/ci/ledger.py`, `tools/ci/failing_linux.txt` (seeded), `tests/tools/test_ci_ledger.py`
- Modify: `.github/workflows/ci.yml` (the final step of each platform job)

**Interfaces:**
- Ledger line format: `<test id>  # <reason>`. The test id is a pytest nodeid or `gtest:<Suite.Case>`.
- `failures(results_dir) -> set[str]` covers failed, errored **and skipped** CI-listed tests; a skip counts as a failure.
- `verdict(failing: set, ledger: dict) -> tuple[list, list]` returns (new_failures, now_passing).
- `summary(platform, ledger, new, now_passing) -> str`: the first line is `"<platform>: <N> known platform failures"`, then every entry. The new and now-passing lists are labelled "fix this" and "remove it from the ledger".
- CLI `ledger.py check --platform P --results DIR` writes the summary to `$GITHUB_STEP_SUMMARY` and exits 1 if either list is non-empty.
- CLI `ledger.py seed --platform P --results DIR` refuses if `failing_P.txt` exists. Otherwise it writes every failure with the reason `"seeded <date>: <first line of message>"`. There is no other write path.

- [ ] **Step 1: Tests.**
  - `test_new_failure_fails`.
  - `test_ledgered_now_passing_fails` (Review Focus 5).
  - `test_skip_counts_as_failure`.
  - `test_seed_refuses_existing`.
  - `test_summary_lists_every_entry`.
  - `test_ledger_requires_reason`.
- [ ] **Step 2:** `uv run pytest tests/tools/test_ci_ledger.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implement, and wire `ledger.py check` as each platform job's last step.
- [ ] **Step 4:** Same command. Expected: PASS.
- [ ] **Step 5: Seed Linux.** Take the latest `results-linux` artifact and run `ledger.py seed --platform linux`. Expected: few or none (deviation 5's bootstrap put only passing tests on the list). Commit the ledger and the code, then push with Mark's OK. Expected: the Linux job is green.

### Task 11: macOS and Windows jobs

**Files:**
- Modify: `.github/workflows/ci.yml`
- Create: `tools/ci/failing_macos.txt`, `tools/ci/failing_windows.txt` (seeded)

- [ ] **Step 1: Add job `macos`** (`macos-14`, arm64): the same steps without apt or xvfb, and the same `_deps` cache keyed on the OS.
- [ ] **Step 2: Add job `windows`** (`windows-2022`).
  - Use `ilammy/msvc-dev-cmd` (pinned) for the MSVC environment, and the Ninja generator (as in `scripts/win_env.bat`'s usage).
  - Use `.venv\Scripts\python.exe` as `Python3_EXECUTABLE`, keep CEF on, and run `cmake --build build -j`.
  - `.gitattributes` already forces LF; don't override `core.autocrlf`.
- [ ] **Step 3:** Lint (Task 9 step 2), commit, then push with Mark's OK. Iterate until each job **builds**. Test failures are expected at this point.
- [ ] **Step 4:** For each platform, download `results-<platform>` and run `ledger.py seed --platform <p>`. Read every seeded line, and for a GPU or runner limit, edit only the reason text, e.g. `# no OpenGL 4.1 on the Windows runner`. Changing reasons in the seeding commit is allowed; adding or removing ids is not.
- [ ] **Step 5:** Commit both ledgers, then push with Mark's OK. Expected: all three jobs green, and each summary lists its ledger in full.
- [ ] **Step 6:** Hand-off note to Mark: the ledger counts per platform, the deviations above, and that merging stays his call (CI does not block merges; no branch protection is added).
