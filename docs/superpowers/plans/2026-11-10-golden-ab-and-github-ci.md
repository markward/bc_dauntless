# Golden A/B and GitHub CI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop committing per-tick golden recordings, replace them with an on-demand base-vs-HEAD A/B tool, and add a small GitHub Actions CI: builds on three platforms plus the project's rules checks, with no unit or gameplay tests on GitHub.

**Architecture:** Three phases, each mergeable on its own. (A) The golden scenes stay as code. Their recordings and the record/compare machinery go, and the invariants they asserted become plain tests. (B) `tools/golden_ab.py` runs each scene in a child pytest process in two trees, a cached detached worktree of the base commit and the current tree, and compares the rows. (C) A workflow builds on Linux/macOS/Windows; the Linux job then runs a size check and a fixed list of tree guards and drift tests against a fake (markers-only) BC install. Nothing to maintain beyond the workflow and a large-file allowlist.

**Tech Stack:** Python 3.11 (uv), pytest, CMake + googletest, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-11-10-golden-ab-and-github-ci-design.md`

## Global Constraints

- ⛔ Never run `git checkout -- / restore / stash / clean / reset --hard / add -A / add .`. Stage with explicit pathspecs only (CLAUDE.md "Shared checkout"). The only worktree commands the A/B tool may run are `git worktree add --detach` and `git worktree remove` on its own `golden-ab-base-*` paths.
- ⛔ No gate runs (`gate_merge.sh` / `gate_full.sh`) and no whole-suite pytest runs. Run only the focused test files each task names, plus the tree guards: `tests/docs`, `tests/unit/test_path_indirection.py`, `tests/unit/test_install_write_guard.py`, `tests/unit/test_gate_tiers.py`.
- ⛔ Never run the golden A/B tool, any golden scene test (each runs 300–1500 ticks), or the game without asking Mark first. This machine is used for perf testing.
- ⛔ Never push, open a PR or trigger a workflow without asking Mark first. Phase C's verification needs pushes, so each push is a checkpoint.
- No BC content (game files or SDK) on GitHub: not uploaded, cached or in an artifact.
- Never spell `game` or `sdk` as a path segment in code (`tests/unit/test_path_indirection.py`). Use `engine.paths`. A fixture building a fake install tree marks the line `# paths-guard: <reason>`.
- `tools/ci/large_files.txt` is the only list this work adds; every entry carries a reason.
- Thresholds (spec §7.3): a file under `tests/` over **256 KB** (262144 bytes) fails. Any other file over **5 MB** (5242880 bytes) fails unless allowlisted. Any changed file over **1 MB** (1048576 bytes) is listed in the summary.
- CI builds **Debug**, the canonical build type (spec §7.1).
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
2. **`test_scene_skips_identical_writes_and_audit_is_clean` loses its golden comparison and gets no replacement.** Its oracle (behaviour from before write-skipping existed) has done its job, and the audit assertion it keeps proves mirror agreement.

## Review Focus

1. **A base too old for the tool**, whose `golden_fight.py` has no `run_scene` or `SCENES`: expect a tool error naming the requirement, never a crash or "differs". Pinned in Task 5.
2. **Base equals HEAD:** every scene `identical`, no harness warning, exit 0. Pinned in Task 6.
3. **A scene that crashes on one side:** reported `error` with the child's tail, exit 2, never "differs". Pinned in Task 5.
4. **A rules check that skips on GitHub** (it quietly needs BC content): the step fails, never passes green. Pinned in Task 7 (`check_no_skips`).
5. **A push with no usable size-check base** (a new branch's first push gives `github.event.before` as forty zeros): fall back to `git merge-base HEAD origin/main`, never crash or skip the check. Pinned in Task 7.

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

## Phase C — GitHub CI (builds plus rules checks; spec §7)

### Task 7: The rules checks, runnable locally

**Files:**
- Create: `tools/ci/check_sizes.py`, `tools/ci/large_files.txt`, `tools/ci/fake_install.py`, `tools/ci/check_no_skips.py`, `tests/helpers/fake_install.py`
- Create: `tests/tools/test_ci_tools.py`, `tests/unit/test_known_failures_has_no_failures.py`
- Modify: `tests/conftest.py` (the `fake_bc_install` fixture body only)

**Interfaces:**
- `check_sizes.check(changes: list[tuple[str, int]], allow: dict[str, str]) -> tuple[list[str], list[str]]` returns (failures, notices). The thresholds are in Global Constraints.
- `check_sizes.load_allowlist(path) -> dict` reads lines `<path>  # <reason>`. A missing reason raises `ValueError`.
- `check_sizes.resolve_base(base: str) -> str`: an empty or all-zero sha becomes `git merge-base HEAD origin/main`.
- CLI `check_sizes.py --base REV`: changed files come from `git diff --name-only --diff-filter=AM <base>...HEAD`, sizes from the working tree. It prints everything, appends to `$GITHUB_STEP_SUMMARY` when set, and exits 1 on any failure.
- `tools/ci/large_files.txt` is seeded with every tracked file over 5242880 bytes, from `git ls-tree -r -l HEAD`. After Phase A that should be only `native/assets/textures/scuff_normal.tga`; verify.
- `tests/helpers/fake_install.make_fake_install(root: Path) -> tuple[Path, Path]`: the fixture's current body, verbatim, with its `# paths-guard:` comments. The fixture becomes `return make_fake_install(tmp_path / "install")`.
- `tools/ci/fake_install.py <dir>` builds the install and prints `DAUNTLESS_GAME_DIR=<game>` and `DAUNTLESS_SDK_DIR=<sdk>`, one per line, for `$GITHUB_ENV`.
- `check_no_skips.py <junit.xml>` exits 1 and names each skipped test if the JUnit file records any skip; otherwise exits 0.

- [ ] **Step 1: Tests in `tests/tools/test_ci_tools.py`.**
  - `test_test_file_limit`: `tests/x.json.gz` at 262145 bytes fails; at 262144 it passes.
  - `test_other_file_limit_and_allowlist`: `native/a.png` at 5242881 bytes fails; with `{"native/a.png": "art"}` allowlisted it passes.
  - `test_notice_over_1mb`: a file at 1048577 bytes appears in the notices.
  - `test_allowlist_needs_reason`.
  - `test_zero_sha_base_falls_back`: with `subprocess.run` patched, `resolve_base("0" * 40)` calls merge-base (Review Focus 5).
  - `test_fake_install_validates`: `engine.paths.validate_game_root(game).ok` and `validate_sdk_root(sdk).ok`.
  - `test_no_skips_flags_a_skip`: a minimal JUnit XML with one `<skipped/>` → exit 1 and the test name is printed; without it → exit 0 (Review Focus 4).
- [ ] **Step 2: Test in `tests/unit/test_known_failures_has_no_failures.py`.** Every non-comment line of `tests/known_failures.txt` starts with `skip:` or `optional-mod:`.
- [ ] **Step 3:** `uv run pytest tests/tools/test_ci_tools.py tests/unit/test_known_failures_has_no_failures.py -q`. Expected: FAIL, the modules are missing.
- [ ] **Step 4:** Implement, and seed the allowlist.
- [ ] **Step 5:** Run step 3's command plus `uv run pytest tests/unit/test_path_indirection.py tests/unit/test_install_write_guard.py -q`. Expected: PASS.
- [ ] **Step 6: Run the rules list against a fake install locally** (a few guard files, so focused, not a suite):
  - `eval "$(uv run python tools/ci/fake_install.py "$TMPDIR/fi" | sed 's/^/export /')"`
  - Then `uv run pytest <spec §7.3 item 1 files> tests/unit/test_known_failures_has_no_failures.py -q --junitxml="$TMPDIR/rules.xml"` and `uv run python tools/ci/check_no_skips.py "$TMPDIR/rules.xml"`.
  - Expected: all pass with no skips. Any file that fails or skips because it needs content comes off the list; record which one in the commit message.
- [ ] **Step 7: Commit.**

### Task 8: The workflow

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Triggers: `pull_request`, `push: branches: [main]` and `workflow_dispatch`, with `permissions: contents: read`. Never `pull_request_target`.
- Job `linux` (`ubuntu-24.04`):
  1. Checkout with `fetch-depth: 0`.
  2. apt packages for GLFW and CEF. Find them by building, and give each a one-line comment.
  3. Pinned `astral-sh/setup-uv`, `uv python install 3.11`, `uv sync --extra dev`.
  4. Cache `build/_deps`, keyed on the runner OS plus `hashFiles('native/CMakeLists.txt')`.
  5. `cmake -B build -S . -DCMAKE_BUILD_TYPE=Debug -DPython3_EXECUTABLE=$PWD/.venv/bin/python`, then `cmake --build build -j`.
  6. The size check with `--base` set to `origin/${{ github.base_ref }}` on a PR and `${{ github.event.before }}` on a push or dispatch.
  7. The fake install into `$GITHUB_ENV`.
  8. pytest on Task 7 step 6's final file list with `--junitxml`, then `check_no_skips.py`.
- Job `macos` (`macos-14`, arm64): steps 1, 3, 4 and 5 only.
- Job `windows` (`windows-2022`): steps 1, 3 and 4. A pinned `ilammy/msvc-dev-cmd` sets up MSVC. Configure with the Ninja generator and `-DPython3_EXECUTABLE=${{ github.workspace }}\.venv\Scripts\python.exe`, with CEF on, then `cmake --build build -j`. Leave `core.autocrlf` alone (`.gitattributes` forces LF).
- Each job's first summary line: "Builds and rules checks only: no unit or gameplay tests run on GitHub."

- [ ] **Step 1: Write `ci.yml`.**
- [ ] **Step 2: Lint.** Run `uvx --from actionlint-py actionlint .github/workflows/ci.yml`, or if that's unavailable, `uv run python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"`. Expected: no errors.
- [ ] **Step 3: Commit.**
- [ ] **Step 4: ⛔ Ask Mark** to push `feat/golden-ab-ci` and open a draft PR. Watch with `gh run watch`. Fix each job until green (Linux first, then macOS, then Windows). Each fix is its own commit, and every push needs Mark's OK. If a platform's build needs a source fix, that fix is in scope. Name it in the hand-off.
- [ ] **Step 5: Hand-off note to Mark:** run times per job (cold and cached), the apt packages, any check dropped from the rules list, any source fix a platform needed, and that merging stays his call (no branch protection is added).
