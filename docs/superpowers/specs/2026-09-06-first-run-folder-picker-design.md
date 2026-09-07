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

### A CEF first-run screen, with the native panel behind its Browse buttons

**Revised 2026-09-07, after live testing.** The first version of this spec
chose bare native folder dialogs and no screen, to avoid reordering boot.
That shipped, and it was wrong. Two OS panels appear against nothing — no
game window, no context, no explanation — and there is nowhere to say *why*
a folder was rejected. Mark's verdict on seeing it: it reads as broken.

The engineering argument for the original choice was sound; it optimised for
implementation risk over what a first launch feels like, which is the wrong
trade for the one screen a new player is guaranteed to meet.

So: the window comes up as normal, and a full-screen first-run screen is
drawn in CEF over it — a background image with a centred panel carrying one
row per root, a Browse button each, and validation feedback under each row.

**Browse still opens the native `NSOpenPanel`.** A text field the player
types an absolute path into would be worse than the dialogs this replaces.
The panel supplies the *frame*: what is being asked for, what was wrong with
the last answer, and whether Continue is allowed yet.

CEF's parentless-windowless caveat does not apply, because we never ask CEF
to show the dialog — we call our own binding and CEF only renders the page:

> The `parent` value will be used to identify monitor info and **to act as
> the parent view for dialogs**, context menus, etc. If `parent` is not
> provided then the main screen monitor will be used and **some
> functionality that requires a parent view may not function correctly.**
> — `build/_deps/cef-src/include/internal/cef_mac.h:95-110`

We create the browser with `SetAsWindowless(0)` — no parent —
(`native/src/ui_cef/cef_lifecycle.cc:246`), which is why the dialog stays
ours rather than CEF's.

### The boot reorder is the real cost, and it is now paid deliberately

`_setup_sdk()` and `import App` currently run *before* `r.init()`. They move
after CEF init, because the screen must exist before the roots are known.
Verified feasible: CEF's page is `native/assets/ui-cef/index.html` — project
content, not BC content — and window/pipeline init reads no game assets, so
both come up fine with the roots unresolved.

### Triggered by unresolved roots, not by "first launch"

There is no virgin-launch flag. The screen appears whenever resolution
fails, which covers a genuine first run and an install that later moved out
from under a stale `settings.json`. The general form is simpler than the
special case, so it is the one built.

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
| Flow | `engine/first_run.py` | all decision logic; validation reused by the panel |
| Resolution | `engine/paths.py` | `picked` source, `persist()` accepts it |
| Screen (Python) | `engine/ui/first_run_panel.py` | **new** — `Panel` subclass, IPC with the page |
| Screen (page) | `native/assets/ui-cef/panels/first_run/` | **new** — markup, CSS, JS |
| Background | `native/assets/ui-cef/images/first-run-bg.png` | supplied 2026-09-07 |
| Pump loop | `engine/host_loop.py` | **new** — drives CEF before the game loop exists |
| Call site | `engine/host_loop.py` | after `cef_initialize`, one call |

The background image ships in the repo and **cannot** come from `game/` —
that is precisely what is missing when the screen appears. Supplied
2026-09-07: a 1920×1080 render of a Galaxy-class ship against a starfield,
832 KB.

**Its composition dictates the layout.** The ship sits dead centre with
bright window detail across the saucer; a centred panel would land straight
on top of it and fight the text. The left third is clean, near-black
starfield. So the panel sits **left, vertically centred**, with the ship
visible to its right — better composition and better legibility than
centring over a scrim.

The page still keeps a CSS starfield fallback behind the image, so a missing
or failed asset degrades to something deliberate rather than a white void.

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

Boot order changes. Resolution moves *after* CEF init, and `_setup_sdk()`
and `import App` move after resolution:

```
r.init(1280, 720)
r.validate_bindings / host_io.validate_bindings / host_io.verify_keys
cef_initialize(...)
    ↓
resolution = paths.resolve()
if not resolution.ok:
    resolution = first_run_panel.run(resolution)   ← the screen, pumped
    ↓
paths.configure(resolution)
paths.persist(resolution)          ← above the early return; a validated
if not resolution.ok:                pick survives a later abandonment
    print(describe_failure(...), file=stderr)
    return 1
r.set_game_root(str(paths.game_root()))
_setup_sdk()
import App …                       ← everything downstream unchanged
```

### The screen

One row per unresolved root, game first. Each row shows the current path (or
"not set"), a **Browse** button, and a status line underneath: a tick with
the markers found, or the `missing` list plus `hint` from the same
`Validation` the CLI path uses. A root that already resolved is shown
satisfied and is not asked for again.

**Continue** enables only when both roots validate. `_setup_sdk()` runs
immediately after, so letting the player through with only `game` would just
move the failure somewhere with no UI to report it. **Quit** exits with the
full `describe_failure()` diagnostic on stderr and a non-zero code — the
same ending the old bare-dialog path had.

Browse calls `_dauntless_host.pick_folder`, and the answer is validated with
`validate_game_root` / `validate_sdk_root` — the same markers the CLI path
uses, so a folder the screen accepts cannot fail later in boot. An invalid
choice updates that row's status line and leaves Continue disabled; there is
no retry limit because there is no modal to escape from.

### The pump loop

The game loop does not exist yet, so the screen runs its own: poll events →
pump CEF → composite → swap, until Continue or Quit. This is the one
genuinely new mechanism, and the reason the screen cannot simply reuse
`PanelRegistry` as the in-game panels do.

**JS must not be pushed before the page's scripts have run** — pre-load
pushes are silently dropped in this project, which has caused real bugs. The
screen's initial state is therefore sent from the load-end handler, not at
`cef_initialize` time.

A validated pick persists even if the player quits before finishing. If they
locate `game/` and abandon `sdk/`, the next launch asks only for the sdk.
The stored root passed the same validation as any other, so this does not
weaken Spec 1's "a typo never becomes the stored answer" rule.

## Failure handling

Three unrelated causes collapse into one `None` branch:

| Cause | Mechanism |
|---|---|
| Not macOS | `folder_picker.cc` returns `nullopt` |
| Stale `.so` lacking the binding | `getattr(_h, "pick_folder", None)` |
| Player cancelled | panel returns no selection |

All three now mean the same thing to the screen: **Browse did not produce a
path**, so that row keeps its previous state and Continue stays disabled.
The player is not stranded — the screen is still there, saying what it
needs — and Quit remains the way out to `describe_failure()` + exit 1.

This is a real improvement the revision buys. Under the bare-dialog design a
platform with no picker meant the player saw *nothing at all* and the game
exited; now they see a screen that names both folders, with Browse simply
inert. On Windows and Linux, until `IFileOpenDialog` lands, that is the
difference between an unexplained exit and a legible one.

The stale-`.so` case is still `getattr`-guarded rather than added to
`_REQUIRED_BINDINGS`, but for a changed reason: after the reorder the screen
runs *after* `r.validate_bindings()`, so a stale `.so` would now be caught
by it. The guard stays anyway — it costs one line and keeps `first_run.py`
callable from tests and tools that never validated bindings at all.

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
- both roots missing → both rows shown unsatisfied; only sdk missing → the
  game row is shown satisfied and not asked for again
- a Browse answer that fails validation updates that row's status with the
  `missing` markers and `hint`, and leaves Continue disabled
- an empty or whitespace-only picked path is treated as no answer, and never
  becomes `Path(".")`
- Continue is disabled until BOTH roots validate, and enabled the moment
  they do
- Quit with a validated game root and no sdk → the game root persists; next
  launch asks only for the sdk
- **fallback guard:** the screen returns without a complete resolution ⇒
  boot prints the full `describe_failure()` text and returns non-zero

The fallback guard is the most important test in the set. Without it a later
refactor could let boot continue on unresolved paths, or drop the error
message, and no other test would fail. It must be pinned at the boot call
site, not only inside the helper — a version of this guard that tested only
the helper missed exactly that gap and was found by mutation.

The screen's panel logic is Python and testable with a fake picker and a
fake page transport. The **pump loop and the page itself are not** — see
below.

`tests/unit/test_path_indirection.py` needs no change: it already scans all
of `engine/`, so `first_run.py` inherits the no-import-time-capture rule.

## What cannot be tested

Three surfaces here have no automated coverage, and each is deliberate:

**`folder_picker.mm`** — a modal `NSOpenPanel` cannot be exercised by ctest
and the game is not launched during verification. That is why it holds no
logic; if it grows past roughly 30 lines the design has leaked and the
excess belongs in Python.

**The pump loop** — it drives a live CEF browser against a real GL surface.
It is kept to the smallest possible body (poll, pump, composite, swap, check
one flag) for exactly that reason; every decision it might have made belongs
in the panel class instead.

**The page** — CEF is software-rasterized here, so there is no headless
render to assert against. The page must hold no logic beyond
display-and-report: it renders the state it is given and reports button
presses. Anything conditional belongs in `first_run_panel.py`, which is
testable with a fake transport.

The recurring rule: **the untestable layer is a renderer, never a decider.**
This spec's first version proved the cost of getting that wrong in the other
direction — the logic was correctly placed, but the layer it served was the
wrong shape entirely, and only a live run showed it.

## Gate reporting

The Spec 1 branch ran green while four tests errored and roughly 73 skipped
dark. The gate report for this work therefore includes raw pass / skip /
error counts before and after, not only "no new failures" — if the new tests
do not execute, that must be visible rather than inferred.

## Live verification

Mark runs these; they cannot be checked headlessly.

1. Remove `[paths]` from `settings.json` with no BC content in the project →
   **the game window opens as normal** and the first-run screen is drawn
   over it, with both rows unsatisfied.
2. Browse on the game row → the native panel appears **in front of the game
   window and takes focus**. This is the reorder's main risk: the screen now
   runs after `r.init()`, so GLFW has already created the `NSApp` that
   `pick_folder` previously created itself.
3. Pick a valid game folder → the row turns satisfied and names what it
   found; Continue stays disabled while the sdk row is unsatisfied.
4. Pick an *invalid* folder for sdk → the row shows the missing markers and
   the hint; Continue stays disabled.
5. Pick a valid sdk folder → Continue enables; pressing it boots the game
   normally, with no leftover screen and no stuck input focus.
6. Relaunch → no screen at all.
7. Fresh state again, pick only the game folder, then Quit → terminal shows
   the full `describe_failure()` text and a non-zero exit; the NEXT launch
   asks only for the sdk.

Step 2 and step 5 are the ones most likely to fail. Step 2 is the
window/dialog focus interaction; step 5 is whether the pump loop hands
control cleanly to the real game loop.

## Future work

- Windows `IFileOpenDialog` behind the same seam. Until then the screen
  still appears on Windows and Linux with Browse inert — legible, where the
  previous design gave those platforms a silent exit.
- The background is a placeholder taken from the `dauntless_web` assets. If
  a purpose-shot screenshot replaces it later, keep the left third clear —
  the panel's position depends on it.
