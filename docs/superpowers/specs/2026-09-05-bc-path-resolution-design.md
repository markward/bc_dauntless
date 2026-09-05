# BC Path Resolution — Design

**Status:** approved, not yet implemented
**Date:** 2026-09-05
**Supersedes:** the "Future: the bootstrap tier" section of
`docs/superpowers/specs/2026-09-05-settings-persistence-design.md`
**Followed by:** Spec 2 — the first-run picker (not yet written)

## Problem

`game/` and `sdk/` are hardcoded to the project root in 62 places, spread
across three independent mechanisms and 25 further offline scripts. A BC
install that lives anywhere else cannot be found, and moving one out of the
project tree breaks the binary *and* the test suite — `pytest --collect-only`
reports 18 collection errors with the directories absent.

The three hardcodings are independent, and all three must move together:

| Where | How it resolves today | Count |
|---|---|---|
| Python | `PROJECT_ROOT / "game"`, `PROJECT_ROOT / "sdk"` | 36 sites, 14 files (19 in `host_loop.py`) |
| C++ | `resolve_asset_path()` prepends the literal `"game/"`, relative to a cwd `main()` chdir's to | 26 literal constants, 11 files |
| SDK imports | a `SDK_SCRIPTS` meta-path finder, duplicated | `tools/mission_harness.py:29`, `tests/conftest.py:17` |

A further 23 `tools/` scripts build the same paths and are broken by the same
move.

Counts here are from an AST scan for non-docstring string constants equal to
`game`/`sdk` or beginning `game/`/`sdk/` — a textual grep both over-reports
(every `engine/` docstring citing `sdk/Build/scripts/...`) and under-reports
(a constant split across lines, as at `engine/dev_keybindings.py:20`).

## Goal

One authority that resolves where the player's BC content lives, fed by a
persisted setting, so the install can sit anywhere on disk. Everything —
engine, tools, tests, and the renderer — asks that authority.

## Non-goals

- The first-run picker UI and the CEF folder-dialog spike. That is Spec 2;
  this spec is what makes it possible.
- Editing paths from inside a running game. Explicitly out (Mark's call):
  nothing loaded from `game/` can be swapped live, so a change requires a
  relaunch regardless.
- Relocating `settings.json` itself. It keeps its existing
  `default_settings_path()` seam.
- `Keybindings.cfg`'s location.
- Any compatibility with BC's `Options.cfg`.

## Architecture

### The rule

> **Paths are resolved at use, never captured at import.**
> No module-level constant may hold a game or SDK path, and nothing outside
> `engine/paths.py` may spell `game` or `sdk` as a path segment.

The second half is what makes the migration checkable. The first half is
what makes Spec 2 possible, and it is the single most important line in this
document — see "The import-time trap" below.

### `engine/paths.py`

The single authority. Pure resolution, then a cache.

```python
GAME_MARKERS = ("data", "data/Models", "data/Textures", "data/Icons")
SDK_MARKERS  = ("Build/scripts/App.py", "Build/Data/TGL")

@dataclass(frozen=True)
class Validation:
    ok: bool
    root: Path
    missing: tuple[str, ...]     # markers not found, in declaration order
    hint: str | None             # a specific diagnosis, or None

@dataclass(frozen=True)
class Resolution:
    game: Path | None
    sdk: Path | None
    game_source: str             # "cli" | "env" | "settings" | "project" | ""
    sdk_source: str
    game_validation: Validation | None
    sdk_validation: Validation | None

    @property
    def ok(self) -> bool: ...

# Pure — no globals, no filesystem writes, no settings import at module scope.
def resolve(argv=None, env=None, store=None) -> Resolution: ...

# Caches a Resolution. Callable more than once; later calls are observed by
# every consumer (this is what Spec 2's picker needs).
def configure(resolution: Resolution) -> None: ...

def game_root() -> Path
def sdk_root() -> Path
def sdk_scripts() -> Path        # sdk_root() / "Build" / "scripts"
def sdk_data() -> Path           # sdk_root() / "Build" / "Data"
def game_asset(rel) -> Path      # game_root() / rel  — replaces the 39 sites

def validate_game_root(path) -> Validation
def validate_sdk_root(path) -> Validation

def describe_failure(resolution: Resolution) -> str   # the stderr block
```

`resolve()` imports `engine.settings_store` **lazily, inside the function
body**. This is load-bearing, not stylistic: `settings_store` imports
`engine.ui.configuration_panel` at module level (`settings_store.py:29`), so
a top-level import would drag the entire configuration panel into
`engine/audio/tg_sound.py` and `engine/appc/*`, which are among `paths`'
consumers.

`configure()` must run before the first `game_root()`. If it has not,
`game_root()` performs a default `resolve()` (no argv, ambient env, the
default store) rather than raising, so a `tools/` script or a test that
imports an engine module in isolation still works.

If resolution produced no root for the requested half, `game_root()` /
`sdk_root()` raise `PathsUnresolved` carrying `describe_failure()`'s text.
Callers do not handle it: it is a boot-time configuration error, and the
message is the whole point.

### Resolution order

Four sources. **The highest-precedence source that is *set* wins, even if it
is invalid.**

| # | Source | Persists? | Purpose |
|---|---|---|---|
| 1 | `--game-dir` / `--sdk-dir` | **yes** — written to `settings.json` | How a path is set, until the picker ships |
| 2 | `DAUNTLESS_GAME_DIR` / `DAUNTLESS_SDK_DIR` | no | One-off runs, CI, pointing tests at a fixture |
| 3 | `settings.json` → `[paths]` → `game` / `sdk` | — | The persisted answer |
| 4 | `<project>/game`, `<project>/sdk` | no | The legacy in-project layout |

Deliberately **not** "first valid wins". `--game-dir /typo` is an error
naming the typo; falling through to a stale `settings.json` would leave the
player running a different install than they asked for, silently.

Source 4 is the one exception: it is a fallback, so its absence means
"nothing configured", not an error.

A CLI flag persists and an env var never does. That split is what makes
`DAUNTLESS_SDK_DIR=/fixtures pytest` safe to run against a real config —
which the test suite relies on.

Two further rules the table does not carry:

- **The two roots resolve independently.** A source being set for `game` says
  nothing about `sdk`; each runs the table separately and reports its own
  source.
- **Only a valid path persists.** `--game-dir` writes to `settings.json` only
  after that path validates. A typo is reported and exits; it never becomes
  the stored answer, which would make the next launch fail for a reason the
  player has already forgotten about.

### Stored form

`expanduser()`, then `absolute()`, then `normpath` — **not** `Path.resolve()`.
Symlinks are deliberately not followed: an install behind a symlink to an
external volume keeps working across remounts, where a resolved target would
not. Stored as a JSON string under `["paths"]["game"]` / `["paths"]["sdk"]`,
the section `settings_store` already reserves and preserves.

## Validation

Two pure functions. Six `stat` calls, no I/O beyond that, testable against
`tmp_path` trees with no BC install present.

**Shallow on purpose.** BC installs differ by patch level and mods add files,
so a manifest would reject valid installs while catching nothing the engine
does not already report precisely. The job is to catch *wrong folder*, not
*corrupt install*.

`stbc.exe` and `game/scripts/` are **not** markers. Neither is loaded at
runtime — `scripts/` is only `tools/setup.py`'s instrumentation target — so
requiring them would reject a usable content-only copy.

### Diagnoses

"Not a valid game folder" is a useless message. Validation names the three
mistakes a person actually makes:

| Detected by | Message |
|---|---|
| The chosen folder contains a `game/` (or `sdk/`) child that *does* validate | `That folder contains 'game' — did you mean <path>/game?` |
| The game path validates as an SDK root, or vice versa | `That's the SDK folder; it belongs in the SDK field.` |
| The chosen folder's *parent* validates as a game root | `That's the data folder — pick its parent.` |

Each is a `hint` on the `Validation`; `missing` always lists the markers that
were absent, whether or not a hint fired.

### Case sensitivity

Markers are matched exactly — asset loads are case-exact, so a case-tolerant
verdict would pass folders the engine then fails on. When an exact match
fails, validation rescans the directory case-insensitively **purely to
improve the message**: on a case-sensitive volume, `found 'Data/', expected
'data/'` is the difference between a two-second fix and an hour. The rescan
never changes `ok`.

## The import-time trap

Eight `engine/` sites are **module-level constants**, evaluated at import —
plus `tools/mission_harness.py`, which `host_loop.py:3507` imports at runtime:

`engine/ui/weapon_icons.py:77`, `engine/ui/ship_icons.py:39`,
`engine/ui/damage_icons.py:35`, `engine/lip_sync_runtime.py:54`,
`engine/appc/viewscreen_static.py:22`, `engine/appc/bridge_set.py:21`,
`engine/dev_keybindings.py:20` (`_TEST_CHARACTER_NIF`, split across nine lines
and invisible to a line-oriented grep), and
`engine/missions/name_resolver.py:16` (`TGL_ROOTS`, a tuple holding *both*
roots).

The tempting fix is to resolve paths in `engine/__init__.py`, early enough
that the constants still work. **That would make Spec 2 impossible**: the
picker runs after CEF is up, so anything captured at import is already stale
by the time the player chooses a folder.

Hence the rule. Every one of those nine becomes a call at point of use. The
cost is a `Path` join per asset load — these are load paths, not per-frame
paths — and the benefit is that the roots can change after the process has
started, which is the entire premise of a picker.

## Migration

### Python — 36 sites, 14 files

`PROJECT_ROOT / "game" / rel` → `paths.game_asset(rel)`.
`PROJECT_ROOT / "sdk" / "Build" / "scripts"` → `paths.sdk_scripts()`.

`engine/audio/tg_sound.py` loses `OPEN_STBC_GAME_DIR` entirely
(`tg_sound.py:20`). It is a second env var doing this job under a different
name, with its own project-relative fallback, referenced by one test
(`tests/audio/test_loadbridge_loadsounds.py:47`). That test moves to the
`fake_bc_install` fixture. Leaving a rival spelling behind is the mess this
spec removes.

### C++ — 26 literals, 11 files

`native/src/renderer/include/renderer/asset_path.h` is header-only inline
today. It gains an `asset_path.cc` holding one variable:

```cpp
namespace renderer {
void set_game_root(std::string absolute_or_relative);
const std::string& game_root();                       // default: "game"
std::string resolve_asset_path(const std::string& path);
}
```

`resolve_asset_path(rel)` returns `game_root() + "/" + rel`. Absolute inputs
pass through unchanged (`is_absolute_asset_path` is unaltered), as do inputs
already beginning with the current root — the idempotence contract is kept.

The default root stays the literal `"game"`, so the ctest suite, the
`native/tools/` probes, and any path not yet migrated behave exactly as they
do now. The chdir at `host_main.cc:175` **stays**: it is still required for
`native/assets/`, and it is what keeps the legacy default working.

The 26 literals drop their `"game/"` prefix and route through
`resolve_asset_path()` at their load sites.
`_dauntless_host.set_game_root(str)` sets the root once from `host_loop.run()`
before `r.init`, and is callable again later — Spec 2 calls it after the
picker resolves.

**Belt and braces:** if `resolve_asset_path` is handed a path beginning
`"game/"` while the root is *not* `"game"`, it logs loudly once. That turns a
missed literal from a silently-absent texture into a named error.

### Both SDK finders

`tools/mission_harness.py:29` and `tests/conftest.py:17` both read
`paths.sdk_scripts()`. This is the same twinned pair as the duplicated SDK AST
transforms; changing one and not the other is the known failure mode here.

### The 23 other `tools/` scripts

`analyze_power_session`, `analyze_scale_log`, `analyze_session`,
`bake_backdrop_appearance`, `bake_impulse_glow`, `bake_set_course_catalog`,
`bake_star_colors`, `bake_warp_glow`, `bcs_inspect`, `decode_lip_phonemes`,
`gameloop_harness`, `pick_simplest_mission`, `probes/build_ghidra_export`,
`probes/collect`, `probes/collect_q13`, `probes/collect_q14`,
`probes/collect_q15`, `probes/collect_q16`, `probes/collect_q17`,
`probes/push`, `setup`, `tgl_harness`, `uninstall`.

Each is one or two lines. They are broken by the same move, so fixing them is
finishing the job, not widening it — and it lets the guard cover `tools/` with
no per-file allowlist. Module-level constants are acceptable *in these
scripts* (they run to completion, never under the picker), so only the
string-constant guard applies here, not the no-capture-at-import rule.

Five of the flagged strings are **messages and labels, not paths** —
`tools/setup.py:80,83,124` and `tools/probes/push.py:25` describe the legacy
layout in error text and are rewritten to name the new sources; and
`tools/probes/build_ghidra_export.py:189` records `"game/stbc.exe"` as a
portable label in an export manifest, where an absolute machine-specific path
would be worse. That one carries a `# paths-guard: label` comment, which the
guard honours.

## Failure handling

With no picker yet, an unresolved or invalid path prints one stderr block
naming every source consulted and what each said, then exits non-zero:

```
dauntless: cannot locate your Bridge Commander install.

  game folder : not found
     --game-dir        (not given)
     DAUNTLESS_GAME_DIR (not set)
     settings.json     (not set)
     <project>/game    (does not exist)

  sdk folder  : invalid — /Users/mark/BC
     missing: Build/scripts/App.py, Build/Data/TGL
     source : settings.json
     hint   : That folder contains 'sdk' — did you mean /Users/mark/BC/sdk?

Set them once and they persist:

  ./build/dauntless \
      --game-dir "/path/to/Star Trek Bridge Commander/game" \
      --sdk-dir  "/path/to/Star Trek Bridge Commander/sdk"
```

`describe_failure()` produces this string; Spec 2 replaces the *presentation*
with the picker and leaves the resolution layer beneath it unchanged.

`tests/conftest.py` **fails fast with a single actionable error, and does not
skip.** Skipping would turn today's 18 loud collection errors into ~800 silent
skips, and `scripts/check_tests.sh` diffs *failures* against
`tests/known_failures.txt` — a mass-skip would pass the gate green. That is
the "green tests cannot see asset paths" failure mode, and it must be
impossible rather than merely unlikely.

## Guards

A missed site fails silently — a texture that does not load, a mission that
does not list. One pytest file, `tests/unit/test_path_indirection.py`, holds
three guards:

1. **AST scan of `engine/`, `tools/` and `tests/conftest.py`** for
   non-docstring string constants equal to `game`/`sdk` or beginning
   `game/`/`sdk/`. Allowlist: `engine/paths.py`, plus any line carrying a
   `# paths-guard: label` comment. It must be AST-based, not a grep: a grep
   flags every `engine/` docstring that cites `sdk/Build/scripts/...` — dozens
   of them — and a guard that cries wolf gets deleted.
2. **Grep `native/src`** for `"game/` string literals, skipping `//` comment
   lines. Allowlist: `asset_path.cc`.
3. **AST check**: no module in `engine/` binds a module-level name to a
   `paths.*` call. Allowlist: `engine/paths.py`, whose own `GAME_MARKERS` and
   `SDK_MARKERS` are module-level by design. This is the guard for the
   import-time trap, and it is structural rather than textual so it cannot be
   worked around by reformatting.

## Testing

Five files, all runnable with **no BC install present**. A
`fake_bc_install(tmp_path)` fixture builds marker trees, so no unit test
touches the real install.

| File | Covers |
|---|---|
| `tests/unit/test_paths_resolve.py` | The precedence matrix: four sources × set/unset × valid/invalid, including "highest set source wins even when it is wrong", and that env never persists while `--game-dir` does |
| `tests/unit/test_paths_validate.py` | Markers, all three diagnoses, the case-insensitive rescan changing the message but never the verdict |
| `tests/unit/test_path_indirection.py` | The three guards |
| `tests/unit/test_paths_late_reconfigure.py` | `configure()` twice; every consumer observes the new root. Pins the no-capture rule behaviourally, not just structurally — this is the Spec-2 enabler |
| `native/tests/renderer/asset_path_test.cc` (**exists — extend**) | `resolve_asset_path` default, set-root, idempotence, absolute pass-through, and the loud-warning path |

Existing suites that must stay green: the full gate via
`scripts/check_tests.sh`, which currently cannot even collect.

## Documentation

- `engine/paths.py`'s module docstring is the reference.
- CLAUDE.md gains a hard-rule section beside the rotation convention —
  *never spell `game` or `sdk` as a path segment; ask `engine.paths`* — plus a
  reference-table row.
- The settings spec's "Future: the bootstrap tier" section is updated to point
  here; `settings_store.py`'s docstring paragraph about `paths` being reserved
  and read by nothing becomes a pointer to this spec.

## Live verification

Only Mark can confirm these, and none is visible to the gate:

1. The binary boots against the moved install and renders a ship **with
   textures** — the C++ migration's failure mode is untextured passes, not an
   error.
2. `--game-dir` / `--sdk-dir` persist across a relaunch.
3. A deliberately wrong path produces a useful message, not a stack trace.
4. Audio still plays — `tg_sound` is the one hot path changing here.
5. A mission loads from the dev mission picker, exercising `sdk_scripts()`
   through the live finder rather than the test one.
