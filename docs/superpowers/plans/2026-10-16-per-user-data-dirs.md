# Per-user data dirs — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A packaged Dauntless build writes settings, saves, mods, caches and logs only to per-user OS folders. A source checkout keeps writing exactly where it does today.

**Architecture:**
- `engine/paths.py` gains a small "where do user files go" authority:
  - a per-OS folder lookup;
  - a three-way mode (override → one root in the checkout layout; packaged marker → per-OS folders; otherwise → `PROJECT_ROOT` in the checkout layout);
  - resolve-at-use accessors per kind, plus one helper that reports a failed write by path.
- Every write site from the scoping inventory then asks those accessors instead of `PROJECT_ROOT`, `__file__` or the cwd.
- Two guard tests and a read-only end-to-end test lock it in.

**Tech stack:** Python 3.11 stdlib only (`ctypes` on Windows), pytest, the existing C++ host and pybind11 bindings (one binding change).

**Spec:** `docs/superpowers/specs/2026-10-16-per-user-data-dirs-design.md`. The evidence and the write inventory (rows P1–P15, D1, V1–V6) are in `docs/superpowers/specs/2026-10-16-per-user-data-dirs-scoping.md`. Read both.

## Global constraints

- A source checkout with no override and no marker writes every file to **exactly** today's path (design §5.3). Any moved file in a checkout is a failure.
- Paths resolve **at use**. No module-level name may hold a per-user or data-dir path (CLAUDE.md "BC content paths"; `tests/unit/test_path_indirection.py`).
- `engine/paths.py` is the only module that spells `APPDATA`, `LOCALAPPDATA`, `XDG_*`, `Library/...`, the marker filename or `--data-dir`.
- C++ never computes a user folder. Python pushes the path in.
- Folders are created lazily, at the moment of writing, never at boot or on a read.
- No new third-party dependency (Mark ruled: hand-roll, no `platformdirs`).
- Folder names (design §5.1):

  | Kind | Windows | macOS | Linux |
  |---|---|---|---|
  | config | `%APPDATA%\Dauntless` | `~/Library/Application Support/Dauntless` | `$XDG_CONFIG_HOME/dauntless`, else `~/.config/dauntless` |
  | saves | `<config>\saves` | `<config>/saves` | `$XDG_DATA_HOME/dauntless/saves`, else `~/.local/share/dauntless/saves` |
  | mods | `<config>\mods` | `<config>/mods` | `$XDG_DATA_HOME/dauntless/mods`, else `~/.local/share/dauntless/mods` |
  | cache | `%LOCALAPPDATA%\Dauntless\Cache` | `~/Library/Caches/Dauntless` | `$XDG_CACHE_HOME/dauntless`, else `~/.cache/dauntless` |
  | logs | `%LOCALAPPDATA%\Dauntless\Logs` | `~/Library/Logs/Dauntless` | `$XDG_STATE_HOME/dauntless/logs`, else `~/.local/state/dauntless/logs` |

- An `XDG_*` value that is unset, empty or relative is ignored.
- Precedence: `--data-dir` → `DAUNTLESS_DATA_DIR` → packaged marker → checkout. `--mods-dir` / `DAUNTLESS_MODS_DIR` still sit above the mods default. The data-dir flag is never persisted.
- Shared checkout: **no destructive git** (`git checkout -- / restore / stash / clean / reset --hard / add -A / add .`). Stage with explicit paths. Tell every subagent the same.
- Gate: `scripts/check_tests.sh` passes with no new `tests/known_failures.txt` lines.

## Review focus

These are failure modes the spec implies but no task's own tests would otherwise cover. Each now has a test in the named task.

1. **A Windows user name with non-ASCII characters** (`C:\Users\José`). The hull-cache path crosses into C++ as `std::string` and is read in the ANSI codepage, so the cache silently fails. It must round-trip as UTF-8. Owner: Task 7.
2. **A captain name or SDK filename that climbs out of the saves folder** (`saves//../../x.BCS`, `saves\\..\\x`). The resolved path must stay inside `saves_dir()`. Owner: Task 6.
3. **`%APPDATA%` / `XDG_*` set to an empty string or a relative path**, or the Windows known-folder call failing. The lookup must fall back, never return a relative or empty folder. Owner: Task 1.
4. **Log rotation when the old log can't be renamed**: another instance holds it on Windows, or `dauntless.prev.log` is a directory. Startup continues and the console says why. Owner: Task 10.
5. **An override pointing at an existing file or an unwritable place.** Writes fail, each is reported once by path, and the game keeps running. Owner: Task 2.

---

### Task 1: Per-OS user-folder lookup

**Files:**
- Modify: `engine/paths.py` (new section after `project_asset_root`)
- Test: `tests/unit/test_user_dirs_lookup.py`

**Interfaces:**
- Produces:
  - `paths.os_user_dirs(platform: str | None = None, env: Mapping[str, str] | None = None, home: Path | None = None, known_folder: Callable[[str], Path | None] | None = None) -> dict[str, Path]`
    - Returns the keys `"config"`, `"saves"`, `"mods"`, `"cache"`, `"logs"`, all absolute.
    - `platform` defaults to `sys.platform` (`"win32"`, `"darwin"`, other means Linux/XDG).
    - `known_folder` takes `"RoamingAppData"` or `"LocalAppData"`. It defaults to `_windows_known_folder` on win32.
  - `paths._windows_known_folder(name: str) -> Path | None`: `SHGetKnownFolderPath` via `ctypes` (`FOLDERID_RoamingAppData` = `{3EB685DB-65F9-4CF6-A03A-E3EF65729F3D}`, `FOLDERID_LocalAppData` = `{F1B32785-6FBA-4FCF-9D55-7B8E7F157091}`). Returns `None` on any failure. Not called off Windows.

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_user_dirs_lookup.py`:
  - `test_windows_uses_known_folders`: `known_folder` returns `C:/R` and `C:/L` for the two names. Assert config `== Path("C:/R/Dauntless")`, saves `== Path("C:/R/Dauntless/saves")`, mods `== Path("C:/R/Dauntless/mods")`, cache `== Path("C:/L/Dauntless/Cache")`, logs `== Path("C:/L/Dauntless/Logs")`.
  - `test_windows_falls_back_to_env_when_known_folder_fails`: `known_folder` returns `None` and the env holds `APPDATA` / `LOCALAPPDATA`. The env values are used.
  - `test_windows_ignores_empty_or_relative_env`: `known_folder` returns `None`, `APPDATA=""`, `LOCALAPPDATA="rel"`. Falls back to `home/AppData/Roaming` and `home/AppData/Local`. **Review focus 3.**
  - `test_macos_layout`: `home=/h` gives `/h/Library/Application Support/Dauntless`, `.../saves`, `.../mods`, `/h/Library/Caches/Dauntless` and `/h/Library/Logs/Dauntless`.
  - `test_linux_xdg_set`: absolute `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, `XDG_CACHE_HOME` and `XDG_STATE_HOME` give `<cfg>/dauntless`, `<data>/dauntless/saves`, `<data>/dauntless/mods`, `<cache>/dauntless` and `<state>/dauntless/logs`.
  - `test_linux_xdg_unset_empty_or_relative_uses_defaults`: parametrized over unset, `""` and `"relative/x"`. The `~/.config`, `~/.local/share`, `~/.cache` and `~/.local/state` defaults are used under `home`. **Review focus 3.**
  - `test_every_result_is_absolute`: for each platform branch, every value `.is_absolute()`.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_user_dirs_lookup.py -v`. Expected: FAIL, `AttributeError: module 'engine.paths' has no attribute 'os_user_dirs'`.
- [ ] **Step 3: Implement** `os_user_dirs` and `_windows_known_folder` in `engine/paths.py`. Use the app folder `Dauntless` on win32/darwin and `dauntless` elsewhere. `home` defaults to `Path.home()`. The function is pure apart from its defaults.
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit**
  ```bash
  git add engine/paths.py tests/unit/test_user_dirs_lookup.py
  git commit -m "feat(paths): per-OS user folder lookup"
  ```

### Task 2: Data-dir mode, override and accessors

**Files:**
- Modify: `engine/paths.py`, including `hull_volume_cache_root()` at `:411-421`
- Test: `tests/unit/test_data_dirs.py`; update `tests/unit/test_hull_volume_cache_root.py` if any assertion breaks (its "ends in cache/hull_volumes" assertion must still hold)

**Interfaces:**
- Consumes: `os_user_dirs()` (Task 1).
- Produces (each resolves on every call, reading `sys.argv[1:]` and `os.environ` when not given):
  - `PACKAGED_MARKER = "dauntless-packaged.json"`, `DATA_DIR_FLAG = "--data-dir"`, `DATA_DIR_ENV = "DAUNTLESS_DATA_DIR"`
  - `is_packaged() -> bool`: `(PROJECT_ROOT / PACKAGED_MARKER).is_file()`
  - `data_dir_override(argv=None, env=None) -> Path | None`: flag, then env, through `normalise()`. An empty flag value counts as unset here.
  - `data_layout() -> tuple[str, Path | None]`: `("override", root)`, `("packaged", None)` or `("checkout", PROJECT_ROOT)`
  - `config_dir() -> Path`, `saves_dir() -> Path`, `mods_default_dir() -> Path`, `cache_dir() -> Path`, `log_dir() -> Path`, `log_file_path() -> Path`
    - Checkout layout (override root or `PROJECT_ROOT`): `config_dir()` = root; `saves_dir()` = root/`saves`; `mods_default_dir()` = root/`mods`; `cache_dir()` = root/`cache`; `log_dir()` = root; `log_file_path()` = root/`logs`/`dauntless.log`.
    - Packaged: the `os_user_dirs()` values, and `log_file_path()` = `log_dir()/"dauntless.log"`.
  - `hull_volume_cache_root() -> Path` = `cache_dir() / "hull_volumes"`
  - `report_write_failure(path, exc: BaseException) -> None`: prints `[dauntless] could not write <path>: <ExcType>: <exc>` to `sys.stderr` **once per path per process**, regardless of `--developer`. It never raises.

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_data_dirs.py`. Each test `monkeypatch.delenv(DATA_DIR_ENV, raising=False)` first, because Task 3 sets it suite-wide.
  - `test_checkout_layout_is_todays_layout`: no marker, no override. `config_dir() == PROJECT_ROOT`, `saves_dir() == PROJECT_ROOT/"saves"`, `mods_default_dir() == PROJECT_ROOT/"mods"`, `cache_dir() == PROJECT_ROOT/"cache"`, `log_dir() == PROJECT_ROOT`, `hull_volume_cache_root() == PROJECT_ROOT/"cache"/"hull_volumes"`.
  - `test_override_flag_beats_env_beats_marker`: monkeypatch `PROJECT_ROOT` to a tmp dir containing the marker, and set both the flag (via a patched `sys.argv`) and the env. The flag's root wins. Without the flag, the env wins. Without either, `data_layout()[0] == "packaged"`.
  - `test_override_uses_checkout_layout`: `DAUNTLESS_DATA_DIR=<tmp>/d` gives `config_dir() == <tmp>/d` and `saves_dir() == <tmp>/d/saves`.
  - `test_packaged_uses_os_user_dirs`: marker present, `os_user_dirs` monkeypatched to known values. Each accessor returns its value.
  - `test_resolved_at_call_time`: change the env between two calls and see the second call reflect it.
  - `test_accessors_create_nothing`: calling every accessor under an override to a missing dir leaves it missing.
  - `test_report_write_failure_prints_once_per_path` (capsys): two calls for the same path and one for another give exactly two lines, each naming its path.
  - `test_override_pointing_at_a_file_reports_and_continues` (**Review focus 5**): override to an existing *file*. `SettingsStore().save()` doesn't raise, and the reported line names the path. (This depends on Task 4's wiring; mark it `xfail(strict=True, reason="wired in Task 4")` here and remove the mark in Task 4.)
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_data_dirs.py tests/unit/test_hull_volume_cache_root.py -v`. Expected: FAIL on the missing names.
- [ ] **Step 3: Implement** the constants and functions above in `engine/paths.py`, reusing `_flag_value` / `_UNSET` / `normalise`. Rebase `hull_volume_cache_root()` on `cache_dir()`.
- [ ] **Step 4: Run** the same command. Expected: PASS, with the xfail reported as xfail.
- [ ] **Step 5: Commit** `engine/paths.py` and the two test files: `feat(paths): data-dir mode, override and per-kind accessors`.

### Task 3: Test suite runs under the override

**Files:**
- Modify: `tests/conftest.py` (right after `_paths.configure(_RESOLUTION)`, ~line 30)
- Test: `tests/unit/test_suite_data_dir_isolation.py`; fix whatever the gate shows depended on the developer's real `settings.json`

**Interfaces:**
- Consumes: `paths.DATA_DIR_ENV`, `paths.ENV_VARS`, `mods.ENV_VAR`.
- Produces: for the whole session, `DAUNTLESS_DATA_DIR` is a fresh temp dir. `DAUNTLESS_GAME_DIR` / `DAUNTLESS_SDK_DIR` are set from `_RESOLUTION` (so a later `paths.resolve()`, e.g. `host_loop.py:9919`, still finds content without the real `settings.json`). `DAUNTLESS_MODS_DIR` is `PROJECT_ROOT/"mods"` unless already set, which keeps today's mod coverage. All of these use `setdefault`, so a developer's own env still wins.

- [ ] **Step 1: Write the failing tests:**
  - `test_suite_data_dir_is_a_temp_dir`: `paths.data_layout()[0] == "override"` and the root is not under `PROJECT_ROOT`.
  - `test_suite_still_finds_content_without_settings_json`: `paths.resolve().ok` is true, and its source for both roots is `"env"` (or `"cli"` if the developer passed flags).
  - `test_suite_keeps_project_mods`: `mods.mods_root() == PROJECT_ROOT/"mods"` when the developer hasn't set `DAUNTLESS_MODS_DIR`.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_suite_data_dir_isolation.py -v`. Expected: FAIL (layout is `"checkout"`).
- [ ] **Step 3: Implement** the `setdefault` block in `tests/conftest.py`. Use `tempfile.mkdtemp(prefix="dauntless-test-data-")`, and remove the dir in a session-finish hook.
- [ ] **Step 4: Run** `scripts/check_tests.sh`. Expected: green. Any test that read the real `settings.json`, or asserted a `PROJECT_ROOT` data path without `delenv`, now fails. Fix each such test to set what it needs explicitly; never baseline one.
- [ ] **Step 5: Commit** `tests/conftest.py`, the new test and any fixed tests: `test: run the suite under a temp DAUNTLESS_DATA_DIR`.

### Task 4: Settings files (P1–P3) go to the config dir

**Files:**
- Modify: `engine/settings_store.py:44-48` (`default_settings_path`) and `:190-206` (save failure); the `.corrupt` quarantine at `:120` is reported the same way
- Test: `tests/unit/test_settings_location.py`; remove the xfail from Task 2's `test_override_pointing_at_a_file_reports_and_continues`

**Interfaces:**
- Consumes: `paths.config_dir()`, `paths.report_write_failure()`.
- Produces: `default_settings_path() -> Path` = `paths.config_dir() / "settings.json"`. `bridge_selection.py:243` and `quickbattle/presets.py:21` follow unchanged.

- [ ] **Step 1: Write the failing tests:**
  - `test_settings_bridges_presets_land_in_config_dir`: under an override, save all three stores and assert all three files exist in `config_dir()`.
  - `test_checkout_settings_path_unchanged`: with `delenv` and no marker, `default_settings_path() == PROJECT_ROOT/"settings.json"`.
  - `test_failed_save_is_reported_not_raised`: make `config_dir()` an existing file. `save()` returns normally and `report_write_failure` was called with the settings path (capsys).
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_settings_location.py tests/unit/test_data_dirs.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** Re-point `default_settings_path`. In `save()`'s `except`, call `paths.report_write_failure(self._path, exc)` alongside the existing `dev_mode.log_swallowed`.
- [ ] **Step 4: Run** the same tests plus `tests/unit/test_bridge_selection.py tests/unit/test_qb_presets.py`. Expected: PASS.
- [ ] **Step 5: Commit**: `feat(settings): settings, bridges and presets follow config_dir`.

### Task 5: `Options.cfg` and `Keybindings.cfg` (P4, P5) go to the config dir

**Files:**
- Modify: `engine/appc/config_mapping.py:108-140` (`SaveConfigFile`, `_resolve_path`)
- Test: `tests/unit/test_config_mapping_location.py`

**Interfaces:**
- Consumes: `paths.config_dir()`, `paths.report_write_failure()`.
- Produces: `TGConfigMapping._resolve_path(filename) -> Path`. An absolute name is unchanged; a relative name gives `paths.config_dir() / <name with \\ → />`. `LoadConfigFile` uses the same resolution. A failed save returns 0 **and** reports.

- [ ] **Step 1: Write the failing tests:**
  - `test_bare_options_cfg_resolves_into_config_dir`: under an override, `SaveConfigFile("Options.cfg") == 1` and the file exists at `config_dir()/"Options.cfg"`, not in the cwd (`monkeypatch.chdir(tmp_path/"elsewhere")`).
  - `test_keybindings_round_trip_in_config_dir`: `InputMap().save()` then a fresh `InputMap` load reads it back from `config_dir()`.
  - `test_absolute_name_untouched`.
  - `test_checkout_options_cfg_path_unchanged`: `delenv`, `_resolve_path("Options.cfg") == PROJECT_ROOT/"Options.cfg"`.
  - `test_failed_save_reports`: `config_dir()` is a file, save returns 0, reported once.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_config_mapping_location.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** in `config_mapping.py`. Update `_resolve_path`'s docstring: the headless harness no longer writes beside the cwd.
- [ ] **Step 4: Run** the new tests plus `tests/host/test_quickbattle_boot.py`. Expected: PASS.
- [ ] **Step 5: Commit**: `feat(config): BC .cfg files resolve into config_dir, not the cwd`.

### Task 6: Saves (P6–P9) go to the saves dir

**Files:**
- Modify: `engine/appc/save_load.py:31-52` (`_save_dir`, `_normalize`), `:86-135`
- Test: `tests/unit/test_save_location.py` (extend `tests/unit/test_save_load.py` only if a test there pinned `Path.cwd()`)

**Interfaces:**
- Consumes: `paths.saves_dir()`, `paths.report_write_failure()`.
- Produces:
  - `_save_dir() -> Path` returns `paths.saves_dir()` and **does not create it**.
  - `_normalize(filename: str) -> Path` strips a leading `saves/`, `saves\\` or `saves//`, then returns `saves_dir()/<rest>`. If the result does not stay inside `saves_dir()`, it raises `ValueError`, which the callers' existing `except` turns into a return of 0.
  - Writers create the parent folder right before writing.
  - `SaveToFile` / `SaveMissionState` failures report via `report_write_failure`.

- [ ] **Step 1: Write the failing tests:**
  - `test_autosave_name_lands_in_saves_dir`: `SaveToFile("saves//Captain Save-E1M1Picard.BCS") == 1`, and the file is at `saves_dir()/"Captain Save-E1M1Picard.BCS"`.
  - `test_quicksave_backslash_form`: `"saves\\QuickSav.BCS"` ends up in the same folder.
  - `test_mission_state_lands_in_saves_missions`.
  - `test_load_does_not_create_saves_dir`: `LoadFromFile("saves\\QuickSav.BCS") == 0` and `saves_dir()` still doesn't exist (P9).
  - `test_escape_attempts_stay_inside` (**Review focus 2**): parametrized over `"saves//../../x.BCS"`, `"saves\\..\\..\\x.BCS"` and `"/abs/x.BCS"`. `SaveToFile` returns 0 and nothing is written outside `saves_dir()`.
  - `test_checkout_saves_path_unchanged`: `delenv`, `_normalize("saves\\QuickSav.BCS") == PROJECT_ROOT/"saves"/"QuickSav.BCS"`.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_save_location.py tests/unit/test_save_load.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** the changes. Check containment with `Path.resolve()` on both sides and `is_relative_to`.
- [ ] **Step 4: Run** the same tests. Expected: PASS.
- [ ] **Step 5: Commit**: `feat(saves): saves follow saves_dir; loads no longer mkdir; no path escape`.

### Task 7: Caches (P10, P11, P13) and the UTF-8 cache path

**Files:**
- Modify:
  - `engine/ui/weapon_icons.py:103` and its users (`:198-201`, `:319`): replace `_SVG_CACHE_DIR` with `_svg_cache_dir() -> str` = `str(paths.cache_dir()/"icons"/"weapons")`;
  - `engine/ui/damage_icons.py:50`, `:116`, `:166`: the same, `icons/damage`;
  - `engine/ui/ship_icons.py:49,96-101`: keep `_CACHE_DIR`'s repo path, but write it only when `dev_mode.is_enabled()`;
  - `native/src/host/host_bindings.cc:7523-7526`: `hull_volume_set_cache_root` builds the path with `std::filesystem::u8path(root)` (pybind11 hands UTF-8);
  - `engine/host_loop.py:10098` stays as is; it already pushes `paths.hull_volume_cache_root()`.
- Test: update `tests/unit/test_weapon_icons.py:393,417,440` and `tests/unit/test_ship_icons.py:11,33,58`, which monkeypatch the old constants. Add `tests/unit/test_cache_location.py`.

**Interfaces:**
- Consumes: `paths.cache_dir()`, `paths.report_write_failure()`, `dev_mode.is_enabled()`.
- Produces: the private `weapon_icons._svg_cache_dir()` and `damage_icons._svg_cache_dir()`. Tests patch `DAUNTLESS_DATA_DIR` instead of the constant. A trace write that fails now also calls `report_write_failure(out_path, exc)`; until now it was swallowed.

- [ ] **Step 1: Write the failing tests:**
  - `test_weapon_and_damage_traces_land_in_cache_dir`: under an override with a fixture TGA, `icon_svg_for_num(n)` writes under `cache_dir()/"icons"/"weapons"` and `"damage"`.
  - `test_ship_icon_png_written_only_in_dev_mode`: with dev mode off, `icon_path_for_species` returns a data URL and nothing is written to `_CACHE_DIR`. With dev mode on, the PNG is written.
  - `test_hull_cache_root_round_trips_non_ascii` (**Review focus 1**, needs `_dauntless_host`): set the root to `<tmp>/José/cache`, call `hull_volume_bake_to_disk` on a tiny hull, and assert a `.dhv` exists under that exact directory. On macOS/Linux this passes either way; it protects the Windows run in Task 13.
  - Rewrite the six old monkeypatch sites to use the env override.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_cache_location.py tests/unit/test_weapon_icons.py tests/unit/test_ship_icons.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** the changes above. Rebuild with `cmake --build build -j`.
- [ ] **Step 4: Run** the same tests plus `ctest --test-dir build -R hull_volume`. Expected: PASS.
- [ ] **Step 5: Commit** the Python, C++ and test files: `feat(cache): icon and hull caches follow cache_dir; UTF-8 cache root`.

### Task 8: Mods root default (P12, V2)

**Files:**
- Modify: `engine/mods.py:60-82` (`mods_root`, last line)
- Test: `tests/unit/test_mods_discovery.py` (extend)

**Interfaces:**
- Consumes: `paths.mods_default_dir()`.
- Produces: `mods.mods_root(argv=None, env=None) -> Path`: flag → env → `paths.mods_default_dir()`. The gate writer and the SPV mod save follow automatically.

- [ ] **Step 1: Write the failing tests:** `test_mods_default_follows_data_dir` (override and no `DAUNTLESS_MODS_DIR` gives `<override>/mods`), `test_mods_flag_and_env_still_win`, and `test_checkout_mods_default_unchanged`.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_mods_discovery.py -v`. Expected: FAIL on the first test.
- [ ] **Step 3: Implement** the one-line change and update the docstring.
- [ ] **Step 4: Run** the same tests. Expected: PASS.
- [ ] **Step 5: Commit**: `feat(mods): default mods root follows the data dir`.

### Task 9: Diagnostics (D1, V5, V6) and dev authoring refusals (V1, V3, V4)

**Files:**
- Modify:
  - `engine/core/stub_telemetry.py:38-48,204-229`: `SIDECAR_PATH` is removed. `_default_sidecar_path()` is called inside `persist_run` and returns `DAUNTLESS_STUB_TELEMETRY_FILE`, else `str(paths.log_dir()/"stub_hits.jsonl")`. Its swallowed failure now also calls `paths.report_write_failure`;
  - `engine/ui/ai_inspector_panel.py:28,111`: `EXPORT_PATH` → `_export_path() -> Path` = `paths.log_dir()/"ai_inspector_export.json"`;
  - `engine/dev_keybindings.py:216`: `paths.log_dir()/"nonfinite_dumps"`, computed inside the toggle;
  - `engine/paths.py`: add `refuse_repo_write_when_packaged(path) -> None`;
  - call `refuse_repo_write_when_packaged(target)` before writing in `engine/appc/override_routing.py:HardpointOverridesFileTarget.write`, `engine/appc/decals_writer.py:write_decals` and `engine/bridge_editor/lighting_writer.py:save`.
- Test: update `tests/unit/test_stub_telemetry_persist.py:61` and `tests/unit/test_ai_inspector_panel.py:132,161,178`. Add `tests/unit/test_dev_writes_when_packaged.py`.

**Interfaces:**
- Consumes: `paths.log_dir()`, `paths.is_packaged()`, `paths.PROJECT_ROOT`.
- Produces: `paths.RepoWriteInPackagedBuild(OSError)` and `paths.refuse_repo_write_when_packaged(path) -> None`. It raises with the message `"<path> is inside the Dauntless install; developer authoring saves need a source checkout"` when `is_packaged()` and the resolved path is under `PROJECT_ROOT`. It is a no-op otherwise. Being an `OSError`, it reaches the panels' existing "Save failed" paths.

- [ ] **Step 1: Write the failing tests:**
  - `test_sidecar_default_is_resolved_at_use`: change the override between two `persist_run()` calls; each writes under the then-current `log_dir()`.
  - `test_sidecar_env_file_still_wins`.
  - `test_checkout_sidecar_unchanged`: `delenv` gives `PROJECT_ROOT/"stub_hits.jsonl"`.
  - `test_ai_export_and_nonfinite_dir_follow_log_dir`.
  - `test_repo_writers_refuse_when_packaged`: monkeypatch `PROJECT_ROOT` to a tmp tree with the marker. All three writers raise `RepoWriteInPackagedBuild` for a target under it, and write normally for a target outside it (a per-user mod).
  - `test_repo_writers_unaffected_in_checkout`.
  - Replace `test_sidecar_path_is_absolute` with an assertion on `_default_sidecar_path()`.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_dev_writes_when_packaged.py tests/unit/test_stub_telemetry_persist.py tests/unit/test_ai_inspector_panel.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** the changes above.
- [ ] **Step 4: Run** the same tests. Expected: PASS.
- [ ] **Step 5: Commit**: `feat: diagnostics follow log_dir; repo authoring refuses in packaged builds`.

### Task 10: Packaged boot: no bytecode, rotated log tee

**Files:**
- Create: `engine/log_tee.py`
- Modify: `engine/__init__.py` (end of file)
- Test: `tests/unit/test_log_tee.py`, `tests/unit/test_packaged_boot.py`

**Interfaces:**
- Consumes: `paths.is_packaged()`, `paths.log_file_path()`.
- Produces:
  - `log_tee.rotate(path: Path) -> str | None`: renames `path` to `<stem>.prev.log` (replacing any old one) and returns an error string instead of raising.
  - `log_tee.start(path: Path) -> bool`: creates the parent, rotates, then duplicates **file descriptors 1 and 2** into a pipe whose reader thread writes every chunk to the original console fds **and** to the file (flushed per chunk). It returns False, with one console line saying why, if anything fails; the process continues untouched. It is idempotent.
  - `log_tee.stop() -> None`: restores the fds and joins the thread. Registered with `atexit`.
  - In `engine/__init__.py`, when `paths.is_packaged()`: set `sys.dont_write_bytecode = True`, then `log_tee.start(paths.log_file_path())`. This is wrapped so no exception escapes `import engine`.

- [ ] **Step 1: Write the failing tests:**
  - `test_tee_captures_python_and_fd_level_writes` (subprocess, `python -I` with `PYTHONPATH=PROJECT_ROOT`): start the tee on `<tmp>/dauntless.log`, then `print("py-out")`, `sys.stderr.write("py-err\n")` and `os.write(2, b"fd-err\n")` (stand-in for C++ `fprintf`), then `stop()`. Assert all three lines are in the file **and** in the subprocess's captured stdout/stderr.
  - `test_rotation_keeps_one_previous`: two starts leave `dauntless.prev.log` holding the first run's text.
  - `test_rotation_failure_does_not_block_start` (**Review focus 4**): make `dauntless.prev.log` a directory. `start` still returns True, the new run's text reaches the file, and the console has one line naming the rotation failure.
  - `test_unwritable_log_dir_returns_false_and_continues`.
  - `test_packaged_import_disables_bytecode_and_starts_tee` (subprocess): a tmp copy of `engine/` with the marker at its root, `DAUNTLESS_DATA_DIR` set. `import engine` gives `sys.dont_write_bytecode is True` and `<data>/logs/dauntless.log` exists.
  - `test_checkout_import_starts_nothing`: in the normal suite, `sys.dont_write_bytecode` is unchanged and no log file exists.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_log_tee.py tests/unit/test_packaged_boot.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `engine/log_tee.py` and the `engine/__init__.py` hook. Use `os.pipe`, `os.dup`/`os.dup2` and a daemon thread. Write to the console fds with `os.write` (works on Windows; under the host they are the console). Flush `sys.stdout` / `sys.stderr` before redirecting.
- [ ] **Step 4: Run** the same tests. Expected: PASS.
- [ ] **Step 5: Commit**: `feat(packaged): no bytecode writes; stdout/stderr teed to a rotated log`.

### Task 11: Static guard against install-folder writes

**Files:**
- Create: `tests/unit/test_install_write_guard.py` (reuse `_sources()` and `_parse_or_skip` by importing them from `tests/unit/test_path_indirection.py`)

**Interfaces:**
- Consumes: nothing new.
- Produces: `_ALLOWED_REPO_WRITERS: dict[str, str]` maps a module path to its reason.
  - It starts with:
    - `engine/appc/override_routing.py`: V1 hardpoint authoring; `_PATH` is beside `__file__`.
    - `engine/appc/decals_writer.py` (V3) and `engine/bridge_editor/lighting_writer.py` (V4): dev authoring into the repo.
    - `engine/ui/ship_icons.py`: the dev-mode-only inspection PNG (Task 7).
    - `engine/ui/weapon_icons.py`: its tool-only `export_reference_pngs` writes curated references into the repo.
  - For any other hit, fix the site. Add it here only if it is dev authoring into the repo, with its reason.
  - `gate_writer.py` doesn't need an entry: its target comes from the mods index, not from a project-derived path.

- [ ] **Step 1: Write the tests:**
  - `test_no_function_writes_to_a_project_derived_path`: AST-walk `engine/` and the root shims. In each function containing a write call (`open` with a literal mode containing `w`, `a`, `x` or `+`; `.write_text`, `.write_bytes`, `.mkdir`, `os.makedirs`, `os.replace`, `os.rename`, `os.remove`, `.unlink`, `shutil.copy*`/`move`), fail if it also references `PROJECT_ROOT`, `_PROJECT_ROOT`, `__file__`, `Path.cwd`, `os.getcwd`, or `os.path.abspath` with a relative string literal. Modules in `_ALLOWED_REPO_WRITERS` are skipped.
  - `test_no_module_level_project_path_constant_in_a_writing_module`: a module-level `Assign` whose value references `PROJECT_ROOT` / `_PROJECT_ROOT` / `__file__`, in a module that has any write call, fails unless the module is allowlisted.
  - `test_allowlist_has_no_stale_entries`: every allowlisted module exists and still contains a write call.
- [ ] **Step 2: Prove it bites:** back up `engine/appc/save_load.py` to `/tmp/bak_save_load.py`, temporarily re-add `base = Path.cwd() / "saves"` in `_save_dir`, run the guard, and see it FAIL naming that function. Restore with `cp /tmp/bak_save_load.py engine/appc/save_load.py` and `diff` to prove the file is byte-identical. **Never use git to restore.**
- [ ] **Step 3: Run** `uv run pytest tests/unit/test_install_write_guard.py -v`. Expected: PASS on the real tree. If it finds a site this plan missed, fix the site in a new commit; don't allowlist it unless it is dev authoring.
- [ ] **Step 4: Commit**: `test: static guard against install-folder writes`.

### Task 12: Dynamic guard and the QuickBattle-without-`Options.cfg` question (H1)

**Files:**
- Create: `tests/helpers/write_audit.py`, `tests/integration/test_no_install_writes.py`, `tests/host/test_quickbattle_unwritable_config.py`

**Interfaces:**
- Produces:
  - `write_audit.install_once() -> None`, which adds one `sys.addaudithook` for the process, recording when enabled.
  - `write_audit.recording() -> ContextManager[list[tuple[str, str, str]]]`, yielding `(event, abs_path, first_project_frame)` for write-mode `open` (mode string or `os.open` flags with `O_WRONLY|O_RDWR|O_CREAT|O_APPEND|O_TRUNC`) and for `os.mkdir`, `os.rename`, `os.replace`, `os.remove`, `os.rmdir` and `shutil.*`.
  - The scoping run's hook (in the scoping note §2) is the reference shape.

- [ ] **Step 1: Write the tests:**
  - `test_campaign_missions_write_nothing_into_install_or_game`: parametrized over `test_warp_button_handler_sweep.MISSIONS`. Inside `recording()`: `headless_mission.load(name)`, press Warp, and tick as that sweep does. Assert no record's path is under `paths.PROJECT_ROOT` or `paths.game_root()`, ignoring `__pycache__` segments. Assert at least one record landed under `saves_dir()` for an autosaving mission (proving the hook saw the autosave).
  - `test_quickbattle_boot_writes_nothing_into_install`: the boot from `tests/host/test_quickbattle_boot.py` (reuse its `_FakeRenderer` by import) under `recording()`. Assert `Options.cfg` landed in `config_dir()` and nothing landed under the install or game roots.
  - `test_quickbattle_boot_with_unwritable_config_dir` (H1): override to a dir that is then `chmod 0o500`, with no `Options.cfg`. Boot QuickBattle. **Record what happens first.** Then make the outcome deliberate. Either the boot completes, or `host_loop`'s boot raises a `RuntimeError` naming `config_dir()` before `StartSimulation` is reached. The test pins whichever you choose, with a comment saying why. Restore permissions in a `finally`.
- [ ] **Step 2: Run** `uv run pytest tests/integration/test_no_install_writes.py tests/host/test_quickbattle_unwritable_config.py -v`. Expected: the two guards PASS (Tasks 4–9 already moved the writes). H1 is whatever you recorded.
- [ ] **Step 3: Prove the guard bites:** back up `engine/appc/save_load.py`, temporarily point `_save_dir` at `paths.PROJECT_ROOT/"saves"`, and see the campaign test FAIL. Restore by `cp` and verify with `diff`.
- [ ] **Step 4:** If H1 needed a code change in `engine/host_loop.py:7518-7526`, make it, keep the comment there accurate, and re-run.
- [ ] **Step 5: Commit** the helpers, the tests and any `host_loop.py` change: `test: dynamic guard for install writes; pin QuickBattle with unwritable config`.

### Task 13: Read-only packaged end-to-end

**Files:**
- Create: `tests/integration/test_packaged_readonly_e2e.py`, `tests/helpers/packaged_layout.py`

**Interfaces:**
- Produces:
  - `packaged_layout.build(dest: Path) -> Path`: copies `engine/`, the project-root `*.py` shims and `native/assets/` into `dest`, writes `dest/PACKAGED_MARKER`, and returns `dest`. It never copies `settings.json`, `Options.cfg`, `Keybindings.cfg`, `saves/`, `cache/` or `mods/`.
  - `packaged_layout.make_readonly(root)` / `restore_writable(root)`.
  - `packaged_layout.tree_digest(root) -> str`: a sha256 over relative paths and bytes.

- [ ] **Step 1: Write the test** `test_packaged_build_writes_only_to_user_folders`:
  - Build the layout in `tmp/install`, take a digest and make it read-only.
  - Run a subprocess `python -I -c <driver>` with cwd = `tmp/install` and `PYTHONPATH=tmp/install` plus the `build/python` dir.
  - Env: `HOME=tmp/home`, all `XDG_*` unset, `APPDATA` / `LOCALAPPDATA` under `tmp/home` (Windows), and `DAUNTLESS_GAME_DIR` / `DAUNTLESS_SDK_DIR` from the conftest resolution. `DAUNTLESS_DATA_DIR` and `DAUNTLESS_MODS_DIR` are **not** set.
  - The driver asserts `engine.__file__` is inside `tmp/install`, then exercises, through real engine code:
    - `SettingsStore().save()`, the bridges store and the presets store;
    - `TGConfigMapping().SaveConfigFile("Options.cfg")` and `InputMap().save()`;
    - `SaveLoadManager().SaveToFile("saves//Captain Save-E1M1Test.BCS")` and `SaveMissionState` with a mission name set;
    - `LoadFromFile` of a missing file;
    - `weapon_icons.icon_svg_for_num` and `damage_icons.icon_svg_for_num` on one icon each;
    - `stub_telemetry.persist_run()`;
    - printing `paths.hull_volume_cache_root()` and `mods.mods_root()`;
    - writing one line to stderr.
  - Then assert:
    - each file exists under the expected per-OS folder for the current platform (`paths.os_user_dirs(home=tmp/home)` computed in the test);
    - `dauntless.log` exists in the logs folder and contains the stderr line;
    - `sys.dont_write_bytecode` was True in the child;
    - the child's stderr has no `[dauntless] could not write` line;
    - `tree_digest(install)` is unchanged.
  - `restore_writable` runs in a `finally`.
- [ ] **Step 2: Run** `uv run pytest tests/integration/test_packaged_readonly_e2e.py -v`. Expected: PASS. A failure here is a real missed write: fix the site and re-run.
- [ ] **Step 3: Run the gate:** `scripts/check_tests.sh`. Expected: exit 0, no new ledger lines.
- [ ] **Step 4: Windows check.** Ask Mark to run `uv run pytest tests/unit/test_user_dirs_lookup.py tests/unit/test_cache_location.py tests/integration/test_packaged_readonly_e2e.py -v` in the Windows environment (`scripts/win_env.bat`), ideally from a non-ASCII user profile. Record the result in the commit message or a follow-up note. Don't call Windows verified until it has run there.
- [ ] **Step 5: Commit** the helpers and the e2e test: `test: read-only packaged end-to-end`.

### Task 14: Documentation

**Files:**
- Modify: `CLAUDE.md` (the "BC content paths" table row and section), `engine/paths.py` module docstring, `docs/superpowers/specs/2026-10-16-per-user-data-dirs-design.md` (status line: implemented; H1 outcome)

- [ ] **Step 1:** In `CLAUDE.md`, add one row to the reference table: user data dirs, `engine/paths.py`, the design spec, the three modes, "never write under `PROJECT_ROOT` outside the guard's allowlisted authoring writers", and the two guard tests. Add one sentence to "BC content paths — one authority": the data-dir accessors follow the same resolve-at-use rule.
- [ ] **Step 2:** Record the H1 outcome and the Windows check result in the design doc.
- [ ] **Step 3: Run** `uv run pytest tests/docs -q`. Expected: PASS (the doc-consistency tests).
- [ ] **Step 4: Commit** `CLAUDE.md`, `engine/paths.py` and the spec: `docs: per-user data dirs`.
