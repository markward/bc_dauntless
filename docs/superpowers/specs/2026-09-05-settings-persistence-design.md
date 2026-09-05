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

`load()`, `has(section, key)`, `get(section, key)`, `set(section, key, value)`,
`reset_section(name)` (delete only, no engine contact). Section/key addressed
and table-agnostic — it knows nothing about `SETTINGS`. Backed by a JSON
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
- **`set_setting(store, key, value)`** — key-addressed write, looking the
  section up in the table. This is what the panel's `on_change` binds to;
  `SettingsStore.set` alone can't serve, since only the table knows a key's
  section.
- **`reset_and_apply_section(store, ctx, name) -> dict`** — deletes the section
  via `store.reset_section(name)`, re-applies each row's resolved default, and
  returns `{field: value}` keyed by `SettingsSnapshot` **field** name (e.g.
  `smaa_on`), so the panel can `setattr` the result directly. Named distinctly
  from the store's own `reset_section` because it also touches the engine.

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
    on_change        = lambda k, v: set_setting(store, k, v),
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
  each row's default, and returns `{field: value}` for the panel to write into
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

## Survival across QuickBattle init and mission swaps — verified

Every persisted setting must still be in force after `_QBGame.Initialize` and
after every in-process mission swap. Checked against the code rather than
assumed; all ten survive, in three storage classes:

1. **Module globals nothing resets.** `_difficulty` (`engine/core/game.py:235`),
   `_subtitles_enabled` and `_annoying_dialogue_disabled`
   (`engine/appc/crew_speech.py:27`, `:43`). `reset_sdk_globals()` never touches
   any of them, `Game()` construction doesn't, and nothing reloads either
   module. `Game_SetDifficulty` has exactly one caller — the panel applier at
   `host_loop.py:7277`. Note `reset_sdk_globals()` *does* call
   `crew_speech.bus().reset()` on every swap, but that clears channel state
   (active voice, priority, expiry, speaker) and not the two flags, which are
   module-level and separate from the bus instance.
2. **`director.fov_y_rad`** — seeded once from `EXTERIOR_FOV_Y_RAD` at director
   construction (`engine/cameras/director.py:30`) and mutated only by
   `set_fov()`. The director outlives every swap.
3. **Renderer toggles** — C++ renderer state. `reset_sdk_globals()` touches only
   `render_instances.reset()`, which drops the object→render-instance mirror,
   not effect flags.

This is a property of today's reset list, not a structural guarantee.
`reset_sdk_globals`'s own docstring asks that the list be kept "in lockstep with
what the SDK actually mutates", so a future entry could clear one of these and
silently regress persistence to session-only. The testing section pins it.

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

**Swap-survival regression test.** Set the Python-side state to non-default
values — `_difficulty`, `_subtitles_enabled`, `_annoying_dialogue_disabled`,
`director.fov_y_rad`, `camera_shake`, `light_emitters` — call
`reset_sdk_globals()`, assert every one is unchanged. This is what stops a
future addition to the reset list from silently turning persistence back into
session-only state, and nothing else in the suite would catch it.

It cannot cover the four pure-renderer flags (`smaa`, `dust`, and the
`improved_space` / `camera_realism` members), which live in C++ state with no
headless getter. Their survival rests on the argument above — that
`reset_sdk_globals()` touches only `render_instances` — plus live check 6.

**`tests/unit/test_configuration_panel.py`** — extend: toggling calls
`on_change` once with the right key and value, *after* the applier; a raising
applier does **not** call `on_change`; `reset:graphics` calls `on_reset` and
writes the returned values into `_settings`; a construction omitting both new
params still works.

### Where the tests stop

They cover `apply_all(store, ctx)` with a fake ctx and `reset_sdk_globals()`
survival. They do **not** prove the wiring at `host_loop.py:7236` is correct —
that a real boot applies real settings to a real renderer. That is a live
check:

1. No `settings.json` → everything reads as today
2. Camera shake and subtitles off, quit, relaunch → both off **before** opening
   the panel (take a hit, trigger a line)
3. FOV to 25, relaunch → 25 on the first frame
4. Reset Graphics → stock; relaunch → still stock
5. Hand-corrupt the file → boots on defaults, `.corrupt` appears
6. Change difficulty, subtitles **and a renderer toggle**, swap missions → all
   three still applied. This is the only check that covers the renderer flags at
   all, since no headless test can read them

Gate is `scripts/check_tests.sh`, both suites. `.gitignore` gains
`/settings.json` and `/settings.json.corrupt`.

## Future: the bootstrap tier

**Built 2026-09-05.** See
`docs/superpowers/specs/2026-09-05-bc-path-resolution-design.md`.
`engine/paths.py` owns the `paths` section; `game/` and `sdk/` are no longer
hardcoded to the project root.
