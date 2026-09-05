# Settings persistence — design

**Date:** 2026-09-05
**Status:** approved, not yet implemented

## Problem

Configuration panel settings do not survive a launch. A player who turns off
camera shake or subtitles gets them back next session.
`engine/ui/configuration_panel.py` says so in its own docstring: *"Settings are
not persisted across launches."*

A second, latent problem rides along. The panel's `initial_settings` at
`engine/host_loop.py:7245` is partly fiction. Several renderer effects expose no
getter, so the construction site hardcodes `smaa_on=True`, `dust_on=True`, and
assumes rim, shadows and HDR are on. The panel reports state it has not read.

## Goal

A Dauntless-specific settings store: JSON on disk, loaded at boot, applied
through the same appliers the panel uses, written on every change.

## Non-goals

- **BC `Options.cfg` compatibility.** Deliberately rejected. `TGConfigMapping.SaveConfigFile`
  dumps the *entire* in-memory map, and SDK code calls
  `App.g_kConfigMapping.SaveConfigFile("Options.cfg")` at times we don't control
  (`sdk/Build/scripts/QuickBattle/QuickBattle.py:1202`, `engine/host_loop.py:5055`).
  Sharing that global means our settings get written by code we don't own. This
  is one of the rare places where BC compatibility is the wrong target.
- **Keybindings.** They already persist to `Keybindings.cfg` via
  `engine/input_map.py:137`. It works and is live-verified. Folding it into
  `settings.json` is a later pure migration, not part of this work.
- **Developer Options.** Documented as off-every-launch by design so production
  combat can never drift; that property is worth more than the convenience.
- **Quick Battle roster, SPV overlay state.** Session state, not preferences.
- **Bootstrap paths.** See "Future: the bootstrap tier" — reserved in the
  schema, read by nothing.

## Architecture

One new module, `engine/settings_store.py`, holding three things.

### 1. `SETTINGS` — the declarative table

One row per persisted setting; the row is the whole spec for that setting.

```python
Setting(key="camera_shake", section="graphics", kind=bool,
        default=lambda ctx: ctx.camera_shake.enabled(),
        apply=lambda ctx, v: ctx.camera_shake.set_enabled(v))
```

`default` is a value *or* a zero-arg callable, because two defaults must be read
live rather than hardcoded: `fov_deg` comes from `director.fov_y_rad`, and
`camera_shake` has a real `enabled()` getter.

`apply` fans out for the three master toggles — `realistic_lighting` drives four
appliers, exactly as `MASTER_TOGGLES` in `configuration_panel.py` does. Masters
persist as the single row the player sees; member effects are never stored
separately.

The ten rows:

| key | section | kind | appliers |
|---|---|---|---|
| `smaa` | graphics | bool | `r.set_smaa_enabled` |
| `dust` | graphics | bool | `r.set_dust_enabled` |
| `fov_deg` | graphics | int (25–55) | `director.set_fov(radians(v))` |
| `improved_space` | graphics | bool | `set_procedural_sky_enabled`, `set_volumetric_nebulae_enabled` |
| `camera_realism` | graphics | bool | `set_hdr_enabled`, `set_filmic_enabled`, `set_motion_blur_enabled`, `set_hdr_lens_flare_enabled` |
| `realistic_lighting` | graphics | bool | `set_rim_enabled`, `set_shadows_enabled`, `set_nebula_lightning_enabled`, `light_emitters.set_enabled` |
| `camera_shake` | graphics | bool | `camera_shake.set_enabled` |
| `subtitles` | gameplay | bool | `crew_speech.set_subtitles_enabled` |
| `disable_annoying_dialogue` | gameplay | bool | `crew_speech.set_annoying_dialogue_disabled` |
| `ai_difficulty` | gameplay | int (0–2) | `App.Game_SetDifficulty` |

### 2. `SettingsStore`

`load()`, `get(key)`, `set(key, value)`, `reset_section(name)` (delete only,
no engine contact). Backed by a JSON
file at `PROJECT_ROOT / "settings.json"`; the constructor takes `path` so tests
never touch the repo.

`set()` writes through immediately — matching `InputMap`, which saves on every
rebind. The file is a few hundred bytes; an immediate write is cheap and
crash-safe. Writes go to a temp file followed by `os.replace`, so a crash
mid-write cannot leave a truncated file.

### 3. Module-level functions

- **`apply_all(store, ctx)`** — walks the table and calls `apply` for each
  **stored** key.
- **`snapshot_for_panel(store, ctx) -> SettingsSnapshot`** — builds the panel's
  display state: stored value where present, the row's `default` (resolved, if
  callable) where absent.
- **`reset_and_apply_section(store, ctx, name) -> dict`** — deletes the section
  via `store.reset_section(name)`, re-applies each row's resolved default, and
  returns `{key: value}` for the panel. Named distinctly from the store's own
  `reset_section` because it also touches the engine.

`ctx` is a small dataclass bundling `r`, `director`, `crew_speech`,
`light_emitters`, `camera_shake`, `App`, so the table's lambdas close over no
globals and the module is testable headless with a fake ctx.

### The load-time rule

**Absent key ⇒ applier is never called.**

A missing or empty `settings.json` therefore leaves the engine on its native
defaults, and boot is byte-identical to today. The registry's `default` is used
only to populate the panel's display snapshot — never to drive an applier.

This is also why per-tab reset **deletes** the section rather than writing
defaults into it: reset genuinely returns the player to first-launch behaviour,
rather than to our transcription of what first-launch behaviour was.

## File format

```json
{
  "version": 1,
  "graphics": { "smaa": true, "fov_deg": 45, "camera_shake": false },
  "gameplay": { "subtitles": false, "ai_difficulty": 1 }
}
```

Sections mirror tabs, so per-tab reset is a section delete.

Unknown keys and unknown sections are **preserved across a save** — known values
are merged over the raw loaded dict. An older build cannot silently eat a newer
build's settings. This matters most for the bootstrap tier below.

Location is the project/executable directory, alongside the existing gitignored
`Options.cfg` and `Keybindings.cfg`. An installed game's directory may be
read-only, which this choice does not handle; the path lives behind a single
resolver function so it can move to a per-user OS config directory later without
touching call sites.

## Boot flow

Inserted at `engine/host_loop.py:7236`, immediately before the panel is
constructed. That is the first point where every applier exists at once —
renderer `r`, `director`, `crew_speech`, `light_emitters`, `camera_shake`, and
`App` — and it is on the production path, not inside the `--developer` block.

```python
store = SettingsStore(); store.load()
apply_all(store, ctx)                                    # stored keys only
configuration_panel = ConfigurationPanel(
    initial_settings = snapshot_for_panel(store, ctx),   # replaces the guesswork
    on_change        = store.set,
    on_reset         = lambda name: reset_and_apply_section(store, ctx, name),
    ... appliers unchanged ...)
```

Settings apply whether or not the player ever opens the panel. This is why
persistence cannot live inside `ConfigurationPanel` itself: a panel-owned load
would only fire on `open()`, so a player who booted straight into a mission
would get camera shake back.

## Panel wiring

Two new constructor params, both defaulting to no-ops so every existing
construction and test keeps working.

- **`on_change(key, value)`** — called at the **end** of each toggle branch,
  after the `setattr`. The ordering mirrors the discipline already in
  `dispatch_event`: appliers run first, local state second, persistence third.
  A raising applier therefore can never write a value the engine isn't on.
- **`on_reset(section) -> dict`** — the new `reset:<section>` action, bound
  host-side to `reset_and_apply_section`. It deletes the section, re-applies
  each row's default, and returns `{key: value}` for the panel to write into
  `_settings`. The panel never imports the store.

The one unavoidable UI change is the two reset rows. `_focusables()` gains
`("ctrl", "reset_graphics")` and `("ctrl", "reset_gameplay")` at the end of each
tab, with matching rows in `native/assets/ui-cef/js/configuration_panel.js` —
already pinned by `test_js_graphics_focusables_match_python`. Reset is per-tab,
not global, so a fat-finger cannot wipe keybindings.

## Failure handling

| Case | Behaviour |
|---|---|
| File missing | Defaults, no applier called, boot identical to today |
| Unparseable JSON | Rename to `settings.json.corrupt`, start clean, `dev_mode.log_swallowed`. Keeps the file for inspection and unblocks the next save |
| Value wrong type / out of range | Coerce via the row's `kind`, clamp (`fov_deg` 25–55, `ai_difficulty` 0–2); on failure treat the key as **absent** |
| `version` newer than ours | Read recognised keys, preserve the rest, do not wipe |
| `version` older than ours | Migration hook; empty today |
| Write fails (read-only dir) | Log once, keep running on in-memory settings |

## Risks to verify during implementation

Both are the kind of thing a green suite will not catch.

1. **`App.Game_SetDifficulty` at boot.** The panel already *reads*
   `Game_GetDifficulty()` at this site, so a game object exists. But QuickBattle
   boot runs `reset_sdk_globals()` and `_QBGame.Initialize` afterwards
   (`engine/host_loop.py:5043`). Whether a difficulty set before that survives it
   is unverified.
2. **Mission swap.** If a swap re-establishes difficulty or renderer state,
   gameplay settings may need re-applying after `_drain_pending_swap`. It is not
   known that it does — this is a check to run, not a fix to design in advance.

Neither blocks the store. Either may add a re-apply call.

## Testing

**`tests/unit/test_settings_store.py`** — pure Python over a temp path:

- Round-trip: `set` → fresh store → `load` → `get`
- **Missing file calls zero appliers.** A recording fake ctx asserts `apply_all`
  invokes nothing. This is the "first launch is byte-identical to today"
  guarantee, and the most important test here
- Corrupt JSON → renamed to `.corrupt`, defaults used, no raise
- Unknown key and unknown section survive a save
- `version` newer than ours → preserved, known keys still read
- `fov_deg: 999` clamps to 55; `ai_difficulty: "banana"` treated as absent
- Read-only directory → `set` does not raise

**Registry coverage test.** Every persisted `SettingsSnapshot` field has a
`SETTINGS` row and vice versa; the three masters' fan-out is pinned against
`MASTER_TOGGLES`. This catches "added a toggle, forgot to persist it" — the same
bug class `test_js_graphics_focusables_match_python` guards on the JS side.

**`tests/unit/test_configuration_panel.py`** — extend: toggling calls
`on_change` once with the right key and value, *after* the applier; a raising
applier does **not** call `on_change`; `reset:graphics` calls `on_reset` and
writes the returned values into `_settings`; a construction omitting both new
params still works.

### Where the tests stop

They cover `apply_all(store, ctx)` with a fake ctx. They do **not** prove the
wiring at `host_loop.py:7236` is correct, that difficulty survives
`_QBGame.Initialize`, or that a mission swap doesn't stomp a setting. Those are
live checks:

1. No `settings.json` → everything reads as today
2. Camera shake and subtitles off, quit, relaunch → both off **before** opening
   the panel (take a hit, trigger a line)
3. FOV to 25, relaunch → 25 on the first frame
4. Reset Graphics → stock; relaunch → still stock
5. Hand-corrupt the file → boots on defaults, `.corrupt` appears
6. Change difficulty, swap missions → still applied (risk 2 above)

Gate is `scripts/check_tests.sh`, both suites. `.gitignore` gains
`/settings.json` and `/settings.json.corrupt`.

## Future: the bootstrap tier

`game/` and `sdk/` are hardcoded today as `PROJECT_ROOT / "game"` and
`PROJECT_ROOT / "sdk"` (`engine/host_loop.py:1829`, `:1886`, and ~25 further
call sites). That is a dev-checkout assumption. A shipped Dauntless must ask the
player where their BC install lives, and that answer has to be readable before
anything else boots.

This design reserves a `paths` section for it and is written so wiring it up
later is additive:

- The schema is versioned, and unknown sections survive a save, so a build
  without paths support cannot destroy a build with it.
- `paths` is documented but read by nothing. No behaviour depends on it yet.
- The file-location resolver is a single function, so moving to a per-user OS
  config directory — which the bootstrap tier will likely want, since an
  installed game directory may be read-only — is one edit.

Deliberately not built now: reading `paths.game_dir` / `paths.sdk_dir` through
to asset resolution touches every `PROJECT_ROOT / "game"` call site plus the C++
side, and the asset path is load-bearing for every live run. Smallest correct
step is to fix the file format now and wire paths as its own piece of work.
