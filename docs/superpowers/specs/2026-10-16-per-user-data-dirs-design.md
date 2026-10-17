# Per-user data dirs — design

**Date:** 2026-10-16
**Status:** Implemented on branch feat/per-user-data-dirs (2026-10-16); Windows verification pending
**Input:** `docs/superpowers/specs/2026-10-16-per-user-data-dirs-scoping.md`. It holds the full write inventory (rows P1–P15, D1, V1–V6), the method and its limits, and Mark's seven rulings. This document refers to rows by those IDs and does not repeat the evidence.

## Outcomes

- **H1 (QuickBattle without a writable `Options.cfg`), as observed and decided (Task 12).** Confirmed with one refinement: boot returns normally and prints one write-failure line, but `BuildDialog` early-returns so `g_pStartButton` is None, and the player's Start then raises `AttributeError` in `DisableSimulationMenus`. Decision: boot completes. When the `Options.cfg` save fails, `load_quickbattle` runs the QuickBattle init with `LoadConfigFile("Options.cfg")` answering 1 from the in-memory map, scoped to that call. The player loses that session's options (reported once) but not Quick Battle. Pinned by `tests/host/test_quickbattle_unwritable_config.py`.
- **Ruling 8, the log tee design changed.** The first design was a pipe tee. It deadlocks when one GIL-holding C++ write exceeds about two pipe buffers (measured: 200 KB and 1 MB writes hang on macOS; a Windows pipe holds about 4 KB). It also loses in-pipe output on a crash. Replaced by pointing fds 1 and 2 at the log file itself, so writers never block and whatever reached an fd survives a crash, plus a best-effort follower thread that mirrors new file bytes to the saved console fds on stderr. The console may lag or lose its tail on a hard crash. The file has every stderr write, but not C/C++ stdout text still in a stdio buffer at a hard crash: with fd 1 a file, C stdout is fully buffered, so its last lines can be lost. With no console at all (`sys.stdout`/`sys.stderr` None), the tee installs UTF-8 line-buffered text streams on fds 1/2 for its lifetime, so `print`, write-failure lines and uncaught tracebacks still reach the log.
- **Windows run: pending.** Nothing is claimed verified on Windows. The full checklist is below: the pytest commands, the log tee items (a)–(h), and the Windows-only paths nothing on macOS exercises.
- **Known follow-up, not in this branch.** A second `_init_mission` of the same mission in one process reuses stale module globals (no re-import). E3M4 failed on a re-run. This plausibly affects mission restart in production. The test side evicts mission modules in a fixture.

### Windows checklist (not yet run)

Do not call Windows verified until all of this has run. Report pass, fail or skip (with the skip reason) for each item.

**1. Tests.** Open a Windows terminal in the repo, ideally logged in as a user whose profile path has non-ASCII characters (so `%TEMP%`, `%APPDATA%` and `%LOCALAPPDATA%` do too). Then:

```
scripts\win_env.bat
uv run pytest tests/unit/test_user_dirs_lookup.py tests/unit/test_cache_location.py tests/integration/test_packaged_readonly_e2e.py -v
uv run pytest tests/unit/test_log_tee.py -v
cmake --build build -j
ctest --test-dir build -R "Dhv|Dvox|HullVolumeCache" --output-on-failure
```

- The first command is the per-user folder lookup, the caches and the read-only packaged end-to-end run.
- `test_log_tee.py` checks the fd-level tee. `test_no_console_still_writes_the_log` is the no-console case: `print`, a `report_write_failure` line and an uncaught traceback must all reach the log.
- `Dhv.WritesUnderANonAsciiPath` and `Dvox.WritesUnderANonAsciiPath` are the MSVC regression checks for the `.tmp` sibling path, which used to go through the ANSI code page and throw on an unmappable character. They pass on macOS either way, so only a Windows run proves them.
- `HullVolumeCache.FailedWriteSaysSoOncePerPath` checks the one-line `[dauntless] could not write <path>: <reason>` report for a failed `.dhv` write. On Windows, also check that the path is printed as UTF-8 and is not mangled.

**2. Paths the macOS runs never exercise (Ruling 2).**
- **The known-folder call.** `SHGetKnownFolderPath` (`paths._windows_known_folder`) has never run live. The unit tests inject it. Check that a packaged run lands in `%APPDATA%\Dauntless` (config, saves, mods) and `%LOCALAPPDATA%\Dauntless` (Cache, Logs).
- **The e2e test's hand-executed import.** On win32 only, `import engine` would start the log tee before any patch could apply. So the e2e driver builds the `engine` package by hand, patches `paths._windows_known_folder` to return None (so the env fallback, pointed at a temp dir, is used and the real AppData is untouched), and then executes `engine/__init__.py`. That path is untested; this run is its first.
- **Directory chmod does not make a folder read-only on Windows.** In the read-only e2e test, the guard that actually catches an install write is the before/after digest of the install tree, not the permissions. A pass on Windows comes from the digest.

**3. Log tee, with a real packaged build.** The log is `%LOCALAPPDATA%\Dauntless\Logs\dauntless.log`.

Handled in code, to confirm:
- **(a) Console launch.** `sys.stdout`/`sys.stderr` sit on `_WindowsConsoleIO`, which is rewrapped while the tee runs. Check that `print("é")` and `sys.stderr.write` reach `dauntless.log`, that nothing raises, and that `sys.stdout` is the original object again after `stop()`.
- **(d) No console.** A GUI-subsystem launch, or a launch with the std handles detached, still writes a log with the boot output, and start returns True. `print`, write-failure lines and uncaught tracebacks must be in it, because the tee replaces the None streams.

Still to verify, Windows only:
- **(b) C++ host output.** Check that `fprintf(stderr)` from the C++ host lands in the log. It only will if the host and Python share one dynamic UCRT (`/MD`), because `os.dup2` edits that CRT's fd table.
- **(c) CEF output.** Check that CEF and CEF-helper output lands in the log. It depends on `_dup2` calling `SetStdHandle`, so that CEF children inherit the redirected handles. That happens only for a console-subsystem exe. A GUI exe will very likely log Python output only.
- **(e) Two instances at once.** Start a second instance while the first holds the log open. Rotation should fail with `PermissionError`, there should be one console line about it, and the second instance should append. Check that the two runs' lines do not overwrite each other: CRT `O_APPEND` is emulated by seeking, and children inheriting the OS handle write at the shared position.
- **(f) Follower read.** Check that the read handle on a log open for writing works (CRT share mode deny-none), and that the console mirror appears.
- **(g) C stdio flush.** `_flush_c_stdio` is skipped on Windows, so check whether CEF `printf` lines reach the log before exit.
- **(h) Unicode on a legacy-codepage console.** Check how a non-ASCII line looks in the console mirror. That is cosmetic; the log itself is UTF-8.

Known gap: a console stream captured BEFORE the tee starts (for example a `logging.StreamHandler` created before `import engine`) still holds the original `_WindowsConsoleIO` object, so its writes still go to the console handle and fail while the tee runs. Check whether anything in the packaged boot does this.

**4. Cache write failure, live.** With the cache folder made unwritable, a packaged run prints one `[dauntless] could not write ...dhv: <reason>` line per hull into the log and keeps loading.

## 1. Intent

Dauntless v1 ships for Windows as a portable zip. A player may unpack it anywhere, including somewhere read-only like `Program Files`. **A packaged build must never write inside its own folder**, on Windows, macOS or Linux. Everything it writes goes to the OS's per-user folders.

**A source checkout must behave exactly as it does today.** That covers every file, in the same place, with the same names. Developer workflows and the test suite must not notice.

Today, at least 11 player-reachable writes land in the install folder. All of them swallow their own failure. On a read-only install the game therefore wouldn't crash at the write: saves, options and key bindings would just silently not persist. QuickBattle may also break without a writable `Options.cfg` (hypothesis H1 in the scoping note).

## 2. Goals

1. In a packaged build, every runtime write listed in scoping §3a and §3b goes to a per-user folder (§5 of this document).
2. In a source checkout, every one of those writes lands at exactly the path it uses today.
3. A `--data-dir <dir>` flag and a `DAUNTLESS_DATA_DIR` env var redirect all of it to one folder. Tests use this.
4. A packaged build writes its console output to a rotated log file.
5. Two guards keep it that way: a static test that catches new install-folder writes, and a dynamic test that runs missions from a read-only, zip-shaped copy.

## 3. Non-goals

- **Building the zip** is a separate job. That covers copying files, dropping the marker, precompiling Python and choosing the folder layout. This design only states what that job must provide (§9).
- **Migration.** No packaged build exists yet, so there is no player data to move. A checkout keeps its files where they are.
- **No UI for finding the folders, the mods folder included.** There's no "open data folder" button and no path on the Mods screen, because players won't care (Mark). Telling players where mods go is the packaging job's readme, if anything.
- **No bundled mods.** The v1 zip ships no mods (Mark), so a packaged build has exactly one mods root, the per-user one, and `mods.mods_root()` stays single-rooted.
- **No new headless host mode.** The end-to-end test runs the real write code from a read-only copy, but it doesn't boot the full host (§7.3, Mark).
- **The CEF cache.** It already lives in the system temp dir (scoping P14) and stays there.
- **Fixing `tools/mission_harness.py`** (36/37 failing on `ShipDisplay_Create`). It's worth a separate ticket, but this design doesn't depend on it.
- **Developer authoring destinations.** The hardpoint editor, decals and bridge lighting (V1, V3, V4) keep writing into the repo. The SPV mod-hardpoint save (V2) keeps writing into the mod's folder, wherever the mods root now is.

## 4. Anti-goals

The work has failed, even if it technically works, if:

- **A checkout changes behaviour in any way.** That includes a file moving, a new folder appearing under `~/Library` or `%APPDATA%` during development, or a test starting to depend on the developer's home folder.
- **A `--developer` authoring tool stops writing where its author expects.**
- **A write failure in a per-user folder is still silent.** Every such failure must reach the console (and so the log file) at least once, named by path.
- **A path gets captured at import.** The CLAUDE.md "BC content paths" rules apply to these folders too; a module-level constant holding one is a bug.
- **C++ starts computing a per-user folder itself.** C++ gets folders from Python.

## 5. Decided

All of these were decided by Mark on 2026-10-16.

### 5.1 Folders

| Kind | Holds (scoping rows) | Windows | macOS | Linux |
|---|---|---|---|---|
| config | `settings.json`, `bridges.json`, `quickbattle_presets.json`, `Options.cfg`, `Keybindings.cfg` (P1–P5) | `%APPDATA%\Dauntless\` (roaming) | `~/Library/Application Support/Dauntless/` | `$XDG_CONFIG_HOME/dauntless/` |
| saves | `*.BCS`, `missions/*.json` (P6–P9) | `%APPDATA%\Dauntless\saves\` | `~/Library/Application Support/Dauntless/saves/` | `$XDG_DATA_HOME/dauntless/saves/` |
| mods | the mods root, when no `--mods-dir` / `DAUNTLESS_MODS_DIR` is given (P12, V2) | `%APPDATA%\Dauntless\mods\` | `~/Library/Application Support/Dauntless/mods/` | `$XDG_DATA_HOME/dauntless/mods/` |
| cache | hull volumes, icon traces (P10, P13) | `%LOCALAPPDATA%\Dauntless\Cache\` | `~/Library/Caches/Dauntless/` | `$XDG_CACHE_HOME/dauntless/` |
| logs | `dauntless.log`, `stub_hits.jsonl` (D1); dev diagnostics V5, V6 when packaged | `%LOCALAPPDATA%\Dauntless\Logs\` | `~/Library/Logs/Dauntless/` | `$XDG_STATE_HOME/dauntless/logs/` |

- The XDG defaults apply when a variable is unset or relative (XDG spec). They are `~/.config`, `~/.local/share`, `~/.cache` and `~/.local/state`.
- The cache keeps today's sub-layout: `<cache>/hull_volumes`, `<cache>/icons/weapons`, `<cache>/icons/damage`.
- **Hand-rolled, no `platformdirs`.** On Windows, use the known-folder API (`SHGetKnownFolderPath`, `FOLDERID_RoamingAppData` / `FOLDERID_LocalAppData`) via `ctypes`, with `%APPDATA%` / `%LOCALAPPDATA%` as fallback.

### 5.2 Which mode, and the override

Precedence, highest **set** source wins:

| # | Source | Result |
|---|---|---|
| 1 | `--data-dir <dir>` | one root, **checkout layout** under it (5.3) |
| 2 | `DAUNTLESS_DATA_DIR` | same |
| 3 | packaged marker present | per-OS folders (5.1) |
| 4 | otherwise (source checkout) | checkout layout rooted at `PROJECT_ROOT` |

- **The packaged marker** is a file the packaging job drops at the install root, i.e. `PROJECT_ROOT`. The filename is the builder's call; record it once as a constant in `engine/paths.py`. Detection is "the file exists". Python does the detection, and C++ never checks for the marker.
- **No `settings.json` tier, and the flag does not persist.** `settings.json` lives *inside* the data dir, so either would be circular. This differs on purpose from `--game-dir`, and matches `mods.mods_root()`.
- An explicitly set override that is invalid (can't be created or written) still wins, as with `--game-dir`. The resulting write failures surface per 4 (not silent).
- **The mods root** keeps its own precedence on top: `--mods-dir`, then `DAUNTLESS_MODS_DIR`, then the data-dir result (`<data>/mods` under an override or packaged per-OS, `PROJECT_ROOT/mods` in a checkout).

### 5.3 The checkout layout

This is the layout under the override, and the layout a checkout already has. It is exactly today's:

```
<root>/settings.json  bridges.json  quickbattle_presets.json
<root>/Options.cfg    Keybindings.cfg
<root>/saves/...      <root>/mods/...
<root>/cache/hull_volumes/...   <root>/cache/icons/{weapons,damage}/...
<root>/stub_hits.jsonl          <root>/ai_inspector_export.json   <root>/nonfinite_dumps/
```

Logs: the log file exists **only in packaged builds** (5.5). A checkout never writes one, with or without the override. A packaged build run with the override writes it to `<root>/logs/dauntless.log` (my call, see §8).

### 5.4 Per-write decisions

| Row | Decision |
|---|---|
| P1–P3 | `settings_store.default_settings_path()` → `config_dir()/settings.json`. `bridges.json` and presets already derive from it. |
| P4, P5 | `Options.cfg` and `Keybindings.cfg` move to `config_dir()`. The SDK's bare filenames resolve there, not against cwd. |
| P6–P9 | Saves go to `saves_dir()`. The SDK's `"saves\\X"` and `"saves//X"` forms both map into it. **Loading must not create the folder** (today it does, P9). |
| P10 | The icon trace caches move under `cache_dir()`. The module-level `_SVG_CACHE_DIR` constants become resolve-at-use. |
| P11 | The `ship_icons` disk PNG is written **only under `--developer`**, still at its repo path. |
| P12, V2 | Follow the mods root (5.2). |
| P13 | `paths.hull_volume_cache_root()` → `cache_dir()/hull_volumes`, still pushed to C++ at boot (`host_loop.py:10098`). The C++ temp fallback stays. |
| P15 | Packaged builds don't write bytecode: `sys.dont_write_bytecode = True` as early as possible when the marker is present. The zip ships precompiled `.pyc` files (§9). |
| D1 | `stub_hits.jsonl` default → `log_dir()`, resolved at use (it's captured at import today). `DAUNTLESS_STUB_TELEMETRY_FILE` still wins. |
| V5, V6 | Unchanged in a checkout. When packaged they go to `log_dir()`, since a packaged `--developer` run must not write into the install either. |
| V1, V3, V4 | Unchanged: they write into the repo. In a packaged build those writes would hit the install, so they must refuse with a clear message rather than write. |

### 5.5 Log file (packaged builds only)

- **Contents.** Everything the process writes to stdout and stderr goes to `log_dir()/dauntless.log` **and** still to the console. That includes C++ `fprintf(stderr)` and CEF, so the capture must work at the file-descriptor level; replacing `sys.stderr` would miss most of it.
- **Rotation.** On each launch, the previous `dauntless.log` becomes `dauntless.prev.log`, so two runs are kept.
- **Timing.** Start as early as the Python side can (before the game loop), so a boot failure is captured.
- **Failure.** If the log can't be opened, carry on without it and say so on the console.
- A checkout never writes a log file.

## 6. Constraints

- **Resolve at use.** Every new folder function is called fresh each time, with no module-level capture. That follows the existing `engine/paths.py` rules and `tests/unit/test_path_indirection.py`.
- **`engine/paths.py` is the only authority.** No other module spells `APPDATA`, `XDG_*` or `Library/…`.
- **C++ asks Python.** The hull-volume cache root and the nonfinite dump dir are already pushed from Python. Any new C++ consumer gets the same treatment.
- **Create folders lazily, at the moment of writing.** Never at boot, and never on a read (5.4 P6–P9). A launch that writes nothing creates no per-user folders.
- **The test suite stays hermetic without losing coverage.** `tests/conftest.py` resolves the BC game/SDK roots once at session start from the developer's real `settings.json`, and the suite needs that. Pointing the data dir at a temp folder must not cut off that lookup. Nor may it cut off the real mods root (`PROJECT_ROOT/mods`), which today gives tests their mod coverage.
  - In practice conftest resolves and pins both roots and the mods root first, then sets `DAUNTLESS_DATA_DIR` for the rest of the session (or per test).
  - Tests that construct their own `SettingsStore` or call `paths.resolve()` keep working.
- **Python 3.11 stdlib only** for the folder lookup. `ctypes` is fine.
- **Gate.** `scripts/check_tests.sh` stays green with no new `tests/known_failures.txt` entries.

## 7. Verification (must exist when done)

1. **Static guard**, beside `test_path_indirection.py`, parsing rather than grepping:
   - Fail when a function in `engine/` or a root shim both performs a write and builds its path from `PROJECT_ROOT`, `__file__`, `Path.cwd()` / `os.getcwd()`, or `os.path.abspath(<relative literal>)`.
   - A named per-module allowlist covers the developer authoring writers (V1, V3, V4), each entry with its reason.
   - Also flag module-level path constants built from `PROJECT_ROOT` in modules that write.
2. **Dynamic guard.** A test-session `sys.addaudithook` that records write events.
   - During the headless campaign sweep (`tests/integration/test_warp_button_handler_sweep.py`) and the QuickBattle boot, assert nothing lands under `PROJECT_ROOT` or `paths.game_root()`.
   - Exception: `__pycache__` in a checkout.
   - Hooks can't be removed, so install once per session and toggle.
3. **Read-only packaged end-to-end, targeted** (Mark ruled this depth; no new host mode). Two halves:
   - **Subprocess from a read-only copy.**
     - Assemble a zip-shaped install from the checkout with the marker (`engine/`, the root shims, `native/assets/`), then make it read-only.
     - Point HOME / XDG / APPDATA-equivalents at a temp profile.
     - Run Python with only the copy on `sys.path` and cwd set to the copy, mimicking the host's chdir. The copy's own `engine` must be the one imported, never the checkout's.
     - Through the real engine code, exercise every 5.4 write: settings, bridges and presets save; `Options.cfg` and `Keybindings.cfg` save; `SaveToFile` and `SaveMissionState`; a load (which must not create `saves/`); the icon traces; the stub-telemetry sidecar; the hull-volume cache root as handed to C++; the log file; and `dont_write_bytecode`.
     - Assert each file landed in the profile's per-OS folder, no write failure was swallowed, and the install tree is byte-identical before and after (hashes).
   - **In-suite, under the override.**
     - The SDK-driven writes are covered by the dynamic guard (item 2): `MissionLib.SaveGame` autosaves, `QuickBattle.py`'s `Options.cfg` and the QB boot's `Options.cfg`.
     - **H1** gets its own test: boot QuickBattle headless with the config dir made unwritable and no `Options.cfg`. Record what happens, then make the outcome deliberate: either it works, or it fails with a clear message, never a crash deep in `StartSimulation`.
4. **Folder lookup unit tests** for each OS branch, with faked env and platform: XDG unset, relative and set; Windows known-folder success and env fallback; macOS.
5. **Checkout regression.** An existing-layout test confirming every 5.3 path is unchanged with no override and no marker.

## 8. Left to the builder

- **Function names and signatures in `engine/paths.py`.** Suggested names are `is_packaged()`, `data_dir_override()`, `config_dir()`, `saves_dir()`, `mods_default_dir()`, `cache_dir()` and `log_dir()`.
- **The marker filename and contents.** Suggestion: a small JSON file carrying the build id.
- **How the log tee is built**, e.g. a pipe plus a reader thread, or OS-specific handles, as long as 5.5 holds on all three OSes.
- **Where `dont_write_bytecode` and the log tee are switched on.** `engine/__init__.py` is the earliest Python that runs under the host (`host_main.cc` imports `engine.bootstrap` / `engine.host_loop`).
- **How developer authoring writers refuse when packaged** (5.4 V1/V3/V4). One message per attempt is enough.
- **The order of the work**, and whether conftest sets the override per session or per test.

**My calls, which Mark can overrule:**
- The log file is packaged-only. A packaged build under the override writes it to `<root>/logs/`.
- H1: if QuickBattle can't work without a writable `Options.cfg`, it fails with a clear message instead of crashing. The builder picks which outcome after observing it.
- conftest pins the real mods root, as well as the content roots, before redirecting the data dir.
- The packaged-`--developer` handling in 5.4 V5/V6 and V1/V3/V4.
- Creating folders lazily (§6).

## 9. What the packaging job must provide

The packaging job is separate, but it must:

- Drop the marker file at the install root.
- Keep the layout the host relies on to find its root. Today that's "two parents up from the binary" (`host_main.cc:34-40`), or the job changes that rule.
- Ship `.pyc` files compiled with `--invalidation-mode unchecked-hash` for `engine/` and the root shims.
- Ship nothing user-writable that a player needs to edit. In particular, no `Options.cfg`: the engine creates it in the config dir.
- Read diagnostics from stderr or the log, never stdout. In a packaged build the console mirror merges stdout onto stderr, so anything that parses the `--smoke-check` or `--banner` output (packaging checks, CI) must read stderr or `dauntless.log`.
- Ship precompiled bytecode for any bundled Python standard library too. It is imported before `engine` sets `sys.dont_write_bytecode`, so without it the first launch tries to write `.pyc` files into the install.
