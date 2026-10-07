# Dialogue patches — restore cut lines, replace lines

**Status:** built and merged to local main (`bfa75d25`, 2026-10-07); E1M2's reinserted lines and the first `replace` (Felix `E1M2FirstHail6`) live-verified by Mark.

## Goal

Change what BC's mission conversations say **without editing the SDK**:

1. **Insert** lines after an existing scripted line. First use: E1M2's
   supply-transfer exchange, whose replicator lines exist in `E1M2.TGL` with
   voice and `.LIP` files but are never referenced by any SDK script.
2. **Replace** a line's subtitle text, voice file, or both.

## Decisions (Mark, 2026-10-07)

- Patches **always apply**. No toggle; they are part of Dauntless.
- Insertion extends the anchor line (approach B below), not the sequence.
- Data is one hand-edited JSON in the repo, read by the game at runtime, so
  it lives with the runtime assets, not in `tools/` (which holds build-time
  sources such as `dauntless_crew.json`, compiled into a TGL and never read
  by the game).
- Out of scope: mod-supplied patches, inserting *before* a line, anchoring on
  direct `SayLine`/`SpeakLine` calls (54 in Maelstrom vs 3,909 sequenced
  speak actions).

## Data — `native/assets/dialogue/patches.json`

Resolved at use through `paths.project_asset_root()`, like the rest of
`native/assets/`.

Keyed by the TGL the anchor line is read from, so a generic key
(`LoweringShields` in `Bridge Crew General.TGL`) cannot match by accident:

```json
{
  "data/TGL/Maelstrom/Episode 1/E1M2.TGL": {
    "insert_after": {
      "E1M2TransferSupplies2": [{"speaker": "MiscEng/Soams",   "key": "E1M2TransferSupplies2a"}],
      "E1M2TransferSupplies3": [{"speaker": "MiscEng/Soams",   "key": "E1M2TransferSupplies3a"},
                                {"speaker": "bridge/XO",       "key": "E1M2TransferSupplies3b"}],
      "E1M2TransferSupplies4": [{"speaker": "bridge/Engineer", "key": "E1M2TransferSupplies4a"}]
    },
    "replace": {}
  }
}
```

- **TGL path:** game-root-relative, matched case-insensitively with `\` and
  `/` treated alike (scripts spell `.tgl`, files are `.TGL`).
- **`speaker`:** `<set>/<object name>`, looked up with
  `CharacterClass_GetObjectStrict`, as BC scripts do (`bridge/XO` is Saffi,
  `bridge/Engineer` Brex, `MiscEng/Soams` the Haven director on the
  viewscreen).
- **`key`:** read from the anchor's own database by default. An optional
  `"tgl"` names another database (e.g. `data/TGL/Dauntless Crew.tgl` for a
  newly recorded line).
- **`replace` entry:** `{"text": ..., "sound": ...}`, either or both. `sound`
  is game-root-relative and resolves through the replacements overlay, so new
  voice files live under `native/assets/replacements/` like the hazard
  prompts'. A replacement voice mirrors BC's folder with a `.wav` extension
  (`sfx/Maelstrom/Episode 1/Mission 2/E1M2TransferSupplies3.wav`): the
  different extension means it never shadows BC's `.mp3` through the
  overlay, so only the patch entry switches it on, and removing the entry
  brings BC's line back.

Speakers for E1M2 were confirmed by ear: `2a`/`3a` Soams, `3b` Saffi, `4a`
Brex. Restored order: Soams 1, Brex 2, **Soams 2a**, (CheckShields), Soams 3,
**Soams 3a**, **Saffi 3b**, Brex 4, **Brex 4a**, Soams 5. In
`WinWithTransfer` (player reached orbit during the win conversation) Brex's
unconditional "Lowering shields" follows `2a` instead of preceding it.

## Insertion — the anchor line plays the inserts before it completes

`CharacterAction.Completed()` for a speak type (`AT_SAY_LINE`,
`AT_SAY_LINE_AFTER_TURN`, `AT_SPEAK_LINE`, `AT_SPEAK_LINE_NO_FLAP_LIPS`)
checks the patch table for `(its database's TGL, its line key)`. On a hit,
before completing, it builds and plays a `TGSequence` of `AT_SAY_LINE`
actions, one per insert, and completes itself only when that sequence ends.
To the mission script it is one longer line, so every step chained on the
anchor, by `AppendAction` or by an explicit `AddAction(x, pAnchor)`
dependency, waits for the inserts with no change to the sequence.

- **Arguments for inserted actions:** bridge-set speakers get BC's crew form
  `("Captain", 1)`, others the viewscreen form `(None, 0)`, matching how E1M2
  scripts each speaker.
- **Skip (Backspace):** skipping the anchor still plays the inserts (each one
  is its own skippable line, as in BC). `Skip()` already routes to
  `Completed()`.
- **Abort:** an aborted anchor never reaches `Completed()`, so a cancelled
  conversation never starts its inserts. Aborting the anchor *while* its
  inserts play aborts them too.
- **Missing speaker or line:** an insert whose speaker is not present, or
  whose key is not in its database, is skipped with a one-time dev log line;
  the rest still play, and the anchor always completes.
- **Re-entry:** inserts run once per anchor play. A replayed anchor plays
  them again, as the original line would repeat.
- **Hazard prompts:** inserted lines are sequenced speech, so
  `actions.scripted_line_pending` already counts them.

## Replacement — merged into the database at load

`TGLocalizationManager._build_database` applies the patch table's `replace`
entries for that TGL after parsing it: `text` overwrites the string, `sound`
the filename. Lines with a replaced voice have no `.LIP` and get the random
mouth flap (BC's own fallback). A `replace` key not present in the TGL adds
it, which lets an `insert_after` entry point at a line that never existed in
BC (text and sound both required then).

## Validation

A test loads `patches.json` and fails on: an unknown TGL path; an anchor or
insert key missing from its database; a speaker not in `<set>/<name>` form;
a `replace` sound file that does not exist; a malformed entry. Runs in the
normal suite (BC content configured).

The WAV guards in `tests/tools/test_dauntless_dialogue_drift.py` widen to
cover replacement voices: a WAV under `replacements/sfx` must be listed in
`dauntless_crew.json` **or** as a `replace` sound in `patches.json`, and
every listed WAV must pass the native-decoder format check. The
`.gitignore` exception for `replacements/sfx/**/*.wav` already covers both.

## Testing

- Unit: an anchor with inserts completes only after them; explicit
  `AddAction(x, pAnchor)` dependents wait for them; Skip plays inserts;
  Abort does not; missing speaker or key is skipped and the anchor still
  completes; no patch for the TGL leaves behaviour byte-identical.
- Unit: `replace` overrides text and/or sound on load; adds a new key.
- Integration (headless E1M2, extends
  `tests/integration/test_e1m2_supply_transfer.py`): `TransferSupplies` and
  `WinWithTransfer` each speak the restored order above.
- Live: Mark plays E1M2 through the supply transfer, both branches.

## Files

- `native/assets/dialogue/patches.json` (new), `engine/appc/dialogue_patches.py`
  (new: load + validate + lookup, resolved at use).
- `tests/tools/test_dauntless_dialogue_drift.py` (WAV guards accept
  `patches.json` replacement voices).
- `engine/appc/ai.py` (`CharacterAction.Completed` hook).
- `engine/appc/localization.py` (`replace` merge in `_build_database`).
- `docs/engine/dauntless-crew-dialogue.md` (section on patches).
