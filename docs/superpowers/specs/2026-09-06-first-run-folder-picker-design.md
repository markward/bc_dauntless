# First-Run Folder Picker — Design

**Date:** 2026-09-06
**Status:** Approved, not yet implemented
**Follows:** `docs/superpowers/specs/2026-09-05-bc-path-resolution-design.md` (Spec 1)

## Problem

Spec 1 made BC content paths configurable and gave a good diagnostic when
they cannot be found. It stops there: `host_loop.run()` prints
`describe_failure()` and returns 1.

That is the right answer for a script and the wrong one for a player. The
game is a GUI binary that may be launched from Finder with no terminal
attached, so the message it prints to stderr is invisible, and the only
remedies it offers — a command-line flag, or hand-editing `settings.json` —
require a terminal to act on. A first launch against a checkout with no
`game/` therefore fails silently.

## Goal

When a BC root cannot be resolved at launch, ask the player for it with a
native folder panel, validate the choice with the same markers the CLI path
uses, persist what validates, and continue booting.

## Non-goals

- **No in-game path editing.** Spec 1 settled this: once set, the roots are
  changed by editing `settings.json` or passing a CLI flag. This spec adds a
  first-run path only.
- **No CEF UI.** Considered and rejected below.
- **No Windows implementation yet.** The seam is designed for one; the
  fallback is today's behaviour.
- **No change to `paths.py`'s purity.** It never prompts, never blocks.

## Decisions

### Native panel, not a CEF first-run screen

A richer HTML first-run screen (explanatory copy, two Browse buttons, live
validation) would require reordering boot: `_setup_sdk()` runs immediately
after path resolution and needs `sdk`, while the window and CEF do not come
up until ~60 lines later. A native panel needs no reordering at all — it
slots into the existing failure branch.

Rejecting CEF also sidesteps an unknown. CEF's own header is explicit that a
parentless windowless browser is unreliable for exactly this:

> The `parent` value will be used to identify monitor info and **to act as
> the parent view for dialogs**, context menus, etc. If `parent` is not
> provided then the main screen monitor will be used and **some
> functionality that requires a parent view may not function correctly.**
> — `build/_deps/cef-src/include/internal/cef_mac.h:95-110`

We create the browser with `SetAsWindowless(0)` — no parent —
(`native/src/ui_cef/cef_lifecycle.cc:246`). CEF does not promise the default
dialog works in that configuration. Owning the panel removes the question
rather than testing it.

### macOS now; other platforms degrade to today's error

The panel is per-platform code. macOS ships in this spec. Windows and Linux
return "no picker", which routes to the existing `describe_failure()` + exit
1 — no regression, and the Windows `IFileOpenDialog` sibling drops into the
same seam later with no caller change.

### Prompting is a property of the call site, not of the library

`paths.current()` is reached lazily by `tools/` scripts, pytest and CI, none
of which can dismiss a modal dialog. A picker reachable from the library
would hang them. The picker is therefore called from exactly one place —
the boot failure branch in `host_loop.run()` — and lives in its own module
so `paths.py` imports nothing that can block. This is enforced by
construction, not by discipline.

## Architecture

### Placement

| Layer | File | Notes |
|---|---|---|
| Native panel | `native/src/platform/folder_picker.mm` | macOS; `NSOpenPanel` |
| Fallback | `native/src/platform/folder_picker.cc` | returns `nullopt` |
| Header | `native/src/platform/folder_picker.h` | |
| Binding | `native/src/host/host_bindings.cc` | `pick_folder` |
| Flow | `engine/first_run.py` | **new** — all decision logic |
| Resolution | `engine/paths.py` | `picked` source, `persist()` accepts it |
| Call site | `engine/host_loop.py` | the failure branch, one call |

`platform` is the correct home and `ui_cef` is not: `ui_cef/CMakeLists.txt`
returns early when `DAUNTLESS_ENABLE_CEF` is off, so the existing
`cef_macos_app.mm` does not exist in `--no-cef` builds — precisely the
builds most likely to be run from a bare checkout with no game data.
`platform` is always built and its own header comment already describes this
pattern: a `.cc`/`.h` split so per-OS implementation details stay out of
headers.

`folder_picker.mm` must call `[NSApplication sharedApplication]` itself.
`install_macos_app()` is inside `#ifdef DAUNTLESS_ENABLE_CEF`
(`native/src/host/host_main.cc:130-137`), and the picker fires before
`r.init()`, so GLFW has not created an `NSApp` either. `sharedApplication`
is idempotent, so this is safe whether CEF, GLFW, both or neither ran first.

### Seam

```
platform::pick_folder(title, message) -> std::optional<std::string>
_dauntless_host.pick_folder(title, message) -> str | None
```

The native file does one thing: show a panel, return a path or nothing. It
holds no ordering, retry, validation or persistence logic. This is
deliberate — see "What cannot be tested".

### Precedence

A picked root outranks every other source:

```
picked > cli > env > settings.json > legacy in-project
```

`resolve()` grows an optional highest-precedence mapping and stays pure:

```python
resolve(argv=None, env=None, store=None, picked=None) -> Resolution
```

The obvious cheaper approach — write the pick into `settings.json`, re-run
`resolve()` — is wrong. Spec 1's rule is that the highest source which is
**set** wins even when invalid, so an invalid `--game-dir` on the command
line would keep beating the folder the player just chose. A pick is the most
recent explicit human act and must outrank the flag it is correcting.

`Resolution.source(kind)` returns `"picker"`; `persist()` accepts
`("cli", "picker")` and still refuses `env`, `settings` and `legacy`.

## Flow

```python
# host_loop.run(), replacing the bare `return 1`
_resolution = _paths.resolve()
if not _resolution.ok:
    _resolution = first_run.prompt_for_missing(_resolution)
_paths.configure(_resolution)
if not _resolution.ok:
    print(_paths.describe_failure(_resolution), file=_sys.stderr)
    return 1
_paths.persist(_resolution)
```

`first_run.prompt_for_missing` takes the picker function as an injectable
argument so tests drive the whole flow with a fake.

Per folder, in order (game, then sdk), skipping any that already resolved:

1. Open the panel. The title names the folder. On a retry the message
   carries the previous attempt's `missing` markers and `hint`, so the
   second dialog is more informative than the first.
2. Validate with the existing `validate_game_root` / `validate_sdk_root` —
   the same markers the CLI path uses, so a folder accepted here cannot fail
   later in boot.
3. Invalid → re-prompt. Unbounded; cancel is always available.
4. Cancel → stop immediately and return what has been gathered.

A validated pick persists even when a later one is cancelled. If the player
locates `game/` and then gives up on `sdk/`, the next launch asks only for
the sdk. The stored root passed the same validation as any other, so this
does not weaken Spec 1's "a typo never becomes the stored answer" rule.

## Failure handling

Three unrelated causes collapse into one `None` branch:

| Cause | Mechanism |
|---|---|
| Not macOS | `folder_picker.cc` returns `nullopt` |
| Stale `.so` lacking the binding | `getattr(_h, "pick_folder", None)` |
| Player cancelled | panel returns no selection |

All three route to `describe_failure()` + exit 1 — today's behaviour
exactly. Windows therefore needs no special case.

The stale-`.so` case must be `hasattr`-guarded rather than added to
`_REQUIRED_BINDINGS`: the picker runs at `engine/host_loop.py:6738`, while
`r.validate_bindings()` does not run until line 6759. The picker is upstream
of the check that would otherwise have caught it.

## The empty-string boundary

A picked path is rejected as empty **at the picker boundary**, before a
`Path` is ever constructed from it — not inside `_validate`.

`Path("")` normalises to `"."` at construction, so by the time a value
reaches `_validate` it is indistinguishable from a deliberate `Path(".")`.
The guard therefore cannot live there. Spec 1 already handles the sibling
case for the CLI, env and settings sources, where the raw value is still a
string when it arrives (`os.path.abspath("")` returns the CWD, so an empty
`--game-dir=` launched from inside a BC install would otherwise validate
`ok=True`).

`pick_folder` returns `str | None`. `first_run` treats an empty or
whitespace-only string exactly as it treats `None` — as a cancellation —
so a panel that returns one can never become a root, and never becomes a
silent `Path(".")` pointing at the working directory.

## Testing

Python, all with an injected fake picker and no dialog:

- `resolve(picked=…)` outranks cli, env and settings — **including an
  invalid `--game-dir`**, the case that invalidates the cheaper design
- `persist()` accepts `cli` and `picker`; still refuses `env`, `settings`,
  `legacy`
- both roots missing → two prompts; only sdk missing → game is not re-asked
- invalid then valid → two picker calls, and the second call's message
  contains the hint
- cancel on the first prompt → no second prompt
- valid game, cancelled sdk → the game root persists; next launch prompts
  only for sdk
- an empty or whitespace-only picked path is treated as a cancellation,
  and never becomes `Path(".")`
- **fallback guard:** picker returns `None` ⇒ boot prints the full
  `describe_failure()` text and returns 1

The fallback guard is the most important test in the set. Without it a later
refactor could let a picker-less platform boot on unresolved paths, or drop
the error message, and no other test would fail.

`tests/unit/test_path_indirection.py` needs no change: it already scans all
of `engine/`, so `first_run.py` inherits the no-import-time-capture rule.

## What cannot be tested

A modal `NSOpenPanel` cannot be exercised by ctest, and the game is not
launched during verification. `folder_picker.mm` is therefore unverified by
automated tests, which is the reason it holds no logic. If it grows past
roughly 30 lines, the design has leaked and the excess belongs in
`first_run.py`.

## Gate reporting

The Spec 1 branch ran green while four tests errored and roughly 73 skipped
dark. The gate report for this work therefore includes raw pass / skip /
error counts before and after, not only "no new failures" — if the new tests
do not execute, that must be visible rather than inferred.

## Live verification

Mark runs these; they cannot be checked headlessly.

1. Remove `[paths]` from `settings.json` with `game/` absent from the
   project → two dialogs appear in order.
2. Pick both valid folders → the game boots.
3. Relaunch → no dialogs.
4. Pick an invalid folder → the panel reappears with the missing markers
   named in its message.
5. Cancel → the terminal shows the full `describe_failure()` text and a
   non-zero exit.

## Future work

- Windows `IFileOpenDialog` behind the same seam.
- A CEF first-run screen, if the panel's single line of explanatory text
  proves insufficient. It would require the boot reorder described above.
