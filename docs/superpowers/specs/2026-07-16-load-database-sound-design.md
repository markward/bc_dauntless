# LoadDatabaseSound* family — design

**Date:** 2026-07-16
**Status:** Approved
**Heatmap driver:** `Game.LoadDatabaseSoundInGroup` — rank 3, 6,440 hits, 34/47 live runs.

## Problem

`Game.LoadDatabaseSoundInGroup` is a `TGObject.__getattr__` `_Stub` no-op. The
SDK's universal pattern is:

```python
if not App.g_kSoundManager.GetSound(name):
    pGame.LoadDatabaseSoundInGroup(pDatabase, name, group[, iLoadFlags])
    if not App.g_kSoundManager.GetSound(name):
        return 0   # bail — no sound, and (MissionLib.py:681) no subtitle either
```

Because the stub registers nothing, every caller takes the bail branch:

- `MissionLib.py:681` — the per-line lazy voice loader (`"LoadedOnDemand"`
  group). Bailing skips the whole sequence build, so the **subtitle is lost
  along with the voice**.
- `Bridge/EngineerCharacterHandlers.py:100–140` — 22 shield-status callouts
  preloaded into group `"Bridge"`.
- `Bridge/Characters/*.py` (Picard.py:224 et al.) — per-character
  order-confirmation sound preloads.

Playback is by registered name (`TGSoundAction` →
`TGSoundManager.PlaySound(name)`), so registration is the whole feature.

## Evidence

- SDK interface is the contract (per Mark). The RE trace of the binary
  (wrapper `0x005F2600` → TGL lookup `0x006D1E70` → TGSound ctor `0x00406CF0`
  → group tag `0x0070B9B0`) confirms semantics: **key→filename resolve is
  exactly `pDatabase.GetFilename(key)`**, the sound registers under its
  *sound name* (not filename), the group is a tag for batch stop/unload, and
  every failure path returns Python `None` with nothing registered. No
  sound-enabled/headless gate exists on this path.
- `App.TGSound_Create(pDatabase.GetFilename(key), key, flags)` at
  MissionLib.py:4744 reproduces the same two steps manually — independent
  confirmation of the resolve step.
- `ScriptObject.LoadDatabaseSound` (MissionLib.py:4742, called on
  Mission/Episode objects) is the same machinery with the object's own stored
  group string and default flags 2.

## Existing pieces (all reused, none changed in contract)

| Piece | Where | Role |
|---|---|---|
| `TGLocalizationDatabase.GetFilename(key)` | `engine/appc/localization.py:194` | TGL key → wav path (`""` when missing) |
| `TGSoundManager.LoadSoundInGroup(path, name, group)` | `engine/audio/tg_sound.py:270` | load + register + group-tag; registers a real-but-unloaded `TGSound` on file-load failure |
| `TGSoundManager.LoadSound(path, name, loadspec)` | `engine/audio/tg_sound.py:253` | load + register; `None` on failure, nothing registered |
| `_resolve_sfx_path` | `engine/audio/tg_sound.py:23` | game-dir-relative wav paths (TGL filenames are game-dir-relative, same as the crew-speech bus already relies on) |

## Design

### 1. Core — `TGSoundManager.LoadDatabaseSoundInGroup(db, name, group, flags=0)`

New method in `engine/audio/tg_sound.py`, next to `LoadSoundInGroup`:

- If `name` is falsy, `db` is `None`/lacks `GetFilename`, or
  `db.GetFilename(name)` returns anything but a non-empty `str` → return
  `None`, **register nothing**. This keeps the SDK bail-gate faithful:
  a missing TGL key means no voice *and no subtitle*, as in BC.
- Otherwise → `return self.LoadSoundInGroup(filename, name, group)`. Its
  existing contract holds: file-load failure still registers an unloaded
  `TGSound` (silent handle), so post-load chains (`SetVolume`,
  `SetSingleShot`) work.
- `flags` is accepted and ignored: our backend decodes the whole file up
  front, so `LS_STREAMED` is moot; positional (`LS_3D`) is never passed by
  these call sites. Documented in the docstring.

### 2. SDK-facing surface (thin delegates)

- `Game.LoadDatabaseSoundInGroup(db, name, group, flags=0)` in
  `engine/core/game.py` next to `LoadSoundInGroup` — late-import the manager
  (same pattern as neighbours), delegate, return its result (TGSound or
  `None`).
- `LoadDatabaseSound(db, name, flags=2)` on `Game`, `Mission`, and `Episode`
  — delegates with `group = self.GetScript()` where the class has it
  (`Mission`), else `""`. An empty group is fine: `PreloadMissionLine`
  reassigns empty-group sounds to the mission script via `SetGroup`.
- `App.TGSound_Create(filename, name, flags=0)` — module function exported
  from `engine/audio/tg_sound.py` through the `App.py` shim, routing to
  `manager.LoadSound(filename, name, flags)`. `None` on failure, nothing
  registered — its only SDK call site is bail-gated on `GetSound`.

### 3. `TGSound.GetGroup` / `SetGroup`

`PreloadMissionLine` calls both on a successfully loaded sound; today they
would raise `AttributeError` (plain class, no `_Stub`). Add:

- `TGSound._group: str = ""` instance tag.
- `LoadSoundInGroup` stamps `snd._group = group` (in addition to the
  manager's `_groups` set, unchanged).
- `SetGroup(group)`: remove the sound's name from its old group set in the
  manager, add to the new one, update the tag. Setting `""` just removes it.
- `GetGroup()` returns the tag (empty string when untagged — falsy, which is
  what the SDK's `if not pSound.GetGroup():` needs).

### 4. Out of scope

- Whatever upstream gap keeps `MissionLib.PreloadSequenceLines` /
  `GetVoiceLinesFromSequence` from reaching `LoadDatabaseSound` in live runs
  (zero hits in 47 runs; suspects are `TGSequence_Cast` /
  `CharacterAction_Cast` behaviour). The lazy `LoadedOnDemand` path fixed
  here self-heals any preload miss at play time. Separate heatmap work.
- Binary-internal fidelity (hashing, NiNode allocation, sound counters,
  min/max distance defaults 360/700) — SDK interface is the contract.

## Testing

TDD (pytest). Use a real `TGLocalizationDatabase` constructed with a
`sounds=` dict as the fake TGL DB. No audio backend in tests, so load
failures exercise the register-unloaded contract.

- Manager core: hit → registered under sound name + member of group +
  `GetGroup()` returns the group; missing key / `None` db / `None` name →
  returns `None` and `GetSound(name)` stays `None`.
- SDK-shape: the exact MissionLib.py:681 gate (`GetSound` → load → `GetSound`
  truthy → `TGSoundAction_Create(name, ...)` path) and the
  `PreloadMissionLine` post-load block (`SetSingleShot(1)`,
  `if not GetGroup(): SetGroup(script)` moves the group).
- Delegates: `Game.LoadDatabaseSoundInGroup`, `Mission.LoadDatabaseSound`
  (group = script name), `App.TGSound_Create` failure → `None`.
- Suite gate: `scripts/check_tests.sh` before merge.

**Verification:** heatmap entry should disappear from the unimplemented
table on the next live run; audible check (bridge officer lines +
shield callouts) is Mark's — no "works" claim before he's heard it.
